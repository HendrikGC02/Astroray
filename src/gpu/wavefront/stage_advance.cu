// stage_advance.cu — pkg55-B' Session N+6
//
// Full one-bounce wavefront advance: the device twin of the CPU shared
// kernel src/cpu/wavefront/path_kernel.cpp::advance_one_bounce. This is the
// kernel that makes the GPU wavefront produce IMAGES, unlocking the
// final-image gate (the per-stage N+3..N+5 gates compare only
// deterministic-given-stage fields; BSDF/NEE sampling correctness is owned
// by the image gate per spec §4.2 design decision #2).
//
// Stage order mirrors the CPU kernel EXACTLY (the final-image gate is
// sensitive to it): intersect -> env-miss accumulate -> emissive accumulate
// (gated bounce==0||wasSpecular, path ends) -> NEE (skipped on delta) ->
// Russian roulette (bounce > 3) -> BSDF sample -> throughput update + clamp
// -> next ray.
//
// RNG convention (spec §4.2 design decision #2, the N+3..N+5 precedent):
// where the CPU seeds a fresh std::mt19937 from rng.UniformUInt32() (NEE
// light sampling, BSDF sampling), the GPU draws the SAME seed from the same
// WavefrontRNG dimension (alignment preserved) and seeds a LOCAL curandState
// from it. Same architecture, different generator — independent MC samples
// with matched dimension consumption. This lets the kernel call the
// UNMODIFIED megakernel-proven device functions (gpu_material_sample_spectral,
// sampleDirectSpectralMW) — one generator of the sampling math on GPU, never
// a second transcription (design decision #9 applied to the GPU side).
//
// Session N+6 scope notes (documented divergences, all out of the gate
// scene's reach):
//   - Static geometry only: motionVerts/TLAS passed null (pkg88/pkg114
//     wavefront integration is a later session).
//   - The MW kernel's non-visible-band profile override block is NOT
//     replicated (gpu_profile_reflectance is TU-local to the MW kernel);
//     visible-band scenes are unaffected. Non-visible wavefront bands are a
//     later session.
//   - NEE uses sampleDirectSpectralMW (power-CDF GLight + solid-angle
//     sampling + power-heuristic MIS) — the same algorithm the CPU
//     wavefront's LightList::sample NEE mirrors.
//
// References:
//   - CPU mirror: src/cpu/wavefront/path_kernel.cpp::advance_one_bounce.
//   - Cycles intern/cycles/kernel/integrator/shade_surface.h (Apache-2.0) —
//     the wavefront shade-stage structure this program mirrors.
//   - Laine, Karras, Aila 2013 (HPG) — wavefront scheduling.

#include "astroray/gpu_wavefront_state.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"
#include "astroray/gpu_bvh.h"
#include "astroray/gpu_env_spectral.cuh"
#include "astroray/sampling/wavefront_rng_device.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdio>
#include <stdexcept>

// pkg55-B' template-RNG arc: gpu_rng_uniform overload so the templated
// material/NEE samplers (gpu_materials.h, gpu_nee.cuh) draw directly from
// the per-path WavefrontRNG (PCG32) stream. Defined in namespace astroray
// so ADL finds it at template instantiation.
namespace astroray {
__device__ inline float gpu_rng_uniform(WavefrontRNG* rng) {
    return rng->Uniform();
}
}  // namespace astroray
using astroray::gpu_rng_uniform;

// pkg55-B' shadow stage: shared NEE thirds (header-inline since the
// template-RNG arc — one compiled implementation in both TUs).
#include "../gpu_nee.cuh"

// Non-inline XYZ wrapper exported by multiwavelength_kernel.cu (Session N+6)
// — spectrumToXYZ itself is TU-local inline over the constant CMF tables.
__device__ GVec3 gpu_spectrum_to_xyz(
    const GSampledSpectrum& s, const GSampledWavelengths& wl);

// Per-slot init from stage_init.cu (N+7 part 4, rdc-linked) — one generator
// of the init draws shared with stageInitKernel.
namespace astroray { namespace wavefront {
__device__ void initPathSlot(
    int slot, int pixel, int sample_idx,
    GPUWavefrontState& state,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed);
} }

namespace astroray::wavefront {

namespace {

constexpr int kRRDepth = 3;  // mirrors CPU path_kernel.cpp kRRDepth

}  // namespace

// GMAT_LAMBERTIAN=0 .. GMAT_CLOSURE_GRAPH=6 (gpu_types.h GMaterialType).
constexpr int G_WF_NUM_MAT_TYPES = 7;

// pkg55-B' shadow stage: NEE park SoA layout (field-major: field*capacity+idx).
// Float fields: 0-2 origin, 3-5 wi, 6 maxDist, 7-10 the pre-resolved
// contribution throughput*f*wt/(lightPdf+eps) — everything except the
// emission spectrum, which needs the trace result (sphere frontFace).
// Int fields: 0 lightMatId, 1 isSphere. Mirrors Cycles' design: bsdf_eval
// is computed in shade BEFORE queuing intersect_shadow
// (kernel/integrator/shade_surface.h, integrate_surface_direct_light).
constexpr int G_WF_NEE_FLOATS = 11;
constexpr int G_WF_NEE_INTS   = 2;

// ---------------------------------------------------------------------------
// N+7 part 2: the one-bounce advance body, shared by the dense kernel
// (stageAdvanceKernel) and the queued kernel (stageAdvanceQueuedKernel) --
// one generator of the per-bounce math (design decision #9); the queue is
// purely a scheduling change (Laine 2013 sec. 4 compaction; Cycles X uses
// the same dense-active-queue structure in its integrator queues).
// Returns true when the path survives into the next bounce.
// N+7 part 3: the advance body is split at the post-emissive boundary into
// intersectPathSlot (intersect + env-miss + emissive; consumes NO RNG
// dimensions, so the cut preserves the RNG stream exactly) and
// shadePathSlot (NEE + RR + BSDF). advancePathSlot composes the two, so the
// dense and flat-queued kernels and the staged kernels all run the SAME
// compiled halves -- one generator (design decision #9).
//
// intersectPathSlot returns -1 when the path died, else the GMaterialType
// of the hit (0..GMAT_CLOSURE_GRAPH) for shade-queue bucketing. The hit
// record is parked in GPUWavefrontHitBuffers SoA at the slot index.
__device__ int intersectPathSlot(
    int idx,
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces)
{
    const int bounce = state.bounce[idx];

    // ---- Reconstruct live path state from SoA (already-normalized ray
    // direction restored verbatim — the Phase A.1 ulp rule).
    GRay ray;
    ray.origin = GVec3(state.ray_origin_x[idx], state.ray_origin_y[idx],
                       state.ray_origin_z[idx]);
    ray.direction = GVec3(state.ray_direction_x[idx], state.ray_direction_y[idx],
                          state.ray_direction_z[idx]);

    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[idx];
    lambdas.lambda[1] = state.lambda_1[idx];
    lambdas.lambda[2] = state.lambda_2[idx];
    lambdas.lambda[3] = state.lambda_3[idx];
    lambdas.pdf[0] = state.lambda_pdf_0[idx];
    lambdas.pdf[1] = state.lambda_pdf_1[idx];
    lambdas.pdf[2] = state.lambda_pdf_2[idx];
    lambdas.pdf[3] = state.lambda_pdf_3[idx];

    GSampledSpectrum throughput;
    throughput.v[0] = state.throughput_0[idx];
    throughput.v[1] = state.throughput_1[idx];
    throughput.v[2] = state.throughput_2[idx];
    throughput.v[3] = state.throughput_3[idx];

    GSampledSpectrum color;
    color.v[0] = state.color_0[idx];
    color.v[1] = state.color_1[idx];
    color.v[2] = state.color_2[idx];
    color.v[3] = state.color_3[idx];

    bool wasSpecular = state.was_specular[idx] != 0;

    // ---- Intersect (CPU: bvh->hit; ray direction NOT renormalized).
    // This half consumes no RNG dimensions; state.rng_dimension is untouched.
    GHitRecord rec;
    bool hit = gpu_bvh_hit(bvhNodes, prims, tris, spheres,
                           ray, 0.001f, 1e30f, rec, /*motionVerts=*/nullptr);

    if (!hit) {
        // ---- Env-map miss (CPU path_kernel: worldMaxBounces gate; the
        // shared helper mirrors EnvironmentMap::evalSpectral).
        if (bounce <= worldMaxBounces) {
            GVec3 dir = ray.direction.normalized();
            GSampledSpectrum envSpec = gpu_env_miss_spectral(
                envMap, backgroundColor, hasBackgroundColor, dir, lambdas);
            color += throughput * envSpec;
            state.color_0[idx] = color.v[0];
            state.color_1[idx] = color.v[1];
            state.color_2[idx] = color.v[2];
            state.color_3[idx] = color.v[3];
        }
        state.path_alive[idx] = 0;
        return -1;
    }

    const ::GMaterial& mat = materials[rec.materialId];

    // ---- Emission (gated on camera ray or post-specular bounce; path ends).
    GSampledSpectrum Le = gpu_material_emitted_spectral(mat, rec.frontFace, lambdas);
    if (Le.maxValue() > 0.f) {
        if (bounce == 0 || wasSpecular) {
            color += throughput * Le;
            state.color_0[idx] = color.v[0];
            state.color_1[idx] = color.v[1];
            state.color_2[idx] = color.v[2];
            state.color_3[idx] = color.v[3];
        }
        state.path_alive[idx] = 0;
        return -1;
    }

    // ---- Park the hit record in SoA for the shade stage.
    hitBufs.hit_t[idx]           = rec.t;
    hitBufs.hit_point_x[idx]     = rec.point.x;
    hitBufs.hit_point_y[idx]     = rec.point.y;
    hitBufs.hit_point_z[idx]     = rec.point.z;
    hitBufs.hit_normal_x[idx]    = rec.normal.x;
    hitBufs.hit_normal_y[idx]    = rec.normal.y;
    hitBufs.hit_normal_z[idx]    = rec.normal.z;
    hitBufs.hit_tangent_x[idx]   = rec.tangent.x;
    hitBufs.hit_tangent_y[idx]   = rec.tangent.y;
    hitBufs.hit_tangent_z[idx]   = rec.tangent.z;
    hitBufs.hit_bitangent_x[idx] = rec.bitangent.x;
    hitBufs.hit_bitangent_y[idx] = rec.bitangent.y;
    hitBufs.hit_bitangent_z[idx] = rec.bitangent.z;
    hitBufs.hit_material_id[idx] = rec.materialId;
    hitBufs.hit_prim_id[idx]     = rec.primId;
    hitBufs.hit_front_face[idx]  = rec.frontFace ? 1 : 0;
    hitBufs.hit_is_delta[idx]    = rec.isDelta ? 1 : 0;
    hitBufs.hit_valid[idx]       = 1;
    return (int)mat.type;
}

// Shade half: NEE + RR + BSDF over the parked hit record. Returns true when
// the path survives into the next bounce.
// nee_f/nee_i/shadow_queue/shadow_count non-null => DEFER the NEE shadow
// trace + resolve to the dedicated shadow stage (park the sample + wo +
// throughput, enqueue the slot). Null => immediate occlude+resolve inline
// (the flat/dense schedulings keep their original single-kernel behavior).
__device__ bool shadePathSlot(
    int idx,
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    int               max_depth,
    float*            nee_f, int* nee_i,
    int*              shadow_queue, int* shadow_count, int nee_capacity)
{
    const int bounce = state.bounce[idx];

    GRay ray;
    ray.direction = GVec3(state.ray_direction_x[idx], state.ray_direction_y[idx],
                          state.ray_direction_z[idx]);

    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[idx];
    lambdas.lambda[1] = state.lambda_1[idx];
    lambdas.lambda[2] = state.lambda_2[idx];
    lambdas.lambda[3] = state.lambda_3[idx];
    lambdas.pdf[0] = state.lambda_pdf_0[idx];
    lambdas.pdf[1] = state.lambda_pdf_1[idx];
    lambdas.pdf[2] = state.lambda_pdf_2[idx];
    lambdas.pdf[3] = state.lambda_pdf_3[idx];

    GSampledSpectrum throughput;
    throughput.v[0] = state.throughput_0[idx];
    throughput.v[1] = state.throughput_1[idx];
    throughput.v[2] = state.throughput_2[idx];
    throughput.v[3] = state.throughput_3[idx];

    GSampledSpectrum color;
    color.v[0] = state.color_0[idx];
    color.v[1] = state.color_1[idx];
    color.v[2] = state.color_2[idx];
    color.v[3] = state.color_3[idx];

    WavefrontRNG rng(state.rng_pixel[idx], state.rng_sample[idx],
                     state.rng_seed[idx]);
    rng.setDimension(state.rng_dimension[idx]);

    bool wasSpecular = state.was_specular[idx] != 0;

    // ---- Reconstruct the hit record parked by intersectPathSlot.
    GHitRecord rec;
    rec.t          = hitBufs.hit_t[idx];
    rec.point      = GVec3(hitBufs.hit_point_x[idx], hitBufs.hit_point_y[idx],
                           hitBufs.hit_point_z[idx]);
    rec.normal     = GVec3(hitBufs.hit_normal_x[idx], hitBufs.hit_normal_y[idx],
                           hitBufs.hit_normal_z[idx]);
    rec.tangent    = GVec3(hitBufs.hit_tangent_x[idx], hitBufs.hit_tangent_y[idx],
                           hitBufs.hit_tangent_z[idx]);
    rec.bitangent  = GVec3(hitBufs.hit_bitangent_x[idx], hitBufs.hit_bitangent_y[idx],
                           hitBufs.hit_bitangent_z[idx]);
    rec.materialId = hitBufs.hit_material_id[idx];
    rec.primId     = hitBufs.hit_prim_id[idx];
    rec.frontFace  = hitBufs.hit_front_face[idx] != 0;
    rec.isDelta    = hitBufs.hit_is_delta[idx] != 0;

    const ::GMaterial& mat = materials[rec.materialId];

    GVec3 wo = (ray.direction * -1.0f).normalized();

    // ---- NEE (skipped on delta lobes). CPU draws light_seed -> mt19937;
    // GPU twin draws the same dimension -> local curandState (see header).
    // The light_seed draw is gated EXACTLY like the CPU (path_kernel.cpp:230,
    // !isDelta && !lights.empty()) so the RNG dimension stream stays keyed
    // identically even when all lights have zero power (pkg98 N+6 review
    // finding); only the sampling CALL is guarded on totalLightPower — the
    // CPU's lights.sample returns pdf<=0 there and contributes nothing.
    // pkg55-B' template-RNG arc (CONVENTION AMENDMENT to spec sec. 4.2
    // decision #2): the wavefront now draws its NEE/BSDF sampling uniforms
    // DIRECTLY from the per-path PCG32 stream instead of seeding throwaway
    // curandStates from drawn seeds (2x XORWOW curand_init per bounce was
    // the last wavefront-only cost vs the megakernel's one init per path).
    // Per-bounce dimension counts now vary by branch (CPU keeps mt19937
    // sub-streams); the per-stage gates compare only deterministic-given-
    // stage fields and the final-image gates remain the sampling oracle.
    if (!rec.isDelta && numLights > 0) {
        if (totalLightPower > 0.f) {
            GNEESample s = gpu_nee_sample(rec, prims, tris, spheres,
                                          lights, numLights, totalLightPower,
                                          lightTree, &rng);
            if (s.valid) {
                if (nee_f != nullptr) {
                    // Defer the TRACE + emission to the shadow stage; the
                    // BSDF eval/pdf/MIS happen HERE where the material code
                    // already lives (Cycles shade_surface.h ordering). The
                    // original lazy post-trace eval order is a pure-math
                    // reorder: identical output, evals paid on occluded
                    // samples in exchange for a lean ~100-reg shadow kernel
                    // (measured tradeoff per the blueprint).
                    GSampledSpectrum f_spec = gpu_material_eval_spectral(
                        mat, rec, wo, s.wi, lambdas);
                    if (f_spec.maxValue() > 0.f) {
                        float bsdfPdf = gpu_material_pdf(mat, rec, wo, s.wi);
                        // Power heuristic (Veach 1997) — mirrors
                        // gpu_mw_powerHeuristic in the MW TU.
                        float a2 = s.lightPdf * s.lightPdf;
                        float b2 = bsdfPdf * bsdfPdf;
                        float wt = a2 / (a2 + b2 + 1e-8f);
                        float scale = wt / (s.lightPdf + 0.001f);
                        nee_f[ 0 * nee_capacity + idx] = s.origin.x;
                        nee_f[ 1 * nee_capacity + idx] = s.origin.y;
                        nee_f[ 2 * nee_capacity + idx] = s.origin.z;
                        nee_f[ 3 * nee_capacity + idx] = s.wi.x;
                        nee_f[ 4 * nee_capacity + idx] = s.wi.y;
                        nee_f[ 5 * nee_capacity + idx] = s.wi.z;
                        nee_f[ 6 * nee_capacity + idx] = s.maxDist;
                        nee_f[ 7 * nee_capacity + idx] = throughput.v[0] * f_spec.v[0] * scale;
                        nee_f[ 8 * nee_capacity + idx] = throughput.v[1] * f_spec.v[1] * scale;
                        nee_f[ 9 * nee_capacity + idx] = throughput.v[2] * f_spec.v[2] * scale;
                        nee_f[10 * nee_capacity + idx] = throughput.v[3] * f_spec.v[3] * scale;
                        nee_i[ 0 * nee_capacity + idx] = s.lightMatId;
                        nee_i[ 1 * nee_capacity + idx] = s.isSphere;
                        int qslot = atomicAdd(shadow_count, 1);
                        shadow_queue[qslot] = idx;
                    }
                } else {
                    // Immediate (flat/dense schedulings): original behavior.
                    GNEEOcclusion occ = gpu_nee_occlude(
                        s, /*tlas=*/nullptr, /*instances=*/nullptr,
                        /*blas=*/nullptr, bvhNodes, prims, tris, spheres,
                        /*time=*/0.0f, /*motionVerts=*/nullptr);
                    if (!occ.occluded) {
                        GSampledSpectrum nee = gpu_nee_resolve(
                            rec, wo, lambdas, materials, s,
                            s.isSphere ? (occ.frontFace != 0) : true);
                        color += throughput * nee;
                    }
                }
            }
        }
    }

    // ---- Russian roulette on luminance of throughput's XYZ (bounce > 3).
    if (bounce > kRRDepth) {
        GVec3 thrXYZ = gpu_spectrum_to_xyz(throughput, lambdas);
        float p = fminf(0.95f, fmaxf(0.0f, thrXYZ.y));
        float rr_u = rng.Uniform();
        bool survived = (rr_u <= p);
        if (!survived) {
            state.color_0[idx] = color.v[0];
            state.color_1[idx] = color.v[1];
            state.color_2[idx] = color.v[2];
            state.color_3[idx] = color.v[3];
            state.path_alive[idx] = 0;
            state.rng_dimension[idx] = rng.dimension();
            return false;
        }
        if (p > 0.0f) throughput *= (1.0f / p);
    }

    // ---- BSDF sampling via the templated megakernel material dispatch
    // (all 7 GMAT types + closure graphs), drawing directly from the
    // per-path PCG32 stream (template-RNG arc; see the NEE note above).
    GBSDFSample bss = gpu_material_sample_spectral(mat, rec, wo, lambdas, &rng);
    if (bss.pdf <= 0.0f) {
        state.color_0[idx] = color.v[0];
        state.color_1[idx] = color.v[1];
        state.color_2[idx] = color.v[2];
        state.color_3[idx] = color.v[3];
        state.path_alive[idx] = 0;
        state.rng_dimension[idx] = rng.dimension();
        return false;
    }
    wasSpecular = bss.isDelta;
    throughput *= bss.fSpectral * (1.0f / (bss.pdf + 0.001f));

    // ---- Throughput clamp (CPU: maxC > 10 -> scale to 10).
    float maxC = throughput.maxValue();
    if (maxC > 10.0f) throughput *= (10.0f / maxC);

    // ---- Advance ray. Single normalization of the BSDF direction (the
    // Phase A.1 rule: normalize HERE, store verbatim, never renormalize at
    // the SoA boundary).
    GVec3 nextDir = bss.wi.normalized();

    // ---- SoA write-back.
    state.ray_origin_x[idx] = rec.point.x;
    state.ray_origin_y[idx] = rec.point.y;
    state.ray_origin_z[idx] = rec.point.z;
    state.ray_direction_x[idx] = nextDir.x;
    state.ray_direction_y[idx] = nextDir.y;
    state.ray_direction_z[idx] = nextDir.z;
    state.throughput_0[idx] = throughput.v[0];
    state.throughput_1[idx] = throughput.v[1];
    state.throughput_2[idx] = throughput.v[2];
    state.throughput_3[idx] = throughput.v[3];
    state.color_0[idx] = color.v[0];
    state.color_1[idx] = color.v[1];
    state.color_2[idx] = color.v[2];
    state.color_3[idx] = color.v[3];
    state.was_specular[idx] = wasSpecular ? 1 : 0;
    state.rng_dimension[idx] = rng.dimension();

    int next_bounce = bounce + 1;
    state.bounce[idx] = next_bounce;
    if (next_bounce >= max_depth) {
        state.path_alive[idx] = 0;
        return false;
    }
    return true;
}

// Dense (unqueued) advance. NOTE (N+7 part 3): the render driver now uses
// the STAGED pair (stageIntersectQueuedKernel + stageShadeBucketedKernel);
// BOTH this dense form AND the flat-queued stageAdvanceQueuedKernel below
// are currently caller-less. They are RETAINED INTENTIONALLY as the
// reference schedulings (all three run the same advancePathSlot halves --
// one generator) for part-4 path-regeneration equivalence checks and as
// fallbacks; revisit retention when part 4 lands.
//
// Composition wrapper -- the flat (unstaged) scheduling. Dense and
// flat-queued kernels run EXACTLY intersect-half + shade-half back to back.
__device__ bool advancePathSlot(
    int idx,
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth)
{
    int matType = intersectPathSlot(idx, state, hitBufs, bvhNodes, prims, tris,
                                    spheres, materials, envMap, backgroundColor,
                                    hasBackgroundColor, worldMaxBounces);
    if (matType < 0) return false;
    return shadePathSlot(idx, state, hitBufs, bvhNodes, prims, tris, spheres,
                         materials, lights, numLights, totalLightPower,
                         lightTree, max_depth,
                         /*nee_f=*/nullptr, /*nee_i=*/nullptr,
                         /*shadow_queue=*/nullptr, /*shadow_count=*/nullptr,
                         /*nee_capacity=*/0);
}

__global__ void stageAdvanceKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= state.num_active) return;
    if (state.path_alive[idx] == 0) return;
    advancePathSlot(idx, state, hitBufs, bvhNodes, prims, tris, spheres, materials,
                    lights, numLights, totalLightPower, lightTree, envMap,
                    backgroundColor, hasBackgroundColor, worldMaxBounces,
                    max_depth);
}

// ---------------------------------------------------------------------------
// N+7 part 2: queued advance + compaction.
//
// queue_in holds the slot indices of paths alive at this bounce, densely
// packed; *count_in is its length (device-side -- the host never reads it,
// preserving the part-1 zero-sync driver). Survivors append their slot to
// queue_out via atomicAdd on *count_out. Thread blocks beyond the active
// count retire immediately, so later bounces only pay for live paths
// (Laine 2013 sec. 4: compaction keeps warps dense as paths die).
// ---------------------------------------------------------------------------
__global__ void stageAdvanceQueuedKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const int* queue_in, const int* count_in,
    int* queue_out, int* count_out,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= *count_in) return;
    int idx = queue_in[i];
    bool alive = advancePathSlot(idx, state, hitBufs, bvhNodes, prims, tris, spheres,
                                 materials, lights, numLights, totalLightPower,
                                 lightTree, envMap, backgroundColor,
                                 hasBackgroundColor, worldMaxBounces, max_depth);
    if (alive) {
        int slot = atomicAdd(count_out, 1);
        queue_out[slot] = idx;
    }
}

// ---------------------------------------------------------------------------
// pkg55-B' shadow stage: lean occlusion + resolve over the parked NEE
// samples (Laine 2013's dedicated shadow-ray stage). No sampling RNG, no
// BSDF-sampling dispatch — just the trace + the lazy material evals the
// original ran post-trace. Contribution adds into color (one entry per
// slot per pass: non-atomic).
// ---------------------------------------------------------------------------
__global__ void stageShadowKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const float* nee_f, const int* nee_i,
    const int* shadow_queue, const int* shadow_count, int nee_capacity,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= *shadow_count) return;
    int idx = shadow_queue[i];

    GNEESample s{};
    s.origin     = GVec3(nee_f[0 * nee_capacity + idx],
                         nee_f[1 * nee_capacity + idx],
                         nee_f[2 * nee_capacity + idx]);
    s.wi         = GVec3(nee_f[3 * nee_capacity + idx],
                         nee_f[4 * nee_capacity + idx],
                         nee_f[5 * nee_capacity + idx]);
    s.maxDist    = nee_f[6 * nee_capacity + idx];
    s.lightMatId = nee_i[0 * nee_capacity + idx];
    s.isSphere   = nee_i[1 * nee_capacity + idx];
    s.valid      = 1;

    GNEEOcclusion occ = gpu_nee_occlude(
        s, /*tlas=*/nullptr, /*instances=*/nullptr, /*blas=*/nullptr,
        bvhNodes, prims, tris, spheres, /*time=*/0.0f, /*motionVerts=*/nullptr);
    if (occ.occluded) return;

    // Emission upsample only (the BSDF/MIS parts were pre-resolved in the
    // shade stage); lambdas from the slot's live spectral state.
    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[idx];
    lambdas.lambda[1] = state.lambda_1[idx];
    lambdas.lambda[2] = state.lambda_2[idx];
    lambdas.lambda[3] = state.lambda_3[idx];
    lambdas.pdf[0] = state.lambda_pdf_0[idx];
    lambdas.pdf[1] = state.lambda_pdf_1[idx];
    lambdas.pdf[2] = state.lambda_pdf_2[idx];
    lambdas.pdf[3] = state.lambda_pdf_3[idx];

    bool lightFront = s.isSphere ? (occ.frontFace != 0) : true;
    GSampledSpectrum L_spec = gpu_material_emitted_spectral(
        materials[s.lightMatId], lightFront, lambdas);
    if (L_spec.maxValue() <= 0.f) return;

    state.color_0[idx] += nee_f[ 7 * nee_capacity + idx] * L_spec.v[0];
    state.color_1[idx] += nee_f[ 8 * nee_capacity + idx] * L_spec.v[1];
    state.color_2[idx] += nee_f[ 9 * nee_capacity + idx] * L_spec.v[2];
    state.color_3[idx] += nee_f[10 * nee_capacity + idx] * L_spec.v[3];
}

// Fills queue with 0..n-1 and *count = n (bounce-0 population).
__global__ void stageQueueIotaKernel(int* queue, int* count, int n)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    queue[i] = i;
    if (i == 0) *count = n;
}

// ---------------------------------------------------------------------------
// N+7 part 3: staged scheduling -- intersect stage buckets surviving paths
// by material type into per-type shade queues (fixed stride `capacity` per
// bucket), then ONE shade launch covers all buckets with warp-coherent
// material types (thread i -> bucket i/capacity). This is the sort-by-
// material dispatch of Laine 2013 sec. 5 / Cycles X shader sorting, realized
// as bucketed atomic append instead of a radix sort (7 types only).
// ---------------------------------------------------------------------------
__global__ void stageIntersectQueuedKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const int* queue_in, const int* count_in,
    int* shade_queues,     // NUM_TYPES * capacity ints, bucket m at m*capacity
    int* shade_counts,     // NUM_TYPES ints
    int  capacity,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= *count_in) return;
    int idx = queue_in[i];
    // N+7 part 4: dead-slot guard. Part-3 flat queues are guaranteed-alive
    // (no-op there); the regeneration driver iterates a dense identity
    // queue where exhausted slots stay dead.
    if (state.path_alive[idx] == 0) return;
    int matType = intersectPathSlot(idx, state, hitBufs, bvhNodes, prims, tris,
                                    spheres, materials, envMap, backgroundColor,
                                    hasBackgroundColor, worldMaxBounces);
    if (matType < 0) return;
    if (matType >= G_WF_NUM_MAT_TYPES) matType = G_WF_NUM_MAT_TYPES - 1;
    int slot = atomicAdd(&shade_counts[matType], 1);
    shade_queues[matType * capacity + slot] = idx;
}

__global__ void stageShadeBucketedKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const int* shade_queues, const int* shade_counts, int capacity,
    int* queue_out, int* count_out,
    float* nee_f, int* nee_i, int* shadow_queue, int* shadow_count,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    int               max_depth)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    int bucket = i / capacity;
    int pos    = i - bucket * capacity;
    if (bucket >= G_WF_NUM_MAT_TYPES) return;
    if (pos >= shade_counts[bucket]) return;
    int idx = shade_queues[bucket * capacity + pos];
    bool alive = shadePathSlot(idx, state, hitBufs, bvhNodes, prims, tris,
                               spheres, materials, lights, numLights,
                               totalLightPower, lightTree, max_depth,
                               nee_f, nee_i, shadow_queue, shadow_count,
                               capacity);
    if (alive) {
        int slot = atomicAdd(count_out, 1);
        queue_out[slot] = idx;
    }
}

// ---------------------------------------------------------------------------
// pkg55-B' Session N+7: device-side per-sample XYZ accumulation.
//
// NOTE (N+7 part 4): the render driver now accumulates at path death inside
// stageRegenKernel; this per-round dense form is caller-less and RETAINED
// as the reference accumulation for scheduling-equivalence checks (see the
// dense/flat advance kernels' retention note).
//
// The N+6 driver downloaded 12 SoA arrays per SAMPLE round and accumulated
// XYZ on the host — measured at ~185 ms host overhead per 256x64spp render
// (vs ~115 ms of kernel work). This kernel replaces all of that with one
// device-side pass per sample round: radiance -> XYZ (same cross-TU
// gpu_spectrum_to_xyz the RR stage uses, so the CMF integration is the one
// generator) -> the CPU driver's lum>20 firefly clamp -> += into a float3
// accumulator (one slot per pixel; the N+6/N+7 driver maps slot==pixel).
// The final image is downloaded ONCE per render.
//
// Mirrors src/cpu/wavefront/cpu_wavefront_driver.cpp accumulation exactly
// (float accumulation, clamp BEFORE accumulate, /samples + exposure + sRGB
// stay host-side at the single final conversion).
// ---------------------------------------------------------------------------
__global__ void stageAccumulateXYZKernel(
    GPUWavefrontState state,
    float* accum_xyz)   // 3 floats per slot
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= state.num_active) return;

    GSampledSpectrum rad;
    rad.v[0] = state.color_0[idx];
    rad.v[1] = state.color_1[idx];
    rad.v[2] = state.color_2[idx];
    rad.v[3] = state.color_3[idx];

    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[idx];
    lambdas.lambda[1] = state.lambda_1[idx];
    lambdas.lambda[2] = state.lambda_2[idx];
    lambdas.lambda[3] = state.lambda_3[idx];
    lambdas.pdf[0] = state.lambda_pdf_0[idx];
    lambdas.pdf[1] = state.lambda_pdf_1[idx];
    lambdas.pdf[2] = state.lambda_pdf_2[idx];
    lambdas.pdf[3] = state.lambda_pdf_3[idx];

    GVec3 xyz = gpu_spectrum_to_xyz(rad, lambdas);

    // Per-sample firefly clamp on XYZ.Y (mirrors the CPU wavefront driver).
    float lum = xyz.y;
    if (lum > 20.0f) {
        xyz.x *= (20.0f / lum);
        xyz.y = 20.0f;
        xyz.z *= (20.0f / lum);
    }

    accum_xyz[idx * 3 + 0] += xyz.x;
    accum_xyz[idx * 3 + 1] += xyz.y;
    accum_xyz[idx * 3 + 2] += xyz.z;
}

void launchStageAccumulateXYZ(
    GPUWavefrontState& state,
    float* d_accum_xyz)
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_accumulate_n7",
            (const void*)stageAccumulateXYZKernel, blocks, threads);
        stageAccumulateXYZKernel<<<blocks, threads>>>(state, d_accum_xyz);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_accumulate launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

void launchStageAdvance(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const ::GMaterial* d_materials,
    const ::GLight*    d_lights, int num_lights, float total_light_power,
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth,
    bool              sync)
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_advance_n6",
            (const void*)stageAdvanceKernel, blocks, threads);
        stageAdvanceKernel<<<blocks, threads>>>(
            state, hitBufs, d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
            d_lights, num_lights, total_light_power, lightTree,
            envMap, backgroundColor, hasBackgroundColor,
            worldMaxBounces, max_depth);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_advance launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        // pkg55-B' N+7: sync=false defers the device sync to the caller
        // (the N+6 per-launch sync was measured at ~185 ms of host overhead
        // per 256^2x64spp render). Same-stream launches are serialized by
        // CUDA, so correctness is unchanged; runtime errors surface at the
        // caller's sync. As of N+7 part 2 this dense launcher has no in-tree
        // caller (see kernel note above); the default sync=true preserves
        // localized-error semantics for any future direct use.
        if (sync) {
            cudaError_t syncErr = cudaDeviceSynchronize();
            if (syncErr != cudaSuccess) {
                std::fprintf(stderr, "stage_advance runtime error: %s\n",
                             cudaGetErrorString(syncErr));
                throw std::runtime_error(cudaGetErrorString(syncErr));
            }
        }
    }
}


void launchStageAdvanceQueued(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const int* d_queue_in, const int* d_count_in,
    int* d_queue_out, int* d_count_out,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const ::GMaterial* d_materials,
    const ::GLight*    d_lights, int num_lights, float total_light_power,
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth)
{
    if (state.num_active <= 0) return;
    // Grid covers the worst case (all paths alive); the kernel early-outs
    // past *d_count_in, so retired blocks cost only launch overhead. The
    // host never reads the device counters (zero-sync driver).
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_advance_queued_n7",
            (const void*)stageAdvanceQueuedKernel, blocks, threads);
        stageAdvanceQueuedKernel<<<blocks, threads>>>(
            state, hitBufs, d_queue_in, d_count_in, d_queue_out, d_count_out,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
            d_lights, num_lights, total_light_power, lightTree,
            envMap, backgroundColor, hasBackgroundColor,
            worldMaxBounces, max_depth);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_advance_queued launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

void launchStageQueueIota(int* d_queue, int* d_count, int n)
{
    if (n <= 0) return;
    int threads = 256;
    int blocks  = (n + threads - 1) / threads;
    stageQueueIotaKernel<<<blocks, threads>>>(d_queue, d_count, n);
    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        std::fprintf(stderr, "stage_queue_iota launch error: %s\n",
                     cudaGetErrorString(err));
        throw std::runtime_error(cudaGetErrorString(err));
    }
}

void launchStageIntersectQueued(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const int* d_queue_in, const int* d_count_in,
    int* d_shade_queues, int* d_shade_counts, int capacity,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const ::GMaterial* d_materials,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces)
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_intersect_queued_n7",
            (const void*)stageIntersectQueuedKernel, blocks, threads);
        stageIntersectQueuedKernel<<<blocks, threads>>>(
            state, hitBufs, d_queue_in, d_count_in,
            d_shade_queues, d_shade_counts, capacity,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
            envMap, backgroundColor, hasBackgroundColor, worldMaxBounces);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_intersect_queued launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

void launchStageShadeBucketed(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const int* d_shade_queues, const int* d_shade_counts, int capacity,
    int* d_queue_out, int* d_count_out,
    float* d_nee_f, int* d_nee_i, int* d_shadow_queue, int* d_shadow_count,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const ::GMaterial* d_materials,
    const ::GLight*    d_lights, int num_lights, float total_light_power,
    GLightTreeView    lightTree,
    int               max_depth)
{
    if (capacity <= 0) return;
    // One launch covers all buckets: grid = NUM_TYPES * capacity threads;
    // capacity is a multiple of the block size in practice but the kernel
    // handles any value. Threads past a bucket's count retire immediately;
    // surviving warps are material-coherent within their bucket.
    long long total = (long long)G_WF_NUM_MAT_TYPES * capacity;
    int threads = 256;
    int blocks  = (int)((total + threads - 1) / threads);
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_shade_bucketed_n7",
            (const void*)stageShadeBucketedKernel, blocks, threads);
        stageShadeBucketedKernel<<<blocks, threads>>>(
            state, hitBufs, d_shade_queues, d_shade_counts, capacity,
            d_queue_out, d_count_out,
            d_nee_f, d_nee_i, d_shadow_queue, d_shadow_count,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
            d_lights, num_lights, total_light_power, lightTree, max_depth);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_shade_bucketed launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

// ---------------------------------------------------------------------------
// N+7 part 4: path regeneration (Laine 2013 sec. 4).
//
// Dense pass over all slots: a DEAD slot first accumulates its radiance
// (the same XYZ + firefly-clamp math as stageAccumulateXYZKernel -- the
// accumulate-at-death form), zeroes its color (so an exhausted slot adds 0
// on later passes), then claims the next unscheduled (pixel, sample) work
// item from a global counter and re-initializes itself via initPathSlot.
// The pool therefore stays ~full for the whole render and kernel launches
// amortize across ALL samples instead of running depth x spp rounds over
// emptying queues (the part-3 diagnosis).
//
// work item w -> pixel = w % numPixels, sample = w / numPixels, so wave k
// schedules sample k for every pixel: coalesced and identical per-path RNG
// keying to the per-round scheduling (streams keyed by (pixel, sample)).
// ---------------------------------------------------------------------------
__global__ void stageRegenKernel(
    GPUWavefrontState state,
    float* accum_xyz,
    int* work_counter,
    int total_work,
    int numPixels,
    GCameraParams cam,
    int width, int height,
    uint64_t seed)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= state.num_active) return;
    if (state.path_alive[idx] != 0) return;

    // ---- Accumulate the dead path's radiance into ITS pixel (not the
    // slot index -- under regeneration slots host arbitrary pixels).
    GSampledSpectrum rad;
    rad.v[0] = state.color_0[idx];
    rad.v[1] = state.color_1[idx];
    rad.v[2] = state.color_2[idx];
    rad.v[3] = state.color_3[idx];
    bool hasRad = (rad.v[0] != 0.f) | (rad.v[1] != 0.f) |
                  (rad.v[2] != 0.f) | (rad.v[3] != 0.f);
    if (hasRad) {
        GSampledWavelengths lambdas;
        lambdas.lambda[0] = state.lambda_0[idx];
        lambdas.lambda[1] = state.lambda_1[idx];
        lambdas.lambda[2] = state.lambda_2[idx];
        lambdas.lambda[3] = state.lambda_3[idx];
        lambdas.pdf[0] = state.lambda_pdf_0[idx];
        lambdas.pdf[1] = state.lambda_pdf_1[idx];
        lambdas.pdf[2] = state.lambda_pdf_2[idx];
        lambdas.pdf[3] = state.lambda_pdf_3[idx];
        GVec3 xyz = gpu_spectrum_to_xyz(rad, lambdas);
        float lum = xyz.y;
        if (lum > 20.0f) {
            xyz.x *= (20.0f / lum);
            xyz.y = 20.0f;
            xyz.z *= (20.0f / lum);
        }
        int pixel = state.pixel_index[idx];
        // Multiple slots can die holding the same pixel (different samples)
        // within one pass: atomic adds.
        atomicAdd(&accum_xyz[pixel * 3 + 0], xyz.x);
        atomicAdd(&accum_xyz[pixel * 3 + 1], xyz.y);
        atomicAdd(&accum_xyz[pixel * 3 + 2], xyz.z);
        state.color_0[idx] = 0.f;
        state.color_1[idx] = 0.f;
        state.color_2[idx] = 0.f;
        state.color_3[idx] = 0.f;
    }

    // ---- Claim the next work item; leave the slot dead when exhausted.
    int w = atomicAdd(work_counter, 1);
    if (w >= total_work) return;
    int pixel  = w % numPixels;
    int sample = w / numPixels;
    initPathSlot(idx, pixel, sample, state, cam, width, height, seed);
}

void launchStageRegen(
    GPUWavefrontState& state,
    float* d_accum_xyz,
    int* d_work_counter,
    int total_work,
    int numPixels,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed)
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_regen_n7",
            (const void*)stageRegenKernel, blocks, threads);
        stageRegenKernel<<<blocks, threads>>>(
            state, d_accum_xyz, d_work_counter, total_work, numPixels,
            cam, width, height, seed);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_regen launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

void launchStageShadow(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const float* d_nee_f, const int* d_nee_i,
    const int* d_shadow_queue, const int* d_shadow_count, int nee_capacity,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const ::GMaterial* d_materials)
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_shadow_n7",
            (const void*)stageShadowKernel, blocks, threads);
        stageShadowKernel<<<blocks, threads>>>(
            state, hitBufs, d_nee_f, d_nee_i,
            d_shadow_queue, d_shadow_count, nee_capacity,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_materials);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_shadow launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

}  // namespace astroray::wavefront

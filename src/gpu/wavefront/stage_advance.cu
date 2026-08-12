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
#include "../gpu_spectral_tables.h"  // pkg55-C3: gpu_profile_reflectance
#include "astroray/gpu_photon_store.h"  // pkg55-C5 / pkg113: photonGridGatherKnn
#include "astroray/cryptomatte.h"  // pkg159: hash_to_float + atomic rank insert

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
    uint64_t seed,
    float lambdaMin,
    float lambdaMax);
} }

namespace astroray::wavefront {

namespace {

constexpr int kRRDepth = 3;  // mirrors CPU path_kernel.cpp kRRDepth

// pkg55-C3: Rayleigh scattering scale for non-visible-band sky fallback.
// Mirrors multiwavelength_kernel.cu:76 (MW-kernel-local helper).
__device__ inline float rayleighScale(float lambda_nm) {
    float r = 550.f / lambda_nm;
    return r * r * r * r;
}

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
// N+7: the one-bounce advance body, split at the post-emissive boundary into
// intersectPathSlot (intersect + env-miss + emissive; consumes NO RNG
// dimensions, so the cut preserves the RNG stream exactly) and
// shadePathSlot (NEE + RR + BSDF) -- one generator of the per-bounce math
// (design decision #9). The production scheduling is stageRegen ->
// stageIntersectQueued -> stageShadeBucketed -> stageShadow (Laine 2013
// sec. 4 compaction; Cycles X uses the same dense-active-queue structure).
// (Hygiene 2026-08-11: the caller-less dense/flat-queued reference kernels
// stageAdvanceKernel / stageAdvanceQueuedKernel and their composition
// wrapper advancePathSlot were removed.)
//
// intersectPathSlot returns -1 when the path died, else the GMaterialType
// of the hit (0..GMAT_CLOSURE_GRAPH) for shade-queue bucketing. The hit
// record is parked in GPUWavefrontHitBuffers SoA at the slot index.
__device__ int intersectPathSlot(
    int idx,
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const GTLASNode*  tlas,        // pkg55-C4 / pkg114
    const GInstance*  instances,   // pkg55-C4 / pkg114
    const GBLAS*      blas,        // pkg55-C4 / pkg114
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GVec3*      motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* materials,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    bool              useLuminanceOutput,
    bool              enableNEE,        // pkg156: gates the pkg120 two-sided-MIS leg
    float             clampDirect, float clampIndirect,  // pkg157
    // pkg120: light data for the two-sided-MIS emissive-hit reconstruction.
    const ::GLight*   lights, int numLights, float totalLightPower,
    // pkg181: dedicated lamps for the BSDF-ray lamp-intersection pass.
    const GDedicatedLight* dedLights, int numDed,
    GLightTreeView    lightTree)
{
    const int bounce = state.bounce[idx];

    // ---- Reconstruct live path state from SoA (already-normalized ray
    // direction restored verbatim — the Phase A.1 ulp rule).
    GRay ray;
    ray.origin = GVec3(state.ray_origin_x[idx], state.ray_origin_y[idx],
                       state.ray_origin_z[idx]);
    ray.direction = GVec3(state.ray_direction_x[idx], state.ray_direction_y[idx],
                          state.ray_direction_z[idx]);
    // pkg55-C4: deformation-motion time (pkg88-C.0). Sampled once at init,
    // carried through all bounces (mirrors MW kernel multiwavelength_kernel.cu:361).
    ray.time = state.path_time[idx];

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
    // pkg55-C4 / pkg114: route through gpu_tlas_hit when TLAS exists (two-level
    // traversal for instanced scenes). Null-TLAS fallback (tlas==nullptr) routes
    // to the single-level gpu_bvh_hit path inside gpu_tlas_hit, so static scenes
    // stay byte-identical (pkg114 inc-1 identity test).
    GHitRecord rec;
    bool hit = gpu_tlas_hit(tlas, instances, blas, bvhNodes, prims, tris, spheres,
                            ray, 0.001f, 1e30f, rec, motionVerts);

    // pkg181: dedicated-light visibility to BSDF rays (Cycles lights_intersect
    // parity) — device twin of production pathTraceSpectral. Lamps are invisible
    // to camera rays (bounce == 0); a lamp closer than the surface terminates the
    // path. Placed in the INTERSECT stage (this kernel), NOT the REG:254-saturated
    // shade stage (memory wavefront-shade-kernels-register-saturated). The
    // snapshot capture moment is unaffected: this kernel writes no PostIntersect
    // snapshot; the lamp hit terminates before the hit-record is parked. Emission
    // + MIS mirror the emissive-Hittable block below (wB = 1 after specular; the
    // power heuristic otherwise; naive mode = enableNEE false takes specular only).
    if (bounce > 0 && numDed > 0) {
        float surfaceT = hit ? rec.t : 1e30f;
        float lampT, lampScale;
        int lampIdx = gpu_dedicated_intersect_closest(
            dedLights, numDed, ray.origin, ray.direction, 0.001f, surfaceT,
            &lampT, &lampScale);
        if (lampIdx >= 0) {
            GSampledSpectrum Le;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                Le.v[i] = gpu_rgbSpectrumAt(dedLights[lampIdx].emissionRGB,
                                            lambdas.lambda[i], GSPEC_RGB_ILLUMINANT)
                          * lampScale;
            if (Le.maxValue() > 0.f) {
                GSampledSpectrum contrib(0.f);
                if (bounce == 0 || wasSpecular) {
                    contrib = throughput * Le;                 // w_B = 1
                } else if (enableNEE) {
                    float lp = gpu_dedicated_reconstruct_pdf(
                        dedLights, numDed, totalLightPower, ray.origin, ray.direction);
                    float wB = gpu_mw_powerHeuristic(state.path_bsdf_pdf[idx], lp);
                    contrib = throughput * Le * wB;
                }
                // naive mode (enableNEE == false, non-specular): no NEE leg to
                // complement, so nothing is added — mirrors the emissive block.
                color += gpu_clampContribMW(contrib, lambdas, bounce,
                                            clampDirect, clampIndirect, useLuminanceOutput);
            }
            state.color_0[idx] = color.v[0];
            state.color_1[idx] = color.v[1];
            state.color_2[idx] = color.v[2];
            state.color_3[idx] = color.v[3];
            state.path_alive[idx] = 0;
            return -1;   // path terminates on the lamp
        }
    }

    if (!hit) {
        // ---- Env-map miss (CPU path_kernel: worldMaxBounces gate; the
        // shared helper mirrors EnvironmentMap::evalSpectral).
        // pkg55-C3: Rayleigh sky fallback for non-visible-band luminance-output
        // mode (multiwavelength_kernel.cu:171-177).
        if (bounce <= worldMaxBounces) {
            GVec3 dir = ray.direction.normalized();
            GSampledSpectrum envSpec(0.f);
            if (useLuminanceOutput && !hasBackgroundColor && !envMap.loaded) {
                // Rayleigh sky fallback for outside-visible bands.
                for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
                    float scale = rayleighScale(lambdas.lambda[i]);
                    float horizonFade = 0.5f * (dir.y + 1.f);
                    envSpec.v[i] = 0.08f * scale * (0.5f + horizonFade);
                }
            } else {
                envSpec = gpu_env_miss_spectral(
                    envMap, backgroundColor, hasBackgroundColor, dir, lambdas);
            }
            // pkg157: clamp by bounce depth (Cycles film_clamp_light split);
            // see gpu_clampContribMW (gpu_spectral_tables.h).
            color += gpu_clampContribMW(throughput * envSpec, lambdas, bounce,
                                        clampDirect, clampIndirect, useLuminanceOutput);
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
            // pkg157: emissive-hit direct term, same clamp split as above.
            // Camera / post-specular ray: no NEE leg competes (w_B = 1).
            color += gpu_clampContribMW(throughput * Le, lambdas, bounce,
                                        clampDirect, clampIndirect, useLuminanceOutput);
        } else if (enableNEE) {
            // pkg120: two-sided MIS BSDF-sampled leg — device twin of CPU
            // pathTraceSpectral. This continuation ray was BSDF-sampled at a
            // diffuse bounce; weight its emission by the power heuristic against
            // the light-sampling pdf that would have generated this same hit.
            // prevPoint = ray.origin (this ray's origin is the previous shading
            // vertex, written verbatim by shadePathSlot), dir = ray.direction
            // (the sampled BSDF direction) — same values on CPU and GPU, so the
            // pdf reconstruction matches by construction (no snapshot skew).
            //
            // pkg156: gated on enableNEE. The w_B leg is only meaningful as the
            // complement of the NEE light-sampling leg (w_L). In naive mode
            // (enableNEE == false, the multiwavelength_path_tracer route) there
            // is no NEE leg, so the CPU oracle (MultiwavelengthPathTracer::
            // pathTrace) accumulates NOTHING on a diffuse emitter hit — it only
            // takes emission on bounce == 0 || wasSpecular. Applying w_B here
            // diverged the GPU bright from that oracle (bounce-2 onset, the
            // pkg156 residual); skipping it restores CPU/GPU parity and the
            // pre-pkg120 naive behaviour. NEE mode (path_tracer) is unchanged.
            float bsdfPdfPrev = state.path_bsdf_pdf[idx];
            float lp = gpu_reconstruct_light_pdf(
                rec, ray.origin, ray.direction,
                lights, numLights, totalLightPower,
                prims, tris, spheres, lightTree);
            float wB = gpu_mw_powerHeuristic(bsdfPdfPrev, lp);
            GSampledSpectrum contrib = throughput * Le;
            contrib *= wB;
            color += gpu_clampContribMW(contrib, lambdas, bounce,
                                        clampDirect, clampIndirect, useLuminanceOutput);
        }
        state.color_0[idx] = color.v[0];
        state.color_1[idx] = color.v[1];
        state.color_2[idx] = color.v[2];
        state.color_3[idx] = color.v[3];
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
// pkg174: template on Deferred. The production bucketed/NeeMis schedulings
// always park NEE work to the deferred shadow stage (nee_f != nullptr), so the
// immediate-NEE `else` branch (inline gpu_nee_occlude shadow-ray BVH/TLAS
// traversal) is DEAD in those instantiations. Compiling it out with
// `if constexpr (Deferred)` frees ptxas from allocating for its shadow-traversal
// live set in the REG:254-saturated shade kernel. Deferred=false keeps the
// immediate path for advancePathSlot (the dense/flat reference schedulings).
// PERF ONLY — the compiled-out branch is unreachable in the deferred callers.
// pkg178 Stage-3b D4: HasPrincipled is threaded into the material dispatch so
// non-principled scenes launch a shade kernel with ZERO gpu_principled_* codegen
// (if constexpr in gpu_materials.h), restoring main's footprint. The launchers
// pick <true>/<false> off scene_upload's host-side flag. See
// .astroray_plan/docs/pkg178-stage3-d4-and-forks-decision.md §2b.
// pkg186 — image-texture binding in constant memory (see GWavefrontTextureBinding
// in gpu_types.h). Set once per frame by setWavefrontTextureBinding before the
// shade launches; read only inside `if constexpr (HasTexture)`. Keeping it OUT of
// the kernel signature is what leaves the untextured <false,false> fleet kernel at
// its pre-pkg186 REG/STACK footprint (the three signature params cost +24 B stack).
__constant__ GWavefrontTextureBinding c_wfTexBinding;

// pkg184 — HasPhotons isolates the bounce-0 photon-map caustic KNN gather
// (photonGridGatherKnn, 50-neighbour live set) behind `if constexpr`. The gather
// only ever fires at bounce 0 in scenes that carry a photon grid, yet ptxas had to
// allocate its registers/stack in EVERY instantiation of the REG:254-pinned shade
// kernel. Threading HasPhotons lets the fleet's non-photon <*,*,false> kernels
// compile with ZERO gather codegen; the launcher picks <true> off hasPhotonGrid.
// See .astroray_plan/packages/pkg184-stage-advance-hasphotons-isolation.md.
template<bool Deferred, bool HasPrincipled, bool HasTexture = false, bool HasPhotons = false>
__device__ bool shadePathSlot(
    int idx,
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const GTLASNode*  tlas,        // pkg55-C4 / pkg114
    const GInstance*  instances,   // pkg55-C4 / pkg114
    const GBLAS*      blas,        // pkg55-C4 / pkg114
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GVec3*      motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    const GDedicatedLight* dedLights, int numDed,   // pkg89-wavefront (C7)
    GLightTreeView    lightTree,
    int               max_depth,
    float*            nee_f, int* nee_i,
    int*              shadow_queue, int* shadow_count, int nee_capacity,
    bool              useLuminanceOutput,
    bool              enableNEE,
    float             clampDirect, float clampIndirect,  // pkg157
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid,
    float             photonScale,
    bool              captureMis = false,  // pkg55-C7: MIS instrumentation
                                           // stores only for the PostNEE_MIS
                                           // snapshot harness (perf: the #484
                                           // always-on stores were 3 global
                                           // writes per NEE shade in the
                                           // production hot path)
    // pkg159: per-PIXEL cryptomatte rank arrays (numPixels*depth*2 floats
    // each), owned by the driver. cryptoDepth == 0 or null pointers = crypto
    // disabled, which is the default and costs one predicated branch.
    float*            cryptoObjectRanks = nullptr,
    float*            cryptoMaterialRanks = nullptr,
    int               cryptoDepth = 0)
{
    const int bounce = state.bounce[idx];

    GRay ray;
    ray.direction = GVec3(state.ray_direction_x[idx], state.ray_direction_y[idx],
                          state.ray_direction_z[idx]);
    // pkg55-C4: deformation-motion time (pkg88-C.0). Carried from init, threaded
    // to shadow rays (gpu_nee_occlude).
    ray.time = state.path_time[idx];

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

    // pkg178 Stage-3b PR-4b — UV-aligned shading tangent for anisotropic
    // Principled. Default to the arbitrary frame; override from the hit triangle's
    // uploaded active-layer UVs when present (scene_upload sets hasUV only on
    // anisotropic-Principled triangles). Behind `if constexpr (HasPrincipled)` so
    // the non-principled <false> shade kernel compiles this out entirely, and
    // behind the per-triangle `hasUV` runtime gate so non-aniso principled scenes
    // pay nothing. Computed here (not the intersect stage) to avoid a per-path
    // hit-buffer SoA field (see PR report: honors "zero device memory" for
    // non-aniso scenes at the cost of the aniso branch's registers in the <true>
    // kernel — LEAD measures via cuobjdump). NOTE: uses the triangle's stored
    // (object-local for instanced BLAS) verts; correct for the non-instanced flat
    // scene the parity gates use; instanced-aniso tangent orientation is a
    // declared follow-up.
    rec.uvTangent = rec.tangent;
    rec.uvBitangentSign = 1.0f;
    if constexpr (HasPrincipled) {
        if (rec.primId >= 0 && prims[rec.primId].type == GPRIM_TRIANGLE) {
            const GTriangle& utri = tris[prims[rec.primId].index];
            if (utri.hasUV) {
                GVec3 uvT; float uvSign;
                if (gpu_pr_uvAlignedTangent(utri.v0, utri.v1, utri.v2,
                                            utri.uv0, utri.uv1, utri.uv2,
                                            rec.normal, uvT, uvSign)) {
                    rec.uvTangent = uvT;
                    rec.uvBitangentSign = uvSign;
                }
            }
        }
    }

    const ::GMaterial& mat = materials[rec.materialId];

    // pkg186 — image-texture base color for a textured lambertian. The whole
    // diffuse bounce (NEE eval, BSDF throughput, continuation) is LINEAR in
    // albedo_spec = upsample(baseColor), so substituting the sampled texel is a
    // SINGLE multiply of `throughput` by the spectral ratio
    // upsample(texColor)/upsample(baseColor), applied here BEFORE NEE and BSDF.
    // This leaves the shared material dispatch untouched — no per-hit GMaterial
    // copy (GMaterial is a zero-slack 640 B struct; a copy spills the shared
    // kernel) — and, gated behind `if constexpr (HasTexture)`, compiles to
    // nothing in the untextured <...,false> kernel the fleet runs. UVs are
    // interpolated from the hit triangle's uploaded active-layer texcoords
    // (scene_upload sets hasUV on image-textured triangles) via barycentrics
    // recomputed from the world hit point (Ericson, Real-Time Collision
    // Detection §3.4) — mirrors pkg178's in-kernel recompute (no extra per-path
    // SoA field; correct for the non-instanced meshes the parity gate uses;
    // instanced-texture UV is a declared follow-up, same cut pkg178 took for
    // instanced aniso). matTexId[]==-1 (every non-image material) skips this.
    // NOTE: Russian roulette (bounce > kRRDepth) then keys off the already-
    // textured throughput one bounce earlier than the CPU folds albedo in; RR is
    // unbiased/mean-preserving so the per-channel mean-ratio gate is unaffected.
    //
    // The texture arrays are read from the __constant__ c_wfTexBinding symbol
    // (set once per frame via setWavefrontTextureBinding), NOT from kernel
    // signature params. Threading them as three per-launch pointer params grew
    // the SHARED kernel signature (CONSTANT[0] +28 B) and cost +24 B STACK on the
    // untextured <false,false> fleet kernel even though the code is if-constexpr'd
    // out — measured on native sm_120 (STACK 3632 vs main's 3608). Moving them to
    // constant memory keeps the <false,*> signature at its pre-pkg186 footprint.
    if constexpr (HasTexture) {
        const int* matTexId = c_wfTexBinding.matTexId;
        int texId = matTexId[rec.materialId];
        if (texId >= 0 && rec.primId >= 0 &&
            prims[rec.primId].type == GPRIM_TRIANGLE) {
            const GTriangle& ttri = tris[prims[rec.primId].index];
            if (ttri.hasUV) {
                GVec3 e1 = ttri.v1 - ttri.v0, e2 = ttri.v2 - ttri.v0;
                GVec3 ep = rec.point - ttri.v0;
                float d00 = e1.dot(e1), d01 = e1.dot(e2), d11 = e2.dot(e2);
                float d20 = ep.dot(e1), d21 = ep.dot(e2);
                float denom = d00 * d11 - d01 * d01;
                if (fabsf(denom) > 1e-20f) {
                    float b1 = (d11 * d20 - d01 * d21) / denom;
                    float b2 = (d00 * d21 - d01 * d20) / denom;
                    float b0 = 1.0f - b1 - b2;
                    float uu = b0 * ttri.uv0.x + b1 * ttri.uv1.x + b2 * ttri.uv2.x;
                    float vv = b0 * ttri.uv0.y + b1 * ttri.uv1.y + b2 * ttri.uv2.y;
                    GVec3 texColor = gpu_sampleImageTexture(
                        c_wfTexBinding.textures[texId], c_wfTexBinding.texelBuf, uu, vv);
                    GSampledSpectrum texUp =
                        gpu_rgbToSampledSpectrum(texColor, lambdas, mat.spectralMode);
                    GSampledSpectrum baseUp =
                        gpu_rgbToSampledSpectrum(mat.baseColor, lambdas, mat.spectralMode);
                    for (int s = 0; s < G_SPECTRUM_SAMPLES; ++s) {
                        float d = baseUp[s];
                        throughput.v[s] *= (d > 1e-8f ? texUp[s] / d : 0.0f);
                    }
                }
            }
        }
    }

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
    // pkg55-C3: enableNEE flag gates NEE sampling (naive multiwavelength mode).
    // pkg89-wavefront (C7): dedicated lights (point/spot/distant/area lamps)
    // join the wavefront NEE via the SAME unified power-CDF + device sampleLi
    // the MW megakernel uses (gpu_nee.cuh::gpu_dedicated_sample, #489/#500;
    // Cycles kernel/light/{point,spot,distant,area}.h via the CPU mirrors).
    // The (numLights + numDed) gate mirrors both the CPU light_seed gate
    // (path_kernel.cpp:230 !lights.empty() — the CPU LightList spans both
    // kinds) and gpu_nee_sample's own emptiness check.
    if (enableNEE && !rec.isDelta && (numLights + numDed) > 0) {
        if (totalLightPower > 0.f) {
            GNEESample s = gpu_nee_sample(rec, prims, tris, spheres,
                                          lights, numLights, totalLightPower,
                                          dedLights, numDed,
                                          lightTree, &rng);
            if (s.valid) {
                if constexpr (Deferred) {
                    // Defer the TRACE + emission to the shadow stage; the
                    // BSDF eval/pdf/MIS happen HERE where the material code
                    // already lives (Cycles shade_surface.h ordering). The
                    // original lazy post-trace eval order is a pure-math
                    // reorder: identical output, evals paid on occluded
                    // samples in exchange for a lean ~100-reg shadow kernel
                    // (measured tradeoff per the blueprint).
                    GSampledSpectrum f_spec = gpu_material_eval_spectral<HasPrincipled>(
                        mat, rec, wo, s.wi, lambdas);
                    if (f_spec.maxValue() > 0.f) {
                        float bsdfPdf = gpu_material_pdf<HasPrincipled>(mat, rec, wo, s.wi);
                        // Power heuristic (Veach 1997) — mirrors
                        // gpu_mw_powerHeuristic in the MW TU. Delta lights
                        // (pkg140, e.g. zero-diameter sun) force wt = 1
                        // exactly like gpu_nee_resolve: a BSDF ray has zero
                        // probability of hitting a delta direction.
                        float a2 = s.lightPdf * s.lightPdf;
                        float b2 = bsdfPdf * bsdfPdf;
                        float wt = s.isDeltaLight ? 1.0f
                                                  : a2 / (a2 + b2 + 1e-8f);
                        // pkg172(A) secondary: guarded light-pdf (pbrt-v4
                        // convention) — was wt/(lightPdf+1e-3), a biasing
                        // additive-epsilon under-weighting of NEE. Mirrors the
                        // CPU NEE twin (raytracer.h:2558, path_kernel.cpp:290)
                        // already guarded on main (#551); brings the deferred
                        // GPU NEE leg back into CPU parity.
                        float scale = s.lightPdf > 1e-8f ? wt / s.lightPdf : 0.0f;
                        // pkg89-wavefront: dedicated emission is
                        // rgbAt(dedEmissionRGB, λ)·dedGeoScale (gpu_nee_resolve);
                        // dedGeoScale is λ-independent, so fold it into the
                        // parked scale and park only the RGB for the shadow
                        // stage's per-λ upsample.
                        if (s.isDedicated) scale *= s.dedGeoScale;
                        // pkg55-C2 MIS audit: capture the exact pdfs and the
                        // resulting power-heuristic weight (Veach 1997) this NEE
                        // sample used, for the PostNEE_MIS gate. Pure stores to
                        // instrumentation arrays — no RNG draw, no reorder, and
                        // never read by accumulation, so renders are unchanged.
                        // pkg55-C7 perf: gated on captureMis (true only in the
                        // stageShadeNeeMisKernel snapshot path; the production
                        // bucketed pipeline skips the 3 global writes).
                        if (captureMis) {
                            state.path_light_pdf[idx]  = s.lightPdf;
                            state.path_mis_pdf[idx]    = bsdfPdf;
                            state.path_mis_weight[idx] = wt;
                        }
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
                        // pkg89-wavefront: dedicated-light payload lanes.
                        nee_f[11 * nee_capacity + idx] = s.dedEmissionRGB.x;
                        nee_f[12 * nee_capacity + idx] = s.dedEmissionRGB.y;
                        nee_f[13 * nee_capacity + idx] = s.dedEmissionRGB.z;
                        nee_i[ 0 * nee_capacity + idx] = s.lightMatId;
                        nee_i[ 1 * nee_capacity + idx] = s.isSphere;
                        nee_i[ 2 * nee_capacity + idx] = s.isDedicated;  // pkg89-wavefront
                        // pkg157: park the bounce depth this NEE sample was taken
                        // at -- the shadow-resolve kernel runs in a later launch,
                        // after state.bounce[idx] may already have advanced (see
                        // the G_WF_NEE_I_LANES comment, gpu_wavefront_state.h).
                        nee_i[ 3 * nee_capacity + idx] = bounce;
                        int qslot = atomicAdd(shadow_count, 1);
                        shadow_queue[qslot] = idx;
                    }
                } else {
                    // Immediate (flat/dense schedulings): original behavior.
                    // pkg55-C4: thread TLAS + ray.time + motionVerts (null-TLAS path
                    // routes to single-level inside gpu_nee_occlude → gpu_tlas_hit).
                    GNEEOcclusion occ = gpu_nee_occlude(
                        s, tlas, instances, blas, bvhNodes, prims, tris, spheres,
                        ray.time, motionVerts);
                    if (!occ.occluded) {
                        GSampledSpectrum nee = gpu_nee_resolve<HasPrincipled>(
                            rec, wo, lambdas, materials, s,
                            s.isSphere ? (occ.frontFace != 0) : true);
                        // pkg157: direct/indirect clamp split (bounce is the
                        // shading vertex's own depth here, no park needed).
                        color += gpu_clampContribMW(throughput * nee, lambdas, bounce,
                                                    clampDirect, clampIndirect,
                                                    useLuminanceOutput);
                    }
                }
            }
        }
    }

    // pkg55-C5 / pkg113: spectral photon-map caustic gather at the PRIMARY hit
    // (bounce==0). Mirrors multiwavelength_kernel.cu:490-507 (MW megakernel gather).
    // Gated on hasPhotonGrid + non-emissive + !useLuminanceOutput (the MW conditions).
    //
    // The MW kernel accumulates in XYZ space (line 481 converts spectral rad→XYZ sample,
    // line 502 adds photon XYZ to sample). The wavefront accumulates in spectral space
    // (color SoA) and converts to XYZ at the regen stage. To match MW behavior, we store
    // photon XYZ contrib in separate photon_xyz_* SoA fields and add it to accum_xyz
    // during regen (after spectral color→XYZ conversion), preserving the XYZ+XYZ math.
    // pkg184: gated at COMPILE time on HasPhotons so ptxas allocates the 50-neighbour
    // gather's live set only in the <*,*,true> instantiations. The runtime guard is
    // preserved unchanged inside — a HasPhotons=true kernel is byte-identical to the
    // pre-pkg184 kernel; a HasPhotons=false kernel (launched when hasPhotonGrid is
    // false) never gathered anyway, so this is behaviour-preserving.
    if constexpr (HasPhotons) {
        if (bounce == 0 && hasPhotonGrid && !useLuminanceOutput && photonGrid.numPhotons > 0) {
            // rec is already the primary hit from intersectPathSlot; check non-emissive.
            if (mat.emissionIntensity <= 0.0f) {
                int found = 0;
                GVec3 E = astroray::photon::gpu::photonGridGatherKnn(
                    photonGrid, rec.point, 50, 1.1f, found);
                if (found > 0) {
                    GVec3 alb = mat.baseColor;
                    GVec3 photonContrib = GVec3(alb.x * E.x, alb.y * E.y, alb.z * E.z)
                                          * photonScale;
                    // Store in photon_xyz SoA; will be added to accum_xyz during regen.
                    state.photon_xyz_x[idx] = photonContrib.x;
                    state.photon_xyz_y[idx] = photonContrib.y;
                    state.photon_xyz_z[idx] = photonContrib.z;
                }
            }
        }
    }

    // ---- Russian roulette on luminance of throughput's XYZ (bounce > 3).
    // pkg55-C3: for useLuminanceOutput (non-visible bands), use average of
    // spectral samples instead of XYZ.Y (multiwavelength_kernel.cu:315-318).
    if (bounce > kRRDepth) {
        float p;
        if (useLuminanceOutput) {
            float avg = 0.f;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) avg += throughput.v[i];
            p = fminf(0.95f, fmaxf(0.0f, avg / float(G_SPECTRUM_SAMPLES)));
        } else {
            GVec3 thrXYZ = gpu_spectrum_to_xyz(throughput, lambdas);
            p = fminf(0.95f, fmaxf(0.0f, thrXYZ.y));
        }
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
    GBSDFSample bss = gpu_material_sample_spectral<HasPrincipled>(mat, rec, wo, lambdas, &rng);
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
    // pkg120: park this bounce's BSDF pdf so the NEXT bounce's intersect stage
    // can weight a diffuse-bounce emissive hit by the two-sided MIS heuristic
    // (mirrors CPU bsdfPdfPrev = bss.pdf in pathTraceSpectral).
    state.path_bsdf_pdf[idx] = bss.pdf;

    // pkg55-C3/C7: non-visible-band profile override — mirrors the deleted
    // MW megakernel block (multiwavelength_kernel.cu:376-390) and CPU
    // Material::evalSpectralExt EXACTLY:
    //   * visible λ → keep the RGB-upsampled bss.fSpectral,
    //   * non-visible λ + profile → reflectance(λ) · cosθ / π,
    //   * non-visible λ + NO profile → 0 (RGB albedo is undefined outside
    //     the visible band — the else-zero was dropped in the C3 port and
    //     restored in C7).
    if (!wasSpecular) {
        float cosTheta = fmaxf(0.f, rec.normal.dot(bss.wi));
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
            float lam = lambdas.lambda[i];
            if (lam < 380.f || lam > 780.f) {
                if (mat.profileIndex >= 0) {
                    bss.fSpectral.v[i] =
                        gpu_profile_reflectance(mat.profileIndex, lam)
                        * cosTheta / M_PI_F;
                } else {
                    bss.fSpectral.v[i] = 0.f;
                }
            }
        }
    }

    // pkg159: Cryptomatte per-shade-point accumulation, the device twin of
    // Renderer::pathTraceSpectral (raytracer.h:2581-2602).
    //
    // Placed HERE — after the BSDF sample (the weight needs bss.fSpectral) and
    // BEFORE the throughput update — exactly like the CPU oracle. Sits after
    // the non-visible-band profile override above so bss.fSpectral carries the
    // same value the CPU's Material::sampleSpectral returns.
    //
    // Three deliberate divergences from the DELETED RGB megakernel
    // (path_trace_kernel.cu:602-629, recoverable at 9fa91c8^), all specified by
    // pkg159 and all bug fixes rather than ports:
    //   1. bounce == 0 gate. The CPU records the FIRST HIT only
    //      ("Cryptomatte records only the first hit", raytracer.h:2580); the
    //      megakernel accumulated at every bounce. The CPU is the oracle.
    //   2. hash_to_float(). The megakernel did `float id = tri.objectHash;` —
    //      an implicit uint32→float NUMERIC conversion, so its IDs matched
    //      neither the CPU nor the Psyop `uint32_to_float32` manifest.
    //   3. ATOMIC insert. The megakernel ran one thread per pixel; the
    //      wavefront has many concurrent slots per pixel (regeneration), so the
    //      rank read-modify-write is a data race without atomics. See
    //      crypto_insert_atomic (Cycles film_write_cryptomatte_slots under
    //      __ATOMIC_PASS_WRITE__, Apache-2.0).
    //
    // Weight = average(throughput · bsdf_eval) over linear sRGB, per Cycles
    // film_write_cryptomatte_slots; the matrix is the CIE XYZ D65 → linear
    // sRGB one the CPU inlines at raytracer.h:2586-2588.
    if (bounce == 0 && cryptoDepth > 0 &&
        cryptoObjectRanks != nullptr && cryptoMaterialRanks != nullptr) {
        GSampledSpectrum contrib = throughput * bss.fSpectral;
        GVec3 xyz = gpu_spectrum_to_xyz(contrib, lambdas);
        float r =  3.2406f * xyz.x - 1.5372f * xyz.y - 0.4986f * xyz.z;
        float g = -0.9689f * xyz.x + 1.8758f * xyz.y + 0.0415f * xyz.z;
        float b =  0.0557f * xyz.x - 0.2040f * xyz.y + 1.0570f * xyz.z;
        float weight = (r + g + b) / 3.0f;

        // Object/material hashes ride on the uploaded primitive (scene_upload.cu
        // stores the raw MurmurHash3_x86_32 uint32). GHitRecord carries primId
        // (index into prims[]); the GPrimitive carries type + index into
        // tris[]/spheres[] — there is no rec.primType/primIndex.
        float objectId = CRYPTO_ID_NONE, materialId = CRYPTO_ID_NONE;
        const GPrimitive& prim = prims[rec.primId];
        if (prim.type == GPRIM_TRIANGLE) {
            const GTriangle& tri = tris[prim.index];
            objectId   = hash_to_float(tri.objectHash);
            materialId = hash_to_float(tri.materialHash);
        } else if (prim.type == GPRIM_SPHERE) {
            const GSphere& sph = spheres[prim.index];
            objectId   = hash_to_float(sph.objectHash);
            materialId = hash_to_float(sph.materialHash);
        }

        // Ranks are per-PIXEL, not per-slot: under path regeneration a slot
        // hosts an arbitrary (pixel, sample), so index by pixel_index exactly
        // like stageRegenKernel's radiance accumulation.
        crypto_accumulate_shade_point_atomic(
            cryptoObjectRanks, cryptoMaterialRanks,
            state.pixel_index[idx], cryptoDepth, objectId, materialId, weight);
    }

    throughput *= bss.fSpectral * (bss.pdf > 1e-8f ? 1.0f / bss.pdf : 0.0f);

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
    const GTLASNode*  tlas,        // pkg55-C4 / pkg114
    const GInstance*  instances,   // pkg55-C4 / pkg114
    const GBLAS*      blas,        // pkg55-C4 / pkg114
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GVec3*      motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* materials,
    bool              useLuminanceOutput,   // pkg157
    float             clampDirect, float clampIndirect)  // pkg157
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
    // pkg89-wavefront: dedicated-light payload (dedGeoScale was folded into
    // the parked throughput·f·scale lanes at shade time; only the reference
    // RGB is needed here for the per-λ illuminant upsample).
    s.isDedicated    = nee_i[2 * nee_capacity + idx];
    s.dedEmissionRGB = GVec3(nee_f[11 * nee_capacity + idx],
                             nee_f[12 * nee_capacity + idx],
                             nee_f[13 * nee_capacity + idx]);
    s.valid      = 1;

    // pkg55-C4: thread TLAS + path time + motionVerts to shadow rays.
    float time = state.path_time[idx];
    GNEEOcclusion occ = gpu_nee_occlude(
        s, tlas, instances, blas, bvhNodes, prims, tris, spheres,
        time, motionVerts);
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

    GSampledSpectrum L_spec;
    if (s.isDedicated) {
        // pkg89-wavefront: dedicated lights carry emission intrinsically —
        // same RGBIlluminant upsample gpu_nee_resolve uses (dedGeoScale
        // already folded into the parked lanes at shade time).
        for (int k = 0; k < G_SPECTRUM_SAMPLES; ++k)
            L_spec[k] = gpu_rgbSpectrumAt(s.dedEmissionRGB, lambdas.lambda[k],
                                          GSPEC_RGB_ILLUMINANT);
    } else {
        bool lightFront = s.isSphere ? (occ.frontFace != 0) : true;
        L_spec = gpu_material_emitted_spectral(
            materials[s.lightMatId], lightFront, lambdas);
    }
    if (L_spec.maxValue() <= 0.f) return;

    GSampledSpectrum contrib;
    contrib.v[0] = nee_f[ 7 * nee_capacity + idx] * L_spec.v[0];
    contrib.v[1] = nee_f[ 8 * nee_capacity + idx] * L_spec.v[1];
    contrib.v[2] = nee_f[ 9 * nee_capacity + idx] * L_spec.v[2];
    contrib.v[3] = nee_f[10 * nee_capacity + idx] * L_spec.v[3];
    // pkg157: direct/indirect clamp split. bounce is the PARKED depth (lane
    // 3, see G_WF_NEE_I_LANES) the NEE sample was taken at, not state.bounce
    // (already advanced by the time this later-launched kernel runs).
    int bounce = nee_i[3 * nee_capacity + idx];
    contrib = gpu_clampContribMW(contrib, lambdas, bounce,
                                 clampDirect, clampIndirect, useLuminanceOutput);
    state.color_0[idx] += contrib.v[0];
    state.color_1[idx] += contrib.v[1];
    state.color_2[idx] += contrib.v[2];
    state.color_3[idx] += contrib.v[3];
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
    const GTLASNode*  tlas,        // pkg55-C4 / pkg114
    const GInstance*  instances,   // pkg55-C4 / pkg114
    const GBLAS*      blas,        // pkg55-C4 / pkg114
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GVec3*      motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* materials,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    bool              useLuminanceOutput,
    bool              enableNEE,        // pkg156: gates the pkg120 two-sided-MIS leg
    float             clampDirect, float clampIndirect,  // pkg157
    // pkg120: light data threaded to the two-sided-MIS emissive-hit block.
    const ::GLight*   lights, int numLights, float totalLightPower,
    // pkg181: dedicated lamps for the BSDF-ray lamp-intersection pass.
    const GDedicatedLight* dedLights, int numDed,
    GLightTreeView    lightTree)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= *count_in) return;
    int idx = queue_in[i];
    // N+7 part 4: dead-slot guard. Part-3 flat queues are guaranteed-alive
    // (no-op there); the regeneration driver iterates a dense identity
    // queue where exhausted slots stay dead.
    if (state.path_alive[idx] == 0) return;
    int matType = intersectPathSlot(idx, state, hitBufs, tlas, instances, blas,
                                    bvhNodes, prims, tris, spheres, motionVerts,
                                    materials, envMap, backgroundColor,
                                    hasBackgroundColor, worldMaxBounces,
                                    useLuminanceOutput, enableNEE,
                                    clampDirect, clampIndirect,
                                    lights, numLights, totalLightPower,
                                    dedLights, numDed, lightTree);  // pkg120+pkg181
    if (matType < 0) return;
    if (matType >= G_WF_NUM_MAT_TYPES) matType = G_WF_NUM_MAT_TYPES - 1;
    int slot = atomicAdd(&shade_counts[matType], 1);
    shade_queues[matType * capacity + slot] = idx;
}

template<bool HasPrincipled, bool HasTexture, bool HasPhotons>  // pkg178 D4; pkg186 texture; pkg184 photons
__global__ void stageShadeBucketedKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const int* shade_queues, const int* shade_counts, int capacity,
    int* queue_out, int* count_out,
    float* nee_f, int* nee_i, int* shadow_queue, int* shadow_count,
    const GTLASNode*  tlas,        // pkg55-C4 / pkg114
    const GInstance*  instances,   // pkg55-C4 / pkg114
    const GBLAS*      blas,        // pkg55-C4 / pkg114
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GVec3*      motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    const GDedicatedLight* dedLights, int numDed,   // pkg89-wavefront (C7)
    GLightTreeView    lightTree,
    int               max_depth,
    bool              useLuminanceOutput,
    bool              enableNEE,
    float             clampDirect, float clampIndirect,  // pkg157
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid,
    float             photonScale,
    float* cryptoObjectRanks, float* cryptoMaterialRanks, int cryptoDepth)  // pkg159
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    int bucket = i / capacity;
    int pos    = i - bucket * capacity;
    if (bucket >= G_WF_NUM_MAT_TYPES) return;
    if (pos >= shade_counts[bucket]) return;
    int idx = shade_queues[bucket * capacity + pos];
    // pkg186: texture data comes from the __constant__ c_wfTexBinding symbol, NOT
    // kernel params — keeps the untextured <false,false> signature at its
    // pre-pkg186 footprint (see c_wfTexBinding note above).
    bool alive = shadePathSlot<true, HasPrincipled, HasTexture, HasPhotons>(idx, state, hitBufs, tlas, instances, blas,
                               bvhNodes, prims, tris, spheres, motionVerts,
                               materials, lights, numLights,
                               totalLightPower, dedLights, numDed,
                               lightTree, max_depth,
                               nee_f, nee_i, shadow_queue, shadow_count,
                               capacity, useLuminanceOutput, enableNEE,
                               clampDirect, clampIndirect,
                               photonGrid, hasPhotonGrid, photonScale,
                               /*captureMis=*/false,  // pkg159: explicit so the
                               // crypto args below bind to the right params
                               cryptoObjectRanks, cryptoMaterialRanks,
                               cryptoDepth);
    if (alive) {
        int slot = atomicAdd(count_out, 1);
        queue_out[slot] = idx;
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
    const GTLASNode*  d_tlas,        // pkg55-C4 / pkg114
    const GInstance*  d_instances,   // pkg55-C4 / pkg114
    const GBLAS*      d_blas,        // pkg55-C4 / pkg114
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GVec3*      d_motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* d_materials,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    bool              useLuminanceOutput,
    bool              enableNEE,        // pkg156: gates the pkg120 two-sided-MIS leg
    float             clampDirect, float clampIndirect,  // pkg157
    // pkg120: light data for the two-sided-MIS emissive-hit reconstruction.
    const ::GLight*   d_lights, int num_lights, float total_light_power,
    // pkg181: dedicated lamps for the BSDF-ray lamp-intersection pass.
    const GDedicatedLight* d_dedLights, int num_ded,
    GLightTreeView    lightTree)
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
            d_tlas, d_instances, d_blas,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials,
            envMap, backgroundColor, hasBackgroundColor, worldMaxBounces,
            useLuminanceOutput, enableNEE, clampDirect, clampIndirect,
            d_lights, num_lights, total_light_power,
            d_dedLights, num_ded, lightTree);  // pkg120+pkg181
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_intersect_queued launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

// pkg186 — publish the frame's image-texture arrays into the __constant__
// c_wfTexBinding symbol. Called ONCE per frame by the driver (before the shade
// launches), so the shade kernel reads texture data from constant memory instead
// of per-launch signature params. For untextured scenes the driver skips this
// (the <false,*> kernel never reads the symbol).
void setWavefrontTextureBinding(const GWavefrontTextureBinding& binding)
{
    cudaMemcpyToSymbol(c_wfTexBinding, &binding, sizeof(GWavefrontTextureBinding));
}

void launchStageShadeBucketed(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const int* d_shade_queues, const int* d_shade_counts, int capacity,
    int* d_queue_out, int* d_count_out,
    float* d_nee_f, int* d_nee_i, int* d_shadow_queue, int* d_shadow_count,
    const GTLASNode*  d_tlas,        // pkg55-C4 / pkg114
    const GInstance*  d_instances,   // pkg55-C4 / pkg114
    const GBLAS*      d_blas,        // pkg55-C4 / pkg114
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GVec3*      d_motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* d_materials,
    const ::GLight*    d_lights, int num_lights, float total_light_power,
    const GDedicatedLight* d_dedLights, int num_ded,   // pkg89-wavefront (C7)
    GLightTreeView    lightTree,
    int               max_depth,
    bool              useLuminanceOutput,
    bool              enableNEE,
    float             clampDirect, float clampIndirect,  // pkg157
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid,
    float             photonScale,
    // pkg159: per-pixel cryptomatte rank arrays (driver-owned; null/0 = off).
    float* d_cryptoObjectRanks, float* d_cryptoMaterialRanks, int cryptoDepth,
    bool              hasPrincipled,  // pkg178 Stage-3b D4
    // pkg186: hasTexture selects the <*,true> instantiation. The texture DATA is
    // NOT passed here — the driver publishes it to c_wfTexBinding (constant
    // memory) once per frame via setWavefrontTextureBinding, so this signature
    // (shared by the untextured fleet kernel) stays at its pre-pkg186 footprint.
    bool              hasTexture)
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
        // pkg178 Stage-3b D4: select the HasPrincipled specialization off the
        // host scene flag. The <false,*> instantiation carries zero
        // gpu_principled_* codegen (restores main's ~4456 B stage-shade
        // footprint); the <true,*> instantiation is byte-identical to today's
        // principled kernel. pkg186 adds the orthogonal HasTexture axis: the
        // <*,false> instantiation carries ZERO texture codegen (the fleet's
        // untextured scenes), so stageShadeBucketedKernel<false,false> must stay
        // register/stack-identical to the pre-pkg186 <false> kernel — the
        // acceptance check is a cuobjdump on that symbol (native sm_120). All four
        // are referenced below so they appear in the cubin for the register report.
        // pkg186: the texture arrays are NOT in this arg list — they live in the
        // __constant__ c_wfTexBinding symbol (setWavefrontTextureBinding, once per
        // frame), which is what keeps the untextured <false,false> signature at its
        // pre-pkg186 REG/STACK footprint (signature params cost +24 B stack).
        #define ASTRORAY_PKG186_SHADE_ARGS \
                state, hitBufs, d_shade_queues, d_shade_counts, capacity, \
                d_queue_out, d_count_out, \
                d_nee_f, d_nee_i, d_shadow_queue, d_shadow_count, \
                d_tlas, d_instances, d_blas, \
                d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials, \
                d_lights, num_lights, total_light_power, \
                d_dedLights, num_ded, lightTree, max_depth, \
                useLuminanceOutput, enableNEE, \
                clampDirect, clampIndirect, \
                photonGrid, hasPhotonGrid, photonScale, \
                d_cryptoObjectRanks, d_cryptoMaterialRanks, cryptoDepth
        // pkg184: hasPhotonGrid selects the <*,*,true> instantiation, which is the
        // ONLY one carrying the photonGridGatherKnn codegen. The fleet's non-photon
        // scenes launch <*,*,false>, whose ptxas footprint drops back below the
        // pre-pkg184 kernel (acceptance = cuobjdump on the <false,false,false>
        // symbol, native sm_120). All 8 are referenced so they land in the cubin.
        const bool hasPhotons = hasPhotonGrid;
        const void* kptr =
            hasPrincipled
                ? (hasTexture
                    ? (hasPhotons ? (const void*)stageShadeBucketedKernel<true, true, true>
                                  : (const void*)stageShadeBucketedKernel<true, true, false>)
                    : (hasPhotons ? (const void*)stageShadeBucketedKernel<true, false, true>
                                  : (const void*)stageShadeBucketedKernel<true, false, false>))
                : (hasTexture
                    ? (hasPhotons ? (const void*)stageShadeBucketedKernel<false, true, true>
                                  : (const void*)stageShadeBucketedKernel<false, true, false>)
                    : (hasPhotons ? (const void*)stageShadeBucketedKernel<false, false, true>
                                  : (const void*)stageShadeBucketedKernel<false, false, false>));
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_shade_bucketed_n7", kptr, blocks, threads);
        if (hasPrincipled && hasTexture && hasPhotons)
            stageShadeBucketedKernel<true, true, true><<<blocks, threads>>>(ASTRORAY_PKG186_SHADE_ARGS);
        else if (hasPrincipled && hasTexture)
            stageShadeBucketedKernel<true, true, false><<<blocks, threads>>>(ASTRORAY_PKG186_SHADE_ARGS);
        else if (hasPrincipled && hasPhotons)
            stageShadeBucketedKernel<true, false, true><<<blocks, threads>>>(ASTRORAY_PKG186_SHADE_ARGS);
        else if (hasPrincipled)
            stageShadeBucketedKernel<true, false, false><<<blocks, threads>>>(ASTRORAY_PKG186_SHADE_ARGS);
        else if (hasTexture && hasPhotons)
            stageShadeBucketedKernel<false, true, true><<<blocks, threads>>>(ASTRORAY_PKG186_SHADE_ARGS);
        else if (hasTexture)
            stageShadeBucketedKernel<false, true, false><<<blocks, threads>>>(ASTRORAY_PKG186_SHADE_ARGS);
        else if (hasPhotons)
            stageShadeBucketedKernel<false, false, true><<<blocks, threads>>>(ASTRORAY_PKG186_SHADE_ARGS);
        else
            stageShadeBucketedKernel<false, false, false><<<blocks, threads>>>(ASTRORAY_PKG186_SHADE_ARGS);
        #undef ASTRORAY_PKG186_SHADE_ARGS
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
// (the same XYZ conversion math as stageAccumulateXYZKernel -- the
// accumulate-at-death form; pkg157 moved the firefly clamp upstream to the
// per-contribution sites, see gpu_clampContribMW), zeroes its color (so an
// exhausted slot adds 0 on later passes), then claims the next unscheduled
// (pixel, sample) work
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
    uint64_t seed,
    float lambdaMin,
    float lambdaMax,
    int* count_out,      // pkg55-C7 perf: fused per-pass counter zeroing —
    int* shade_counts,   // replaces 3 cudaMemsetAsync launches per pass
    int* shadow_count,   // (~3.6k extra launches per 512-spp render).
    bool useLuminanceOutput)  // pkg55-C7: non-visible-band accumulation —
                              // grey band-mean radiance instead of the CMF
                              // XYZ projection (which is ~0 outside 380-780,
                              // silently zeroing all non-visible energy).
                              // Mirrors the deleted MW megakernel
                              // (multiwavelength_kernel.cu:510-518).
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    // Thread 0 zeroes the per-pass queue counters BEFORE the early-outs
    // (its own slot may be alive). Same-stream ordering makes this visible
    // to the intersect/shade/shadow launches that follow, exactly like the
    // memsets it replaces.
    if (idx == 0 && count_out != nullptr) {
        *count_out    = 0;
        *shadow_count = 0;
        #pragma unroll
        for (int m = 0; m < G_WF_NUM_MAT_TYPES; ++m) shade_counts[m] = 0;
    }
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
        GVec3 xyz;
        if (useLuminanceOutput) {
            // pkg55-C7: band-mean radiance as neutral grey (the MW megakernel
            // luminance convention). No CMF projection — the CMFs are ~0
            // outside the visible band. No lum>20 clamp here either: the MW
            // kernel applied none in luminance mode, and the CPU naive
            // multiwavelength reference is the parity target.
            float L = 0.f;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) L += rad.v[i];
            L = fmaxf(0.f, L / float(G_SPECTRUM_SAMPLES));
            xyz = GVec3(L, L, L);
        } else {
            GSampledWavelengths lambdas;
            lambdas.lambda[0] = state.lambda_0[idx];
            lambdas.lambda[1] = state.lambda_1[idx];
            lambdas.lambda[2] = state.lambda_2[idx];
            lambdas.lambda[3] = state.lambda_3[idx];
            lambdas.pdf[0] = state.lambda_pdf_0[idx];
            lambdas.pdf[1] = state.lambda_pdf_1[idx];
            lambdas.pdf[2] = state.lambda_pdf_2[idx];
            lambdas.pdf[3] = state.lambda_pdf_3[idx];
            // pkg157: the always-on, whole-path `lum > 20` clamp that used to
            // live here has been REMOVED -- see gpu_clampContribMW calls in
            // intersectPathSlot / shadePathSlot / stageShadowKernel, which now
            // clamp direct vs indirect contributions independently, per
            // bounce, mirroring the CPU fix (Renderer::clampContribSpectral)
            // and the deleted MW megakernel's identical removal (PR #515,
            // commit 1af7eca).
            xyz = gpu_spectrum_to_xyz(rad, lambdas);
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
    // pkg55-C5 / pkg113: flush the photon caustic XYZ contrib (if any) to the
    // dead path's pixel. INDEPENDENT of hasRad -- a path can carry photon
    // energy with zero spectral radiance (e.g. no NEE-visible lights), and the
    // MW kernel adds photonXYZ to the sample unconditionally
    // (multiwavelength_kernel.cu:502). Zero after adding: a dead slot that is
    // NOT reclaimed below stays dead and re-enters this block next pass -- the
    // zeroing (like color_* above) is the double-add guard.
    {
        float photon_x = state.photon_xyz_x[idx];
        float photon_y = state.photon_xyz_y[idx];
        float photon_z = state.photon_xyz_z[idx];
        if (photon_x != 0.f || photon_y != 0.f || photon_z != 0.f) {
            int pixel = state.pixel_index[idx];
            atomicAdd(&accum_xyz[pixel * 3 + 0], photon_x);
            atomicAdd(&accum_xyz[pixel * 3 + 1], photon_y);
            atomicAdd(&accum_xyz[pixel * 3 + 2], photon_z);
            state.photon_xyz_x[idx] = 0.f;
            state.photon_xyz_y[idx] = 0.f;
            state.photon_xyz_z[idx] = 0.f;
        }
    }

    // ---- Claim the next work item; leave the slot dead when exhausted.
    int w = atomicAdd(work_counter, 1);
    if (w >= total_work) return;
    int pixel  = w % numPixels;
    int sample = w / numPixels;
    initPathSlot(idx, pixel, sample, state, cam, width, height, seed,
                 lambdaMin, lambdaMax);
}

void launchStageRegen(
    GPUWavefrontState& state,
    float* d_accum_xyz,
    int* d_work_counter,
    int total_work,
    int numPixels,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed,
    float lambdaMin,
    float lambdaMax,
    int* d_count_out,      // pkg55-C7: fused counter zeroing (nullptr = skip)
    int* d_shade_counts,
    int* d_shadow_count,
    bool useLuminanceOutput)  // pkg55-C7: non-visible-band accumulation
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
            cam, width, height, seed,
            lambdaMin, lambdaMax,
            d_count_out, d_shade_counts, d_shadow_count,
            useLuminanceOutput);
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
    const GTLASNode*  d_tlas,        // pkg55-C4 / pkg114
    const GInstance*  d_instances,   // pkg55-C4 / pkg114
    const GBLAS*      d_blas,        // pkg55-C4 / pkg114
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GVec3*      d_motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* d_materials,
    bool              useLuminanceOutput,   // pkg157
    float             clampDirect, float clampIndirect)  // pkg157
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
            d_tlas, d_instances, d_blas,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials,
            useLuminanceOutput, clampDirect, clampIndirect);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_shadow launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

// ---------------------------------------------------------------------------
// pkg55-C2 MIS audit snapshot kernel. Runs the PRODUCTION intersect + shade
// halves for one bounce over every path with the deferred (parking) NEE
// branch enabled (nee_f != nullptr), so shadePathSlot records the real
// power-heuristic MIS pdfs into state.path_light_pdf / path_mis_pdf /
// path_mis_weight. This is the exact code the bucketed production pipeline
// runs (intersectPathSlot + shadePathSlot); it is invoked ONLY by the
// PostNEE_MIS snapshot harness, never by the render driver. The nee_f/nee_i/
// shadow buffers are throwaway parking scratch — the shadow trace is NOT run
// here; the audit inspects the shade-time MIS weight, not the occlusion.
// ---------------------------------------------------------------------------
template<bool HasPrincipled>  // pkg178 Stage-3b D4
__global__ void stageShadeNeeMisKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    float* nee_f, int* nee_i,
    int* shadow_queue, int* shadow_count, int nee_capacity,
    const GTLASNode*  tlas,        // pkg55-C4 / pkg114
    const GInstance*  instances,   // pkg55-C4 / pkg114
    const GBLAS*      blas,        // pkg55-C4 / pkg114
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GVec3*      motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    const GDedicatedLight* dedLights, int numDed,   // pkg89-wavefront (C7)
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth,
    bool              useLuminanceOutput,
    bool              enableNEE,
    float             clampDirect, float clampIndirect)  // pkg157
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= state.num_active) return;
    if (state.path_alive[idx] == 0) return;
    int matType = intersectPathSlot(idx, state, hitBufs, tlas, instances, blas,
                                    bvhNodes, prims, tris, spheres, motionVerts,
                                    materials, envMap, backgroundColor,
                                    hasBackgroundColor, worldMaxBounces,
                                    useLuminanceOutput, enableNEE,
                                    clampDirect, clampIndirect,
                                    lights, numLights, totalLightPower,
                                    dedLights, numDed, lightTree);  // pkg120+pkg181
    if (matType < 0) return;  // env miss / emissive hit: path died, no NEE.
    shadePathSlot<true, HasPrincipled>(idx, state, hitBufs, tlas, instances, blas,
                  bvhNodes, prims, tris, spheres, motionVerts,
                  materials, lights, numLights, totalLightPower,
                  dedLights, numDed, lightTree, max_depth,
                  nee_f, nee_i, shadow_queue, shadow_count, nee_capacity,
                  useLuminanceOutput, enableNEE,
                  clampDirect, clampIndirect,
                  astroray::photon::gpu::GPhotonGrid{}, false, 0.0f,
                  /*captureMis=*/true);  // pkg55-C7: snapshot harness captures
}

void launchStageShadeNeeMis(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    float* d_nee_f, int* d_nee_i,
    int* d_shadow_queue, int* d_shadow_count, int nee_capacity,
    const GTLASNode*  d_tlas,        // pkg55-C4 / pkg114
    const GInstance*  d_instances,   // pkg55-C4 / pkg114
    const GBLAS*      d_blas,        // pkg55-C4 / pkg114
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GVec3*      d_motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* d_materials,
    const ::GLight*    d_lights, int num_lights, float total_light_power,
    const GDedicatedLight* d_dedLights, int num_ded,   // pkg89-wavefront (C7)
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth,
    bool              useLuminanceOutput,
    bool              enableNEE,
    float             clampDirect, float clampIndirect,  // pkg157
    bool              hasPrincipled)  // pkg178 Stage-3b D4
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    // pkg178 Stage-3b D4: select the HasPrincipled specialization (see
    // launchStageShadeBucketed). Both referenced so both land in the cubin.
    if (hasPrincipled)
        stageShadeNeeMisKernel<true><<<blocks, threads>>>(
            state, hitBufs, d_nee_f, d_nee_i,
            d_shadow_queue, d_shadow_count, nee_capacity,
            d_tlas, d_instances, d_blas,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials,
            d_lights, num_lights, total_light_power,
            d_dedLights, num_ded, lightTree,
            envMap, backgroundColor, hasBackgroundColor, worldMaxBounces,
            max_depth, useLuminanceOutput, enableNEE,
            clampDirect, clampIndirect);
    else
        stageShadeNeeMisKernel<false><<<blocks, threads>>>(
            state, hitBufs, d_nee_f, d_nee_i,
            d_shadow_queue, d_shadow_count, nee_capacity,
            d_tlas, d_instances, d_blas,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials,
            d_lights, num_lights, total_light_power,
            d_dedLights, num_ded, lightTree,
            envMap, backgroundColor, hasBackgroundColor, worldMaxBounces,
            max_depth, useLuminanceOutput, enableNEE,
            clampDirect, clampIndirect);
    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        std::fprintf(stderr, "stage_shade_nee_mis launch error: %s\n",
                     cudaGetErrorString(err));
        throw std::runtime_error(cudaGetErrorString(err));
    }
}

}  // namespace astroray::wavefront

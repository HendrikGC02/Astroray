// gpu_wavefront_state.h — pkg55-B' Session N+3
//
// GPU SoA path-state buffers for the wavefront CUDA pipeline (REWRITTEN).
//
// Session N+3 scope:
//   - Replace the Phase A.1 curandState + RGB structure with WavefrontRNG + spectral.
//   - Mirror the CPU wavefront's CPUWavefrontState SoA layout (cpu_wavefront_state.h).
//   - Store WavefrontRNG as 4 POD members (pixel/sample/dimension/seed) so the
//     CUDA kernel can reconstruct the EXACT stream position the CPU carries.
//   - GSampledWavelengths + GSampledSpectrum (gpu_types.h) for spectral state.
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §4.2 Session N+3.
// Design: PR #296 §4.1, §4.2 (two-tier gate: CPU↔GPU bounded, not exact).
//
// References (Apache-2.0):
//   - intern/cycles/kernel/integrator/state.h (Cycles IntegratorState SoA)
//   - mmp/pbrt-v4 src/pbrt/wavefront/workitems.soa (PBRT-v4 SOA<RayWorkItem>)
//   - Laine, Karras, Aila 2013 §4 "Wavefront Path Tracing" (HPG 2013)
//   - CPU mirror: src/cpu/wavefront/cpu_wavefront_state.h

#ifndef ASTRORAY_GPU_WAVEFRONT_STATE_H
#define ASTRORAY_GPU_WAVEFRONT_STATE_H

#include <cstddef>
#include <cstdint>
#include "astroray/gpu_types.h"  // GVec3, GSampledWavelengths, GSampledSpectrum
#include "astroray/shader_vm.h"  // pkg219b GWavefrontProgramBinding
// pkg157: GPhotonGrid, needed by launchStageShadeBucketed's declaration below.
// Safe from any TU: gpu_photon_store.h is explicitly written to compile under
// both nvcc and pure C++ (its device-only helpers sit behind __CUDACC__), and
// it pulls in nothing beyond gpu_types.h + <cstdint>/<vector>.
#include "astroray/gpu_photon_store.h"

namespace astroray::wavefront {

// ---------------------------------------------------------------------------
// GPUWavefrontState — flat per-path device pointer arrays (spectral).
//
// This REPLACES the Phase A.1 IntegratorStateSoA (which used curandState + RGB).
// Session N+3 rewrites the GPU wavefront to match the CPU baseline:
//   - WavefrontRNG (PCG32) instead of curandState → bit-comparable thresholds.
//   - GSampledWavelengths + GSampledSpectrum instead of RGB throughput.
//   - Carried live RNG dimension counter so shade never reconstructs RNG.
//
// All pointers are device addresses. `capacity` is the maximum number of
// concurrent in-flight paths the buffers can hold. For Session N+3 (stage_init
// only), capacity = pixelCount * samples (1:1 mapping).
//
// Field meanings (per path slot i):
//   pixel_index[i]    — flat pixel index (y * width + x)
//   sample_index[i]   — per-pixel sample index (0..spp-1)
//   bounce[i]         — current bounce count (0 after init)
//
//   rng_pixel[i]      — WavefrontRNG.pixel (uint32_t)
//   rng_sample[i]     — WavefrontRNG.sample (uint32_t)
//   rng_dimension[i]  — WavefrontRNG.dimension (uint32_t) — the LIVE auto-incrementing counter
//   rng_seed[i]       — WavefrontRNG.seed (uint64_t)
//
//   ray_origin_*[i]   — primary ray origin (float x/y/z, separate arrays)
//   ray_direction_*[i]— primary ray direction (float x/y/z, ALREADY NORMALIZED)
//
//   lambdas[i]        — GSampledWavelengths (32 bytes = 8 floats)
//   throughput[i]     — GSampledSpectrum (16 bytes = 4 floats)
//   color[i]          — GSampledSpectrum radiance accumulator (16 bytes = 4 floats)
//
//   was_specular[i]   — bool (0/1)
//   path_alive[i]     — bool (0/1)
//
// The struct is POD; copy by value into kernels.
struct GPUWavefrontState {
    // Identity.
    int*      pixel_index   = nullptr;
    int*      sample_index  = nullptr;
    int*      bounce        = nullptr;

    // WavefrontRNG state (POD members, carried exactly).
    uint32_t* rng_pixel     = nullptr;
    uint32_t* rng_sample    = nullptr;
    uint32_t* rng_dimension = nullptr;
    uint64_t* rng_seed      = nullptr;

    // Ray state (ALREADY-NORMALIZED direction; restored verbatim).
    float*    ray_origin_x    = nullptr;
    float*    ray_origin_y    = nullptr;
    float*    ray_origin_z    = nullptr;
    float*    ray_direction_x = nullptr;
    float*    ray_direction_y = nullptr;
    float*    ray_direction_z = nullptr;
    // pkg55-C4: geometry motion time (pkg88-C.0). Sampled once per path at init
    // via gpu_mw_haltonBase2(sample_idx + 1), carried through all bounces (mirrors
    // multiwavelength_kernel.cu:448, 361). Static scenes: time=0 by default;
    // motion-enabled scenes thread motionVerts through intersect/occlude.
    float*    path_time       = nullptr;

    // Spectral state (gpu_types.h). GSampledWavelengths = 8 floats (lambda + pdf).
    // Store as separate component arrays for coalesced access.
    float*    lambda_0      = nullptr;
    float*    lambda_1      = nullptr;
    float*    lambda_2      = nullptr;
    float*    lambda_3      = nullptr;
    float*    lambda_pdf_0  = nullptr;
    float*    lambda_pdf_1  = nullptr;
    float*    lambda_pdf_2  = nullptr;
    float*    lambda_pdf_3  = nullptr;

    // GSampledSpectrum throughput = 4 floats.
    float*    throughput_0  = nullptr;
    float*    throughput_1  = nullptr;
    float*    throughput_2  = nullptr;
    float*    throughput_3  = nullptr;

    // GSampledSpectrum color (radiance accumulator) = 4 floats.
    float*    color_0       = nullptr;
    float*    color_1       = nullptr;
    float*    color_2       = nullptr;
    float*    color_3       = nullptr;

    // pkg55-C2 MIS audit instrumentation (NOT a transport change — written by
    // shadePathSlot's NEE branch where the values are already computed, and
    // never read by accumulation, so renders stay bit-identical). Inspected by
    // the PostNEE_MIS per-stage gate.
    //   path_light_pdf[i]  — NEE selection×solid-angle pdf s.lightPdf
    //                        (includes the light-tree pick pdf when resident).
    //   path_mis_pdf[i]    — BSDF pdf gpu_material_pdf(mat, rec, wo, s.wi).
    //   path_mis_weight[i] — resulting power-heuristic weight wt (Veach 1997).
    // Sentinel: path_light_pdf[i] == 0.0f means "no NEE fired at this slot".
    float*    path_light_pdf  = nullptr;
    float*    path_mis_pdf    = nullptr;
    float*    path_mis_weight = nullptr;

    // pkg120 (two-sided MIS): the BSDF pdf that generated this slot's CURRENT
    // continuation ray (written at shade after the BSDF sample). Unlike the
    // instrumentation fields above this one IS load-bearing for transport: the
    // intersect stage reads it when a diffuse-bounce continuation ray lands on
    // an emitter, to weight the BSDF-sampled emission by the power heuristic
    // against the reconstructed light-sampling pdf (gpu_reconstruct_light_pdf).
    float*    path_bsdf_pdf   = nullptr;

    // pkg55-C5 / pkg113: photon caustic contribution (XYZ) accumulated at primary
    // hit (bounce==0) from photonGridGatherKnn. Added to accum_xyz during regen
    // (after spectral color→XYZ conversion), matching MW kernel's per-sample XYZ
    // accumulation model. Zero for paths that don't hit photons.
    float*    photon_xyz_x    = nullptr;
    float*    photon_xyz_y    = nullptr;
    float*    photon_xyz_z    = nullptr;

    // pkg55-C6b / pkg24: the ReSTIR reservoir SoA has moved out of this
    // per-path-slot struct into a dedicated per-pixel struct GPUReservoirSoA
    // (below). The reservoir arrays are per-PIXEL (length numPixels) and
    // double-buffered (current/previous), so they cannot share this struct's
    // per-slot `capacity` sizing. (C6a placed the field decls here as a
    // placeholder; they were never allocated. C6b relocates them.)

    // Path-continuation flags.
    int*      was_specular  = nullptr;  // 0/1
    int*      path_alive    = nullptr;  // 0 = terminated, 1 = active

    // Sizing.
    int       capacity      = 0;        // total slot count
    int       num_active    = 0;        // [0, capacity); written by host
};

// Allocation / free helpers, defined in src/gpu/wavefront/wavefront_state.cu.
// `capacity` should be width*height*samples for Session N+3 1:1 pixel-to-slot.
// Returns true on success.
bool  allocateGPUWavefrontState(GPUWavefrontState& s, int capacity);
void  freeGPUWavefrontState(GPUWavefrontState& s);

// ---------------------------------------------------------------------------
// pkg55-C6b / pkg24: ReSTIR reservoir SoA (per-pixel, double-buffered).
//
// A flat, per-pixel mirror of the CPU `Reservoir<ReSTIRCandidate>` (reservoir.h)
// + `PixelHistory` (frame_state.h) — component arrays of length `numPixels`.
// The driver holds TWO instances in its persistent WfContext (current +
// previous) and swaps them per frame (device-pointer swap = the CPU
// FrameState::advanceFrame policy, frame_state.h:160). Reuse stages read the
// PREVIOUS buffer and write the CURRENT one, so the reuse is race-free exactly
// like the CPU (restir_di.cpp:20-31). Plan §5 layout.
struct GPUReservoirSoA {
    // Selected candidate y (ReSTIRCandidate, light_sample.h):
    float* res_y_pos_x      = nullptr;   // candidate.position
    float* res_y_pos_y      = nullptr;
    float* res_y_pos_z      = nullptr;
    float* res_y_normal_x   = nullptr;   // candidate.normal
    float* res_y_normal_y   = nullptr;
    float* res_y_normal_z   = nullptr;
    float* res_y_emission_x = nullptr;   // candidate.emission (RGB)
    float* res_y_emission_y = nullptr;
    float* res_y_emission_z = nullptr;
    float* res_y_pdf        = nullptr;   // candidate.pdf
    float* res_y_distance   = nullptr;   // candidate.distance
    // Reservoir bookkeeping (Bitterli 2020):
    float* res_w_sum        = nullptr;   // Reservoir.w_sum
    int*   res_M            = nullptr;   // Reservoir.M
    float* res_W            = nullptr;   // Reservoir.W (final RIS weight)
    // PixelHistory (temporal-validity gate, frame_state.h):
    float* meta_normal_x    = nullptr;   // PixelHistory.normal
    float* meta_normal_y    = nullptr;
    float* meta_normal_z    = nullptr;
    float* meta_depth       = nullptr;   // PixelHistory.depth
    int*   meta_valid       = nullptr;   // PixelHistory.valid (0/1)
    int    numPixels        = 0;
};

// Allocate/free the per-pixel reservoir SoA (wavefront_state.cu).
bool  allocateGPUReservoirSoA(GPUReservoirSoA& r, int numPixels);
void  freeGPUReservoirSoA(GPUReservoirSoA& r);
// Zero a reservoir SoA in place (cudaMemset all arrays) — the frame-start
// "clear current" step (mirrors ReservoirBuffer::clear, frame_state.h:69).
void  clearGPUReservoirSoA(GPUReservoirSoA& r);

// Session N+3 launchers. Defined in src/gpu/wavefront/stage_*.cu.
struct GPUWavefrontHitBuffers;  // forward decl; full definition below
// GMaterial is in the global namespace (gpu_types.h); referenced unqualified
// below — do NOT forward-declare here or it shadows the real type.

// stage_init: writes ray_origin/ray_direction/lambdas/throughput/rng_*/etc.
// for slot i. Uses WavefrontRNG (PCG32) to match CPU baseline.
// pkg162: this declaration MUST stay in sync with the definition in
// stage_init.cu. It previously declared only 6 parameters (`..., uint64_t seed,
// int sample_index = 0`) while the definition takes 8, making it a PHANTOM
// overload that no definition matched. It compiled only because
// gpu_wavefront_snapshot.cu carried a private re-declaration that shadowed it
// for that translation unit; that duplicate is now deleted and this is the
// single source of truth.
//
// The `= 0` default on sample_index was REMOVED rather than relocated: a
// defaulted parameter cannot precede non-defaulted ones, and all 6 call sites
// pass sample_index explicitly, so the default was never actually used.
void launchStageInit(
    GPUWavefrontState& state,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed,
    int sample_index,        // Session N+6: per-sample RNG keying
    float lambdaMin,
    float lambdaMax);

// Session N+3 part 2: intersect stage.
void launchStageIntersect_SessionN3(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres);

// Session N+3 part 2: Lambertian shade stage.
// NOTE: ::GMaterial is in the global namespace (gpu_types.h); we qualify with
// :: because unqualified `GMaterial` inside namespace astroray::wavefront
// caused NVCC to forward-declare an incomplete astroray::wavefront::GMaterial
// in some TUs and shadow the global type.
void launchStageShadeLambertian_SessionN3(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const ::GMaterial* d_materials,
    int num_materials);

// Session N+4: Light sampling (NEE) stage.
// GAreaLight is defined in gpu_types.h (global namespace); use ::GAreaLight to
// avoid shadowing with an in-namespace forward decl (incomplete-type errors).

void launchStageLightSample_SessionN4(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const ::GMaterial* d_materials,
    int num_materials,
    const ::GAreaLight* d_lights,
    int num_lights,
    const GBVHNode* d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle* d_tris,
    const GSphere* d_spheres);

// Session N+4: Russian roulette stage.
void launchStageRussianRoulette_SessionN4(
    GPUWavefrontState& state);

// (Hygiene 2026-08-11: the caller-less N+6/N+7 launchers launchStageAdvance /
// launchStageAdvanceQueued and their kernels were removed; the live path is
// stageRegen -> stageIntersectQueued -> stageShadeBucketed -> stageShadow.)

// Fills d_queue with 0..n-1 and *d_count = n (bounce-0 population).
void launchStageQueueIota(int* d_queue, int* d_count, int n);

// Session N+7 part 3: staged intersect/shade with material-bucketed shade
// queues (7 GMaterialType buckets, fixed stride = capacity). One shade
// launch covers all buckets with warp-coherent material types.
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
    bool              useLuminanceOutput,  // pkg55-C3 (was missing)
    bool              enableNEE,        // pkg156: gates the pkg120 two-sided-MIS leg
    float             clampDirect, float clampIndirect,  // pkg157
    // pkg120: light data for the two-sided-MIS emissive-hit reconstruction.
    const ::GLight*   d_lights, int num_lights, float total_light_power,
    // pkg181: dedicated lamps for the BSDF-ray lamp-intersection pass.
    const GDedicatedLight* d_dedLights, int num_ded,
    GLightTreeView    lightTree,
    int* d_vol_queue, int* d_vol_count,   // pkg199 Stage 2
    bool has_world_scatter,               // pkg199 Stage 2 fleet-isolation axis
    bool has_light_pass_aovs);            // pkg198 Stage 2 pass-AOV axis

// pkg199 Stage 2 — dedicated volume-scatter wavefront stage (between intersect
// and shade). Drains the volume-scatter queue, parks the phase-sampled
// NEE-through-medium into the shared nee_f/nee_i lanes + shadow queue, and emits
// the HG continuation ray, requeuing survivors into queue_out for the next bounce.
void launchStageVolumeScatter(
    GPUWavefrontState& state,
    const int* d_vol_queue, const int* d_vol_count,
    int* d_queue_out, int* d_count_out,
    float* d_nee_f, int* d_nee_i, int* d_shadow_queue, int* d_shadow_count,
    int nee_capacity,
    const GPrimitive* d_prims, const GTriangle* d_tris, const GSphere* d_spheres,
    const ::GLight* d_lights, int num_lights, float total_light_power,
    const GDedicatedLight* d_dedLights, int num_ded,
    GLightTreeView lightTree,
    int max_depth, bool useLuminanceOutput, bool enableNEE);

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
    bool              useLuminanceOutput,  // pkg55-C3 (was missing)
    bool              enableNEE,           // pkg55-C3 (was missing)
    float             clampDirect, float clampIndirect,  // pkg157
    // pkg157 FIX (pre-existing defect, exposed by this package): these three
    // photon params have been on the DEFINITION (stage_advance.cu) since
    // pkg55-C5/pkg113 but were never added here, so this declaration was a
    // PHANTOM overload that no definition matched. It compiled only because
    // gpu_wavefront_snapshot.cu carried a private re-declaration that shadowed
    // it. That duplicate is now deleted; this declaration is the single source
    // of truth and must be kept in sync with stage_advance.cu.
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid,
    float             photonScale,
    // pkg159: per-PIXEL cryptomatte rank arrays (numPixels*depth*2 floats
    // each), allocated + zeroed by the driver and copied back to
    // Camera::cryptoObjectBuffer / cryptoMaterialBuffer after the render.
    // cryptoDepth == 0 (or null pointers) = cryptomatte disabled, the default.
    // The shade stage inserts ATOMICALLY (crypto_insert_atomic, cryptomatte.h)
    // because path regeneration puts many concurrent slots on one pixel.
    float* d_cryptoObjectRanks, float* d_cryptoMaterialRanks, int cryptoDepth,
    // pkg178 Stage-3b D4: scene-content flag from scene_upload. true selects the
    // stageShadeBucketedKernel<true,*> (principled) instantiation; false selects
    // <false,*>, which compiles out all gpu_principled_* codegen for the fleet-wide
    // non-principled perf restore. See pkg178-stage3-d4-and-forks-decision.md §2b.
    bool hasPrincipled,
    // pkg186: hasTexture=true selects stageShadeBucketedKernel<*,true>; false
    // selects <*,false>, which compiles out ALL texture codegen. The texture DATA
    // is published to constant memory once per frame via
    // setWavefrontTextureBinding (below) — NOT passed here — so this signature
    // (shared by the untextured fleet kernel) keeps its pre-pkg186 REG/STACK.
    bool hasTexture,
    // pkg189: hasDispersion=true selects stageShadeBucketedKernel<*,*,*,true>,
    // the only instantiations carrying the hero-λ collapse SoA write-back for
    // dispersive refraction; false selects <*,*,*,false>, byte-identical to the
    // pre-pkg189 kernels. Host-side flag (any uploaded material isDispersive).
    bool hasDispersion,
    // pkg198 Stage 2: hasLightPassAOVs=true selects
    // stageShadeBucketedKernel<*,*,*,*,true>, which carries the first-bounce
    // classification lock; false selects <*,*,*,*,false>, byte-identical to the
    // pre-pkg198 kernels (254/3352/1700 — the REGISTER PROBE result, PR #620). The
    // pass buffers ride in the __constant__ c_wfLpBinding, not this signature.
    bool hasLightPassAOVs,
    // pkg219b: hasProgram=true selects stageShadeBucketedKernel<*,*,*,*,*,true>,
    // which carries the per-texel op-VM; false selects <…,false>, byte-identical
    // to the pre-pkg219b kernels (the register-probe gate). The program array +
    // per-material index ride in the __constant__ c_wfProgBinding, not this
    // signature.
    bool hasProgram,
    // pkg223: hasNormalPerturb=true selects stageShadeBucketedKernel<…,true>,
    // which carries the tangent-space normal-map perturbation; false selects
    // <…,false>, byte-identical to the pre-pkg223 kernels (register-probe gate).
    // The normal-texture arrays ride c_wfTexBinding (matNormalTexId/Strength),
    // NOT this signature.
    bool hasNormalPerturb);

// pkg186 — publish the frame's image-texture arrays into the shade kernel's
// __constant__ binding. Call ONCE per frame before launchStageShadeBucketed (only
// for scenes with textures); see stage_advance.cu / GWavefrontTextureBinding.
void setWavefrontTextureBinding(const GWavefrontTextureBinding& binding);

// pkg219b — publish the frame's op-VM program array + per-material index into the
// shade kernel's __constant__ binding. Call ONCE per frame before
// launchStageShadeBucketed (only for scenes with a program material); see
// stage_advance.cu / GWavefrontProgramBinding (astroray/shader_vm.h).
void setWavefrontProgramBinding(const GWavefrontProgramBinding& binding);

// pkg197 — publish the frame's first-hit denoise-guide output pointers into the
// intersect stage's __constant__ binding. Call ONCE per frame before the render
// loop. Pass all-null (the default) to disable guide capture. See
// stage_advance.cu / GWavefrontGuideBinding.
void setWavefrontGuideBinding(const GWavefrontGuideBinding& binding);

// pkg198 Stage 2 — publish the frame's light-path pass buffers into the shade/
// intersect/shadow/volume/regen kernels' __constant__ binding. Call ONCE per frame
// before the render loop. Pass passAccum==nullptr (the default) to disable the
// partition (fleet renders byte-identical). See stage_advance.cu /
// GWavefrontLightPassBinding.
void setWavefrontLightPassBinding(const GWavefrontLightPassBinding& binding);

// pkg199 Stage 1 — publish the frame's homogeneous world-volume medium into the
// wavefront's __constant__ binding. Call ONCE per frame (cuda_wavefront_render).
// Pass hasVolume==0 (the default vacuum) to disable the Beer-Lambert branch in
// intersectPathSlot/stageShadowKernel. See stage_advance.cu / GWorldVolume.
void setWavefrontWorldVolume(const GWorldVolume& volume);

// pkg201 Stage 2 (Finding F, transparent film) — publish the frame's bounce-0
// background-miss coverage accumulator (numPixels floats, or nullptr to disable).
// intersectPathSlot atomicAdds 1.0 into c_wfMissCoverage[pixel] for every
// primary-ray sample that misses to the background; the driver derives per-pixel
// alpha = clamp(1 - miss/samples, 0, 1). Null (the default) leaves the alpha
// buffer opaque (1.0) — byte-identical renders. See stage_advance.cu.
void setWavefrontMissCoverage(float* coverage);

// pkg201 Stage 2 (Finding D, pixel filter) — publish the frame's pixel
// reconstruction filter for filter importance sampling of the primary-ray
// sub-pixel offset (type 0=Box/1=Gaussian/2=Blackman-Harris; width in pixels).
// Box ignores width and is byte-identical to the pre-pkg201 default; only
// Gaussian/Blackman-Harris honour width (offsets cross pixel boundaries for
// width>1). Read by stage_init.cu::filterSample at primary-ray generation.
void setWavefrontPixelFilter(int type, float width);

// pkg55-B' shadow stage: lean occlusion + lazy resolve over the NEE
// samples parked by the deferring bucketed shade. nee_f/nee_i lane counts
// are G_WF_NEE_F_LANES / G_WF_NEE_I_LANES (field-major); see the
// stage_advance.cu parking layout.
// pkg89-wavefront (C7): lanes 11-13 = dedEmissionRGB, int lane 2 =
// isDedicated (dedGeoScale is folded into the parked scale at shade time).
// pkg157: int lane 3 = the bounce depth the NEE sample was taken at. The
// deferred shadow-resolve kernel runs in a LATER launch after shadePathSlot
// may already have advanced state.bounce[idx] to bounce+1 (or left it
// unchanged if RR/BSDF-pdf killed the path first, ambiguously) -- so the
// bounce needed for the pkg144 direct/indirect clamp split must be parked
// here rather than re-read from state at resolve time.
// pkg199: float lane 14 = geomDist, the TRUE vertex->light distance for the
// world-volume Beer-Lambert Tr in stageShadowKernel. Parked SEPARATELY from
// lane 6 (maxDist), which is a 1e30 occlusion sentinel for sphere/distant
// sources and would collapse fogged NEE to zero if used as a path length.
// pkg204: int lane 4 = volume-scatter direct/indirect encoding. The dedicated
// volume-scatter stage parks (bounce+1) for a FIRST-interaction in-scatter NEE
// (CPU firstInteraction => PASS_VOLUME_DIRECT) and -(bounce+1) for a deeper
// scatter. The shadow-resolve kernel routes fc==3 NEE to PASS_VOLUME_DIRECT
// only when the parked value is positive AND its (bounce+1) matches the NEE's
// own parked bounce (int lane 3) -- so a surface-after-fog NEE (firstCat locked
// to 3, its stale lane-4 from an EARLIER scatter's bounce a<b) never false-
// matches and correctly falls to PASS_VOLUME_INDIRECT. Read-only in the shadow
// kernel (no scratch mutation); zeroed per render so bounce 0's first scatter
// (enc=1) never aliases the memset default (enc=0 => -1 != any bounce).
constexpr int G_WF_NEE_F_LANES = 15;
constexpr int G_WF_NEE_I_LANES = 5;
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
    float             clampDirect, float clampIndirect);  // pkg157

// Session N+7 part 4: path regeneration -- dense pass accumulating dead
// paths' radiance (atomic, per-pixel) then refilling slots from a global
// (pixel, sample) work counter. Pool stays ~full; launches amortize across
// all samples (Laine 2013 sec. 4).
void launchStageRegen(
    GPUWavefrontState& state,
    float* d_accum_xyz,
    int* d_work_counter,
    int total_work,
    int numPixels,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed,
    float lambdaMin,        // pkg55-C3
    float lambdaMax,        // pkg55-C3
    int* d_count_out,       // pkg55-C7: fused per-pass counter zeroing
    int* d_shade_counts,    //   (replaces 3 cudaMemsetAsync per pass;
    int* d_shadow_count,    //   nullptr = skip)
    int* d_vol_count,       // pkg199 Stage 2: volume-scatter queue counter (nullptr = skip)
    bool useLuminanceOutput);  // pkg55-C7: grey band-mean accumulation for
                               // non-visible bands (CMF XYZ is ~0 there)

// pkg55-C2 MIS audit: instrumented one-bounce intersect+shade over all paths
// that runs the PRODUCTION intersectPathSlot + shadePathSlot (deferred/parking
// NEE branch — the exact code the bucketed production pipeline uses), so the
// power-heuristic MIS captured in state.path_light_pdf / path_mis_pdf /
// path_mis_weight is the real production weight. Test-only (the PostNEE_MIS
// snapshot harness); NOT used by the render driver.
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
    bool              useLuminanceOutput,  // pkg55-C3 (was missing)
    bool              enableNEE,           // pkg55-C3 (was missing)
    float             clampDirect, float clampIndirect,  // pkg157
    bool              hasPrincipled);  // pkg178 Stage-3b D4 (snapshot launcher; passed res.hasPrincipled)

// Session N+3 part 2: Hit record fields (extend GPUWavefrontState for intersect->shade flow).
// These are passed as separate device pointers; will be folded into GPUWavefrontState
// struct after Session N+3 verification.
struct GPUWavefrontHitBuffers {
    float* hit_t            = nullptr;
    float* hit_point_x      = nullptr;
    float* hit_point_y      = nullptr;
    float* hit_point_z      = nullptr;
    float* hit_normal_x     = nullptr;
    float* hit_normal_y     = nullptr;
    float* hit_normal_z     = nullptr;
    float* hit_tangent_x    = nullptr;
    float* hit_tangent_y    = nullptr;
    float* hit_tangent_z    = nullptr;
    float* hit_bitangent_x  = nullptr;
    float* hit_bitangent_y  = nullptr;
    float* hit_bitangent_z  = nullptr;
    int*   hit_material_id  = nullptr;
    int*   hit_prim_id      = nullptr;  // N+7 part 3: GHitRecord.primId carry
    int*   hit_front_face   = nullptr;  // 0/1
    int*   hit_is_delta     = nullptr;  // 0/1
    int*   hit_valid        = nullptr;  // 0 = miss, 1 = hit
};

// Allocation helper for hit buffers. Returns true on success.
bool allocateGPUWavefrontHitBuffers(GPUWavefrontHitBuffers& hb, int capacity);
void freeGPUWavefrontHitBuffers(GPUWavefrontHitBuffers& hb);

// ---------------------------------------------------------------------------
// pkg55-C6b / pkg24: ReSTIR-DI wavefront stage launchers (stage_restir.cu).
//
// These run once per primary/bounce-0 shade over `numPixels` pixels (1 thread
// per pixel — no atomics into the reservoir, so the reservoir arithmetic is
// race-free and deterministic). Stage order mirrors the CPU restir_di.cpp
// sampleFull direct-lighting block: RIS -> [temporal] -> [spatial] -> resolve.
// The driver (cuda_wavefront_render_restir) drives one primary pass per sample.
// ---------------------------------------------------------------------------

// Primary pass: init the bounce-0 ray + intersect for every pixel (slot=pixel).
// Writes env/emissive radiance into state.color and parks the shading hit in
// hitBufs (hit_valid=1) for RIS. Reuses the shared initPathSlot/intersectPathSlot.
void launchStageRestirPrimary(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const GCameraParams& cam,
    int width, int height, int sample_index, uint64_t seed,
    float lambdaMin, float lambdaMax,
    const GTLASNode*  d_tlas,
    const GInstance*  d_instances,
    const GBLAS*      d_blas,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GVec3*      d_motionVerts,
    const ::GMaterial* d_materials,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    bool              useLuminanceOutput,
    float             clampDirect, float clampIndirect);  // pkg157

// Initial RIS (Bitterli 2020, Algorithm 1) over the parked primary hits.
void launchStageRestirInitialRIS(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    GPUReservoirSoA& cur,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const ::GMaterial* d_materials,
    const ::GLight*    d_lights, int num_lights, float total_light_power,
    GLightTreeView    lightTree,
    int numCandidates, int mCap, int numPixels);

// Temporal reuse (Algorithm 2) — merge previous frame's reservoir at the same
// pixel, gated by isTemporallyValid.
void launchStageRestirTemporalReuse(
    GPUWavefrontState& state,
    GPUReservoirSoA& cur,
    const GPUReservoirSoA& prev,
    int mCap, int numPixels);

// Spatial reuse (Algorithm 3) — merge validity-gated random neighbours from the
// previous frame's buffer (device twin of selectSpatialNeighbors).
void launchStageRestirSpatialReuse(
    GPUWavefrontState& state,
    GPUReservoirSoA& cur,
    const GPUReservoirSoA& prev,
    int width, int height,
    int spatialRadius, int spatialNeighbors, int mCap, int numPixels);

// Resolve — finalize weight, shadow ray (gpu_tlas_occluded), BSDF eval,
// accumulate throughput·f·L·W + primary env/emission into accum_xyz.
void launchStageRestirResolve(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    GPUReservoirSoA& cur,
    float* d_accum_xyz,
    const GTLASNode*  d_tlas,
    const GInstance*  d_instances,
    const GBLAS*      d_blas,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GVec3*      d_motionVerts,
    const ::GMaterial* d_materials,
    int numPixels,
    bool              useLuminanceOutput,   // pkg157
    float             clampDirect, float clampIndirect);  // pkg157

}  // namespace astroray::wavefront

#endif  // ASTRORAY_GPU_WAVEFRONT_STATE_H

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

// Session N+3 launchers. Defined in src/gpu/wavefront/stage_*.cu.
struct GPUWavefrontHitBuffers;  // forward decl; full definition below
// GMaterial is in the global namespace (gpu_types.h); referenced unqualified
// below — do NOT forward-declare here or it shadows the real type.

// stage_init: writes ray_origin/ray_direction/lambdas/throughput/rng_*/etc.
// for slot i. Uses WavefrontRNG (PCG32) to match CPU baseline.
void launchStageInit(
    GPUWavefrontState& state,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed,
    int sample_index = 0);  // Session N+6: per-sample RNG keying

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

// Session N+6: full one-bounce advance — device twin of CPU
// path_kernel.cpp::advance_one_bounce (intersect -> env-miss -> emissive ->
// NEE -> RR -> BSDF -> next ray). Self-contained (does its own intersect);
// the N+3..N+5 per-stage kernels remain as the gated diff instruments.
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
    bool              sync = true);  // N+7: render driver passes false, syncs once per render

// Session N+7 part 2: queued advance + compaction. queue/count buffers are
// device pointers; the host never reads the counters (zero-sync driver).
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
    int               max_depth);

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
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const ::GMaterial* d_materials,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces);

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
    int               max_depth);

// pkg55-B' shadow stage: lean occlusion + lazy resolve over the NEE
// samples parked by the deferring bucketed shade. nee_f = 11 floats/slot
// (field-major), nee_i = 2 ints/slot; see stage_advance.cu layout consts.
void launchStageShadow(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const float* d_nee_f, const int* d_nee_i,
    const int* d_shadow_queue, const int* d_shadow_count, int nee_capacity,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const ::GMaterial* d_materials);

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
    uint64_t seed);

// Session N+7: device-side per-sample XYZ accumulation (radiance -> XYZ ->
// firefly clamp -> += accum). accum_xyz is 3 floats per slot, zeroed by the
// driver before the first sample round.
void launchStageAccumulateXYZ(
    GPUWavefrontState& state,
    float* d_accum_xyz);

// Session N+5: Metal shade stage.
void launchStageShadeMetalGPU(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const ::GMaterial* d_materials,
    int num_materials);

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

}  // namespace astroray::wavefront

#endif  // ASTRORAY_GPU_WAVEFRONT_STATE_H

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

// Session N+3 launchers. Defined in src/gpu/wavefront/stage_init.cu.

// stage_init: writes ray_origin/ray_direction/lambdas/throughput/rng_*/etc.
// for slot i. Uses WavefrontRNG (PCG32) to match CPU baseline.
void launchStageInit(
    GPUWavefrontState& state,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed);

}  // namespace astroray::wavefront

#endif  // ASTRORAY_GPU_WAVEFRONT_STATE_H

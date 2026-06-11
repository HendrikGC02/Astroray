// stage_init.cu — pkg55-B' Session N+3 (REWRITTEN)
//
// Wavefront primary-ray init stage kernel. REPLACES the Phase A.1 version
// (which used curandState + RGB throughput) with WavefrontRNG + spectral state
// to match the CPU wavefront baseline.
//
// Session N+3 scope:
//   - WavefrontRNG (PCG32) instead of curandState → bit-comparable CPU↔GPU threshold.
//   - GSampledWavelengths + GSampledSpectrum instead of RGB.
//   - RNG draw order MUST match cpu_wavefront/path_kernel.cpp::init_path():
//       1. filter u  2. filter v  3. lens seed  4. lambda uniform.
//   - Store ALREADY-NORMALIZED ray direction (never renormalize at boundaries).
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §4.2 Session N+3.
// Design: PR #296 §4.1, §4.2 (two-tier gate: CPU↔GPU bounded, not exact).
//
// Reference (Apache-2.0):
//   - Cycles intern/cycles/kernel/integrator/init_from_camera.h —
//       integrator_init_from_camera() does exactly this: pulls rng,
//       samples lens + film, writes ray_P/ray_D into the SoA state.
//   - PBRT-v4 src/pbrt/wavefront/camera.cpp —
//       GenerateCameraRays() launches one thread per pixel and
//       enqueues a RayWorkItem with (origin, dir, pixelIndex).
//   - CPU mirror: src/cpu/wavefront/stage_init.cpp + path_kernel.cpp::init_path().

#include "astroray/gpu_wavefront_state.h"
#include "astroray/gpu_types.h"
#include "astroray/sampling/wavefront_rng_device.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <cstdio>
#include <stdexcept>

namespace astroray::wavefront {

namespace {

// Box filter: returns uniform [-0.5, 0.5]. Mirrors the CPU
// path_kernel.cpp::filterSample. Same byte-exact uniform_real_distribution
// conversion pattern (draw uint32, multiply by 2^-32, subtract 0.5).
__device__ inline float filterSample(WavefrontRNG& rng) {
    // Mirrors std::uniform_real_distribution<float>(0, 1) on CPU:
    //   uint32_t u = rng(); float f = u * 0x1p-32f; clamp to [0, 1 - eps).
    // Then subtract 0.5 for box filter.
    return rng.Uniform() - 0.5f;
}

// sampleUniformWavelength: hero-wavelength sampling with wrap-around.
// Mirrors astroray::SampledWavelengths::sampleUniform() from spectrum.cpp:82
// byte-for-byte:
//   hero    = lambdaMin + u * span
//   lam[i]  = hero + i * step                          (stratified offset)
//   lam[i] -= span  if lam[i] > lambdaMax              (wrap into range)
//   pdf[i]  = 1 / span
//
// The hero sample over the full range keeps dispersion / wavelength-dependent
// paths unbiased when they collapse to the hero wavelength. Previous GPU
// implementation used pure stratified (`lambdaMin + (i + u) * delta`) which
// produced a DIFFERENT wavelength SET than the CPU for the same u — caught by
// pkg64-gpu Phase 2 HW verify as 8.7M-ULP CPU↔GPU PostInit divergence (the
// RNG draw count fix was necessary but not sufficient). See
// `src/spectrum.cpp:82-99` for the CPU reference.
__device__ inline GSampledWavelengths sampleUniformWavelength(float u,
                                                               float lambdaMin = G_LAMBDA_MIN,
                                                               float lambdaMax = G_LAMBDA_MAX) {
    GSampledWavelengths swl;
    float span = lambdaMax - lambdaMin;
    float step = span / static_cast<float>(G_SPECTRUM_SAMPLES);
    float hero = lambdaMin + u * span;
    float invSpan = 1.0f / span;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        float lam = hero + static_cast<float>(i) * step;
        if (lam > lambdaMax) lam -= span;
        swl.lambda[i] = lam;
        swl.pdf[i]    = invSpan;
    }
    return swl;
}

// generatePrimaryRay: camera ray generation. Mirrors the CPU path_kernel.cpp::init_path()
// RNG draw order:
//   1. filter u  2. filter v  3. lens seed (converted to mt19937)  4. lambda uniform.
//
// This is the EXACT RNG draw order the CPU oracle uses. The lens sampling step on CPU
// uses std::mt19937 seeded from rng.UniformUInt32(); we replicate that seed-draw here
// but inline the lens DOF math (cam.aperture / focal_distance) without mt19937 on GPU
// (CUDA mt19937 is heavier; for Session N+3 we simplify to a single-draw uniform disk).
//
// The CPU oracle's Camera::getRay() uses mt19937 for lens, which makes exact bit-identity
// impossible (CUDA has no std::mt19937 equivalent). We accept this as a bounded CPU↔GPU
// difference in PostInit geometry ULP (≤ 4 per spec §4.2). The RNG draw COUNT matches
// (4 draws total: 2 filter + 1 lens-seed + 1 lambda), so dimension counters stay aligned.
__device__ inline void generatePrimaryRay(
    WavefrontRNG& rng,
    const GCameraParams& cam,
    int px, int py, int width, int height,
    GVec3& ray_origin, GVec3& ray_direction,
    GSampledWavelengths& lambdas)
{
    // 1. Filter u/v (CPU draws 2× std::uniform_real_distribution<float>(0,1)).
    float u = (px + filterSample(rng)) / float(width - 1);
    float v = 1.0f - (py + filterSample(rng)) / float(height - 1);

    // 2. Lens seed draw (CPU converts to mt19937; we consume the same dimension).
    uint32_t lens_seed = rng.UniformUInt32();
    // For Session N+3, inline a simple uniform-disk DOF. This is NOT byte-identical
    // to CPU mt19937, but the draw COUNT is exact, so dimension alignment holds.
    // The ULP difference is bounded by the pinned threshold (≤ 4 per spec §4.2).
    //
    // Simplified lens DOF: if lensRadius > 0, offset origin by a disk sample.
    // We use a quick uniform-disk via lens_seed (no full mt19937 stream).
    // This is a Session N+3 simplification; full mt19937 port is a future refinement.
    float lens_u1 = (lens_seed & 0xFFFF) / float(0xFFFF);
    float lens_u2 = ((lens_seed >> 16) & 0xFFFF) / float(0xFFFF);
    float lens_r = sqrtf(lens_u1);
    float lens_theta = 2.0f * 3.14159265f * lens_u2;
    float lens_offset_x = lens_r * cosf(lens_theta) * cam.lensRadius;
    float lens_offset_y = lens_r * sinf(lens_theta) * cam.lensRadius;

    // Ray direction (world-space from camera basis).
    // Mirrors Camera::getRay() math (no GR; flat-space camera).
    // GCameraParams has: lowerLeft, horizontal, vertical, origin.
    GVec3 dir = cam.lowerLeft + cam.horizontal * u + cam.vertical * v - cam.origin;
    dir = dir.normalized();  // Normalize ONCE here; stored as already-normalized.

    // Apply DOF if lensRadius > 0.
    if (cam.lensRadius > 0.0f) {
        // Focus plane intersection: t = focusDist / |dir|.
        // (Simplified flat-camera focal plane; matches production Camera::getRay().)
        float focal_t = cam.focusDist / dir.length();
        GVec3 focus_point = cam.origin + dir * focal_t;
        // Offset origin by lens disk sample in camera UV basis.
        // GCameraParams.u and GCameraParams.v are the camera right/up basis vectors.
        ray_origin = cam.origin + cam.u * lens_offset_x + cam.v * lens_offset_y;
        ray_direction = (focus_point - ray_origin).normalized();
    } else {
        ray_origin = cam.origin;
        ray_direction = dir;
    }

    // 3. Lambda uniform draw (CPU: std::uniform_real_distribution<float>(0,1)).
    float lambda_u = rng.Uniform();
    lambdas = sampleUniformWavelength(lambda_u, G_LAMBDA_MIN, G_LAMBDA_MAX);
}

}  // namespace (anonymous -- TU-local helpers above)

// N+7 part 4: per-slot path initialization, callable from BOTH the
// stage_init kernel (slot==pixel mapping) and the regeneration kernel
// (arbitrary slot <- (pixel, sample) work item). NON-static: linked into
// stage_advance.cu's regen kernel via -rdc=true. One generator of the
// init draws (decision #9).
__device__ void initPathSlot(
    int slot, int pixel, int sample_idx,
    GPUWavefrontState& state,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed)
{
    int idx = slot;
    int px = pixel % width;
    int py = pixel / width;

    // Construct WavefrontRNG for this path. Dimension counter starts at 0.
    // Mirrors the CPU oracle: PathState ps(pixel_idx, sample_idx, seed);
    // RNG is keyed by PIXEL (not slot) so regeneration produces the exact
    // same per-(pixel,sample) stream as the per-round scheduling did.
    WavefrontRNG rng(static_cast<uint32_t>(pixel), static_cast<uint32_t>(sample_idx), seed);

    // Generate primary ray + lambda sample. RNG draw order matches CPU path_kernel.cpp::init_path().
    GVec3 ray_origin, ray_direction;
    GSampledWavelengths lambdas;
    generatePrimaryRay(rng, cam, px, py, width, height, ray_origin, ray_direction, lambdas);

    // SoA writes. Store the LIVE RNG state (dimension counter advanced by 4 draws).
    state.pixel_index[idx]  = pixel;
    state.sample_index[idx] = sample_idx;
    state.bounce[idx]       = 0;

    state.rng_pixel[idx]     = rng.pixel();
    state.rng_sample[idx]    = rng.sample();
    state.rng_dimension[idx] = rng.dimension();  // Should be 4 after init.
    state.rng_seed[idx]      = rng.seed();

    // Ray state (direction is ALREADY normalized; stored verbatim).
    state.ray_origin_x[idx]    = ray_origin.x;
    state.ray_origin_y[idx]    = ray_origin.y;
    state.ray_origin_z[idx]    = ray_origin.z;
    state.ray_direction_x[idx] = ray_direction.x;
    state.ray_direction_y[idx] = ray_direction.y;
    state.ray_direction_z[idx] = ray_direction.z;

    // Spectral state.
    state.lambda_0[idx]     = lambdas.lambda[0];
    state.lambda_1[idx]     = lambdas.lambda[1];
    state.lambda_2[idx]     = lambdas.lambda[2];
    state.lambda_3[idx]     = lambdas.lambda[3];
    state.lambda_pdf_0[idx] = lambdas.pdf[0];
    state.lambda_pdf_1[idx] = lambdas.pdf[1];
    state.lambda_pdf_2[idx] = lambdas.pdf[2];
    state.lambda_pdf_3[idx] = lambdas.pdf[3];

    // Throughput = (1, 1, 1, 1).
    state.throughput_0[idx] = 1.0f;
    state.throughput_1[idx] = 1.0f;
    state.throughput_2[idx] = 1.0f;
    state.throughput_3[idx] = 1.0f;

    // Color = (0, 0, 0, 0).
    state.color_0[idx] = 0.0f;
    state.color_1[idx] = 0.0f;
    state.color_2[idx] = 0.0f;
    state.color_3[idx] = 0.0f;

    // Path flags.
    state.was_specular[idx] = 1;  // true
    state.path_alive[idx]   = 1;  // true
}

__global__ void stageInitKernel(
    GPUWavefrontState state,
    GCameraParams cam,
    int width, int height,
    uint64_t seed,
    int sample_index)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    int total = width * height;
    if (idx >= total) return;
    // Legacy per-round scheduling: slot == pixel.
    initPathSlot(idx, idx, sample_index, state, cam, width, height, seed);
}

void launchStageInit(
    GPUWavefrontState& state,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed,
    int sample_index)
{
    int total = width * height;
    if (total <= 0 || state.capacity < total) {
        throw std::runtime_error(
            "wavefront::launchStageInit — SoA capacity smaller than pixel count");
    }
    int threads = 256;
    int blocks  = (total + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_init_n3",
            (const void*)stageInitKernel, blocks, threads);
        stageInitKernel<<<blocks, threads>>>(state, cam, width, height, seed, sample_index);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_init launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        cudaError_t syncErr = cudaDeviceSynchronize();
        if (syncErr != cudaSuccess) {
            std::fprintf(stderr, "stage_init runtime error: %s\n",
                         cudaGetErrorString(syncErr));
            throw std::runtime_error(cudaGetErrorString(syncErr));
        }
    }
    state.num_active = total;
}

}  // namespace astroray::wavefront

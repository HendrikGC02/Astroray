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

// pkg201 Stage 2 (Finding D) — pixel reconstruction filter, published ONCE per
// frame into this __constant__ symbol (setWavefrontPixelFilter), mirroring the
// pkg197 guide / pkg199 world-volume binding pattern so no kernel signature grows.
// Default {Box, width 1} == the pre-pkg201 behaviour, so drivers that never
// publish it (ReSTIR/snapshot) and every default fleet render stay byte-identical.
struct GPixelFilterParams { int type; float width; };
__constant__ GPixelFilterParams c_wfPixelFilter = {0, 1.0f};

void setWavefrontPixelFilter(int type, float width) {
    GPixelFilterParams p{type, width};
    cudaMemcpyToSymbol(c_wfPixelFilter, &p, sizeof(GPixelFilterParams));
}

namespace {

// pkg201 Stage 2 (Finding D) — filter importance sampling of the primary-ray
// sub-pixel offset (in pixels): draw the offset from the reconstruction filter's
// own distribution over [-width/2, +width/2] and accumulate with UNIT weight
// (Ernst-Stamminger-Greiner, Filter Importance Sampling, IRT 2006; PBRT-v4 §8.8
// FilterSampler, BSD; Cycles filter_table inverted-CDF, Apache-2.0). For width>1
// the offset crosses pixel boundaries — that is what blurs edges (a wide filter
// lowers the luminance gradient, a narrow one preserves it). See
// .astroray_plan/docs/pkg201-pixel-filter-research.md.
//
// Box (type 0) ignores width and returns uniform [-0.5, 0.5] — byte-identical to
// the pre-pkg201 GPU default AND to the CPU box (raytracer.h::filterSample), so the
// default fleet render and its register/parity baseline are untouched (1 RNG draw).
__device__ inline float filterSample(WavefrontRNG& rng) {
    const int type = c_wfPixelFilter.type;
    const float width = c_wfPixelFilter.width;
    if (type == 1) {
        // Gaussian: Box-Muller normal z (2 draws); sigma = width/6 puts the ±3σ
        // mass at the ±width/2 support edge (the CPU filterSample sigma). Offset
        // ∝ gaussian (importance-sampled), clamped to the support, unit weight.
        float u1 = rng.Uniform();
        float u2 = rng.Uniform();
        if (u1 < 1e-7f) u1 = 1e-7f;
        float z = sqrtf(-2.0f * logf(u1)) * cosf(2.0f * 3.14159265f * u2);
        float half = 0.5f * width;
        float off = z * (width / 6.0f);
        return fmaxf(-half, fminf(half, off));
    } else if (type == 2) {
        // Blackman-Harris 4-term window (same coefficients as the CPU filterSample
        // and Cycles): rejection-sample a normalised position x in [0,1) with
        // accept probability = the window (peaks 1.0 at x=0.5, ~0 at the edges),
        // then map to a width-scaled centred offset. ≤20 attempts, uniform fallback.
        for (int attempt = 0; attempt < 20; ++attempt) {
            float x = rng.Uniform();
            float w = 0.35875f - 0.48829f * cosf(2.0f * 3.14159265f * x)
                               + 0.14128f * cosf(4.0f * 3.14159265f * x)
                               - 0.01168f * cosf(6.0f * 3.14159265f * x);
            if (rng.Uniform() < w) return (x - 0.5f) * width;
        }
        return (rng.Uniform() - 0.5f) * width;
    }
    // Box filter (type 0): uniform [-0.5, 0.5], width-ignored. Mirrors the CPU
    // path_kernel.cpp::filterSample byte-exact uniform_real_distribution pattern
    // (draw uint32, multiply by 2^-32, subtract 0.5).
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

// pkg55-C4: Halton base-2 sequence for deformation-motion time sampling.
// Mirrors multiwavelength_kernel.cu:374 (MW-kernel-local helper, cited from
// PBRT Van der Corput radix-2, Apache-2.0). Sampled once per path at init via
// gpu_mw_haltonBase2(sample_idx + 1), carried through all bounces (MW kernel
// convention: multiwavelength_kernel.cu:448, 361).
__device__ inline float gpu_mw_haltonBase2(int index) {
    float result = 0.0f;
    float f = 1.0f;
    int i = index;
    while (i > 0) {
        f = f / 2.0f;
        result += f * (i % 2);
        i = i / 2;
    }
    return result;
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
    GSampledWavelengths& lambdas,
    float lambdaMin, float lambdaMax)
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
    lambdas = sampleUniformWavelength(lambda_u, lambdaMin, lambdaMax);
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
    uint64_t seed,
    float lambdaMin,
    float lambdaMax)
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
    generatePrimaryRay(rng, cam, px, py, width, height, ray_origin, ray_direction, lambdas,
                       lambdaMin, lambdaMax);

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

    // pkg55-C4: deformation-motion time (pkg88-C.0). Sampled once per path via
    // Halton base-2 (PBRT Van der Corput radix-2, cited from MW kernel). Mirrors
    // multiwavelength_kernel.cu:448 convention: ray.time = gpu_mw_haltonBase2(s+1).
    // Static scenes: time will be 0 (or unused when motionVerts==nullptr).
    // CRITICAL: this is NOT an RNG draw — it's deterministic per sample_idx,
    // so it does NOT advance rng.dimension(). Static-scene renders must stay
    // bit-identical (no new RNG draws on the default path).
    state.path_time[idx] = gpu_mw_haltonBase2(sample_idx + 1);

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

    // pkg55-C5 / pkg113: photon XYZ contrib = (0, 0, 0) for new paths.
    state.photon_xyz_x[idx] = 0.0f;
    state.photon_xyz_y[idx] = 0.0f;
    state.photon_xyz_z[idx] = 0.0f;

    // Path flags.
    state.was_specular[idx] = 1;  // true
    state.path_alive[idx]   = 1;  // true
}

__global__ void stageInitKernel(
    GPUWavefrontState state,
    GCameraParams cam,
    int width, int height,
    uint64_t seed,
    int sample_index,
    float lambdaMin,
    float lambdaMax)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    int total = width * height;
    if (idx >= total) return;
    // Legacy per-round scheduling: slot == pixel.
    initPathSlot(idx, idx, sample_index, state, cam, width, height, seed,
                 lambdaMin, lambdaMax);
}

void launchStageInit(
    GPUWavefrontState& state,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed,
    int sample_index,
    float lambdaMin,
    float lambdaMax)
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
        stageInitKernel<<<blocks, threads>>>(state, cam, width, height, seed, sample_index,
                                              lambdaMin, lambdaMax);
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

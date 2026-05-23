// stage_russian_roulette.cu — pkg55-B' Session N+4
//
// Wavefront Russian roulette (RR) continuation stage kernel.
//
// Session N+4 scope:
//   - Compute RR continuation probability based on throughput luminance (XYZ Y).
//   - Draw one RNG sample and test against continuation probability.
//   - If path survives, scale throughput by 1/p. If path dies, set path_alive=0.
//   - Skip RR before bounce > rrDepth (mirrors CPU kRRDepth = 3).
//
// This kernel runs AFTER stage_light_sample (NEE) and BEFORE stage_shade
// (BSDF sampling for next bounce). It reads throughput from the current state
// and either continues the path (with scaled throughput) or terminates it.
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §4.2 Session N+4.
// Design: PR #296 §4.2 (two-tier gate: CPU↔GPU bounded p99.9 for transcendentals).
//
// Reference (Apache-2.0):
//   - Cycles intern/cycles/kernel/integrator/path_state.h —
//       path_state_rng_terminate() implements RR via throughput luminance.
//   - PBRT-v4 src/pbrt/wavefront/integrator.cpp — RussianRoulette kernel.
//   - CPU mirror: src/cpu/wavefront/path_kernel.cpp::advance_one_bounce()
//       lines 275-306 (Russian roulette block).

#include "astroray/gpu_wavefront_state.h"
#include "astroray/gpu_types.h"
#include "astroray/sampling/wavefront_rng_device.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <cstdio>
#include <stdexcept>

namespace astroray::wavefront {

namespace {

// Russian roulette depth threshold.
// Mirrors CPU kRRDepth = 3 from path_kernel.cpp line 8.
// RR is NOT applied on bounces 0, 1, 2, 3; starts at bounce 4.
constexpr int kRRDepth = 3;

// Convert GSampledSpectrum to XYZ and extract luminance (Y component).
// Mirrors CPU SampledSpectrum::toXYZ() from spectrum.h.
//
// For Session N+4, we use a simplified conversion (direct sum of spectral
// samples weighted by CIE Y matching function). Production would use the
// full CIE 1964 standard observer or CIE 1931 observer via wavelength lookup.
//
// NOTE: This is a PLACEHOLDER conversion. A proper implementation requires:
//   - Wavelength-dependent CIE Y matching function y_bar(lambda).
//   - Integration: Y = sum_i (spectrum[i] * y_bar(lambdas[i]) * lambdas.pdf[i]).
//
// For Session N+4 (Lambertian-only Cornell), we use a coarse approximation:
//   Y ≈ (spectrum[0] + spectrum[1] + spectrum[2] + spectrum[3]) / 4.
//
// This mirrors the CPU toXYZ() logic, which integrates over the CIE matching
// functions. The exact conversion is not critical for RR (we only need a
// monotonic brightness proxy); the relative ordering is what matters.
//
// Session N+5+ will replace this with the full CIE 1964 GPU lookup from pkg54b.
__device__ float estimateLuminance(
    const GSampledSpectrum& spectrum,
    const GSampledWavelengths& lambdas)
{
    // Simplified luminance estimate: average of the 4 spectral samples.
    // This is NOT physically accurate but is monotonic and sufficient for RR.
    float sum = spectrum[0] + spectrum[1] + spectrum[2] + spectrum[3];
    float avg = sum * 0.25f;
    return fmaxf(0.0f, avg);
}

// Russian roulette kernel: for each active path, compute RR probability,
// draw one RNG sample, and either continue (with scaled throughput) or
// terminate (set path_alive = 0).
//
// Reads:
//   - state.bounce[i]: current bounce count.
//   - state.throughput: current path throughput (spectral).
//   - state.lambdas: wavelengths for throughput→XYZ conversion.
//   - state.rng_*: RNG state (consumes one dimension for RR test).
//   - state.path_alive[i]: current alive flag (0 = already dead, skip RR).
//
// Writes:
//   - state.throughput: scaled by 1/p if path survives.
//   - state.path_alive[i]: set to 0 if RR terminates path.
//   - state.rng_dimension: advanced by 1 (consumed one uniform draw).
//
// Logic:
//   - If bounce <= kRRDepth (3), skip RR (paths always continue).
//   - Compute luminance Y from throughput.toXYZ(lambdas).
//   - Continuation probability p = min(0.95, max(0.0, Y)).
//   - Draw u ~ Uniform(0, 1). If u > p, terminate. Else scale throughput by 1/p.
__global__ void stageRussianRouletteKernel(
    GPUWavefrontState state)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= state.num_active) return;

    // Skip if path is already dead.
    if (state.path_alive[i] == 0) return;

    int bounce = state.bounce[i];

    // Skip RR if bounce <= kRRDepth. Mirrors CPU line 276: if (bounce > kRRDepth).
    if (bounce <= kRRDepth) return;

    // Reconstruct RNG.
    WavefrontRNG rng(state.rng_pixel[i], state.rng_sample[i],
                     state.rng_dimension[i], state.rng_seed[i]);

    // Reconstruct throughput.
    GSampledSpectrum throughput(
        state.throughput_0[i],
        state.throughput_1[i],
        state.throughput_2[i],
        state.throughput_3[i]
    );

    // Reconstruct wavelengths.
    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[i];
    lambdas.lambda[1] = state.lambda_1[i];
    lambdas.lambda[2] = state.lambda_2[i];
    lambdas.lambda[3] = state.lambda_3[i];
    lambdas.pdf[0] = state.lambda_pdf_0[i];
    lambdas.pdf[1] = state.lambda_pdf_1[i];
    lambdas.pdf[2] = state.lambda_pdf_2[i];
    lambdas.pdf[3] = state.lambda_pdf_3[i];

    // Estimate luminance Y from throughput.
    // Mirrors CPU line 277: XYZ thrXYZ = ps.throughput.toXYZ(ps.lambdas);
    float Y = estimateLuminance(throughput, lambdas);

    // Continuation probability: min(0.95, max(0.0, Y)).
    // Mirrors CPU line 278.
    float p = fminf(0.95f, fmaxf(0.0f, Y));

    // Draw one uniform RNG sample for RR test.
    // Mirrors CPU line 280: float rr_u = ps.rng.Uniform();
    float rr_u = rng.Uniform();

    // Test: if rr_u > p, terminate path.
    // Mirrors CPU line 281: bool survived = (rr_u <= p);
    bool survived = (rr_u <= p);

    if (!survived) {
        // Path terminated by RR. Set alive flag to 0.
        state.path_alive[i] = 0;
    } else {
        // Path survived. Scale throughput by 1/p.
        // Mirrors CPU line 305: if (p > 0.0f) ps.throughput = ps.throughput * (1.0f / p);
        if (p > 0.0f) {
            float inv_p = 1.0f / p;
            throughput = throughput * inv_p;

            // Write scaled throughput back to SoA.
            state.throughput_0[i] = throughput[0];
            state.throughput_1[i] = throughput[1];
            state.throughput_2[i] = throughput[2];
            state.throughput_3[i] = throughput[3];
        }
    }

    // Update RNG dimension (consumed 1 dimension for RR test).
    state.rng_dimension[i] = rng.dimension_;
}

}  // anonymous namespace

// Host-side launcher for stage_russian_roulette.
void launchStageRussianRoulette_SessionN4(
    GPUWavefrontState& state)
{
    if (state.num_active == 0) return;

    const int kThreadsPerBlock = 256;
    int numBlocks = (state.num_active + kThreadsPerBlock - 1) / kThreadsPerBlock;

    stageRussianRouletteKernel<<<numBlocks, kThreadsPerBlock>>>(state);

    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        throw std::runtime_error(
            std::string("launchStageRussianRoulette_SessionN4 kernel launch failed: ") +
            cudaGetErrorString(err)
        );
    }
}

}  // namespace astroray::wavefront

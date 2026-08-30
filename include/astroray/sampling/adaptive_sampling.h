// adaptive_sampling.h — pkg131 zero-knob adaptive sampling core.
//
// Per-pixel Monte-Carlo stopping condition (Dammertz 2010, brightness-relative
// noise) with Cycles' zero-knob auto-threshold: replace the `samples = N` knob
// with a `max_samples` safety cap + an auto-derived noise threshold + a minimum
// sample floor. This header is the SHARED numeric core consumed by both the CPU
// per-pixel sample loop and the GPU wavefront's compacted active-pixel round; it
// is intentionally a set of pure __host__ __device__ free functions so the host
// build exercised by the unit tests is byte-identical to the device build.
//
// Source: Dammertz, Hanika, Keller, Lensch, "A Hierarchical Automatic Stopping
//   Condition for Monte Carlo Global Illumination", WSCG 2010
//   (http://jo.dreggn.org/home/2009_stopping.pdf) — the per-pixel error metric.
// Reference impl: github.com/blender/cycles@main (read 2026-08-30) —
//   src/scene/integrator.cpp §Integrator::get_adaptive_sampling (auto-threshold),
//   src/integrator/adaptive_sampling.cpp §need_filter/align_samples (cadence),
//   src/kernel/film/adaptive_sampling.h §film_adaptive_sampling_convergence_check
//   + _filter_x/_y (per-pixel error + mask dilation).
// License: Apache-2.0 (compatible with Astroray's LICENSE).
// Notes: .astroray_plan/docs/pkg131-adaptive-sampling-autothreshold-research.md
//
// DELIBERATE DEVIATION FROM CYCLES (documented in the research note): Cycles' aux
// buffer is float3; Astroray stores a SCALAR-LUMINANCE half-buffer (one float per
// pixel) to avoid doubling framebuffer memory on the 8 GB config. The stopping
// signal Dammertz thresholds is brightness noise, which the scalar luminance
// captures; per-channel chroma noise is not separately gated. Luminance here is
// the sum of the three accumulator channels (matches Cycles' `(I.x+I.y+I.z)`
// intensity reduction), the raw XYZ/linear-RGB accumulators Astroray already owns.

#ifndef ASTRORAY_SAMPLING_ADAPTIVE_SAMPLING_H
#define ASTRORAY_SAMPLING_ADAPTIVE_SAMPLING_H

#if defined(__CUDACC__)
#define ASTRORAY_ADAPTIVE_HD __host__ __device__
#else
#define ASTRORAY_ADAPTIVE_HD
#endif

#include <cmath>

namespace astroray {
namespace adaptive {

// Cycles' adaptive_step: convergence is checked every 16th sample past the floor.
// Power of two so `sample & (kAdaptiveStep-1)` is the cadence test.
static constexpr int kAdaptiveStep = 16;

// Resolved sampler schedule for one render (Cycles Integrator::get_adaptive_sampling).
struct AdaptiveParams {
    bool  use;          // adaptive sampling enabled?
    float threshold;    // post-scale noise threshold; converged when error < threshold
    int   min_samples;  // sampling floor — no pixel may converge before this many samples
    int   max_samples;  // safety cap (Cycles' aa_samples); every pixel stops here
    int   adaptive_step;// check cadence (kAdaptiveStep)
};

// Zero-knob derivation from the sample budget. `user_threshold <= 0` and
// `user_min_samples <= 0` request the auto (zero-knob) path; positive values
// override. Mirrors Integrator::get_adaptive_sampling() including the exact
// ordering: min_samples is derived from the PRE-scale threshold, then the
// "arbitrary factor" *5 is applied to the threshold.
ASTRORAY_ADAPTIVE_HD inline AdaptiveParams deriveAdaptiveParams(
    int max_samples, float user_threshold, int user_min_samples) {
    AdaptiveParams p;
    p.use = true;
    p.max_samples = max_samples > 0 ? max_samples : 1;
    p.adaptive_step = kAdaptiveStep;

    float thr;
    if (max_samples > 0 && user_threshold <= 0.0f) {
        // Auto: 1/budget, clamped so a huge budget still stops at a finite noise
        // floor (Cycles clamps to 0.001).
        thr = 1.0f / static_cast<float>(p.max_samples);
        if (thr < 0.001f) thr = 0.001f;
    } else {
        thr = user_threshold;
    }

    if (thr > 0.0f && user_min_samples <= 0) {
        // "Threshold 0.1 -> 32, 0.01 -> 64, 0.001 -> 128" (Cycles comment).
        int ms = static_cast<int>(std::ceil(16.0f / std::pow(thr, 0.3f)));
        p.min_samples = ms > 4 ? ms : 4;
    } else {
        p.min_samples = user_min_samples > 4 ? user_min_samples : 4;
    }

    // Arbitrary factor applied AFTER min_samples derivation (Cycles order).
    thr *= 5.0f;
    p.threshold = thr;

    // The floor can never exceed the cap.
    if (p.min_samples > p.max_samples) p.min_samples = p.max_samples;
    return p;
}

// Cycles need_filter: only check convergence once past the floor, and only on the
// (adaptive_step)-aligned samples. `samples_done` is the number of samples already
// accumulated for the pixel (so the check runs after the 16th, 32nd, … sample).
ASTRORAY_ADAPTIVE_HD inline bool needConvergenceCheck(
    const AdaptiveParams& p, int samples_done) {
    if (!p.use) return false;
    if (samples_done <= p.min_samples) return false;
    return (samples_done & (p.adaptive_step - 1)) == 0;
}

// Per-pixel convergence test (film_adaptive_sampling_convergence_check), scalar
// luminance variant. Inputs are the RUNNING SUMS the render already accumulates:
//   full_lum_sum : Σ luminance over ALL samples_done samples
//   half_lum_sum : Σ luminance over the EVEN-indexed samples only
//   samples_done : n (>= 1)
//   exposure     : film exposure (1.0 unless a film exposure is set)
// Returns true when the pixel's brightness-relative noise is below `threshold`.
ASTRORAY_ADAPTIVE_HD inline bool pixelConverged(
    float full_lum_sum, float half_lum_sum, int samples_done,
    float threshold, float exposure) {
    if (samples_done < 1) return false;
    const int n_half = (samples_done + 1) / 2;  // ceil(n/2): even indices 0,2,4,…
    if (n_half < 1) return false;
    const float mean_full = full_lum_sum / static_cast<float>(samples_done);
    const float mean_half = half_lum_sum / static_cast<float>(n_half);

    const float error_difference = fabsf(mean_full - mean_half) * exposure;
    const float intensity = mean_full * exposure;
    const float error_normalize = (intensity < 1.0f) ? sqrtf(intensity) : intensity;
    const float error = error_difference / (0.0001f + error_normalize);
    return error < threshold;
}

// One 1-D pass of the unconverged-mask box dilation (film_adaptive_sampling_filter_x
// / _filter_y). `converged` is the current mask (1 = converged/retired,
// 0 = keep sampling); `out` receives the dilated mask. A converged pixel is forced
// back to unconverged if either 1-neighbor along `stride` is unconverged, so
// neighborhoods keep sampling together and early-out boundaries are not splotchy.
// Call once with stride=1 (rows) and once with stride=width (columns) for the full
// 3x3 dilation. `out` and `converged` must not alias.
inline void dilateConvergedMaskPass(
    const unsigned char* converged, unsigned char* out,
    int width, int height, int stride) {
    const int n = width * height;
    for (int i = 0; i < n; ++i) {
        if (!converged[i]) { out[i] = 0; continue; }
        // Neighbor along `stride`, guarded at the row/column boundary.
        bool edgeLo, edgeHi;
        if (stride == 1) {
            const int x = i % width;
            edgeLo = (x == 0);
            edgeHi = (x == width - 1);
        } else {
            const int y = i / width;
            edgeLo = (y == 0);
            edgeHi = (y == height - 1);
        }
        const bool loUnconv = !edgeLo && !converged[i - stride];
        const bool hiUnconv = !edgeHi && !converged[i + stride];
        out[i] = (loUnconv || hiUnconv) ? 0 : 1;
    }
}

}  // namespace adaptive
}  // namespace astroray

#endif  // ASTRORAY_SAMPLING_ADAPTIVE_SAMPLING_H

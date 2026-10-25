#pragma once
// #1152 - host planning arithmetic for the GPU wavefront pass plan and its 32-bit
// work counter (cuda_wavefront_render). Pure integer math, no CUDA, so the CPU
// test module can exercise it (module/test_helpers_module.cpp).
//
// The work counter d_work is a 32-bit atomic. Besides the render's real work
// (pixels * spp per round) it overshoots: after the work is exhausted every dead
// slot still claims once per pass. Overshoot passes = 16 (counter read-back
// cadence, kCheckEvery) + passDepth (drain) + 2 (final regen / off-by-one), so the
// counter must hold  work + pool * (16 + passDepth + 2).  That margin is applied
// once, in counterSlack(); callers pass the TRUE pass count (passDepth).
#include <algorithm>
#include <climits>

namespace astroray {
namespace wfplan {

constexpr long long kCounterMax = 0x7FFFFFFFLL;
// Blender's UI maximum for transparent_max_bounces. The host plan never provisions
// more passes than this; the per-path pass_count lane remains the true limit.
constexpr int kTransparentPlanMax = 1024;
// Planned transparent passes when the limit is unlimited (< 0), pre-#1125 value.
constexpr int kUnlimitedTransparentPlan = 31;

// Passes a path can take: max_depth + 2 vertices (#1165: Cycles max_bounces + 1
// scatters, then the emission-only surface), plus limit + 1 transparent passes when
// transparent pass-through is on. long long math: the limit is Python-settable.
inline int passDepth(int maxDepth, bool transparentOn, int transparentLimit) {
    long long d = (long long)maxDepth + 2;
    if (transparentOn) {
        const long long t = transparentLimit >= 0
            ? std::min(transparentLimit, kTransparentPlanMax)
            : kUnlimitedTransparentPlan;
        d += t + 1;
    }
    return (int)std::min<long long>(d, INT_MAX);
}

// Counter overshoot reserved per in-flight path.
inline long long counterSlackPerPath(int passDepthV) {
    return 16LL + (long long)passDepthV + 2;
}

// Path-pool size (before the VRAM budget cap). minPaths = device floor (pkg298).
// Shrinks to numPixels, then below numPixels (work-indexed regeneration allows it),
// until the overshoot slack leaves at least half the counter for real work.
inline long long planPool(long long numPixels, long long samples, int passDepthV,
                          long long minPaths) {
    const long long work = numPixels * samples;
    const long long s = counterSlackPerPath(passDepthV);
    long long pool = std::max(numPixels, std::min(minPaths, work));
    if (work + pool * s > kCounterMax) pool = numPixels;
    if (work + pool * s > kCounterMax)   // chunking the samples (below) fixes the rest
        pool = std::min(numPixels, std::max<long long>(1, (kCounterMax / 2) / s));
    return pool;
}

// Samples per pixel one round may schedule so work + pool slack fits the counter.
inline int maxSamplesPerRound(long long roundPixels, long long pool, int passDepthV) {
    const long long room = kCounterMax - pool * counterSlackPerPath(passDepthV);
    const long long k = roundPixels > 0 ? room / roundPixels : (long long)INT_MAX;
    return (int)std::min<long long>(std::max<long long>(1, k), INT_MAX);
}

} // namespace wfplan
} // namespace astroray

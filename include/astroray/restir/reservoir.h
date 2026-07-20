#pragma once

// ReSTIR reservoir core (pkg20, refactored pkg55-C6).
//
// Header-only Reservoir<T,TRng> implementing the weighted reservoir sampling
// update and merge rules from Bitterli et al. 2020, "Spatiotemporal reservoir
// resampling for real-time ray tracing with dynamic direct lighting."
//
// Terminology matches the paper:
//   w_sum  — running sum of candidate weights
//   M      — number of candidates seen
//   W      — final RIS weight (set by finalizeWeight)
//   y      — currently selected candidate
//
// pkg55-C6: Template over RNG type (TRng) per spec decision #9 (one-generator
// rule). The CPU `restir_di` uses `std::mt19937`; the GPU wavefront uses
// `WavefrontRNG`. Templated functions are __host__ __device__, callable from
// both CPU and CUDA kernels. CPU callers still pass `std::mt19937&` via the
// explicit `Reservoir<T,std::mt19937>` instantiation; GPU callers instantiate
// `Reservoir<T,WavefrontRNG>` and draw via the ADL-dispatched `rng_uniform`.
//
// References:
//   - Bitterli et al. 2020 (DOI 10.1145/3386569.3392481), Algorithm 1–2
//   - DQLin/ReSTIR_PT (BSD-3-Clause, NVIDIA), reservoir structure
//   - pkg55 Phase C plan §5 (one-generator rule)
//
// Weights that are NaN, infinite, or negative are treated as zero: M is still
// incremented (the candidate was seen) but cannot displace the selected sample.

#include <cmath>
#include <limits>
#include <random>

// Host-side ADL dispatch for std::mt19937 (inlined in the header so CPU TUs
// don't need to see device code).
inline float rng_uniform(std::mt19937& gen) {
    std::uniform_real_distribution<float> u01(0.0f, 1.0f);
    return u01(gen);
}

namespace astroray::restir {

template <typename T, typename TRng>
struct Reservoir {
    T     y{};      // selected candidate
    float w_sum{};  // sum of candidate weights
    int   M{};      // candidates seen
    float W{};      // final RIS weight

#ifdef __CUDACC__
    __host__ __device__
#endif
    void reset() {
        y     = T{};
        w_sum = 0.0f;
        M     = 0;
        W     = 0.0f;
    }

    // Weighted reservoir update (Algorithm 1, Bitterli 2020).
    // w < 0, NaN, or Inf is clamped to 0: M still increments.
    //
    // pkg55-C6: Template-RNG arc — TRng can be std::mt19937 (CPU) or
    // WavefrontRNG (GPU). The uniform draw is dispatched via ADL-based
    // `rng_uniform(gen)`, where:
    //   - CPU: rng_uniform(std::mt19937&) is defined above (inline header func)
    //   - GPU: rng_uniform(WavefrontRNG&) is defined in the wavefront headers
    //          (device-only, so not visible here — ADL picks it up in caller TU)
#ifdef __CUDACC__
    __host__ __device__
#endif
    void update(const T& x, float w, TRng& gen) {
#ifdef __CUDA_ARCH__
        if (!isfinite(w) || w < 0.0f) w = 0.0f;
#else
        if (!std::isfinite(w) || w < 0.0f) w = 0.0f;
#endif
        w_sum += w;
        M     += 1;
        if (w_sum > 0.0f) {
            if (rng_uniform(gen) < w / w_sum)
                y = x;
        }
    }

    // Combine another reservoir into this one (Algorithm 2, Bitterli 2020).
    // target_pdf_other_y is p_hat evaluated at other.y in the current domain.
    // Caller must call finalizeWeight after all merges are done.
#ifdef __CUDACC__
    __host__ __device__
#endif
    void merge(const Reservoir<T,TRng>& other, float target_pdf_other_y, TRng& gen) {
        int combined_M = M + other.M;
        update(other.y, other.W * target_pdf_other_y * static_cast<float>(other.M), gen);
        M = combined_M;  // override: paper sets M = sum(M_i), not M + 1
    }

    // Compute the final RIS weight W = w_sum / (p_hat(y) * M).
    // Call once after all updates/merges are complete.
    // Returns 0 if M == 0 or target_pdf_y <= 0 (avoids division by zero).
#ifdef __CUDACC__
    __host__ __device__
#endif
    void finalizeWeight(float target_pdf_y) {
        if (M == 0 || !(target_pdf_y > 0.0f))
            W = 0.0f;
        else
            W = w_sum / (target_pdf_y * static_cast<float>(M));
    }
};

// Type alias for CPU uses (backward compat — existing code references
// `Reservoir<ReSTIRCandidate>` without the RNG template parameter).
template <typename T>
using ReservoirMT19937 = Reservoir<T, std::mt19937>;

} // namespace astroray::restir

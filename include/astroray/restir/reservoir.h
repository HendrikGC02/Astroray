#pragma once

// ReSTIR reservoir core (pkg20).
//
// Header-only Reservoir<T> implementing the weighted reservoir sampling update
// and merge rules from Bitterli et al. 2020, "Spatiotemporal reservoir
// resampling for real-time ray tracing with dynamic direct lighting."
//
// Terminology matches the paper:
//   w_sum  — running sum of candidate weights
//   M      — number of candidates seen
//   W      — final RIS weight (set by finalizeWeight)
//   y      — currently selected candidate
//
// The caller injects randomness via std::mt19937&; the reservoir owns no RNG.
// Weights that are NaN, infinite, or negative are treated as zero: M is still
// incremented (the candidate was seen) but cannot displace the selected sample.

#include <cmath>
#include <limits>
#include <random>

namespace astroray::restir {

template <typename T>
struct Reservoir {
    T     y{};      // selected candidate
    float w_sum{};  // sum of candidate weights
    int   M{};      // candidates seen
    float W{};      // final RIS weight

    void reset() {
        y     = T{};
        w_sum = 0.0f;
        M     = 0;
        W     = 0.0f;
    }

    // Weighted reservoir update (Algorithm 1, Bitterli 2020).
    // w < 0, NaN, or Inf is clamped to 0: M still increments.
    void update(const T& x, float w, std::mt19937& gen) {
        if (!std::isfinite(w) || w < 0.0f) w = 0.0f;
        w_sum += w;
        M     += 1;
        if (w_sum > 0.0f) {
            std::uniform_real_distribution<float> u01(0.0f, 1.0f);
            if (u01(gen) < w / w_sum)
                y = x;
        }
    }

    // Combine another reservoir into this one (Algorithm 2, Bitterli 2020).
    // target_pdf_other_y is p_hat evaluated at other.y in the current domain.
    // Caller must call finalizeWeight after all merges are done.
    void merge(const Reservoir<T>& other, float target_pdf_other_y, std::mt19937& gen) {
        int combined_M = M + other.M;
        update(other.y, other.W * target_pdf_other_y * static_cast<float>(other.M), gen);
        M = combined_M;  // override: paper sets M = sum(M_i), not M + 1
    }

    // Compute the final RIS weight W = w_sum / (p_hat(y) * M).
    // Call once after all updates/merges are complete.
    // Returns 0 if M == 0 or target_pdf_y <= 0 (avoids division by zero).
    void finalizeWeight(float target_pdf_y) {
        if (M == 0 || !(target_pdf_y > 0.0f))
            W = 0.0f;
        else
            W = w_sum / (target_pdf_y * static_cast<float>(M));
    }
};

} // namespace astroray::restir

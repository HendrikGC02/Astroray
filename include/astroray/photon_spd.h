// photon_spd.h — pkg221 — light-SPD importance sampling for the photon-caustic
// pre-pass (both CPU spectral_path_tracer::buildPhotonMap and the GPU
// gpu_wavefront_snapshot::buildCausticAim host paths use this).
//
// The photon pre-pass historically drew each photon's wavelength UNIFORMLY over
// [380,720] and deposited pure CMF, ignoring the emitting light's spectral power
// distribution. For a narrow-line lamp (sodium D, mercury lines) that spreads the
// photons across the whole band → a physically-impossible continuous rainbow
// caustic. pkg221 importance-samples λ ∝ S(λ): with pdf p(λ)=S(λ)/I the deposit
// weight CMF·S/p collapses to the constant I=∫S dλ, so photons cluster at the
// emission lines and every photon carries the same spectral weight.
//
// Citation (CLAUDE.md §6; .astroray_plan/docs/pkg221-spectral-importance-sampling-
// research.md): PBRT-v4 §4.5.4 spectral importance sampling / SampledWavelengths;
// Cycles hero-wavelength sampling. Standard inverse-CDF of a tabulated density.
#pragma once

#include "astroray/spectrum.h"        // SampledWavelengths, SampledSpectrum, kSpectrumSamples
#include "astroray/light_sampler.h"   // LightSampler, LightSample

#include <algorithm>
#include <array>
#include <cmath>
#include <random>

namespace astroray {

// A tabulated, normalized CDF of the emitting light's relative SPD over the
// photon band, plus the SPD integral used as the (constant) deposit weight.
struct PhotonSpdCdf {
    static constexpr int   K       = 341;     // 380..720 nm at 1 nm
    static constexpr float kLmin   = 380.0f;
    static constexpr float kLmax   = 720.0f;
    float cdf[K];        // cdf[k] = normalized cumulative Σ_{j≤k} S_j (in [0,1])
    float integral;      // I = Σ S_k · Δλ (Δλ = 1 nm), the deposit weight
    bool  valid;         // false → no usable SPD → caller keeps the uniform path
};

// Build the CDF by evaluating the DOMINANT light's emission across the band.
// Light selection inside LightSampler::sample depends only on the RNG (a
// power/tree CDF over spectrally-integrated power, not on the probe λ), so a
// fresh mt19937(12345) each call selects the SAME light, and emission_spec[j]
// returns that light's relative SPD at probe lane λ_j. Four grid points are
// evaluated per sample() call (kSpectrumSamples=4). Position-independent for the
// point/spot/distant lamps that carry a line SPD; a constant geometric factor
// cancels in the normalization.
// Templated on the light-container type (Renderer::getLights() returns a
// LightList, defined in raytracer.h) so this header stays decoupled from that
// heavy header — the type binds at each call site where it is already visible.
// The container must provide `.empty()` and
// `.sample(LightSample&, point, normal, SampledWavelengths, std::mt19937&)`.
template <class LightsT>
inline PhotonSpdCdf buildPhotonSpdCdf(const LightsT& lights,
                                      const Vec3& casterC, const Vec3& normal) {
    PhotonSpdCdf out;
    out.valid = false;
    out.integral = 0.0f;
    if (lights.empty()) return out;

    const int   K    = PhotonSpdCdf::K;
    const float lmin = PhotonSpdCdf::kLmin;

    float S[PhotonSpdCdf::K];
    for (int k = 0; k < K; k += kSpectrumSamples) {
        std::array<float, kSpectrumSamples> lam, pdf;
        for (int j = 0; j < kSpectrumSamples; ++j) {
            int idx = std::min(k + j, K - 1);
            lam[j] = lmin + static_cast<float>(idx);
            pdf[j] = 1.0f;
        }
        SampledWavelengths swl = SampledWavelengths::fromLambdas(lam, pdf);
        std::mt19937 gen(12345u);            // pin the same dominant light every call
        LightSample ls;
        lights.sample(ls, casterC, normal, swl, gen);
        for (int j = 0; j < kSpectrumSamples; ++j) {
            int idx = k + j;
            if (idx < K) S[idx] = std::max(0.0f, ls.emission_spec[j]);
        }
    }

    double sum = 0.0;
    for (int k = 0; k < K; ++k) sum += S[k];
    if (sum <= 0.0 || !std::isfinite(sum)) return out;   // no SPD → uniform fallback

    out.integral = static_cast<float>(sum);              // Δλ = 1 nm
    double acc = 0.0;
    for (int k = 0; k < K; ++k) { acc += S[k]; out.cdf[k] = static_cast<float>(acc / sum); }
    out.cdf[K - 1] = 1.0f;                                // guard against fp drift
    out.valid = true;
    return out;
}

// Inverse-CDF sample: given u∈[0,1) return λ. Binary-search the smallest k with
// cdf[k] ≥ u, then linearly interpolate within the [k-1,k] bin. This exact logic
// is byte-mirrored on the device (photon_caustic.cu :pc_spdInverseCdf) so both
// backends produce statistically matching caustic spectra.
inline float photonSpdInverseCdf(const float* cdf, int K, float lmin, float u) {
    int lo = 0, hi = K - 1;
    while (lo < hi) {
        int mid = (lo + hi) >> 1;
        if (cdf[mid] < u) lo = mid + 1; else hi = mid;
    }
    int k = lo;
    float cLo = (k > 0) ? cdf[k - 1] : 0.0f;
    float cHi = cdf[k];
    float t = (cHi > cLo) ? (u - cLo) / (cHi - cLo) : 0.0f;
    float lambda = lmin + static_cast<float>(k - 1) + t;   // bin [lmin+k-1, lmin+k]
    if (lambda < lmin) lambda = lmin;
    return lambda;
}

}  // namespace astroray

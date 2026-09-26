// photon_spd.h — pkg221 — light-SPD importance sampling for the photon-caustic
// pre-pass. pkg287: the per-light CDF is built in photon_lights.h
// (buildPhotonLights) for every emitting lamp, CPU and GPU alike.
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


namespace astroray {

// A tabulated, normalized CDF of the emitting light's relative SPD over the
// photon band, plus the SPD integral used as the (constant) deposit weight.
struct PhotonSpdCdf {
    static constexpr int   K       = 341;     // 380..720 nm at 1 nm
    static constexpr float kLmin   = 380.0f;
    static constexpr float kLmax   = 720.0f;
    float cdf[K];        // cdf[k] = normalized cumulative Σ_{j≤k} S_j (in [0,1])
    float integral;      // I = Σ S_k · Δλ (Δλ = 1 nm), the deposit weight
    bool  valid;         // false → no usable SPD (the light emits nothing)
};

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

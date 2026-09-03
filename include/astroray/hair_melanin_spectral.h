#pragma once
// Spectral melanin absorption for the Principled Hair BSDF — pkg225 Stage 5.
//
// Per-wavelength eumelanin / pheomelanin absorption cross-sections, so the 4-λ
// hero pipeline evaluates hair σ_a directly at each sampled wavelength with NO
// Jakob–Hanika RGB→spectral→RGB round-trip (the round-trip smears out the
// monotone melanin structure this replaces).
//
// Physics (public-domain data; no code copied):
//   Eumelanin   σ_a(λ) = 6.6e11 · λ^-3.33  [cm^-1]  — Jacques 2013,
//     "Optical properties of biological tissues: a review", Phys. Med. Biol.
//     58(11) R37. DOI:10.1088/0031-9155/58/11/R37. Exponent -3.33 verified vs
//     the Jacques 1998 OMLC "Skin Optics Summary" melanosome fit.
//   Pheomelanin σ_a(λ) = 2.9e14 · λ^-4.75  [mm^-1]  — Donner & Jensen 2006,
//     "A Spectral BSSRDF for Shading Human Skin", EGSR 2006.
// Full derivation + the 550 nm magnitude anchor + divergences:
//   .astroray_plan/docs/pkg225-spectral-melanin-research.md
//
// Header-only, STL-free scalar hot path (only std::pow), AR_HAIR_HD so the GPU
// hair leg (gpu_hair.cuh) reuses the EXACT same seam — CPU/GPU parity by
// construction, mirroring hair_bsdf.h.
#include <cmath>
#if defined(__CUDACC__)
#  define AR_HAIR_MEL_HD __host__ __device__
#else
#  define AR_HAIR_MEL_HD
#endif

namespace astroray {
namespace hair {

// Per-wavelength melanin absorption coefficient (the Stage-5 seam).
//
// Only the published wavelength dependence (exponents) is physical; each power
// law is anchored at 550 nm (green) to the Cycles green melanin coefficient
// (eumelanin 0.841, pheomelanin 0.733) so this equals the RGB-mode green σ_a at
// 550 nm and diverges physically toward the red/blue extremes. See the research
// note "Differences from the reference".
static AR_HAIR_MEL_HD inline float melaninSigmaAtLambda(
        float eumelanin, float pheomelanin, float lambda) {
    const float lambda0 = 550.0f;  // green anchor
    float kEu = 0.841f * std::pow(lambda / lambda0, -3.33f);
    float kPh = 0.733f * std::pow(lambda / lambda0, -4.75f);
    return eumelanin * kEu + pheomelanin * kPh;
}

}  // namespace hair
}  // namespace astroray

// Host-only SampledSpectrum convenience (spectrum.h pulls in STL; keep it off
// the device translation unit). Matches the spec signature
// melaninAbsorption(eumelanin, pheomelanin, SampledWavelengths).
#if !defined(__CUDACC__)
#include "astroray/spectrum.h"
namespace astroray {
namespace hair {
inline SampledSpectrum melaninAbsorption(
        float eumelanin, float pheomelanin, const SampledWavelengths& lambdas) {
    SampledSpectrum out(0.0f);
    for (int i = 0; i < kSpectrumSamples; ++i)
        out[i] = melaninSigmaAtLambda(eumelanin, pheomelanin, lambdas.lambda(i));
    return out;
}
}  // namespace hair
}  // namespace astroray
#endif

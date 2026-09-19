// pkg270 — Planck evaluation for Principled Volume blackbody emission, routed
// through the existing engine Blackbody path (planck() in
// include/astroray/spectral.h + the pkg122 photopic-luminance normalisation
// blackbodyLuminanceNorm() in src/emission_spectrum.cpp) so a volume at T
// carries exactly the same normalised SPD as an EmissionSpectrum::Blackbody lamp.
// Research: .astroray_plan/docs/pkg270-spectral-tracking-volume-emission-research.md §3.

#include "astroray/volume/volume_emission.h"

#include "astroray/emission_spectrum.h"  // blackbodyLuminanceNorm
#include "astroray/spectral.h"           // planck()
#include "astroray/volume/blackbody_lut.h"

namespace astroray {
namespace volume {

double blackbodyLuminanceIntegral(double temperatureK) {
    if (!(temperatureK > 0.0)) return 0.0;
    double lum = 0.0;  // same 1 nm Riemann sum as blackbodyLuminanceNorm (pkg122)
    for (int lambda = 360; lambda <= 830; ++lambda) {
        double bb = planck(static_cast<double>(lambda), temperatureK) * 1e9;
        lum += bb * static_cast<double>(cieCmf1964_10deg(static_cast<float>(lambda)).Y);
    }
    return lum;
}

const std::vector<float>& blackbodyLogLuminanceLut() {
    static const std::vector<float> lut = [] {
        std::vector<float> t(static_cast<size_t>(kBBLutN));
        const double lnMin = double(kBBLutLnTMin);
        const double h = 1.0 / double(kBBLutInvH);   // the index formula's step
        for (int k = 0; k < kBBLutN; ++k) {
            double lum = blackbodyLuminanceIntegral(std::exp(lnMin + h * double(k)));
            t[size_t(k)] = (lum > 0.0) ? static_cast<float>(std::log(lum)) : -1e30f;
        }
        return t;
    }();
    return lut;
}

float normalizedPlanck(float lambdaNm, float temperatureK) {
    // #828: the shared CPU/GPU formula (blackbody_lut.h). Replaces the float
    // blackbodyLuminanceNorm() product, which gave NaN for T ~ 25-140 K
    // (normaliser overflowed to inf, float(planck) underflowed to 0), and any
    // per-kelvin memo, which mis-normalises non-integer grid temperatures.
    return bbNormalizedPlanck(lambdaNm, temperatureK, blackbodyLogLuminanceLut().data());
}

}  // namespace volume
}  // namespace astroray

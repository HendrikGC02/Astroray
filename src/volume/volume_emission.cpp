// pkg270 — Planck evaluation for Principled Volume blackbody emission, routed
// through the existing engine Blackbody path (planck() in
// include/astroray/spectral.h + the pkg122 photopic-luminance normalisation
// blackbodyLuminanceNorm() in src/emission_spectrum.cpp) so a volume at T
// carries exactly the same normalised SPD as an EmissionSpectrum::Blackbody lamp.
// Research: .astroray_plan/docs/pkg270-spectral-tracking-volume-emission-research.md §3.

#include "astroray/volume/volume_emission.h"

#include "astroray/emission_spectrum.h"  // blackbodyLuminanceNorm
#include "astroray/spectral.h"           // planck()

#include <unordered_map>

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

float normalizedPlanck(float lambdaNm, float temperatureK) {
    if (!(temperatureK > 0.0f)) return 0.0f;
    // #828: the ratio is formed in DOUBLE. The previous float normaliser
    // (blackbodyLuminanceNorm) overflowed to inf for T ~ 25-140 K and
    // float(planck) underflowed to 0, giving NaN. Memoised per rounded kelvin
    // (thread_local), evaluated AT the rounded kelvin so the value does not
    // depend on which temperature a thread saw first.
    static thread_local std::unordered_map<int, double> cache;
    const int key = static_cast<int>(std::lround(temperatureK));
    auto it = cache.find(key);
    double lum;
    if (it != cache.end()) {
        lum = it->second;
    } else {
        lum = blackbodyLuminanceIntegral(static_cast<double>(key));
        cache.emplace(key, lum);
    }
    if (!(lum > 0.0)) return 0.0f;
    double bb = planck(static_cast<double>(lambdaNm), static_cast<double>(temperatureK)) * 1e9;
    return static_cast<float>(bb / lum);
}

std::vector<float> blackbodyLogLuminanceLut(int n, double lnTMin, double lnTMax) {
    std::vector<float> lut(static_cast<size_t>(std::max(n, 2)));
    const double h = (lnTMax - lnTMin) / double(lut.size() - 1);
    for (size_t k = 0; k < lut.size(); ++k) {
        double lum = blackbodyLuminanceIntegral(std::exp(lnTMin + h * double(k)));
        lut[k] = (lum > 0.0) ? static_cast<float>(std::log(lum)) : -1e30f;
    }
    return lut;
}

}  // namespace volume
}  // namespace astroray

#include "astroray/light.h"
#include "astroray/spectral.h"  // for planck()
#include "astroray/spectrum.h"  // for cieCmf1964_10deg
#include "raytracer.h"  // for Vec3
#include <cmath>

namespace astroray {

// Helper: compute normalize factor for blackbody emission.
// Returns 1.0 if normalize is false or emission is non-blackbody.
// Reference: Cycles scene/light.cpp::light_normalize_factor (Apache-2.0).
float Light::computeNormalizeFactor(const EmissionSpectrum& emission, bool shouldNormalize) {
    if (!shouldNormalize) return 1.0f;

    // Only normalize Blackbody mode (check if the variant holds Blackbody).
    const auto& var = emission.variant();
    if (!std::holds_alternative<EmissionSpectrum::Blackbody>(var)) {
        return 1.0f;
    }

    const auto& bb = std::get<EmissionSpectrum::Blackbody>(var);
    float temperature_K = bb.temperature_K;

    // Integrate the blackbody SPD against the CIE 1964 10° photopic luminance
    // function (Y channel) over the visible band to get photopic luminance.
    // Normalization: divide by this integral so the artist's intensity slider
    // behaves uniformly across temperatures.
    //
    // Integration range: 380-780 nm (visible), 5 nm steps (trapezoid rule).
    double yIntegral = 0.0;
    constexpr double lambdaMin = 380.0;
    constexpr double lambdaMax = 780.0;
    constexpr double step = 5.0;

    for (double lam = lambdaMin; lam < lambdaMax; lam += step) {
        double lam1 = lam;
        double lam2 = lam + step;
        // Planck radiance in W/(m²·sr·m), convert to W/(m²·sr·nm) by multiplying by 1e9.
        double bb1 = planck(lam1, temperature_K) * 1e9;
        double bb2 = planck(lam2, temperature_K) * 1e9;
        // CIE Y (photopic luminance) at lam1, lam2.
        double y1 = cieCmf1964_10deg(static_cast<float>(lam1)).Y;
        double y2 = cieCmf1964_10deg(static_cast<float>(lam2)).Y;
        // Trapezoid rule: integral += 0.5 * dλ * (f1 + f2).
        yIntegral += 0.5 * step * (bb1 * y1 + bb2 * y2);
    }

    // Normalize factor: 1 / integrated photopic luminance.
    // If yIntegral is near zero (extremely cold blackbody), clamp to 1.0.
    if (yIntegral < 1e-6) return 1.0f;
    return static_cast<float>(1.0 / yIntegral);
}

} // namespace astroray

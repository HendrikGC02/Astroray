// pkg270 — Planck evaluation for Principled Volume blackbody emission, routed
// through the existing engine Blackbody path (planck() in
// include/astroray/spectral.h + the pkg122 photopic-luminance normalisation
// blackbodyLuminanceNorm() in src/emission_spectrum.cpp) so a volume at T
// carries exactly the same normalised SPD as an EmissionSpectrum::Blackbody lamp.
// Research: .astroray_plan/docs/pkg270-spectral-tracking-volume-emission-research.md §3.

#include "astroray/volume/volume_emission.h"

#include "astroray/emission_spectrum.h"  // blackbodyLuminanceNorm
#include "astroray/spectral.h"           // planck()

namespace astroray {
namespace volume {

float normalizedPlanck(float lambdaNm, float temperatureK) {
    if (!(temperatureK > 0.0f)) return 0.0f;
    // blackbodyLuminanceNorm memoises per rounded kelvin (thread_local), so a
    // temperature grid costs one 471-step integral per distinct kelvin per thread.
    float norm = blackbodyLuminanceNorm(static_cast<double>(temperatureK));
    if (!(norm > 0.0f)) return 0.0f;
    double bb = planck(static_cast<double>(lambdaNm), static_cast<double>(temperatureK)) * 1e9;
    return static_cast<float>(bb) * norm;
}

}  // namespace volume
}  // namespace astroray

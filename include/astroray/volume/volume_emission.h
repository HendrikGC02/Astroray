// pkg270 — Principled Volume emission: constant emission (Emission Strength ×
// Emission Color) plus blackbody emission driven by a temperature (socket or
// grid) evaluated through Planck's law SPECTRALLY per sampled wavelength.
//
// Socket semantics follow Cycles `svm_node_principled_volume`
// (blender/cycles src/kernel/svm/closure.h, Apache-2.0; raw source read
// 2026-09-15 — see .astroray_plan/docs/pkg270-spectral-tracking-volume-emission-research.md §3):
//   emission is radiance PER UNIT LENGTH and is independent of the voxel density;
//   T = Temperature socket, multiplied by the "temperature" attribute when present;
//   intensity = (5.670373e-8 · 1e-6 / π) · mix(1, T⁴, Blackbody Intensity)
//   colour    = Blackbody Tint × luminance-normalised blackbody colour(T).
// Cycles' colour is a Rec.709 polynomial fit (RGB-LUT-approximate); Astroray
// evaluates the exact Planck spectrum through the existing engine Blackbody path
// (planck() + blackbodyLuminanceNorm(), src/emission_spectrum.cpp) so the
// luminance per unit length equals Cycles' while the colour is physical. The
// Planck evaluation lives in src/volume/volume_emission.cpp so this header stays
// free of spectral.h (which includes raytracer.h).

#pragma once

#include <algorithm>
#include <array>
#include <cmath>

#include "astroray/spectrum.h"

namespace astroray {
namespace volume {

// Luminance-normalised Planck radiance per nm at (lambda_nm, T): E[Y] == 1 for
// any T (pkg122 normalisation). 0 for T <= 0. Defined in volume_emission.cpp.
float normalizedPlanck(float lambdaNm, float temperatureK);

// Cycles Stefan–Boltzmann intensity: sigma·1e-6/π · mix(1, T⁴, I_bb).
inline float cyclesBlackbodyIntensity(float temperatureK, float blackbodyIntensity) {
    float T = std::max(temperatureK, 0.0f);
    float T4 = (T * T) * (T * T);
    const float sigma = 5.670373e-8f * 1e-6f / 3.14159265358979323846f;
    return sigma * ((1.0f - blackbodyIntensity) + blackbodyIntensity * T4);
}

// Prepared emission evaluator for one bounded medium (built once at
// registration from the PrincipledVolume sockets).
struct VolumeEmission {
    float emissionStrength = 0.0f;
    float blackbodyIntensity = 0.0f;
    bool tintIsWhite = true;
    astroray::RGBIlluminantSpectrum emissionSpec;  // Emission Color (illuminant upsample)
    astroray::RGBAlbedoSpectrum tintSpec;          // Blackbody Tint (reflectance-like filter)

    void setup(float strength, const std::array<float, 3>& color, float bbIntensity,
               const std::array<float, 3>& tint) {
        emissionStrength = std::max(0.0f, strength);
        blackbodyIntensity = std::clamp(bbIntensity, 0.0f, 1.0f);
        std::array<float, 3> c = {std::max(0.0f, color[0]), std::max(0.0f, color[1]),
                                  std::max(0.0f, color[2])};
        emissionSpec = astroray::RGBIlluminantSpectrum(c);
        tintSpec = astroray::RGBAlbedoSpectrum(tint);
        tintIsWhite = std::abs(tint[0] - 1.0f) < 1e-6f && std::abs(tint[1] - 1.0f) < 1e-6f &&
                      std::abs(tint[2] - 1.0f) < 1e-6f;
    }

    bool hasConstant() const { return emissionStrength > 0.0f; }
    bool hasBlackbody() const { return blackbodyIntensity > 0.0f; }
    bool active() const { return hasConstant() || hasBlackbody(); }

    // Constant term: Emission Strength × Emission Color(λ)  (per unit length).
    astroray::SampledSpectrum evalConstant(const astroray::SampledWavelengths& wl) const {
        return emissionSpec.sample(wl) * emissionStrength;
    }

    // Blackbody term at temperature T (K): Cycles intensity × tint(λ) ×
    // luminance-normalised Planck(λ, T)  (per unit length).
    astroray::SampledSpectrum evalBlackbody(float temperatureK,
                                            const astroray::SampledWavelengths& wl) const {
        astroray::SampledSpectrum s(0.0f);
        if (!(temperatureK > 0.0f)) return s;
        float intensity = cyclesBlackbodyIntensity(temperatureK, blackbodyIntensity);
        if (!(intensity > 0.0f)) return s;
        for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
            float v = normalizedPlanck(wl.lambda(i), temperatureK) * intensity;
            if (!tintIsWhite) v *= tintSpec.evalAt(wl.lambda(i));
            s[i] = v;
        }
        return s;
    }
};

}  // namespace volume
}  // namespace astroray

#pragma once

// ReSTIR light candidate payload (pkg21).
//
// ReSTIRCandidate is the renderer-agnostic representation of a sampled direct-
// light candidate. It carries enough information to evaluate the RIS target
// function and to test visibility later, but it never traces shadow rays itself.
//
// Fields mirror those of LightSample (raytracer.h) so fromLightSample() is a
// zero-cost adapter.  The abstraction gives ReSTIR passes a stable API that
// does not depend on how LightList::sample() is implemented internally.
//
// Target-weight formula follows Bitterli et al. 2020 §3.2:
//   p_hat(x) = luminance( L_e(x) )
// where luminance is derived from the spectral Y channel (CIE 1931 2°).

#include <array>
#include <cmath>

#include "raytracer.h"           // Vec3, LightSample
#include "astroray/spectrum.h"   // SampledWavelengths, SampledSpectrum, RGBIlluminantSpectrum

namespace astroray::restir {

struct ReSTIRCandidate {
    Vec3  position;   // sampled point on the light surface
    Vec3  normal;     // surface normal at position (light-facing convention)
    Vec3  emission;   // RGB emission at the sampled point (pre-multiplied by falloff)
    float pdf;        // combined light-selection × solid-angle sampling PDF
    float distance;   // distance from shading point (for occlusion test)

    // Construct from an existing LightSample (zero overhead; pure field copy).
    static ReSTIRCandidate fromLightSample(const LightSample& ls) {
        return {ls.position, ls.normal, ls.emission, ls.pdf, ls.distance};
    }

    // Returns true when the candidate can contribute to the RIS estimator:
    //   pdf > 0 and finite, emission components finite, position finite.
    // A candidate with pdf == 0 cannot be importance-weighted.
    bool isValid() const {
        return pdf > 0.0f
            && std::isfinite(pdf)
            && std::isfinite(emission.x)
            && std::isfinite(emission.y)
            && std::isfinite(emission.z)
            && std::isfinite(position.x)
            && std::isfinite(position.y)
            && std::isfinite(position.z);
    }

    // RIS target weight p_hat(y): spectral luminance of the emission.
    // Upsamples RGB emission via RGBIlluminantSpectrum and returns Y channel.
    // Returns 0.0 for invalid candidates or black emitters.
    float targetLuminance(const SampledWavelengths& lambdas) const {
        if (!isValid()) return 0.0f;
        SampledSpectrum spec =
            RGBIlluminantSpectrum({emission.x, emission.y, emission.z}).sample(lambdas);
        float Y = spec.toXYZ(lambdas).Y;
        return Y > 0.0f ? Y : 0.0f;
    }
};

} // namespace astroray::restir

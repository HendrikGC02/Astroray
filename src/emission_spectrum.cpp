#include "astroray/emission_spectrum.h"
#include "astroray/spectral.h"  // for planck()
#include "astroray/spectrum.h"  // for RGBAlbedoSpectrum, RGBIlluminantSpectrum
#include "astroray/spectral_profile.h"
#include "raytracer.h"  // for Vec3
#include <stdexcept>

namespace astroray {

// Copy constructor (handles unique_ptr in Composite).
EmissionSpectrum::EmissionSpectrum(const EmissionSpectrum& other) {
    data_ = std::visit([](const auto& mode) -> Variant {
        using T = std::decay_t<decltype(mode)>;
        if constexpr (std::is_same_v<T, Composite>) {
            Composite newComp;
            newComp.base = std::make_unique<EmissionSpectrum>(*mode.base);
            newComp.filter_rgb = mode.filter_rgb;
            return newComp;
        } else {
            return mode;  // Blackbody, RGB, MeasuredSPD are trivially copyable
        }
    }, other.data_);
}

// Copy assignment (handles unique_ptr in Composite).
EmissionSpectrum& EmissionSpectrum::operator=(const EmissionSpectrum& other) {
    if (this == &other) return *this;
    data_ = std::visit([](const auto& mode) -> Variant {
        using T = std::decay_t<decltype(mode)>;
        if constexpr (std::is_same_v<T, Composite>) {
            Composite newComp;
            newComp.base = std::make_unique<EmissionSpectrum>(*mode.base);
            newComp.filter_rgb = mode.filter_rgb;
            return newComp;
        } else {
            return mode;  // Blackbody, RGB, MeasuredSPD are trivially copyable
        }
    }, other.data_);
    return *this;
}

// Evaluate the emission spectrum at the given wavelengths.
SampledSpectrum EmissionSpectrum::eval(const SampledWavelengths& lambdas) const {
    return std::visit([&](const auto& mode) -> SampledSpectrum {
        using T = std::decay_t<decltype(mode)>;
        if constexpr (std::is_same_v<T, Blackbody>) {
            return evalBlackbody(mode, lambdas);
        } else if constexpr (std::is_same_v<T, RGB>) {
            return evalRGB(mode, lambdas);
        } else if constexpr (std::is_same_v<T, MeasuredSPD>) {
            return evalMeasuredSPD(mode, lambdas);
        } else if constexpr (std::is_same_v<T, Composite>) {
            return evalComposite(mode, lambdas);
        }
    }, data_);
}

// Helper: create a Composite by multiplying this spectrum by a filter.
EmissionSpectrum EmissionSpectrum::composeWith(const Vec3& filterRGB) const {
    Composite comp;
    comp.base = std::make_unique<EmissionSpectrum>(*this);
    comp.filter_rgb = filterRGB;
    return EmissionSpectrum(std::move(comp));
}

// Internal: evaluate Blackbody mode.
SampledSpectrum EmissionSpectrum::evalBlackbody(const Blackbody& bb,
                                                 const SampledWavelengths& wl) const {
    SampledSpectrum result;
    for (int i = 0; i < kSpectrumSamples; ++i) {
        float lambda = wl.lambda(i);
        // Planck blackbody (W/(m²·sr·nm)) — note: spectral.h planck() returns
        // W/(m²·sr·m), so multiply by 1e9 to get per-nm.
        double bbValue = planck(static_cast<double>(lambda), static_cast<double>(bb.temperature_K));
        float bbFloat = static_cast<float>(bbValue * 1e9);  // W/(m²·sr·m) → W/(m²·sr·nm)

        // Apply RGB tint as a multiplicative filter via Jakob-Hanika upsample.
        // When tint == (1,1,1), this is a no-op (white filter).
        RGBAlbedoSpectrum tintSpectrum({bb.tint_rgb.x, bb.tint_rgb.y, bb.tint_rgb.z});
        float tintAt = tintSpectrum.evalAt(lambda);

        result[i] = bbFloat * tintAt;
    }
    return result;
}

// Internal: evaluate RGB mode.
SampledSpectrum EmissionSpectrum::evalRGB(const RGB& rgb,
                                           const SampledWavelengths& wl) const {
    // Pure Jakob-Hanika upsample (illuminant mode: scales by D65).
    RGBIlluminantSpectrum rgbSpectrum({rgb.color.x, rgb.color.y, rgb.color.z});
    return rgbSpectrum.sample(wl);
}

// Internal: evaluate MeasuredSPD mode.
SampledSpectrum EmissionSpectrum::evalMeasuredSPD(const MeasuredSPD& spd,
                                                    const SampledWavelengths& wl) const {
    const SpectralProfileDatabase& db = SpectralProfileDatabase::instance();
    const SpectralProfile* profile = db.get(spd.profile_name);
    if (!profile || !profile->valid()) {
        throw std::runtime_error("EmissionSpectrum: MeasuredSPD profile '" +
                                 spd.profile_name + "' not found in database");
    }

    SampledSpectrum result;
    for (int i = 0; i < kSpectrumSamples; ++i) {
        float lambda = wl.lambda(i);
        // SpectralProfile::emission() returns relative SPD (normalized to [0, 1]).
        // For emission, interpret as relative spectral radiance.
        result[i] = profile->emission(lambda);
    }
    return result;
}

// Internal: evaluate Composite mode.
SampledSpectrum EmissionSpectrum::evalComposite(const Composite& comp,
                                                 const SampledWavelengths& wl) const {
    // Evaluate base emission.
    SampledSpectrum baseEmission = comp.base->eval(wl);

    // Apply RGB filter via Jakob-Hanika upsample.
    RGBAlbedoSpectrum filterSpectrum({comp.filter_rgb.x, comp.filter_rgb.y, comp.filter_rgb.z});
    SampledSpectrum filterSampled = filterSpectrum.sample(wl);

    // Multiply: spectrum(λ) = base(λ) · filter(λ).
    return baseEmission * filterSampled;
}

} // namespace astroray

#pragma once

// EmissionSpectrum — spectral emission representation for dedicated Light objects.
//
// Resolves pkg89 Q-Owner-1 (owner-answered 2026-05-14): default is Blackbody +
// tint, with toggle for RGB-upsample mode and preset measured SPDs (fluorescent,
// LED, gas lamps). Cycles has only Blackbody + RGB color; this design adds the
// "color as filter" semantic and the spectral-profile library.
//
// Four modes:
//   1. Blackbody { temperature_K, tint_rgb } — DEFAULT. Planck blackbody
//      multiplied by Jakob-Hanika upsample of the tint. The tint is a "gel
//      filter" on the thermal source. Precompute the product at construction.
//   2. RGB { color } — pure Jakob-Hanika upsample, no blackbody base.
//   3. MeasuredSPD { profile_name } — loads from pkg38 spectral-profile database.
//   4. Composite { base, filter_rgb } — explicit composite for advanced users
//      (e.g., fluorescent SPD × colored gel). Not exposed in basic Blender UI.
//
// Reference:
//   - Planck blackbody: include/astroray/spectral.h:15 (already implemented).
//   - Jakob-Hanika upsample: include/astroray/spectrum.h (pkg10).
//   - Measured SPDs: include/astroray/spectral_profile.h (pkg38).
//
// CLAUDE.md §6 citation: design is Cycles-inspired (Apache-2.0,
// intern/cycles/scene/light.h `Light::emission`) extended with the owner's
// "color as filter" + measured-SPD presets model. The composite multiply-at-
// construction pattern (Q10 resolution) follows Cycles' static emission-
// spectrum-baking convention.

#include "spectrum.h"
#include "spectral_profile.h"
#include "../raytracer.h"  // for Vec3
#include <string>
#include <memory>
#include <variant>

namespace astroray {

// Forward declarations
class RGBAlbedoSpectrum;

// --------------------------------------------------------------------------
// EmissionSpectrum — tagged union representing spectral emission.
// --------------------------------------------------------------------------
class EmissionSpectrum {
public:
    // Mode 1: Blackbody with optional RGB tint (gel filter).
    // Default temperature is D65 (6500 K). Tint (1,1,1) is white (no-op).
    // At evaluation time: spectrum(λ) = blackbody(λ, T) · rgb_to_spectrum(tint, λ).
    struct Blackbody {
        float temperature_K = 6500.0f;
        Vec3  tint_rgb      = Vec3(1.0f, 1.0f, 1.0f);
    };

    // Mode 2: Pure RGB upsample via Jakob-Hanika (no blackbody base).
    struct RGB {
        Vec3 color;
    };

    // Mode 3: Measured SPD from spectral-profile database (pkg38).
    // Preset examples: "CIE_F2", "LED_3000K", "LED_6500K", "SODIUM_VAPOR", etc.
    struct MeasuredSPD {
        std::string profile_name;
    };

    // Mode 4: Explicit composite (for advanced users). Base emission × filter.
    // The base can itself be any EmissionSpectrum mode (recursive).
    struct Composite {
        std::unique_ptr<EmissionSpectrum> base;
        Vec3 filter_rgb;
    };

    using Variant = std::variant<Blackbody, RGB, MeasuredSPD, Composite>;

    // Constructors (defaults to Blackbody at 6500 K with white tint).
    EmissionSpectrum() : data_(Blackbody{}) {}
    explicit EmissionSpectrum(const Blackbody& bb) : data_(bb) {}
    explicit EmissionSpectrum(const RGB& rgb) : data_(rgb) {}
    explicit EmissionSpectrum(const MeasuredSPD& spd) : data_(spd) {}
    explicit EmissionSpectrum(Composite&& comp) : data_(std::move(comp)) {}

    // Copy constructor and assignment (handles unique_ptr in Composite).
    EmissionSpectrum(const EmissionSpectrum& other);
    EmissionSpectrum& operator=(const EmissionSpectrum& other);

    // Move constructor and assignment (default is fine).
    EmissionSpectrum(EmissionSpectrum&&) noexcept = default;
    EmissionSpectrum& operator=(EmissionSpectrum&&) noexcept = default;

    ~EmissionSpectrum() = default;

    // Evaluate the emission spectrum at the given wavelengths.
    // Returns the spectral radiance (W/(m²·sr·nm)) per wavelength sample.
    SampledSpectrum eval(const SampledWavelengths& lambdas) const;

    // Helper: create a Composite by multiplying this spectrum by a filter.
    // Used when the user applies a colored gel to an existing emission source.
    EmissionSpectrum composeWith(const Vec3& filterRGB) const;

    // Accessors for the underlying variant (for UI / serialization).
    const Variant& variant() const { return data_; }
    Variant&       variant()       { return data_; }

private:
    Variant data_;

    // Internal helpers for eval dispatch.
    SampledSpectrum evalBlackbody(const Blackbody& bb, const SampledWavelengths& wl) const;
    SampledSpectrum evalRGB(const RGB& rgb, const SampledWavelengths& wl) const;
    SampledSpectrum evalMeasuredSPD(const MeasuredSPD& spd, const SampledWavelengths& wl) const;
    SampledSpectrum evalComposite(const Composite& comp, const SampledWavelengths& wl) const;
};

} // namespace astroray

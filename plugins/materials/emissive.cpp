#include "astroray/register.h"
#include "raytracer.h"

// Omnidirectional emitter — emits from both faces.
// Unlike DiffuseLight ("light"/"emission"/"diffuse_light") which only emits
// from the front face, EmissivePlugin emits regardless of face orientation.
// Useful for self-luminous objects that should glow from all sides.
class EmissivePlugin : public Material {
    Vec3 color_;
    float intensity_;
    // pkg142 (Defect 4): RGBUnbounded (no-D65) lift, matching Cycles' RGB-native
    // light scaling and astroray::EmissionSpectrum::evalRGB. See
    // .astroray_plan/packages/pkg142-rgb-emission-convention.md.
    astroray::RGBUnboundedSpectrum emission_spec_;

public:
    explicit EmissivePlugin(const astroray::ParamDict& p)
        : color_(p.getVec3("albedo", Vec3(1.0f))),
          intensity_(p.getFloat("intensity", 1.0f)),
          emission_spec_({color_.x * intensity_, color_.y * intensity_, color_.z * intensity_}) {}

    Vec3 emitted(const HitRecord& rec) const override {
        return color_ * intensity_;  // no front-face gate
    }

    astroray::SampledSpectrum emittedSpectral(
            const HitRecord& rec,
            const astroray::SampledWavelengths& lambdas) const override {
        // pkg142 hardware-verifier fix: RGBUnboundedSpectrum::sample() has no
        // photometric anchor -- apply astroray::cieYIntegral()'s reciprocal
        // here (mirrors sampleUnboundedEmission(); can't use that helper
        // directly since emission_spec_ is a stored, pre-constructed object).
        return emission_spec_.sample(lambdas) * (1.0f / astroray::cieYIntegral());  // no front-face gate
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord&, const Vec3&, const Vec3&,
            const astroray::SampledWavelengths&) const override {
        return astroray::SampledSpectrum(0.0f);
    }

    Vec3 getEmission() const override { return color_ * intensity_; }
    bool isEmissive() const override { return true; }
    std::string getGPUTypeName() const override { return "diffuse_light"; }
};

ASTRORAY_REGISTER_MATERIAL("emissive", EmissivePlugin)

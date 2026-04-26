#include "astroray/register.h"
#include "raytracer.h"

// Omnidirectional emitter — emits from both faces.
// Unlike DiffuseLight ("light"/"emission"/"diffuse_light") which only emits
// from the front face, EmissivePlugin emits regardless of face orientation.
// Useful for self-luminous objects that should glow from all sides.
class EmissivePlugin : public Material {
    Vec3 color_;
    float intensity_;
    astroray::RGBIlluminantSpectrum emission_spec_;

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
        return emission_spec_.sample(lambdas);  // no front-face gate
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord&, const Vec3&, const Vec3&,
            const astroray::SampledWavelengths&) const override {
        return astroray::SampledSpectrum(0.0f);
    }

    Vec3 getEmission() const override { return color_ * intensity_; }
    bool isEmissive() const override { return true; }
};

ASTRORAY_REGISTER_MATERIAL("emissive", EmissivePlugin)

#include "astroray/register.h"
#include "raytracer.h"

class DiffuseLightPlugin : public Material {
    Vec3 color_;
    float intensity_;
    astroray::RGBIlluminantSpectrum emission_spec_;

public:
    explicit DiffuseLightPlugin(const astroray::ParamDict& p)
        : color_(p.getVec3("albedo", Vec3(1.0f))),
          intensity_(p.getFloat("intensity", 1.0f)),
          emission_spec_({color_.x * intensity_, color_.y * intensity_, color_.z * intensity_}) {}

    Vec3 emitted(const HitRecord& rec) const override {
        return rec.frontFace ? color_ * intensity_ : Vec3(0);
    }

    astroray::SampledSpectrum emittedSpectral(
            const HitRecord& rec,
            const astroray::SampledWavelengths& lambdas) const override {
        if (!rec.frontFace) return astroray::SampledSpectrum(0.0f);
        return emission_spec_.sample(lambdas);
    }

    Vec3 getEmission() const override { return color_ * intensity_; }
    bool isEmissive() const override { return true; }
};

struct EmissionPlugin : public DiffuseLightPlugin { using DiffuseLightPlugin::DiffuseLightPlugin; };
struct DiffuseLightAliasPlugin : public DiffuseLightPlugin { using DiffuseLightPlugin::DiffuseLightPlugin; };

ASTRORAY_REGISTER_MATERIAL("light", DiffuseLightPlugin)
ASTRORAY_REGISTER_MATERIAL("emission", EmissionPlugin)
ASTRORAY_REGISTER_MATERIAL("diffuse_light", DiffuseLightAliasPlugin)

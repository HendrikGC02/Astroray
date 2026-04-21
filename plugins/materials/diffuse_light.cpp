#include "astroray/register.h"
#include "raytracer.h"

class DiffuseLightPlugin : public Material {
    Vec3 color_;
    float intensity_;

public:
    explicit DiffuseLightPlugin(const astroray::ParamDict& p)
        : color_(p.getVec3("albedo", Vec3(1.0f))),
          intensity_(p.getFloat("intensity", 1.0f)) {}

    Vec3 emitted(const HitRecord& rec) const override {
        return rec.frontFace ? color_ * intensity_ : Vec3(0);
    }

    Vec3 getEmission() const override { return color_ * intensity_; }
    bool isEmissive() const override { return true; }
};

struct EmissionPlugin : public DiffuseLightPlugin { using DiffuseLightPlugin::DiffuseLightPlugin; };
struct DiffuseLightAliasPlugin : public DiffuseLightPlugin { using DiffuseLightPlugin::DiffuseLightPlugin; };

ASTRORAY_REGISTER_MATERIAL("light", DiffuseLightPlugin)
ASTRORAY_REGISTER_MATERIAL("emission", EmissionPlugin)
ASTRORAY_REGISTER_MATERIAL("diffuse_light", DiffuseLightAliasPlugin)

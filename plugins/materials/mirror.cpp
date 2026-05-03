#include "astroray/register.h"
#include "raytracer.h"

class MirrorPlugin : public Material {
public:
    explicit MirrorPlugin(const astroray::ParamDict&) {}

    // Delta lobe: evalSpectral is never called meaningfully by the spectral path.
    astroray::SampledSpectrum evalSpectral(
            const HitRecord&, const Vec3&, const Vec3&,
            const astroray::SampledWavelengths&) const override {
        return astroray::SampledSpectrum(0.0f);
    }

    MaterialBackendCapabilities backendCapabilities() const override {
        MaterialBackendCapabilities caps;
        caps.notes = "mirror has no dedicated GPU material lowering yet";
        return caps;
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937&) const override {
        BSDFSample s;
        s.wi = rec.normal * (2 * wo.dot(rec.normal)) - wo;
        s.f = Vec3(1);
        s.pdf = 1;
        s.isDelta = true;
        const_cast<HitRecord&>(rec).isDelta = true;
        return s;
    }
};

ASTRORAY_REGISTER_MATERIAL("mirror", MirrorPlugin)

#include "astroray/register.h"
#include "raytracer.h"

// Wraps another material and renders both faces.
// On the back face, flips the hit record normal so the inner material
// sees a front-face hit â€” allowing e.g. a Lambertian cloth to be
// shaded correctly from both sides.
class TwoSidedPlugin : public Material {
    std::shared_ptr<Material> inner_;

    static HitRecord flipToFront(const HitRecord& rec) {
        HitRecord out = rec;
        out.normal = -rec.normal;
        out.frontFace = true;
        buildOrthonormalBasis(out.normal, out.tangent, out.bitangent);
        return out;
    }

public:
    explicit TwoSidedPlugin(const astroray::ParamDict& p)
        : inner_(astroray::MaterialRegistry::instance().create(
              p.getString("inner_type", "lambertian"), p)) {}

    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        const HitRecord& r = rec.frontFace ? rec : flipToFront(rec);
        return inner_->eval(r, wo, wi);
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const override {
        const HitRecord flipped = rec.frontFace ? rec : flipToFront(rec);
        return inner_->evalSpectral(flipped, wo, wi, lambdas);
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        const HitRecord flipped = rec.frontFace ? rec : flipToFront(rec);
        return inner_->sample(flipped, wo, gen);
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        const HitRecord flipped = rec.frontFace ? rec : flipToFront(rec);
        return inner_->pdf(flipped, wo, wi);
    }
};

ASTRORAY_REGISTER_MATERIAL("two_sided", TwoSidedPlugin)

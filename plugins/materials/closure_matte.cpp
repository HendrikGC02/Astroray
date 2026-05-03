#include "astroray/register.h"
#include "raytracer.h"

class ClosureMattePlugin : public Material {
    Vec3 albedo_;
    astroray::RGBAlbedoSpectrum albedoSpec_;

public:
    explicit ClosureMattePlugin(const astroray::ParamDict& p)
        : albedo_(p.getVec3("albedo", Vec3(0.75f))),
          albedoSpec_({albedo_.x, albedo_.y, albedo_.z}) {}

    Vec3 getAlbedo() const override { return albedo_; }

    astroray::MaterialClosureGraph closureGraph() const override {
        astroray::MaterialClosureGraph graph;
        graph.add(astroray::makeDiffuseClosure({albedo_.x, albedo_.y, albedo_.z}));
        return graph;
    }

    Vec3 eval(const HitRecord& rec, const Vec3&, const Vec3& wi) const {
        float cosTheta = wi.dot(rec.normal);
        return cosTheta > 0.0f ? albedo_ * (cosTheta / float(M_PI)) : Vec3(0);
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3&, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const override {
        float cosTheta = wi.dot(rec.normal);
        if (cosTheta <= 0.0f) return astroray::SampledSpectrum(0.0f);
        return albedoSpec_.sample(lambdas) * (cosTheta / float(M_PI));
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        (void)wo;
        Vec3 localWi = Vec3::randomCosineDirection(gen);
        BSDFSample s;
        s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
        s.f = eval(rec, Vec3(0), s.wi);
        s.pdf = pdf(rec, Vec3(0), s.wi);
        s.isDelta = false;
        return s;
    }

    float pdf(const HitRecord& rec, const Vec3&, const Vec3& wi) const override {
        float cosTheta = wi.dot(rec.normal);
        return cosTheta > 0.0f ? cosTheta / float(M_PI) : 0.0f;
    }
};

ASTRORAY_REGISTER_MATERIAL("closure_matte", ClosureMattePlugin)

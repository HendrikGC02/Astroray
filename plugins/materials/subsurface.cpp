#include "astroray/register.h"
#include "raytracer.h"

class SubsurfacePlugin : public Material {
    Vec3 albedo_;
    Vec3 scatterDistance_;
    float scale_;
    astroray::RGBAlbedoSpectrum albedo_spec_;

public:
    explicit SubsurfacePlugin(const astroray::ParamDict& p)
        : albedo_(p.getVec3("albedo", Vec3(0.8f))),
          scatterDistance_(p.getVec3("scatter_distance", Vec3(1.0f, 0.2f, 0.1f))),
          scale_(p.getFloat("scale", 1.0f)),
          albedo_spec_({albedo_.x, albedo_.y, albedo_.z}) {}

    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        float cosTheta = std::abs(wi.dot(rec.normal));
        float distance = 1.0f / (cosTheta + 0.1f);
        Vec3 transmission(
            std::exp(-distance * scale_ / scatterDistance_.x),
            std::exp(-distance * scale_ / scatterDistance_.y),
            std::exp(-distance * scale_ / scatterDistance_.z)
        );
        return albedo_ * transmission * cosTheta / float(M_PI);
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const override {
        float cosTheta = std::abs(wi.dot(rec.normal));
        float distance = 1.0f / (cosTheta + 0.1f);
        Vec3 t(std::exp(-distance * scale_ / scatterDistance_.x),
               std::exp(-distance * scale_ / scatterDistance_.y),
               std::exp(-distance * scale_ / scatterDistance_.z));
        astroray::SampledSpectrum trans =
            astroray::RGBAlbedoSpectrum({t.x, t.y, t.z}).sample(lambdas);
        return albedo_spec_.sample(lambdas) * trans * (cosTheta / float(M_PI));
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        std::uniform_real_distribution<float> dist(0, 1);
        Vec3 localWi = Vec3::randomCosineDirection(gen);
        if (dist(gen) < 0.5f) localWi.z = -localWi.z;
        s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
        float r = -std::log(dist(gen) + 0.001f) * scale_;
        Vec3 transmission(
            std::exp(-r / scatterDistance_.x),
            std::exp(-r / scatterDistance_.y),
            std::exp(-r / scatterDistance_.z)
        );
        s.f = albedo_ * transmission;
        s.pdf = std::abs(rec.normal.dot(s.wi)) / float(M_PI);
        s.isDelta = false;
        return s;
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        return std::abs(rec.normal.dot(wi)) / float(M_PI);
    }
};

ASTRORAY_REGISTER_MATERIAL("subsurface", SubsurfacePlugin)

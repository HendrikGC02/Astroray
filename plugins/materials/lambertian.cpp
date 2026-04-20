#include "astroray/register.h"
#include "raytracer.h"

class LambertianPlugin : public Material {
    Vec3 albedo_;
    float roughness_;
public:
    explicit LambertianPlugin(const astroray::ParamDict& p)
        : albedo_(p.getVec3("albedo", Vec3(0.8f))),
          roughness_(p.getFloat("roughness", 1.0f)) {}

    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        return (wi.dot(rec.normal) <= 0) ? Vec3(0) : albedo_ / M_PI * wi.dot(rec.normal);
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        Vec3 localWi = Vec3::randomCosineDirection(gen);
        s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
        s.f = albedo_ / M_PI * s.wi.dot(rec.normal);
        s.pdf = s.wi.dot(rec.normal) / M_PI;
        s.isDelta = false;
        return s;
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        float cosTheta = wi.dot(rec.normal);
        return cosTheta > 0 ? cosTheta / M_PI : 0;
    }
};

ASTRORAY_REGISTER_MATERIAL("lambertian", LambertianPlugin)

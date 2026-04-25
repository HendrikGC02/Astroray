#include "astroray/register.h"
#include "raytracer.h"

class PhongPlugin : public Material {
    Vec3 albedo_;
    float shininess_;
    float ks_;  // specular weight; kd = 1 - ks
    float kd_;
    astroray::RGBAlbedoSpectrum diffuse_spec_;
    astroray::RGBUnboundedSpectrum specular_spec_;

public:
    explicit PhongPlugin(const astroray::ParamDict& p)
        : albedo_(p.getVec3("albedo", Vec3(0.8f))),
          shininess_(std::max(1.0f, p.getFloat("shininess", 32.0f))),
          ks_(std::clamp(p.getFloat("specular", 0.3f), 0.0f, 1.0f)),
          kd_(1.0f - ks_),
          diffuse_spec_({albedo_.x, albedo_.y, albedo_.z}),
          specular_spec_({1.0f, 1.0f, 1.0f}) {}

    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        float cosTheta = wi.dot(rec.normal);
        if (cosTheta <= 0) return Vec3(0);

        Vec3 diffuse = albedo_ * (kd_ / M_PI * cosTheta);

        Vec3 refl = (rec.normal * (2 * wo.dot(rec.normal)) - wo).normalized();
        float cosAlpha = std::max(0.0f, wi.dot(refl));
        float specFactor = (shininess_ + 1) / (2 * float(M_PI));
        Vec3 specular = Vec3(ks_ * specFactor * std::pow(cosAlpha, shininess_));

        return diffuse + specular;
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const override {
        float cosTheta = wi.dot(rec.normal);
        if (cosTheta <= 0.0f) return astroray::SampledSpectrum(0.0f);

        astroray::SampledSpectrum diffuse =
            diffuse_spec_.sample(lambdas) * (kd_ / float(M_PI) * cosTheta);

        Vec3 refl = (rec.normal * (2 * wo.dot(rec.normal)) - wo).normalized();
        float cosAlpha = std::max(0.0f, wi.dot(refl));
        float specFactor = (shininess_ + 1) / (2 * float(M_PI));
        astroray::SampledSpectrum specular =
            specular_spec_.sample(lambdas) * (ks_ * specFactor * std::pow(cosAlpha, shininess_));

        return diffuse + specular;
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        std::uniform_real_distribution<float> dist(0, 1);

        if (dist(gen) < kd_) {
            Vec3 localWi = Vec3::randomCosineDirection(gen);
            s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
        } else {
            Vec3 refl = (rec.normal * (2 * wo.dot(rec.normal)) - wo).normalized();
            Vec3 u, v;
            buildOrthonormalBasis(refl, u, v);
            float r1 = dist(gen), r2 = dist(gen);
            float cosTheta = std::pow(r1, 1.0f / (shininess_ + 1));
            float sinTheta = std::sqrt(std::max(0.0f, 1.0f - cosTheta * cosTheta));
            float phi = 2 * float(M_PI) * r2;
            s.wi = (u * std::cos(phi) * sinTheta + v * std::sin(phi) * sinTheta + refl * cosTheta).normalized();
        }

        float cosI = s.wi.dot(rec.normal);
        if (cosI <= 0) { s.f = Vec3(0); s.pdf = 0; s.isDelta = false; return s; }
        s.f = eval(rec, wo, s.wi);
        s.pdf = pdf(rec, wo, s.wi);
        s.isDelta = false;
        return s;
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        float cosI = wi.dot(rec.normal);
        if (cosI <= 0) return 0;
        float pDiff = kd_ * cosI / float(M_PI);
        Vec3 refl = (rec.normal * (2 * wo.dot(rec.normal)) - wo).normalized();
        float cosAlpha = std::max(0.0f, wi.dot(refl));
        float pSpec = ks_ * (shininess_ + 1) / (2 * float(M_PI)) * std::pow(cosAlpha, shininess_);
        return pDiff + pSpec;
    }
};

ASTRORAY_REGISTER_MATERIAL("phong", PhongPlugin)

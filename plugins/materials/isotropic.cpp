#include "astroray/register.h"
#include "raytracer.h"

// Isotropic phase function for volumetric scattering.
// Scatters light uniformly in all directions with phase function p = 1/(4*PI).
class IsotropicPlugin : public Material {
    Vec3 albedo_;
    astroray::RGBAlbedoSpectrum albedo_spec_;

    static constexpr float kInv4Pi = 1.0f / (4.0f * float(M_PI));

public:
    explicit IsotropicPlugin(const astroray::ParamDict& p)
        : albedo_(p.getVec3("albedo", Vec3(1.0f))),
          albedo_spec_({albedo_.x, albedo_.y, albedo_.z}) {}

    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        return albedo_ * kInv4Pi;
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const override {
        return albedo_spec_.sample(lambdas) * kInv4Pi;
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        std::uniform_real_distribution<float> dist(0.0f, 1.0f);
        float u1 = dist(gen), u2 = dist(gen);
        float cosTheta = 1.0f - 2.0f * u1;
        float sinTheta = std::sqrt(std::max(0.0f, 1.0f - cosTheta * cosTheta));
        float phi = 2.0f * float(M_PI) * u2;
        s.wi = Vec3(sinTheta * std::cos(phi), sinTheta * std::sin(phi), cosTheta);
        s.f = albedo_ * kInv4Pi;
        s.pdf = kInv4Pi;
        s.isDelta = false;
        return s;
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        return kInv4Pi;
    }
};

ASTRORAY_REGISTER_MATERIAL("isotropic", IsotropicPlugin)

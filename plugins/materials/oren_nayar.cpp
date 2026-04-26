#include "astroray/register.h"
#include "raytracer.h"

class OrenNayarPlugin : public Material {
    Vec3 albedo_;
    float roughness_;
    astroray::RGBAlbedoSpectrum albedo_spec_;

    // Precomputed Oren-Nayar A and B coefficients
    float A_, B_;

public:
    explicit OrenNayarPlugin(const astroray::ParamDict& p)
        : albedo_(p.getVec3("albedo", Vec3(0.8f))),
          roughness_(p.getFloat("roughness", 0.5f)),
          albedo_spec_({albedo_.x, albedo_.y, albedo_.z}) {
        float s2 = roughness_ * roughness_;
        A_ = 1.0f - 0.5f * s2 / (s2 + 0.33f);
        B_ = 0.45f * s2 / (s2 + 0.09f);
    }

    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        float NdotL = wi.dot(rec.normal);
        float NdotV = wo.dot(rec.normal);
        if (NdotL <= 0.0f || NdotV <= 0.0f) return Vec3(0.0f);

        // Project wi and wo onto the tangent plane to get the azimuthal difference
        Vec3 wiPerp = (wi - rec.normal * NdotL);
        Vec3 woPerp = (wo - rec.normal * NdotV);
        float lenWi = wiPerp.length(), lenWo = woPerp.length();
        float cosPhiDiff = (lenWi > 1e-6f && lenWo > 1e-6f)
            ? std::max(0.0f, wiPerp.dot(woPerp) / (lenWi * lenWo))
            : 0.0f;

        float cosAlpha = std::min(NdotL, NdotV);
        float sinAlpha = std::sqrt(std::max(0.0f, 1.0f - cosAlpha * cosAlpha));
        float maxNdot  = std::max(NdotL, NdotV);
        float tanBeta  = (maxNdot > 1e-6f)
            ? std::sqrt(std::max(0.0f, 1.0f - maxNdot * maxNdot)) / maxNdot
            : 0.0f;

        float f = (A_ + B_ * cosPhiDiff * sinAlpha * tanBeta) / float(M_PI);
        return albedo_ * f * NdotL;
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const override {
        float NdotL = wi.dot(rec.normal);
        float NdotV = wo.dot(rec.normal);
        if (NdotL <= 0.0f || NdotV <= 0.0f) return astroray::SampledSpectrum(0.0f);

        Vec3 wiPerp = wi - rec.normal * NdotL;
        Vec3 woPerp = wo - rec.normal * NdotV;
        float lenWi = wiPerp.length(), lenWo = woPerp.length();
        float cosPhiDiff = (lenWi > 1e-6f && lenWo > 1e-6f)
            ? std::max(0.0f, wiPerp.dot(woPerp) / (lenWi * lenWo))
            : 0.0f;

        float cosAlpha = std::min(NdotL, NdotV);
        float sinAlpha = std::sqrt(std::max(0.0f, 1.0f - cosAlpha * cosAlpha));
        float maxNdot  = std::max(NdotL, NdotV);
        float tanBeta  = (maxNdot > 1e-6f)
            ? std::sqrt(std::max(0.0f, 1.0f - maxNdot * maxNdot)) / maxNdot
            : 0.0f;

        float f = (A_ + B_ * cosPhiDiff * sinAlpha * tanBeta) / float(M_PI);
        return albedo_spec_.sample(lambdas) * (f * NdotL);
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        Vec3 localWi = Vec3::randomCosineDirection(gen);
        s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
        s.f = eval(rec, wo, s.wi);
        s.pdf = std::max(0.0f, s.wi.dot(rec.normal)) / float(M_PI);
        s.isDelta = false;
        return s;
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        float cosTheta = wi.dot(rec.normal);
        return cosTheta > 0.0f ? cosTheta / float(M_PI) : 0.0f;
    }
};

ASTRORAY_REGISTER_MATERIAL("oren_nayar", OrenNayarPlugin)

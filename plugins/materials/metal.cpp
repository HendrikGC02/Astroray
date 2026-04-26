#include "astroray/register.h"
#include "raytracer.h"

class MetalPlugin : public Material {
    Vec3 albedo_;
    float roughness_;
    astroray::RGBAlbedoSpectrum albedo_spec_;
    static constexpr float kNearDeltaThreshold = 0.1f;

    Vec3 fresnelSchlick(float cosTheta, const Vec3& F0) const {
        float c = std::clamp(cosTheta, 0.0f, 1.0f);
        return F0 + (Vec3(1) - F0) * std::pow(1 - c, 5);
    }

public:
    explicit MetalPlugin(const astroray::ParamDict& p)
        : albedo_(p.getVec3("albedo", Vec3(0.8f))),
          roughness_(std::clamp(p.getFloat("roughness", 0.1f), 0.001f, 1.0f)),
          albedo_spec_({albedo_.x, albedo_.y, albedo_.z}) {}

    bool isGlossy() const override { return true; }
    Vec3 getAlbedo() const override { return albedo_; }

    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        if (roughness_ <= kNearDeltaThreshold) {
            Vec3 perfectRefl = rec.normal * (2 * wo.dot(rec.normal)) - wo;
            float deviation = (wi - perfectRefl).length();
            return (deviation < 0.1f) ? albedo_ * std::exp(-deviation * 100.0f) : Vec3(0);
        }

        float rawNdotL = rec.normal.dot(wi);
        float rawNdotV = rec.normal.dot(wo);
        if (rawNdotL <= 0 || rawNdotV <= 0) return Vec3(0);

        Vec3 h = (wo + wi).normalized();
        float NdotH = std::max(rec.normal.dot(h), 0.001f);
        float NdotL = rawNdotL;
        float NdotV = rawNdotV;

        float a = roughness_ * roughness_, a2 = a * a;
        float denom = NdotH * NdotH * (a2 - 1) + 1;
        float D = a2 / (M_PI * denom * denom + 0.001f);
        Vec3 F = fresnelSchlick(wo.dot(h), albedo_);
        float k = (roughness_ + 1) * (roughness_ + 1) / 8;
        float G = (NdotL / (NdotL * (1 - k) + k)) * (NdotV / (NdotV * (1 - k) + k));
        Vec3 singleScatter = F * D * G / (4 * NdotV + 0.001f);
        float Fms = ggxMultiScatterCompensation(NdotV, NdotL, roughness_);
        float msWeight = roughness_ * (2.0f - roughness_);
        Vec3 multiScatter = albedo_ * (Fms * msWeight * 1.3f);
        return singleScatter + multiScatter;
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const override {
        if (roughness_ <= kNearDeltaThreshold) {
            Vec3 perfectRefl = rec.normal * (2 * wo.dot(rec.normal)) - wo;
            float deviation = (wi - perfectRefl).length();
            float factor = (deviation < 0.1f) ? std::exp(-deviation * 100.0f) : 0.0f;
            return albedo_spec_.sample(lambdas) * factor;
        }
        float rawNdotL = rec.normal.dot(wi);
        float rawNdotV = rec.normal.dot(wo);
        if (rawNdotL <= 0 || rawNdotV <= 0) return astroray::SampledSpectrum(0.0f);
        Vec3 h = (wo + wi).normalized();
        float NdotH = std::max(rec.normal.dot(h), 0.001f);
        float NdotL = rawNdotL, NdotV = rawNdotV;
        float a = roughness_ * roughness_, a2 = a * a;
        float denom = NdotH * NdotH * (a2 - 1) + 1;
        float D = a2 / (float(M_PI) * denom * denom + 0.001f);
        // Per-Î» Schlick Fresnel: F0 is the albedo spectrum; scale by (1-cosTheta)^5 term.
        astroray::SampledSpectrum F0 = albedo_spec_.sample(lambdas);
        float fresnelPow5 = std::pow(1.0f - std::clamp(h.dot(wo), 0.0f, 1.0f), 5.0f);
        astroray::SampledSpectrum F = F0 + (astroray::SampledSpectrum(1.0f) - F0) * fresnelPow5;
        float k = (roughness_ + 1) * (roughness_ + 1) / 8;
        float G = (NdotL / (NdotL * (1 - k) + k)) * (NdotV / (NdotV * (1 - k) + k));
        astroray::SampledSpectrum singleScatter = F * (D * G / (4 * NdotV + 0.001f));
        float Fms = ggxMultiScatterCompensation(NdotV, NdotL, roughness_);
        float msWeight = roughness_ * (2.0f - roughness_);
        astroray::SampledSpectrum multiScatter = albedo_spec_.sample(lambdas) * (Fms * msWeight * 1.3f);
        return singleScatter + multiScatter;
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        if (roughness_ <= kNearDeltaThreshold) {
            s.wi = rec.normal * (2 * wo.dot(rec.normal)) - wo;
            s.f = albedo_;
            s.pdf = 1;
            s.isDelta = true;
            const_cast<HitRecord&>(rec).isDelta = true;
        } else {
            std::uniform_real_distribution<float> dist(0, 1);
            float a = roughness_ * roughness_;
            float phi = 2 * M_PI * dist(gen);
            float cosTheta = std::sqrt((1 - dist(gen)) / (1 + (a*a - 1) * dist(gen)));
            float sinTheta = std::sqrt(1 - cosTheta * cosTheta);
            Vec3 h(std::cos(phi) * sinTheta, std::sin(phi) * sinTheta, cosTheta);
            h = rec.tangent * h.x + rec.bitangent * h.y + rec.normal * h.z;
            s.wi = (h * (2 * wo.dot(h)) - wo).normalized();
            s.f = Vec3(0);
            s.pdf = 0.0f;
            if (s.wi.dot(rec.normal) > 0) {
                s.f = eval(rec, wo, s.wi);
                float NdotH = std::max(rec.normal.dot(h), 0.001f);
                float HdotV = std::max(h.dot(wo), 0.001f);
                float a2 = a * a, d = NdotH * NdotH * (a2 - 1) + 1;
                float D = a2 / (M_PI * d * d + 0.001f);
                s.pdf = D * NdotH / (4.0f * HdotV);
            }
            s.isDelta = false;
        }
        return s;
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        if (roughness_ <= kNearDeltaThreshold) return 0;
        Vec3 h = (wo + wi).normalized();
        float NdotH = std::max(rec.normal.dot(h), 0.001f);
        float HdotV = std::max(h.dot(wo), 0.001f);
        float a = roughness_ * roughness_, a2 = a * a;
        float denom = NdotH * NdotH * (a2 - 1) + 1;
        float D = a2 / (M_PI * denom * denom + 0.001f);
        return D * NdotH / (4.0f * HdotV);
    }
};

ASTRORAY_REGISTER_MATERIAL("metal", MetalPlugin)

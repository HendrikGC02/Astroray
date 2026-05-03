#include "astroray/register.h"
#include "astroray/spectrum.h"
#include "raytracer.h"

#include <cmath>

class ThinGlassPlugin : public Material {
    Vec3 tint_;
    float ior_;
    float roughness_;
    float transmission_;
    astroray::RGBAlbedoSpectrum tintSpec_;

    float fresnelDielectric(float cosThetaI, float etaI, float etaT) const {
        cosThetaI = std::clamp(cosThetaI, -1.0f, 1.0f);
        bool entering = cosThetaI > 0.0f;
        if (!entering) { std::swap(etaI, etaT); cosThetaI = std::abs(cosThetaI); }
        float sinThetaI = std::sqrt(std::max(0.0f, 1.0f - cosThetaI * cosThetaI));
        float sinThetaT = etaI / etaT * sinThetaI;
        if (sinThetaT >= 1.0f) return 1.0f;
        float cosThetaT = std::sqrt(std::max(0.0f, 1.0f - sinThetaT * sinThetaT));
        float rParl = ((etaT * cosThetaI) - (etaI * cosThetaT)) /
                      ((etaT * cosThetaI) + (etaI * cosThetaT));
        float rPerp = ((etaI * cosThetaI) - (etaT * cosThetaT)) /
                      ((etaI * cosThetaI) + (etaT * cosThetaT));
        return (rParl * rParl + rPerp * rPerp) * 0.5f;
    }

    Vec3 sampleCone(const Vec3& dir, float roughness, std::mt19937& gen) const {
        if (roughness <= 0.001f) return dir.normalized();

        Vec3 w = dir.normalized();
        Vec3 a = (std::abs(w.x) > 0.9f) ? Vec3(0, 1, 0) : Vec3(1, 0, 0);
        Vec3 u = (a - w * a.dot(w)).normalized();
        Vec3 v = w.cross(u);

        std::uniform_real_distribution<float> dist(0.0f, 1.0f);
        float maxAngle = std::clamp(roughness, 0.0f, 1.0f) * 0.35f;
        float cosMax = std::cos(maxAngle);
        float cosTheta = 1.0f - dist(gen) * (1.0f - cosMax);
        float sinTheta = std::sqrt(std::max(0.0f, 1.0f - cosTheta * cosTheta));
        float phi = 2.0f * float(M_PI) * dist(gen);
        return (u * (std::cos(phi) * sinTheta) +
                v * (std::sin(phi) * sinTheta) +
                w * cosTheta).normalized();
    }

public:
    explicit ThinGlassPlugin(const astroray::ParamDict& p)
        : tint_(p.getVec3("albedo", Vec3(1.0f))),
          ior_(p.getFloat("ior", 1.5f)),
          roughness_(std::clamp(p.getFloat("roughness", 0.0f), 0.0f, 1.0f)),
          transmission_(std::clamp(p.getFloat("transmission", 1.0f), 0.0f, 1.0f)),
          tintSpec_({tint_.x, tint_.y, tint_.z}) {}

    bool isTransmissive() const override { return true; }
    Vec3 getAlbedo() const override { return tint_; }
    std::string getGPUTypeName() const override { return "thin_glass"; }
    float getIOR() const override { return ior_; }
    float getRoughness() const override { return roughness_; }
    float getTransmission() const override { return transmission_; }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord&, const Vec3&, const Vec3&,
            const astroray::SampledWavelengths&) const override {
        return astroray::SampledSpectrum(0.0f);
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        s.isDelta = roughness_ < 0.02f;
        const_cast<HitRecord&>(rec).isDelta = s.isDelta;

        float cosTheta = std::abs(wo.normalized().dot(rec.normal));
        float F = fresnelDielectric(cosTheta, 1.0f, ior_);
        float reflectProb = std::clamp(F, 0.0f, 1.0f);
        float transmitProb = std::max(0.0f, (1.0f - reflectProb) * transmission_);
        float totalProb = reflectProb + transmitProb;
        if (totalProb <= 1e-5f) {
            s.wi = sampleCone(rec.normal * (2.0f * wo.dot(rec.normal)) - wo, roughness_, gen);
            s.f = Vec3(0.0f);
            s.pdf = 1.0f;
            return s;
        }

        reflectProb /= totalProb;
        transmitProb /= totalProb;

        std::uniform_real_distribution<float> dist(0.0f, 1.0f);
        if (dist(gen) < reflectProb) {
            s.wi = sampleCone(rec.normal * (2.0f * wo.dot(rec.normal)) - wo, roughness_, gen);
            s.f = Vec3(reflectProb);
            s.pdf = std::max(reflectProb, 1e-4f);
        } else {
            s.wi = sampleCone(-wo, roughness_, gen);
            s.f = tint_ * transmitProb;
            s.pdf = std::max(transmitProb, 1e-4f);
        }
        return s;
    }

    BSDFSampleSpectral sampleSpectral(
            const HitRecord& rec, const Vec3& wo, std::mt19937& gen,
            astroray::SampledWavelengths& lambdas) const override {
        BSDFSample rgb = sample(rec, wo, gen);
        BSDFSampleSpectral s;
        s.wi = rgb.wi;
        s.pdf = rgb.pdf;
        s.isDelta = rgb.isDelta;
        s.f_spectral = (rgb.wi.dot(rec.normal) * wo.dot(rec.normal) > 0.0f)
            ? astroray::SampledSpectrum(rgb.f.x)
            : tintSpec_.sample(lambdas) * (rgb.f.x > 0.0f ? rgb.f.x / std::max(tint_.x, 1e-4f) : 0.0f);
        return s;
    }
};

struct ArchitecturalGlassPlugin : public ThinGlassPlugin {
    using ThinGlassPlugin::ThinGlassPlugin;
};

ASTRORAY_REGISTER_MATERIAL("thin_glass", ThinGlassPlugin)
ASTRORAY_REGISTER_MATERIAL("architectural_glass", ArchitecturalGlassPlugin)

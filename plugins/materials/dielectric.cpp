#include "astroray/register.h"
#include "raytracer.h"

class DielectricPlugin : public Material {
    float ior_;

    float fresnelDielectric(float cosThetaI, float etaI, float etaT) const {
        cosThetaI = std::clamp(cosThetaI, -1.0f, 1.0f);
        bool entering = cosThetaI > 0;
        if (!entering) { std::swap(etaI, etaT); cosThetaI = std::abs(cosThetaI); }
        float sinThetaI = std::sqrt(std::max(0.0f, 1 - cosThetaI * cosThetaI));
        float sinThetaT = etaI / etaT * sinThetaI;
        if (sinThetaT >= 1) return 1;
        float cosThetaT = std::sqrt(std::max(0.0f, 1 - sinThetaT * sinThetaT));
        float Rparl = ((etaT * cosThetaI) - (etaI * cosThetaT)) / ((etaT * cosThetaI) + (etaI * cosThetaT));
        float Rperp = ((etaI * cosThetaI) - (etaT * cosThetaT)) / ((etaI * cosThetaI) + (etaT * cosThetaT));
        return (Rparl * Rparl + Rperp * Rperp) / 2;
    }

public:
    explicit DielectricPlugin(const astroray::ParamDict& p)
        : ior_(p.getFloat("ior", 1.5f)) {}

    bool isTransmissive() const override { return true; }
    Vec3 getAlbedo() const override { return Vec3(1.0f); }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        s.isDelta = true;
        const_cast<HitRecord&>(rec).isDelta = true;

        float cosTheta = wo.dot(rec.normal);
        float etaI = 1, etaT = ior_;
        Vec3 n = rec.normal;
        if (cosTheta < 0) { cosTheta = -cosTheta; std::swap(etaI, etaT); n = -n; }

        float eta = etaI / etaT;
        float sinTheta = std::sqrt(std::max(0.0f, 1 - cosTheta * cosTheta));
        bool cannotRefract = eta * sinTheta > 1;

        std::uniform_real_distribution<float> dist(0, 1);
        float fresnel = fresnelDielectric(cosTheta, etaI, etaT);

        if (cannotRefract || dist(gen) < fresnel) {
            s.wi = n * (2 * wo.dot(n)) - wo;
            s.f = Vec3(1);
            s.pdf = 1.0f;
        } else {
            Vec3 wt_perp = (wo - n * cosTheta) * (-eta);
            Vec3 wt_parallel = n * (-std::sqrt(std::abs(1 - wt_perp.length2())));
            s.wi = (wt_perp + wt_parallel).normalized();
            s.f = Vec3(eta * eta);
            s.pdf = 1.0f;
        }
        return s;
    }
};

struct GlassPlugin : public DielectricPlugin { using DielectricPlugin::DielectricPlugin; };

ASTRORAY_REGISTER_MATERIAL("dielectric", DielectricPlugin)
ASTRORAY_REGISTER_MATERIAL("glass", GlassPlugin)

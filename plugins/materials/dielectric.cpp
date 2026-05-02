#include "astroray/register.h"
#include "astroray/spectrum.h"
#include "raytracer.h"

#include <cmath>
#include <string>

struct SellmeierCoeffs { Vec3 B; Vec3 C; };

static SellmeierCoeffs lookupPreset(const std::string& name) {
    if (name == "bk7")
        return {{1.03961212f, 0.231792344f, 1.01046945f},
                {0.00600069867f, 0.0200179144f, 103.560653f}};
    if (name == "fused_silica")
        return {{0.6961663f, 0.4079426f, 0.8974794f},
                {0.0046791f, 0.0135121f, 97.9340f}};
    if (name == "flint_sf11")
        return {{1.73759695f, 0.313747346f, 1.89878101f},
                {0.013188707f, 0.0623068142f, 155.23629f}};
    if (name == "diamond")
        return {{0.3306f, 4.3356f, 0.0f},
                {0.0175f, 0.1060f, 0.0f}};
    return {{0.0f, 0.0f, 0.0f}, {0.0f, 0.0f, 0.0f}};
}

static float sellmeierIOR(float lambda_nm, Vec3 B, Vec3 C) {
    float l = lambda_nm * 1e-3f; // nm → μm
    float l2 = l * l;
    float n2 = 1.0f + B.x*l2/(l2 - C.x) + B.y*l2/(l2 - C.y) + B.z*l2/(l2 - C.z);
    return std::sqrt(std::max(1.0f, n2));
}

class DielectricPlugin : public Material {
    float ior_;
    bool dispersive_;
    SellmeierCoeffs sellmeier_;

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

    BSDFSampleSpectral refractSpectral(
            const HitRecord& rec, const Vec3& wo,
            std::mt19937& gen, float ior) const {
        BSDFSampleSpectral bss;
        bss.isDelta = true;
        const_cast<HitRecord&>(rec).isDelta = true;

        float cosTheta = wo.dot(rec.normal);
        float etaI = 1.0f, etaT = ior;
        Vec3 n = rec.normal;
        if (cosTheta < 0) { cosTheta = -cosTheta; std::swap(etaI, etaT); n = -n; }

        float eta = etaI / etaT;
        float sinTheta = std::sqrt(std::max(0.0f, 1.0f - cosTheta * cosTheta));
        bool cannotRefract = eta * sinTheta > 1.0f;

        std::uniform_real_distribution<float> dist(0.0f, 1.0f);
        float fresnel = fresnelDielectric(cosTheta, etaI, etaT);

        bool reflected = cannotRefract || dist(gen) < fresnel;
        if (reflected) {
            bss.wi = n * (2.0f * wo.dot(n)) - wo;
            bss.f_spectral = astroray::SampledSpectrum(1.0f);
        } else {
            Vec3 wt_perp = (wo - n * cosTheta) * (-eta);
            Vec3 wt_parallel = n * (-std::sqrt(std::abs(1.0f - wt_perp.length2())));
            bss.wi = (wt_perp + wt_parallel).normalized();
            bss.f_spectral = astroray::SampledSpectrum(eta * eta);
        }
        bss.pdf = 1.0f;
        return bss;
    }

public:
    explicit DielectricPlugin(const astroray::ParamDict& p)
        : ior_(p.getFloat("ior", 1.5f)),
          dispersive_(false),
          sellmeier_{{0,0,0},{0,0,0}} {
        std::string preset = p.getString("sellmeier_preset", "");
        if (!preset.empty()) {
            sellmeier_ = lookupPreset(preset);
            dispersive_ = (sellmeier_.B.x != 0.0f || sellmeier_.B.y != 0.0f);
        }
    }

    bool isTransmissive() const override { return true; }
    Vec3 getAlbedo() const override { return Vec3(1.0f); }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord&, const Vec3&, const Vec3&,
            const astroray::SampledWavelengths&) const override {
        return astroray::SampledSpectrum(0.0f);
    }

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

    BSDFSampleSpectral sampleSpectral(
            const HitRecord& rec, const Vec3& wo,
            std::mt19937& gen,
            astroray::SampledWavelengths& lambdas) const override {
        if (!dispersive_)
            return refractSpectral(rec, wo, gen, ior_);

        float heroIOR = sellmeierIOR(lambdas.lambda(0), sellmeier_.B, sellmeier_.C);
        BSDFSampleSpectral bss = refractSpectral(rec, wo, gen, heroIOR);

        // On refraction (not reflection), each wavelength refracts differently.
        // We can only trace one direction — terminate secondaries.
        bool reflected = (bss.wi.dot(rec.normal) > 0) == (wo.dot(rec.normal) > 0);
        if (!reflected) {
            lambdas.terminateSecondary();
        }

        return bss;
    }
};

struct GlassPlugin : public DielectricPlugin { using DielectricPlugin::DielectricPlugin; };

ASTRORAY_REGISTER_MATERIAL("dielectric", DielectricPlugin)
ASTRORAY_REGISTER_MATERIAL("glass", GlassPlugin)

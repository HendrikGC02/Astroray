#include "astroray/register.h"
#include "astroray/optical_presets.h"
#include "astroray/spectrum.h"
#include "raytracer.h"

#include <cmath>
#include <string>

static float sellmeierIOR(float lambda_nm, Vec3 B, Vec3 C) {
    float l = lambda_nm * 1e-3f; // nm → μm
    float l2 = l * l;
    float n2 = 1.0f + B.x*l2/(l2 - C.x) + B.y*l2/(l2 - C.y) + B.z*l2/(l2 - C.z);
    return std::sqrt(std::max(1.0f, n2));
}

class DielectricPlugin : public Material {
    float ior_;
    bool dispersive_;
    Vec3 sellmeierB_;
    Vec3 sellmeierC_;
    Vec3 tint_;
    astroray::RGBAlbedoSpectrum tintSpec_;

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
            std::mt19937& gen, float ior,
            const astroray::SampledWavelengths& lambdas) const {
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
            bss.f_spectral = tintSpec_.sample(lambdas) * (eta * eta);
        }
        bss.pdf = 1.0f;
        return bss;
    }

public:
    explicit DielectricPlugin(const astroray::ParamDict& p)
        : ior_(p.getFloat("ior", 1.5f)),
          dispersive_(false),
          sellmeierB_(0.0f),
          sellmeierC_(0.0f),
          tint_(p.getVec3("albedo", Vec3(1.0f))),
          tintSpec_({tint_.x, tint_.y, tint_.z}) {
        std::string preset = p.getString("sellmeier_preset", "");
        if (preset.empty()) preset = p.getString("glass_preset", "");
        if (preset.empty()) preset = p.getString("preset", "");
        if (!preset.empty()) {
            if (const auto* data = astroray::findOpticalGlassPreset(preset)) {
                ior_ = p.getFloat("ior", data->ior);
                sellmeierB_ = data->sellmeierB;
                sellmeierC_ = data->sellmeierC;
                dispersive_ = data->hasSellmeier;
                if ((tint_ - Vec3(1.0f)).length2() < 1e-6f) {
                    tint_ = data->transmissionTint;
                    tintSpec_ = astroray::RGBAlbedoSpectrum({tint_.x, tint_.y, tint_.z});
                }
            }
        }
    }

    bool isTransmissive() const override { return true; }
    Vec3 getAlbedo() const override { return tint_; }
    std::string getGPUTypeName() const override { return "dielectric"; }
    float getIOR() const override { return ior_; }
    MaterialBackendCapabilities backendCapabilities() const override {
        MaterialBackendCapabilities caps;
        caps.gpuType = "dielectric";
        if (dispersive_) {
            caps.gpu = false;
            caps.gpuSpectral = false;
            caps.notes = "Sellmeier dispersion requires wavelength-dependent GPU refraction and remains CPU-only";
        } else {
            caps.gpu = true;
            caps.gpuSpectral = true;
            caps.notes = "spectral flat-IOR dielectric GPU lowering";
        }
        return caps;
    }

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
            s.f = tint_ * (eta * eta);
            s.pdf = 1.0f;
        }
        return s;
    }

    BSDFSampleSpectral sampleSpectral(
            const HitRecord& rec, const Vec3& wo,
            std::mt19937& gen,
            astroray::SampledWavelengths& lambdas) const override {
        if (!dispersive_)
            return refractSpectral(rec, wo, gen, ior_, lambdas);

        float heroIOR = sellmeierIOR(lambdas.lambda(0), sellmeierB_, sellmeierC_);
        BSDFSampleSpectral bss = refractSpectral(rec, wo, gen, heroIOR, lambdas);

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

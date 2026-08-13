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

        // Enter/exit MUST come from rec.frontFace, not the sign of wo·rec.normal.
        // rec.normal is the front-facing (setFaceNormal'd) shading normal, so
        // wo·rec.normal is ALWAYS > 0 and the old sign test read every hit as
        // "entering" -> eta = 1/ior at BOTH surfaces -> the eta^2 radiance factor
        // never cancelled (glass rendered too dark, loss growing with IOR). Disney
        // already keys off rec.frontFace; this mirrors it.
        float cosTheta = wo.dot(rec.normal);
        float etaI = rec.frontFace ? 1.0f : ior;
        float etaT = rec.frontFace ? ior : 1.0f;
        Vec3 n = rec.normal;
        if (cosTheta < 0) { cosTheta = -cosTheta; n = -n; }

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
        // pkg195 Stage C: manual Sellmeier B/C coefficients. When no preset is
        // active, the Astroray Sellmeier Glass node sends sellmeier_b/sellmeier_c
        // float3 triples (the addon socket defaults are the Schott BK7 terms).
        // Previously these were exported but no engine code read them — the
        // "manual coefficients" UI was a silent no-op. A non-zero B vector turns
        // on dispersion using the supplied coefficients.
        if (!dispersive_) {
            Vec3 bMan = p.getVec3("sellmeier_b", Vec3(0.0f));
            Vec3 cMan = p.getVec3("sellmeier_c", Vec3(0.0f));
            if (bMan.length2() > 0.0f) {
                sellmeierB_ = bMan;
                sellmeierC_ = cMan;
                dispersive_ = true;
            }
        }
    }

    bool isTransmissive() const override { return true; }
    Vec3 getAlbedo() const override { return tint_; }
    std::string getGPUTypeName() const override { return "dielectric"; }
    float getIOR() const override { return ior_; }
    // Wavelength-dependent IOR. With a Sellmeier preset loaded this evaluates
    // the dispersion equation at λ; otherwise it falls back to the flat IOR.
    // Consumed by pkg64 Phase 2 SMS wavelength-Newton (Hanika 2015 §4).
    float iorAt(float lambda_nm) const override {
        if (!dispersive_) return ior_;
        return sellmeierIOR(lambda_nm, sellmeierB_, sellmeierC_);
    }
    // pkg64-gpu-sellmeier-upload: expose dispersion data for GPU upload
    bool isDispersive() const override { return dispersive_; }
    Vec3 getSellmeierB() const override { return sellmeierB_; }
    Vec3 getSellmeierC() const override { return sellmeierC_; }
    astroray::MaterialClosureGraph closureGraph() const override {
        astroray::MaterialClosureGraph graph;
        if (!dispersive_) {
            graph.add(astroray::makeDielectricTransmissionClosure(
                {tint_.x, tint_.y, tint_.z}, ior_));
        }
        return graph;
    }
    MaterialBackendCapabilities backendCapabilities() const override {
        MaterialBackendCapabilities caps;
        // pkg64-gpu-sellmeier-upload: dispersive dielectrics now upload to GPU
        // with Sellmeier coefficients + hero-wavelength IOR evaluation. The
        // GPU dielectric BSDF branches on GMaterial::isDispersive at runtime.
        caps.gpu = true;
        caps.gpuSpectral = true;
        if (dispersive_) {
            caps.gpuType = "dielectric";  // no closure graph for dispersive
            caps.notes = "spectral Sellmeier-dispersive dielectric GPU lowering (hero-wavelength)";
        } else {
            caps.closureGraph = true;
            caps.gpuType = "closure_graph";
            caps.notes = "spectral flat-IOR dielectric closure-graph GPU lowering";
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

        // Enter/exit from rec.frontFace (see refractSpectral above): rec.normal is
        // front-facing so the old sign test always read "entering" -> eta^2 never
        // cancelled across the glass -> too dark.
        float cosTheta = wo.dot(rec.normal);
        float etaI = rec.frontFace ? 1.0f : ior_;
        float etaT = rec.frontFace ? ior_ : 1.0f;
        Vec3 n = rec.normal;
        if (cosTheta < 0) { cosTheta = -cosTheta; n = -n; }

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

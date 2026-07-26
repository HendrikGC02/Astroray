#include "astroray/register.h"
#include "astroray/energy_compensation.h"
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

    // pkg160: GGX multiple-scattering energy compensation for the conductor
    // lobe. Kulla & Conty 2017 Eq. 6-9 / Cycles
    // bsdf_microfacet.h:389-436 `microfacet_ggx_preserve_energy`
    // (BSD-3-Clause), net factor "1 + Fms*(1-E)/E" — see
    // astroray::ggxDarkeningChannel. Identical in form and in table source to
    // disney.cpp::ggxCompensationFactor (`spec *= ggxCompensationFactor(F0,
    // roughness_, NdotV)`, disney.cpp:653), which is the shipped, verified
    // in-repo implementation this borrows rather than re-deriving.
    //
    // `Fss` = albedo_. For a conductor the Schlick F0 IS the reflectance
    // colour (fresnelSchlick above passes albedo_ as F0), and Disney at
    // metallic=1 collapses to exactly the same thing (F0 = Cspec0*(1-metallic)
    // + Cdlin*metallic = base colour, disney.cpp:530), so passing albedo_ here
    // keeps plain `metal` and Disney-metal on ONE compensation — the pkg158
    // reconciliation would be re-split if they disagreed. Cycles' own
    // generalized-Schlick branch is slightly different (`Fss = mix(f0, f90,
    // 1/21)`, the hemispherical average of the Schlick lobe, ~0.4% above F0
    // at albedo 0.92 and ~9% at 0.35); adopting it would have to be done for
    // BOTH plugins at once and is deliberately out of scope here.
    //
    // Fallback when the shipped tables are missing is 1.0 (identity) — this
    // factor is MULTIPLICATIVE, so identity degrades to the uncompensated
    // single-scatter lobe. (The term this replaced was additive, where the
    // safe fallback would have been 0.0.)
    Vec3 ggxCompensationFactor(float mu) const {
        const auto& tables = astroray::DisneyEnergyCompensationTables::instance();
        if (!tables.loaded()) return Vec3(1.0f);

        const float E = std::max(tables.ggxE(roughness_, mu), 1e-4f);
        const float Eavg = std::clamp(tables.ggxEavg(roughness_), 0.0f, 0.999f);
        return Vec3(astroray::ggxDarkeningChannel(albedo_.x, E, Eavg),
                    astroray::ggxDarkeningChannel(albedo_.y, E, Eavg),
                    astroray::ggxDarkeningChannel(albedo_.z, E, Eavg));
    }

public:
    explicit MetalPlugin(const astroray::ParamDict& p)
        : albedo_(p.getVec3("albedo", Vec3(0.8f))),
          roughness_(std::clamp(p.getFloat("roughness", 0.1f), 0.001f, 1.0f)),
          albedo_spec_({albedo_.x, albedo_.y, albedo_.z}) {}

    bool isGlossy() const override { return true; }
    Vec3 getAlbedo() const override { return albedo_; }
    astroray::MaterialClosureGraph closureGraph() const override {
        astroray::MaterialClosureGraph graph;
        graph.add(astroray::makeGGXConductorClosure(
            {albedo_.x, albedo_.y, albedo_.z}, roughness_));
        return graph;
    }
    std::string getGPUTypeName() const override { return "metal"; }
    float getRoughness() const override { return roughness_; }

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
        // pkg160: multiplicative Kulla & Conty compensation, replacing an
        // additive `albedo_ * (Fms * roughness*(2-roughness) * 1.3f)` term
        // that (a) read a runtime-MC LUT whose 256 uniform-hemisphere samples
        // could not resolve a narrow GGX lobe (E -> 0 as roughness -> 0, which
        // pinned Fms near its 1/pi ceiling exactly where multiple scattering
        // should vanish), (b) carried NO NdotL and so violated the eval()
        // brdf*NdotL contract (AGENTS.md:87), and (c) used a hand-tuned
        // `roughness*(2-roughness)` weight and `1.3f` found in no publication.
        // Measured consequence at roughness 0.15: the old term contributed
        // 0.111*albedo of near-view-independent ambient floor, ~7x the typical
        // pixel's true radiance. See
        // .astroray_plan/packages/pkg160-gpu-plain-metal-multiscatter-omission.md.
        return singleScatter * ggxCompensationFactor(NdotV);
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
        // Per-wavelength Schlick Fresnel: F0 is the albedo spectrum; scale by (1-cosTheta)^5 term.
        astroray::SampledSpectrum F0 = albedo_spec_.sample(lambdas);
        float fresnelPow5 = std::pow(1.0f - std::clamp(h.dot(wo), 0.0f, 1.0f), 5.0f);
        astroray::SampledSpectrum F = F0 + (astroray::SampledSpectrum(1.0f) - F0) * fresnelPow5;
        float k = (roughness_ + 1) * (roughness_ + 1) / 8;
        float G = (NdotL / (NdotL * (1 - k) + k)) * (NdotV / (NdotV * (1 - k) + k));
        astroray::SampledSpectrum singleScatter = F * (D * G / (4 * NdotV + 0.001f));
        // pkg160: same multiplicative Kulla & Conty compensation as eval(),
        // applied PER WAVELENGTH. `Fss` is the conductor's reflectance, which
        // in the spectral path is F0 (= albedo_spec_ at these lambdas), so the
        // darkening factor is evaluated per sampled wavelength exactly the way
        // the Fresnel term above already is; E/Eavg are achromatic geometry
        // and stay scalar. See the ggxCompensationFactor comment for the
        // citation and for why the additive term it replaces was wrong.
        const auto& tables = astroray::DisneyEnergyCompensationTables::instance();
        if (!tables.loaded()) return singleScatter;
        const float E = std::max(tables.ggxE(roughness_, NdotV), 1e-4f);
        const float Eavg = std::clamp(tables.ggxEavg(roughness_), 0.0f, 0.999f);
        astroray::SampledSpectrum result = singleScatter;
        for (int i = 0; i < astroray::kSpectrumSamples; ++i)
            result[i] *= astroray::ggxDarkeningChannel(F0[i], E, Eavg);
        return result;
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
            float r1 = dist(gen);
            float r2 = dist(gen);
            float phi = 2 * M_PI * r1;
            float cosTheta = std::sqrt((1 - r2) / (1 + (a*a - 1) * r2));
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

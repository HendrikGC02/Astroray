// Native Cycles Principled BSDF port (pkg178 Stage 1 — CPU core lobes).
//
// Source: Blender Cycles @main (Blender 5.2-era) —
//   src/kernel/svm/closure.h            (CLOSURE_BSDF_PRINCIPLED_ID assembly + layering)
//   src/kernel/closure/bsdf_util.h      (closure_layering_weight, fresnel_dielectric_cos,
//                                        F0_from_ior, fresnel_f82{tint_B,}, schlick_fresnel)
//   src/kernel/closure/bsdf_microfacet.h (generalized_schlick_fresnel; GGX D/Lambda/VNDF;
//                                        microfacet_ggx_preserve_energy)
//   src/kernel/closure/bsdf_oren_nayar.h (Fujii improved Oren-Nayar + OpenPBR multiscatter)
// License: Apache-2.0 / BSD-3-Clause (several closure headers) — compatible with
//   Astroray's LICENSE; same citation pattern as disney.cpp / energy_compensation.h.
// Papers: Kulla & Conty 2017 (multiscatter GGX); Kutz/Hoffman F82-tint conductor;
//   Walter et al. 2007 (microfacet refraction); Heitz 2018 (VNDF); Fujii/OpenPBR (EON);
//   Veach 1997 §9.2.4 / PBRT-v4 §9.5 (one-sample MIS).
// Per-function math notes: .astroray_plan/docs/pkg178-stage1-closure-math-research.md
// Stage-0 map: docs/blender_parity/pkg178_stage0_closure_map.{md,json}
//
// Stage 1 = CPU only, four core lobes (diffuse Lambert/EON, specular GGX generalized-
// Schlick, metallic F82-tint, transmission rough glass). GPU (Stage 2), coat/sheen/
// aniso/emission/SSS (Stage 3), thin-film/thin-wall (Stage 4), addon flag (Stage 5)
// are DEFERRED and leave the documented lobe-contract seam below.

#include "astroray/register.h"
#include "astroray/energy_compensation.h"
#include "raytracer.h"

#include <algorithm>
#include <cmath>
#include <vector>

class PrincipledPlugin : public Material {
    // --- Cycles Principled inputs (Stage-1 subset; socket names) ---
    Vec3 baseColor_;
    float metallic_, roughness_, ior_, alpha_;
    float diffuseRoughness_;
    float specularIorLevel_;
    Vec3 specularTint_;
    float transmission_;
    bool thinWall_;  // parsed; Thin Wall is Stage 4 (unused here — seam only)

    // Smooth glass below this roughness is treated as a delta transmission event
    // (matches disney.cpp::kDeltaTransmissionRoughness).
    static constexpr float kDeltaGlassRoughness = 0.03f;

    // ======================================================================
    // Lobe-interface contract (the seam parallel lobe agents code against).
    // A new lobe = enum value + arm in the four evaluators + row in
    // assembleLobes(); the MIS recombination (eval/pdf/sample) is invariant.
    // ======================================================================
    enum class LobeKind { Diffuse, Specular, Metallic, Transmission };
    struct Lobe {
        LobeKind kind;
        Vec3 weight{1, 1, 1};  // spectral layering weight (RGB; upsampled per-λ)
        Vec3 color{1, 1, 1};   // reflectance colour (base_color / specular f0 / base_color)
        float roughness = 0.0f;
        float ior = 1.5f;
        float sel = 0.0f;      // scalar selection weight; Σ sel = W
        bool isDelta = false;  // smooth glass → excluded from continuous eval/pdf sums
    };

    // ----------------------------------------------------------------------
    // GGX + Fresnel primitives (ported verbatim from disney.cpp / metal.cpp,
    // which cite pbrt-v4 / Walter 2007 / Heitz 2018 per function).
    // ----------------------------------------------------------------------
    static float D_GTR2(float NdotH, float a) {
        float a2 = a * a;
        float t = 1 + (a2 - 1) * NdotH * NdotH;
        return a2 / (float(M_PI) * t * t);
    }
    // True Smith masking-shadowing G1 (Walter 2007 Eq. 34), used by the
    // rough-transmission estimator (disney.cpp comment).
    static float smithG1_GGX(float NdotV, float alphaG) {
        float a = alphaG * alphaG;
        float b = NdotV * NdotV;
        return 2.0f * NdotV / (NdotV + std::sqrt(a + b - a * b) + 0.001f);
    }
    // Schlick-GGX combined G (metal.cpp): G1(L)·G1(V) with k = (r+1)²/8.
    static float smithG_k(float NdotL, float NdotV, float roughness) {
        float k = (roughness + 1) * (roughness + 1) / 8.0f;
        return (NdotL / (NdotL * (1 - k) + k)) * (NdotV / (NdotV * (1 - k) + k));
    }

    // Cycles bsdf_util.h: F0_from_ior.
    static float F0_from_ior(float ior) {
        float f = (ior - 1.0f) / (ior + 1.0f);
        return f * f;
    }
    // Cycles bsdf_util.h: fresnel_dielectric_cos (unpolarized, real Fresnel).
    static float fresnelDielectricCos(float cosi, float eta) {
        float c = std::abs(cosi);
        float g = eta * eta - 1.0f + c * c;
        if (g > 0.0f) {
            g = std::sqrt(g);
            float A = (g - c) / (g + c);
            float B = (c * (g + c) - 1.0f) / (c * (g - c) + 1.0f);
            return 0.5f * A * A * (1.0f + B * B);
        }
        return 1.0f;
    }
    // Cycles bsdf_microfacet.h generalized_schlick_fresnel, exponent<0 branch:
    // reparameterize the real dielectric curve onto [f0, f90]. Returns the
    // achromatic interpolation scalar s (F = mix(f0, f90, s)).
    static float generalizedSchlickS(float cosThetaI, float ior) {
        float Fr = fresnelDielectricCos(cosThetaI, ior);
        float F0r = F0_from_ior(ior);
        float denom = 1.0f - F0r;
        if (denom < 1e-6f) return 0.0f;
        return std::clamp((Fr - F0r) / denom, 0.0f, 1.0f);
    }
    // Cycles bsdf_util.h fresnel_f82tint_B / fresnel_f82, per channel.
    static float f82BChannel(float f0, float tint) {
        const float f = 6.0f / 7.0f;
        const float f5 = (f * f) * (f * f) * f;  // f^5
        float Fs = f0 + (1.0f - f0) * f5;        // mix(F0, 1, f5)
        return Fs * (7.0f / (f5 * f)) * (1.0f - tint);
    }
    static float f82Channel(float cosi, float f0, float tint) {
        float B = f82BChannel(f0, tint);
        float s = std::clamp(1.0f - cosi, 0.0f, 1.0f);
        float s5 = (s * s) * (s * s) * s;        // s^5
        float Fs = f0 + (1.0f - f0) * s5;        // mix(F0, 1, s5)
        return std::clamp(Fs - B * cosi * s5 * s, 0.0f, 1.0f);
    }
    // PBRT-v4 unpolarized dielectric Fresnel (disney.cpp) — used for the
    // transmission lobe reflect/refract split.
    static float fresnelDielectric(float cosThetaI, float etaI, float etaT) {
        cosThetaI = std::clamp(cosThetaI, -1.0f, 1.0f);
        if (cosThetaI <= 0.0f) { std::swap(etaI, etaT); cosThetaI = std::abs(cosThetaI); }
        float sinI = std::sqrt(std::max(0.0f, 1.0f - cosThetaI * cosThetaI));
        float sinT = etaI / etaT * sinI;
        if (sinT >= 1.0f) return 1.0f;
        float cosT = std::sqrt(std::max(0.0f, 1.0f - sinT * sinT));
        float rp = (etaT * cosThetaI - etaI * cosT) / (etaT * cosThetaI + etaI * cosT + 1e-6f);
        float rs = (etaI * cosThetaI - etaT * cosT) / (etaI * cosThetaI + etaT * cosT + 1e-6f);
        return std::clamp(0.5f * (rp * rp + rs * rs), 0.0f, 1.0f);
    }

    // Multiscatter GGX energy compensation (Kulla & Conty 2017 / Cycles
    // microfacet_ggx_preserve_energy) — reuses the shipped in-repo table +
    // astroray::ggxDarkeningChannel (do not fork; disney.cpp/metal.cpp lineage).
    Vec3 ggxCompFactor(const Vec3& Fss, float roughness, float mu) const {
        const auto& t = astroray::DisneyEnergyCompensationTables::instance();
        if (!t.loaded()) return Vec3(1.0f);
        float E = std::max(t.ggxE(roughness, mu), 1e-4f);
        float Eavg = std::clamp(t.ggxEavg(roughness), 0.0f, 0.999f);
        return Vec3(astroray::ggxDarkeningChannel(Fss.x, E, Eavg),
                    astroray::ggxDarkeningChannel(Fss.y, E, Eavg),
                    astroray::ggxDarkeningChannel(Fss.z, E, Eavg));
    }
    // Compensated GGX directional-hemispherical albedo at wo (disney.cpp pkg145),
    // used by closure_layering_weight to attenuate the layer below the specular.
    Vec3 ggxDirectionalAlbedo(const Vec3& Fview, float roughness, float mu) const {
        const auto& t = astroray::DisneyEnergyCompensationTables::instance();
        if (!t.loaded()) return Fview;
        float E = std::max(t.ggxE(roughness, mu), 1e-4f);
        float Eavg = std::clamp(t.ggxEavg(roughness), 0.0f, 0.999f);
        auto ch = [&](float f) {
            float fc = std::clamp(f, 0.0f, 0.999f);
            return E * fc * astroray::ggxDarkeningChannel(fc, E, Eavg);
        };
        return Vec3(ch(Fview.x), ch(Fview.y), ch(Fview.z));
    }
    float ggxGlassComp(float etap, float muAbs) const {
        const auto& t = astroray::DisneyEnergyCompensationTables::instance();
        if (!t.loaded()) return 1.0f;
        float E = std::max(t.ggxGlassE(roughness_, muAbs, etap), 1e-4f);
        float Eavg = std::clamp(t.ggxGlassEavg(roughness_, etap), 0.0f, 0.999f);
        float Fss = std::clamp(etap >= 1.0f
                                   ? (etap - 1.0f) / (4.08567f + 1.00071f * etap)
                                   : 0.997118f + etap * (0.1014f - etap * (0.965241f + etap * 0.130607f)),
                               0.0f, 0.999f);
        return astroray::ggxDarkeningChannel(Fss, E, Eavg);
    }

    // Cycles bsdf_util.h closure_layering_weight: attenuate the running weight
    // by the just-placed layer's directional albedo.
    static Vec3 layeringWeightAfter(const Vec3& weight, const Vec3& albedo) {
        // saturate(1 - max(albedo/weight)) per channel-safe form: use the
        // simpler (1 - albedo) elementwise form disney.cpp uses (equivalent for
        // weight≈1 and numerically robust — Kulla-Conty layering).
        return weight * (Vec3(1.0f) - Vec3::min(albedo, Vec3(0.999f)));
    }

    // ------------------------------------------------------------------
    // VNDF sampling (Heitz 2018 / pbrt-v4, disney.cpp) — transmission lobe.
    // ------------------------------------------------------------------
    Vec3 sampleGgxVNDF(const HitRecord& rec, const Vec3& wo, float roughness,
                       std::mt19937& gen) const {
        std::uniform_real_distribution<float> dist(0.0f, 1.0f);
        float alpha = std::max(roughness * roughness, 0.0064f);
        float u1 = dist(gen), u2 = dist(gen);
        Vec3 wo_l(wo.dot(rec.tangent), wo.dot(rec.bitangent), wo.dot(rec.normal));
        Vec3 wh = Vec3(alpha * wo_l.x, alpha * wo_l.y, wo_l.z).normalized();
        if (wh.z < 0.0f) wh = -wh;
        Vec3 T1 = (wh.z < 0.99999f) ? Vec3(0, 0, 1).cross(wh).normalized() : Vec3(1, 0, 0);
        Vec3 T2 = wh.cross(T1);
        float r = std::sqrt(u1);
        float phi = 2.0f * float(M_PI) * u2;
        float px = r * std::cos(phi);
        float py = r * std::sin(phi);
        float h = std::sqrt(std::max(0.0f, 1.0f - px * px));
        float t = (1.0f + wh.z) / 2.0f;
        py = (1.0f - t) * h + t * py;
        float pz = std::sqrt(std::max(0.0f, 1.0f - px * px - py * py));
        Vec3 nh = T1 * px + T2 * py + wh * pz;
        Vec3 m_l = Vec3(alpha * nh.x, alpha * nh.y, std::max(1e-6f, nh.z)).normalized();
        Vec3 m = rec.tangent * m_l.x + rec.bitangent * m_l.y + rec.normal * m_l.z;
        return m.normalized();
    }
    float vndfPdf(const Vec3& N, const Vec3& wo, const Vec3& wm, float roughness) const {
        float absCosO = std::abs(wo.dot(N));
        if (absCosO <= 1e-10f) return 0.0f;
        float HdotO = std::abs(wo.dot(wm));
        float NdotH = std::abs(wm.dot(N));
        if (HdotO <= 1e-10f || NdotH <= 1e-10f) return 0.0f;
        float alpha = std::max(roughness * roughness, 0.0064f);
        float D = D_GTR2(NdotH, alpha);
        float G1 = smithG1_GGX(absCosO, alpha);
        return G1 / absCosO * D * HdotO;
    }
    bool refractMicro(const Vec3& wo, const Vec3& m, float eta, Vec3& wi) const {
        float c = std::clamp(wo.dot(m), -1.0f, 1.0f);
        if (c <= 0.0f) return false;
        Vec3 perp = (wo - m * c) * (-eta);
        float par2 = 1.0f - perp.length2();
        if (par2 <= 0.0f) return false;
        wi = (perp + m * (-std::sqrt(par2))).normalized();
        return wi.length2() > 1e-10f;
    }

    static Vec3 sqrtColor(const Vec3& c) {
        return Vec3(std::sqrt(std::max(0.0f, c.x)),
                    std::sqrt(std::max(0.0f, c.y)),
                    std::sqrt(std::max(0.0f, c.z)));
    }
    static astroray::SampledSpectrum upsample(const Vec3& c,
                                              const astroray::SampledWavelengths& l) {
        return astroray::RGBAlbedoSpectrum(
                   {std::clamp(c.x, 0.0f, 1.0f), std::clamp(c.y, 0.0f, 1.0f),
                    std::clamp(c.z, 0.0f, 1.0f)})
            .sample(l);
    }

    // ------------------------------------------------------------------
    // Closure-stack assembly (Cycles order; view-dependent layering).
    // Called by eval/pdf/sample so all three see identical weights (matched
    // normalization — the pkg170 lesson).
    // ------------------------------------------------------------------
    std::vector<Lobe> assembleLobes(const HitRecord& rec, const Vec3& wo) const {
        std::vector<Lobe> lobes;
        float nv = std::clamp(rec.normal.dot(wo), 1e-4f, 1.0f);
        Vec3 weight(1.0f, 1.0f, 1.0f);  // running weight (alpha handled at Stage 5)

        // 4. Metallic (GGX + F82-tint). closure weight = metallic·weight.
        if (metallic_ > 1e-4f) {
            Lobe L;
            L.kind = LobeKind::Metallic;
            L.weight = weight * metallic_;
            L.color = baseColor_;
            L.roughness = roughness_;
            L.ior = ior_;
            L.sel = std::max(luminance(L.weight * baseColor_), 1e-4f);
            lobes.push_back(L);
            weight = weight * (1.0f - metallic_);
        }
        // 5. Transmission (rough glass; thin_wall → Stage 4).
        if (transmission_ > 1e-4f && luminance(weight) > 1e-4f) {
            Lobe L;
            L.kind = LobeKind::Transmission;
            L.weight = weight * transmission_;
            L.color = baseColor_;
            L.roughness = roughness_;
            L.ior = ior_;
            L.isDelta = roughness_ <= kDeltaGlassRoughness;
            L.sel = std::max(luminance(L.weight), 1e-4f);
            lobes.push_back(L);
            weight = weight * (1.0f - transmission_);
        }
        // 6. Specular dielectric (generalized-Schlick, exponent = -ior).
        if (luminance(weight) > 1e-4f) {
            float f0s = F0_from_ior(ior_) * 2.0f * specularIorLevel_;
            Vec3 specF0 = Vec3(f0s) * specularTint_;  // fresnel->f0 = f0 * specular_tint
            float sView = generalizedSchlickS(nv, ior_);
            Vec3 Fview = specF0 + (Vec3(1.0f) - specF0) * sView;  // mix(f0, f90=1, s)
            Lobe L;
            L.kind = LobeKind::Specular;
            L.weight = weight;
            L.color = specF0;
            L.roughness = roughness_;
            L.ior = ior_;
            L.sel = std::max(luminance(weight * Fview), 1e-4f);
            lobes.push_back(L);
            weight = layeringWeightAfter(weight, ggxDirectionalAlbedo(Fview, roughness_, nv));
        }
        // 8. Diffuse (Lambert / EON). closure weight = base_color·weight.
        if (luminance(weight) > 1e-4f) {
            Lobe L;
            L.kind = LobeKind::Diffuse;
            L.weight = weight * baseColor_;
            L.color = baseColor_;
            L.roughness = diffuseRoughness_;
            L.sel = std::max(luminance(L.weight), 1e-4f);
            lobes.push_back(L);
        }
        if (lobes.empty()) {  // degenerate guard (e.g. metallic=1 pathological)
            Lobe L;
            L.kind = LobeKind::Diffuse;
            L.weight = baseColor_;
            L.color = baseColor_;
            L.sel = std::max(luminance(baseColor_), 1e-4f);
            lobes.push_back(L);
        }
        return lobes;
    }

    // ------------------------------------------------------------------
    // EON diffuse (Fujii improved Oren-Nayar + OpenPBR multiscatter),
    // Cycles bsdf_oren_nayar.h. Returns the per-channel BSDF·cos for one
    // albedo channel value `c`. `sigma` = diffuse_roughness.
    // ------------------------------------------------------------------
    static float orenNayarG(float cosTheta) {
        if (cosTheta < 1e-6f) return (float(M_PI) * 0.5f - 2.0f / 3.0f) - cosTheta;
        float sinT = std::sqrt(std::max(0.0f, 1.0f - cosTheta * cosTheta));
        float theta = std::acos(std::clamp(cosTheta, -1.0f, 1.0f));
        return sinT * (theta - 2.0f / 3.0f - sinT * cosTheta) +
               2.0f / 3.0f * (sinT / cosTheta) * (1.0f - sinT * sinT * sinT);
    }
    // Returns the achromatic single-scatter term and (via out) the per-channel
    // multiscatter coefficients so eval can apply per-λ albedo.
    struct EON { float a, b, Ev, El, Eavg, single, nl; };
    EON eonSetup(float sigma, float nl, float nv, float LdotV) const {
        EON e{};
        e.nl = nl;
        e.a = 1.0f / (float(M_PI) + sigma * (float(M_PI) * 0.5f - 2.0f / 3.0f));
        e.b = sigma * e.a;
        float s = LdotV - nl * nv;
        float t = s > 0.0f ? s / std::max(nl, nv) : s;
        e.single = e.a + e.b * t;
        e.Eavg = e.a * float(M_PI) + ((2.0f * float(M_PI) - 5.6f) / 3.0f) * e.b;
        e.El = e.a * float(M_PI) + e.b * orenNayarG(nl);
        e.Ev = e.a * float(M_PI) + e.b * orenNayarG(nv);
        return e;
    }
    float eonChannel(const EON& e, float c) const {
        float Eavg = std::clamp(e.Eavg, 0.0f, 0.999f);
        float denom = std::max(1.0f - c * (1.0f - Eavg), 1e-4f);
        float Ems = (1.0f / float(M_PI)) * c * c * (Eavg / std::max(1.0f - Eavg, 1e-4f)) / denom;
        float multi = Ems * (1.0f - e.Ev) * (1.0f - e.El);
        return e.nl * (e.single + multi);
    }

    // ==================================================================
    // Per-lobe evaluators (the four contract methods).
    // ==================================================================
    Vec3 evalLobeRGB(const Lobe& L, const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
        switch (L.kind) {
            case LobeKind::Diffuse: {
                if (nl <= 0.0f || nv <= 0.0f) return Vec3(0);
                if (L.roughness <= 1e-4f) return L.weight * (nl / float(M_PI));  // Lambert
                EON e = eonSetup(std::clamp(L.roughness, 0.0f, 1.0f), nl, nv, wi.dot(wo));
                return Vec3(L.weight.x * eonChannel(e, L.color.x),
                            L.weight.y * eonChannel(e, L.color.y),
                            L.weight.z * eonChannel(e, L.color.z));
            }
            case LobeKind::Specular: {
                if (nl <= 0.0f || nv <= 0.0f) return Vec3(0);
                Vec3 h = (wo + wi).normalized();
                float sHalf = generalizedSchlickS(std::abs(wo.dot(h)), L.ior);
                Vec3 F = L.color + (Vec3(1.0f) - L.color) * sHalf;
                return L.weight * ggxReflectRGB(F, L.color, L.roughness, rec, wo, wi);
            }
            case LobeKind::Metallic: {
                if (nl <= 0.0f || nv <= 0.0f) return Vec3(0);
                Vec3 h = (wo + wi).normalized();
                float ci = std::clamp(wo.dot(h), 0.0f, 1.0f);
                Vec3 F(f82Channel(ci, L.color.x, specularTint_.x),
                       f82Channel(ci, L.color.y, specularTint_.y),
                       f82Channel(ci, L.color.z, specularTint_.z));
                return L.weight * ggxReflectRGB(F, L.color, L.roughness, rec, wo, wi);
            }
            case LobeKind::Transmission:
                return transmissionEvalRGB(L, rec, wo, wi);
        }
        return Vec3(0);
    }

    // GGX reflection BRDF·cos with multiscatter comp (metal.cpp form).
    Vec3 ggxReflectRGB(const Vec3& Fhalf, const Vec3& compFss, float roughness,
                       const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
        if (nl <= 0.0f || nv <= 0.0f) return Vec3(0);
        Vec3 h = (wo + wi).normalized();
        float NdotH = std::max(rec.normal.dot(h), 1e-4f);
        float a = std::max(roughness * roughness, 0.0064f), a2 = a * a;
        float denom = NdotH * NdotH * (a2 - 1.0f) + 1.0f;
        float D = a2 / (float(M_PI) * denom * denom + 1e-4f);
        float G = smithG_k(nl, nv, roughness);
        Vec3 single = Fhalf * (D * G / (4.0f * nv + 1e-4f));  // brdf·NdotL
        return single * ggxCompFactor(compFss, roughness, nv);
    }

    // Transmission rough glass (Walter 2007 / pbrt-v4, disney.cpp) — reflection
    // tinted by specular_tint (Stage-1 white default), transmission by
    // sqrt(base_color) (Cycles generalized_schlick transmission_tint).
    Vec3 transmissionEvalRGB(const Lobe& L, const HitRecord& rec, const Vec3& wo,
                             const Vec3& wi) const {
        if (L.isDelta) return Vec3(0);  // delta handled in sampling
        float cosO = rec.normal.dot(wo), cosI = rec.normal.dot(wi);
        bool entering = rec.frontFace;
        float etaI = entering ? 1.0f : L.ior, etaT = entering ? L.ior : 1.0f;
        float alpha = std::max(L.roughness * L.roughness, 0.0064f);
        if (cosO > 0.0f && cosI > 0.0f) {
            // reflection lobe (dielectric Fresnel, specular_tint)
            Vec3 wm = (wo + wi).normalized();
            if (wm.dot(rec.normal) < 0.0f) wm = -wm;
            float HdotO = wo.dot(wm);
            if (HdotO <= 1e-10f) return Vec3(0);
            float D = D_GTR2(wm.dot(rec.normal), alpha);
            float G = smithG1_GGX(cosO, alpha) * smithG1_GGX(cosI, alpha);
            float F = fresnelDielectric(HdotO, 1.0f, L.ior);
            float fr = D * G * F / (4.0f * cosO * cosI + 1e-8f) * cosI;  // brdf·cosI
            return L.weight * specularTint_ * fr;
        }
        if (cosO * cosI >= 0.0f) return Vec3(0);
        // transmission lobe
        float etap = entering ? L.ior : (1.0f / L.ior);
        Vec3 wm = (wi * etap + wo).normalized();
        if (wm.dot(rec.normal) < 0.0f) wm = -wm;
        if (wm.dot(wi) * cosI < 0.0f || wm.dot(wo) * cosO < 0.0f) return Vec3(0);
        float D = D_GTR2(std::abs(wm.dot(rec.normal)), alpha);
        float G = smithG1_GGX(std::abs(cosO), alpha) * smithG1_GGX(std::abs(cosI), alpha);
        float F = fresnelDielectric(std::abs(wo.dot(wm)), etaI, etaT);
        float den = wi.dot(wm) + wo.dot(wm) / etap;
        den = den * den * cosI * cosO;
        float ft = D * (1.0f - F) * G * std::abs(wi.dot(wm) * wo.dot(wm) / (den + 1e-10f));
        ft /= (etap * etap);
        float scale = ft * std::abs(cosI) * ggxGlassComp(etap, std::abs(cosO));
        Vec3 res = L.weight * sqrtColor(baseColor_) * scale;
        return Vec3::max(res, Vec3(0.0f));
    }

    float pdfLobe(const Lobe& L, const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
        switch (L.kind) {
            case LobeKind::Diffuse:
                return (nl > 0.0f && nv > 0.0f) ? nl / float(M_PI) : 0.0f;
            case LobeKind::Specular:
            case LobeKind::Metallic: {
                if (nl <= 0.0f || nv <= 0.0f) return 0.0f;
                Vec3 h = (wo + wi).normalized();
                float NdotH = rec.normal.dot(h), HdotV = h.dot(wo);
                if (NdotH <= 0.0f || HdotV <= 0.0f) return 0.0f;
                float a = std::max(L.roughness * L.roughness, 0.0064f);
                return D_GTR2(NdotH, a) * NdotH / (4.0f * HdotV);
            }
            case LobeKind::Transmission:
                return L.isDelta ? 0.0f : transmissionPdf(L, rec, wo, wi);
        }
        return 0.0f;
    }

    float transmissionPdf(const Lobe& L, const HitRecord& rec, const Vec3& wo,
                          const Vec3& wi) const {
        float cosO = rec.normal.dot(wo), cosI = rec.normal.dot(wi);
        bool entering = rec.frontFace;
        float etaI = entering ? 1.0f : L.ior, etaT = entering ? L.ior : 1.0f;
        float alpha = std::max(L.roughness * L.roughness, 0.0064f);
        if (cosO > 0.0f && cosI > 0.0f) {  // reflection
            Vec3 wm = (wo + wi).normalized();
            if (wm.dot(rec.normal) < 0.0f) wm = -wm;
            float HdotO = std::abs(wo.dot(wm));
            if (HdotO <= 1e-10f) return 0.0f;
            float F = fresnelDielectric(HdotO, etaI, etaT);
            return F * vndfPdf(rec.normal, wo, wm, L.roughness) / (4.0f * HdotO);
        }
        if (cosO * cosI >= 0.0f) return 0.0f;  // transmission
        float etap = entering ? L.ior : (1.0f / L.ior);
        Vec3 wm = (wi * etap + wo).normalized();
        if (wm.dot(rec.normal) < 0.0f) wm = -wm;
        float HdotO = wo.dot(wm), HdotI = wi.dot(wm);
        if (HdotO * HdotI >= 0.0f) return 0.0f;
        float d = HdotI + HdotO / etap;
        float d2 = d * d;
        if (d2 <= 1e-10f) return 0.0f;
        float F = fresnelDielectric(std::abs(HdotO), etaI, etaT);
        return (1.0f - F) * vndfPdf(rec.normal, wo, wm, L.roughness) * std::abs(HdotI) / d2;
    }

    // ==================================================================
    // Direction sampling (shared by sample / sampleSpectral).
    // ==================================================================
    struct DirSample {
        bool ok = false;
        Vec3 wi;
        bool isDelta = false;
        int lobe = -1;
        float pdfInternal = 1.0f;  // within-lobe selection prob for delta events
        bool deltaRefract = false;
        float eta = 1.0f;          // etaI/etaT for the delta refraction radiance factor
    };
    DirSample chooseAndSampleDir(const HitRecord& rec, const Vec3& wo,
                                 std::mt19937& gen, const std::vector<Lobe>& lobes,
                                 float W) const {
        std::uniform_real_distribution<float> dist(0.0f, 1.0f);
        DirSample ds;
        float xi = dist(gen) * W, acc = 0.0f;
        int j = int(lobes.size()) - 1;
        for (int i = 0; i < int(lobes.size()); ++i) {
            acc += lobes[i].sel;
            if (xi <= acc) { j = i; break; }
        }
        ds.lobe = j;
        const Lobe& L = lobes[j];
        if (L.kind == LobeKind::Diffuse) {
            Vec3 local = Vec3::randomCosineDirection(gen);
            ds.wi = rec.tangent * local.x + rec.bitangent * local.y + rec.normal * local.z;
            ds.ok = rec.normal.dot(ds.wi) > 0.0f;
            return ds;
        }
        if (L.kind == LobeKind::Specular || L.kind == LobeKind::Metallic) {
            float a = std::max(L.roughness * L.roughness, 0.0064f);
            float r1 = dist(gen), r2 = dist(gen);
            float phi = 2.0f * float(M_PI) * r1;
            float cosT = std::sqrt((1.0f - r2) / (1.0f + (a * a - 1.0f) * r2));
            float sinT = std::sqrt(std::max(0.0f, 1.0f - cosT * cosT));
            Vec3 h(std::cos(phi) * sinT, std::sin(phi) * sinT, cosT);
            h = rec.tangent * h.x + rec.bitangent * h.y + rec.normal * h.z;
            ds.wi = (h * (2.0f * wo.dot(h)) - wo).normalized();
            ds.ok = rec.normal.dot(ds.wi) > 0.0f;
            return ds;
        }
        // Transmission
        float etaI = rec.frontFace ? 1.0f : L.ior;
        float etaT = rec.frontFace ? L.ior : 1.0f;
        float eta = etaI / etaT;
        ds.eta = eta;
        Vec3 n = rec.normal;
        float cosTheta = wo.dot(n);
        if (cosTheta < 0.0f) { cosTheta = -cosTheta; n = -n; }
        float sinT = std::sqrt(std::max(0.0f, 1.0f - cosTheta * cosTheta));
        bool cannotRefract = eta * sinT > 1.0f;
        if (!L.isDelta) {
            Vec3 wm = sampleGgxVNDF(rec, wo, L.roughness, gen);
            float HdotO = wo.dot(wm);
            float F = fresnelDielectric(std::abs(HdotO), etaI, etaT);
            bool refl = cannotRefract || dist(gen) < F;
            if (refl) {
                ds.wi = (wm * (2.0f * HdotO) - wo).normalized();
                ds.ok = ds.wi.dot(rec.normal) * wo.dot(rec.normal) > 0.0f;
            } else {
                ds.ok = refractMicro(wo, wm, eta, ds.wi);
            }
            ds.isDelta = false;
            return ds;
        }
        // delta (smooth) glass
        float f0 = (etaI - etaT) / (etaI + etaT);
        f0 = f0 * f0;
        float fresnel = f0 + (1.0f - f0) * std::pow(std::clamp(1.0f - cosTheta, 0.0f, 1.0f), 5.0f);
        ds.isDelta = true;
        if (cannotRefract || dist(gen) < fresnel) {
            ds.wi = n * (2.0f * wo.dot(n)) - wo;
            ds.deltaRefract = false;
            ds.pdfInternal = cannotRefract ? 1.0f : fresnel;
        } else {
            Vec3 perp = (wo - n * cosTheta) * (-eta);
            Vec3 para = n * (-std::sqrt(std::abs(1.0f - perp.length2())));
            ds.wi = (perp + para).normalized();
            ds.deltaRefract = true;
            ds.pdfInternal = 1.0f - fresnel;
        }
        ds.ok = true;
        return ds;
    }

public:
    explicit PrincipledPlugin(const astroray::ParamDict& p)
        : baseColor_(p.getVec3("base_color", p.getVec3("albedo", Vec3(0.8f)))),
          metallic_(std::clamp(p.getFloat("metallic", 0.0f), 0.0f, 1.0f)),
          roughness_(std::clamp(p.getFloat("roughness", 0.5f), 0.001f, 1.0f)),
          ior_(std::max(1.0f, p.getFloat("ior", 1.5f))),
          alpha_(std::clamp(p.getFloat("alpha", 1.0f), 0.0f, 1.0f)),
          diffuseRoughness_(std::clamp(p.getFloat("diffuse_roughness", 0.0f), 0.0f, 1.0f)),
          specularIorLevel_(std::max(0.0f, p.getFloat("specular_ior_level", 0.5f))),
          specularTint_(p.getVec3("specular_tint", Vec3(1.0f))),
          transmission_(std::clamp(
              p.getFloat("transmission_weight", p.getFloat("transmission", 0.0f)), 0.0f, 1.0f)),
          thinWall_(p.getFloat("thin_wall", 0.0f) > 0.5f) {}

    Vec3 getAlbedo() const override { return baseColor_; }
    float getRoughness() const override { return roughness_; }
    float getMetallic() const override { return metallic_; }
    float getIOR() const override { return ior_; }
    float getTransmission() const override { return transmission_; }
    bool isTransmissive() const override { return transmission_ > 1e-4f; }
    bool isGlossy() const override { return true; }

    // pkg178 Stage 2 GPU seam (the ONLY additions to this Stage-1 file — no lobe
    // math changed): lower to GMAT_CLOSURE_GRAPH via a single monolithic
    // GCLOSURE_PRINCIPLED closure carrying the raw core-lobe params. The device
    // twin (gpu_principled_* in gpu_materials.h) re-runs assembleLobes on device
    // per shade, because the assembly is VIEW-DEPENDENT and cannot be baked into
    // static per-lobe closure weights.
    std::string getGPUTypeName() const override { return "principled"; }
    astroray::MaterialClosureGraph closureGraph() const override {
        astroray::MaterialClosureGraph graph;
        graph.add(astroray::makePrincipledClosure(
            astroray::ClosureColor{baseColor_.x, baseColor_.y, baseColor_.z},
            metallic_, roughness_, ior_, specularIorLevel_,
            astroray::ClosureColor{specularTint_.x, specularTint_.y, specularTint_.z},
            transmission_, diffuseRoughness_));
        return graph;
    }
    MaterialBackendCapabilities backendCapabilities() const override {
        MaterialBackendCapabilities caps;
        caps.cpu = true;
        caps.spectral = true;
        caps.gpu = true;           // pkg178 Stage 2: closure-graph lowering (below)
        caps.gpuSpectral = true;   // native per-λ device twin (gpu_principled_eval_spectral)
        caps.closureGraph = true;
        caps.gpuType = "closure_graph";
        caps.notes = "pkg178 Stage 2: native Principled core lobes (diffuse/specular/"
                     "metallic/transmission) via GMAT_CLOSURE_GRAPH + GCLOSURE_PRINCIPLED";
        return caps;
    }

    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        auto lobes = assembleLobes(rec, wo);
        Vec3 sum(0);
        for (const auto& L : lobes)
            if (!L.isDelta) sum += evalLobeRGB(L, rec, wo, wi);
        return Vec3::max(sum, Vec3(0.0f));
    }

    astroray::SampledSpectrum evalSpectral(const HitRecord& rec, const Vec3& wo,
                                           const Vec3& wi,
                                           const astroray::SampledWavelengths& lambdas) const override {
        auto lobes = assembleLobes(rec, wo);
        astroray::SampledSpectrum sum(0.0f);
        for (const auto& L : lobes)
            if (!L.isDelta) sum += evalLobeSpectral(L, rec, wo, wi, lambdas);
        return sum;
    }

    astroray::SampledSpectrum evalLobeSpectral(const Lobe& L, const HitRecord& rec,
                                               const Vec3& wo, const Vec3& wi,
                                               const astroray::SampledWavelengths& lam) const {
        float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
        astroray::SampledSpectrum wSpec = upsample(L.weight, lam);
        switch (L.kind) {
            case LobeKind::Diffuse: {
                if (nl <= 0.0f || nv <= 0.0f) return astroray::SampledSpectrum(0.0f);
                if (L.roughness <= 1e-4f) return wSpec * (nl / float(M_PI));  // Lambert
                EON e = eonSetup(std::clamp(L.roughness, 0.0f, 1.0f), nl, nv, wi.dot(wo));
                astroray::SampledSpectrum cSpec = upsample(L.color, lam);
                astroray::SampledSpectrum out(0.0f);
                for (int i = 0; i < astroray::kSpectrumSamples; ++i)
                    out[i] = wSpec[i] * eonChannel(e, cSpec[i]);
                return out;
            }
            case LobeKind::Specular: {
                if (nl <= 0.0f || nv <= 0.0f) return astroray::SampledSpectrum(0.0f);
                Vec3 h = (wo + wi).normalized();
                float sHalf = generalizedSchlickS(std::abs(wo.dot(h)), L.ior);
                astroray::SampledSpectrum f0 = upsample(L.color, lam);
                astroray::SampledSpectrum F = f0 + (astroray::SampledSpectrum(1.0f) - f0) * sHalf;
                return wSpec * ggxReflectSpectral(F, f0, L.roughness, rec, wo, wi);
            }
            case LobeKind::Metallic: {
                if (nl <= 0.0f || nv <= 0.0f) return astroray::SampledSpectrum(0.0f);
                Vec3 h = (wo + wi).normalized();
                float ci = std::clamp(wo.dot(h), 0.0f, 1.0f);
                astroray::SampledSpectrum f0 = upsample(L.color, lam);
                astroray::SampledSpectrum tint = upsample(specularTint_, lam);
                astroray::SampledSpectrum F(0.0f);
                for (int i = 0; i < astroray::kSpectrumSamples; ++i)
                    F[i] = f82Channel(ci, f0[i], tint[i]);
                return wSpec * ggxReflectSpectral(F, f0, L.roughness, rec, wo, wi);
            }
            case LobeKind::Transmission: {
                // Colour upsampled; achromatic geometry/Fresnel scalar per-λ (native).
                Vec3 rgb = transmissionEvalRGB(L, rec, wo, wi);
                if (rgb.x <= 0.0f && rgb.y <= 0.0f && rgb.z <= 0.0f)
                    return astroray::SampledSpectrum(0.0f);
                float maxc = std::max({rgb.x, rgb.y, rgb.z, 1.0f});
                Vec3 tint = rgb * (1.0f / maxc);
                return upsample(tint, lam) * maxc;
            }
        }
        return astroray::SampledSpectrum(0.0f);
    }

    astroray::SampledSpectrum ggxReflectSpectral(const astroray::SampledSpectrum& Fhalf,
                                                 const astroray::SampledSpectrum& compFss,
                                                 float roughness, const HitRecord& rec,
                                                 const Vec3& wo, const Vec3& wi) const {
        float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
        if (nl <= 0.0f || nv <= 0.0f) return astroray::SampledSpectrum(0.0f);
        Vec3 h = (wo + wi).normalized();
        float NdotH = std::max(rec.normal.dot(h), 1e-4f);
        float a = std::max(roughness * roughness, 0.0064f), a2 = a * a;
        float denom = NdotH * NdotH * (a2 - 1.0f) + 1.0f;
        float D = a2 / (float(M_PI) * denom * denom + 1e-4f);
        float G = smithG_k(nl, nv, roughness);
        astroray::SampledSpectrum single = Fhalf * (D * G / (4.0f * nv + 1e-4f));
        const auto& t = astroray::DisneyEnergyCompensationTables::instance();
        if (!t.loaded()) return single;
        float E = std::max(t.ggxE(roughness, nv), 1e-4f);
        float Eavg = std::clamp(t.ggxEavg(roughness), 0.0f, 0.999f);
        astroray::SampledSpectrum out = single;
        for (int i = 0; i < astroray::kSpectrumSamples; ++i)
            out[i] *= astroray::ggxDarkeningChannel(compFss[i], E, Eavg);
        return out;
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        auto lobes = assembleLobes(rec, wo);
        float W = 0.0f;
        for (const auto& L : lobes) W += L.sel;
        if (W <= 0.0f) return 0.0f;
        float p = 0.0f;
        for (const auto& L : lobes)
            if (!L.isDelta) p += (L.sel / W) * pdfLobe(L, rec, wo, wi);
        return p;
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        s.wi = rec.normal;
        s.f = Vec3(0);
        s.pdf = 0.0f;
        s.isDelta = false;
        auto lobes = assembleLobes(rec, wo);
        float W = 0.0f;
        for (const auto& L : lobes) W += L.sel;
        if (W <= 0.0f) return s;
        DirSample ds = chooseAndSampleDir(rec, wo, gen, lobes, W);
        if (!ds.ok) return s;
        s.wi = ds.wi;
        if (ds.isDelta) {
            const Lobe& L = lobes[ds.lobe];
            float qj = L.sel / W;
            if (ds.deltaRefract) {
                s.f = L.weight * sqrtColor(baseColor_) * (ds.eta * ds.eta * ds.pdfInternal);
            } else {
                s.f = L.weight * specularTint_ * ds.pdfInternal;
            }
            s.pdf = qj * ds.pdfInternal;
            s.isDelta = true;
            const_cast<HitRecord&>(rec).isDelta = true;
        } else {
            s.f = eval(rec, wo, s.wi);
            s.pdf = pdf(rec, wo, s.wi);
            s.isDelta = false;
        }
        return s;
    }

    BSDFSampleSpectral sampleSpectral(const HitRecord& rec, const Vec3& wo,
                                      std::mt19937& gen,
                                      astroray::SampledWavelengths& lambdas) const override {
        BSDFSampleSpectral bss;
        bss.wi = rec.normal;
        bss.f_spectral = astroray::SampledSpectrum(0.0f);
        bss.pdf = 0.0f;
        bss.isDelta = false;
        auto lobes = assembleLobes(rec, wo);
        float W = 0.0f;
        for (const auto& L : lobes) W += L.sel;
        if (W <= 0.0f) return bss;
        DirSample ds = chooseAndSampleDir(rec, wo, gen, lobes, W);
        if (!ds.ok) return bss;
        bss.wi = ds.wi;
        if (ds.isDelta) {
            const Lobe& L = lobes[ds.lobe];
            float qj = L.sel / W;
            // eta²-clamp guard (base-class pattern): upsample normalized tint × magnitude.
            Vec3 rgb = ds.deltaRefract
                           ? L.weight * sqrtColor(baseColor_) * (ds.eta * ds.eta * ds.pdfInternal)
                           : L.weight * specularTint_ * ds.pdfInternal;
            float maxc = std::max({rgb.x, rgb.y, rgb.z, 1.0f});
            bss.f_spectral = upsample(rgb * (1.0f / maxc), lambdas) * maxc;
            bss.pdf = qj * ds.pdfInternal;
            bss.isDelta = true;
            const_cast<HitRecord&>(rec).isDelta = true;
        } else {
            bss.f_spectral = evalSpectral(rec, wo, ds.wi, lambdas);
            bss.pdf = pdf(rec, wo, ds.wi);
            bss.isDelta = false;
        }
        return bss;
    }
};

ASTRORAY_REGISTER_MATERIAL("principled", PrincipledPlugin)

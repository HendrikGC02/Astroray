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
#include "astroray/sheen_ltc_table.h"
#include "astroray/thin_film_fresnel.h"    // pkg178 Stage 4 PR-1 (Belcour-Barla 2017)
#include "astroray/thin_film_cie_table.h"  // Rec.709-baked CIE sensitivity LUT
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
    bool thinWall_;  // parsed; Thin Wall is Stage 4 PR-4 (unused here — seam only)
    // pkg178 Stage 4 PR-1 — thin-film iridescence (Belcour-Barla 2017). Default
    // thickness 0 → film OFF (thickness ≤ 0.1nm cutoff): the dielectric
    // specular/transmission Fresnel takes the exact Stage-3b path, byte-identical.
    float thinFilmThickness_;  // Cycles thin_film_thickness (nm)
    float thinFilmIor_;        // Cycles thin_film_ior
    // pkg178 Stage-3b PR-4b — Cycles anisotropic + anisotropic_rotation sockets.
    // Default 0 → isotropic (alpha_x==alpha_y), Stage-1/2 behavior byte-for-byte.
    float anisotropic_, anisotropicRotation_;

    // pkg178 Stage 3 advanced-layer inputs (Cycles socket names). Default values
    // (all weights 0) reproduce the Stage-1 core-lobe stack byte-for-byte so the
    // merged furnace/chi²/parity gates do not regress.
    float coatWeight_, coatRoughness_, coatIor_;
    Vec3 coatTint_;
    float sheenWeight_, sheenRoughness_;
    Vec3 sheenTint_;
    float subsurfaceWeight_, subsurfaceScale_;
    Vec3 subsurfaceRadius_;
    Vec3 emissionColor_;
    float emissionStrength_;
    astroray::RGBIlluminantSpectrum emissionSpec_;

    // Smooth glass below this roughness is treated as a delta transmission event
    // (matches disney.cpp::kDeltaTransmissionRoughness).
    static constexpr float kDeltaGlassRoughness = 0.03f;

    // ======================================================================
    // Lobe-interface contract (the seam parallel lobe agents code against).
    // A new lobe = enum value + arm in the four evaluators + row in
    // assembleLobes(); the MIS recombination (eval/pdf/sample) is invariant.
    // ======================================================================
    // pkg178 Stage 3 adds Coat / Sheen / Subsurface to the Stage-1 core kinds.
    // pkg178 Stage-3b PR-6 adds Transparent (the alpha delta lobe, assembled first).
    enum class LobeKind { Diffuse, Specular, Metallic, Transmission, Coat, Sheen, Subsurface, Transparent };
    struct Lobe {
        LobeKind kind;
        Vec3 weight{1, 1, 1};  // spectral layering weight (RGB; upsampled per-λ)
        Vec3 color{1, 1, 1};   // reflectance colour (base_color / specular f0 / base_color)
        float roughness = 0.0f;
        float ior = 1.5f;
        float sel = 0.0f;      // scalar selection weight; Σ sel = W
        bool isDelta = false;  // smooth glass → excluded from continuous eval/pdf sums
        float sheenA = 0.0f;   // Sheen: LTC aInv (view-dependent, fetched at assembly)
        float sheenB = 0.0f;   // Sheen: LTC bInv
        // pkg178 PR-4b: anisotropy (specular/metallic only; 0 → isotropic).
        float anisotropic = 0.0f;
        float anisoRotation = 0.0f;
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
    // Height-correlated Smith masking-shadowing (pkg178 Stage-3b PR-4a). Replaces
    // the former Disney/UE4 Schlick-k approximation with the EXACT form Cycles
    // uses for BOTH reflection and transmission — Heitz 2014 "Understanding the
    // Masking-Shadowing Function in Microfacet-Based BRDFs" (JCGT Vol.3 No.2,
    // §3.2, Eq. 72) — mirrored from Cycles
    // intern/cycles/kernel/closure/bsdf_microfacet.h (BSD-3-Clause):
    // bsdf_lambda_from_sqr_alpha_tan_n / bsdf_lambda / bsdf_microfacet_eval.
    // ISOTROPIC only (αx=αy → α=roughness²); anisotropy is the PR-4b follow-up.
    // λ(θ) = ½(√(1 + α²·tan²θ) − 1); alpha arg = α (Cycles alpha2 = αx·αy).
    static float smithLambda(float cosTheta, float alpha) {
        float a2 = alpha * alpha;  // sqr_alpha (Cycles alpha2)
        float c2 = std::max(cosTheta * cosTheta, 1e-7f);
        float t = a2 * std::max(1.0f / c2 - 1.0f, 0.0f);  // sqr_alpha · tan²θ
        return 0.5f * (std::sqrt(1.0f + t) - 1.0f);
    }
    // Height-correlated Smith G2 = 1 / (1 + λO + λI) (Cycles bsdf_microfacet_eval).
    static float smithG2_GGX(float NdotL, float NdotV, float alpha) {
        return 1.0f / (1.0f + smithLambda(NdotV, alpha) + smithLambda(NdotL, alpha));
    }

    // ---- pkg178 Stage-3b PR-4b — anisotropic GGX (specular + metallic only) ----
    // Cited from Cycles intern/cycles/kernel/closure/bsdf_microfacet.h and
    // svm/closure.h (Apache-2.0 / BSD-3-Clause); see
    // .astroray_plan/docs/anisotropic-ggx-research.md. Every helper below reduces
    // EXACTLY to the PR-4a isotropic value at anisotropic==0 (aspect==1 →
    // alpha_x==alpha_y==a), so isotropic scenes never enter the aniso branch and
    // are bit-identical. Transmission stays isotropic (alpha2 = alpha_x*alpha_y =
    // roughness^4 → alpha = roughness^2, unchanged) and is untouched here.

    // svm/closure.h: aspect = sqrt(1 - anisotropic*0.9); alpha_x = a/aspect,
    // alpha_y = a*aspect, with a = max(roughness^2, floor) (the PR-4a iso floor).
    static void anisoAlphas(float roughness, float anisotropic, float& ax, float& ay) {
        float a = std::max(roughness * roughness, 0.0064f);
        float aspect = std::sqrt(std::max(1.0f - anisotropic * 0.9f, 1e-4f));
        ax = std::max(a / aspect, 0.0064f);
        ay = std::max(a * aspect, 0.0064f);
    }
    // Rodrigues rotation of a unit tangent T (assumed perpendicular to unit N)
    // around N by `angle` — Cycles rotate_around_axis specialized to T⊥N.
    static Vec3 rotateAroundAxis(const Vec3& T, const Vec3& N, float angle) {
        return T * std::cos(angle) + N.cross(T) * std::sin(angle);
    }
    // Build the anisotropy shading frame from the UV-aligned tangent (PR-3),
    // rotated by anisotropic_rotation*2π. Cycles make_orthonormals_tangent(N,T):
    // Y = normalize(N×T), X = Y×N. Falls back to the arbitrary frame if degenerate.
    static void anisoFrame(const HitRecord& rec, float anisoRotation, Vec3& X, Vec3& Y) {
        Vec3 T = rec.uvTangent;
        if (anisoRotation != 0.0f)
            T = rotateAroundAxis(T, rec.normal, anisoRotation * 2.0f * float(M_PI));
        Vec3 b = rec.normal.cross(T);
        float bl2 = b.length2();
        if (bl2 < 1e-12f) { X = rec.tangent; Y = rec.bitangent; return; }
        Y = b * (1.0f / std::sqrt(bl2));
        X = Y.cross(rec.normal);
    }
    // bsdf_aniso_lambda: H/V in the (X,Y,N) local frame (z = cosθ).
    static float smithLambdaAniso(const Vec3& Vloc, float ax, float ay) {
        float vz2 = std::max(Vloc.z * Vloc.z, 1e-7f);
        float t = ((ax * Vloc.x) * (ax * Vloc.x) + (ay * Vloc.y) * (ay * Vloc.y)) / vz2;
        return 0.5f * (std::sqrt(1.0f + t) - 1.0f);
    }
    static float smithG2Aniso(const Vec3& Iloc, const Vec3& Oloc, float ax, float ay) {
        return 1.0f / (1.0f + smithLambdaAniso(Oloc, ax, ay) + smithLambdaAniso(Iloc, ax, ay));
    }
    // bsdf_aniso_D: Hloc = microfacet normal in (X,Y,N); z = NdotH.
    // Written as alpha2/(π·(alpha2·len2)² + reg) so that at ax==ay==a it is
    // ALGEBRAICALLY a²/(π·denom² + reg), denom = 1+(a²-1)NdotH² — i.e. it reduces
    // exactly to the isotropic forms. `reg` selects which iso form: 1e-4 matches
    // the eval-side inline D (ggxReflectRGB), ~0 matches the pdf-side D_GTR2.
    static float ggxAnisoD(const Vec3& Hloc, float ax, float ay, float reg) {
        float hx = Hloc.x / ax, hy = Hloc.y / ay, hz = Hloc.z;
        float len2 = hx * hx + hy * hy + hz * hz;
        float alpha2 = ax * ay;
        float denomA = alpha2 * len2;
        return alpha2 / (float(M_PI) * denomA * denomA + reg);
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

    // ==================================================================
    // pkg178 Stage 4 PR-1 — thin-film iridescence Fresnel (Belcour-Barla 2017).
    // Shared core in include/astroray/thin_film_fresnel.h; here are the
    // per-material call wrappers. Film active ⇔ thickness > 0.1nm cutoff; when
    // inactive these are NEVER called (the callers take the exact Stage-3b path),
    // so thickness=0 renders are byte-identical to pre-change.
    // ==================================================================
    bool filmActive() const {
        return thinFilmThickness_ > astroray::thinfilm::kThinFilmThicknessCutoff;
    }
    // Per-RGB-channel dielectric iridescence F at incident cosine `cosI`, over a
    // dielectric substrate of relative IOR `iorArg` (= Cycles bsdf->ior) with the
    // film IOR `filmIor` (backface-adjusted by the caller). RGB sensitivity via
    // the Rec.709-baked CIE LUT — Cycles bsdf_util.h fresnel_iridescence_channel<false>.
    Vec3 thinFilmFresnelRGB(float cosI, float iorArg, float filmIor) const {
        namespace tf = astroray::thinfilm;
        Vec3 out;
        for (int c = 0; c < 3; ++c) {
            auto S = [c](float argOPD) {
                return tf::sensitivityRGB(argOPD, c, tf::kThinFilmCieTable);
            };
            float v = tf::fresnelIridescenceChannel<false>(
                1.0f, thinFilmThickness_, filmIor, iorArg, 0.0f, -1.0f, cosI, nullptr, S);
            (&out.x)[c] = v;
        }
        return out;
    }
    // Per-λ dielectric iridescence F — analytic sensitivity (no LUT), pkg163
    // per-λ discipline. Cycles bsdf_util.h fresnel_iridescence_channel<false>.
    astroray::SampledSpectrum thinFilmFresnelSpectral(
            float cosI, float iorArg, float filmIor,
            const astroray::SampledWavelengths& lam) const {
        namespace tf = astroray::thinfilm;
        astroray::SampledSpectrum out(0.0f);
        for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
            float lambda = lam.lambda(i);
            auto S = [lambda](float argOPD) { return tf::sensitivitySpectral(argOPD, lambda); };
            out[i] = tf::fresnelIridescenceChannel<false>(
                1.0f, thinFilmThickness_, filmIor, iorArg, 0.0f, -1.0f, cosI, nullptr, S);
        }
        return out;
    }
    // Cycles generalized_schlick_fresnel thin-film F0-rescale (bsdf_microfacet.h
    // :284-297): scale the (possibly colored, possibly <F0) iridescence F toward
    // the artist f0, with strength depending on how close F is to F0_real.
    // With the common defaults (specular_tint=1, specular_ior_level=0.5) this is
    // a no-op (f0/F0_real == 1). `iorArg` = Cycles bsdf->ior.
    static float thinFilmF0RescaleChannel(float Fc, float f0c, float F0real) {
        // s = saturate(inverse_lerp(1, F0real, Fc)); Fc *= mix(1, f0c/F0real, s).
        float s = std::clamp((Fc - 1.0f) / (F0real - 1.0f), 0.0f, 1.0f);
        float factor = f0c / F0real;
        return Fc * (1.0f + (factor - 1.0f) * s);
    }
    static Vec3 thinFilmF0RescaleRGB(Vec3 F, const Vec3& f0, float iorArg) {
        float F0real = F0_from_ior(iorArg);
        if (F0real <= 1e-5f || (F.x == 1.0f && F.y == 1.0f && F.z == 1.0f)) return F;
        return Vec3(thinFilmF0RescaleChannel(F.x, f0.x, F0real),
                    thinFilmF0RescaleChannel(F.y, f0.y, F0real),
                    thinFilmF0RescaleChannel(F.z, f0.z, F0real));
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

    // ==================================================================
    // pkg178 Stage 3 — Coat / Sheen helpers (Cycles ports).
    // ==================================================================
    // Coat (Cycles svm/closure.h Principled coat layer): a clear GGX dielectric
    // reflection using coat_ior, plus Beer absorption of the layers below by
    // coat_tint^(1/cosθ_refracted) and the layer's own directional-albedo
    // attenuation. Beer factor per Cycles closure.h:
    //   cosNT = sqrt(1 - (1/coat_ior)²·(1-cosNI²)); optical_depth = 1/cosNT;
    //   weight *= mix(1, coat_tint^optical_depth, coat_weight).
    // coat_normal_offset is a per-hit shading-normal input the addon does not yet
    // plumb through ParamDict (Stage 5); here the coat uses the shading normal
    // (offset 0), so cosNI = dot(N, wo). SEAM: wire coat_normal_offset when the
    // addon exposes it.
    Vec3 coatBeerFactor(float nv) const {
        if (coatWeight_ <= 1e-4f) return Vec3(1.0f);
        if (coatTint_.x >= 0.999f && coatTint_.y >= 0.999f && coatTint_.z >= 0.999f)
            return Vec3(1.0f);
        float cosNI = std::clamp(nv, 1e-3f, 1.0f);
        float inv = 1.0f / coatIor_;
        float cosNT = std::sqrt(std::max(1e-4f, 1.0f - inv * inv * (1.0f - cosNI * cosNI)));
        float opticalDepth = 1.0f / cosNT;
        auto pw = [&](float t) { return std::pow(std::clamp(t, 0.0f, 1.0f), opticalDepth); };
        Vec3 tintPow(pw(coatTint_.x), pw(coatTint_.y), pw(coatTint_.z));
        // mix(1, tintPow, coat_weight)
        return Vec3(1.0f) * (1.0f - coatWeight_) + tintPow * coatWeight_;
    }

    // Sheen microfiber LTC (Zeltner/Burley/Chiang 2022; Cycles bsdf_sheen.h).
    // View-dependent frame: make_orthonormals_safe_tangent(N, wo) (wo = Cycles
    // sd->wi, the view/incoming direction).
    void sheenFrame(const Vec3& N, const Vec3& wo, Vec3& T, Vec3& B) const {
        Vec3 t = wo - N * N.dot(wo);
        if (t.length2() > 1e-8f) {
            T = t.normalized();
        } else {  // wo ‖ N — pick an arbitrary tangent
            T = (std::abs(N.x) < 0.99f) ? Vec3(1, 0, 0).cross(N).normalized()
                                        : Vec3(0, 1, 0).cross(N).normalized();
        }
        B = N.cross(T);
    }
    // Cycles bsdf_sheen_eval: val = 1/π · max(localO.z,0) · (a / lenSqr)².
    // localO = to_local(wi) in the (T,B,N) sheen frame. Returns BSDF·cos (Cycles
    // bsdf eval convention — see disney.cpp sheen note), matching the other lobes.
    static float sheenValue(float a, float b, const Vec3& localO) {
        float lenSqr = (a * localO.x + b * localO.z) * (a * localO.x + b * localO.z) +
                       (a * localO.y) * (a * localO.y) + localO.z * localO.z;
        float lo = std::max(localO.z, 0.0f);
        float t = a / std::max(lenSqr, 1e-12f);
        return (1.0f / float(M_PI)) * lo * t * t;
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
        Vec3 weight(1.0f, 1.0f, 1.0f);  // running weight (W₀ = 1)

        // 1. Transparent (alpha). Cycles svm/closure.h CLOSURE_BSDF_PRINCIPLED_ID
        //    does transparency FIRST, before every other closure:
        //      bsdf_transparent_setup(sd, weight*(1-alpha)); weight *= alpha;
        //    A GPR/Transparent delta lobe (Cycles bsdf_transparent.h: wo=-wi,
        //    matched pdf==eval so f/pdf==weight, zero eval/pdf outside sampling)
        //    is assembled with weight (1-alpha)·W₀; the remaining lobes then run on
        //    the alpha-scaled weight. At alpha==1 NO lobe is assembled and this whole
        //    block is skipped → the stack is byte-identical to PR-4b (the delta-glass
        //    safety property: existing alpha==1 gates are untouched by construction).
        if (alpha_ < 1.0f) {
            Lobe L;
            L.kind = LobeKind::Transparent;
            L.weight = weight * (1.0f - alpha_);  // (1-alpha)·W₀
            L.color = Vec3(1.0f);
            L.isDelta = true;  // excluded from continuous eval/pdf sums (zero NEE)
            L.sel = std::max(luminance(L.weight), 1e-4f);
            lobes.push_back(L);
            weight = weight * alpha_;
        }
        // 2. Sheen (LTC microfiber). Cycles order: sheen sits ABOVE coat. closure
        //    weight = sheen_weight·sheen_tint·weight·ltc_albedo; then the running
        //    weight is attenuated by the sheen directional albedo.
        if (sheenWeight_ > 1e-4f) {
            astroray::SheenLtcCoeffs sc =
                astroray::sheenLtcFetch(std::clamp(sheenRoughness_, 1e-3f, 1.0f), nv);
            if (std::abs(sc.aInv) >= 1e-5f && sc.albedo >= 1e-5f) {  // Cycles setup skip guard
                Vec3 sheenW = weight * sheenTint_ * (sheenWeight_ * sc.albedo);
                Lobe L;
                L.kind = LobeKind::Sheen;
                L.weight = sheenW;
                L.color = sheenTint_;
                L.sheenA = sc.aInv;
                L.sheenB = sc.bInv;
                L.sel = std::max(luminance(sheenW), 1e-4f);
                lobes.push_back(L);
                weight = layeringWeightAfter(weight, sheenTint_ * (sheenWeight_ * sc.albedo));
            }
        }
        // 3. Coat (clear GGX dielectric, coat_ior). Beer absorption + directional-
        //    albedo layering attenuate everything below.
        if (coatWeight_ > 1e-4f) {
            float f0c = F0_from_ior(coatIor_);
            float sView = generalizedSchlickS(nv, coatIor_);
            float Fview = f0c + (1.0f - f0c) * sView;
            Lobe L;
            L.kind = LobeKind::Coat;
            L.weight = weight * coatWeight_;
            L.color = Vec3(f0c);
            L.roughness = coatRoughness_;
            L.ior = coatIor_;
            L.sel = std::max(luminance(weight * coatWeight_) * Fview, 1e-4f);
            lobes.push_back(L);
            weight = layeringWeightAfter(
                weight, ggxDirectionalAlbedo(Vec3(Fview), coatRoughness_, nv) * coatWeight_);
            weight = weight * coatBeerFactor(nv);
        }
        // 4. Metallic (GGX + F82-tint). closure weight = metallic·weight.
        if (metallic_ > 1e-4f) {
            Lobe L;
            L.kind = LobeKind::Metallic;
            L.weight = weight * metallic_;
            L.color = baseColor_;
            L.roughness = roughness_;
            L.ior = ior_;
            L.anisotropic = anisotropic_;          // pkg178 PR-4b
            L.anisoRotation = anisotropicRotation_;
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
            L.anisotropic = anisotropic_;          // pkg178 PR-4b
            L.anisoRotation = anisotropicRotation_;
            L.sel = std::max(luminance(weight * Fview), 1e-4f);
            lobes.push_back(L);
            weight = layeringWeightAfter(weight, ggxDirectionalAlbedo(Fview, roughness_, nv));
        }
        // 7. Subsurface — APPROXIMATE (owner decision D2 = option (a)). Cycles uses
        //    a random-walk Bssrdf; here we reuse the diffusion-style plugin lineage
        //    (subsurface.cpp) and model SSS as a Lambertian base-colour lobe with
        //    weight = base_color·subsurface_weight·weight. This captures the SSS
        //    energy/colour but NOT the sub-surface blur (wider declared parity band
        //    vs Cycles). SEAM: converge to the transport-correct random walk in
        //    include/astroray/bssrdf_random_walk.h (PR #565) when D2 converges — that
        //    needs an "intersect within this object only" integrator query, so it is
        //    NOT a Material::eval closure and cannot be wired here.
        //    subsurface_radius/scale are parsed for that future path (unused now).
        if (subsurfaceWeight_ > 1e-4f && luminance(weight) > 1e-4f) {
            Lobe L;
            L.kind = LobeKind::Subsurface;
            L.weight = weight * baseColor_ * subsurfaceWeight_;
            L.color = baseColor_;
            L.roughness = 0.0f;  // Lambertian approximation
            L.sel = std::max(luminance(L.weight), 1e-4f);
            lobes.push_back(L);
        }
        // 8. Diffuse (Lambert / EON). closure weight = base_color·(1-subsurface)·weight.
        if (luminance(weight) > 1e-4f) {
            Lobe L;
            L.kind = LobeKind::Diffuse;
            L.weight = weight * baseColor_ * (1.0f - subsurfaceWeight_);
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
            case LobeKind::Subsurface:  // approximate SSS = Lambert (D2=a)
            case LobeKind::Diffuse: {
                if (nl <= 0.0f || nv <= 0.0f) return Vec3(0);
                if (L.roughness <= 1e-4f) return L.weight * (nl / float(M_PI));  // Lambert
                EON e = eonSetup(std::clamp(L.roughness, 0.0f, 1.0f), nl, nv, wi.dot(wo));
                return Vec3(L.weight.x * eonChannel(e, L.color.x),
                            L.weight.y * eonChannel(e, L.color.y),
                            L.weight.z * eonChannel(e, L.color.z));
            }
            case LobeKind::Sheen: {  // Cycles bsdf_sheen_eval
                if (nl <= 0.0f || nv <= 0.0f) return Vec3(0);
                Vec3 T, B;
                sheenFrame(rec.normal, wo, T, B);
                Vec3 localO(wi.dot(T), wi.dot(B), wi.dot(rec.normal));
                return L.weight * sheenValue(L.sheenA, L.sheenB, localO);
            }
            case LobeKind::Coat:      // clear GGX dielectric — same eval as specular
            case LobeKind::Specular: {
                if (nl <= 0.0f || nv <= 0.0f) return Vec3(0);
                Vec3 h = (wo + wi).normalized();
                // Film-OFF statements FIRST, textually unchanged from pre-change, so
                // /fp:fast codegen at the ggxReflectRGB call site — and the
                // thickness-0 render — stay byte-for-byte identical (memory
                // incremental-build-signature-staleness). The film (rare path) only
                // OVERRIDES F afterward.
                float sHalf = generalizedSchlickS(std::abs(wo.dot(h)), L.ior);
                Vec3 F = L.color + (Vec3(1.0f) - L.color) * sHalf;
                if (L.kind == LobeKind::Specular && filmActive()) {
                    // pkg178 Stage 4 PR-1: thin-film iridescence replaces the
                    // single-scatter Fresnel (Cycles generalized_schlick_fresnel
                    // thin-film branch). compFss stays FILM-FREE (L.color = specF0)
                    // so energy compensation is not double-counted.
                    Vec3 Fraw = thinFilmFresnelRGB(std::abs(wo.dot(h)), L.ior, thinFilmIor_);
                    F = thinFilmF0RescaleRGB(Fraw, L.color, L.ior);
                }
                return L.weight * ggxReflectRGB(F, L.color, L.roughness,
                                                L.anisotropic, L.anisoRotation, rec, wo, wi);
            }
            case LobeKind::Metallic: {
                if (nl <= 0.0f || nv <= 0.0f) return Vec3(0);
                Vec3 h = (wo + wi).normalized();
                float ci = std::clamp(wo.dot(h), 0.0f, 1.0f);
                Vec3 F(f82Channel(ci, L.color.x, specularTint_.x),
                       f82Channel(ci, L.color.y, specularTint_.y),
                       f82Channel(ci, L.color.z, specularTint_.z));
                return L.weight * ggxReflectRGB(F, L.color, L.roughness,
                                                L.anisotropic, L.anisoRotation, rec, wo, wi);
            }
            case LobeKind::Transmission:
                return transmissionEvalRGB(L, rec, wo, wi);
        }
        return Vec3(0);
    }

    // GGX reflection BRDF·cos with multiscatter comp (metal.cpp form).
    // pkg178 PR-4b: `anisotropic<=0` runs the PR-4a isotropic form verbatim
    // (bit-identical); >0 uses Cycles' aniso D/λ in the UV-aligned frame + the
    // geometric-mean roughness for the iso energy table.
    Vec3 ggxReflectRGB(const Vec3& Fhalf, const Vec3& compFss, float roughness,
                       float anisotropic, float anisoRotation,
                       const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
        if (nl <= 0.0f || nv <= 0.0f) return Vec3(0);
        Vec3 h = (wo + wi).normalized();
        float D, G, roughComp;
        if (anisotropic <= 0.0f) {
            float NdotH = std::max(rec.normal.dot(h), 1e-4f);
            float a = std::max(roughness * roughness, 0.0064f), a2 = a * a;
            float denom = NdotH * NdotH * (a2 - 1.0f) + 1.0f;
            D = a2 / (float(M_PI) * denom * denom + 1e-4f);
            G = smithG2_GGX(nl, nv, a);  // height-correlated Smith (Cycles parity)
            roughComp = roughness;
        } else {
            float ax, ay; anisoAlphas(roughness, anisotropic, ax, ay);
            Vec3 X, Y; anisoFrame(rec, anisoRotation, X, Y);
            Vec3 Hl(X.dot(h), Y.dot(h), std::max(rec.normal.dot(h), 1e-4f));
            Vec3 Il(X.dot(wi), Y.dot(wi), nl);
            Vec3 Ol(X.dot(wo), Y.dot(wo), nv);
            D = ggxAnisoD(Hl, ax, ay, 1e-4f);
            G = smithG2Aniso(Il, Ol, ax, ay);
            roughComp = std::sqrt(std::sqrt(ax * ay));
        }
        Vec3 single = Fhalf * (D * G / (4.0f * nv + 1e-4f));  // brdf·NdotL
        return single * ggxCompFactor(compFss, roughComp, nv);
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
            // Height-correlated Smith G2 for the external-reflection sub-lobe
            // (Cycles bsdf_microfacet_eval uses 1/(1+λI+λO) for reflection too).
            float G = smithG2_GGX(cosI, cosO, alpha);
            if (filmActive()) {
                // pkg178 Stage 4 PR-1: thin-film iridescence F (Cycles single
                // microfacet_fresnel at bsdf->ior = etap; specular_tint folded
                // into f0 via the F0-rescale, not a post-multiply).
                float etapR = entering ? L.ior : (1.0f / L.ior);
                float filmIor = entering ? thinFilmIor_ : thinFilmIor_ / L.ior;
                Vec3 F = thinFilmFresnelRGB(HdotO, etapR, filmIor);
                F = thinFilmF0RescaleRGB(F, Vec3(F0_from_ior(etapR)) * specularTint_, etapR);
                float geom = D * G / (4.0f * cosO * cosI + 1e-8f) * cosI;
                return L.weight * F * geom;
            }
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
        // Height-correlated Smith G2 for the refraction sub-lobe (Cycles parity).
        float G = smithG2_GGX(std::abs(cosI), std::abs(cosO), alpha);
        if (filmActive()) {
            // pkg178 Stage 4 PR-1: transmittance = (1-F)·transmission_tint with the
            // same iridescence F; film IOR backface-adjusted (÷bulk IOR).
            float filmIor = entering ? thinFilmIor_ : thinFilmIor_ / L.ior;
            Vec3 Fv = thinFilmFresnelRGB(std::abs(wo.dot(wm)), etap, filmIor);
            Fv = thinFilmF0RescaleRGB(Fv, Vec3(F0_from_ior(etap)) * specularTint_, etap);
            float den = wi.dot(wm) + wo.dot(wm) / etap;
            den = den * den * cosI * cosO;
            float ft = D * G * std::abs(wi.dot(wm) * wo.dot(wm) / (den + 1e-10f));
            ft /= (etap * etap);
            float scale = ft * std::abs(cosI) * ggxGlassComp(etap, std::abs(cosO));
            Vec3 res = L.weight * sqrtColor(baseColor_) * (Vec3(1.0f) - Fv) * scale;
            return Vec3::max(res, Vec3(0.0f));
        }
        float F = fresnelDielectric(std::abs(wo.dot(wm)), etaI, etaT);
        float den = wi.dot(wm) + wo.dot(wm) / etap;
        den = den * den * cosI * cosO;
        float ft = D * (1.0f - F) * G * std::abs(wi.dot(wm) * wo.dot(wm) / (den + 1e-10f));
        ft /= (etap * etap);
        float scale = ft * std::abs(cosI) * ggxGlassComp(etap, std::abs(cosO));
        Vec3 res = L.weight * sqrtColor(baseColor_) * scale;
        return Vec3::max(res, Vec3(0.0f));
    }

    // pkg178 Stage 4 PR-1 — per-λ native thin-film glass eval (film ONLY; the
    // film-free spectral path stays the Stage-3b upsample-of-RGB in the caller).
    // Achromatic geometry × per-λ iridescence F (both faces; backface film-IOR
    // adjust ÷ bulk IOR).
    astroray::SampledSpectrum transmissionEvalSpectral(
            const Lobe& L, const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lam) const {
        if (L.isDelta) return astroray::SampledSpectrum(0.0f);
        float cosO = rec.normal.dot(wo), cosI = rec.normal.dot(wi);
        bool entering = rec.frontFace;
        float alpha = std::max(L.roughness * L.roughness, 0.0064f);
        float etap = entering ? L.ior : (1.0f / L.ior);
        float filmIor = entering ? thinFilmIor_ : thinFilmIor_ / L.ior;
        float F0real = F0_from_ior(etap);
        astroray::SampledSpectrum wSpec = upsample(L.weight, lam);
        astroray::SampledSpectrum tintSpec = upsample(specularTint_, lam);
        if (cosO > 0.0f && cosI > 0.0f) {  // reflection sub-lobe
            Vec3 wm = (wo + wi).normalized();
            if (wm.dot(rec.normal) < 0.0f) wm = -wm;
            float HdotO = wo.dot(wm);
            if (HdotO <= 1e-10f) return astroray::SampledSpectrum(0.0f);
            float D = D_GTR2(wm.dot(rec.normal), alpha);
            float G = smithG2_GGX(cosI, cosO, alpha);
            float geom = D * G / (4.0f * cosO * cosI + 1e-8f) * cosI;
            astroray::SampledSpectrum F = thinFilmFresnelSpectral(HdotO, etap, filmIor, lam);
            astroray::SampledSpectrum out(0.0f);
            for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
                float Fi = (F0real > 1e-5f)
                               ? thinFilmF0RescaleChannel(F[i], F0real * tintSpec[i], F0real)
                               : F[i];
                out[i] = wSpec[i] * Fi * geom;
            }
            return out;
        }
        if (cosO * cosI >= 0.0f) return astroray::SampledSpectrum(0.0f);
        // transmission sub-lobe
        Vec3 wm = (wi * etap + wo).normalized();
        if (wm.dot(rec.normal) < 0.0f) wm = -wm;
        if (wm.dot(wi) * cosI < 0.0f || wm.dot(wo) * cosO < 0.0f)
            return astroray::SampledSpectrum(0.0f);
        float D = D_GTR2(std::abs(wm.dot(rec.normal)), alpha);
        float G = smithG2_GGX(std::abs(cosI), std::abs(cosO), alpha);
        float den = wi.dot(wm) + wo.dot(wm) / etap;
        den = den * den * cosI * cosO;
        float ft = D * G * std::abs(wi.dot(wm) * wo.dot(wm) / (den + 1e-10f));
        ft /= (etap * etap);
        float scale = ft * std::abs(cosI) * ggxGlassComp(etap, std::abs(cosO));
        astroray::SampledSpectrum F = thinFilmFresnelSpectral(std::abs(wo.dot(wm)), etap, filmIor, lam);
        astroray::SampledSpectrum baseSpec = upsample(sqrtColor(baseColor_), lam);
        astroray::SampledSpectrum out(0.0f);
        for (int i = 0; i < astroray::kSpectrumSamples; ++i) {
            float Fi = (F0real > 1e-5f)
                           ? thinFilmF0RescaleChannel(F[i], F0real * tintSpec[i], F0real)
                           : F[i];
            float v = wSpec[i] * baseSpec[i] * (1.0f - Fi) * scale;
            out[i] = v > 0.0f ? v : 0.0f;
        }
        return out;
    }

    float pdfLobe(const Lobe& L, const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
        switch (L.kind) {
            case LobeKind::Subsurface:
            case LobeKind::Diffuse:
                return (nl > 0.0f && nv > 0.0f) ? nl / float(M_PI) : 0.0f;
            case LobeKind::Sheen: {  // Cycles bsdf_sheen_sample: *pdf = val
                if (nl <= 0.0f || nv <= 0.0f) return 0.0f;
                Vec3 T, B;
                sheenFrame(rec.normal, wo, T, B);
                Vec3 localO(wi.dot(T), wi.dot(B), wi.dot(rec.normal));
                return sheenValue(L.sheenA, L.sheenB, localO);
            }
            case LobeKind::Coat:
            case LobeKind::Specular:
            case LobeKind::Metallic: {
                if (nl <= 0.0f || nv <= 0.0f) return 0.0f;
                Vec3 h = (wo + wi).normalized();
                float NdotH = rec.normal.dot(h), HdotV = h.dot(wo);
                if (NdotH <= 0.0f || HdotV <= 0.0f) return 0.0f;
                if (L.anisotropic <= 0.0f) {
                    float a = std::max(L.roughness * L.roughness, 0.0064f);
                    return D_GTR2(NdotH, a) * NdotH / (4.0f * HdotV);
                }
                // pkg178 PR-4b: NDF-sampling pdf with the anisotropic D (Cycles).
                float ax, ay; anisoAlphas(L.roughness, L.anisotropic, ax, ay);
                Vec3 X, Y; anisoFrame(rec, L.anisoRotation, X, Y);
                Vec3 Hl(X.dot(h), Y.dot(h), NdotH);
                return ggxAnisoD(Hl, ax, ay, 1e-12f) * NdotH / (4.0f * HdotV);
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
        // Transparent (alpha) — Cycles bsdf_transparent.h sample: wo = -wi (straight
        // through), delta, matched pdf==eval (ratio 1) → pdfInternal=1, no medium
        // change (eta=1, no η² factor). Consumes ZERO rng draws (CPU/GPU aligned).
        if (L.kind == LobeKind::Transparent) {
            ds.wi = -wo;
            ds.isDelta = true;
            ds.pdfInternal = 1.0f;
            ds.deltaRefract = false;
            ds.eta = 1.0f;
            ds.ok = true;
            return ds;
        }
        if (L.kind == LobeKind::Diffuse || L.kind == LobeKind::Subsurface) {
            Vec3 local = Vec3::randomCosineDirection(gen);
            ds.wi = rec.tangent * local.x + rec.bitangent * local.y + rec.normal * local.z;
            ds.ok = rec.normal.dot(ds.wi) > 0.0f;
            return ds;
        }
        if (L.kind == LobeKind::Sheen) {  // Cycles bsdf_sheen_sample (disk → LTC)
            float u1 = dist(gen), u2 = dist(gen);
            float r = std::sqrt(u1), phi = 2.0f * float(M_PI) * u2;
            float dx = r * std::cos(phi), dy = r * std::sin(phi);
            float diskZ = std::sqrt(std::max(0.0f, 1.0f - dx * dx - dy * dy));
            Vec3 localO = Vec3(dx - diskZ * L.sheenB, dy, diskZ * L.sheenA).normalized();
            Vec3 T, B;
            sheenFrame(rec.normal, wo, T, B);
            ds.wi = (T * localO.x + B * localO.y + rec.normal * localO.z).normalized();
            ds.ok = rec.normal.dot(ds.wi) > 0.0f;
            return ds;
        }
        if (L.kind == LobeKind::Specular || L.kind == LobeKind::Metallic ||
            L.kind == LobeKind::Coat) {
            float r1 = dist(gen), r2 = dist(gen);  // 2 draws in both branches
            float phi = 2.0f * float(M_PI) * r1;
            if (L.anisotropic <= 0.0f) {
                float a = std::max(L.roughness * L.roughness, 0.0064f);
                float cosT = std::sqrt((1.0f - r2) / (1.0f + (a * a - 1.0f) * r2));
                float sinT = std::sqrt(std::max(0.0f, 1.0f - cosT * cosT));
                Vec3 h(std::cos(phi) * sinT, std::sin(phi) * sinT, cosT);
                h = rec.tangent * h.x + rec.bitangent * h.y + rec.normal * h.z;
                ds.wi = (h * (2.0f * wo.dot(h)) - wo).normalized();
                ds.ok = rec.normal.dot(ds.wi) > 0.0f;
                return ds;
            }
            // pkg178 PR-4b: anisotropic NDF half-vector via slope stretch
            // (Heitz 2018 / Walter 2007). Reduces to the iso sampler at ax==ay.
            float ax, ay; anisoAlphas(L.roughness, L.anisotropic, ax, ay);
            Vec3 X, Y; anisoFrame(rec, L.anisoRotation, X, Y);
            float rr = std::sqrt(r2 / std::max(1.0f - r2, 1e-6f));
            float sx = ax * rr * std::cos(phi);
            float sy = ay * rr * std::sin(phi);
            Vec3 hl = Vec3(-sx, -sy, 1.0f).normalized();
            Vec3 h = X * hl.x + Y * hl.y + rec.normal * hl.z;
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
          thinWall_(p.getFloat("thin_wall", 0.0f) > 0.5f),
          thinFilmThickness_(std::max(0.0f, p.getFloat("thin_film_thickness", 0.0f))),
          // Cycles forces film IOR to 0 below the cutoff; here we simply gate on
          // thickness (filmActive()) and keep the socket default 1.33 otherwise.
          thinFilmIor_(std::max(1e-5f, p.getFloat("thin_film_ior", 1.33f))),
          anisotropic_(std::clamp(p.getFloat("anisotropic", 0.0f), 0.0f, 1.0f)),
          anisotropicRotation_(p.getFloat("anisotropic_rotation", 0.0f)),
          coatWeight_(std::clamp(p.getFloat("coat_weight", 0.0f), 0.0f, 1.0f)),
          coatRoughness_(std::clamp(p.getFloat("coat_roughness", 0.03f), 0.001f, 1.0f)),
          coatIor_(std::max(1.0f, p.getFloat("coat_ior", 1.5f))),
          coatTint_(p.getVec3("coat_tint", Vec3(1.0f))),
          sheenWeight_(std::clamp(p.getFloat("sheen_weight", 0.0f), 0.0f, 1.0f)),
          sheenRoughness_(std::clamp(p.getFloat("sheen_roughness", 0.5f), 0.001f, 1.0f)),
          sheenTint_(p.getVec3("sheen_tint", Vec3(1.0f))),
          subsurfaceWeight_(std::clamp(p.getFloat("subsurface_weight", 0.0f), 0.0f, 1.0f)),
          subsurfaceScale_(std::max(0.0f, p.getFloat("subsurface_scale", 0.05f))),
          subsurfaceRadius_(p.getVec3("subsurface_radius", Vec3(1.0f, 0.2f, 0.1f))),
          emissionColor_(p.getVec3("emission_color", Vec3(0.0f))),
          emissionStrength_(std::max(0.0f, p.getFloat("emission_strength", 1.0f))),
          emissionSpec_({emissionColor_.x * emissionStrength_,
                         emissionColor_.y * emissionStrength_,
                         emissionColor_.z * emissionStrength_}) {}

    Vec3 getAlbedo() const override { return baseColor_; }
    float getAnisotropic() const override { return anisotropic_; }  // pkg178 PR-4b
    float getRoughness() const override { return roughness_; }
    float getMetallic() const override { return metallic_; }
    float getIOR() const override { return ior_; }
    float getTransmission() const override { return transmission_; }
    bool isTransmissive() const override { return transmission_ > 1e-4f; }
    bool isGlossy() const override { return true; }

    // pkg178 Stage 3 — emission inside the node (retires the addon promote-to-light
    // heuristic for the flagged path; the closure side lives here, the addon switch
    // is Stage 5). Emission = emission_color·emission_strength (two-sided, like
    // EmissivePlugin). Default emission_color=(0,0,0) → emitted()=0 (non-regressing).
    // NOTE (LEAD/GPU): the GPU leg emits via scene_upload's g.emissionIntensity +
    // GAreaLight extraction, which today only fires for gpuType=="diffuse_light";
    // an emissive Principled surface on the wavefront leg needs that extraction to
    // learn the closure-graph emission path. CPU leg is complete here.
    Vec3 emitted(const HitRecord& /*rec*/) const override {
        return emissionColor_ * emissionStrength_;
    }
    astroray::SampledSpectrum emittedSpectral(
            const HitRecord& /*rec*/,
            const astroray::SampledWavelengths& lambdas) const override {
        if (emissionStrength_ <= 0.0f) return astroray::SampledSpectrum(0.0f);
        return emissionSpec_.sample(lambdas);
    }
    Vec3 getEmission() const override { return emissionColor_ * emissionStrength_; }
    bool isEmissive() const override {
        return emissionStrength_ > 0.0f &&
               (emissionColor_.x > 0.0f || emissionColor_.y > 0.0f || emissionColor_.z > 0.0f);
    }

    // pkg178 Stage 2 GPU seam (the ONLY additions to this Stage-1 file — no lobe
    // math changed): lower to GMAT_CLOSURE_GRAPH via a single monolithic
    // GCLOSURE_PRINCIPLED closure carrying the raw core-lobe params. The device
    // twin (gpu_principled_* in gpu_materials.h) re-runs assembleLobes on device
    // per shade, because the assembly is VIEW-DEPENDENT and cannot be baked into
    // static per-lobe closure weights.
    std::string getGPUTypeName() const override { return "principled"; }
    astroray::MaterialClosureGraph closureGraph() const override {
        astroray::MaterialClosureGraph graph;
        astroray::MaterialClosure c = astroray::makePrincipledClosure(
            astroray::ClosureColor{baseColor_.x, baseColor_.y, baseColor_.z},
            metallic_, roughness_, ior_, specularIorLevel_,
            astroray::ClosureColor{specularTint_.x, specularTint_.y, specularTint_.z},
            transmission_, diffuseRoughness_);
        // pkg178 Stage 3: carry the advanced-layer params (values are already the
        // ctor-clamped members, so the device twin sees exactly the CPU values).
        c.coatWeight = coatWeight_;
        c.coatRoughness = coatRoughness_;
        c.coatIor = coatIor_;
        c.coatTint = {coatTint_.x, coatTint_.y, coatTint_.z};
        c.sheenWeight = sheenWeight_;
        c.sheenRoughness = sheenRoughness_;
        c.sheenTint = {sheenTint_.x, sheenTint_.y, sheenTint_.z};
        c.subsurfaceWeight = subsurfaceWeight_;
        c.subsurfaceRadius = {subsurfaceRadius_.x, subsurfaceRadius_.y, subsurfaceRadius_.z};
        c.subsurfaceScale = subsurfaceScale_;
        c.emissionColor = {emissionColor_.x, emissionColor_.y, emissionColor_.z};
        c.emissionStrength = emissionStrength_;
        c.anisotropic = anisotropic_;                 // pkg178 PR-4b
        c.anisotropicRotation = anisotropicRotation_;
        c.alpha = alpha_;                             // pkg178 PR-6
        c.thinFilmThickness = thinFilmThickness_;     // pkg178 Stage 4 PR-1 (GPU twin: PR-3)
        c.thinFilmIor = thinFilmIor_;
        graph.add(c);
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
        caps.notes = "pkg178 Stage 3: native Principled core lobes + coat/sheen(LTC)/"
                     "approx-subsurface/emission via GMAT_CLOSURE_GRAPH + GCLOSURE_PRINCIPLED";
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
            case LobeKind::Subsurface:  // approximate SSS = Lambert (D2=a)
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
            case LobeKind::Sheen: {  // achromatic LTC scalar; tinted weight upsampled
                if (nl <= 0.0f || nv <= 0.0f) return astroray::SampledSpectrum(0.0f);
                Vec3 T, B;
                sheenFrame(rec.normal, wo, T, B);
                Vec3 localO(wi.dot(T), wi.dot(B), wi.dot(rec.normal));
                return wSpec * sheenValue(L.sheenA, L.sheenB, localO);
            }
            case LobeKind::Coat:      // clear GGX dielectric — same spectral eval
            case LobeKind::Specular: {
                if (nl <= 0.0f || nv <= 0.0f) return astroray::SampledSpectrum(0.0f);
                Vec3 h = (wo + wi).normalized();
                // Film-OFF statements FIRST, textually unchanged from pre-change (see
                // the RGB twin above); the film (rare path) only OVERRIDES F afterward.
                float sHalf = generalizedSchlickS(std::abs(wo.dot(h)), L.ior);
                astroray::SampledSpectrum f0 = upsample(L.color, lam);
                astroray::SampledSpectrum F = f0 + (astroray::SampledSpectrum(1.0f) - f0) * sHalf;
                if (L.kind == LobeKind::Specular && filmActive()) {
                    // pkg178 Stage 4 PR-1: per-λ native thin-film iridescence
                    // (analytic sensitivity, no LUT). compFss (f0) stays film-free.
                    F = thinFilmFresnelSpectral(std::abs(wo.dot(h)), L.ior, thinFilmIor_, lam);
                    float F0real = F0_from_ior(L.ior);
                    if (F0real > 1e-5f)
                        for (int i = 0; i < astroray::kSpectrumSamples; ++i)
                            F[i] = thinFilmF0RescaleChannel(F[i], f0[i], F0real);
                }
                return wSpec * ggxReflectSpectral(F, f0, L.roughness, L.anisotropic,
                                                  L.anisoRotation, rec, wo, wi);
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
                return wSpec * ggxReflectSpectral(F, f0, L.roughness, L.anisotropic,
                                                  L.anisoRotation, rec, wo, wi);
            }
            case LobeKind::Transmission: {
                // pkg178 Stage 4 PR-1: with the film ON, evaluate F per-λ natively
                // (pkg163 discipline); OFF path is the exact Stage-3b upsample hack.
                if (filmActive()) return transmissionEvalSpectral(L, rec, wo, wi, lam);
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
                                                 float roughness, float anisotropic,
                                                 float anisoRotation, const HitRecord& rec,
                                                 const Vec3& wo, const Vec3& wi) const {
        float nl = rec.normal.dot(wi), nv = rec.normal.dot(wo);
        if (nl <= 0.0f || nv <= 0.0f) return astroray::SampledSpectrum(0.0f);
        Vec3 h = (wo + wi).normalized();
        float D, G, roughComp;
        if (anisotropic <= 0.0f) {
            float NdotH = std::max(rec.normal.dot(h), 1e-4f);
            float a = std::max(roughness * roughness, 0.0064f), a2 = a * a;
            float denom = NdotH * NdotH * (a2 - 1.0f) + 1.0f;
            D = a2 / (float(M_PI) * denom * denom + 1e-4f);
            G = smithG2_GGX(nl, nv, a);  // height-correlated Smith (Cycles parity)
            roughComp = roughness;
        } else {
            float ax, ay; anisoAlphas(roughness, anisotropic, ax, ay);
            Vec3 X, Y; anisoFrame(rec, anisoRotation, X, Y);
            Vec3 Hl(X.dot(h), Y.dot(h), std::max(rec.normal.dot(h), 1e-4f));
            Vec3 Il(X.dot(wi), Y.dot(wi), nl);
            Vec3 Ol(X.dot(wo), Y.dot(wo), nv);
            D = ggxAnisoD(Hl, ax, ay, 1e-4f);
            G = smithG2Aniso(Il, Ol, ax, ay);
            roughComp = std::sqrt(std::sqrt(ax * ay));
        }
        astroray::SampledSpectrum single = Fhalf * (D * G / (4.0f * nv + 1e-4f));
        const auto& t = astroray::DisneyEnergyCompensationTables::instance();
        if (!t.loaded()) return single;
        float E = std::max(t.ggxE(roughComp, nv), 1e-4f);
        float Eavg = std::clamp(t.ggxEavg(roughComp), 0.0f, 0.999f);
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
            if (L.kind == LobeKind::Transparent) {
                // Straight-through: f = weight_T, pdf = qj → f/pdf = weight_T/qj
                // (Cycles bsdf_transparent.h; unbiased one-sample MIS: W cancels).
                s.f = L.weight;
            } else if (ds.deltaRefract) {
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
            Vec3 rgb = (L.kind == LobeKind::Transparent)
                           ? L.weight  // straight-through weight_T (spectrally flat grey ≤1)
                       : ds.deltaRefract
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

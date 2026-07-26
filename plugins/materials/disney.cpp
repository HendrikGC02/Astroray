#include "astroray/register.h"
#include "astroray/energy_compensation.h"
#include "advanced_features.h"

class DisneyPlugin : public Material {
    Vec3 baseColor_;
    float metallic_, roughness_, anisotropic_, anisotropicRotation_;
    float subsurface_, specular_, specularTint_;
    float clearcoat_, clearcoatGloss_;
    float sheen_, sheenTint_;
    float transmission_, ior_;
    static constexpr float kDeltaTransmissionRoughness = 0.03f;

    // GGX/Trowbridge-Reitz NDF (Walter 2007 Eq. 33, pbrt-v4 §9.6).
    // D(wm) = α² / (π (1 + (α²-1)·cos²θm)²)
    float D_GTR2(float NdotH, float a) const {
        float a2 = a * a;
        float t = 1 + (a2 - 1) * NdotH * NdotH;
        return a2 / (float(M_PI) * t * t);
    }

    float smithG_GGX(float NdotV, float alphaG) const {
        float a = alphaG * alphaG;
        float b = NdotV * NdotV;
        return 1 / (NdotV + std::sqrt(a + b - a * b) + 0.001f);
    }

    // True Smith masking-shadowing G1 in [0,1] (Walter 2007 Eq. 34). Note smithG_GGX
    // above is the COMBINED visibility form G1/(2·NdotV) — it folds the reflection
    // BRDF's 1/(4·cosO·cosI) into G (so the reflection lobe uses spec = D·F·Gs bare).
    // The rough-TRANSMISSION estimator (Walter 2007 §5.3) needs the true G1, not the
    // combined form, otherwise a spurious 1/(4·cosO·cosI) ≈ 0.25 factor survives in
    // f/pdf and rough glass loses ~70% energy. smithG1_GGX = 2·NdotV·smithG_GGX.
    float smithG1_GGX(float NdotV, float alphaG) const {
        float a = alphaG * alphaG;
        float b = NdotV * NdotV;
        return 2.0f * NdotV / (NdotV + std::sqrt(a + b - a * b) + 0.001f);
    }

    Vec3 fresnelSchlick(float cosTheta, const Vec3& F0, float scale = 0.8f) const {
        float c = std::clamp(1 - cosTheta, 0.0f, 1.0f);
        return F0 + (Vec3(1) - F0) * std::pow(c, 5) * scale;
    }

    // Cycles bsdf_microfacet.h microfacet_ggx_preserve_energy (BSD-3-Clause):
    // per-channel darkening factor "1 + Fms*(1-E)/E" that scales a raw
    // single-scatter GGX term up to the true (single+multi-scatter,
    // Fresnel-darkened) energy. `f` is the layer's own (achromatic)
    // Fresnel reflectance channel, `E`/`Eavg` the in-repo table_ggx_E /
    // table_ggx_Eavg directional/average albedo at this (roughness, mu).
    //
    // pkg160: the body moved verbatim to astroray::ggxDarkeningChannel
    // (include/astroray/energy_compensation.h) so plugins/materials/metal.cpp
    // can call the SAME implementation instead of growing a third host copy
    // of the formula. This forwarder keeps the call sites below unchanged.
    float ggxDarkeningChannel(float f, float E, float Eavg) const {
        return astroray::ggxDarkeningChannel(f, E, Eavg);
    }

    // pkg151: Kulla & Conty 2017 "Revisiting Physically Based Shading at
    // Imageworks" hemispherical-average Fresnel reflectance fit for a
    // dielectric interface, ported from Cycles `bsdf_util.h`
    // `fresnel_dielectric_Fss` (BSD-3-Clause). Used (not the per-direction
    // Schlick approximation) because the glass multi-scatter tables below are
    // baked assuming this exact closed-form average, matching how Cycles'
    // `bsdf_microfacet_setup_fresnel_dielectric` derives the `Fss` argument to
    // `microfacet_ggx_preserve_energy` for `CLOSURE_BSDF_MICROFACET_GGX_GLASS_ID`.
    float fresnelDielectricFss(float eta) const {
        if (eta < 1.0f) {
            return 0.997118f + eta * (0.1014f - eta * (0.965241f + eta * 0.130607f));
        }
        return (eta - 1.0f) / (4.08567f + 1.00071f * eta);
    }

    // pkg151: rough-transmission multi-scatter energy compensation, the
    // transmission-lobe counterpart to ggxCompensationFactor below. Cycles
    // bakes ONE compensation for its combined glass closure (reflection +
    // transmission); Astroray splits the two lobes at eval() time, so this is
    // applied to roughTransmissionEval's own return value only (Caveat 1,
    // .astroray_plan/docs/pkg151-cycles-glass-tables-research.md) — it must
    // not touch roughTransmissionPdf or the VNDF sampler (throughput magnitude
    // only, not sampled-direction shape, per the spec's peak-alignment gate).
    // `etap` is the same entering/exiting-relative ior roughTransmissionEval
    // already computes (ior_ when entering, 1/ior_ when exiting); `muAbs` is
    // the outgoing-direction cosine to the macro normal, matching Cycles'
    // `mu = dot(wi, bsdf->N)` (wi there = the view/outgoing direction).
    float ggxGlassCompensationFactor(float etap, float muAbs) const {
        const auto& tables = astroray::DisneyEnergyCompensationTables::instance();
        if (!tables.loaded()) return 1.0f;

        const float E = std::max(tables.ggxGlassE(roughness_, muAbs, etap), 1e-4f);
        const float Eavg = std::clamp(tables.ggxGlassEavg(roughness_, etap), 0.0f, 0.999f);
        const float Fss = std::clamp(fresnelDielectricFss(etap), 0.0f, 0.999f);
        return ggxDarkeningChannel(Fss, E, Eavg);
    }

    Vec3 ggxCompensationFactor(const Vec3& Fss, float roughness, float mu) const {
        const auto& tables = astroray::DisneyEnergyCompensationTables::instance();
        if (!tables.loaded()) return Vec3(1.0f);

        const float E = std::max(tables.ggxE(roughness, mu), 1e-4f);
        const float Eavg = std::clamp(tables.ggxEavg(roughness), 0.0f, 0.999f);
        return Vec3(ggxDarkeningChannel(Fss.x, E, Eavg),
                    ggxDarkeningChannel(Fss.y, E, Eavg),
                    ggxDarkeningChannel(Fss.z, E, Eavg));
    }

    // pkg145: the compensated GGX specular layer's own directional-
    // hemispherical reflectance at wo — the quantity Cycles calls via
    // `bsdf_albedo`/`bsdf_microfacet_estimate_albedo` before
    // `closure_layering_weight` attenuates whatever sits underneath it
    // (`bsdf_util.h`, Apache-2.0; `bsdf_microfacet.h`, BSD-3-Clause).
    // `Fview` is the layer's Fresnel reflectance AT THE VIEW ANGLE
    // (`fresnelSchlick(mu, F0, ...)`, matching Cycles' `bsdf_microfacet_
    // estimate_albedo`'s `cos_NI`-evaluated fallback, `microfacet_fresnel`)
    // — Kulla & Conty 2017's E(mu_o) is itself defined through this angle
    // dependence (the "constant Fresnel" approximation `ggxCompensationFactor`
    // above uses is only valid ACROSS the lobe at a fixed mu, i.e. F(l.h)~=
    // F(mu_o) for wi near the lobe peak, not across different mu_o — grazing
    // mu_o must use the grazing-boosted Fresnel, not the material's F0).
    // Raw single-scatter directional albedo at this angle is
    // `E(roughness,mu)*Fview`; the darkening factor recovers the compensated
    // total. No new table, no separate integration.
    Vec3 ggxDirectionalAlbedo(const Vec3& Fview, float roughness, float mu) const {
        const auto& tables = astroray::DisneyEnergyCompensationTables::instance();
        if (!tables.loaded()) return Fview;

        const float E = std::max(tables.ggxE(roughness, mu), 1e-4f);
        const float Eavg = std::clamp(tables.ggxEavg(roughness), 0.0f, 0.999f);
        auto channel = [&](float f) {
            const float fc = std::clamp(f, 0.0f, 0.999f);
            return E * fc * ggxDarkeningChannel(fc, E, Eavg);
        };
        return Vec3(channel(Fview.x), channel(Fview.y), channel(Fview.z));
    }

    Vec3 layeringWeightAfter(const Vec3& weight, const Vec3& albedo) const {
        return weight * (Vec3(1.0f) - Vec3::min(albedo, Vec3(0.999f)));
    }

    // pkg60 grazing-incidence Burley-diffuse furnace normalization. Measured
    // (pkg145 grid sweep) to still be required at roughness in {0.7, 0.9},
    // grazing cos_theta_o=0.1 even after the diffuse-under-specular coupling
    // lands (see the eval() comment above `diffuse`) — a rough dielectric's
    // specular directional albedo is small, so the coupling barely
    // attenuates diffuse there, leaving Burley 2015's own grazing/roughness
    // retro-reflection excess unchecked. Retained unmodified; a from-first-
    // principles refit of the Burley retro term itself is future work.
    float diffuseFurnaceScale(float roughness, float mu) const {
        const float grazing = 1.0f - std::clamp(mu, 0.0f, 1.0f);
        const float excess = roughness * (0.055f + 0.40f * grazing * grazing);
        return 1.0f / (1.0f + excess);
    }

    // pkg123: floor at 0 only — NO upper cap. A finite cap clips the near-delta
    // GGX specular peak: once the chi²-required spurious `+0.001f` epsilon is
    // removed from D_GTR2, the specular D reaches ~1e3-1e4 at the alpha floor
    // (roughness<=0.08), so eval()'s spec `f` gets capped while pdf() carries
    // the uncapped D — the importance-sampled f/pdf ratio then no longer cancels
    // D and metal reflection collapses to black (test_disney_metal_reflection_
    // not_black: 0.215 vs 0.604, ~2.8x too dark). On the pre-pkg123 engine the
    // epsilon deflated D to <=~0.32 at every roughness, so this 4.0 cap never
    // fired and f/pdf cancelled cleanly; removing the cap restores that render
    // behaviour while keeping the epsilon-free pdf the chi² gates require.
    // Firefly control belongs at the integrator (raytracer.h clampDirect/
    // clampIndirect + the sLum>20 per-sample guard), mirroring Cycles'
    // kernel_accum_clamp (clamp_direct/clamp_indirect) — never a closure-level
    // cap on the BRDF value (Cycles bsdf_microfacet.h returns the true D).
    Vec3 clampColor(const Vec3& c) const {
        return Vec3::max(c, Vec3(0.0f));
    }

    float fresnelDielectric(float cosThetaI, float etaI, float etaT) const {
        cosThetaI = std::clamp(cosThetaI, -1.0f, 1.0f);
        bool entering = cosThetaI > 0.0f;
        if (!entering) {
            std::swap(etaI, etaT);
            cosThetaI = std::abs(cosThetaI);
        }

        float sinThetaI = std::sqrt(std::max(0.0f, 1.0f - cosThetaI * cosThetaI));
        float sinThetaT = etaI / etaT * sinThetaI;
        if (sinThetaT >= 1.0f) return 1.0f;

        float cosThetaT = std::sqrt(std::max(0.0f, 1.0f - sinThetaT * sinThetaT));
        float rParallel = ((etaT * cosThetaI) - (etaI * cosThetaT)) /
                          ((etaT * cosThetaI) + (etaI * cosThetaT) + 1e-6f);
        float rPerp = ((etaI * cosThetaI) - (etaT * cosThetaT)) /
                      ((etaI * cosThetaI) + (etaT * cosThetaT) + 1e-6f);
        return std::clamp(0.5f * (rParallel * rParallel + rPerp * rPerp), 0.0f, 1.0f);
    }

    // Heitz 2018 "Sampling the GGX Distribution of Visible Normals", JCGT 7(4).
    // Ported from PBRT-v4 TrowbridgeReitzDistribution::Sample_wm (BSD-3-Clause).
    Vec3 sampleGgxVNDF(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const {
        std::uniform_real_distribution<float> dist(0.0f, 1.0f);
        float alpha = std::max(roughness_ * roughness_, 0.0064f);
        float u1 = dist(gen), u2 = dist(gen);

        // Transform wo to local tangent space
        Vec3 wo_local(wo.dot(rec.tangent), wo.dot(rec.bitangent), wo.dot(rec.normal));
        // Transform to hemispherical configuration
        Vec3 wh = Vec3(alpha * wo_local.x, alpha * wo_local.y, wo_local.z).normalized();
        if (wh.z < 0.0f) wh = -wh;

        // Orthonormal basis for visible normal sampling
        Vec3 T1 = (wh.z < 0.99999f) ? Vec3(0, 0, 1).cross(wh).normalized() : Vec3(1, 0, 0);
        Vec3 T2 = wh.cross(T1);

        // Sample uniform disk (polar)
        float r = std::sqrt(u1);
        float phi = 2.0f * float(M_PI) * u2;
        float px = r * std::cos(phi);
        float py = r * std::sin(phi);

        // Warp hemispherical projection for visible normal sampling
        // pkg149: pbrt-v4 computes `p.y = Lerp((1+wh.z)/2, h, p.y)` where
        // Lerp(t,a,b) = (1-t)*a + t*b (pbrt-v4 src/pbrt/util/math.h), i.e.
        // p.y = (1-t)*h + t*p.y. This line had `h` and `py` swapped (t*h +
        // (1-t)*py) -- an argument-order transcription bug, not a sign or
        // Jacobian error. Root-caused via a standalone half-vector-space
        // sweep (wo at 45 deg, roughness 0.3): the buggy formula drew visible
        // normals concentrated on the AZIMUTH OPPOSITE wo (phi in [-180,-150]
        // union [150,180], zero density near phi=0, the side VNDF sampling
        // should concentrate on), which after refraction produced the
        // measured ~16-18 deg transmission sample/pdf peak offset (152 deg
        // pdf peak vs 168-170 deg sample peak, glass[0.3-45]). Fixing the
        // argument order realigns the sampled half-vector azimuth with wo and
        // collapses the peak offset to <1 deg (see
        // .astroray_plan/docs/pkg149-disney-rough-transmission-research.md).
        float h = std::sqrt(std::max(0.0f, 1.0f - px * px));
        float t = (1.0f + wh.z) / 2.0f;
        py = (1.0f - t) * h + t * py;

        // Reproject to hemisphere and transform normal to ellipsoid configuration
        float pz = std::sqrt(std::max(0.0f, 1.0f - px * px - py * py));
        Vec3 nh = T1 * px + T2 * py + wh * pz;
        Vec3 m_local = Vec3(alpha * nh.x, alpha * nh.y, std::max(1e-6f, nh.z)).normalized();

        // Transform back to world space
        Vec3 m = rec.tangent * m_local.x + rec.bitangent * m_local.y + rec.normal * m_local.z;
        return m.normalized();
    }

    bool refractThroughMicroNormal(const Vec3& wo, const Vec3& m, float eta, Vec3& wi) const {
        float cosTheta = std::clamp(wo.dot(m), -1.0f, 1.0f);
        if (cosTheta <= 0.0f) return false;

        Vec3 wtPerp = (wo - m * cosTheta) * (-eta);
        float parallel2 = 1.0f - wtPerp.length2();
        if (parallel2 <= 0.0f) return false;

        Vec3 wtParallel = m * (-std::sqrt(parallel2));
        wi = (wtPerp + wtParallel).normalized();
        return wi.length2() > 1e-10f;
    }

    // VNDF reflection PDF (PBRT-v4 DielectricBxDF::PDF reflection branch).
    float microfacetReflectionPdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        if (rec.normal.dot(wo) * rec.normal.dot(wi) <= 0.0f) return 0.0f;
        Vec3 wm = (wo + wi).normalized();
        if (wm.length2() <= 1e-10f) return 0.0f;
        if (wm.dot(rec.normal) < 0.0f) wm = -wm;

        float HdotO = std::abs(wo.dot(wm));
        if (HdotO <= 1e-10f) return 0.0f;

        // PBRT-v4: reflection PDF = VNDF_PDF / (4 * |HdotO|)
        // (pbrt-v4 DielectricBxDF, Walter 2007 §5.3 Jacobian).
        return vndfPdf(rec.normal, wo, wm) / (4.0f * HdotO);
    }

    // pkg138: rough dielectric reflection BRDF (PBRT-v4 DielectricBxDF::f
    // reflection branch, BSD-3-Clause; Walter, Marschner, Li, Torrance 2007
    // "Microfacet Models for Refraction through Rough Surfaces" (EGSR) §5.1
    // Eq. 20):
    //   f_r(wo,wi) = D(wm)*G(wo,wi)*F_dielectric(wo.wm,eta) / (4*cosThetaO*cosThetaI)
    // Mirrors roughTransmissionEval's structure and reuses D_GTR2, the TRUE
    // Smith G1 (smithG1_GGX -- Eq.20's explicit 1/(4 cosO cosI) needs
    // G(wo,wi)=G1(wo)*G1(wi), not the combined-visibility form baked into the
    // opaque Schlick `spec` lobe in eval() below) and fresnelDielectric.
    // Untinted (no baseColor/Cspec0 tint): a dielectric surface reflection is
    // the bare Fresnel reflectance, matching pbrt-v4's plain DielectricBxDF
    // (no separate reflectance albedo/spectrum). This is the pkg138 fix: the
    // Schlick-F0/Cspec0 collapsed reflection color previously made eval()'s
    // reflection lobe near-zero for a transmissive (glass) material, causing
    // sample()'s VNDF reflection candidate to be rejected in favor of a
    // smooth-mirror delta while pdf() kept reporting a continuous VNDF
    // density for the same directions (chi²=143M at glass[0.3-45]).
    Vec3 roughReflectionEval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        float cosO = rec.normal.dot(wo);
        float cosI = rec.normal.dot(wi);
        if (cosO <= 0.0f || cosI <= 0.0f) return Vec3(0);

        Vec3 wm = (wo + wi).normalized();
        if (wm.length2() <= 1e-10f) return Vec3(0);
        if (wm.dot(rec.normal) < 0.0f) wm = -wm;

        float HdotO = wo.dot(wm);
        if (HdotO <= 1e-10f) return Vec3(0);

        float alpha = std::max(roughness_ * roughness_, 0.0064f);
        float NdotH = wm.dot(rec.normal);
        float D = D_GTR2(NdotH, alpha);
        float G = smithG1_GGX(cosO, alpha) * smithG1_GGX(cosI, alpha);
        float F = fresnelDielectric(HdotO, 1.0f, ior_);

        float fr = D * G * F / (4.0f * cosO * cosI + 1e-8f);
        return Vec3(fr);
    }

    // PBRT-v4 DielectricBxDF::f transmission (BSD-3-Clause).
    // Walter 2007 "Microfacet Models for Refraction through Rough Surfaces" Eq. 21.
    Vec3 roughTransmissionEval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        float cosO = rec.normal.dot(wo);
        float cosI = rec.normal.dot(wi);
        if (cosO == 0.0f || cosI == 0.0f || cosO * cosI >= 0.0f) return Vec3(0);

        // pkg154: entering/exiting MUST come from rec.frontFace, not the sign
        // of cosO = rec.normal.dot(wo). rec.normal is the front-facing
        // (HitRecord::setFaceNormal'd) shading normal, so it is ALWAYS
        // reoriented to satisfy wo.dot(rec.normal) >= 0 regardless of which
        // side of the interface the ray is actually crossing -- `cosO > 0.0f`
        // is therefore true on effectively 100% of calls (measured on the
        // pkg149 corrected-sampler branch: 274,809/274,809 at roughness=0.1,
        // including the 61% of those calls where rec.frontFace was false,
        // i.e. a true glass->air exit event). Both the entering AND exiting
        // refraction events were computing etap = ior_ (never 1/ior_), so the
        // radiance-compression factor 1/etap^2 applied at BOTH transmission
        // events instead of cancelling over the round trip: (1/ior^2)^2 =
        // (1/2.25)^2 = 0.1975 at ior=1.5. Same bug class already found and
        // fixed in the smooth dielectric (plugins/materials/dielectric.cpp:
        // "Enter/exit MUST come from rec.frontFace, not the sign of
        // wo.rec.normal") and in photon_caustic.cu (memory:
        // photon-caustic-exit-refraction-oriented-normal); never ported to
        // the Disney rough-transmission eval()/pdf() pair. sample()'s own eta
        // computation (`rec.frontFace ? 1.0f : ior_`, a few lines above this
        // function's call sites) was already correct -- it just wasn't
        // consulted here, so the refracted direction was right but this
        // function recomputed a different (wrong) eta orientation for the
        // same event. See .astroray_plan/docs/pkg154-furnace-deficit-findings.md.
        bool entering = rec.frontFace;
        float etaI = entering ? 1.0f : ior_;
        float etaT = entering ? ior_ : 1.0f;
        float etap = entering ? ior_ : (1.0f / ior_);  // etaT/etaI
        Vec3 wm = (wi * etap + wo).normalized();
        if (wm.length2() <= 1e-10f) return Vec3(0);
        // Face forward (PBRT-v4 FaceForward)
        if (wm.dot(rec.normal) < 0.0f) wm = -wm;

        // Discard backfacing microfacets
        if (wm.dot(wi) * cosI < 0.0f || wm.dot(wo) * cosO < 0.0f) return Vec3(0);

        float alpha = std::max(roughness_ * roughness_, 0.0064f);
        float D = D_GTR2(std::abs(wm.dot(rec.normal)), alpha);
        // PBRT-v4: G(wo, wi) = 1 / (1 + Lambda(wo) + Lambda(wi))
        float G = smithG1_GGX(std::abs(cosO), alpha) * smithG1_GGX(std::abs(cosI), alpha);
        float F = fresnelDielectric(std::abs(wo.dot(wm)), etaI, etaT);

        // PBRT-v4 transmission eval: D * (1-F) * G * |HdotI * HdotO / denom|
        float denom = (wi.dot(wm) + wo.dot(wm) / etap);
        denom = denom * denom * cosI * cosO;
        float ft = D * (1.0f - F) * G * std::abs(wi.dot(wm) * wo.dot(wm) / (denom + 1e-10f));

        // PBRT-v4: radiance transport correction (Astroray is a radiance path tracer)
        ft /= (etap * etap);

        float scale = (1.0f - metallic_) * transmission_ * ft;
        Vec3 result = baseColor_ * scale;

        // pkg151: rough-transmission multi-scatter compensation (Cycles glass
        // tables, see ggxGlassCompensationFactor above). Scales throughput
        // magnitude only; roughTransmissionPdf/sampleGgxVNDF are untouched.
        result *= ggxGlassCompensationFactor(etap, std::abs(cosO));

        // pkg154: removed the closure-level `clamp(0,4)` this function used to
        // apply here. GGX D(wm) grows without bound as alpha -> 0 for
        // near-perfectly-aligned half-vectors, so at LOW roughness the
        // legitimate (unbiased) MC estimator has a heavy right tail -- rare
        // high-value samples that a hard magnitude cap silently discards,
        // which is exactly what an unbiased Monte Carlo estimator must not do
        // (the mean of a truncated distribution is not the mean of the true
        // one). Measured: on the pkg149 corrected sampler + the frontFace fix
        // above, the cap alone held the furnace at 0.18/0.37/0.85/0.98
        // (roughness 0.1/0.3/0.6/1.0) -- rising toward 1.0 with roughness
        // exactly as the D(wm) tail flattens out; removing it restores
        // 0.999/0.999/0.999/0.997 (uncapped) across the same grid, plus
        // 0.999 at roughness=0.05. This is the same bug class already found
        // and fixed for the metal REFLECTION lobe (pkg123, see the
        // `clampColor` comment a few lines above `fresnelDielectric`: "a
        // closure-level cap ... never fires and f/pdf cancelled cleanly;
        // removing the cap restores that render behaviour" -- Cycles
        // bsdf_microfacet.h returns the true D with no closure-level cap;
        // firefly control belongs at the integrator, raytracer.h
        // clampDirect/clampIndirect). roughReflectionEval (this file, a few
        // functions above) was never given this cap; only the transmission
        // twin was, inconsistently. See
        // .astroray_plan/docs/pkg154-furnace-deficit-findings.md.
        result = clampColor(result);
        return result;
    }

    // VNDF PDF including half-vector Jacobian (PBRT-v4 DielectricBxDF::PDF).
    float vndfPdf(const Vec3& rec_normal, const Vec3& wo, const Vec3& wm) const {
        float absCosO = std::abs(wo.dot(rec_normal));
        if (absCosO <= 1e-10f) return 0.0f;
        float HdotO = std::abs(wo.dot(wm));
        float NdotH = std::abs(wm.dot(rec_normal));
        if (HdotO <= 1e-10f || NdotH <= 1e-10f) return 0.0f;

        float alpha = std::max(roughness_ * roughness_, 0.0064f);
        float D = D_GTR2(NdotH, alpha);
        float G1 = smithG1_GGX(absCosO, alpha);
        // PBRT-v4: VNDF PDF = D(wo, wm) = G1(wo) / absCosO * D(wm) * absDot(wo, wm)
        return G1 / absCosO * D * HdotO;
    }

    float roughTransmissionPdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        float cosO = rec.normal.dot(wo);
        float cosI = rec.normal.dot(wi);
        if (cosO == 0.0f || cosI == 0.0f || cosO * cosI >= 0.0f) return 0.0f;

        // pkg154: mirrors roughTransmissionEval's fix -- entering/exiting MUST
        // come from rec.frontFace, not the sign of cosO (see the comment
        // there). Keeps the half-vector reconstruction (wm = wi*etap + wo)
        // and Fresnel/Jacobian terms consistent with the same event's eval().
        bool entering = rec.frontFace;
        float etap = entering ? ior_ : (1.0f / ior_);
        Vec3 wm = (wi * etap + wo).normalized();
        if (wm.length2() <= 1e-10f) return 0.0f;
        if (wm.dot(rec.normal) < 0.0f) wm = -wm;

        float HdotO = wo.dot(wm);
        float HdotI = wi.dot(wm);
        if (HdotO * HdotI >= 0.0f) return 0.0f;

        // PBRT-v4: dwm_dwi Jacobian
        float denom = (HdotI + HdotO / etap);
        float denom2 = denom * denom;
        if (denom2 <= 1e-10f) return 0.0f;
        float dwm_dwi = std::abs(HdotI) / denom2;

        // VNDF PDF * Jacobian * transmission probability
        float etaI = entering ? 1.0f : ior_;
        float etaT = entering ? ior_ : 1.0f;
        float F = fresnelDielectric(std::abs(HdotO), etaI, etaT);
        return transmission_ * (1.0f - F) * vndfPdf(rec.normal, wo, wm) * dwm_dwi;
    }

public:
    explicit DisneyPlugin(const astroray::ParamDict& p)
        : baseColor_(p.getVec3("albedo", Vec3(0.8f))),
          metallic_(std::clamp(p.getFloat("metallic", 0.0f), 0.0f, 1.0f)),
          roughness_(std::clamp(p.getFloat("roughness", 0.5f), 0.001f, 1.0f)),
          anisotropic_(std::clamp(p.getFloat("anisotropic", 0.0f), 0.0f, 1.0f)),
          anisotropicRotation_(p.getFloat("anisotropic_rotation", 0.0f)),
          subsurface_(std::clamp(p.getFloat("subsurface", 0.0f), 0.0f, 1.0f)),
          specular_(std::clamp(p.getFloat("specular", 0.5f), 0.0f, 1.0f)),
          specularTint_(std::clamp(p.getFloat("specular_tint", 0.0f), 0.0f, 1.0f)),
          clearcoat_(std::clamp(p.getFloat("clearcoat", 0.0f), 0.0f, 1.0f)),
          clearcoatGloss_(std::clamp(p.getFloat("clearcoat_gloss", 1.0f), 0.0f, 1.0f)),
          sheen_(std::clamp(p.getFloat("sheen", 0.0f), 0.0f, 1.0f)),
          sheenTint_(std::clamp(p.getFloat("sheen_tint", 0.5f), 0.0f, 1.0f)),
          transmission_(std::clamp(p.getFloat("transmission", 0.0f), 0.0f, 1.0f)),
          ior_(std::max(1.0f, p.getFloat("ior", 1.5f))) {}

    Vec3 getAlbedo() const override { return baseColor_; }
    std::string getGPUTypeName() const override { return "disney"; }
    astroray::MaterialClosureGraph closureGraph() const override {
        astroray::MaterialClosureGraph graph;
        const astroray::ClosureColor base{baseColor_.x, baseColor_.y, baseColor_.z};
        const float diffuseWeight = (1.0f - metallic_) * (1.0f - transmission_);
        if (diffuseWeight > 1e-4f) {
            graph.add(astroray::makeDiffuseClosure(base, diffuseWeight));
        }
        const float conductorWeight = transmission_ < 0.999f ? 1.0f : 0.0f;
        if (conductorWeight > 1e-4f) {
            graph.add(astroray::makeGGXConductorClosure(base, roughness_, conductorWeight));
        }
        if (transmission_ > 1e-4f) {
            graph.add(astroray::makeDielectricTransmissionClosure(
                base, ior_, roughness_, transmission_, transmission_));
        }
        if (graph.empty()) {
            graph.add(astroray::makeDiffuseClosure(base, 1.0f));
        }
        return graph;
    }
    MaterialBackendCapabilities backendCapabilities() const override {
        MaterialBackendCapabilities caps;
        caps.gpu = true;
        caps.gpuSpectral = true;
        caps.gpuApproximate = true;
        caps.closureGraph = true;
        caps.gpuType = "closure_graph";
        caps.notes = "spectral Disney closure-graph GPU lowering; advanced Disney lobes remain approximated";
        return caps;
    }
    float getRoughness() const override { return roughness_; }
    float getMetallic() const override { return metallic_; }
    float getIOR() const override { return ior_; }
    float getTransmission() const override { return transmission_; }
    float getClearcoat() const override { return clearcoat_; }
    float getClearcoatGloss() const override { return clearcoatGloss_; }
    float getSpecular() const override { return specular_; }
    float getSpecularTint() const override { return specularTint_; }
    float getSheen() const override { return sheen_; }
    float getSheenTint() const override { return sheenTint_; }
    float getSubsurface() const override { return subsurface_; }
    float getAnisotropic() const override { return anisotropic_; }
    float getAnisotropicRotation() const override { return anisotropicRotation_; }

    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const {
        Vec3 N = rec.normal;
        float NdotL = N.dot(wi);
        float NdotV = N.dot(wo);
        if (transmission_ > 0.0f && roughness_ > kDeltaTransmissionRoughness && NdotL * NdotV < 0.0f) {
            return roughTransmissionEval(rec, wo, wi);
        }
        if (NdotL <= 0 || NdotV <= 0) return Vec3(0);

        Vec3 H = (wi + wo).normalized();
        float NdotH = N.dot(H);
        float LdotH = wi.dot(H);

        Vec3 Cdlin = baseColor_;
        float Cdlum = luminance(Cdlin);
        Vec3 Ctint = Cdlum > 0 ? Cdlin / Cdlum : Vec3(1);
        Vec3 Cspec0 = Vec3(specular_ * 0.08f) * (Vec3(1) * (1 - specularTint_) + Ctint * specularTint_);
        Vec3 F0 = Cspec0 * (1 - metallic_) + Cdlin * metallic_;
        F0 = Vec3::min(F0, Vec3(1));

        float FL = std::pow(1 - NdotL, 5);
        float FV = std::pow(1 - NdotV, 5);
        float Fd90 = 0.5f + 2 * LdotH * LdotH * roughness_;
        float Fd = (1 + (Fd90 - 1) * FL) * (1 + (Fd90 - 1) * FV);
        // pkg108 BUG-16 fix: Burley 2012 Hanrahan-Krueger subsurface
        // approximation. The subsurface_ parameter was previously parsed,
        // stored, and exposed via getSubsurface() but never used in eval(),
        // so toggling subsurface produced bit-identical renders.
        // Burley 2012 "Physically-Based Shading at Disney" §5.3
        // (Hanrahan-Krueger subsurface BRDF approximation).
        float Fss90 = LdotH * LdotH * roughness_;
        float Fss = (1 + (Fss90 - 1) * FL) * (1 + (Fss90 - 1) * FV);
        float ss = 1.25f * (Fss * (1.0f / std::max(NdotL + NdotV, 1e-4f) - 0.5f) + 0.5f);
        float FdMixed = (1.0f - subsurface_) * Fd + subsurface_ * ss;
        // pkg145 measurement (grid sweep, N=65536): a full removal of the
        // pkg60 grazing furnace normalization was tried first and rejected
        // by evidence — it fixes the roughness<=0.3 grazing set the
        // diffuse-under-specular coupling below targets, but *uncovers* a
        // much larger, distinct violation at roughness in {0.7, 0.9},
        // cos_theta_o=0.1 (measured worst 1.305 at roughness=0.9, vs. the
        // pre-removal 1.011 the furnace scale was keeping in check). That
        // defect is intrinsic to Burley 2015's diffuse retro-reflection term
        // at rough grazing incidence — orthogonal to the diffuse/specular
        // layering coupling: a rough dielectric's specular directional
        // albedo is small (low Fresnel reflectance, most of the lobe's
        // energy has decayed into the diffuse-dominated regime), so
        // `(1-specAlbedo)` barely attenuates diffuse there, leaving the
        // Burley term's own grazing-roughness excess unchecked. Kept as-is
        // (pkg60 fit) pending its own root-cause refit; the two mechanisms
        // are independent and both required.
        Vec3 diffuse = (1 / float(M_PI)) * Cdlin * FdMixed * diffuseFurnaceScale(roughness_, NdotV);

        float a = std::max(roughness_ * roughness_, 0.0064f);
        float Ds = D_GTR2(NdotH, a);
        float schlickScale = 0.8f + 0.2f * metallic_;
        Vec3 F = fresnelSchlick(LdotH, F0, schlickScale);
        float Gs = smithG_GGX(NdotL, a) * smithG_GGX(NdotV, a);
        Vec3 spec = Ds * F * Gs;

        // pkg138: blend in the rough dielectric reflection lobe. sample()'s
        // dielectric branch (roughness_ > kDeltaTransmissionRoughness) picks
        // this reflection direction with probability transmission_ (VNDF +
        // Fresnel-roulette reflect), and the complementary opaque plain-NDF
        // branch below with probability (1-transmission_) -- pdf() already
        // mixes its density by these exact weights (mixScale below,
        // transmission_*F*microfacetReflectionPdf). eval() must report the
        // same mixture, or the VNDF reflection candidate in sample() is
        // vetoed by the collapsed Cspec0 Schlick term instead of matching
        // pdf()'s continuous VNDF density. The (1-metallic_) factor mirrors
        // roughTransmissionEval's own scale (metallic materials don't
        // transmit). Smooth glass (roughness_<=kDeltaTransmissionRoughness)
        // is unaffected -- boundary preserved per spec.
        if (transmission_ > 0.0f && roughness_ > kDeltaTransmissionRoughness) {
            float dielectricWeight = (1.0f - metallic_) * transmission_;
            spec = spec * (1.0f - dielectricWeight) +
                   dielectricWeight * roughReflectionEval(rec, wo, wi);
        }

        Vec3 Csheen = Vec3(1) * (1 - sheenTint_) + Ctint * sheenTint_;
        Vec3 Fsheen = sheen_ * Csheen * std::pow(1 - LdotH, 5) * 0.5f;
        Vec3 lowerLayerWeight(1.0f);
        const auto& compensationTables = astroray::DisneyEnergyCompensationTables::instance();
        if (compensationTables.loaded() && sheen_ > 0.0f) {
            const float sheenAlbedo =
                compensationTables.sheenAlbedo(roughness_, NdotV) * sheen_;
            Fsheen *= sheenAlbedo;
            // Kulla & Conty 2017 Eq. 6-9 layering, using Cycles
            // src/kernel/svm/closure.h:208-211 and bsdf_sheen.h:40-51.
            lowerLayerWeight = layeringWeightAfter(lowerLayerWeight, Csheen * sheenAlbedo);
        }

        float Dr = D_GTR2(NdotH, clearcoatGloss_ * clearcoatGloss_);
        float Fr = 0.04f + (1 - 0.04f) * std::pow(1 - LdotH, 5);
        float Gr = smithG_GGX(NdotL, 0.25f) * smithG_GGX(NdotV, 0.25f);
        Vec3 clearcoatTerm = Vec3(clearcoat_ * Dr * Fr * Gr) * 0.25f;
        if (compensationTables.loaded() && clearcoat_ > 0.0f) {
            // pkg145 (absorbs pkg143/PR #508, superseded) — clearcoat fork,
            // decided against the grid sweep, not by assumption.
            //
            // The spec's "preferred" option (retire clearcoat_E.bin, route
            // coat through the same table_ggx_E/table_ggx_Eavg path as the
            // base specular) was tried and MEASURED to regress: Disney
            // 2012's clearcoat deliberately uses a FIXED G-term roughness of
            // 0.25 (`Gr` below) regardless of `clearcoatGloss_` (only `Dr`'s
            // shape varies with gloss) — an intentional simplification
            // ("visual impact is negligible", Burley 2012 §clearcoat).
            // `table_ggx_E` was precomputed assuming the SAME alpha drives
            // both D and G (a self-consistent GGX BRDF); querying it at
            // `roughness=clearcoatGloss_` does not describe a lobe whose
            // masking uses a different, fixed alpha=0.25. A Fresnel-at-view-
            // angle layering reduction built on top of that table lookup
            // was also tried and measured to over-attenuate the base layer
            // (worst-case grid reflectance fell to ~0.33, a new under-
            // conservation regression) and to erase the clearcoat's own
            // visible gloss contribution (`test_disney_clearcoat_adds_gloss`
            // regressed: p99.5 delta 0.001 -> 0.0005, below its gate).
            //
            // Kept: the ENTIRE original pkg60 mechanism unchanged (dedicated
            // `clearcoat_E.bin`, `min(1/clearE, 1.25)` clamp, and the
            // `clearcoat_*(1-clearE)` layering deduction) — measurement
            // showed clearcoat's own contribution to the quarantined
            // grazing-incidence overshoot was small (+0.003..0.01 across the
            // full clearcoat range at the worst dielectric config) relative
            // to the base diffuse/specular coupling below, which the full
            // grid sweep confirms is sufficient on its own: with the
            // diffuse-under-specular fix and this block fully untouched,
            // the complete 90-config x 3-angle grid measures <= 1.004
            // (N=65536; previously up to 1.2048 pre-fix), and the pkg123
            // clearcoat=1.0/roughness=0.3/cos=0.9 regression (measured
            // 1.0206 on `main`) now measures 0.947.
            const float clearE = std::max(compensationTables.clearcoatE(NdotV), 1e-4f);
            clearcoatTerm *= std::min(1.0f / clearE, 1.25f);
            lowerLayerWeight = layeringWeightAfter(
                lowerLayerWeight, Vec3(clearcoat_ * (1.0f - clearE)));
        }

        // Kulla & Conty 2017 Eq. 6-9 and Cycles
        // src/kernel/closure/bsdf_microfacet.h:389-436
        // (microfacet_ggx_preserve_energy): use the net
        // 1 + Fms * ((1 - E) / E) factor on the GGX lobe.
        spec *= ggxCompensationFactor(F0, roughness_, NdotV);

        // pkg145: diffuse-under-dielectric-specular layering. The dielectric
        // specular lobe sits ABOVE the diffuse base in the stack (sheen ->
        // coat -> specular -> diffuse); it must attenuate the diffuse layer
        // by its own directional albedo, the same way the sheen/coat layers
        // above already attenuate everything below them via
        // layeringWeightAfter. This is Cycles' `closure_layering_weight`
        // (kernel/closure/bsdf_util.h, Apache-2.0) applied one layer deeper,
        // equivalently the OpenPBR Surface spec's glossy-diffuse
        // non-reciprocal albedo-scaling approximation (Academy Software
        // Foundation, ASWF): f ~= f_specular + (1 - E_specular(wo))*f_diffuse
        // (Kulla & Conty 2017 lineage). Disney 2012's diffuse+specular sum is
        // otherwise uncoupled and over-shoots at grazing incidence: measured
        // at roughness=0.1, cos_theta_o=0.1 (worst quarantined config),
        // diffuse alone integrates to 0.73 and specular alone to 0.48 (naive
        // sum 1.20); with the coupling, 0.48 + (1-0.48)*0.73 = 0.86 <= 1.0.
        // The specular layer's own weight (lowerLayerWeight, unaffected by
        // its own albedo) is unchanged; only what sits below it is reduced.
        // Fresnel is evaluated AT THE VIEW ANGLE (NdotV) — same schlickScale
        // as the raw spec term above, matching Cycles' cos_NI convention —
        // not the material's normal-incidence F0, so the grazing Fresnel
        // rise (0.04 -> ~1.0 for a dielectric) is captured (measured
        // specAlbedo ~0.49 at roughness=0.1, cos_theta_o=0.1, close to the
        // 0.48 decomposition above; a constant-F0 estimate would floor near
        // 0.04 and under-attenuate diffuse by ~10x at grazing incidence).
        Vec3 Fview = fresnelSchlick(NdotV, F0, schlickScale);
        Vec3 specAlbedo = ggxDirectionalAlbedo(Fview, roughness_, NdotV);
        Vec3 diffuseLayerWeight = layeringWeightAfter(lowerLayerWeight, specAlbedo);

        Vec3 baseLayer = (1 - metallic_) * (1 - transmission_) * diffuse * diffuseLayerWeight +
                         spec * lowerLayerWeight;
        Vec3 result = (baseLayer + (1 - metallic_) * Fsheen + clearcoatTerm) * NdotL;

        return clampColor(result);
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const override {
        // pkg13 fallback: upsample final RGB Disney eval to stay within the pkg14 1.5x perf budget.
        Vec3 rgb = eval(rec, wo, wi);
        return astroray::RGBAlbedoSpectrum({rgb.x, rgb.y, rgb.z}).sample(lambdas);
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample s;
        s.wi = rec.normal;
        s.f = Vec3(0);
        s.pdf = 0.0f;
        s.isDelta = false;
        std::uniform_real_distribution<float> dist(0, 1);

        if (transmission_ > 0 && dist(gen) < transmission_) {
            float etaI = rec.frontFace ? 1.0f : ior_;
            float etaT = rec.frontFace ? ior_ : 1.0f;
            float eta = etaI / etaT;
            Vec3 n = rec.normal;
            float cosTheta = wo.dot(n);
            if (cosTheta < 0) { cosTheta = -cosTheta; n = -n; }

            float sinTheta = std::sqrt(std::max(0.0f, 1 - cosTheta * cosTheta));
            bool cannotRefract = eta * sinTheta > 1;

            float f0 = ((etaI - etaT) / (etaI + etaT));
            f0 = f0 * f0;
            float fresnel = f0 + (1 - f0) * std::pow(1 - cosTheta, 5);

            if (roughness_ > kDeltaTransmissionRoughness) {
                // Sample VNDF microfacet normal (Heitz 2018, PBRT-v4)
                Vec3 wm = sampleGgxVNDF(rec, wo, gen);
                float HdotO = wo.dot(wm);
                float F = fresnelDielectric(std::abs(HdotO), etaI, etaT);

                // Sample reflection or transmission based on Fresnel
                float R = F, T = 1.0f - F;
                bool sampleReflection = cannotRefract || dist(gen) < R / (R + T);

                if (sampleReflection) {
                    // Reflect off microfacet
                    s.wi = (wm * (2.0f * HdotO) - wo).normalized();
                    if (s.wi.dot(rec.normal) * wo.dot(rec.normal) > 0.0f) {
                        // Evaluate reflection (specular lobe contribution)
                        s.f = eval(rec, wo, s.wi);
                        // PDF = VNDF_PDF / (4 * |HdotO|) * R / (R + T)
                        float vndfPdfVal = vndfPdf(rec.normal, wo, wm);
                        s.pdf = transmission_ * vndfPdfVal / (4.0f * std::abs(HdotO) + 1e-10f) * R / (R + T + 1e-10f);
                    }
                } else {
                    // Refract through microfacet
                    if (refractThroughMicroNormal(wo, wm, eta, s.wi)) {
                        s.f = roughTransmissionEval(rec, wo, s.wi);
                        s.pdf = roughTransmissionPdf(rec, wo, s.wi);
                    }
                }

                if (s.pdf > 0.0f && s.f.length2() > 0.0f) {
                    s.isDelta = false;
                    const_cast<HitRecord&>(rec).isDelta = false;
                    return s;
                }
                // Extremely grazing sampled microfacets can fail both reflection
                // and refraction. Fall through to the smooth event instead of
                // treating that as absorption.
                //
                // pkg138 investigation note: a PBRT-v4-faithful "return a dead
                // (pdf=0) sample instead of this delta fallback" was tried and
                // MEASURED to regress energy conservation severely (white-furnace
                // collapsed from ~0.9-1.0 to ~0.0 at roughness in {0.1,0.3,0.6}
                // both CPU and GPU) -- the masked-VNDF-reflection dead-sample rate
                // measured here (100% at moderate roughness/incidence, not a rare
                // tail -- see the pkg138 research note) is NOT balanced by a
                // corresponding discount in this file's pdf()/microfacetReflectionPdf
                // (a full Smith joint-masking term or Turquin-style multiscatter
                // compensation would be needed first). Reverted; kept as the
                // pre-existing (if imperfect) energy-conserving behavior. See
                // .astroray_plan/docs/pkg138-disney-dielectric-rough-reflection-research.md.
            }

            if (cannotRefract || dist(gen) < fresnel) {
                s.wi = n * (2 * wo.dot(n)) - wo;
                s.f = Vec3(1);
                // pkg118 Part A: a forced-TIR reflection is deterministic (selection
                // probability 1), so pdf = transmission_; only a Fresnel-roulette-selected
                // reflection keeps the `fresnel` factor. PBRT-v4 §9.5 DielectricBxDF::Sample_f:
                // reflection pdf = pr/(pr+pt); for TIR pt=0 => pdf=1. The old
                // `fresnel * transmission_` over-counted forced-TIR throughput by ~1/fresnel
                // (~21x firefly that masked the single-scatter masking loss).
                s.pdf = (cannotRefract ? transmission_ : fresnel * transmission_);
            } else {
                Vec3 perp = (wo - n * cosTheta) * (-eta);
                Vec3 para = n * (-std::sqrt(std::abs(1 - perp.length2())));
                s.wi = (perp + para).normalized();
                s.f = baseColor_ * (eta * eta);
                s.pdf = (1 - fresnel) * transmission_;
            }
            // Smooth/failed rough samples use a delta glass event so spectral
            // paths do not evaluate the wrong side of the surface as opaque.
            s.isDelta = true;
            const_cast<HitRecord&>(rec).isDelta = true;
            return s;
        }

        float diffWeight = (1 - metallic_) * (1 - transmission_);
        float specWeight = 1;
        float total = diffWeight + specWeight;

        if (dist(gen) * total < diffWeight) {
            Vec3 localWi = Vec3::randomCosineDirection(gen);
            s.wi = rec.tangent * localWi.x + rec.bitangent * localWi.y + rec.normal * localWi.z;
            s.f = eval(rec, wo, s.wi);
            s.pdf = pdf(rec, wo, s.wi);
        } else {
            // Specular REFLECTION lobe: sample standard GGX NDF (matches the NDF
            // spec pdf in pdf() below, and the GPU non-transmission spec lobe). The
            // VNDF sampler is only paired with a matching VNDF pdf on the
            // transmission path — using it here against the NDF pdf was a
            // sample/pdf mismatch that darkened disney metal/specular reflection.
            float a = std::max(roughness_ * roughness_, 0.0064f);
            float r1 = dist(gen), r2 = dist(gen);
            float phi = 2.0f * float(M_PI) * r1;
            float cosTheta = std::sqrt((1.0f - r2) / (1.0f + (a * a - 1.0f) * r2));
            float sinTheta = std::sqrt(std::max(0.0f, 1.0f - cosTheta * cosTheta));
            Vec3 h(std::cos(phi) * sinTheta, std::sin(phi) * sinTheta, cosTheta);
            h = rec.tangent * h.x + rec.bitangent * h.y + rec.normal * h.z;
            s.wi = (h * (2.0f * wo.dot(h)) - wo).normalized();
            if (rec.normal.dot(s.wi) > 0) {
                s.f = eval(rec, wo, s.wi);
                s.pdf = pdf(rec, wo, s.wi);
            }
        }
        return s;
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        if (transmission_ > 0.0f && roughness_ > kDeltaTransmissionRoughness &&
            rec.normal.dot(wo) * rec.normal.dot(wi) < 0.0f) {
            return roughTransmissionPdf(rec, wo, wi);
        }

        Vec3 H = (wo + wi).normalized();
        float diffWeight = (1 - metallic_) * (1 - transmission_);
        float specWeight = 1;
        float total = diffWeight + specWeight;
        // The diffuse+plain-NDF-specular block below is only reached by sample()
        // when the top-level transmission roulette (line ~412:
        // `dist(gen) < transmission_`) selects the NON-transmissive branch —
        // probability (1 - transmission_). pdf() must gate this whole block by
        // that same factor, or it reports density for an event class sample()
        // has already excluded via the transmission branch. For transmission_=1.0
        // (pure glass) the plain-NDF specular branch is provably unreachable
        // (`dist(gen) < 1.0` is always true), yet the unscaled formula
        // unconditionally added its full pdf — a double-count against the VNDF
        // reflection term added below. Evidence: glass chi² (roughness=0.3)
        // measured PDF integral 1.951 (~2x over unity, exactly consistent with
        // one fully-duplicated reflection term).
        float mixScale = 1.0f - transmission_;
        float p = 0;
        if (diffWeight > 0) p += (rec.normal.dot(wi) / float(M_PI)) * (diffWeight / total) * mixScale;
        if (specWeight > 0) {
            float a = std::max(roughness_ * roughness_, 0.0064f);
            float NdotH = rec.normal.dot(H);
            float HdotV = H.dot(wo);
            if (NdotH > 0.0f && HdotV > 0.0f) {
                float D = D_GTR2(NdotH, a);
                // GGX reflection PDF: p(wi) = D(wm)·(wm·n) / (4·(wo·wm))
                // (Walter 2007 §5.3, pbrt-v4 §9.6 Eq. 9.24).
                p += (D * NdotH / (4.0f * HdotV)) * (specWeight / total) * mixScale;
            }
        }
        if (transmission_ > 0.0f && roughness_ > kDeltaTransmissionRoughness) {
            bool entering = rec.normal.dot(wo) > 0.0f;
            float etaI = entering ? 1.0f : ior_;
            float etaT = entering ? ior_ : 1.0f;
            // std::abs() matches sample()'s inline computation (disney.cpp ~431:
            // `fresnelDielectric(std::abs(HdotO), etaI, etaT)`) and is defensive
            // hardening against out-of-domain `wo.dot(H)` signs when `H` is
            // reconstructed from an arbitrary query wi (tabulate_pdf's quadrature
            // sweeps the full domain, not just plausible reflections). NOTE
            // (Opus re-review, 2026-07-20, measured on hardware): this is NOT the
            // root cause of the glass chi² residual (chi^2=143M/dof=1025 with the
            // fix present). The actual mechanism is a delta-vs-continuous
            // sample/pdf type mismatch -- see pkg121-disney-pdf-finding.md
            // "Round 2d" and the xfail reason on test_chi2_disney_glass. Kept as
            // harmless hardening, not claimed as a fix.
            float F = fresnelDielectric(std::abs(wo.dot(H)), etaI, etaT);
            p += transmission_ * F * microfacetReflectionPdf(rec, wo, wi);
        }
        return p;
    }
};

ASTRORAY_REGISTER_MATERIAL("disney", DisneyPlugin)

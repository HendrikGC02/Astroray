// Principled Hair BSDF (Chiang et al. 2016) — CPU material, pkg225 Stage 2.
// DOI:10.1145/2775280.2792559. Ported from pbrt-v3 src/materials/hair.cpp
// (BSD-2-Clause, Pharr/Jakob) for the Mp/Ap/Np/Sample_f math skeleton, with
// Cycles' parameter conventions (melanin coeffs, coat→R-roughness, alpha tilt)
// per intern/cycles/kernel/closure/bsdf_principled_hair_chiang.h + bsdf_util.h
// (Apache-2.0). Full derivation + pbrt-vs-Cycles divergence table:
// .astroray_plan/docs/pkg225-hair-bsdf-research.md.
//
// Convention: Astroray materials fold the cosine into eval()/sample.f (see
// Lambertian in raytracer.h — returns albedo*cos/pi), and the integrator does
// NOT re-apply it. pbrt's HairBSDF::f returns fsum/AbsCosTheta(wi), so the
// integrator's cosine cancels and the net is fsum. Hence eval() returns fsum
// directly. Frame is view-dependent (Cycles §5): X=tangent(uvTangent),
// Y=normalize(X×wo), Z=X×Y — rebuilt from wo in eval/sample/pdf.
#include "astroray/register.h"
#include "astroray/hair_bsdf.h"
#include "raytracer.h"
#include <cmath>

using namespace astroray::hair;

namespace {

// View-dependent hair frame: X=tangent, Y=normalize(X×wo), Z=X×Y.
struct HairFrame {
    Vec3 X, Y, Z;
    HairFrame(const Vec3& tangent, const Vec3& wo) {
        X = tangent.normalized();
        Vec3 y = X.cross(wo);
        if (y.length2() < 1e-12f) {          // wo ∥ tangent — pick any ⟂ axis
            Vec3 a = (std::abs(X.x) > 0.9f) ? Vec3(0, 1, 0) : Vec3(1, 0, 0);
            y = X.cross(a);
        }
        Y = y.normalized();
        Z = X.cross(Y);
    }
    void toLocal(const Vec3& d, float& sinTheta, float& phi) const {
        float lx = d.dot(X), ly = d.dot(Y), lz = d.dot(Z);
        sinTheta = std::min(1.0f, std::max(-1.0f, lx));
        phi = std::atan2(lz, ly);
    }
    Vec3 fromAngles(float sinThetaI, float cosThetaI, float phiI) const {
        return X * sinThetaI + Y * (cosThetaI * std::cos(phiI)) + Z * (cosThetaI * std::sin(phiI));
    }
};

}  // namespace

class PrincipledHairPlugin : public Material {
public:
    explicit PrincipledHairPlugin(const astroray::ParamDict& p) {
        betaM_ = std::clamp(p.getFloat("roughness", 0.3f), 1e-3f, 1.0f);
        betaN_ = std::clamp(p.getFloat("radial_roughness", 0.3f), 1e-3f, 1.0f);
        float coat = std::clamp(p.getFloat("coat", 0.0f), 0.0f, 1.0f);
        eta_ = p.getFloat("ior", 1.55f);
        float alpha = p.getFloat("offset", 2.0f * kPi / 180.0f);  // 2° default
        coat_ = coat;    // pkg225 Stage 4 — retained for GPU upload (hairGPUParams)
        alpha_ = alpha;

        // Longitudinal variances: R uses a coat-smoothed roughness (Cycles
        // m0_roughness = (1-coat) multiplier); TT/TRT/residual from base betaM.
        float vBase = longitudinalVariance(betaM_);
        v_[0] = longitudinalVariance(betaM_ * (1.0f - coat));  // R
        v_[1] = 0.25f * vBase;                                 // TT
        v_[2] = 4.0f * vBase;                                  // TRT
        v_[3] = 4.0f * vBase;                                  // residual
        s_ = azimuthalScale(betaN_);
        tilt_ = makeAlphaTilt(alpha);

        std::string mode = p.getString("parametrization", "reflectance");
        if (mode == "absorption" || mode == "direct_absorption") {
            sigmaA_ = p.getVec3("absorption_coefficient", Vec3(0.245531f, 0.52f, 1.365f));
        } else if (mode == "melanin" || mode == "pigment" || mode == "pigment_concentration") {
            float mel = std::clamp(p.getFloat("melanin", 0.8f), 0.0f, 1.0f);
            float redness = std::clamp(p.getFloat("melanin_redness", 1.0f), 0.0f, 1.0f);
            Vec3 tint = p.getVec3("tint", Vec3(1.0f));
            float m = -std::log(std::max(1.0f - mel, 1e-4f));  // perceptual remap
            float eu = m * (1.0f - redness), ph = m * redness;
            for (int c = 0; c < 3; ++c) {
                float ce, cp; melaninCoeffs(c, ce, cp);
                float tintSigma = sigmaAFromReflectanceChannel(tint[c], betaN_);
                (&sigmaA_.x)[c] = ce * eu + cp * ph + tintSigma;
            }
        } else {  // reflectance / direct coloring (node default)
            // The Blender node's "Color" socket maps to the material base color,
            // which createMaterial() routes into ParamDict "albedo". Prefer an
            // explicit "color" key, else fall back to the base color ("albedo").
            Vec3 color = p.getVec3("color", p.getVec3("albedo", Vec3(0.017513f, 0.005763f, 0.002059f)));
            for (int c = 0; c < 3; ++c)
                (&sigmaA_.x)[c] = sigmaAFromReflectanceChannel(color[c], betaN_);
        }
    }

    bool isGlossy() const override { return true; }
    bool isTransmissive() const override { return true; }
    float getIOR() const override { return eta_; }
    float getRoughness() const override { return betaM_; }

    // pkg225 Stage 4 — GPU lowering. getGPUTypeName() makes the default
    // backendCapabilities() advertise gpu/gpuSpectral; scene_upload tags the
    // GMaterial as GMAT_HAIR_PRINCIPLED and reads hairGPUParams() (the OWN
    // ctor-resolved sigma_a + roughness/tilt) so CPU/GPU are identical.
    std::string getGPUTypeName() const override { return "principled_hair"; }
    HairGPUParams hairGPUParams() const override {
        HairGPUParams h;
        h.isHair = true;
        h.betaM = betaM_;
        h.betaN = betaN_;
        h.eta = eta_;
        h.alpha = alpha_;
        h.coat = coat_;
        h.sigmaA = sigmaA_;
        return h;
    }
    Vec3 getAlbedo() const override {
        return Vec3(std::exp(-std::sqrt(std::max(0.0f, sigmaA_.x))),
                    std::exp(-std::sqrt(std::max(0.0f, sigmaA_.y))),
                    std::exp(-std::sqrt(std::max(0.0f, sigmaA_.z))));
    }

    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        if (rec.hair_v < 0.0f) return Vec3(0);
        Geom g = setup(rec, wo);
        float sinThetaI, phiI;
        g.frame.toLocal(wi, sinThetaI, phiI);
        float cosThetaI = safeSqrt(1.0f - sqr(sinThetaI));
        float phi = phiI - g.phiO;
        Vec3 out;
        for (int c = 0; c < 3; ++c)
            (&out.x)[c] = fChannel(g, (&sigmaA_.x)[c], sinThetaI, cosThetaI, phi);
        return out;
    }

    astroray::SampledSpectrum evalSpectral(
            const HitRecord& rec, const Vec3& wo, const Vec3& wi,
            const astroray::SampledWavelengths& lambdas) const override {
        if (rec.hair_v < 0.0f) return astroray::SampledSpectrum(0.0f);
        Geom g = setup(rec, wo);
        float sinThetaI, phiI;
        g.frame.toLocal(wi, sinThetaI, phiI);
        float cosThetaI = safeSqrt(1.0f - sqr(sinThetaI));
        float phi = phiI - g.phiO;
        astroray::SampledSpectrum out(0.0f);
        for (int i = 0; i < astroray::kSpectrumSamples; ++i)
            out[i] = fChannel(g, sigmaAAtLambda(lambdas.lambda(i)), sinThetaI, cosThetaI, phi);
        return out;
    }

    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override {
        if (rec.hair_v < 0.0f) return 0.0f;
        Geom g = setup(rec, wo);
        float sinThetaI, phiI;
        g.frame.toLocal(wi, sinThetaI, phiI);
        float cosThetaI = safeSqrt(1.0f - sqr(sinThetaI));
        float phi = phiI - g.phiO;
        return pdfCore(g, sinThetaI, cosThetaI, phi);
    }

    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override {
        BSDFSample bs{Vec3(0, 1, 0), Vec3(0), 0.0f, false};
        if (rec.hair_v < 0.0f) return bs;
        Vec3 wi = sampleDir(rec, wo, gen);
        bs.wi = wi;
        bs.f = eval(rec, wo, wi);
        bs.pdf = pdf(rec, wo, wi);
        if (bs.pdf <= 0.0f) { bs.f = Vec3(0); bs.pdf = 0.0f; }
        return bs;
    }

    // Override: the base sampleSpectral routes RGB f through the RGBAlbedo eta²
    // clamp (wrong for hair). Sample the direction, return spectral f directly.
    BSDFSampleSpectral sampleSpectral(
            const HitRecord& rec, const Vec3& wo, std::mt19937& gen,
            astroray::SampledWavelengths& lambdas) const override {
        BSDFSampleSpectral bss;
        bss.isDelta = false;
        if (rec.hair_v < 0.0f) { bss.wi = Vec3(0, 1, 0); bss.pdf = 0.0f; return bss; }
        Vec3 wi = sampleDir(rec, wo, gen);
        bss.wi = wi;
        bss.f_spectral = evalSpectral(rec, wo, wi, lambdas);
        bss.pdf = pdf(rec, wo, wi);
        if (bss.pdf <= 0.0f) { bss.f_spectral = astroray::SampledSpectrum(0.0f); bss.pdf = 0.0f; }
        return bss;
    }

private:
    struct Geom {
        HairFrame frame;
        float h, gammaO, gammaT;
        float sinThetaO, cosThetaO, phiO;
        float fFresnel, cosGammaT, cosThetaT;
    };

    Geom setup(const HitRecord& rec, const Vec3& wo) const {
        HairFrame frame(rec.uvTangent, wo);
        float sinThetaO, phiO;
        frame.toLocal(wo, sinThetaO, phiO);
        float cosThetaO = safeSqrt(1.0f - sqr(sinThetaO));
        float h = std::clamp(2.0f * rec.hair_v - 1.0f, -1.0f, 1.0f);
        float gammaO = safeAsin(h);
        float sinThetaT = sinThetaO / eta_;
        float cosThetaT = safeSqrt(1.0f - sqr(sinThetaT));
        float etap = safeSqrt(eta_ * eta_ - sqr(sinThetaO)) / std::max(cosThetaO, 1e-5f);
        float sinGammaT = h / etap;
        float cosGammaT = safeSqrt(1.0f - sqr(sinGammaT));
        float gammaT = safeAsin(sinGammaT);
        float cosGammaO = safeSqrt(1.0f - sqr(h));
        float fFresnel = frDielectric(cosThetaO * cosGammaO, 1.0f, eta_);
        return {frame, h, gammaO, gammaT, sinThetaO, cosThetaO, phiO, fFresnel, cosGammaT, cosThetaT};
    }

    float transmittance(float sigmaAChannel, const Geom& g) const {
        return std::exp(-sigmaAChannel * (2.0f * g.cosGammaT / std::max(g.cosThetaT, 1e-5f)));
    }

    float fChannel(const Geom& g, float sigmaAChannel,
                   float sinThetaI, float cosThetaI, float phi) const {
        float T = transmittance(sigmaAChannel, g);
        float ap[kPMax + 1];
        Ap(g.fFresnel, T, ap);
        float fc = 0.0f;
        for (int pp = 0; pp < kPMax; ++pp) {
            float sinThetaOp, cosThetaOp;
            tiltThetaO(tilt_, pp, g.sinThetaO, g.cosThetaO, sinThetaOp, cosThetaOp);
            cosThetaOp = std::abs(cosThetaOp);
            fc += Mp(cosThetaI, cosThetaOp, sinThetaI, sinThetaOp, v_[pp]) * ap[pp] *
                  Np(phi, pp, s_, g.gammaO, g.gammaT);
        }
        fc += Mp(cosThetaI, g.cosThetaO, sinThetaI, g.sinThetaO, v_[kPMax]) * ap[kPMax] *
              (1.0f / (2.0f * kPi));
        return fc;
    }

    void computeApPdf(const Geom& g, float apPdfArr[kPMax + 1]) const {
        float apLum[kPMax + 1] = {0, 0, 0, 0};
        for (int c = 0; c < 3; ++c) {
            float T = transmittance((&sigmaA_.x)[c], g);
            float ap[kPMax + 1];
            Ap(g.fFresnel, T, ap);
            for (int i = 0; i <= kPMax; ++i) apLum[i] += ap[i] * (1.0f / 3.0f);
        }
        apPdf(apLum, apPdfArr);
    }

    float pdfCore(const Geom& g, float sinThetaI, float cosThetaI, float phi) const {
        float apPdfArr[kPMax + 1];
        computeApPdf(g, apPdfArr);
        float pdfSum = 0.0f;
        for (int pp = 0; pp < kPMax; ++pp) {
            float sinThetaOp, cosThetaOp;
            tiltThetaO(tilt_, pp, g.sinThetaO, g.cosThetaO, sinThetaOp, cosThetaOp);
            cosThetaOp = std::abs(cosThetaOp);
            pdfSum += Mp(cosThetaI, cosThetaOp, sinThetaI, sinThetaOp, v_[pp]) *
                      apPdfArr[pp] * Np(phi, pp, s_, g.gammaO, g.gammaT);
        }
        pdfSum += Mp(cosThetaI, g.cosThetaO, sinThetaI, g.sinThetaO, v_[kPMax]) *
                  apPdfArr[kPMax] * (1.0f / (2.0f * kPi));
        return pdfSum;
    }

    Vec3 sampleDir(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const {
        Geom g = setup(rec, wo);
        std::uniform_real_distribution<float> U(0.0f, 1.0f);
        float apPdfArr[kPMax + 1];
        computeApPdf(g, apPdfArr);
        float up = U(gen), cdf = 0.0f;
        int p = kPMax;
        for (int i = 0; i <= kPMax; ++i) { cdf += apPdfArr[i]; if (up < cdf) { p = i; break; } }

        float sinThetaOp, cosThetaOp;
        tiltThetaO(tilt_, p, g.sinThetaO, g.cosThetaO, sinThetaOp, cosThetaOp);

        float u1x = std::max(U(gen), 1e-5f), u1y = U(gen);
        float cosTheta = 1.0f + v_[p] * std::log(u1x + (1.0f - u1x) * std::exp(-2.0f / v_[p]));
        float sinTheta = safeSqrt(1.0f - sqr(cosTheta));
        float cosPhi = std::cos(2.0f * kPi * u1y);
        float sinThetaI = -cosTheta * sinThetaOp + sinTheta * cosPhi * cosThetaOp;
        float cosThetaI = safeSqrt(1.0f - sqr(sinThetaI));

        float dphi;
        if (p < kPMax)
            dphi = deltaPhi(p, g.gammaO, g.gammaT) + sampleTrimmedLogistic(U(gen), s_, -kPi, kPi);
        else
            dphi = 2.0f * kPi * U(gen);
        float phiI = g.phiO + dphi;
        return g.frame.fromAngles(sinThetaI, cosThetaI, phiI).normalized();
    }

    // Spectral sigma_a: piecewise-linear upsample of the RGB absorption over the
    // 3 primaries' representative wavelengths. Stage-5 replaces this with a true
    // melanin cross-section (the sigmaA function boundary is the seam).
    float sigmaAAtLambda(float lambda) const {
        if (lambda <= 450.0f) return sigmaA_.z;
        if (lambda >= 600.0f) return sigmaA_.x;
        if (lambda < 550.0f) { float t = (lambda - 450.0f) / 100.0f; return sigmaA_.z * (1 - t) + sigmaA_.y * t; }
        float t = (lambda - 550.0f) / 50.0f; return sigmaA_.y * (1 - t) + sigmaA_.x * t;
    }

    float betaM_, betaN_, eta_, s_;
    float alpha_ = 0.0349f, coat_ = 0.0f;  // pkg225 Stage 4 — GPU-upload retained
    float v_[kPMax + 1];
    AlphaTilt tilt_;
    Vec3 sigmaA_;
};

ASTRORAY_REGISTER_MATERIAL("principled_hair", PrincipledHairPlugin)

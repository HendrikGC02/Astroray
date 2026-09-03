#pragma once
// pkg225 Stage 4 — GPU Principled Hair BSDF (Chiang 2016).
//
// Device twin of plugins/materials/principled_hair.cpp. Reuses the EXACT shared
// math in include/astroray/hair_bsdf.h (Mp/Np/Ap/logistic/Fresnel + sigma_a),
// so CPU/GPU parity is by construction — this file only ports the GVec3 frame
// setup, the per-hit (v,s,tilt) precompute (recomputed from the packed GMaterial
// fields), the RGB/spectral channel loop, and the lobe sampler.
//
// REGISTER DISCIPLINE (Claude-last-line, memory noinline-runtime-flag-avoids-
// shade-spill / wavefront-shade-kernels-register-saturated): the hair BSDF is
// transcendental-heavy (Bessel-I0/sinh/log/atan2/pow per lobe) and hair is a
// whole-scene property. The dispatch ENTRY points below are __device__
// __noinline__ so their register pressure lives in their OWN frames, NOT in the
// REG:254-pinned stageShadeBucketedKernel. A non-hair scene never reaches them
// (mat.type gate), and the SoA uvTangent/hairV restore that feeds them is gated
// by the runtime __constant__ c_hasHair flag in stage_advance.cu. NOT a 9th
// template axis (architect-pinned; the shade kernel already carries 8).
//
// Param packing (GMaterial stays EXACTLY 640 B — no new field; see gpu_types.h
// GImageTexture note): a GMAT_HAIR_PRINCIPLED material reuses existing scalar
// fields, filled by scene_upload.cu from Material::hairGPUParams() (which returns
// the CPU plugin's OWN precomputed values, so all three sigma_a parametrizations
// are already resolved host-side, matching the CPU ctor):
//   baseColor      = sigma_a (RGB absorption coefficient)
//   roughness      = beta_m  (longitudinal roughness)
//   clearcoatGloss = beta_n  (radial/azimuthal roughness)
//   transmission   = coat    (Cycles Coat -> R-lobe m0_roughness)
//   clearcoat      = alpha   (cuticle tilt, radians)
//   ior            = eta     (1.55 keratin)

#include "gpu_types.h"
#include "hair_bsdf.h"
#include "hair_melanin_spectral.h"

namespace astroray_gpu_hair {

namespace ah = astroray::hair;

// View-dependent hair frame (Cycles §5 / principled_hair.cpp HairFrame):
// X = strand tangent, Y = normalize(X x wo), Z = X x Y. Rebuilt from wo each
// call — the frame genuinely depends on the view.
struct GHairFrame {
    GVec3 X, Y, Z;
    __device__ GHairFrame(const GVec3& tangent, const GVec3& wo) {
        X = tangent.normalized();
        GVec3 y = X.cross(wo);
        if (y.length2() < 1e-12f) {                 // wo || tangent: any perp axis
            GVec3 a = (fabsf(X.x) > 0.9f) ? GVec3(0.f, 1.f, 0.f) : GVec3(1.f, 0.f, 0.f);
            y = X.cross(a);
        }
        Y = y.normalized();
        Z = X.cross(Y);
    }
    __device__ void toLocal(const GVec3& d, float& sinTheta, float& phi) const {
        float lx = d.dot(X), ly = d.dot(Y), lz = d.dot(Z);
        sinTheta = fminf(1.f, fmaxf(-1.f, lx));
        phi = atan2f(lz, ly);
    }
    __device__ GVec3 fromAngles(float sinThetaI, float cosThetaI, float phiI) const {
        return X * sinThetaI + Y * (cosThetaI * cosf(phiI)) + Z * (cosThetaI * sinf(phiI));
    }
};

// Per-material precompute recomputed once per hit inside the __noinline__ entry
// (mirrors the CPU ctor: v_[0..3], s_, tilt_, sigmaA_ from the packed fields).
struct GHairMat {
    float eta;
    float v[ah::kPMax + 1];
    float s;
    ah::AlphaTilt tilt;
    GVec3 sigmaA;
    // pkg225 Stage 5 — spectral melanin (rides hair-unused GMaterial scalars so
    // GMaterial stays EXACTLY 640 B): specular=melaninMode flag, metallic=eu,
    // subsurface=ph. RGB path & non-melanin modes untouched (sigmaA carries them).
    bool  melaninMode;
    float eu, ph;
};

__device__ inline GHairMat gpu_hair_unpack(const GMaterial& mat) {
    GHairMat m;
    float betaM = fminf(fmaxf(mat.roughness, 1e-3f), 1.0f);
    float betaN = fminf(fmaxf(mat.clearcoatGloss, 1e-3f), 1.0f);
    float coat  = fminf(fmaxf(mat.transmission, 0.0f), 1.0f);
    float alpha = mat.clearcoat;
    m.eta = mat.ior;
    float vBase = ah::longitudinalVariance(betaM);
    m.v[0] = ah::longitudinalVariance(betaM * (1.0f - coat));  // R (coat-smoothed)
    m.v[1] = 0.25f * vBase;                                    // TT
    m.v[2] = 4.0f * vBase;                                     // TRT
    m.v[3] = 4.0f * vBase;                                     // residual
    m.s = ah::azimuthalScale(betaN);
    m.tilt = ah::makeAlphaTilt(alpha);
    m.sigmaA = mat.baseColor;
    m.melaninMode = (mat.specular > 0.5f);  // pkg225 Stage 5
    m.eu = mat.metallic;
    m.ph = mat.subsurface;
    return m;
}

// Fiber geometry at the hit (principled_hair.cpp Geom / setup()).
struct GHairGeom {
    GHairFrame frame;
    float gammaO, gammaT;
    float sinThetaO, cosThetaO, phiO;
    float fFresnel, cosGammaT, cosThetaT;
};

__device__ inline GHairGeom gpu_hair_setup(const GHairMat& m, const GHitRecord& rec,
                                           const GVec3& wo) {
    GHairFrame frame(rec.uvTangent, wo);
    float sinThetaO, phiO;
    frame.toLocal(wo, sinThetaO, phiO);
    float cosThetaO = ah::safeSqrt(1.0f - ah::sqr(sinThetaO));
    float h = fminf(fmaxf(2.0f * rec.hairV - 1.0f, -1.0f), 1.0f);
    float gammaO = ah::safeAsin(h);
    float sinThetaT = sinThetaO / m.eta;
    float cosThetaT = ah::safeSqrt(1.0f - ah::sqr(sinThetaT));
    float etap = ah::safeSqrt(m.eta * m.eta - ah::sqr(sinThetaO)) / fmaxf(cosThetaO, 1e-5f);
    float sinGammaT = h / etap;
    float cosGammaT = ah::safeSqrt(1.0f - ah::sqr(sinGammaT));
    float gammaT = ah::safeAsin(sinGammaT);
    float cosGammaO = ah::safeSqrt(1.0f - ah::sqr(h));
    float fFresnel = ah::frDielectric(cosThetaO * cosGammaO, 1.0f, m.eta);
    GHairGeom g{frame, gammaO, gammaT, sinThetaO, cosThetaO, phiO, fFresnel, cosGammaT, cosThetaT};
    return g;
}

__device__ inline float gpu_hair_transmittance(float sigmaAChannel, const GHairGeom& g) {
    return expf(-sigmaAChannel * (2.0f * g.cosGammaT / fmaxf(g.cosThetaT, 1e-5f)));
}

// Single-channel BSDF value (principled_hair.cpp fChannel()).
__device__ inline float gpu_hair_fChannel(const GHairMat& m, const GHairGeom& g,
                                          float sigmaAChannel, float sinThetaI,
                                          float cosThetaI, float phi) {
    float T = gpu_hair_transmittance(sigmaAChannel, g);
    float ap[ah::kPMax + 1];
    ah::Ap(g.fFresnel, T, ap);
    float fc = 0.0f;
    for (int pp = 0; pp < ah::kPMax; ++pp) {
        float sinThetaOp, cosThetaOp;
        ah::tiltThetaO(m.tilt, pp, g.sinThetaO, g.cosThetaO, sinThetaOp, cosThetaOp);
        cosThetaOp = fabsf(cosThetaOp);
        fc += ah::Mp(cosThetaI, cosThetaOp, sinThetaI, sinThetaOp, m.v[pp]) * ap[pp] *
              ah::Np(phi, pp, m.s, g.gammaO, g.gammaT);
    }
    fc += ah::Mp(cosThetaI, g.cosThetaO, sinThetaI, g.sinThetaO, m.v[ah::kPMax]) *
          ap[ah::kPMax] * (1.0f / (2.0f * ah::kPi));
    return fc;
}

__device__ inline void gpu_hair_computeApPdf(const GHairMat& m, const GHairGeom& g,
                                             float apPdfArr[ah::kPMax + 1]) {
    float apLum[ah::kPMax + 1] = {0, 0, 0, 0};
    for (int c = 0; c < 3; ++c) {
        float T = gpu_hair_transmittance(m.sigmaA[c], g);
        float ap[ah::kPMax + 1];
        ah::Ap(g.fFresnel, T, ap);
        for (int i = 0; i <= ah::kPMax; ++i) apLum[i] += ap[i] * (1.0f / 3.0f);
    }
    ah::apPdf(apLum, apPdfArr);
}

__device__ inline float gpu_hair_pdfCore(const GHairMat& m, const GHairGeom& g,
                                         float sinThetaI, float cosThetaI, float phi) {
    float apPdfArr[ah::kPMax + 1];
    gpu_hair_computeApPdf(m, g, apPdfArr);
    float pdfSum = 0.0f;
    for (int pp = 0; pp < ah::kPMax; ++pp) {
        float sinThetaOp, cosThetaOp;
        ah::tiltThetaO(m.tilt, pp, g.sinThetaO, g.cosThetaO, sinThetaOp, cosThetaOp);
        cosThetaOp = fabsf(cosThetaOp);
        pdfSum += ah::Mp(cosThetaI, cosThetaOp, sinThetaI, sinThetaOp, m.v[pp]) *
                  apPdfArr[pp] * ah::Np(phi, pp, m.s, g.gammaO, g.gammaT);
    }
    pdfSum += ah::Mp(cosThetaI, g.cosThetaO, sinThetaI, g.sinThetaO, m.v[ah::kPMax]) *
              apPdfArr[ah::kPMax] * (1.0f / (2.0f * ah::kPi));
    return pdfSum;
}

// Spectral sigma_a — the Stage-5 seam, byte-parallel to principled_hair.cpp
// sigmaAAtLambda(). In melanin mode, evaluate the physical eu/ph cross-section
// per wavelength directly (hair_melanin_spectral.h); otherwise piecewise-linear
// upsample the RGB absorption (reflectance / direct-absorption modes).
__device__ inline float gpu_hair_sigmaAAtLambda(const GHairMat& m, float lambda) {
    if (m.melaninMode)
        return ah::melaninSigmaAtLambda(m.eu, m.ph, lambda);
    const GVec3& sigmaA = m.sigmaA;
    if (lambda <= 450.0f) return sigmaA.z;
    if (lambda >= 600.0f) return sigmaA.x;
    if (lambda < 550.0f) { float t = (lambda - 450.0f) / 100.0f; return sigmaA.z * (1 - t) + sigmaA.y * t; }
    float t = (lambda - 550.0f) / 50.0f; return sigmaA.y * (1 - t) + sigmaA.x * t;
}

// Sample an incoming direction (principled_hair.cpp sampleDir()). Templated on
// the RNG type (curandState in the megakernel, WavefrontRNG in the wavefront),
// matching gpu_material_sample_spectral's convention.
template <typename TRng>
__device__ inline GVec3 gpu_hair_sampleDir(const GHairMat& m, const GHairGeom& g,
                                           const GVec3& /*wo*/, TRng* rng) {
    float apPdfArr[ah::kPMax + 1];
    gpu_hair_computeApPdf(m, g, apPdfArr);
    float up = gpu_rng_uniform(rng), cdf = 0.0f;
    int p = ah::kPMax;
    for (int i = 0; i <= ah::kPMax; ++i) { cdf += apPdfArr[i]; if (up < cdf) { p = i; break; } }

    float sinThetaOp, cosThetaOp;
    ah::tiltThetaO(m.tilt, p, g.sinThetaO, g.cosThetaO, sinThetaOp, cosThetaOp);

    float u1x = fmaxf(gpu_rng_uniform(rng), 1e-5f), u1y = gpu_rng_uniform(rng);
    float cosTheta = 1.0f + m.v[p] * logf(u1x + (1.0f - u1x) * expf(-2.0f / m.v[p]));
    float sinTheta = ah::safeSqrt(1.0f - ah::sqr(cosTheta));
    float cosPhi = cosf(2.0f * ah::kPi * u1y);
    float sinThetaI = -cosTheta * sinThetaOp + sinTheta * cosPhi * cosThetaOp;
    float cosThetaI = ah::safeSqrt(1.0f - ah::sqr(sinThetaI));

    float dphi;
    if (p < ah::kPMax)
        dphi = ah::deltaPhi(p, g.gammaO, g.gammaT) +
               ah::sampleTrimmedLogistic(gpu_rng_uniform(rng), m.s, -ah::kPi, ah::kPi);
    else
        dphi = 2.0f * ah::kPi * gpu_rng_uniform(rng);
    float phiI = g.phiO + dphi;
    return g.frame.fromAngles(sinThetaI, cosThetaI, phiI).normalized();
}

// ===========================================================================
//  Dispatch entry points — __noinline__ so their transcendental register
//  pressure stays OUT of the REG:254 fleet shade kernel (see file header).
// ===========================================================================

__device__ __noinline__ inline GVec3 gpu_hair_eval(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi) {
    if (rec.hairV < 0.0f) return GVec3(0.f);
    GHairMat m = gpu_hair_unpack(mat);
    GHairGeom g = gpu_hair_setup(m, rec, wo);
    float sinThetaI, phiI;
    g.frame.toLocal(wi, sinThetaI, phiI);
    float cosThetaI = ah::safeSqrt(1.0f - ah::sqr(sinThetaI));
    float phi = phiI - g.phiO;
    GVec3 out;
    for (int c = 0; c < 3; ++c)
        out[c] = gpu_hair_fChannel(m, g, m.sigmaA[c], sinThetaI, cosThetaI, phi);
    return out;
}

__device__ __noinline__ inline GSampledSpectrum gpu_hair_eval_spectral(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi,
    const GSampledWavelengths& wl) {
    GSampledSpectrum out(0.f);
    if (rec.hairV < 0.0f) return out;
    GHairMat m = gpu_hair_unpack(mat);
    GHairGeom g = gpu_hair_setup(m, rec, wo);
    float sinThetaI, phiI;
    g.frame.toLocal(wi, sinThetaI, phiI);
    float cosThetaI = ah::safeSqrt(1.0f - ah::sqr(sinThetaI));
    float phi = phiI - g.phiO;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
        out[i] = gpu_hair_fChannel(m, g, gpu_hair_sigmaAAtLambda(m, wl.lambda[i]),
                                   sinThetaI, cosThetaI, phi);
    return out;
}

__device__ __noinline__ inline float gpu_hair_pdf(
    const GMaterial& mat, const GHitRecord& rec, const GVec3& wo, const GVec3& wi) {
    if (rec.hairV < 0.0f) return 0.0f;
    GHairMat m = gpu_hair_unpack(mat);
    GHairGeom g = gpu_hair_setup(m, rec, wo);
    float sinThetaI, phiI;
    g.frame.toLocal(wi, sinThetaI, phiI);
    float cosThetaI = ah::safeSqrt(1.0f - ah::sqr(sinThetaI));
    float phi = phiI - g.phiO;
    return gpu_hair_pdfCore(m, g, sinThetaI, cosThetaI, phi);
}

// RGB sample (megakernel / non-spectral path). Mirrors the CPU sample(): pick a
// direction, return the RGB f + model pdf. The wavefront uses the spectral
// sampler below; this keeps the material switch complete so a hair material never
// falls through to the black default.
template <typename TRng>
__device__ __noinline__ inline GBSDFSample gpu_hair_sample(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo, TRng* rng) {
    GBSDFSample s;
    s.isDelta = false;
    s.f = GVec3(0.f);
    s.fSpectral = GSampledSpectrum(0.f);
    s.wi = GVec3(0.f, 1.f, 0.f);
    s.pdf = 0.0f;
    if (rec.hairV < 0.0f) return s;
    GHairMat m = gpu_hair_unpack(mat);
    GHairGeom g = gpu_hair_setup(m, rec, wo);
    GVec3 wi = gpu_hair_sampleDir(m, g, wo, rng);
    s.wi = wi;
    float sinThetaI, phiI;
    g.frame.toLocal(wi, sinThetaI, phiI);
    float cosThetaI = ah::safeSqrt(1.0f - ah::sqr(sinThetaI));
    float phi = phiI - g.phiO;
    float pdf = gpu_hair_pdfCore(m, g, sinThetaI, cosThetaI, phi);
    if (pdf <= 0.0f) return s;
    s.pdf = pdf;
    for (int c = 0; c < 3; ++c)
        s.f[c] = gpu_hair_fChannel(m, g, m.sigmaA[c], sinThetaI, cosThetaI, phi);
    return s;
}

// Spectral sample: pick a direction, return f_spectral directly (mirrors the CPU
// sampleSpectral override — do NOT route through the RGBAlbedo eta^2 clamp).
template <typename TRng>
__device__ __noinline__ inline GBSDFSample gpu_hair_sample_spectral(
    const GMaterial& mat, GHitRecord& rec, const GVec3& wo,
    GSampledWavelengths& wl, TRng* rng) {
    GBSDFSample s;
    s.isDelta = false;
    s.f = GVec3(0.f);
    s.fSpectral = GSampledSpectrum(0.f);
    s.wi = GVec3(0.f, 1.f, 0.f);
    s.pdf = 0.0f;
    if (rec.hairV < 0.0f) return s;
    GHairMat m = gpu_hair_unpack(mat);
    GHairGeom g = gpu_hair_setup(m, rec, wo);
    GVec3 wi = gpu_hair_sampleDir(m, g, wo, rng);
    s.wi = wi;
    // Evaluate pdf + f at the sampled wi (frame already built in g).
    float sinThetaI, phiI;
    g.frame.toLocal(wi, sinThetaI, phiI);
    float cosThetaI = ah::safeSqrt(1.0f - ah::sqr(sinThetaI));
    float phi = phiI - g.phiO;
    float pdf = gpu_hair_pdfCore(m, g, sinThetaI, cosThetaI, phi);
    if (pdf <= 0.0f) return s;
    s.pdf = pdf;
    GVec3 fRGB;
    for (int c = 0; c < 3; ++c)
        fRGB[c] = gpu_hair_fChannel(m, g, m.sigmaA[c], sinThetaI, cosThetaI, phi);
    s.f = fRGB;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
        s.fSpectral[i] = gpu_hair_fChannel(m, g, gpu_hair_sigmaAAtLambda(m, wl.lambda[i]),
                                           sinThetaI, cosThetaI, phi);
    return s;
}

}  // namespace astroray_gpu_hair

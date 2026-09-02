#pragma once
// Principled Hair BSDF — Chiang et al. 2016, "A Practical and Controllable Hair
// and Fur Model for Production Path Tracing", CGF 35(2). DOI:10.1145/2775280.2792559.
// Built on Marschner 2003 (DOI:10.1145/882262.882345) + d'Eon 2011
// (DOI:10.1111/j.1467-8659.2011.01976.x).
//
// Reference impl (primary, cross-checked): pbrt-v3 src/materials/hair.cpp,
//   BSD-2-Clause (Pharr/Jakob) — textbook Chiang form (pbrt §9.9 "Hair"); the
//   Mp/Ap/Np/Logistic/I0/Phi math below is ported from it verbatim in structure.
// Reference impl (parameter plumbing): Blender Cycles @main —
//   intern/cycles/kernel/closure/bsdf_principled_hair_chiang.h (roughness/coat
//   remap, hair_alpha_angles), intern/cycles/kernel/closure/bsdf_util.h
//   (sigma_from_{concentration,reflectance}), Apache-2.0 — compatible with MIT.
// Per-function math notes + pbrt-vs-Cycles divergence table:
//   .astroray_plan/docs/pkg225-hair-bsdf-research.md
//
// Header-only, STL-free in the hot path (raw arrays), so the Stage 3/4 GPU leg
// can #include the same functions into a .cuh unchanged. CPU-only for Stage 2.
#include "astroray/spectrum.h"
#include <cmath>
#include <algorithm>
#include <utility>

namespace astroray {
namespace hair {

// Number of scattering lobes tracked explicitly: R(0), TT(1), TRT(2) + a
// residual TRRT+ geometric tail at index pMax=3. (pbrt hair.cpp pMax=3.)
static constexpr int kPMax = 3;
static constexpr float kPi   = 3.14159265358979323846f;
static constexpr float kSqrtPiOver8 = 0.626657069f;  // sqrt(pi/8)

static inline float sqr(float v) { return v * v; }
static inline float safeSqrt(float v) { return std::sqrt(std::max(0.0f, v)); }
static inline float safeAsin(float v) { return std::asin(std::min(1.0f, std::max(-1.0f, v))); }

// Modified Bessel I0 and its log (pbrt hair.cpp I0/LogI0). Series for I0; the
// log form is used for the numerically-stable small-variance Mp branch.
static inline float besselI0(float x) {
    float val = 0.0f, x2i = 1.0f, ifact = 1.0f;
    int i4 = 1;
    // 10 terms is ample for the |x| range Mp produces (pbrt uses the same).
    for (int i = 0; i < 10; ++i) {
        if (i > 1) ifact *= (float)i;
        val += x2i / (float)(i4 * ifact * ifact);
        x2i *= x * x;
        i4 *= 4;
    }
    return val;
}
static inline float logBesselI0(float x) {
    if (x > 12.0f)
        return x + 0.5f * (-std::log(2.0f * kPi) + std::log(1.0f / x) + 1.0f / (8.0f * x));
    return std::log(besselI0(x));
}

// Longitudinal scattering Mp (d'Eon 2011 Gaussian detector via Bessel I0).
// pbrt hair.cpp Mp(). v is the per-lobe longitudinal variance.
static inline float Mp(float cosThetaI, float cosThetaO,
                       float sinThetaI, float sinThetaO, float v) {
    float a = cosThetaI * cosThetaO / v;
    float b = sinThetaI * sinThetaO / v;
    float mp = (v <= 0.1f)
        ? std::exp(logBesselI0(a) - b - 1.0f / v + 0.6931f + std::log(1.0f / (2.0f * v)))
        : (std::exp(-b) * besselI0(a)) / (std::sinh(1.0f / v) * 2.0f * v);
    return mp;
}

// Logistic distribution + its trimmed form over [a,b] (pbrt hair.cpp).
static inline float logistic(float x, float s) {
    x = std::abs(x);
    float e = std::exp(-x / s);
    return e / (s * sqr(1.0f + e));
}
static inline float logisticCDF(float x, float s) {
    return 1.0f / (1.0f + std::exp(-x / s));
}
static inline float trimmedLogistic(float x, float s, float a, float b) {
    return logistic(x, s) / (logisticCDF(b, s) - logisticCDF(a, s));
}
static inline float sampleTrimmedLogistic(float u, float s, float a, float b) {
    float k = logisticCDF(b, s) - logisticCDF(a, s);
    float x = -s * std::log(1.0f / (u * k + logisticCDF(a, s)) - 1.0f);
    return std::min(std::max(x, a), b);
}

// Azimuthal ideal-specular direction offset for order p (pbrt hair.cpp Phi()).
static inline float deltaPhi(int p, float gammaO, float gammaT) {
    return 2.0f * (float)p * gammaT - 2.0f * gammaO + (float)p * kPi;
}

// Wrap an angle into [-pi, pi] (pbrt hair.cpp inline in Np).
static inline float wrapAngle(float phi) {
    while (phi > kPi)  phi -= 2.0f * kPi;
    while (phi < -kPi) phi += 2.0f * kPi;
    return phi;
}

// Azimuthal scattering Np (Chiang logistic lobe; residual is isotropic 1/2pi).
static inline float Np(float phi, int p, float s, float gammaO, float gammaT) {
    float dphi = phi - deltaPhi(p, gammaO, gammaT);
    dphi = wrapAngle(dphi);
    return trimmedLogistic(dphi, s, -kPi, kPi);
}

// UI roughness (beta_m, beta_n) -> longitudinal variance v and azimuthal
// logistic scale s (Chiang §4; identical in pbrt and Cycles — note divergence
// table row 4). Precompute once per material.
static inline float longitudinalVariance(float betaM) {
    float t = 0.726f * betaM + 0.812f * sqr(betaM) + 3.7f * std::pow(betaM, 20.0f);
    return sqr(t);
}
static inline float azimuthalScale(float betaN) {
    return (0.265f * betaN + 1.194f * sqr(betaN) + 5.372f * std::pow(betaN, 22.0f)) * kSqrtPiOver8;
}

// Fresnel dielectric reflectance (unpolarized), pbrt reflection.cpp FrDielectric.
// etaI outside, etaT inside; cosThetaI is the incidence cosine on the outside.
static inline float frDielectric(float cosThetaI, float etaI, float etaT) {
    cosThetaI = std::min(1.0f, std::max(-1.0f, cosThetaI));
    if (cosThetaI < 0.0f) { std::swap(etaI, etaT); cosThetaI = -cosThetaI; }
    float sinThetaI = safeSqrt(1.0f - cosThetaI * cosThetaI);
    float sinThetaT = etaI / etaT * sinThetaI;
    if (sinThetaT >= 1.0f) return 1.0f;  // TIR
    float cosThetaT = safeSqrt(1.0f - sinThetaT * sinThetaT);
    float rParl = ((etaT * cosThetaI) - (etaI * cosThetaT)) /
                  ((etaT * cosThetaI) + (etaI * cosThetaT));
    float rPerp = ((etaI * cosThetaI) - (etaT * cosThetaT)) /
                  ((etaI * cosThetaI) + (etaT * cosThetaT));
    return 0.5f * (rParl * rParl + rPerp * rPerp);
}

// Per-lobe absorption attenuation Ap[0..pMax], given the single-traversal
// transmittance T for ONE channel (pbrt hair.cpp Ap()). f is the fiber-surface
// Fresnel. Returns the (un-normalized) energy of each lobe for that channel.
static inline void Ap(float f, float T, float ap[kPMax + 1]) {
    ap[0] = f;                          // R
    ap[1] = sqr(1.0f - f) * T;          // TT
    ap[2] = ap[1] * T * f;              // TRT
    // residual TRRT+ geometric tail (pbrt: ap[pMax] = ap[pMax-1]*f*T/(1-T*f))
    ap[3] = ap[2] * f * T / std::max(1e-5f, 1.0f - T * f);
}

// Discrete lobe-selection pmf from a channel-luminance of Ap (pbrt ComputeApPdf).
// Uses the given per-lobe scalar energies (already luminance-reduced).
static inline void apPdf(const float ap[kPMax + 1], float pdf[kPMax + 1]) {
    float sum = 0.0f;
    for (int i = 0; i <= kPMax; ++i) sum += ap[i];
    float inv = (sum > 0.0f) ? 1.0f / sum : 0.0f;
    for (int i = 0; i <= kPMax; ++i) pdf[i] = ap[i] * inv;
}

// Cuticle-tilt scaled angles per lobe (Cycles hair_alpha_angles / pbrt
// sin2kAlpha,cos2kAlpha with the 1/2/4 Marschner pattern). Precompute the base
// sin/cos of 2^k * alpha for k=0,1,2 once. Divergence-table row 8: match this
// convention exactly. angleShift returns (sinThetaOp, cosThetaOp) for lobe p by
// rotating (sinThetaO, cosThetaO) by the lobe's tilt.
struct AlphaTilt {
    float sin2k[3];  // sin(2^k * alpha)
    float cos2k[3];
};
static inline AlphaTilt makeAlphaTilt(float alpha) {
    AlphaTilt t;
    t.sin2k[0] = std::sin(alpha);
    t.cos2k[0] = std::cos(alpha);
    for (int i = 1; i < 3; ++i) {
        t.sin2k[i] = 2.0f * t.cos2k[i - 1] * t.sin2k[i - 1];
        t.cos2k[i] = sqr(t.cos2k[i - 1]) - sqr(t.sin2k[i - 1]);
    }
    return t;
}
// Rotate (sinThetaO, cosThetaO) by the tilt for lobe p (pbrt hair.cpp f()):
//   R (p=0): +2 alpha ; TT (p=1): -1 alpha ; TRT (p=2): -4 alpha ; residual: 0.
static inline void tiltThetaO(const AlphaTilt& t, int p,
                              float sinThetaO, float cosThetaO,
                              float& sinThetaOp, float& cosThetaOp) {
    if (p == 0) {
        sinThetaOp = sinThetaO * t.cos2k[1] - cosThetaO * t.sin2k[1];  // +2a
        cosThetaOp = cosThetaO * t.cos2k[1] + sinThetaO * t.sin2k[1];
    } else if (p == 1) {
        sinThetaOp = sinThetaO * t.cos2k[0] + cosThetaO * t.sin2k[0];  // -1a
        cosThetaOp = cosThetaO * t.cos2k[0] - sinThetaO * t.sin2k[0];
    } else if (p == 2) {
        sinThetaOp = sinThetaO * t.cos2k[2] + cosThetaO * t.sin2k[2];  // -4a
        cosThetaOp = cosThetaO * t.cos2k[2] - sinThetaO * t.sin2k[2];
    } else {
        sinThetaOp = sinThetaO;
        cosThetaOp = cosThetaO;
    }
}

// --- sigma_a parameterizations (Cycles bsdf_util.h; divergence-table rows 1-3) ---

// Direct-coloring: invert a target reflectance `color` into absorption, using
// the radial roughness beta_n (Cycles bsdf_principled_hair_sigma_from_reflectance).
static inline float sigmaAFromReflectanceChannel(float color, float betaN) {
    float d = 5.969f - 0.215f * betaN + 2.532f * sqr(betaN) - 10.73f * betaN * betaN * betaN +
              5.574f * std::pow(betaN, 4.0f) + 0.245f * std::pow(betaN, 5.0f);
    float t = std::log(std::max(color, 1e-4f)) / d;
    return t * t;
}

// Melanin -> absorption (Cycles coefficients; divergence-table row 1).
// eumelanin c_e=(0.506,0.841,1.653), pheomelanin c_p=(0.343,0.733,1.924).
static inline void melaninCoeffs(int channel, float& ce, float& cp) {
    const float CE[3] = {0.506f, 0.841f, 1.653f};
    const float CP[3] = {0.343f, 0.733f, 1.924f};
    ce = CE[channel]; cp = CP[channel];
}

}  // namespace hair
}  // namespace astroray

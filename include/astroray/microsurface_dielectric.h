#pragma once

// pkg265 — Multiple-scattering microfacet DIELECTRIC: the Smith-microsurface
// random walk of
//
//   Heitz, Hanika, d'Eon, Dachsbacher, "Multiple-Scattering Microfacet BSDFs
//   with the Smith Model", ACM TOG 35(4) (SIGGRAPH 2016),
//   DOI 10.1145/2897824.2925943.
//
// CLEAN-ROOM from the paper's published equations only (lead decision 2026-09-09,
// Option A). NO code was copied from the paper's unstated-licence supplemental
// `MicrosurfaceScattering.cpp` or the GPLv3 Mitsuba plugin. Equation references:
//   height stats  P1,C1  (Sec 5.1, Eq 18-19)
//   signed Smith  Lambda (Sec 5.1, Eq 21-22, App. B)
//   height sample Alg 1 / Eq 30
//   dielectric phase Alg 3 / Eq 34
//   random walk   Alg 7 (Sec 7) + dielectric vertical flip (Fig 11)
//   stochastic eval E1..N (Sec 8.1, Eq 42); MIS pdf (Sec 9)
// See .astroray_plan/docs/pkg265-multiscatter-microfacet-research.md and the numpy
// oracle benchmarks/cycles-parity/glass_ms_oracle/heitz_random_walk.py, against
// which this header is validated (energy R+T==1, directional histograms).
//
// This is the HOST implementation using astroray::Vec3. The device twin lives in
// include/astroray/gpu_materials.h (pkg265 Phase 3) and must stay numerically
// consistent, the same way gpu_ggxDarkeningChannel mirrors ggxDarkeningChannel.
//
// HOST-ONLY: this header pulls raytracer.h and <cmath>/<algorithm> host STL and
// must never be compiled by the CUDA device front-end (cpp-abi-guard). The device
// twin is the hand-written mirror in gpu_materials.h, not this file.
#ifndef __CUDACC__

#include <algorithm>
#include <cmath>
#include "raytracer.h"   // astroray::Vec3, M_PI

namespace astroray {
namespace msdiel {

// Giles single-precision erf^-1 approximation (M. Giles, "Approximating the
// erfinv function", GPU Computing Gems Jade Edition, 2011 — freely published,
// widely reproduced; the CUDA twin uses the built-in erfinvf). Max abs error
// ~6e-3 over the domain, far below the MC noise the walk carries.
inline float erfinvApprox(float x) {
    float w = -std::log((1.0f - x) * (1.0f + x));
    float p;
    if (w < 5.0f) {
        w -= 2.5f;
        p = 2.81022636e-08f;
        p = 3.43273939e-07f + p * w;
        p = -3.5233877e-06f + p * w;
        p = -4.39150654e-06f + p * w;
        p = 0.00021858087f + p * w;
        p = -0.00125372503f + p * w;
        p = -0.00417768164f + p * w;
        p = 0.246640727f + p * w;
        p = 1.50140941f + p * w;
    } else {
        w = std::sqrt(w) - 3.0f;
        p = -0.000200214257f;
        p = 0.000100950558f + p * w;
        p = 0.00134934322f + p * w;
        p = -0.00367342844f + p * w;
        p = 0.00573950773f + p * w;
        p = -0.0076224613f + p * w;
        p = 0.00943887047f + p * w;
        p = 1.00167406f + p * w;
        p = 2.83297682f + p * w;
    }
    return p * x;
}

// Standard-normal microsurface height CDF and its inverse (Eq 18-19).
inline float C1(float h) { return 0.5f * (1.0f + std::erf(h * 0.70710678f)); }
inline float invC1(float u) {
    if (u >= 1.0f) return 1e9f;           // ray escapes (+inf)
    u = std::min(std::max(u, 1e-7f), 1.0f - 1e-7f);
    return 1.41421356f * erfinvApprox(2.0f * u - 1.0f);
}

// Signed Smith GGX Lambda (Eq 21-22). Positive for up rays (escape possible),
// <= -1 for down rays (always intersect). alpha is isotropic GGX roughness.
inline float lambdaGGX(float wz, float alpha) {
    if (wz > 0.9999f) return 0.0f;
    if (wz < -0.9999f) return -1.0f;
    float tan2 = (1.0f - wz * wz) / (wz * wz);
    float s = (wz >= 0.0f) ? 1.0f : -1.0f;
    return 0.5f * (s * std::sqrt(1.0f + alpha * alpha * tan2) - 1.0f);
}

// Alg 1 / Eq 30: next intersection height given current height hr, ray direction
// wr and a uniform U. Returns >=1e9 when the ray leaves the microsurface.
inline float sampleHeight(const Vec3& wr, float hr, float alpha, float U) {
    float wz = wr.z;
    if (wz > 0.9999f) return 1e9f;                 // straight up: always leaves
    if (wz < -0.9999f) return invC1(C1(hr) * (1.0f - U));  // straight down, Lambda=-1
    if (std::abs(wz) < 1e-4f) return hr;           // horizontal: stays (Table 3)
    float L = lambdaGGX(wz, alpha);
    float c1 = std::min(std::max(C1(hr), 1e-7f), 1.0f);
    if (wz > 0.0f) {                               // up rays can escape
        if (U >= 1.0f - std::pow(c1, L)) return 1e9f;
    }
    float arg = c1 / std::pow(std::max(1.0f - U, 1e-7f), 1.0f / L);
    return invC1(arg);
}

// GGX VNDF sampling (Heitz JCGT 2018; == principled.cpp sampleGgxVNDF). wi may be
// in either hemisphere (walk direction -wr). Returns a micronormal with z>0.
inline Vec3 sampleVNDF(const Vec3& wi, float alpha, float u1, float u2) {
    Vec3 Vh = Vec3(alpha * wi.x, alpha * wi.y, wi.z).normalized();
    float lensq = Vh.x * Vh.x + Vh.y * Vh.y;
    Vec3 T1 = (lensq > 1e-12f) ? Vec3(-Vh.y, Vh.x, 0.0f) * (1.0f / std::sqrt(lensq))
                               : Vec3(1.0f, 0.0f, 0.0f);
    Vec3 T2 = Vh.cross(T1);
    float r = std::sqrt(u1);
    float phi = 2.0f * float(M_PI) * u2;
    float t1 = r * std::cos(phi);
    float t2 = r * std::sin(phi);
    float s = 0.5f * (1.0f + Vh.z);
    t2 = (1.0f - s) * std::sqrt(std::max(0.0f, 1.0f - t1 * t1)) + s * t2;
    float t3 = std::sqrt(std::max(0.0f, 1.0f - t1 * t1 - t2 * t2));
    Vec3 Nh = T1 * t1 + T2 * t2 + Vh * t3;
    return Vec3(alpha * Nh.x, alpha * Nh.y, std::max(1e-6f, Nh.z)).normalized();
}

// Exact dielectric Fresnel; cosI>=0 is the incidence cosine on the micronormal.
inline float fresnelDielectric(float cosI, float etaI, float etaT) {
    cosI = std::min(std::max(std::abs(cosI), 0.0f), 1.0f);
    float sinI = std::sqrt(std::max(0.0f, 1.0f - cosI * cosI));
    float sinT = etaI / etaT * sinI;
    if (sinT >= 1.0f) return 1.0f;                 // TIR
    float cosT = std::sqrt(std::max(0.0f, 1.0f - sinT * sinT));
    float rp = (etaT * cosI - etaI * cosT) / (etaT * cosI + etaI * cosT + 1e-9f);
    float rs = (etaI * cosI - etaT * cosT) / (etaI * cosI + etaT * cosT + 1e-9f);
    return std::min(std::max(0.5f * (rp * rp + rs * rs), 0.0f), 1.0f);
}

// Snell refraction of the travel-reversed incident wi about micronormal wm,
// relative eta = etaI/etaT. Returns false on TIR (caller reflects instead).
inline bool refractMicro(const Vec3& wi, const Vec3& wm, float eta, Vec3& wt) {
    float c = wi.dot(wm);                           // dot(wi,wm) > 0
    Vec3 perp = (wi - wm * c) * (-eta);
    float par2 = 1.0f - perp.length2();
    if (par2 <= 0.0f) return false;
    wt = (perp - wm * std::sqrt(par2)).normalized();
    return true;
}

struct WalkSample {
    Vec3 wi = Vec3(0, 0, 1);
    bool reflected = true;
    bool escaped = false;
    float radianceScale = 1.0f;   // product of eta^2 per transmission (1 for solids)
};

// Alg 7 dielectric random walk in the LOCAL frame (normal = +z). woLocal.z must
// be > 0. entering: incident side is air (true, n1=1,n2=ior) or glass (false,
// n1=ior,n2=1 -> the exit interface). Rng is any callable returning U(0,1) float.
// The sampler is a PERFECT importance sampler for a lossless dielectric (phase
// weight == 1): the returned direction carries unit throughput, no dead samples.
template <class Rng>
inline WalkSample sampleWalk(const Vec3& woLocal, float alpha, float ior,
                             bool entering, Rng& rng, int scatterMax) {
    WalkSample out;
    Vec3 wr = -woLocal;                             // omega1 = -omega_i (Alg 7)
    float hr = invC1(0.999999f);
    float n1 = entering ? 1.0f : ior;               // incident-side ior
    float n2 = entering ? ior : 1.0f;               // transmit-side ior
    int nflip = 0;
    float radiance = 1.0f;
    int order = 0;
    while (true) {
        hr = sampleHeight(wr, hr, alpha, rng());
        if (hr >= 1e9f) { out.escaped = true; break; }
        if (order >= scatterMax) { out.escaped = false; break; }   // dead sample
        // dielectric phase event (Alg 3): visible normal from wi = -wr
        Vec3 wi = -wr;
        Vec3 wm = sampleVNDF(wi, alpha, rng(), rng());
        float c = wi.dot(wm);
        float F = fresnelDielectric(c, n1, n2);
        if (rng() < F) {
            wr = wm * (2.0f * c) - wi;               // reflect
        } else {
            Vec3 wt;
            float eta = n1 / n2;
            if (refractMicro(wi, wm, eta, wt)) {
                wr = wt;
                hr = -hr;                            // Fig 11 vertical flip
                wr.z = -wr.z;
                float tmp = n1; n1 = n2; n2 = tmp;   // swap interface iors
                radiance *= eta * eta;               // radiance compression
                ++nflip;
            } else {
                wr = wm * (2.0f * c) - wi;           // TIR -> reflect
            }
        }
        ++order;
    }
    // undo the net vertical flips to recover the physical outgoing direction
    if (nflip & 1) { out.wi = Vec3(wr.x, wr.y, -wr.z); out.reflected = false; }
    else { out.wi = wr; out.reflected = true; }
    out.wi = out.wi.normalized();
    out.radianceScale = radiance;
    return out;
}

// Sec 9 MIS pdf: the closed-form single-scattering VNDF pdf of the FIRST event
// plus a small diffuse floor. NOT the true (intractable) multi-bounce pdf; a
// valid quantity for unbiased MIS weights (paper Sec 9). woLocal/wiLocal in the
// local +z frame; reflected iff wiLocal.z and woLocal.z share sign.
inline float firstBouncePdf(const Vec3& woLocal, const Vec3& wiLocal, float alpha,
                            float ior, bool entering) {
    float ni = entering ? 1.0f : ior;
    float nt = entering ? ior : 1.0f;
    float cosO = woLocal.z;                          // > 0
    float cosI = wiLocal.z;
    const float diffuseFloor = 0.05f;               // Sec 9 "small diffuse contribution"
    float diffuse = diffuseFloor * std::abs(cosI) / float(M_PI);
    float p = 0.0f;
    auto vndfPdf = [&](const Vec3& wm) {
        float absCosO = std::abs(cosO);
        float HdotO = std::abs(wm.dot(woLocal));
        float NdotH = std::abs(wm.z);
        if (HdotO <= 1e-8f || NdotH <= 1e-8f || absCosO <= 1e-8f) return 0.0f;
        float a2 = alpha * alpha;
        float t = 1.0f + (a2 - 1.0f) * NdotH * NdotH;
        float D = a2 / (float(M_PI) * t * t);
        float lam = lambdaGGX(absCosO, alpha);       // classic G1 via +Lambda
        float G1 = 1.0f / (1.0f + lam);
        return G1 / absCosO * D * HdotO;
    };
    if (cosO * cosI > 0.0f) {                        // reflection
        Vec3 wm = (woLocal + wiLocal).normalized();
        if (wm.z < 0.0f) wm = -wm;
        float HdotO = std::abs(woLocal.dot(wm));
        float F = fresnelDielectric(HdotO, ni, nt);
        if (HdotO > 1e-8f) p = F * vndfPdf(wm) / (4.0f * HdotO);
    } else if (cosO * cosI < 0.0f) {                 // transmission
        float etap = nt / ni;
        Vec3 wm = (wiLocal * etap + woLocal).normalized();
        if (wm.z < 0.0f) wm = -wm;
        float HdotO = woLocal.dot(wm);
        float HdotI = wiLocal.dot(wm);
        float d = HdotI + HdotO / etap;
        float d2 = d * d;
        if (HdotO * HdotI < 0.0f && d2 > 1e-8f) {
            float F = fresnelDielectric(std::abs(HdotO), ni, nt);
            p = (1.0f - F) * vndfPdf(wm) * std::abs(HdotI) / d2;
        }
    }
    return p + diffuse;
}

// Signed-cos_i VNDF value Dwi(wm) = <wi,wm> D(wm) / (cos_i (1+Lambda(wi)))  (Eq 32).
// cos_i is SIGNED: Eq 32 is valid for wi in EITHER hemisphere (paper Sec 6.1). For an
// upward-going ray (wi.z<0) cos_i<0 AND (1+Lambda)<0, so their product (the projected
// area) is positive; using |cos_i| makes it negative and, floored, blows Dwi up to
// ~1e11 (the pkg265 stochastic-eval firefly). Signed cos_i keeps it bounded.
inline float vndfDwi(const Vec3& wi, const Vec3& wm, float alpha) {
    float NdotH = std::abs(wm.z);
    float a2 = alpha * alpha;
    float t = 1.0f + (a2 - 1.0f) * NdotH * NdotH;
    float D = a2 / (float(M_PI) * t * t);
    float idot = std::max(wi.dot(wm), 0.0f);
    float denom = wi.z * (1.0f + lambdaGGX(wi.z, alpha));   // SIGNED, both hemispheres
    return idot * D / std::max(denom, 1e-8f);
}

// Reflection phase-lobe density wi->tgt off an UPPER-hemisphere microfacet
// wh=normalize(wi+tgt) (must have wh.z>0, a real upward microfacet).
inline float reflLobe(const Vec3& wi, const Vec3& tgt, float alpha, float ni, float nt) {
    Vec3 whv = wi + tgt;
    if (whv.length2() < 1e-24f) return 0.0f;
    Vec3 wh = whv.normalized();
    float c = wi.dot(wh);
    if (wh.z <= 1e-7f || c <= 1e-7f) return 0.0f;
    float F = fresnelDielectric(c, ni, nt);
    return F * vndfDwi(wi, wh, alpha) / (4.0f * std::abs(c) + 1e-12f);
}

// Refraction phase-lobe density wi->tgt through an UPPER-hemisphere microfacet
// wht=normalize(-(ni wi + nt tgt)) oriented for visibility (wi.wht>0); must be an
// upward microfacet AND actually refract wi onto tgt (reachability check).
inline float refrLobe(const Vec3& wi, const Vec3& tgt, float alpha, float ni, float nt) {
    Vec3 whv = -(wi * ni + tgt * nt);
    if (whv.length2() < 1e-24f) return 0.0f;
    Vec3 wht = whv.normalized();
    float ci = wi.dot(wht);
    if (ci < 0.0f) { wht = -wht; ci = -ci; }
    if (wht.z <= 1e-7f || ci <= 1e-7f) return 0.0f;
    Vec3 wt;
    if (!refractMicro(wi, wht, ni / nt, wt)) return 0.0f;
    if (wt.dot(tgt) <= 0.999f) return 0.0f;             // reachability
    float od = tgt.dot(wht);
    float F = fresnelDielectric(ci, ni, nt);
    float d = ni * ci + nt * od;
    return std::abs(od) * (nt * nt) * (1.0f - F) * vndfDwi(wi, wht, alpha)
           / std::max(d * d, 1e-12f);
}

// Sec 8.1 / Eq 42 stochastic eval: f(wo,wi)*|cos wi|, an unbiased estimate from a
// fresh walk started at wo, summing per-bounce phase*shadowing toward wiLocal.
// Reserved for NEE/MIS legs; the sampler above is used for path continuation.
//
// The connection runs in the SAME flip frame as the validated walk (R+T==1). At a
// vertex the fixed macro dir wiLocal maps to wifR=flip^nflip(wiLocal); the walk only
// escapes flip-frame-up, so exactly one lobe contributes:
//   wifR.z>0 : the escaping ray is a REFLECTION toward wifR, shadow C1(hr)^Lambda(wifR);
//   wifR.z<0 : the escaping ray is a REFRACTION whose pre-flip output is wifR; the walk
//              flips it to flip(wifR) (z>0) with shadow C1(-hr)^Lambda(flip(wifR)).
// Each lobe is the exact sampler density (upper-hemisphere microfacet + reachability),
// so per-bounce energy conserves and the R/T split matches the walk to MC error.
template <class Rng>
inline float stochasticEval(const Vec3& woLocal, const Vec3& wiLocal, float alpha,
                            float ior, bool entering, Rng& rng, int scatterMax) {
    Vec3 wr = -woLocal;
    float hr = invC1(0.999999f);
    float n1 = entering ? 1.0f : ior;
    float n2 = entering ? ior : 1.0f;
    int nflip = 0;
    float acc = 0.0f;
    int order = 0;
    while (true) {
        hr = sampleHeight(wr, hr, alpha, rng());
        if (hr >= 1e9f) break;
        if (order >= scatterMax) break;
        Vec3 wifR = (nflip & 1) ? Vec3(wiLocal.x, wiLocal.y, -wiLocal.z) : wiLocal;
        Vec3 wi = -wr;
        if (wifR.z > 1e-7f) {                            // reflection lobe, escape up
            float G = std::pow(std::min(std::max(C1(hr), 1e-7f), 1.0f),
                               lambdaGGX(wifR.z, alpha));
            acc += reflLobe(wi, wifR, alpha, n1, n2) * G;
        } else if (wifR.z < -1e-7f) {                    // refraction lobe, flip escapes up
            Vec3 wf = Vec3(wifR.x, wifR.y, -wifR.z);
            float G = std::pow(std::min(std::max(C1(-hr), 1e-7f), 1.0f),
                               lambdaGGX(wf.z, alpha));
            acc += refrLobe(wi, wifR, alpha, n1, n2) * G;
        }
        // advance the walk one phase event
        Vec3 wm = sampleVNDF(wi, alpha, rng(), rng());
        float c = wi.dot(wm);
        float F = fresnelDielectric(c, n1, n2);
        if (rng() < F) {
            wr = wm * (2.0f * c) - wi;
        } else {
            Vec3 wt; float eta = n1 / n2;
            if (refractMicro(wi, wm, eta, wt)) {
                wr = wt; hr = -hr; wr.z = -wr.z;
                float tmp = n1; n1 = n2; n2 = tmp; ++nflip;
            } else {
                wr = wm * (2.0f * c) - wi;
            }
        }
        ++order;
    }
    return acc;
}

}  // namespace msdiel
}  // namespace astroray

#endif  // __CUDACC__ (host-only header)

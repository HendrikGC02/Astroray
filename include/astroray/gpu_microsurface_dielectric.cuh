// gpu_microsurface_dielectric.cuh — pkg265 Phase 3 (GPU walk), WIP.
//
// Device twin of the host-only `msdiel` namespace in
// include/astroray/microsurface_dielectric.h — Heitz et al. 2016,
// "Multiple-Scattering Microfacet BSDFs with the Smith Model" (Alg 1/3/7),
// and Dupuy/Heitz VNDF sampling (JCGT 2018). Ported 1:1 from the CPU reference
// (which itself cites those papers and pbrt-v4's Hash-seeded RNG); the only
// changes are device intrinsics (erff/erfinvf built in — the CPU header uses
// Giles's erfinv approximation because the host lacks erfinvf, research note
// line ~118) and __noinline__ bodies so the walk does not inflate the REG-254
// stageShadeBucketedKernel caller's live-register set (memories
// noinline-runtime-flag-avoids-shade-spill, shade-axis-side-table-avoids-spill).
//
// STATUS: WIP — these functions are written and self-contained but NOT yet wired
// into gpu_pr_chooseAndSampleDir / gpu_closure_graph_eval[_spectral] / the pdf,
// and NOT yet gated behind the runtime __constant__ c_gpuGlassWalk flag. See
// .scratch/STATE.md on this branch for the remaining routing + build + REG-probe
// + gate-sweep steps. Unused for now (DCE'd), so the fleet build is unaffected.

#ifndef ASTRORAY_GPU_MICROSURFACE_DIELECTRIC_CUH
#define ASTRORAY_GPU_MICROSURFACE_DIELECTRIC_CUH

#ifdef __CUDACC__

#include "gpu_types.h"

namespace astroray {
namespace gpu_msd {

// pbrt-v4 splitmix64 + PCG32 hash RNG (device-portable; the CPU HashRng is
// already pure integer math). Two independent seeds hashed from wo/wi so two
// materials at the same geometry do not share a stream.
struct HashRng {
    unsigned long long state, inc;
    __device__ HashRng(unsigned long long seq0, unsigned long long seq1) {
        state = 0ull; inc = (seq1 << 1u) | 1u;
        nextUInt(); state += seq0; nextUInt();
    }
    __device__ unsigned int nextUInt() {
        unsigned long long old = state;
        state = old * 6364136223846793005ull + inc;
        unsigned int xorshifted = (unsigned int)(((old >> 18u) ^ old) >> 27u);
        unsigned int rot = (unsigned int)(old >> 59u);
        return (xorshifted >> rot) | (xorshifted << ((~rot + 1u) & 31u));
    }
    __device__ float operator()() {
        return fminf(nextUInt() * 2.3283064365386963e-10f, 0.99999994f);
    }
};

__device__ inline unsigned long long msd_mix64(unsigned long long z) {
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
    return z ^ (z >> 31);
}
__device__ inline unsigned long long msd_hashFloat(float f, unsigned long long seed) {
    unsigned int bits = __float_as_uint(f);
    return msd_mix64(seed ^ (unsigned long long)bits * 0x9E3779B97F4A7C15ull);
}
__device__ inline HashRng hashRngFor(const GVec3& woL, const GVec3& wiL,
                                     float alpha, float ior, bool entering) {
    unsigned long long a = msd_hashFloat(woL.x, 0x1234567ull);
    a = msd_hashFloat(woL.y, a); a = msd_hashFloat(woL.z, a); a = msd_hashFloat(alpha, a);
    unsigned long long b = msd_hashFloat(wiL.x, 0x89abcdefull);
    b = msd_hashFloat(wiL.y, b); b = msd_hashFloat(wiL.z, b); b = msd_hashFloat(ior, b);
    b = msd_mix64(b ^ (entering ? 0x9E37ull : 0x0ull));
    return HashRng(a, b);
}

__device__ constexpr int kMsScatterMax = 16;   // measured 0.00% dead over the grid
__device__ constexpr int kMsEvalWalks  = 1;     // Eq 42 unbiased at N=1

// Standard-normal microsurface height CDF and inverse (Eq 18-19). Device erff/
// erfinvf replace the CPU header's std::erf + Giles erfinv approximation.
__device__ inline float C1(float h) { return 0.5f * (1.0f + erff(h * 0.70710678f)); }
__device__ inline float invC1(float u) {
    if (u >= 1.0f) return 1e9f;               // ray escapes (+inf)
    u = fminf(fmaxf(u, 1e-7f), 1.0f - 1e-7f);
    return 1.41421356f * erfinvf(2.0f * u - 1.0f);
}

// Signed Smith GGX Lambda (Eq 21-22).
__device__ inline float lambdaGGX(float wz, float alpha) {
    if (wz > 0.9999f) return 0.0f;
    if (wz < -0.9999f) return -1.0f;
    float tan2 = (1.0f - wz * wz) / (wz * wz);
    float s = (wz >= 0.0f) ? 1.0f : -1.0f;
    return 0.5f * (s * sqrtf(1.0f + alpha * alpha * tan2) - 1.0f);
}

// Alg 1 / Eq 30 next-height sampling.
__device__ inline float sampleHeight(const GVec3& wr, float hr, float alpha, float U) {
    float wz = wr.z;
    if (wz > 0.9999f) return 1e9f;
    if (wz < -0.9999f) return invC1(C1(hr) * (1.0f - U));
    if (fabsf(wz) < 1e-4f) return hr;
    float L = lambdaGGX(wz, alpha);
    float c1 = fminf(fmaxf(C1(hr), 1e-7f), 1.0f);
    if (wz > 0.0f) { if (U >= 1.0f - powf(c1, L)) return 1e9f; }
    float arg = c1 / powf(fmaxf(1.0f - U, 1e-7f), 1.0f / L);
    return invC1(arg);
}

// GGX VNDF sampling (Heitz JCGT 2018). Mirrors gpu_pr_sampleGgxVNDF but in a
// caller-supplied local frame (wi may be in either hemisphere = walk dir -wr).
__device__ inline GVec3 sampleVNDF(const GVec3& wi, float alpha, float u1, float u2) {
    GVec3 Vh = GVec3(alpha * wi.x, alpha * wi.y, wi.z).normalized();
    float lensq = Vh.x * Vh.x + Vh.y * Vh.y;
    GVec3 T1 = (lensq > 1e-12f) ? GVec3(-Vh.y, Vh.x, 0.0f) * (1.0f / sqrtf(lensq))
                                : GVec3(1.0f, 0.0f, 0.0f);
    GVec3 T2 = Vh.cross(T1);
    float r = sqrtf(u1);
    float phi = 2.0f * 3.14159265358979323846f * u2;
    float t1 = r * cosf(phi);
    float t2 = r * sinf(phi);
    float s = 0.5f * (1.0f + Vh.z);
    t2 = (1.0f - s) * sqrtf(fmaxf(0.0f, 1.0f - t1 * t1)) + s * t2;
    float t3 = sqrtf(fmaxf(0.0f, 1.0f - t1 * t1 - t2 * t2));
    GVec3 Nh = T1 * t1 + T2 * t2 + Vh * t3;
    return GVec3(alpha * Nh.x, alpha * Nh.y, fmaxf(1e-6f, Nh.z)).normalized();
}

// Exact dielectric Fresnel (cosI on the micronormal). Same as the CPU header's
// fresnelDielectric; kept local so the walk is self-contained (gpu_materials.h's
// gpu_pr_fresnelDielectric(cosThetaI, etaI, etaT) is identical and can be reused
// once this header is included there — see STATE.md routing step).
__device__ inline float fresnelDielectric(float cosI, float etaI, float etaT) {
    cosI = fminf(fmaxf(fabsf(cosI), 0.0f), 1.0f);
    float sinI = sqrtf(fmaxf(0.0f, 1.0f - cosI * cosI));
    float sinT = etaI / etaT * sinI;
    if (sinT >= 1.0f) return 1.0f;
    float cosT = sqrtf(fmaxf(0.0f, 1.0f - sinT * sinT));
    float rp = (etaT * cosI - etaI * cosT) / (etaT * cosI + etaI * cosT + 1e-9f);
    float rs = (etaI * cosI - etaT * cosT) / (etaI * cosI + etaT * cosT + 1e-9f);
    return fminf(fmaxf(0.5f * (rp * rp + rs * rs), 0.0f), 1.0f);
}

__device__ inline bool refractMicro(const GVec3& wi, const GVec3& wm, float eta, GVec3& wt) {
    float c = wi.dot(wm);
    GVec3 perp = (wi - wm * c) * (-eta);
    float par2 = 1.0f - perp.length2();
    if (par2 <= 0.0f) return false;
    wt = (perp - wm * sqrtf(par2)).normalized();
    return true;
}

struct WalkSample {
    GVec3 wi;
    bool reflected;
    bool escaped;
    float radianceScale;   // product of eta^2 per transmission (1 for solids)
};

// Alg 7 dielectric random walk in the LOCAL frame (+z normal), woLocal.z > 0.
// Perfect importance sampler for a lossless dielectric (phase weight == 1).
// __noinline__: called-out subroutine so it does not inflate the shade kernel's
// live-register set (register-critical; see the file header).
template <class Rng>
__device__ __noinline__ WalkSample sampleWalk(const GVec3& woLocal, float alpha, float ior,
                                              bool entering, Rng& rng, int scatterMax) {
    WalkSample out; out.wi = GVec3(0, 0, 1); out.reflected = true; out.escaped = false;
    GVec3 wr = woLocal * (-1.0f);                 // omega1 = -omega_i
    float hr = invC1(0.999999f);
    float n1 = entering ? 1.0f : ior;
    float n2 = entering ? ior : 1.0f;
    int nflip = 0; float radiance = 1.0f; int order = 0;
    while (true) {
        hr = sampleHeight(wr, hr, alpha, rng());
        if (hr >= 1e9f) { out.escaped = true; break; }
        if (order >= scatterMax) { out.escaped = false; break; }  // dead sample
        GVec3 wi = wr * (-1.0f);
        GVec3 wm = sampleVNDF(wi, alpha, rng(), rng());
        float c = wi.dot(wm);
        float F = fresnelDielectric(c, n1, n2);
        if (rng() < F) {
            wr = wm * (2.0f * c) - wi;             // reflect
        } else {
            GVec3 wt; float eta = n1 / n2;
            if (refractMicro(wi, wm, eta, wt)) {
                wr = wt; hr = -hr; wr.z = -wr.z;
                float tmp = n1; n1 = n2; n2 = tmp;
                radiance *= eta * eta; ++nflip;
            } else {
                wr = wm * (2.0f * c) - wi;         // TIR -> reflect
            }
        }
        ++order;
    }
    if (nflip & 1) { out.wi = GVec3(wr.x, wr.y, -wr.z); out.reflected = false; }
    else { out.wi = wr; out.reflected = true; }
    out.wi = out.wi.normalized();
    out.radianceScale = radiance;
    return out;
}

// reflLobe / refrLobe (Eq 33/37 micro-BSDF single-event weights). Ported from the
// CPU header's reflLobe/refrLobe (see microsurface_dielectric.h ~346-386).
__device__ inline float vndfDwi(const GVec3& wi, const GVec3& wm, float alpha) {
    float a2 = alpha * alpha;
    float cos2 = wm.z * wm.z;
    float t = (wm.x * wm.x + wm.y * wm.y) / fmaxf(a2, 1e-12f) + cos2;
    float D = 1.0f / fmaxf(3.14159265358979323846f * a2 * t * t, 1e-20f);
    float lam = lambdaGGX(wi.z, alpha);
    float G1 = 1.0f / (1.0f + fmaxf(lam, 0.0f));
    return G1 * fmaxf(wi.dot(wm), 0.0f) * D / fmaxf(fabsf(wi.z), 1e-8f);
}
__device__ inline float reflLobe(const GVec3& wi, const GVec3& tgt, float alpha, float ni, float nt) {
    GVec3 wh = (wi + tgt); float len = wh.length(); if (len < 1e-8f) return 0.0f;
    wh = wh * (1.0f / len); if (wh.z < 0.0f) wh = wh * (-1.0f);
    float F = fresnelDielectric(wi.dot(wh), ni, nt);
    return F * vndfDwi(wi, wh, alpha) / fmaxf(4.0f * fabsf(wi.dot(wh)), 1e-8f);
}
__device__ inline float refrLobe(const GVec3& wi, const GVec3& tgt, float alpha, float ni, float nt) {
    GVec3 wh = (wi * ni + tgt * nt) * (-1.0f); float len = wh.length(); if (len < 1e-8f) return 0.0f;
    wh = wh * (1.0f / len); if (wh.z < 0.0f) wh = wh * (-1.0f);
    float c = wi.dot(wh), ct = tgt.dot(wh);
    float F = fresnelDielectric(c, ni, nt);
    float denom = ni * c + nt * ct; denom *= denom; if (denom < 1e-12f) return 0.0f;
    float jac = (nt * nt * fabsf(ct)) / denom;
    return (1.0f - F) * vndfDwi(wi, wh, alpha) * jac / fmaxf(fabsf(wi.dot(wh)), 1e-8f);
}

// stochasticEval (Eq 42) — one unbiased estimate of the walk's escape density
// p(wi). __noinline__ (register-critical).
template <class Rng>
__device__ __noinline__ float stochasticEval(const GVec3& woLocal, const GVec3& wiLocal,
                                             float alpha, float ior, bool entering,
                                             Rng& rng, int scatterMax) {
    GVec3 wr = woLocal * (-1.0f);
    float hr = invC1(0.999999f);
    float n1 = entering ? 1.0f : ior;
    float n2 = entering ? ior : 1.0f;
    int nflip = 0; float acc = 0.0f; int order = 0;
    while (true) {
        hr = sampleHeight(wr, hr, alpha, rng());
        if (hr >= 1e9f) break;
        if (order >= scatterMax) break;
        GVec3 wifR = (nflip & 1) ? GVec3(wiLocal.x, wiLocal.y, -wiLocal.z) : wiLocal;
        GVec3 wi = wr * (-1.0f);
        if (wifR.z > 1e-7f) {
            float G = powf(fminf(fmaxf(C1(hr), 1e-7f), 1.0f), lambdaGGX(wifR.z, alpha));
            acc += reflLobe(wi, wifR, alpha, n1, n2) * G;
        } else if (wifR.z < -1e-7f) {
            float G = powf(fminf(fmaxf(C1(-hr), 1e-7f), 1.0f), lambdaGGX(-wifR.z, alpha));
            acc += refrLobe(wi, wifR, alpha, n1, n2) * G;
        }
        GVec3 wm = sampleVNDF(wi, alpha, rng(), rng());
        float c = wi.dot(wm);
        float F = fresnelDielectric(c, n1, n2);
        if (rng() < F) { wr = wm * (2.0f * c) - wi; }
        else {
            GVec3 wt; float eta = n1 / n2;
            if (refractMicro(wi, wm, eta, wt)) { wr = wt; hr = -hr; wr.z = -wr.z; float t = n1; n1 = n2; n2 = t; ++nflip; }
            else { wr = wm * (2.0f * c) - wi; }
        }
        ++order;
    }
    return acc;
}

// Material-facing hash-seeded eval (Eq 42, N walks). Local +z frame, woLocal.z>0.
__device__ inline float stochasticEvalHashed(const GVec3& woLocal, const GVec3& wiLocal,
                                             float alpha, float ior, bool entering,
                                             int walks = kMsEvalWalks, int scatterMax = kMsScatterMax) {
    if (woLocal.z <= 1e-6f || walks <= 0) return 0.0f;
    HashRng rng = hashRngFor(woLocal, wiLocal, alpha, ior, entering);
    float acc = 0.0f;
    for (int k = 0; k < walks; ++k)
        acc += stochasticEval(woLocal, wiLocal, alpha, ior, entering, rng, scatterMax);
    acc /= (float)walks;
    if (!(acc > 0.0f)) return 0.0f;
    float radScale = (wiLocal.z > 0.0f) ? 1.0f : (entering ? 1.0f / (ior * ior) : ior * ior);
    return radScale * acc;
}

}  // namespace gpu_msd
}  // namespace astroray

#endif  // __CUDACC__
#endif  // ASTRORAY_GPU_MICROSURFACE_DIELECTRIC_CUH

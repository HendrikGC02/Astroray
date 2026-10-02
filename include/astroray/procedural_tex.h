#pragma once
// ============================================================================
// #1007 - procedural texture evaluators, host + device (one implementation).
//
// The CPU Texture classes (include/advanced_features.h NoiseTextureCycles,
// WaveTexture, VoronoiTexture, WhiteNoiseTexture) call these functions, and the
// GPU wavefront shade path evaluates them per hit (src/gpu/wavefront/
// proc_tex_eval.cu) instead of sampling the 64^3 voxel bake of #994/pkg190.
// The bodies are the pkg115 CPU ports moved here verbatim (same operations in
// the same order, so the CPU output is bit-identical); std:: calls became the
// float C functions they resolve to, and Vec3 / became an explicit per-component
// division (GVec3::operator/ multiplies by the reciprocal).
//
// Sources (research note .astroray_plan/docs/issue1007-perhit-procedural-research.md):
//   Blender intern/cycles/util/hash.h            (Apache-2.0) - Jenkins lookup3, PCG3D
//   Blender intern/cycles/kernel/svm/noise.h     (BSD-3-Clause, Sony Pictures Imageworks /
//                                                 Blender Foundation; adapted from OSL)
//   Blender intern/cycles/kernel/svm/fractal_noise.h (Apache-2.0)
//   Blender intern/cycles/kernel/svm/noisetex.h  (Apache-2.0)
//   Blender intern/cycles/kernel/svm/wave.h      (Apache-2.0)
//   Blender intern/cycles/kernel/svm/voronoi.h   (Apache-2.0; smooth F1 and distance to
//                                                 edge after Inigo Quilez 2013, MIT)
// SPDX-FileCopyrightText: 2009-2010 Sony Pictures Imageworks Inc., et al.
// SPDX-FileCopyrightText: 2011-2022 Blender Foundation
// SPDX-License-Identifier: Apache-2.0 AND BSD-3-Clause AND MIT
// ============================================================================

#include "astroray/gpu_types.h"   // GVec3, HD

namespace astroray {
namespace proc {

// std::min / std::max / std::clamp semantics (argument order matters for NaN/-0).
HD inline float pmin(float a, float b) { return (b < a) ? b : a; }
HD inline float pmax(float a, float b) { return (a < b) ? b : a; }
HD inline float pclamp(float v, float lo, float hi) { return (v < lo) ? lo : (hi < v) ? hi : v; }
HD inline GVec3 pdiv(const GVec3& v, float s) { return GVec3(v.x / s, v.y / s, v.z / s); }

// ---------------------------------------------------------------------------
// Hash family - Cycles util/hash.h (Apache-2.0). Bit-identical to Cycles.
// ---------------------------------------------------------------------------
HD inline uint32_t hash_rot(uint32_t x, int k) {
    return (x << k) | (x >> (32 - k));
}

HD inline void hash_mix(uint32_t& a, uint32_t& b, uint32_t& c) {
    a -= c; a ^= hash_rot(c, 4); c += b;
    b -= a; b ^= hash_rot(a, 6); a += c;
    c -= b; c ^= hash_rot(b, 8); b += a;
    a -= c; a ^= hash_rot(c, 16); c += b;
    b -= a; b ^= hash_rot(a, 19); a += c;
    c -= b; c ^= hash_rot(b, 4); b += a;
}

HD inline void hash_final(uint32_t& a, uint32_t& b, uint32_t& c) {
    c ^= b; c -= hash_rot(b, 14);
    a ^= c; a -= hash_rot(c, 11);
    b ^= a; b -= hash_rot(a, 25);
    c ^= b; c -= hash_rot(b, 16);
    a ^= c; a -= hash_rot(c, 4);
    b ^= a; b -= hash_rot(a, 14);
    c ^= b; c -= hash_rot(b, 24);
}

HD inline uint32_t hash_uint(uint32_t kx) {
    uint32_t a, b, c;
    a = b = c = 0xdeadbeefu + (1u << 2) + 13u;
    a += kx;
    hash_final(a, b, c);
    return c;
}

HD inline uint32_t hash_uint2(uint32_t kx, uint32_t ky) {
    uint32_t a, b, c;
    a = b = c = 0xdeadbeefu + (2u << 2) + 13u;
    b += ky;
    a += kx;
    hash_final(a, b, c);
    return c;
}

HD inline uint32_t hash_uint3(uint32_t kx, uint32_t ky, uint32_t kz) {
    uint32_t a, b, c;
    a = b = c = 0xdeadbeefu + (3u << 2) + 13u;
    c += kz;
    b += ky;
    a += kx;
    hash_final(a, b, c);
    return c;
}

HD inline uint32_t hash_uint4(uint32_t kx, uint32_t ky, uint32_t kz, uint32_t kw) {
    uint32_t a, b, c;
    a = b = c = 0xdeadbeefu + (4u << 2) + 13u;
    a += kx;
    b += ky;
    c += kz;
    hash_mix(a, b, c);
    a += kw;
    hash_final(a, b, c);
    return c;
}

HD inline float uint_to_float_incl(uint32_t n) {
    return (float)n * (1.0f / (float)0xFFFFFFFFu);
}

HD inline uint32_t float_as_uint(float f) {
    union { float f; uint32_t u; } conv;
    conv.f = f;
    return conv.u;
}

HD inline float hash_uint_to_float(uint32_t kx) { return uint_to_float_incl(hash_uint(kx)); }
HD inline float hash_uint2_to_float(uint32_t kx, uint32_t ky) {
    return uint_to_float_incl(hash_uint2(kx, ky));
}
HD inline float hash_uint3_to_float(uint32_t kx, uint32_t ky, uint32_t kz) {
    return uint_to_float_incl(hash_uint3(kx, ky, kz));
}
HD inline float hash_uint4_to_float(uint32_t kx, uint32_t ky, uint32_t kz, uint32_t kw) {
    return uint_to_float_incl(hash_uint4(kx, ky, kz, kw));
}
HD inline float hash_float_to_float(float k) { return hash_uint_to_float(float_as_uint(k)); }
HD inline float hash_float2_to_float(float kx, float ky) {
    return hash_uint2_to_float(float_as_uint(kx), float_as_uint(ky));
}
HD inline float hash_float3_to_float(float kx, float ky, float kz) {
    return hash_uint3_to_float(float_as_uint(kx), float_as_uint(ky), float_as_uint(kz));
}
HD inline float hash_float4_to_float(float kx, float ky, float kz, float kw) {
    return hash_uint4_to_float(float_as_uint(kx), float_as_uint(ky), float_as_uint(kz),
                               float_as_uint(kw));
}

// PCG3D hash for int3 -> float3 (Voronoi cell colours). Cycles util/hash.h
// hash_pcg3d_i runs on SIGNED int3, so the >>16 is an ARITHMETIC shift: emulate it
// through int32_t for the shift only (the rest stays unsigned for defined wraparound).
HD inline uint32_t pcg_xorshift_signed16(uint32_t v) {
    return v ^ (uint32_t)(((int32_t)v) >> 16);
}

HD inline GVec3 hash_int3_to_float3(int ix, int iy, int iz) {
    uint32_t vx = (uint32_t)ix;
    uint32_t vy = (uint32_t)iy;
    uint32_t vz = (uint32_t)iz;
    vx = vx * 1664525u + 1013904223u;
    vy = vy * 1664525u + 1013904223u;
    vz = vz * 1664525u + 1013904223u;
    vx += vy * vz;
    vy += vz * vx;
    vz += vx * vy;
    vx = pcg_xorshift_signed16(vx);
    vy = pcg_xorshift_signed16(vy);
    vz = pcg_xorshift_signed16(vz);
    vx += vy * vz;
    vy += vz * vx;
    vz += vx * vy;
    vx = vx & 0x7FFFFFFFu;
    vy = vy & 0x7FFFFFFFu;
    vz = vz & 0x7FFFFFFFu;
    return GVec3((float)vx * (1.0f / (float)0x7FFFFFFFu),
                 (float)vy * (1.0f / (float)0x7FFFFFFFu),
                 (float)vz * (1.0f / (float)0x7FFFFFFFu));
}

HD inline GVec3 hash_float3_to_float3(float kx, float ky, float kz) {
    return GVec3(hash_float3_to_float(kx, ky, kz),
                 hash_float4_to_float(kx, ky, kz, 1.0f),
                 hash_float4_to_float(kx, ky, kz, 2.0f));
}

// ---------------------------------------------------------------------------
// Perlin noise - Cycles kernel/svm/noise.h (BSD-3-Clause, adapted from OSL).
// ---------------------------------------------------------------------------
HD inline float floorfrac(float x, int* i) {
    *i = (int)floorf(x);
    return x - (float)(*i);
}

HD inline float negate_if(float val, int condition) { return condition ? -val : val; }

HD inline float fade(float t) { return t * t * t * (t * (t * 6.0f - 15.0f) + 10.0f); }

HD inline float grad3(int hash, float x, float y, float z) {
    int h = hash & 15;
    float u = (h < 8) ? x : y;
    float vt = ((h == 12) || (h == 14)) ? x : z;
    float v = (h < 4) ? y : vt;
    return negate_if(u, h & 1) + negate_if(v, h & 2);
}

HD inline float tri_mix(float v0, float v1, float v2, float v3,
                        float v4, float v5, float v6, float v7,
                        float x, float y, float z) {
    float x1 = 1.0f - x;
    float y1 = 1.0f - y;
    float z1 = 1.0f - z;
    return z1 * (y1 * (v0 * x1 + v1 * x) + y * (v2 * x1 + v3 * x)) +
           z * (y1 * (v4 * x1 + v5 * x) + y * (v6 * x1 + v7 * x));
}

HD inline float perlin_3d(float x, float y, float z) {
    int X, Y, Z;
    float fx = floorfrac(x, &X);
    float fy = floorfrac(y, &Y);
    float fz = floorfrac(z, &Z);
    float u = fade(fx);
    float v = fade(fy);
    float w = fade(fz);
    float r = tri_mix(
        grad3(hash_uint3(X, Y, Z), fx, fy, fz),
        grad3(hash_uint3(X + 1, Y, Z), fx - 1.0f, fy, fz),
        grad3(hash_uint3(X, Y + 1, Z), fx, fy - 1.0f, fz),
        grad3(hash_uint3(X + 1, Y + 1, Z), fx - 1.0f, fy - 1.0f, fz),
        grad3(hash_uint3(X, Y, Z + 1), fx, fy, fz - 1.0f),
        grad3(hash_uint3(X + 1, Y, Z + 1), fx - 1.0f, fy, fz - 1.0f),
        grad3(hash_uint3(X, Y + 1, Z + 1), fx, fy - 1.0f, fz - 1.0f),
        grad3(hash_uint3(X + 1, Y + 1, Z + 1), fx - 1.0f, fy - 1.0f, fz - 1.0f),
        u, v, w);
    return r;
}

HD inline float noise_scale3(float result) { return 0.9820f * result; }

HD inline float snoise_3d(GVec3 p) {
    // Precision guard per Cycles noise.h snoise_3d: repeat every 100000.
    const float precision_limit = 1000000.0f;
    GVec3 correction(0.0f);
    if (fabsf(p.x) >= precision_limit) correction.x = 0.5f;
    if (fabsf(p.y) >= precision_limit) correction.y = 0.5f;
    if (fabsf(p.z) >= precision_limit) correction.z = 0.5f;
    p.x = fmodf(p.x, 100000.0f) + correction.x;
    p.y = fmodf(p.y, 100000.0f) + correction.y;
    p.z = fmodf(p.z, 100000.0f) + correction.z;
    return noise_scale3(perlin_3d(p.x, p.y, p.z));
}

// ---------------------------------------------------------------------------
// Fractal noise - Cycles kernel/svm/fractal_noise.h (Apache-2.0).
// ---------------------------------------------------------------------------
HD inline float noise_fbm(GVec3 p, float detail, float roughness, float lacunarity,
                          bool normalize) {
    float fscale = 1.0f;
    float amp = 1.0f;
    float maxamp = 0.0f;
    float sum = 0.0f;
    int octaves = (int)detail;
    for (int i = 0; i <= octaves; i++) {
        float t = snoise_3d(p * fscale);
        sum += t * amp;
        maxamp += amp;
        amp *= roughness;
        fscale *= lacunarity;
    }
    float rmd = detail - floorf(detail);
    if (rmd != 0.0f) {
        float t = snoise_3d(p * fscale);
        float sum2 = sum + t * amp;
        float result = normalize ?
            (0.5f * sum / maxamp + 0.5f) * (1.0f - rmd) +
                (0.5f * sum2 / (maxamp + amp) + 0.5f) * rmd :
            sum * (1.0f - rmd) + sum2 * rmd;
        return result;
    }
    return normalize ? 0.5f * sum / maxamp + 0.5f : sum;
}

HD inline float noise_multi_fractal(GVec3 p, float detail, float roughness, float lacunarity) {
    float value = 1.0f;
    float pwr = 1.0f;
    int octaves = (int)detail;
    for (int i = 0; i <= octaves; i++) {
        value *= (pwr * snoise_3d(p) + 1.0f);
        pwr *= roughness;
        p = p * lacunarity;
    }
    float rmd = detail - floorf(detail);
    if (rmd != 0.0f) {
        value *= (rmd * pwr * snoise_3d(p) + 1.0f);
    }
    return value;
}

HD inline float noise_hetero_terrain(GVec3 p, float detail, float roughness, float lacunarity,
                                     float offset) {
    float pwr = roughness;
    float value = offset + snoise_3d(p);
    p = p * lacunarity;
    int octaves = (int)detail;
    for (int i = 1; i <= octaves; i++) {
        float increment = (snoise_3d(p) + offset) * pwr * value;
        value += increment;
        pwr *= roughness;
        p = p * lacunarity;
    }
    float rmd = detail - floorf(detail);
    if (rmd != 0.0f) {
        float increment = (snoise_3d(p) + offset) * pwr * value;
        value += rmd * increment;
    }
    return value;
}

HD inline float noise_hybrid_multi_fractal(GVec3 p, float detail, float roughness,
                                           float lacunarity, float offset, float gain) {
    float pwr = 1.0f;
    float value = 0.0f;
    float weight = 1.0f;
    int octaves = (int)detail;
    for (int i = 0; (weight > 0.001f) && (i <= octaves); i++) {
        weight = pmin(weight, 1.0f);
        float signal = (snoise_3d(p) + offset) * pwr;
        pwr *= roughness;
        value += weight * signal;
        weight *= gain * signal;
        p = p * lacunarity;
    }
    float rmd = detail - floorf(detail);
    if ((rmd != 0.0f) && (weight > 0.001f)) {
        weight = pmin(weight, 1.0f);
        float signal = (snoise_3d(p) + offset) * pwr;
        value += rmd * weight * signal;
    }
    return value;
}

HD inline float noise_ridged_multi_fractal(GVec3 p, float detail, float roughness,
                                           float lacunarity, float offset, float gain) {
    float pwr = roughness;
    float signal = offset - fabsf(snoise_3d(p));
    signal *= signal;
    float value = signal;
    float weight = 1.0f;
    int octaves = (int)detail;
    for (int i = 1; i <= octaves; i++) {
        p = p * lacunarity;
        weight = pclamp(signal * gain, 0.0f, 1.0f);
        signal = offset - fabsf(snoise_3d(p));
        signal *= signal;
        signal *= weight;
        value += signal * pwr;
        pwr *= roughness;
    }
    return value;
}

// ---------------------------------------------------------------------------
// Noise Texture node - Cycles kernel/svm/noisetex.h noise_texture_3d (Apache-2.0).
// type: 0=fBM, 1=multifractal, 2=hybrid, 3=ridged, 4=hetero terrain.
// ---------------------------------------------------------------------------
struct NoiseParams {
    float scale, detail, roughness, lacunarity, offset, gain, distortion;
    int type;
    int normalize;
};

// Cycles noisetex.h random_float3_offset(seed) = 100 + hash_float2_to_float(seed, k) * 100
// for the five seeds noise_texture uses, precomputed as a fused multiply-add (one
// rounding): the value the production CPU build (MSVC /arch:AVX2 /fp:fast) produced and
// nvcc produces. Whether a compiler fuses it depends on inlining (GCC -mfma folded the
// old constant-seed call unfused), and the one-ulp offset change is amplified by the
// fractal octaves to ~1e-4 in the noise value, so the table pins it.
HD inline GVec3 random_float3_offset(int seed) {
    switch (seed) {
        case 0:  return GVec3(0x1.741004p+7f, 0x1.cbd2e6p+6f, 0x1.34e51ep+7f);
        case 1:  return GVec3(0x1.8fae14p+7f, 0x1.4495cep+7f, 0x1.3418b2p+7f);
        case 2:  return GVec3(0x1.be890ep+6f, 0x1.3abd22p+7f, 0x1.8e2d1cp+7f);
        case 3:  return GVec3(0x1.4ae3fcp+7f, 0x1.458954p+7f, 0x1.82d11ap+7f);
        default: return GVec3(0x1.37296ep+7f, 0x1.624f2cp+7f, 0x1.1447b2p+7f);
    }
}

HD inline float noise_select(GVec3 p, float det, float rough, float lac, float off, float g,
                             int type, bool norm) {
    switch (type) {
        case 1: return noise_multi_fractal(p, det, rough, lac);
        case 2: return noise_hybrid_multi_fractal(p, det, rough, lac, off, g);
        case 3: return noise_ridged_multi_fractal(p, det, rough, lac, off, g);
        case 4: return noise_hetero_terrain(p, det, rough, lac, off);
        case 0:
        default:
            return noise_fbm(p, det, rough, lac, norm);
    }
}

// Color output (Fac, noise(+offset 3), noise(+offset 4)); Fac = .x.
HD inline GVec3 noise_texture(const NoiseParams& np, GVec3 p) {
    // Clamp detail [0,15], roughness >= 0 per svm_node_tex_noise.
    float det = pclamp(np.detail, 0.0f, 15.0f);
    float rough = pmax(np.roughness, 0.0f);
    bool norm = np.normalize != 0;
    GVec3 co = p * np.scale;
    GVec3 distorted = co;
    if (np.distortion != 0.0f) {
        distorted.x += snoise_3d(co + random_float3_offset(0)) * np.distortion;
        distorted.y += snoise_3d(co + random_float3_offset(1)) * np.distortion;
        distorted.z += snoise_3d(co + random_float3_offset(2)) * np.distortion;
    }
    float fac = noise_select(distorted, det, rough, np.lacunarity, np.offset, np.gain, np.type, norm);
    float r = noise_select(distorted + random_float3_offset(3), det, rough, np.lacunarity,
                           np.offset, np.gain, np.type, norm);
    float g = noise_select(distorted + random_float3_offset(4), det, rough, np.lacunarity,
                           np.offset, np.gain, np.type, norm);
    return GVec3(fac, r, g);
}

// ---------------------------------------------------------------------------
// Wave Texture node - Cycles kernel/svm/wave.h svm_wave (Apache-2.0).
// waveType 0=bands, 1=rings; bands 0=X 1=Y 2=Z 3=diagonal; rings 0=X 1=Y 2=Z
// 3=spherical; profile 0=sine 1=saw 2=triangle. Colour = lerp(colorLow, colorHigh, t).
// ---------------------------------------------------------------------------
struct WaveParams {
    int waveType, bandsDirection, ringsDirection, profile;
    float scale, distortion, detail, detailScale, detailRoughness, phaseOffset;
    GVec3 colorLow, colorHigh;
};

HD inline GVec3 wave_texture(const WaveParams& wp, GVec3 p) {
    // Precision guard per Cycles.
    GVec3 pp = (p + GVec3(0.000001f)) * 0.999999f;
    pp = pp * wp.scale;

    float n = 0.0f;
    if (wp.waveType == 0) {
        switch (wp.bandsDirection) {
            case 0: n = pp.x * 20.0f; break;
            case 1: n = pp.y * 20.0f; break;
            case 2: n = pp.z * 20.0f; break;
            case 3: n = (pp.x + pp.y + pp.z) * 10.0f; break;
        }
    } else {
        GVec3 rp = pp;
        switch (wp.ringsDirection) {
            case 0: rp.x = 0.0f; break;
            case 1: rp.y = 0.0f; break;
            case 2: rp.z = 0.0f; break;
            case 3: break;
        }
        float r = sqrtf(rp.x*rp.x + rp.y*rp.y + rp.z*rp.z);
        n = r * 20.0f;
    }

    n += wp.phaseOffset;

    if (wp.distortion != 0.0f) {
        // Distortion via signed fBM (lacunarity fixed 2.0, normalized).
        float distort = noise_fbm(pp * wp.detailScale, wp.detail, wp.detailRoughness, 2.0f, true);
        n += wp.distortion * (distort * 2.0f - 1.0f);
    }

    float t;
    const float pi = 3.14159265358979323846f;
    const float two_pi = 2.0f * pi;
    switch (wp.profile) {
        case 1: {  // Saw
            float frac = n / two_pi;
            t = frac - floorf(frac);
            break;
        }
        case 2: {  // Triangle
            float frac = n / two_pi;
            t = fabsf(frac - floorf(frac + 0.5f)) * 2.0f;
            break;
        }
        default: {  // Sine
            t = 0.5f + 0.5f * sinf(n - pi / 2.0f);
            break;
        }
    }

    return wp.colorLow * (1.0f - t) + wp.colorHigh * t;
}

// ---------------------------------------------------------------------------
// Voronoi Texture node - Cycles kernel/svm/voronoi.h (Apache-2.0; IQ 2013 MIT).
// Metrics: 0=Euclidean 1=Manhattan 2=Chebychev 3=Minkowski(exponent).
// Features (Blender order): 0=F1 1=Smooth F1 2=F2 3=Distance to Edge 4=N-Sphere Radius;
// standalone-only 5=F1+F2, 6=F2-F1. Params are CONDITIONED (voronoi_condition).
// ---------------------------------------------------------------------------
struct VoronoiParams {
    float scale, detail, roughness, lacunarity, smoothness, exponent, randomness;
    float maxDistance;
    int normalize, outputColor, distMetric, feature;
    GVec3 colorLow, colorHigh;
};

struct VoronoiOut {
    float distance;
    GVec3 color;
    GVec3 position;
    float radius;
};

HD inline float voronoi_distance(const VoronoiParams& vp, const GVec3& a, const GVec3& b) {
    GVec3 d = a - b;
    switch (vp.distMetric) {
        case 1: return fabsf(d.x) + fabsf(d.y) + fabsf(d.z);
        case 2: return pmax(pmax(fabsf(d.x), fabsf(d.y)), fabsf(d.z));
        case 3: {
            float sum = powf(fabsf(d.x), vp.exponent) +
                        powf(fabsf(d.y), vp.exponent) +
                        powf(fabsf(d.z), vp.exponent);
            return powf(sum, 1.0f / vp.exponent);
        }
        default: return sqrtf(d.dot(d));
    }
}

// Cycles svm_node_tex_voronoi parameter conditioning (host side, once per texture).
HD inline void voronoi_condition(VoronoiParams& vp) {
    vp.detail = pclamp(vp.detail, 0.0f, 15.0f);
    vp.roughness = pclamp(vp.roughness, 0.0f, 1.0f);
    vp.randomness = pclamp(vp.randomness, 0.0f, 1.0f);
    vp.smoothness = pclamp(vp.smoothness / 2.0f, 0.0f, 0.5f);  // UI 0-1 -> Cycles 0-0.5
    GVec3 ones(0.5f + 0.5f * vp.randomness);
    if (vp.feature == 3) {
        vp.maxDistance = 0.5f + 0.5f * vp.randomness;
    } else {
        vp.maxDistance = voronoi_distance(vp, GVec3(0.0f), ones);
        if (vp.feature == 2) vp.maxDistance *= 2.0f;
    }
}

// Neighbour cell index. The pkg115 CPU port held it in a float Vec3 before hashing,
// so it round-trips int -> float -> int (lossy beyond 2^24); kept for bit parity.
HD inline int voronoi_cell(int c) { return (int)(float)c; }

HD inline GVec3 voronoi_cell_hash(const GVec3& cellPositionF, int i, int j, int k) {
    return hash_int3_to_float3(voronoi_cell((int)cellPositionF.x + i),
                               voronoi_cell((int)cellPositionF.y + j),
                               voronoi_cell((int)cellPositionF.z + k));
}

HD inline GVec3 voronoi_cell_point(const VoronoiParams& vp, const GVec3& cellPositionF,
                                   int i, int j, int k) {
    return GVec3((float)i, (float)j, (float)k) +
        voronoi_cell_hash(cellPositionF, i, j, k) * vp.randomness;
}

HD inline VoronoiOut voronoi_f1(const VoronoiParams& vp, const GVec3& coord) {
    GVec3 cellPositionF(floorf(coord.x), floorf(coord.y), floorf(coord.z));
    GVec3 localPosition = coord - cellPositionF;
    float minDistance = 1e9f;
    GVec3 targetOffset(0.0f);
    GVec3 targetPosition(0.0f);
    for (int k = -1; k <= 1; ++k)
        for (int j = -1; j <= 1; ++j)
            for (int i = -1; i <= 1; ++i) {
                GVec3 pointPosition = voronoi_cell_point(vp, cellPositionF, i, j, k);
                float d = voronoi_distance(vp, pointPosition, localPosition);
                if (d < minDistance) {
                    minDistance = d;
                    targetOffset = GVec3((float)i, (float)j, (float)k);
                    targetPosition = pointPosition;
                }
            }
    VoronoiOut out;
    out.distance = minDistance;
    GVec3 targetCell = cellPositionF + targetOffset;
    out.color = hash_int3_to_float3((int)targetCell.x, (int)targetCell.y, (int)targetCell.z);
    out.position = targetPosition + cellPositionF;
    out.radius = 0.0f;
    return out;
}

// 5x5x5 neighbourhood, polynomial smooth-min.
HD inline VoronoiOut voronoi_smooth_f1(const VoronoiParams& vp, const GVec3& coord) {
    GVec3 cellPositionF(floorf(coord.x), floorf(coord.y), floorf(coord.z));
    GVec3 localPosition = coord - cellPositionF;
    float smoothDistance = 1e9f;
    GVec3 smoothColor(0.0f);
    GVec3 smoothPosition(0.0f);
    float h = -1.0f;
    for (int k = -2; k <= 2; ++k)
        for (int j = -2; j <= 2; ++j)
            for (int i = -2; i <= 2; ++i) {
                GVec3 pointPosition = voronoi_cell_point(vp, cellPositionF, i, j, k);
                float d = voronoi_distance(vp, pointPosition, localPosition);
                GVec3 cellColor = voronoi_cell_hash(cellPositionF, i, j, k);
                h = (h == -1.0f) ? 1.0f :
                    pclamp(0.5f + 0.5f * (smoothDistance - d) / vp.smoothness, 0.0f, 1.0f);
                h = h * h * (3.0f - 2.0f * h);
                float correction = vp.smoothness * h * (1.0f - h);
                smoothDistance = smoothDistance * (1.0f - h) + d * h - correction;
                correction /= 1.0f + 3.0f * vp.smoothness;
                smoothColor = smoothColor * (1.0f - h) + cellColor * h - GVec3(correction);
                smoothPosition = smoothPosition * (1.0f - h) + pointPosition * h - GVec3(correction);
            }
    VoronoiOut out;
    out.distance = smoothDistance;
    out.color = smoothColor;
    out.position = smoothPosition + cellPositionF;
    out.radius = 0.0f;
    return out;
}

HD inline VoronoiOut voronoi_f2(const VoronoiParams& vp, const GVec3& coord) {
    GVec3 cellPositionF(floorf(coord.x), floorf(coord.y), floorf(coord.z));
    GVec3 localPosition = coord - cellPositionF;
    float dist1 = 1e9f, dist2 = 1e9f;
    GVec3 offset1(0.0f), offset2(0.0f);
    GVec3 position1(0.0f), position2(0.0f);
    for (int k = -1; k <= 1; ++k)
        for (int j = -1; j <= 1; ++j)
            for (int i = -1; i <= 1; ++i) {
                GVec3 cellOffset((float)i, (float)j, (float)k);
                GVec3 pointPosition = voronoi_cell_point(vp, cellPositionF, i, j, k);
                float d = voronoi_distance(vp, pointPosition, localPosition);
                if (d < dist1) {
                    dist2 = dist1; offset2 = offset1; position2 = position1;
                    dist1 = d; offset1 = cellOffset; position1 = pointPosition;
                } else if (d < dist2) {
                    dist2 = d; offset2 = cellOffset; position2 = pointPosition;
                }
            }
    VoronoiOut out;
    out.distance = dist2;
    GVec3 cell2 = cellPositionF + offset2;
    out.color = hash_int3_to_float3((int)cell2.x, (int)cell2.y, (int)cell2.z);
    out.position = position2 + cellPositionF;
    out.radius = 0.0f;
    return out;
}

// IQ two-pass perpendicular edge distance; first pass squared Euclidean (metric ignored).
HD inline VoronoiOut voronoi_distance_to_edge(const VoronoiParams& vp, const GVec3& coord) {
    GVec3 cellPositionF(floorf(coord.x), floorf(coord.y), floorf(coord.z));
    GVec3 localPosition = coord - cellPositionF;
    float minDistance = 1e9f;
    GVec3 targetOffset(0.0f);
    GVec3 vectorToClosest(0.0f);
    for (int k = -1; k <= 1; ++k)
        for (int j = -1; j <= 1; ++j)
            for (int i = -1; i <= 1; ++i) {
                GVec3 vectorToPoint = voronoi_cell_point(vp, cellPositionF, i, j, k)
                    - localPosition;
                float d = vectorToPoint.dot(vectorToPoint);
                if (d < minDistance) {
                    minDistance = d;
                    targetOffset = GVec3((float)i, (float)j, (float)k);
                    vectorToClosest = vectorToPoint;
                }
            }
    minDistance = 1e9f;
    for (int k = -1; k <= 1; ++k)
        for (int j = -1; j <= 1; ++j)
            for (int i = -1; i <= 1; ++i) {
                GVec3 vectorToPoint = voronoi_cell_point(vp, cellPositionF, i, j, k)
                    - localPosition;
                GVec3 perpendicularToEdge = vectorToPoint - vectorToClosest;
                if (perpendicularToEdge.dot(perpendicularToEdge) > 1e-4f) {
                    GVec3 perpN = pdiv(perpendicularToEdge,
                                       sqrtf(perpendicularToEdge.dot(perpendicularToEdge)));
                    float d = ((vectorToClosest + vectorToPoint) * 0.5f).dot(perpN);
                    minDistance = pmin(minDistance, d);
                }
            }
    VoronoiOut out;
    out.distance = minDistance;
    GVec3 targetCell = cellPositionF + targetOffset;
    out.color = hash_int3_to_float3((int)targetCell.x, (int)targetCell.y, (int)targetCell.z);
    out.position = vectorToClosest + localPosition + cellPositionF;
    out.radius = 0.0f;
    return out;
}

// Half the distance between the closest point and its closest neighbour.
HD inline VoronoiOut voronoi_n_sphere_radius(const VoronoiParams& vp, const GVec3& coord) {
    GVec3 cellPositionF(floorf(coord.x), floorf(coord.y), floorf(coord.z));
    GVec3 localPosition = coord - cellPositionF;
    float minDistance = 1e9f;
    GVec3 targetOffset(0.0f);
    GVec3 targetPosition(0.0f);
    for (int k = -1; k <= 1; ++k)
        for (int j = -1; j <= 1; ++j)
            for (int i = -1; i <= 1; ++i) {
                GVec3 pointPosition = voronoi_cell_point(vp, cellPositionF, i, j, k);
                float d = voronoi_distance(vp, pointPosition, localPosition);
                if (d < minDistance) {
                    minDistance = d;
                    targetOffset = GVec3((float)i, (float)j, (float)k);
                    targetPosition = pointPosition;
                }
            }
    float closestNeighborDist = 1e9f;
    for (int k = -1; k <= 1; ++k)
        for (int j = -1; j <= 1; ++j)
            for (int i = -1; i <= 1; ++i) {
                if (i == 0 && j == 0 && k == 0) continue;
                GVec3 cellOffset((float)i, (float)j, (float)k);
                GVec3 pointPosition = cellOffset +
                    hash_int3_to_float3(voronoi_cell((int)cellPositionF.x + (int)targetOffset.x + i),
                                        voronoi_cell((int)cellPositionF.y + (int)targetOffset.y + j),
                                        voronoi_cell((int)cellPositionF.z + (int)targetOffset.z + k)) *
                    vp.randomness;
                float d = voronoi_distance(vp, GVec3(0.0f), pointPosition);
                closestNeighborDist = pmin(closestNeighborDist, d);
            }
    VoronoiOut out;
    out.distance = minDistance;
    GVec3 targetCell = cellPositionF + targetOffset;
    out.color = hash_int3_to_float3((int)targetCell.x, (int)targetCell.y, (int)targetCell.z);
    out.position = targetPosition + cellPositionF;
    out.radius = closestNeighborDist / 2.0f;
    return out;
}

HD inline VoronoiOut voronoi_feature(const VoronoiParams& vp, const GVec3& coord) {
    switch (vp.feature) {
        case 1: return voronoi_smooth_f1(vp, coord);
        case 2: return voronoi_f2(vp, coord);
        case 3: return voronoi_distance_to_edge(vp, coord);
        case 4: return voronoi_n_sphere_radius(vp, coord);
        default: return voronoi_f1(vp, coord);
    }
}

// Cycles fractal_voronoi_x_fx (octave loop with normalize).
HD inline VoronoiOut fractal_voronoi(const VoronoiParams& vp, const GVec3& coord) {
    float octaveScale = 1.0f;
    float amplitude = 1.0f;
    float maxAmplitude = 0.0f;
    VoronoiOut sum;
    sum.distance = 0.0f;
    sum.color = GVec3(0.0f);
    sum.position = GVec3(0.0f);
    sum.radius = 0.0f;
    int octaves = (int)ceilf(vp.detail);
    for (int i = 0; i <= octaves; ++i) {
        VoronoiOut octave = voronoi_feature(vp, coord * octaveScale);
        if (i <= (int)vp.detail) {
            sum.distance += octave.distance * amplitude;
            sum.color = sum.color + octave.color * amplitude;
            sum.position = sum.position + octave.position * amplitude;
            sum.radius += octave.radius * amplitude;
            maxAmplitude += amplitude;
        } else {
            float rmd = vp.detail - floorf(vp.detail);
            sum.distance = sum.distance * (1.0f - rmd) + (sum.distance + octave.distance * amplitude) * rmd;
            sum.color = sum.color * (1.0f - rmd) + (sum.color + octave.color * amplitude) * rmd;
            sum.position = sum.position * (1.0f - rmd) + (sum.position + octave.position * amplitude) * rmd;
            sum.radius = sum.radius * (1.0f - rmd) + (sum.radius + octave.radius * amplitude) * rmd;
            if (vp.normalize) {
                maxAmplitude = maxAmplitude * (1.0f - rmd) + (maxAmplitude + amplitude) * rmd;
            }
        }
        octaveScale *= vp.lacunarity;
        amplitude *= vp.roughness;
    }
    if (vp.normalize) {
        sum.distance /= maxAmplitude * vp.maxDistance;
        sum.color = pdiv(sum.color, maxAmplitude);
    }
    // Cycles: output.position = safe_divide(position, params.scale).
    sum.position = (vp.scale != 0.0f) ? pdiv(sum.position, vp.scale) : sum.position;
    return sum;
}

// Features 0-4 always go through the fractal wrapper (Cycles calls it even at
// detail 0, so normalize applies there too); 5/6 have no Cycles counterpart.
HD inline VoronoiOut voronoi_eval_full(const VoronoiParams& vp, const GVec3& p) {
    GVec3 coord = p * vp.scale;
    if (vp.feature <= 4) return fractal_voronoi(vp, coord);
    switch (vp.feature) {
        case 5: {
            VoronoiOut f1 = voronoi_f1(vp, coord);
            VoronoiOut f2 = voronoi_f2(vp, coord);
            f1.distance = (f1.distance + f2.distance) * 0.5f;
            return f1;
        }
        case 6: {
            VoronoiOut f1 = voronoi_f1(vp, coord);
            VoronoiOut f2 = voronoi_f2(vp, coord);
            f1.distance = f2.distance - f1.distance;
            return f1;
        }
        default: return voronoi_f1(vp, coord);
    }
}

// Color output (hashed cell colour) or Distance as a colorLow->colorHigh lerp.
HD inline GVec3 voronoi_texture(const VoronoiParams& vp, GVec3 p) {
    VoronoiOut out = voronoi_eval_full(vp, p);
    if (vp.outputColor) return out.color;
    float t = pclamp(out.distance, 0.0f, 1.0f);
    return vp.colorLow * (1.0f - t) + vp.colorHigh * t;
}

// ---------------------------------------------------------------------------
// Device-side tagged evaluator (GPU per-hit procedurals, #1007). One entry per
// procedural the GPU evaluates per hit (scene_upload.cu lowerProcTexture). A
// CoordProgramTexture (pkg277) is the child's entry plus the warp: p is replaced
// by svm_eval(program warpProg, {p, input warpInput sampled at p}) before the child
// runs (see gpu_procTexEval).
// ---------------------------------------------------------------------------
enum GProcKind : int { G_PROC_NOISE = 0, G_PROC_WAVE = 1, G_PROC_VORONOI = 2 };

struct GProcTexture {
    int kind = G_PROC_NOISE;
    int warpProg = -1;   // CoordProgramTexture warp program (index into programs), -1 none
    int warpInput = -1;     // GProcTexture index of the warp's texture input, -1 none
    NoiseParams noise{};
    WaveParams wave{};
    VoronoiParams voronoi{};
};

HD inline GVec3 proc_texture_eval(const GProcTexture& t, GVec3 p) {
    switch (t.kind) {
        case G_PROC_WAVE: return wave_texture(t.wave, p);
        case G_PROC_VORONOI: return voronoi_texture(t.voronoi, p);
        default: return noise_texture(t.noise, p);
    }
}

}  // namespace proc
}  // namespace astroray

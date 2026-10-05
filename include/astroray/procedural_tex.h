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

// #881 - the Noise Texture's 1D / 2D / 4D dimensions (Cycles noise.h, scalar
// non-SSE path; the SSE path computes the same values). PVec2 / PVec4 stand in
// for Cycles float2 / float4.
struct PVec2 { float x, y; };
struct PVec4 { float x, y, z, w; };
HD inline PVec2 operator*(const PVec2& a, float s) { return PVec2{a.x * s, a.y * s}; }
HD inline PVec2 operator+(const PVec2& a, const PVec2& b) { return PVec2{a.x + b.x, a.y + b.y}; }
HD inline PVec4 operator*(const PVec4& a, float s) {
    return PVec4{a.x * s, a.y * s, a.z * s, a.w * s};
}
HD inline PVec4 operator+(const PVec4& a, const PVec4& b) {
    return PVec4{a.x + b.x, a.y + b.y, a.z + b.z, a.w + b.w};
}

// Cycles util/math_base.h mix().
HD inline float pmix(float a, float b, float t) { return a + t * (b - a); }

HD inline float grad1(int hash, float x) {
    int h = hash & 15;
    float g = (float)(1 + (h & 7));
    return negate_if(g, h & 8) * x;
}

HD inline float perlin_1d(float x) {
    int X;
    float fx = floorfrac(x, &X);
    float u = fade(fx);
    return pmix(grad1(hash_uint(X), fx), grad1(hash_uint(X + 1), fx - 1.0f), u);
}

HD inline float bi_mix(float v0, float v1, float v2, float v3, float x, float y) {
    float x1 = 1.0f - x;
    return (1.0f - y) * (v0 * x1 + v1 * x) + y * (v2 * x1 + v3 * x);
}

HD inline float grad2(int hash, float x, float y) {
    int h = hash & 7;
    float u = h < 4 ? x : y;
    float v = 2.0f * (h < 4 ? y : x);
    return negate_if(u, h & 1) + negate_if(v, h & 2);
}

HD inline float perlin_2d(float x, float y) {
    int X, Y;
    float fx = floorfrac(x, &X);
    float fy = floorfrac(y, &Y);
    float u = fade(fx);
    float v = fade(fy);
    return bi_mix(grad2(hash_uint2(X, Y), fx, fy),
                  grad2(hash_uint2(X + 1, Y), fx - 1.0f, fy),
                  grad2(hash_uint2(X, Y + 1), fx, fy - 1.0f),
                  grad2(hash_uint2(X + 1, Y + 1), fx - 1.0f, fy - 1.0f),
                  u, v);
}

HD inline float grad4(int hash, float x, float y, float z, float w) {
    int h = hash & 31;
    float u = h < 24 ? x : y;
    float v = h < 16 ? y : z;
    float s = h < 8 ? z : w;
    return negate_if(u, h & 1) + negate_if(v, h & 2) + negate_if(s, h & 4);
}

HD inline float quad_mix(float v0, float v1, float v2, float v3, float v4, float v5, float v6,
                         float v7, float v8, float v9, float v10, float v11, float v12,
                         float v13, float v14, float v15, float x, float y, float z, float w) {
    return pmix(tri_mix(v0, v1, v2, v3, v4, v5, v6, v7, x, y, z),
                tri_mix(v8, v9, v10, v11, v12, v13, v14, v15, x, y, z), w);
}

HD inline float perlin_4d(float x, float y, float z, float w) {
    int X, Y, Z, W;
    float fx = floorfrac(x, &X);
    float fy = floorfrac(y, &Y);
    float fz = floorfrac(z, &Z);
    float fw = floorfrac(w, &W);
    float u = fade(fx);
    float v = fade(fy);
    float t = fade(fz);
    float s = fade(fw);
    return quad_mix(
        grad4(hash_uint4(X, Y, Z, W), fx, fy, fz, fw),
        grad4(hash_uint4(X + 1, Y, Z, W), fx - 1.0f, fy, fz, fw),
        grad4(hash_uint4(X, Y + 1, Z, W), fx, fy - 1.0f, fz, fw),
        grad4(hash_uint4(X + 1, Y + 1, Z, W), fx - 1.0f, fy - 1.0f, fz, fw),
        grad4(hash_uint4(X, Y, Z + 1, W), fx, fy, fz - 1.0f, fw),
        grad4(hash_uint4(X + 1, Y, Z + 1, W), fx - 1.0f, fy, fz - 1.0f, fw),
        grad4(hash_uint4(X, Y + 1, Z + 1, W), fx, fy - 1.0f, fz - 1.0f, fw),
        grad4(hash_uint4(X + 1, Y + 1, Z + 1, W), fx - 1.0f, fy - 1.0f, fz - 1.0f, fw),
        grad4(hash_uint4(X, Y, Z, W + 1), fx, fy, fz, fw - 1.0f),
        grad4(hash_uint4(X + 1, Y, Z, W + 1), fx - 1.0f, fy, fz, fw - 1.0f),
        grad4(hash_uint4(X, Y + 1, Z, W + 1), fx, fy - 1.0f, fz, fw - 1.0f),
        grad4(hash_uint4(X + 1, Y + 1, Z, W + 1), fx - 1.0f, fy - 1.0f, fz, fw - 1.0f),
        grad4(hash_uint4(X, Y, Z + 1, W + 1), fx, fy, fz - 1.0f, fw - 1.0f),
        grad4(hash_uint4(X + 1, Y, Z + 1, W + 1), fx - 1.0f, fy, fz - 1.0f, fw - 1.0f),
        grad4(hash_uint4(X, Y + 1, Z + 1, W + 1), fx, fy - 1.0f, fz - 1.0f, fw - 1.0f),
        grad4(hash_uint4(X + 1, Y + 1, Z + 1, W + 1), fx - 1.0f, fy - 1.0f, fz - 1.0f, fw - 1.0f),
        u, v, t, s);
}

// Precision guard as snoise_3d: repeat every 100000, shift by 0.5 past 1e6.
HD inline float noise_wrap(float x) {
    return fmodf(x, 100000.0f) + ((fabsf(x) >= 1000000.0f) ? 0.5f : 0.0f);
}

HD inline float snoise_1d(float p) { return 0.2500f * perlin_1d(noise_wrap(p)); }
HD inline float snoise_2d(PVec2 p) { return 0.6616f * perlin_2d(noise_wrap(p.x), noise_wrap(p.y)); }
HD inline float snoise_4d(PVec4 p) {
    return 0.8344f * perlin_4d(noise_wrap(p.x), noise_wrap(p.y), noise_wrap(p.z), noise_wrap(p.w));
}

// Overloads so the fractal templates below follow the point type (Cycles overloads
// noise_fbm etc. per dimension with identical bodies).
HD inline float snoise(float p) { return snoise_1d(p); }
HD inline float snoise(const PVec2& p) { return snoise_2d(p); }
HD inline float snoise(const GVec3& p) { return snoise_3d(p); }
HD inline float snoise(const PVec4& p) { return snoise_4d(p); }

// ---------------------------------------------------------------------------
// Fractal noise - Cycles kernel/svm/fractal_noise.h (Apache-2.0). T is float,
// PVec2, GVec3 or PVec4 (the 1D-4D Noise dimensions).
// ---------------------------------------------------------------------------
template<typename T>
HD inline float noise_fbm(T p, float detail, float roughness, float lacunarity, bool normalize) {
    float fscale = 1.0f;
    float amp = 1.0f;
    float maxamp = 0.0f;
    float sum = 0.0f;
    int octaves = (int)detail;
    for (int i = 0; i <= octaves; i++) {
        float t = snoise(p * fscale);
        sum += t * amp;
        maxamp += amp;
        amp *= roughness;
        fscale *= lacunarity;
    }
    float rmd = detail - floorf(detail);
    if (rmd != 0.0f) {
        float t = snoise(p * fscale);
        float sum2 = sum + t * amp;
        return normalize ?
            pmix(0.5f * sum / maxamp + 0.5f, 0.5f * sum2 / (maxamp + amp) + 0.5f, rmd) :
            pmix(sum, sum2, rmd);
    }
    return normalize ? 0.5f * sum / maxamp + 0.5f : sum;
}

template<typename T>
HD inline float noise_multi_fractal(T p, float detail, float roughness, float lacunarity) {
    float value = 1.0f;
    float pwr = 1.0f;
    int octaves = (int)detail;
    for (int i = 0; i <= octaves; i++) {
        value *= (pwr * snoise(p) + 1.0f);
        pwr *= roughness;
        p = p * lacunarity;
    }
    float rmd = detail - floorf(detail);
    if (rmd != 0.0f) {
        value *= (rmd * pwr * snoise(p) + 1.0f);
    }
    return value;
}

template<typename T>
HD inline float noise_hetero_terrain(T p, float detail, float roughness, float lacunarity,
                                     float offset) {
    float pwr = roughness;
    float value = offset + snoise(p);
    p = p * lacunarity;
    int octaves = (int)detail;
    for (int i = 1; i <= octaves; i++) {
        float increment = (snoise(p) + offset) * pwr * value;
        value += increment;
        pwr *= roughness;
        p = p * lacunarity;
    }
    float rmd = detail - floorf(detail);
    if (rmd != 0.0f) {
        float increment = (snoise(p) + offset) * pwr * value;
        value += rmd * increment;
    }
    return value;
}

template<typename T>
HD inline float noise_hybrid_multi_fractal(T p, float detail, float roughness,
                                           float lacunarity, float offset, float gain) {
    float pwr = 1.0f;
    float value = 0.0f;
    float weight = 1.0f;
    int octaves = (int)detail;
    for (int i = 0; (weight > 0.001f) && (i <= octaves); i++) {
        weight = pmin(weight, 1.0f);
        float signal = (snoise(p) + offset) * pwr;
        pwr *= roughness;
        value += weight * signal;
        weight *= gain * signal;
        p = p * lacunarity;
    }
    float rmd = detail - floorf(detail);
    if ((rmd != 0.0f) && (weight > 0.001f)) {
        weight = pmin(weight, 1.0f);
        float signal = (snoise(p) + offset) * pwr;
        value += rmd * weight * signal;
    }
    return value;
}

template<typename T>
HD inline float noise_ridged_multi_fractal(T p, float detail, float roughness,
                                           float lacunarity, float offset, float gain) {
    float pwr = roughness;
    float signal = offset - fabsf(snoise(p));
    signal *= signal;
    float value = signal;
    float weight = 1.0f;
    int octaves = (int)detail;
    for (int i = 1; i <= octaves; i++) {
        p = p * lacunarity;
        weight = pclamp(signal * gain, 0.0f, 1.0f);
        signal = offset - fabsf(snoise(p));
        signal *= signal;
        signal *= weight;
        value += signal * pwr;
        pwr *= roughness;
    }
    return value;
}

// ---------------------------------------------------------------------------
// Noise Texture node - Cycles kernel/svm/noisetex.h svm_node_tex_noise (Apache-2.0).
// type: 0=fBM, 1=multifractal, 2=hybrid, 3=ridged, 4=hetero terrain.
// dimensions 1-4 (#881): 1D reads only w, 2D (x, y), 3D the point, 4D (point, w);
// Cycles scales w by Scale too. facOnly (#881): the Fac output wired into a
// colour / vector socket is grey (Fac, Fac, Fac), not the Color triple.
// ---------------------------------------------------------------------------
struct NoiseParams {
    float scale, detail, roughness, lacunarity, offset, gain, distortion;
    int type;
    int normalize;
    int dimensions = 3;
    float w = 0.0f;
    int facOnly = 0;
};

// Cycles noisetex.h random_float{,2,3,4}_offset(seed): component k is
// 100 + hash_float2_to_float(seed, k) * 100 (1D: hash_float_to_float(seed)),
// precomputed as a fused multiply-add (one rounding): the value the production CPU
// build (MSVC /arch:AVX2 /fp:fast) produced and nvcc produces. Whether a compiler
// fuses it depends on inlining (GCC -mfma folded the old constant-seed call
// unfused), and the one-ulp offset change is amplified by the fractal octaves to
// ~1e-4 in the noise value, so the table pins it. Seeds 0-5, k 0-3; the 2D / 3D
// offsets are prefixes of the 4D ones. Generator + check against the original 3D
// table: .astroray_plan/docs/issue881-1006-noise-objcoords-research.md.
HD inline float random_offset(int seed, int k) {
    switch (seed * 4 + k) {
        case 0:  return 0x1.741004p+7f;  case 1:  return 0x1.cbd2e6p+6f;
        case 2:  return 0x1.34e51ep+7f;  case 3:  return 0x1.1d0284p+7f;
        case 4:  return 0x1.8fae14p+7f;  case 5:  return 0x1.4495cep+7f;
        case 6:  return 0x1.3418b2p+7f;  case 7:  return 0x1.1c8902p+7f;
        case 8:  return 0x1.be890ep+6f;  case 9:  return 0x1.3abd22p+7f;
        case 10: return 0x1.8e2d1cp+7f;  case 11: return 0x1.64df4ep+7f;
        case 12: return 0x1.4ae3fcp+7f;  case 13: return 0x1.458954p+7f;
        case 14: return 0x1.82d11ap+7f;  case 15: return 0x1.2282d2p+7f;
        case 16: return 0x1.37296ep+7f;  case 17: return 0x1.624f2cp+7f;
        case 18: return 0x1.1447b2p+7f;  case 19: return 0x1.685f18p+7f;
        case 20: return 0x1.79b524p+7f;  case 21: return 0x1.095afap+7f;
        case 22: return 0x1.441ab4p+7f;  default: return 0x1.72894cp+7f;
    }
}

HD inline float random_float_offset(int seed) {
    switch (seed) {
        case 0:  return 0x1.3c7c34p+7f;
        case 1:  return 0x1.cb581ep+6f;
        default: return 0x1.78fa36p+7f;
    }
}

HD inline PVec2 random_float2_offset(int seed) {
    return PVec2{random_offset(seed, 0), random_offset(seed, 1)};
}

HD inline GVec3 random_float3_offset(int seed) {
    return GVec3(random_offset(seed, 0), random_offset(seed, 1), random_offset(seed, 2));
}

HD inline PVec4 random_float4_offset(int seed) {
    return PVec4{random_offset(seed, 0), random_offset(seed, 1), random_offset(seed, 2),
                 random_offset(seed, 3)};
}

// Offset of the point's own dimension (overload on the point type).
HD inline float random_offset_like(float, int seed) { return random_float_offset(seed); }
HD inline PVec2 random_offset_like(const PVec2&, int seed) { return random_float2_offset(seed); }
HD inline GVec3 random_offset_like(const GVec3&, int seed) { return random_float3_offset(seed); }
HD inline PVec4 random_offset_like(const PVec4&, int seed) { return random_float4_offset(seed); }

template<typename T>
HD inline float noise_select(T p, float det, float rough, float lac, float off, float g,
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

// Cycles noise_texture_{1,2,3,4}d: value at the distorted point; the Color output is
// (value, select(p + offset c0), select(p + offset c1)) with per-dimension seeds.
template<typename T>
HD inline GVec3 noise_texture_nd(const NoiseParams& np, const T& p, int c0, int c1,
                                 float det, float rough, bool norm) {
    float fac = noise_select(p, det, rough, np.lacunarity, np.offset, np.gain, np.type, norm);
    if (np.facOnly) return GVec3(fac);
    const T o0 = random_offset_like(p, c0), o1 = random_offset_like(p, c1);
    float r = noise_select(p + o0, det, rough, np.lacunarity, np.offset, np.gain, np.type, norm);
    float g = noise_select(p + o1, det, rough, np.lacunarity, np.offset, np.gain, np.type, norm);
    return GVec3(fac, r, g);
}

// Color output (Fac, noise(+offset), noise(+offset)); Fac = .x.
HD inline GVec3 noise_texture(const NoiseParams& np, GVec3 p) {
    // Clamp detail [0,15], roughness >= 0 per svm_node_tex_noise.
    float det = pclamp(np.detail, 0.0f, 15.0f);
    float rough = pmax(np.roughness, 0.0f);
    bool norm = np.normalize != 0;
    const float d = np.distortion;
    GVec3 co = p * np.scale;
    float w = np.w * np.scale;
    switch (np.dimensions) {
        case 1: {
            float q = w;
            if (d != 0.0f) q += snoise_1d(q + random_float_offset(0)) * d;
            return noise_texture_nd(np, q, 1, 2, det, rough, norm);
        }
        case 2: {
            PVec2 q{co.x, co.y};
            if (d != 0.0f) {
                PVec2 dq{snoise_2d(q + random_float2_offset(0)) * d,
                         snoise_2d(q + random_float2_offset(1)) * d};
                q = q + dq;
            }
            return noise_texture_nd(np, q, 2, 3, det, rough, norm);
        }
        case 4: {
            PVec4 q{co.x, co.y, co.z, w};
            if (d != 0.0f) {
                PVec4 dq{snoise_4d(q + random_float4_offset(0)) * d,
                         snoise_4d(q + random_float4_offset(1)) * d,
                         snoise_4d(q + random_float4_offset(2)) * d,
                         snoise_4d(q + random_float4_offset(3)) * d};
                q = q + dq;
            }
            return noise_texture_nd(np, q, 4, 5, det, rough, norm);
        }
        default: {
            GVec3 distorted = co;
            if (d != 0.0f) {
                distorted.x += snoise_3d(co + random_float3_offset(0)) * d;
                distorted.y += snoise_3d(co + random_float3_offset(1)) * d;
                distorted.z += snoise_3d(co + random_float3_offset(2)) * d;
            }
            return noise_texture_nd(np, distorted, 3, 4, det, rough, norm);
        }
    }
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
    // #975: dimensions 1-4 (Cycles svm_node_tex_voronoi node.dimensions). 3 is the
    // pkg115 path above (unchanged); 1D reads only w, 2D (x, y), 4D (point, w).
    // Cycles scales w by Scale too (applied at evaluation, like NoiseParams::w).
    int dimensions = 3;
    float w = 0.0f;
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

// #975: max_distance of the 1D / 2D / 4D nodes (defined with them, below).
HD inline float voronoi_nd_max_distance(const VoronoiParams& vp);

// Cycles svm_node_tex_voronoi parameter conditioning (host side, once per texture).
HD inline void voronoi_condition(VoronoiParams& vp) {
    vp.detail = pclamp(vp.detail, 0.0f, 15.0f);
    vp.roughness = pclamp(vp.roughness, 0.0f, 1.0f);
    vp.randomness = pclamp(vp.randomness, 0.0f, 1.0f);
    vp.smoothness = pclamp(vp.smoothness / 2.0f, 0.0f, 0.5f);  // UI 0-1 -> Cycles 0-0.5
    if (vp.dimensions != 3) {
        vp.maxDistance = voronoi_nd_max_distance(vp);
        return;
    }
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

// ---------------------------------------------------------------------------
// #975 - the Voronoi Texture's 1D / 2D / 4D dimensions. Cycles kernel/svm/voronoi.h
// (Apache-2.0, blender-v5.2-release; IQ 2013 MIT for smooth F1 / distance to edge),
// the float / float2 / float4 overloads, ported function by function (research note
// .astroray_plan/docs/issue975-voronoi-nd-research.md). Differences from the 3-D
// path above, all as in Cycles: cell indices are ints (no float round trip), 2D / 4D
// use the PCG2D / PCG4D hash (util/hash.h hash_int{2,4}_to_float{2,4}), 1D hashes the
// float cell position (hash_float_to_float), F1 searches with the cheaper
// voronoi_distance_bound, and Distance to Edge has its own fractal wrapper
// (fractal_voronoi_distance_to_edge) while N-Sphere Radius is not fractal. Only the
// Distance / Color / Radius outputs are produced; the Position / W outputs are not
// exposed by any Astroray consumer, so they are not computed.
// ---------------------------------------------------------------------------
struct PInt2 { int x, y; };
struct PInt4 { int x, y, z, w; };
HD inline PVec2 operator-(const PVec2& a, const PVec2& b) { return PVec2{a.x - b.x, a.y - b.y}; }
HD inline PVec4 operator-(const PVec4& a, const PVec4& b) {
    return PVec4{a.x - b.x, a.y - b.y, a.z - b.z, a.w - b.w};
}

HD inline float vnd_flt_max() { return 3.402823466e+38f; }  // FLT_MAX

// util/math_base.h smoothstep (edges 0, 1) and mix.
HD inline float vnd_smoothstep(float x) {
    if (x < 0.0f) return 0.0f;
    if (x >= 1.0f) return 1.0f;
    return (3.0f - 2.0f * x) * (x * x);
}
HD inline GVec3 vnd_mix3(const GVec3& a, const GVec3& b, float t) { return a + (b - a) * t; }

// hash.h: hash_float_to_float3, hash_pcg{2,4}d_i -> float (signed-int arithmetic
// shift emulated by pcg_xorshift_signed16, as for the 3-D hash above).
HD inline GVec3 hash_float_to_float3(float k) {
    return GVec3(hash_float_to_float(k), hash_float2_to_float(k, 1.0f),
                 hash_float2_to_float(k, 2.0f));
}

HD inline PVec2 hash_int2_to_float2(const PInt2& k) {
    uint32_t x = (uint32_t)k.x * 1664525u + 1013904223u;
    uint32_t y = (uint32_t)k.y * 1664525u + 1013904223u;
    x += y * 1664525u;
    y += x * 1664525u;
    x = pcg_xorshift_signed16(x);
    y = pcg_xorshift_signed16(y);
    x += y * 1664525u;
    y += x * 1664525u;
    const float s = 1.0f / (float)0x7FFFFFFFu;
    return PVec2{(float)(x & 0x7FFFFFFFu) * s, (float)(y & 0x7FFFFFFFu) * s};
}

HD inline PVec4 hash_int4_to_float4(const PInt4& k) {
    uint32_t x = (uint32_t)k.x * 1664525u + 1013904223u;
    uint32_t y = (uint32_t)k.y * 1664525u + 1013904223u;
    uint32_t z = (uint32_t)k.z * 1664525u + 1013904223u;
    uint32_t w = (uint32_t)k.w * 1664525u + 1013904223u;
    x += y * w;
    y += z * x;
    z += x * y;
    w += y * z;
    x = pcg_xorshift_signed16(x);
    y = pcg_xorshift_signed16(y);
    z = pcg_xorshift_signed16(z);
    w = pcg_xorshift_signed16(w);
    x += y * w;
    y += z * x;
    z += x * y;
    w += y * z;
    const float s = 1.0f / (float)0x7FFFFFFFu;
    return PVec4{(float)(x & 0x7FFFFFFFu) * s, (float)(y & 0x7FFFFFFFu) * s,
                 (float)(z & 0x7FFFFFFFu) * s, (float)(w & 0x7FFFFFFFu) * s};
}

// Per-dimension vector traits for the 2D / 4D templates. offset() enumerates the
// (width)^N cells with i fastest (then j, k, u) - Cycles' loop nest order, which
// decides ties.
template<typename P> struct VorTraits;

template<> struct VorTraits<PVec2> {
    typedef PInt2 C;
    HD static int count(int w) { return w * w; }
    HD static C offset(int idx, int w, int lo) { return C{lo + idx % w, lo + (idx / w) % w}; }
    HD static C zeroCell() { return C{0, 0}; }
    HD static bool isZero(const C& c) { return c.x == 0 && c.y == 0; }
    HD static C add(const C& a, const C& b) { return C{a.x + b.x, a.y + b.y}; }
    HD static PVec2 zero() { return PVec2{0.0f, 0.0f}; }
    HD static PVec2 floor_(const PVec2& a) { return PVec2{floorf(a.x), floorf(a.y)}; }
    HD static C toInt(const PVec2& a) { return C{(int)a.x, (int)a.y}; }
    HD static PVec2 toFloat(const C& c) { return PVec2{(float)c.x, (float)c.y}; }
    HD static PVec2 hash(const C& c) { return hash_int2_to_float2(c); }
    HD static GVec3 color(const C& c) { return hash_int3_to_float3(c.x, c.y, 0); }  // hash_int2_to_float3
    HD static float dot(const PVec2& a, const PVec2& b) { return a.x * b.x + a.y * b.y; }
    HD static float reduceAdd(const PVec2& a) { return a.x + a.y; }
    HD static float reduceMax(const PVec2& a) { return pmax(a.x, a.y); }
    HD static PVec2 fabs_(const PVec2& a) { return PVec2{fabsf(a.x), fabsf(a.y)}; }
    HD static PVec2 pow_(const PVec2& a, float e) { return PVec2{powf(a.x, e), powf(a.y, e)}; }
};

template<> struct VorTraits<PVec4> {
    typedef PInt4 C;
    HD static int count(int w) { return w * w * w * w; }
    HD static C offset(int idx, int w, int lo) {
        return C{lo + idx % w, lo + (idx / w) % w, lo + (idx / (w * w)) % w,
                 lo + (idx / (w * w * w)) % w};
    }
    HD static C zeroCell() { return C{0, 0, 0, 0}; }
    HD static bool isZero(const C& c) { return c.x == 0 && c.y == 0 && c.z == 0 && c.w == 0; }
    HD static C add(const C& a, const C& b) { return C{a.x + b.x, a.y + b.y, a.z + b.z, a.w + b.w}; }
    HD static PVec4 zero() { return PVec4{0.0f, 0.0f, 0.0f, 0.0f}; }
    HD static PVec4 floor_(const PVec4& a) {
        return PVec4{floorf(a.x), floorf(a.y), floorf(a.z), floorf(a.w)};
    }
    HD static C toInt(const PVec4& a) { return C{(int)a.x, (int)a.y, (int)a.z, (int)a.w}; }
    HD static PVec4 toFloat(const C& c) { return PVec4{(float)c.x, (float)c.y, (float)c.z, (float)c.w}; }
    HD static PVec4 hash(const C& c) { return hash_int4_to_float4(c); }
    HD static GVec3 color(const C& c) {  // hash_int4_to_float3
        PVec4 h = hash_int4_to_float4(c);
        return GVec3(h.x, h.y, h.z);
    }
    HD static float dot(const PVec4& a, const PVec4& b) {
        return (a.x * b.x + a.y * b.y) + (a.z * b.z + a.w * b.w);
    }
    HD static float reduceAdd(const PVec4& a) { return a.x + a.y + a.z + a.w; }
    HD static float reduceMax(const PVec4& a) { return pmax(pmax(a.x, a.y), pmax(a.z, a.w)); }
    HD static PVec4 fabs_(const PVec4& a) {
        return PVec4{fabsf(a.x), fabsf(a.y), fabsf(a.z), fabsf(a.w)};
    }
    HD static PVec4 pow_(const PVec4& a, float e) {
        return PVec4{powf(a.x, e), powf(a.y, e), powf(a.z, e), powf(a.w, e)};
    }
};

// voronoi_distance(a, b, params) and voronoi_distance_bound (same ordering as the
// full distance for every metric, cheaper for Euclidean / Minkowski).
template<typename P>
HD inline float vnd_distance(const VoronoiParams& vp, const P& a, const P& b) {
    typedef VorTraits<P> T;
    const P d = a - b;
    switch (vp.distMetric) {
        case 1: return T::reduceAdd(T::fabs_(d));
        case 2: return T::reduceMax(T::fabs_(d));
        case 3: return powf(T::reduceAdd(T::pow_(T::fabs_(d), vp.exponent)), 1.0f / vp.exponent);
        default: return sqrtf(T::dot(d, d));
    }
}

template<typename P>
HD inline float vnd_distance_bound(const VoronoiParams& vp, const P& a, const P& b) {
    typedef VorTraits<P> T;
    const P d = a - b;
    switch (vp.distMetric) {
        case 1: return T::reduceAdd(T::fabs_(d));
        case 2: return T::reduceMax(T::fabs_(d));
        case 3: return T::reduceAdd(T::pow_(T::fabs_(d), vp.exponent));
        default: return T::dot(d, d);
    }
}

// ---- 2D / 4D features (templates over PVec2 / PVec4) ----
template<typename P>
HD inline VoronoiOut vnd_f1(const VoronoiParams& vp, const P& coord) {
    typedef VorTraits<P> T;
    typedef typename T::C C;
    const P cellF = T::floor_(coord);
    const P local = coord - cellF;
    const C cell = T::toInt(cellF);
    float minDistance = vnd_flt_max();
    C targetOffset = T::zeroCell();
    P targetPosition = T::zero();
    for (int n = 0; n < T::count(3); ++n) {
        const C off = T::offset(n, 3, -1);
        const P pt = T::toFloat(off) + T::hash(T::add(cell, off)) * vp.randomness;
        const float d = vnd_distance_bound(vp, pt, local);
        if (d < minDistance) {
            targetOffset = off;
            minDistance = d;
            targetPosition = pt;
        }
    }
    VoronoiOut o;
    o.distance = vnd_distance(vp, targetPosition, local);
    o.color = T::color(T::add(cell, targetOffset));
    o.position = GVec3(0.0f);
    o.radius = 0.0f;
    return o;
}

template<typename P>
HD inline VoronoiOut vnd_smooth_f1(const VoronoiParams& vp, const P& coord) {
    typedef VorTraits<P> T;
    typedef typename T::C C;
    const P cellF = T::floor_(coord);
    const P local = coord - cellF;
    const C cell = T::toInt(cellF);
    float smoothDistance = 0.0f;
    GVec3 smoothColor(0.0f);
    float h = -1.0f;
    for (int n = 0; n < T::count(5); ++n) {
        const C off = T::offset(n, 5, -2);
        const P pt = T::toFloat(off) + T::hash(T::add(cell, off)) * vp.randomness;
        const float d = vnd_distance(vp, pt, local);
        h = (h == -1.0f) ? 1.0f
                         : vnd_smoothstep(0.5f + 0.5f * (smoothDistance - d) / vp.smoothness);
        float correction = vp.smoothness * h * (1.0f - h);
        smoothDistance = pmix(smoothDistance, d, h) - correction;
        correction /= 1.0f + 3.0f * vp.smoothness;
        const GVec3 cellColor = T::color(T::add(cell, off));
        smoothColor = vnd_mix3(smoothColor, cellColor, h) - GVec3(correction);
    }
    VoronoiOut o;
    o.distance = smoothDistance;
    o.color = smoothColor;
    o.position = GVec3(0.0f);
    o.radius = 0.0f;
    return o;
}

template<typename P>
HD inline VoronoiOut vnd_f2(const VoronoiParams& vp, const P& coord) {
    typedef VorTraits<P> T;
    typedef typename T::C C;
    const P cellF = T::floor_(coord);
    const P local = coord - cellF;
    const C cell = T::toInt(cellF);
    float distanceF1 = vnd_flt_max();
    float distanceF2 = vnd_flt_max();
    C offsetF1 = T::zeroCell();
    C offsetF2 = T::zeroCell();
    for (int n = 0; n < T::count(3); ++n) {
        const C off = T::offset(n, 3, -1);
        const P pt = T::toFloat(off) + T::hash(T::add(cell, off)) * vp.randomness;
        const float d = vnd_distance(vp, pt, local);
        if (d < distanceF1) {
            distanceF2 = distanceF1;
            distanceF1 = d;
            offsetF2 = offsetF1;
            offsetF1 = off;
        } else if (d < distanceF2) {
            distanceF2 = d;
            offsetF2 = off;
        }
    }
    VoronoiOut o;
    o.distance = distanceF2;
    o.color = T::color(T::add(cell, offsetF2));
    o.position = GVec3(0.0f);
    o.radius = 0.0f;
    return o;
}

template<typename P>
HD inline float vnd_distance_to_edge(const VoronoiParams& vp, const P& coord) {
    typedef VorTraits<P> T;
    typedef typename T::C C;
    const P cellF = T::floor_(coord);
    const P local = coord - cellF;
    const C cell = T::toInt(cellF);
    P vectorToClosest = T::zero();
    float minDistance = vnd_flt_max();
    for (int n = 0; n < T::count(3); ++n) {
        const C off = T::offset(n, 3, -1);
        const P v = T::toFloat(off) + T::hash(T::add(cell, off)) * vp.randomness - local;
        const float d = T::dot(v, v);
        if (d < minDistance) {
            minDistance = d;
            vectorToClosest = v;
        }
    }
    minDistance = vnd_flt_max();
    for (int n = 0; n < T::count(3); ++n) {
        const C off = T::offset(n, 3, -1);
        const P v = T::toFloat(off) + T::hash(T::add(cell, off)) * vp.randomness - local;
        const P perp = v - vectorToClosest;
        if (T::dot(perp, perp) > 0.0001f) {
            const float inv = 1.0f / sqrtf(T::dot(perp, perp));  // normalize(): a / len(a)
            const float distanceToEdge = T::dot((vectorToClosest + v) * 0.5f, perp * inv);
            minDistance = pmin(minDistance, distanceToEdge);
        }
    }
    return minDistance;
}

template<typename P>
HD inline float vnd_n_sphere_radius(const VoronoiParams& vp, const P& coord) {
    typedef VorTraits<P> T;
    typedef typename T::C C;
    const P cellF = T::floor_(coord);
    const P local = coord - cellF;
    const C cell = T::toInt(cellF);
    P closestPoint = T::zero();
    C closestPointOffset = T::zeroCell();
    float minDistanceSq = vnd_flt_max();
    for (int n = 0; n < T::count(3); ++n) {
        const C off = T::offset(n, 3, -1);
        const P pt = T::toFloat(off) + T::hash(T::add(cell, off)) * vp.randomness;
        const P dv = pt - local;
        const float dSq = T::dot(dv, dv);
        if (dSq < minDistanceSq) {
            minDistanceSq = dSq;
            closestPoint = pt;
            closestPointOffset = off;
        }
    }
    minDistanceSq = vnd_flt_max();
    P closestToClosest = T::zero();
    for (int n = 0; n < T::count(3); ++n) {
        const C base = T::offset(n, 3, -1);
        if (T::isZero(base)) continue;
        const C off = T::add(base, closestPointOffset);
        const P pt = T::toFloat(off) + T::hash(T::add(cell, off)) * vp.randomness;
        const P dv = closestPoint - pt;
        const float dSq = T::dot(dv, dv);
        if (dSq < minDistanceSq) {
            minDistanceSq = dSq;
            closestToClosest = pt;
        }
    }
    const P dv = closestToClosest - closestPoint;
    return sqrtf(T::dot(dv, dv)) / 2.0f;
}

// ---- 1D features (float coordinate; the only distance is |b - a|) ----
HD inline VoronoiOut vnd_f1(const VoronoiParams& vp, float coord) {
    const float cellPosition = floorf(coord);
    const float local = coord - cellPosition;
    float minDistance = vnd_flt_max();
    float targetOffset = 0.0f;
    for (int i = -1; i <= 1; ++i) {
        const float cellOffset = (float)i;
        const float pt = cellOffset + hash_float_to_float(cellPosition + cellOffset) * vp.randomness;
        const float d = fabsf(local - pt);
        if (d < minDistance) {
            targetOffset = cellOffset;
            minDistance = d;
        }
    }
    VoronoiOut o;
    o.distance = minDistance;
    o.color = hash_float_to_float3(cellPosition + targetOffset);
    o.position = GVec3(0.0f);
    o.radius = 0.0f;
    return o;
}

HD inline VoronoiOut vnd_smooth_f1(const VoronoiParams& vp, float coord) {
    const float cellPosition = floorf(coord);
    const float local = coord - cellPosition;
    float smoothDistance = 0.0f;
    GVec3 smoothColor(0.0f);
    float h = -1.0f;
    for (int i = -2; i <= 2; ++i) {
        const float cellOffset = (float)i;
        const float pt = cellOffset + hash_float_to_float(cellPosition + cellOffset) * vp.randomness;
        const float d = fabsf(local - pt);
        h = (h == -1.0f) ? 1.0f
                         : vnd_smoothstep(0.5f + 0.5f * (smoothDistance - d) / vp.smoothness);
        float correction = vp.smoothness * h * (1.0f - h);
        smoothDistance = pmix(smoothDistance, d, h) - correction;
        correction /= 1.0f + 3.0f * vp.smoothness;
        const GVec3 cellColor = hash_float_to_float3(cellPosition + cellOffset);
        smoothColor = vnd_mix3(smoothColor, cellColor, h) - GVec3(correction);
    }
    VoronoiOut o;
    o.distance = smoothDistance;
    o.color = smoothColor;
    o.position = GVec3(0.0f);
    o.radius = 0.0f;
    return o;
}

HD inline VoronoiOut vnd_f2(const VoronoiParams& vp, float coord) {
    const float cellPosition = floorf(coord);
    const float local = coord - cellPosition;
    float distanceF1 = vnd_flt_max();
    float distanceF2 = vnd_flt_max();
    float offsetF1 = 0.0f;
    float offsetF2 = 0.0f;
    for (int i = -1; i <= 1; ++i) {
        const float cellOffset = (float)i;
        const float pt = cellOffset + hash_float_to_float(cellPosition + cellOffset) * vp.randomness;
        const float d = fabsf(local - pt);
        if (d < distanceF1) {
            distanceF2 = distanceF1;
            distanceF1 = d;
            offsetF2 = offsetF1;
            offsetF1 = cellOffset;
        } else if (d < distanceF2) {
            distanceF2 = d;
            offsetF2 = cellOffset;
        }
    }
    VoronoiOut o;
    o.distance = distanceF2;
    o.color = hash_float_to_float3(cellPosition + offsetF2);
    o.position = GVec3(0.0f);
    o.radius = 0.0f;
    return o;
}

HD inline float vnd_distance_to_edge(const VoronoiParams& vp, float coord) {
    const float cellPosition = floorf(coord);
    const float local = coord - cellPosition;
    const float mid = hash_float_to_float(cellPosition) * vp.randomness;
    const float left = -1.0f + hash_float_to_float(cellPosition - 1.0f) * vp.randomness;
    const float right = 1.0f + hash_float_to_float(cellPosition + 1.0f) * vp.randomness;
    const float distanceToMidLeft = fabsf((mid + left) / 2.0f - local);
    const float distanceToMidRight = fabsf((mid + right) / 2.0f - local);
    return pmin(distanceToMidLeft, distanceToMidRight);
}

HD inline float vnd_n_sphere_radius(const VoronoiParams& vp, float coord) {
    const float cellPosition = floorf(coord);
    const float local = coord - cellPosition;
    float closestPoint = 0.0f;
    float closestPointOffset = 0.0f;
    float minDistance = vnd_flt_max();
    for (int i = -1; i <= 1; ++i) {
        const float cellOffset = (float)i;
        const float pt = cellOffset + hash_float_to_float(cellPosition + cellOffset) * vp.randomness;
        const float d = fabsf(pt - local);
        if (d < minDistance) {
            minDistance = d;
            closestPoint = pt;
            closestPointOffset = cellOffset;
        }
    }
    minDistance = vnd_flt_max();
    float closestToClosest = 0.0f;
    for (int i = -1; i <= 1; ++i) {
        if (i == 0) continue;
        const float cellOffset = (float)i + closestPointOffset;
        const float pt = cellOffset + hash_float_to_float(cellPosition + cellOffset) * vp.randomness;
        const float d = fabsf(closestPoint - pt);
        if (d < minDistance) {
            minDistance = d;
            closestToClosest = pt;
        }
    }
    return fabsf(closestToClosest - closestPoint) / 2.0f;
}

// ---- fractal wrappers and the node entry (all dimensions, P in {float, PVec2, PVec4}) ----
// fractal_voronoi_x_fx: the fBM logic with some additions replaced by lerps.
template<typename P>
HD inline VoronoiOut vnd_fractal_x_fx(const VoronoiParams& vp, const P& coord) {
    float amplitude = 1.0f;
    float maxAmplitude = 0.0f;
    float scale = 1.0f;
    VoronoiOut output;
    output.distance = 0.0f;
    output.color = GVec3(0.0f);
    output.position = GVec3(0.0f);
    output.radius = 0.0f;
    const bool zeroInput = vp.detail == 0.0f || vp.roughness == 0.0f;
    const int octaves = (int)ceilf(vp.detail);
    for (int i = 0; i <= octaves; ++i) {
        const P c = coord * scale;
        VoronoiOut octave = (vp.feature == 2) ? vnd_f2(vp, c)
                          : (vp.feature == 1 && vp.smoothness != 0.0f) ? vnd_smooth_f1(vp, c)
                          : vnd_f1(vp, c);
        if (zeroInput) {
            maxAmplitude = 1.0f;
            output = octave;
            break;
        }
        if ((float)i <= vp.detail) {
            maxAmplitude += amplitude;
            output.distance += octave.distance * amplitude;
            output.color = output.color + octave.color * amplitude;
            scale *= vp.lacunarity;
            amplitude *= vp.roughness;
        } else {
            const float remainder = vp.detail - floorf(vp.detail);
            if (remainder != 0.0f) {
                maxAmplitude = pmix(maxAmplitude, maxAmplitude + amplitude, remainder);
                output.distance = pmix(output.distance, output.distance + octave.distance * amplitude,
                                       remainder);
                output.color = vnd_mix3(output.color, output.color + octave.color * amplitude,
                                        remainder);
            }
        }
    }
    if (vp.normalize) {
        output.distance /= maxAmplitude * vp.maxDistance;
        output.color = output.color / maxAmplitude;
    }
    return output;
}

// fractal_voronoi_distance_to_edge.
template<typename P>
HD inline float vnd_fractal_distance_to_edge(const VoronoiParams& vp, const P& coord) {
    float amplitude = 1.0f;
    float maxAmplitude = vp.maxDistance;
    float scale = 1.0f;
    float distance = 8.0f;
    const bool zeroInput = vp.detail == 0.0f || vp.roughness == 0.0f;
    const int octaves = (int)ceilf(vp.detail);
    for (int i = 0; i <= octaves; ++i) {
        const float octaveDistance = vnd_distance_to_edge(vp, coord * scale);
        if (zeroInput) {
            distance = octaveDistance;
            break;
        }
        if ((float)i <= vp.detail) {
            maxAmplitude = pmix(maxAmplitude, vp.maxDistance / scale, amplitude);
            distance = pmix(distance, pmin(distance, octaveDistance / scale), amplitude);
            scale *= vp.lacunarity;
            amplitude *= vp.roughness;
        } else {
            const float remainder = vp.detail - floorf(vp.detail);
            if (remainder != 0.0f) {
                const float lerpAmplitude = pmix(maxAmplitude, vp.maxDistance / scale, amplitude);
                maxAmplitude = pmix(maxAmplitude, lerpAmplitude, remainder);
                const float lerpDistance = pmix(distance, pmin(distance, octaveDistance / scale),
                                                amplitude);
                distance = pmix(distance, pmin(distance, lerpDistance), remainder);
            }
        }
    }
    if (vp.normalize) distance /= maxAmplitude;
    return distance;
}

// svm_node_tex_voronoi switch per feature: Distance to Edge -> distance only,
// N-Sphere Radius -> radius only (Distance 0), else the fractal x_fx output.
template<typename P>
HD inline VoronoiOut vnd_node(const VoronoiParams& vp, const P& coord) {
    VoronoiOut o;
    o.distance = 0.0f;
    o.color = GVec3(0.0f);
    o.position = GVec3(0.0f);
    o.radius = 0.0f;
    if (vp.feature == 3) {
        o.distance = vnd_fractal_distance_to_edge(vp, coord);
    } else if (vp.feature == 4) {
        o.radius = vnd_n_sphere_radius(vp, coord);
    } else {
        o = vnd_fractal_x_fx(vp, coord);
    }
    return o;
}

// max_distance for normalize (svm_node_tex_voronoi): Distance to Edge 0.5 + 0.5 r;
// else the metric distance (0, 0..) -> (m, m..) with m = 0.5 + 0.5 r, doubled for F2
// (1D has no metric). N-Sphere Radius never reads it.
HD inline float voronoi_nd_max_distance(const VoronoiParams& vp) {
    const float m = 0.5f + 0.5f * vp.randomness;
    if (vp.feature == 3) return m;
    const float f2 = (vp.feature == 2) ? 2.0f : 1.0f;
    switch (vp.dimensions) {
        case 1: return m * f2;
        case 2: return vnd_distance(vp, PVec2{0.0f, 0.0f}, PVec2{m, m}) * f2;
        default: return vnd_distance(vp, PVec4{0.0f, 0.0f, 0.0f, 0.0f}, PVec4{m, m, m, m}) * f2;
    }
}

// Texture point p (3-D, scaled by Scale) and the W socket value vp.w (also scaled).
HD inline VoronoiOut voronoi_eval_nd(const VoronoiParams& vp, const GVec3& p) {
    const GVec3 co = p * vp.scale;
    const float w = vp.w * vp.scale;
    switch (vp.dimensions) {
        case 1: return vnd_node(vp, w);
        case 2: return vnd_node(vp, PVec2{co.x, co.y});
        default: return vnd_node(vp, PVec4{co.x, co.y, co.z, w});
    }
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

// #975: the node entry for every dimension. The 3-D body (voronoi_eval_full) is left
// untouched so its code generation, and with it the 3-D output, is unchanged.
HD inline VoronoiOut voronoi_eval(const VoronoiParams& vp, const GVec3& p) {
    return (vp.dimensions != 3) ? voronoi_eval_nd(vp, p) : voronoi_eval_full(vp, p);
}

// Color output (hashed cell colour) or Distance as a colorLow->colorHigh lerp.
HD inline GVec3 voronoi_texture(const VoronoiParams& vp, GVec3 p) {
    VoronoiOut out = voronoi_eval(vp, p);
    if (vp.outputColor) return out.color;
    // #975: 1D / 2D / 4D return the node's Distance (or Radius for N-Sphere Radius,
    // whose Distance is 0 in Cycles) unclamped: Cycles distances exceed 1 (F2,
    // Manhattan) and Smooth F1 dips below 0. The 3-D path keeps its pkg115 [0,1] clamp.
    float t;
    if (vp.dimensions != 3) t = (vp.feature == 4) ? out.radius : out.distance;
    else t = pclamp(out.distance, 0.0f, 1.0f);
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

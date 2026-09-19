#pragma once
// #840 — NEE sample of a point/spot lamp, shared by the CPU
// (src/lights/{point,spot}_light.cpp) and the GPU (gpu_nee.cuh).
//
// Source: Blender 5.2 Cycles (Apache-2.0, compatible with Astroray's LICENSE):
//   kernel/light/point.h  point_light_sample (sphere when use_soft_falloff is
//                         off; otherwise an oriented disk facing the lit point)
//   kernel/light/common.h disk_light_sample, light_pdf_area_to_solid_angle
//   kernel/sample/mapping.h sample_uniform_disk, sample_uniform_cone,
//                         sample_uniform_sphere
//   util/math_base.h      sin_sqr_to_one_minus_cos; util/math_float3.h make_orthonormals
//   scene/light.cpp       PointLight::area = 4 pi r^2 in BOTH modes, so the lamp
//                         radiance is P/(4 pi r^2 * pi) = I/(pi r^2), I = P/(4 pi).
// Notes + measured A/B: .astroray_plan/docs/pkg276-ies-spot-research.md (#840).
//
// Differences from Cycles (sampling strategy only; same expectation): inside a
// sphere lamp the direction is drawn uniformly on the sphere (Cycles' branch for
// transmissive surfaces, so no shading normal is needed); a sphere spot never
// switches to sampling its spread cone.

#include <math.h>

#if defined(__CUDACC__)
#  define AR_LAMP_HD __host__ __device__
#else
#  define AR_LAMP_HD
#endif

namespace astroray {
namespace lamp {

constexpr float kPiF = 3.14159265358979323846f;

struct Sample {
    float q[3];    // sampled lamp point (lamp centre for radius 0)
    float pdf;     // solid-angle pdf (1 for radius 0: delta, emission carries 1/d^2)
    float emit;    // multiplies the radiant intensity I: 1/d^2 (radius 0) or 1/(pi r^2)
    int   outside; // 0 only inside a sphere lamp (Cycles skips spot attenuation there)
    int   valid;
};

// util/math_float3.h make_orthonormals.
AR_LAMP_HD inline void orthonormals(const float n[3], float t[3], float b[3]) {
    if (n[0] != n[1] || n[0] != n[2]) {
        t[0] = n[2] - n[1]; t[1] = n[0] - n[2]; t[2] = n[1] - n[0];
    } else {
        t[0] = n[2] - n[1]; t[1] = n[0] + n[2]; t[2] = -n[1] - n[0];
    }
    const float inv = 1.0f / sqrtf(t[0] * t[0] + t[1] * t[1] + t[2] * t[2]);
    t[0] *= inv; t[1] *= inv; t[2] *= inv;
    b[0] = n[1] * t[2] - n[2] * t[1];
    b[1] = n[2] * t[0] - n[0] * t[2];
    b[2] = n[0] * t[1] - n[1] * t[0];
}

// kernel/sample/mapping.h sample_uniform_disk (concentric map).
AR_LAMP_HD inline void uniformDisk(float u1, float u2, float& x, float& y) {
    const float a = 2.0f * u1 - 1.0f, b = 2.0f * u2 - 1.0f;
    if (a == 0.0f && b == 0.0f) { x = 0.0f; y = 0.0f; return; }
    float r, phi;
    if (a * a > b * b) { r = a; phi = 0.25f * kPiF * (b / a); }
    else               { r = b; phi = 0.5f * kPiF - 0.25f * kPiF * (a / b); }
    x = r * cosf(phi); y = r * sinf(phi);
}

// util/math_base.h sin_sqr_to_one_minus_cos.
AR_LAMP_HD inline float sinSqrToOneMinusCos(float s) {
    return s > 0.0004f ? 1.0f - sqrtf(fmaxf(0.0f, 1.0f - s)) : 0.5f * s;
}

// c = lamp centre, r = radius, sphere = !use_soft_falloff, p = lit point,
// (u1, u2) = the two sampling uniforms (unused for radius 0).
AR_LAMP_HD inline Sample sample(const float c[3], float r, bool sphere, const float p[3],
                                float u1, float u2) {
    Sample s{};
    float ln[3] = {p[0] - c[0], p[1] - c[1], p[2] - c[2]};   // lamp -> lit point
    const float d2 = ln[0] * ln[0] + ln[1] * ln[1] + ln[2] * ln[2];
    const float d = sqrtf(d2);
    if (!(d > 1e-6f)) return s;
    ln[0] /= d; ln[1] /= d; ln[2] /= d;
    s.outside = 1;
    if (!(r > 0.0f)) {
        s.q[0] = c[0]; s.q[1] = c[1]; s.q[2] = c[2];
        s.pdf = 1.0f; s.emit = 1.0f / d2; s.valid = 1;
        return s;
    }
    const float r2 = r * r;
    s.emit = 1.0f / (kPiF * r2);
    if (sphere) {
        float D[3], cosT, t;
        if (d2 > r2) {
            // sample_uniform_cone(-lightN, one_minus_cos(r^2/d^2)).
            const float omc = sinSqrToOneMinusCos(r2 / d2);
            // Cycles kernel/sample/mapping.h (:131, :171-174) guards a zero
            // one_minus_cos_angle (fully degenerate cone) by returning
            // cos_theta=1, pdf=1, D=N instead of dividing by zero below.
            if (omc > 0.0f) {
                float x, y;
                uniformDisk(u1, u2, x, y);
                const float rd2 = x * x + y * y;
                cosT = 1.0f - rd2 * omc;
                const float k = sqrtf(fmaxf(0.0f, omc * (2.0f - omc * rd2)));
                x *= k; y *= k;
                const float N[3] = {-ln[0], -ln[1], -ln[2]};
                float T[3], B[3];
                orthonormals(N, T, B);
                for (int i = 0; i < 3; ++i) D[i] = x * T[i] + y * B[i] + cosT * N[i];
                s.pdf = 1.0f / (2.0f * kPiF * omc);
                t = d * cosT - sqrtf(fmaxf(0.0f, r2 - d2 + d2 * cosT * cosT));
            } else {
                // Degenerate cone: collapse to the sphere axis (cos_theta=1).
                cosT = 1.0f;
                s.pdf = 1.0f;
                D[0] = -ln[0]; D[1] = -ln[1]; D[2] = -ln[2];
                t = d - r;
            }
        } else {
            // Inside: uniform sphere (sample_uniform_sphere), pdf 1/(4 pi).
            const float z = 1.0f - 2.0f * u1;
            const float rr = sqrtf(fmaxf(0.0f, 1.0f - z * z));
            const float phi = 2.0f * kPiF * u2;
            D[0] = rr * cosf(phi); D[1] = rr * sinf(phi); D[2] = z;
            s.pdf = 1.0f / (4.0f * kPiF);
            cosT = -(D[0] * ln[0] + D[1] * ln[1] + D[2] * ln[2]);
            t = d * cosT + sqrtf(fmaxf(0.0f, r2 - d2 + d2 * cosT * cosT));
            s.outside = 0;
        }
        // Remap the hit onto the sphere (Cycles: precision for small radii).
        float g[3] = {p[0] + D[0] * t - c[0], p[1] + D[1] * t - c[1], p[2] + D[2] * t - c[2]};
        const float gl = sqrtf(g[0] * g[0] + g[1] * g[1] + g[2] * g[2]);
        if (!(gl > 0.0f)) return s;
        for (int i = 0; i < 3; ++i) s.q[i] = c[i] + g[i] / gl * r;
        s.valid = 1;
        return s;
    }
    // Oriented disk facing the lit point (use_soft_falloff, Blender's default).
    float T[3], B[3], x, y;
    orthonormals(ln, T, B);
    uniformDisk(u1, u2, x, y);
    for (int i = 0; i < 3; ++i) s.q[i] = c[i] + (x * T[i] + y * B[i]) * r;
    const float v[3] = {p[0] - s.q[0], p[1] - s.q[1], p[2] - s.q[2]};   // disk point -> lit point
    const float t2 = v[0] * v[0] + v[1] * v[1] + v[2] * v[2];
    const float t = sqrtf(t2);
    if (!(t > 0.0f)) return s;
    const float cosL = (ln[0] * v[0] + ln[1] * v[1] + ln[2] * v[2]) / t;
    if (!(cosL > 0.0f)) return s;
    s.pdf = t2 / (kPiF * r2 * cosL);   // invarea * light_pdf_area_to_solid_angle
    s.valid = 1;
    return s;
}

}  // namespace lamp
}  // namespace astroray

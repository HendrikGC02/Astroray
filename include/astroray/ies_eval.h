#pragma once
// pkg276 — IES lookup shared by the CPU (IESProfile, raytracer.h) and the GPU
// (gpu_nee.cuh gpu_lamp_sample_ext, gated by the runtime __constant__ flag
// c_iesEnabled), so both backends evaluate the SAME Cycles interpolation.
//
// Source: Blender 5.2 Cycles, intern/cycles/kernel/util/ies.h
//   (kernel_ies_interp, interpolate_ies_vertical), kernel/svm/ies.h
//   (svm_node_ies angle convention), util/math_base.h (cubic_interp).
// License: Apache-2.0 (compatible with Astroray's LICENSE).
// Notes + measured A/B: .astroray_plan/docs/pkg276-ies-spot-research.md.
//
// Packed layout (Cycles IESFile::pack, counts stored as float values):
//   [h_num, v_num, h_angles[h_num], v_angles[v_num], intensity[h_num * v_num]]
// Angles in radians (float32, `deg * (M_PI_F / 180.f)`), intensity row-major
// by horizontal angle, already scaled to Watt (candela * 4*pi/177.83).

#include <math.h>

#if defined(__CUDACC__)
#  define AR_IES_HD __host__ __device__
#else
#  define AR_IES_HD
#endif

namespace astroray {
namespace ies {

constexpr float kPiF = 3.14159265358979323846f;
constexpr float k2PiF = 6.28318530717958647692f;

// util/math_base.h cubic_interp (Catmull-Rom between b and c).
AR_IES_HD inline float cubicInterp(float a, float b, float c, float d, float x) {
    return 0.5f * (((d + 3.0f * (b - c) - a) * x + (2.0f * a - 5.0f * b + 4.0f * c - d)) * x +
                   (c - a)) * x + b;
}

// kernel/util/ies.h interpolate_ies_vertical.
AR_IES_HD inline float interpVertical(const float* I, bool wrapVLow, bool wrapVHigh,
                                      int v, int vNum, float vFrac, int h) {
    const float c = I[h * vNum + v + 1];
    const float b = I[h * vNum + v];
    float a = b;
    if (v > 0) a = I[h * vNum + v - 1];
    else if (wrapVLow) a = I[h * vNum + 1];
    float d = c;
    if (v + 2 < vNum) d = I[h * vNum + v + 2];
    else if (wrapVHigh) d = I[h * vNum + vNum - 2];
    return cubicInterp(a, b, c, d, vFrac);
}

// kernel/util/ies.h kernel_ies_interp. The wrap tests are float32 exactly as
// in the kernel: 1e-7f is below the ulp at 2*pi / pi, so a 0..360 (0..180)
// table does NOT wrap in Cycles; parity keeps that.
AR_IES_HD inline float interp(const float* p, float hAngle, float vAngle) {
    const int hNum = static_cast<int>(p[0]);
    const int vNum = static_cast<int>(p[1]);
    const float* H = p + 2;
    const float* V = H + hNum;
    const float* I = V + vNum;

    const float vLow = V[0], vHigh = V[vNum - 1];
    const float hLow = H[0], hHigh = H[hNum - 1];
    if (vAngle < vLow || vAngle >= vHigh) return 0.0f;
    if (hAngle < hLow || hAngle >= hHigh) return 0.0f;

    const bool wrapH = (hLow < 1e-7f && hHigh > k2PiF - 1e-7f);
    const bool wrapVLow = (vLow < 1e-7f);
    const bool wrapVHigh = (vHigh > kPiF - 1e-7f);

    int hi = 0, vi = 0;
    while (H[hi + 1] < hAngle) ++hi;
    while (V[vi + 1] < vAngle) ++vi;
    const float hFrac = (hAngle - H[hi]) / (H[hi + 1] - H[hi]);
    const float vFrac = (vAngle - V[vi]) / (V[vi + 1] - V[vi]);

    const float b = interpVertical(I, wrapVLow, wrapVHigh, vi, vNum, vFrac, hi);
    const float c = interpVertical(I, wrapVLow, wrapVHigh, vi, vNum, vFrac, hi + 1);
    float a = b;
    if (hi > 0) a = interpVertical(I, wrapVLow, wrapVHigh, vi, vNum, vFrac, hi - 1);
    else if (wrapH) a = interpVertical(I, wrapVLow, wrapVHigh, vi, vNum, vFrac, hNum - 2);
    float d = b;  // Cycles falls back to b (not c) here.
    if (hi + 2 < hNum) d = interpVertical(I, wrapVLow, wrapVHigh, vi, vNum, vFrac, hi + 2);
    else if (wrapH) d = interpVertical(I, wrapVLow, wrapVHigh, vi, vNum, vFrac, 1);
    const float r = cubicInterp(a, b, c, d, hFrac);
    return r > 0.0f ? r : 0.0f;
}

// kernel/svm/ies.h svm_node_ies on a light-local direction (x, y, z) pointing
// from the light toward the lit point (the node's default Vector is
// Geometry:Incoming transformed world->object as a normal,
// scene/shader_graph.cpp LINK_TEXTURE_INCOMING): v = acos(-z),
// h = atan2(x, y) + pi.
AR_IES_HD inline float evalLocal(const float* p, float x, float y, float z) {
    const float len = sqrtf(x * x + y * y + z * z);
    if (!(len > 0.0f)) return 0.0f;
    const float inv = 1.0f / len;
    x *= inv; y *= inv; z *= inv;
    float cz = -z;
    cz = cz < -1.0f ? -1.0f : (cz > 1.0f ? 1.0f : cz);
    const float vAngle = acosf(cz);
    const float hAngle = atan2f(x, y) + kPiF;
    return interp(p, hAngle, vAngle);
}

// World direction `d` (light -> lit point) through the light object's 3x3
// columns fx/fy/fz (local X/Y/Z in world, unnormalised): object-space normal
// transform `transform_direction_transposed` (kernel/geom/object.h), i.e.
// local = (d.fx, d.fy, d.fz), then evalLocal.
AR_IES_HD inline float evalFrame(const float* p, const float* fx, const float* fy,
                                 const float* fz, float dx, float dy, float dz) {
    return evalLocal(p, dx * fx[0] + dy * fx[1] + dz * fx[2],
                        dx * fy[0] + dy * fy[1] + dz * fy[2],
                        dx * fz[0] + dy * fz[1] + dz * fz[2]);
}

}  // namespace ies
}  // namespace astroray

#pragma once
#include "../raytracer.h"
#include <cmath>

namespace astroray {
// Watertight ray/triangle test: Woop, Benthin, Wald, "Watertight Ray/Triangle
// Intersection", JCGT 2(1), 2013, with the FMA error-free edge-function product
// and double fallback on a zero edge function (pbrt-v4 shapes.h, Apache-2.0).
// Replaces an absolute |det| < 1e-6 Moller-Trumbore rejection that dropped
// small/grazing triangles (#1000). GPU twin: gpu_triangle_watertight
// (gpu_bvh.h). Returns t and barycentric weights (u, v) of (p1, p2).
inline float watertightDop(float a, float b, float c, float d) {
    float w = d * c;
    float e = std::fma(-d, c, w);
    float f = std::fma(a, b, -w);
    return f + e;
}

inline bool watertightTriangle(const Vec3& p0, const Vec3& p1, const Vec3& p2,
                               const Ray& r, float tMin, float tMax,
                               float& t_out, float& u_out, float& v_out) {
    const Vec3& d = r.direction;
    float adx = std::fabs(d.x), ady = std::fabs(d.y), adz = std::fabs(d.z);
    int kz = (adx > ady) ? ((adx > adz) ? 0 : 2) : ((ady > adz) ? 1 : 2);
    int kx = kz + 1; if (kx == 3) kx = 0;
    int ky = kx + 1; if (ky == 3) ky = 0;
    float dz = d[kz];
    if (dz == 0.f) return false;
    Vec3 a = p0 - r.origin, b = p1 - r.origin, c = p2 - r.origin;
    float Sx = -d[kx] / dz, Sy = -d[ky] / dz, Sz = 1.f / dz;
    float ax = a[kx] + Sx * a[kz], ay = a[ky] + Sy * a[kz];
    float bx = b[kx] + Sx * b[kz], by = b[ky] + Sy * b[kz];
    float cx = c[kx] + Sx * c[kz], cy = c[ky] + Sy * c[kz];
    float e0 = watertightDop(bx, cy, by, cx);
    float e1 = watertightDop(cx, ay, cy, ax);
    float e2 = watertightDop(ax, by, ay, bx);
    if (e0 == 0.f || e1 == 0.f || e2 == 0.f) {
        e0 = (float)((double)bx * cy - (double)by * cx);
        e1 = (float)((double)cx * ay - (double)cy * ax);
        e2 = (float)((double)ax * by - (double)ay * bx);
    }
    if ((e0 < 0.f || e1 < 0.f || e2 < 0.f) && (e0 > 0.f || e1 > 0.f || e2 > 0.f)) return false;
    float det = e0 + e1 + e2;
    if (det == 0.f) return false;
    float tScaled = e0 * (Sz * a[kz]) + e1 * (Sz * b[kz]) + e2 * (Sz * c[kz]);
    float invDet = 1.f / det;
    float t = tScaled * invDet;
    if (t < tMin || t > tMax) return false;
    t_out = t; u_out = e1 * invDet; v_out = e2 * invDet;
    return true;
}
}  // namespace astroray


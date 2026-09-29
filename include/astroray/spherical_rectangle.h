#pragma once
// pkg294 (#922) — solid-angle sampling of a rectangular area lamp, shared by
// the CPU (src/lights/area_light.cpp) and the GPU (src/gpu/gpu_nee.cuh).
//
// Source: Urena, Fajardo & King 2013, "An Area-Preserving Parametrization for
// Spherical Rectangles" (EGSR), as implemented in Blender 5.2 Cycles
// kernel/light/area.h::area_light_rect_sample (Apache-2.0, compatible with
// Astroray's LICENSE). Cycles uses it for every non-segment area-light sample
// and pdf (area_light_eval<false>: NEE from a surface or a volume scatter
// point, and area_light_eval_from_intersection for the lamp-hit MIS pdf);
// the volume-segment anchor stays area-uniform (area_light_eval<true>).
// Notes: .astroray_plan/docs/pkg294-media-lamp-variance-ablation.md.

#include <math.h>

#if defined(__CUDACC__)
#  define AR_SPHRECT_HD __host__ __device__
#else
#  define AR_SPHRECT_HD
#endif

namespace astroray {
namespace sphrect {

// Rectangle centred at c with unit in-plane axes x, y and side lengths lenU,
// lenV, seen from p. Returns the solid-angle pdf 1/Omega (Cycles falls back to
// the area pdf at the centre when the rectangle is tiny or seen edge-on). When
// sampleCoord, q receives a point drawn uniformly in solid angle from (u1, u2).
AR_SPHRECT_HD inline float sample(const float p[3], const float c[3], const float x[3],
                                  float lenU, const float y[3], float lenV, float u1,
                                  float u2, bool sampleCoord, float q[3]) {
    float z[3] = {x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2],
                  x[0] * y[1] - x[1] * y[0]};
    const float dir[3] = {c[0] - p[0], c[1] - p[1], c[2] - p[2]};
    float z0 = dir[0] * z[0] + dir[1] * z[1] + dir[2] * z[2];
    if (z0 > 0.0f) {
        z[0] = -z[0]; z[1] = -z[1]; z[2] = -z[2];
        z0 = -z0;
    }
    const float xc = dir[0] * x[0] + dir[1] * x[1] + dir[2] * x[2];
    const float yc = dir[0] * y[0] + dir[1] * y[1] + dir[2] * y[2];
    const float x0 = xc - 0.5f * lenU, x1 = xc + 0.5f * lenU;
    const float y0 = yc - 0.5f * lenV, y1 = yc + 0.5f * lenV;
    float nz[4] = {-y0, x1, y1, -x0};
    for (int i = 0; i < 4; ++i) nz[i] /= sqrtf(nz[i] * nz[i] + z0 * z0);
    // safe_asinf: clamp to [-1, 1].
    const float g0 = asinf(fminf(1.0f, fmaxf(-1.0f, -nz[0] * nz[1])));
    const float g1 = asinf(fminf(1.0f, fmaxf(-1.0f, -nz[1] * nz[2])));
    const float g2 = asinf(fminf(1.0f, fmaxf(-1.0f, -nz[2] * nz[3])));
    const float g3 = asinf(fminf(1.0f, fmaxf(-1.0f, -nz[3] * nz[0])));
    const float S = -(g0 + g1 + g2 + g3);
    if (sampleCoord) {
        const float b0 = nz[0], b1 = nz[2], b0sq = b0 * b0;
        const float au = u1 * S + g2 + g3;
        const float sau = sinf(au);
        const float fu = (sau != 0.0f) ? (cosf(au) * b0 + b1) / sau : 0.0f;   // safe_divide
        float cu = copysignf(1.0f / sqrtf(fu * fu + b0sq), fu);
        cu = fminf(1.0f, fmaxf(-1.0f, cu));
        float xu = -(cu * z0) / fmaxf(sqrtf(1.0f - cu * cu), 1e-7f);
        xu = fminf(x1, fmaxf(x0, xu));
        const float d2 = xu * xu + z0 * z0;
        const float h0 = y0 / sqrtf(d2 + y0 * y0);
        const float h1 = y1 / sqrtf(d2 + y1 * y1);
        const float hv = h0 + u2 * (h1 - h0), hv2 = hv * hv;
        const float yv = (hv2 < 1.0f - 1e-6f) ? hv * sqrtf(d2 / (1.0f - hv2)) : y1;
        for (int i = 0; i < 3; ++i) q[i] = p[i] + xu * x[i] + yv * y[i] + z0 * z[i];
    }
    const float mn = fminf(fminf(nz[0] * nz[0], nz[1] * nz[1]), fminf(nz[2] * nz[2], nz[3] * nz[3]));
    if (S < 1e-5f || mn > 0.99999f) {
        const float t = sqrtf(dir[0] * dir[0] + dir[1] * dir[1] + dir[2] * dir[2]);
        const float den = z0 * lenU * lenV;
        return (den != 0.0f) ? (-t * t * t) / den : 0.0f;
    }
    return 1.0f / S;
}

// Astroray uses the solid-angle map only at full spread (Blender spread 180 deg,
// Cycles normalize_spread == 0). Below that Cycles first clips the rectangle
// to the spread cone (area_light_spread_clamp_light), which is not ported; the
// area-uniform draw stays there (unbiased, #852 unchanged). The half-angle
// threshold matches astroray::areaSpreadAttenuation's early-out.
AR_SPHRECT_HD inline bool fullSpread(float halfSpread) { return halfSpread >= 1.5707963f; }

}  // namespace sphrect
}  // namespace astroray

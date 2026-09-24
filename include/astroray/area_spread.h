#pragma once
// #852 — AREA-light spread attenuation, shared by the CPU (src/lights/area_light.cpp)
// and the GPU (src/gpu/gpu_nee.cuh).
//
// Source: Blender 5.2 Cycles (Apache-2.0, compatible with Astroray's LICENSE):
//   kernel/light/area.h  area_light_spread_attenuation — soft-box grid model:
//                        f(a) = max(tan(h) - tan(a), 0) * N, a = angle to the normal
//   scene/light.cpp      h = spread / 2 (Blender's spread is the FULL angle);
//                        N = 1 / (tan h - h), or 3 / h^3 for h <= 0.05 (Taylor).
// N keeps the emitted power of the Lambertian lamp (derivation):
//   int_hemi f cos(a) dw = 2 pi N int_0^h (tan h - tan a) cos a sin a da
//                        = pi N (tan h - h) = pi.
// So power(), light selection and the uniform-area NEE pdf are unchanged; f only
// reshapes the radiance. f > 0 exactly where a < h, the existing hard-cone support.
// Notes: .astroray_plan/docs/issue852-area-spread-research.md.

#include <math.h>

#if defined(__CUDACC__)
#  define AR_AREA_HD __host__ __device__
#else
#  define AR_AREA_HD
#endif

namespace astroray {

// cosA = cos(angle between emitted direction and the light normal);
// halfSpread = h in radians. h >= pi/2 (Blender spread 180 deg) -> 1 (Lambertian).
AR_AREA_HD inline float areaSpreadAttenuation(float cosA, float halfSpread) {
    if (halfSpread >= 1.5707963f) return 1.0f;
    if (cosA <= 0.0f) return 0.0f;
    const float tanH = tanf(halfSpread);
    const float norm = halfSpread > 0.05f ? 1.0f / (tanH - halfSpread)
                                          : 3.0f / (halfSpread * halfSpread * halfSpread);
    const float tanA = sqrtf(fmaxf(0.0f, 1.0f - cosA * cosA)) / cosA;
    return fmaxf((tanH - tanA) * norm, 0.0f);
}

}  // namespace astroray

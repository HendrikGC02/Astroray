// #828 — the ONE luminance-normalised Planck formula shared by the CPU volume
// emission (src/volume/volume_emission.cpp) and the GPU heterogeneous-volume
// stage (src/gpu/wavefront/stage_volume_hetero.cu), so both backends evaluate
// identical arithmetic on the identical table.
//
//   normalizedPlanck(λ,T) = B(λ,T)·1e9 / ∫ B(λ',T)·1e9·ȳ(λ') dλ'      (pkg122)
//
// evaluated in LOG space (no float underflow at any T):
//   ln(B·1e9) = ln(2hc²·1e9) − 5 ln λ − ln(expm1(hc/λkT)),
// divided by the photopic integral read from a 2048-entry table uniform in ln T
// over [30 K, 1e6 K] (linear interpolation; linear extrapolation above 1e6 K;
// 0 below 30 K). The table is built once from the exact double integral
// (astroray::volume::blackbodyLogLuminanceLut). Interpolation error h²/8·|f''|
// with f'' ≈ −hc/(λ̄kT): ≤ 0.2 % at 30 K, < 1e-4 above 1000 K.
// Constants: h, c, k of include/astroray/gr_types.h.
// Research: .astroray_plan/docs/batchq-volumes-3-research.md §1.

#pragma once

#include <cmath>

#if defined(__CUDACC__)
#  define ASTRORAY_BB_HD __host__ __device__
#else
#  define ASTRORAY_BB_HD
#endif

namespace astroray {
namespace volume {

inline constexpr int   kBBLutN       = 2048;
inline constexpr float kBBLutTMin    = 30.0f;
inline constexpr float kBBLutLnTMin  = 3.4011973817f;    // ln 30
inline constexpr float kBBLutLnTMax  = 13.8155105580f;   // ln 1e6
inline constexpr float kBBLutInvH    = 196.5564089870f;  // (N-1)/(lnTMax-lnTMin)
inline constexpr float kBBLn2hc2e9   = -15.9432662803f;  // ln(2·h·c²·1e9)
inline constexpr float kBBC2         = 1.438776877504e-2f;  // h·c/k [m·K]

// ln of the photopic integral at T (T >= kBBLutTMin), linear in ln T.
inline ASTRORAY_BB_HD float bbLogLuminance(float T, const float* lut)
{
    float u = (logf(T) - kBBLutLnTMin) * kBBLutInvH;
    int i = (int)u;
    if (i < 0) i = 0;
    if (i > kBBLutN - 2) i = kBBLutN - 2;
    float f = u - (float)i;
    return lut[i] + f * (lut[i + 1] - lut[i]);
}

// Luminance-normalised Planck radiance per nm (E[Y] == 1 for any T >= 30 K).
inline ASTRORAY_BB_HD float bbNormalizedPlanck(float lambdaNm, float T, const float* lut)
{
    if (!(T >= kBBLutTMin)) return 0.0f;
    float lam = lambdaNm * 1e-9f;
    float x = kBBC2 / (lam * T);
    if (x > 700.0f) return 0.0f;            // planck() returns 0 there
    float lnExpm1 = (x > 20.0f) ? x : logf(expm1f(x));
    return expf(kBBLn2hc2e9 - 5.0f * logf(lam) - lnExpm1 - bbLogLuminance(T, lut));
}

}  // namespace volume
}  // namespace astroray

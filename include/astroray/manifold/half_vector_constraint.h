#pragma once
// pkg64 Phase 1 — half-vector constraint for Specular Manifold Sampling.
//
// References:
//   Zeltner, Georgiev, Jakob, "Specular Manifold Sampling for Rendering
//     High-Frequency Caustics and Glints", SIGGRAPH 2020. §4.2 (Eq. 4–6).
//   Mitsuba 2 SMS reference, BSD-3-Clause:
//     https://github.com/tizian/specular-manifold-sampling
//     commit 1f0e40342a8760450d5aa6202ea096feaa70256a (2021-06-27),
//     src/librender/manifold_ss.cpp (compute_step_halfvector).
//   Hanika, Droske, Manakov, "Manifold Next Event Estimation",
//     EGSR 2015 (DOI 10.1111/cgf.12681), §4 — same generalized
//     half-vector formulation re-derived from the paper math.
//
// License: this header is original Astroray code (MIT). It re-expresses
// the public-paper math; no SMS source lines are copied. The upstream
// reference is BSD-3-Clause and would be MIT-compatible if vendored,
// but Phase 1 only needs the math.
//
// Phase 1 scope: RGB / single-IOR. Per-wavelength η is Phase 2
// (pkg64-spectral-caustics.md, Hanika 2015 §4 wavelength-Newton).

#include "../../raytracer.h"
#include <cmath>

namespace astroray::manifold {

// Generalized half-vector h(x1) for a single specular vertex x1 between
// shading point x0 and emitter point x2.
//
//   ω_i = normalize(x0 - x1)   (toward the shading point)
//   ω_o = normalize(x2 - x1)   (toward the emitter)
//   reflection : h = ω_i + ω_o
//   refraction : h = ω_i + η · ω_o    (Zeltner 2020 Eq. 4)
//
// `eta` is the relative index of refraction n_outside / n_inside on the
// transmission side. Pass eta = 1 for reflection.
inline Vec3 generalizedHalfVector(const Vec3& x0, const Vec3& x1,
                                  const Vec3& x2, float eta,
                                  bool refraction) {
    Vec3 wi = (x0 - x1).normalized();
    Vec3 wo = (x2 - x1).normalized();
    return refraction ? (wi + wo * eta) : (wi + wo);
}

// 2D half-vector residual in the tangent plane of n1.
//
// Specular constraint: at a valid stationary point, h(x1) is parallel to
// n1. Projecting h onto the tangent frame (s1, t1) gives a 2D residual
// that is zero exactly on the manifold of valid specular paths
// (Zeltner 2020 Eq. 5; Hanika 2015 Eq. 8).
inline Vec2 halfVectorResidual(const Vec3& x0, const Vec3& x1,
                               const Vec3& x2,
                               const Vec3& s1, const Vec3& t1,
                               float eta, bool refraction) {
    Vec3 h = generalizedHalfVector(x0, x1, x2, eta, refraction);
    // Normalize so the residual scale is independent of |x0-x1|, |x2-x1|.
    float len = std::sqrt(h.length2());
    if (len > 1e-12f) h = h * (1.0f / len);
    return Vec2(h.dot(s1), h.dot(t1));
}

}  // namespace astroray::manifold

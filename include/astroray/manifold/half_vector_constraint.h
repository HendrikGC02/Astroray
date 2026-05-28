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

// pkg106 Chunk A — analytic 2x2 Jacobian of the half-vector constraint.
//
// The constraint residual c(x1) = (h·s, h·t) is differentiated w.r.t. the
// surface (u,v) parameterization at the specular vertex x1. This is the
// analytic replacement for newton_iterate.h's central-difference Jacobian,
// which diverges on triangulated casters (a ±h tangent step can cross a
// triangle edge into a neighbour with a different normal — see
// pkg106-research-2026-05-28.md).
//
// Mirrors Cycles `mnee_compute_constraint_derivatives` current-vertex ("b")
// block, src/kernel/integrator/mnee.h lines 285-356 (Apache-2.0, MIT-compatible),
// and Hanika, Droske, Manakov 2015 "Manifold Next Event Estimation" §5
// (DOI 10.1111/cgf.12681). Re-expressed in Astroray's +h convention
// (h = wi + eta·wo); Cycles uses H = -(…), an overall sign that cancels in the
// Newton step. Validated analytic-vs-central-difference to ~1e-10 (flat and
// curved dn≠0 cases).
//
// The tangent frame is built FROM dp_du (s = normalize(dp_du - (dp_du·n)n),
// t = n×s) so the frame-rotation derivatives ds/du, dt/du are well-defined.
// This intentionally differs from HitRecord's arbitrary buildOrthonormalBasis
// frame: callers supply the true surface partials dp_du/dp_dv/dn_du/dn_dv
// (constant edge vectors + zero dn for a flat triangle; analytic for a sphere).
// dn_du/dn_dv must be perpendicular to n1, as for any unit-normal field.
struct HalfVectorConstraint {
    Vec2  residual;        // c = (h·s, h·t)
    Vec3  s, t;            // dp_du-derived tangent frame at x1
    // Jacobian J = dc/d(u,v), row-major: J·(du,dv) ≈ Δc.
    float j00, j01;        // d(residual.u)/du, d(residual.u)/dv
    float j10, j11;        // d(residual.v)/du, d(residual.v)/dv
    bool  valid;           // false on a degenerate (zero-length) input
};

inline HalfVectorConstraint halfVectorConstraintJacobian(
        const Vec3& x0, const Vec3& x1, const Vec3& x2, const Vec3& n1,
        const Vec3& dp_du, const Vec3& dp_dv,
        const Vec3& dn_du, const Vec3& dn_dv,
        float eta, bool refraction) {
    HalfVectorConstraint R;
    R.valid = false;
    R.residual = Vec2(0.0f, 0.0f);
    R.s = Vec3(0.0f); R.t = Vec3(0.0f);
    R.j00 = R.j01 = R.j10 = R.j11 = 0.0f;

    Vec3  wi = x0 - x1;  float li = std::sqrt(wi.length2());
    Vec3  wo = x2 - x1;  float lo = std::sqrt(wo.length2());
    if (li < 1e-12f || lo < 1e-12f) return R;
    float ili = 1.0f / li;  wi = wi * ili;
    float ilo = 1.0f / lo;  wo = wo * ilo;

    const float etaEff = refraction ? eta : 1.0f;
    Vec3  h  = wi + wo * etaEff;
    float lh = std::sqrt(h.length2());
    if (lh < 1e-12f) return R;
    const float ilh = 1.0f / lh;  h = h * ilh;
    // Scale the inverse distances by the half-vector normalization (Cycles l.288-290).
    ilo *= etaEff * ilh;
    ili *= ilh;

    // Local shading frame from dp_du (Cycles l.292-296).
    const float dp_du_dot_n = dp_du.dot(n1);
    Vec3  s  = dp_du - n1 * dp_du_dot_n;
    float ls = std::sqrt(s.length2());
    if (ls < 1e-12f) return R;
    const float inv_len_s = 1.0f / ls;  s = s * inv_len_s;
    const Vec3  t = n1.cross(s);

    // dH/du, dH/dv at the current vertex, then project off h (keep tangential).
    Vec3 dH_du = dp_du * (-(ili + ilo)) + wi * (wi.dot(dp_du) * ili) + wo * (wo.dot(dp_du) * ilo);
    Vec3 dH_dv = dp_dv * (-(ili + ilo)) + wi * (wi.dot(dp_dv) * ili) + wo * (wo.dot(dp_dv) * ilo);
    dH_du = dH_du - h * dH_du.dot(h);
    dH_dv = dH_dv - h * dH_dv.dot(h);

    // Tangent-frame derivatives ds/du, ds/dv (from dn) and dt = n×s product rule.
    Vec3 ds_du = (n1 * dp_du.dot(dn_du) + dn_du * dp_du_dot_n) * (-inv_len_s);
    Vec3 ds_dv = (n1 * dp_du.dot(dn_dv) + dn_dv * dp_du_dot_n) * (-inv_len_s);
    ds_du = ds_du - s * s.dot(ds_du);
    ds_dv = ds_dv - s * s.dot(ds_dv);
    const Vec3 dt_du = dn_du.cross(s) + n1.cross(ds_du);
    const Vec3 dt_dv = dn_dv.cross(s) + n1.cross(ds_dv);

    R.residual = Vec2(s.dot(h), t.dot(h));
    R.s = s;  R.t = t;
    R.j00 = dH_du.dot(s) + h.dot(ds_du);
    R.j01 = dH_dv.dot(s) + h.dot(ds_dv);
    R.j10 = dH_du.dot(t) + h.dot(dt_du);
    R.j11 = dH_dv.dot(t) + h.dot(dt_dv);
    R.valid = true;
    return R;
}

}  // namespace astroray::manifold

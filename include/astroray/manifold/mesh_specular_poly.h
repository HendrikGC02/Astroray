#pragma once
// pkg227 Phase 2b-flat — Specular Polynomials for a FLAT triangle facet.
//
// Deterministic, seed-free enumeration of every admissible single-vertex
// specular path (refract or reflect) on ONE triangle with a CONSTANT (flat)
// facet normal — the mesh analogue of specular_poly.h's exact sphere solver,
// replacing the single-seed Newton search of mesh_attempt.h for the flat case.
//
// Method — re-derived from the open-access paper (CLAUDE.md §6, no invented
// algorithm; the reference impl github.com/mollnn/spoly is UNLICENSED and was
// NOT read/copied):
//   Fan, Guo, Wang, Xiao, Zhang, Zhou, Chen, Hong, Guo, Yan,
//     "Specular Polynomials", ACM TOG 43(4) (SIGGRAPH 2024), article 126,
//     DOI 10.1145/3658132, arXiv:2405.13409. Paper text CC BY 4.0.
//     §3.2 generalized half-vector constraint splits into a COPLANARITY
//     constraint (d_{i-1} x d_i) . n_i = 0 and an ANGULARITY constraint;
//     §3.3 "square form" removes the angularity norm denominators by squaring,
//     admitting superfluous (sign-flipped) roots re-filtered against the SIGNED
//     residual in path space (identical structure to the CI-validated sphere
//     solver, specular_poly.h).
//
// FLAT-FACET SPECIALIZATION (this file; Phase 2b-flat — interpolated shading
// normals are the separate Phase 2b-smooth). For a single vertex on ONE triangle
// with a normal N that is CONSTANT over the facet, the paper's rational
// coordinate mapping (§3.4) and 6-piece sqrt-fit (§3.5, error < 1e-3) are NOT
// needed — they exist to propagate a vertex through a multi-bounce chain and
// through a curved (interpolated-normal) surface. With a single vertex and a
// constant normal:
//   Coplanarity  (p - x0) x (x2 - p) . N = 0  expands (p x p = 0) to
//     p . ((x2 - x0) x N) = (x0 x x2) . N ,                              (*)
//   LINEAR in p; intersected with the triangle plane {p = P0 + u e1 + v e2} it
//   confines the vertex to a LINE L (one parameter t). Working in the incidence
//   plane through x0 with normal m = (x2 - x0) x N (basis e1=norm(x2-x0),
//   e2=m x e1) gives 2D coords a=(0,0) for x0, b=(|x2-x0|,0) for x2, a constant
//   2D normal n2 for N, and p(t) AFFINE in t. Mirroring the sphere residual
//   (specular_poly.h) exactly:
//     Ci = n2 x (a - p)  deg 1 ,  Co = n2 x (b - p)  deg 1
//     Ri^2 = |a - p|^2   deg 2 ,  Ro^2 = |b - p|^2   deg 2
//     square form  Ci^2 Ro^2 - eta^2 Co^2 Ri^2 = 0   ->  DEGREE 4 in t.
//   Degree 4 independently matches the paper's Table 2 flat-normal refraction
//   degree, cross-validating the specialization (CLAUDE.md §6: cite, borrow,
//   VERIFY). Real roots are refined by one Newton polish on the signed residual
//   g(t) = Ci/Ri + eta*Co/Ro and filtered by |g| < 1e-3 (superfluous root) and
//   by triangle bounds (0 <= u,v ; u+v <= 1).
//
// Validated to < 5.7e-6 rad against solveSphereSpecular over a fine icosphere
// tessellation (scratchpad/proto_mesh_specular.py; note
// .astroray_plan/docs/pkg227-phase2b-research.md; CI oracle
// tests/test_pkg227_mesh_poly_unit.py). Convergence vs the smooth continuum is
// LINEAR in facet edge length — faceted casters render faceted caustics by
// design; smooth-shaded casters are Phase 2b-smooth.
//
// ETA CONVENTION (research note §3 — the top port risk): `eta` is passed through
// UNMODIFIED into g = Ci/Ri + eta*Co/Ro, mirroring specular_poly.h's sphere
// Ci/Co pattern literally. Inverting it (n_to/n_from) passes an isolated Snell
// sanity check but SILENTLY stops matching the sphere oracle for every
// refractive case. The unit test gates this against the sphere oracle directly.
//
// This header is original Astroray code (MIT), STL-free like specular_poly.h.

#include "../../raytracer.h"
#include "specular_poly.h"   // realRoots, polyMul (degree-4 subset of degree-6)
#include <cmath>

namespace astroray::manifold {
namespace specpoly {

struct FlatTriSolution {
    Vec3 p;   // specular vertex position on the triangle facet
    Vec3 n;   // outward (flat) facet unit normal
};

// Signed angularity residual g(t) at the affine 2D point p(t) = (px0 + t*dpx,
// py0 + t*dpy) in the incidence plane. Zero on a true solution, O(1) on a
// superfluous (squared) root — same role as specular_poly.h::signedResidual.
inline float flatTriResidual(float px0, float py0, float dpx, float dpy,
                             float b2x, float b2y, float n2x, float n2y,
                             float eta, float t) {
    const float px = px0 + t * dpx, py = py0 + t * dpy;
    // 2D cross (u x v) = ux*vy - uy*vx; a = (0,0), so a - p = (-px, -py).
    const float Ci = n2x * (-py) - n2y * (-px);
    const float Co = n2x * (b2y - py) - n2y * (b2x - px);
    const float Ri = std::sqrt(px * px + py * py);
    const float dbx = b2x - px, dby = b2y - py;
    const float Ro = std::sqrt(dbx * dbx + dby * dby);
    if (Ri < 1e-12f || Ro < 1e-12f) return 1e9f;
    return Ci / Ri + eta * Co / Ro;
}

// Enumerate admissible single-vertex specular points on ONE flat triangle facet
// (P0, P1, P2) for the configuration (x0 -> vertex -> x2). `refraction` selects
// the refractive residual (etaEff = eta) vs reflection (etaEff = 1), matching
// solveSphereSpecular. Returns the number of in-triangle, filtered solutions
// written to out[] (up to maxOut), or -1 for a degenerate configuration
// (degenerate triangle; triangle plane parallel to the coplanarity plane;
// (x2 - x0) parallel to N) where the caller must fall back to Newton/skip.
inline int solveFlatTriangleSpecular(const Vec3& x0, const Vec3& x2,
                                     const Vec3& P0, const Vec3& P1, const Vec3& P2,
                                     float eta, bool refraction,
                                     FlatTriSolution* out, int maxOut) {
    const Vec3 e1v = P1 - P0;
    const Vec3 e2v = P2 - P0;
    Vec3 N = e1v.cross(e2v);
    const float nlen2 = N.length2();
    if (nlen2 < 1e-28f) return -1;               // degenerate triangle
    N = N * (1.0f / std::sqrt(nlen2));
    const float etaEff = refraction ? eta : 1.0f;

    // Coplanarity: p . w = k  (linear in p), w = (x2 - x0) x N, k = (x0 x x2).N
    const Vec3 d = x2 - x0;
    const Vec3 w = d.cross(N);
    const float k = x0.cross(x2).dot(N);
    // Restrict to the triangle plane p = P0 + u*e1v + v*e2v:
    //   u*(e1v.w) + v*(e2v.w) = k - P0.w
    const float c1 = e1v.dot(w), c2 = e2v.dot(w), rhs = k - P0.dot(w);
    if (std::fabs(c1) < 1e-14f && std::fabs(c2) < 1e-14f) return -1;

    // Incidence-plane 2D basis (m == w up to scale; degenerate if d || N).
    const float mlen2 = w.length2();
    if (mlen2 < 1e-28f) return -1;
    const Vec3 mUnit = w * (1.0f / std::sqrt(mlen2));
    const float dlen2 = d.length2();
    if (dlen2 < 1e-20f) return -1;
    const Vec3 eb1 = d * (1.0f / std::sqrt(dlen2));
    const Vec3 eb2 = mUnit.cross(eb1);

    // p(t) affine: parameterise L by u (if |c2| usable) else by v. Sample the
    // line at t=0,1 in 3D, then express in the incidence-plane basis (relative
    // to x0) to get the affine 2D map directly (mirrors the prototype).
    const bool paramIsU = std::fabs(c2) > 1e-10f;
    Vec3 pA, pB;   // p(0), p(1) in 3D
    if (paramIsU) {
        const float v0 = rhs / c2;               // u = 0
        const float v1 = (rhs - c1) / c2;         // u = 1
        pA = P0 + e2v * v0;
        pB = P0 + e1v + e2v * v1;
    } else {
        const float u0 = rhs / c1;               // v = 0
        const float u1 = (rhs - c2) / c1;         // v = 1
        pA = P0 + e1v * u0;
        pB = P0 + e1v * u1 + e2v;
    }
    const Vec3 qA = pA - x0, qB = pB - x0;
    const float px0 = qA.dot(eb1), py0 = qA.dot(eb2);
    const float px1 = qB.dot(eb1), py1 = qB.dot(eb2);
    const float dpx = px1 - px0, dpy = py1 - py0;
    const Vec3 db = x2 - x0;
    const float b2x = db.dot(eb1), b2y = db.dot(eb2);
    const float n2x = N.dot(eb1),  n2y = N.dot(eb2);

    // Ci(t) = n2 x (a - p(t)), a = (0,0):  {n2x*(-py0)-n2y*(-px0), n2x*(-dpy)-n2y*(-dpx)}
    const float Ci[2] = { n2x * (-py0) - n2y * (-px0), n2x * (-dpy) - n2y * (-dpx) };
    // Co(t) = n2 x (b - p(t)):  const term uses b2; linear term same as Ci's.
    const float Co[2] = { n2x * (b2y - py0) - n2y * (b2x - px0), Ci[1] };
    // Ri^2(t) = |a - p(t)|^2, Ro^2(t) = |b - p(t)|^2  (each degree 2 in t).
    const float Ri2[3] = { px0 * px0 + py0 * py0,
                           2.0f * (px0 * dpx + py0 * dpy),
                           dpx * dpx + dpy * dpy };
    const float ob0 = b2x - px0, ob1 = b2y - py0;
    const float Ro2[3] = { ob0 * ob0 + ob1 * ob1,
                           -2.0f * (ob0 * dpx + ob1 * dpy),
                           dpx * dpx + dpy * dpy };

    float Ci2[3], Co2[3], term1[5], term2[5];
    polyMul(Ci, 2, Ci, 2, Ci2);          // deg 2
    polyMul(Co, 2, Co, 2, Co2);          // deg 2
    polyMul(Ci2, 3, Ro2, 3, term1);      // deg 4
    polyMul(Co2, 3, Ri2, 3, term2);      // deg 4
    const float e2 = etaEff * etaEff;
    float c[5];
    for (int i = 0; i < 5; ++i) c[i] = term1[i] - e2 * term2[i];

    float troots[kMaxRoots];
    const int nr = realRoots(c, 4, troots);

    const float kResidualTol = 1e-3f;
    int n = 0;
    for (int i = 0; i < nr && n < maxOut; ++i) {
        float t = troots[i];
        // One Newton polish on g(t) (paper §4; mirrors the sphere polish).
        for (int it = 0; it < 4; ++it) {
            const float h = 1e-5f;
            const float g0 = flatTriResidual(px0, py0, dpx, dpy, b2x, b2y, n2x, n2y, etaEff, t);
            const float gp = flatTriResidual(px0, py0, dpx, dpy, b2x, b2y, n2x, n2y, etaEff, t + h);
            const float gm = flatTriResidual(px0, py0, dpx, dpy, b2x, b2y, n2x, n2y, etaEff, t - h);
            const float dg = (gp - gm) * (0.5f / h);
            if (std::fabs(dg) < 1e-9f) break;
            t -= g0 / dg;
        }
        if (std::fabs(flatTriResidual(px0, py0, dpx, dpy, b2x, b2y, n2x, n2y, etaEff, t)) >
            kResidualTol)
            continue;  // superfluous (squared-form) root

        // Reconstruct the 3D vertex and its barycentric (u, v) for the triangle test.
        float u, v;
        Vec3 p3d;
        if (paramIsU) { u = t; v = (rhs - c1 * t) / c2; }
        else          { v = t; u = (rhs - c2 * t) / c1; }
        p3d = P0 + e1v * u + e2v * v;
        if (u < -1e-6f || v < -1e-6f || (u + v) > 1.0f + 1e-6f) continue;  // outside facet

        // Dedup near-double roots (a fold bracketed twice as two close roots).
        bool dup = false;
        for (int j = 0; j < n; ++j)
            if ((out[j].p - p3d).length2() < 1e-10f) { dup = true; break; }
        if (dup) continue;
        out[n].p = p3d;
        out[n].n = N;
        ++n;
    }
    return n;
}

}  // namespace specpoly
}  // namespace astroray::manifold

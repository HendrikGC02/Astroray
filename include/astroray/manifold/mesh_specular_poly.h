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
#include "mesh_caustic.h"    // CausticTri (per-vertex normals for the smooth polish)
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

// ---------------------------------------------------------------------------
// pkg227 Phase 2b-smooth — interpolated (smooth) shading-normal support.
//
// The flat solver above enumerates the specular BASINS (position on the facet).
// For a smooth-shaded caster the SHADING normal is the interpolated
//   n̂(u,v) = normalize(n0*(1-u-v) + n1*u + n2*v),
// nonlinear in (u,v) — porting the paper's degree-inflated interpolated-normal
// polynomial (Fan §6) is unnecessary: a short Newton polish of the flat root on
// the standard MNEE half-vector residual (Hanika 2015 / Cycles mnee.h) reaches
// the smooth solution. The interpolated normal deviates from the true smooth
// normal by O(edge^2), so the polished vertex converges QUADRATICALLY in facet
// edge length (vs the flat solver's linear) — reaching the sphere oracle at
// ~80k triangles where flat needs ~3e8 (proven in
// scratchpad/proto_mesh_smooth.py; note pkg227-phase2b-smooth-research.md). The
// vertex POSITION stays on the flat facet (faceted geometry, interpolated
// shading normal) — matching Cycles' smooth shading.
// ---------------------------------------------------------------------------

// MNEE half-vector residual (2 tangential components) at facet point p with
// shading normal nhat: h = d1 + eta*d2 (d1 toward x0, d2 toward x2), the residual
// is the part of h perpendicular to nhat, expressed in an nhat-orthonormal frame.
// Zero exactly on a specular vertex (h || nhat).
inline void mneeResidual2(const Vec3& p, const Vec3& x0, const Vec3& x2,
                          const Vec3& nhat, float eta, float& r0, float& r1) {
    const Vec3 d1 = (x0 - p).normalized();
    const Vec3 d2 = (x2 - p).normalized();
    const Vec3 h = d1 + d2 * eta;
    const Vec3 ht = h - nhat * h.dot(nhat);
    const Vec3 a = (std::fabs(nhat.x) < 0.9f) ? Vec3(1.0f, 0.0f, 0.0f)
                                              : Vec3(0.0f, 1.0f, 0.0f);
    const Vec3 t1 = (a - nhat * a.dot(nhat)).normalized();
    const Vec3 t2 = nhat.cross(t1);
    r0 = ht.dot(t1);
    r1 = ht.dot(t2);
}

// Newton-polish a flat-facet specular seed vertex to the SMOOTH (interpolated-
// normal) solution, staying on the facet plane. On convergence fills outP (the
// polished vertex), outN (the interpolated unit shading normal there), and
// outDnDu/outDnDv (the smooth unit-normal partials for the MNEE weight, matching
// surface_partials.h::trianglePartialsSmooth). Returns false if it does not
// converge or the vertex leaves the facet. `seedP` is the flat root (or the facet
// centroid when the flat quartic found none).
inline bool polishSmoothVertex(const Vec3& seedP, const CausticTri& tr,
                               const Vec3& x0, const Vec3& x2, float eta,
                               Vec3& outP, Vec3& outN, Vec3& outDnDu, Vec3& outDnDv,
                               int iters = 8) {
    const Vec3 e1 = tr.v1 - tr.v0;
    const Vec3 e2 = tr.v2 - tr.v0;
    const float d11 = e1.dot(e1), d12 = e1.dot(e2), d22 = e2.dot(e2);
    const float den = d11 * d22 - d12 * d12;
    if (std::fabs(den) < 1e-20f) return false;
    const Vec3 vp = seedP - tr.v0;
    float u = (d22 * vp.dot(e1) - d12 * vp.dot(e2)) / den;
    float v = (d11 * vp.dot(e2) - d12 * vp.dot(e1)) / den;

    for (int it = 0; it < iters; ++it) {
        const Vec3 p = tr.v0 + e1 * u + e2 * v;
        const Vec3 nhat = (tr.n0 * (1.0f - u - v) + tr.n1 * u + tr.n2 * v).normalized();
        float r0, r1;
        mneeResidual2(p, x0, x2, nhat, eta, r0, r1);
        if (r0 * r0 + r1 * r1 < 1e-20f) break;
        const float hs = 1e-5f;
        const Vec3 pu = tr.v0 + e1 * (u + hs) + e2 * v;
        const Vec3 nu = (tr.n0 * (1.0f - (u + hs) - v) + tr.n1 * (u + hs) + tr.n2 * v).normalized();
        float ru0, ru1; mneeResidual2(pu, x0, x2, nu, eta, ru0, ru1);
        const Vec3 pv = tr.v0 + e1 * u + e2 * (v + hs);
        const Vec3 nv = (tr.n0 * (1.0f - u - (v + hs)) + tr.n1 * u + tr.n2 * (v + hs)).normalized();
        float rv0, rv1; mneeResidual2(pv, x0, x2, nv, eta, rv0, rv1);
        const float j00 = (ru0 - r0) / hs, j01 = (rv0 - r0) / hs;
        const float j10 = (ru1 - r1) / hs, j11 = (rv1 - r1) / hs;
        const float jdet = j00 * j11 - j01 * j10;
        if (std::fabs(jdet) < 1e-20f) break;
        float du = (-r0 * j11 + r1 * j01) / jdet;   // solve J*(du,dv) = -(r0,r1)
        float dv = (r0 * j10 - r1 * j00) / jdet;
        du = du < -0.5f ? -0.5f : (du > 0.5f ? 0.5f : du);   // damp to the facet nbhd
        dv = dv < -0.5f ? -0.5f : (dv > 0.5f ? 0.5f : dv);
        u += du; v += dv;
    }

    const Vec3 p = tr.v0 + e1 * u + e2 * v;
    const Vec3 ni = tr.n0 * (1.0f - u - v) + tr.n1 * u + tr.n2 * v;
    const float len = std::sqrt(ni.length2());
    if (len < 1e-12f) return false;
    const Vec3 nhat = ni * (1.0f / len);
    float r0, r1;
    mneeResidual2(p, x0, x2, nhat, eta, r0, r1);
    if (r0 * r0 + r1 * r1 > 1e-12f) return false;                       // not converged
    if (u < -1e-4f || v < -1e-4f || (u + v) > 1.0f + 1e-4f) return false;  // left facet

    outP = p;
    outN = nhat;
    const float invLen = 1.0f / len;
    const Vec3 dni_du = tr.n1 - tr.n0;
    const Vec3 dni_dv = tr.n2 - tr.n0;
    outDnDu = (dni_du - nhat * nhat.dot(dni_du)) * invLen;
    outDnDv = (dni_dv - nhat * nhat.dot(dni_dv)) * invLen;
    return true;
}

}  // namespace specpoly
}  // namespace astroray::manifold

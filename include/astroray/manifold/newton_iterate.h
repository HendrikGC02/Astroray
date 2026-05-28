#pragma once
// pkg64 Phase 1 — Newton iteration on the specular manifold.
//
// References:
//   Zeltner et al. 2020 §4.3 (the "newton_solver" loop).
//   Mitsuba 2 SMS reference, BSD-3-Clause:
//     https://github.com/tizian/specular-manifold-sampling
//     commit 1f0e40342a8760450d5aa6202ea096feaa70256a (2021-06-27),
//     src/librender/manifold_ss.cpp::newton_solver — generic shape:
//       repeat until converged:
//         c   = constraint(p)
//         J   = jacobian(p)
//         dp  = -J^{-1} c
//         p   = step(p, dp)             // tangent walk + reproject
//
// This header provides the algorithmic skeleton. It is shape-agnostic:
// callers pass the constraint evaluation and the reprojection step as
// std::function callbacks. The integrator
// (plugins/integrators/sms_caustic_path_tracer.cpp) supplies sphere-
// based reprojection via the analytic ray/sphere hit; future passes
// can plug in BVH-based ray-cast reprojection for general meshes.
//
// Phase 1 keeps the Jacobian as a numerical (central-difference)
// approximation. Switching to the analytic Jacobian from
// Zeltner 2020 §4.3 / Hanika 2015 §5 is a straightforward Phase 2/3
// optimization once the skeleton is validated.

#include "../../raytracer.h"
#include "half_vector_constraint.h"  // pkg106 Chunk B: analytic Jacobian path
#include <cmath>
#include <functional>

namespace astroray::manifold {

struct NewtonResult {
    Vec3   x1;            // converged manifold vertex (or last iterate)
    Vec3   n1;            // surface normal at x1
    Vec3   s1, t1;        // tangent frame at x1
    bool   converged;
    int    iterations;
    float  residualNorm;  // |c(x1)| at termination
};

struct NewtonConfig {
    int   maxIterations = 20;     // SMS reference default
    float tolerance     = 1e-4f;  // |c| below this counts as converged
    float step          = 1e-3f;  // central-difference step in tangent plane
    float damping       = 1.0f;   // Levenberg-style damping (1 = pure Newton)
};

// Constraint: returns the 2D residual c(x1) at the supplied vertex.
// The 2D coordinates are in the tangent plane of the *current* x1.
using ConstraintFn = std::function<Vec2(const Vec3& x1, const Vec3& n1,
                                        const Vec3& s1, const Vec3& t1)>;

// Reproject: given the current x1 and a tangent-plane offset (du, dv),
// returns the new vertex on the specular surface together with its
// normal and tangent frame. Returns false if the offset misses the
// surface.
using ReprojectFn = std::function<bool(const Vec3& x1, const Vec3& s1,
                                       const Vec3& t1, float du, float dv,
                                       Vec3& outX, Vec3& outN,
                                       Vec3& outS, Vec3& outT)>;

// Pure-Newton iteration on the manifold. Returns once |c| < tol or
// iteration budget exhausted. The caller is responsible for sampling a
// reasonable seed `x1Init` (Zeltner 2020 §4.4 suggests uniform on the
// caster's surface; we mirror that in the integrator).
inline NewtonResult solve(const Vec3& x1Init, const Vec3& n1Init,
                          const Vec3& s1Init, const Vec3& t1Init,
                          const ConstraintFn& constraint,
                          const ReprojectFn&  reproject,
                          const NewtonConfig& cfg = {}) {
    NewtonResult R;
    R.x1 = x1Init; R.n1 = n1Init; R.s1 = s1Init; R.t1 = t1Init;
    R.converged = false; R.iterations = 0; R.residualNorm = 0.0f;

    for (int it = 0; it < cfg.maxIterations; ++it) {
        R.iterations = it + 1;
        Vec2 c = constraint(R.x1, R.n1, R.s1, R.t1);
        R.residualNorm = std::sqrt(c.u * c.u + c.v * c.v);
        if (R.residualNorm < cfg.tolerance) { R.converged = true; break; }

        // Numerical 2x2 Jacobian via central differences in the tangent
        // plane. Mitsuba's reference uses an analytic form; this is
        // Phase 1 scaffolding (CLAUDE.md §2 — minimum that solves the
        // problem; revisit when convergence is the bottleneck).
        const float h = cfg.step;
        Vec3 xP, nP, sP, tP;
        Vec2 cu_p, cu_m, cv_p, cv_m;
        if (!reproject(R.x1, R.s1, R.t1,  h, 0, xP, nP, sP, tP)) break;
        cu_p = constraint(xP, nP, sP, tP);
        if (!reproject(R.x1, R.s1, R.t1, -h, 0, xP, nP, sP, tP)) break;
        cu_m = constraint(xP, nP, sP, tP);
        if (!reproject(R.x1, R.s1, R.t1, 0,  h, xP, nP, sP, tP)) break;
        cv_p = constraint(xP, nP, sP, tP);
        if (!reproject(R.x1, R.s1, R.t1, 0, -h, xP, nP, sP, tP)) break;
        cv_m = constraint(xP, nP, sP, tP);

        const float inv2h = 0.5f / h;
        float J00 = (cu_p.u - cu_m.u) * inv2h;
        float J10 = (cu_p.v - cu_m.v) * inv2h;
        float J01 = (cv_p.u - cv_m.u) * inv2h;
        float J11 = (cv_p.v - cv_m.v) * inv2h;

        float det = J00 * J11 - J01 * J10;
        if (std::fabs(det) < 1e-12f) break;
        float invDet = 1.0f / det;

        // Solve J · dp = -c  →  dp = -J^{-1} c.
        float du = -invDet * ( J11 * c.u - J01 * c.v) * cfg.damping;
        float dv = -invDet * (-J10 * c.u + J00 * c.v) * cfg.damping;

        Vec3 xNew, nNew, sNew, tNew;
        if (!reproject(R.x1, R.s1, R.t1, du, dv, xNew, nNew, sNew, tNew)) break;
        R.x1 = xNew; R.n1 = nNew; R.s1 = sNew; R.t1 = tNew;
    }
    return R;
}

// ---------------------------------------------------------------------------
// pkg106 Chunk B — analytic-Jacobian manifold solve.
//
// Same Newton loop as solve() above, but the 2x2 Jacobian comes from
// halfVectorConstraintJacobian (Cycles mnee.h analytic derivatives) instead of
// central differences. The FD path reprojects with +/-h tangent steps and
// finite-differences the constraint; on a triangulated caster a +/-h step can
// cross a triangle edge into a neighbour with a different normal, producing a
// spurious Jacobian discontinuity that stalls/diverges Newton (the SMS-fails-
// on-triangles failure, see pkg106-research-2026-05-28.md). The analytic
// Jacobian has no such artefact.
// ---------------------------------------------------------------------------
struct AnalyticNewtonResult {
    Vec3  x1, n1;                       // converged manifold vertex + normal
    Vec3  dp_du, dp_dv, dn_du, dn_dv;   // surface partials at x1
    bool  converged;
    int   iterations;
    float residualNorm;
};

// Reproject for the analytic path: given the current vertex x1 and a tangent
// step (du, dv) in the constraint's (s, t) frame, return the new surface point,
// its unit normal, and the surface partials there (from surface_partials.h on
// real geometry; a closed form for analytic surfaces). Returns false if the
// step leaves the surface.
using ReprojectFnAnalytic = std::function<bool(
    const Vec3& x1, const Vec3& s, const Vec3& t, float du, float dv,
    Vec3& outX, Vec3& outN,
    Vec3& outDpDu, Vec3& outDpDv, Vec3& outDnDu, Vec3& outDnDv)>;

inline AnalyticNewtonResult solveAnalytic(
        const Vec3& x0, const Vec3& x2, float eta, bool refraction,
        const Vec3& x1Init, const Vec3& n1Init,
        const Vec3& dpduInit, const Vec3& dpdvInit,
        const Vec3& dnduInit, const Vec3& dndvInit,
        const ReprojectFnAnalytic& reproject,
        const NewtonConfig& cfg = {}) {
    AnalyticNewtonResult R;
    R.x1 = x1Init; R.n1 = n1Init;
    R.dp_du = dpduInit; R.dp_dv = dpdvInit; R.dn_du = dnduInit; R.dn_dv = dndvInit;
    R.converged = false; R.iterations = 0; R.residualNorm = 0.0f;

    for (int it = 0; it < cfg.maxIterations; ++it) {
        R.iterations = it + 1;
        HalfVectorConstraint c = halfVectorConstraintJacobian(
            x0, R.x1, x2, R.n1, R.dp_du, R.dp_dv, R.dn_du, R.dn_dv, eta, refraction);
        if (!c.valid) break;
        R.residualNorm = std::sqrt(c.residual.u * c.residual.u +
                                   c.residual.v * c.residual.v);
        if (R.residualNorm < cfg.tolerance) { R.converged = true; break; }

        const float det = c.j00 * c.j11 - c.j01 * c.j10;
        if (std::fabs(det) < 1e-12f) break;
        const float invDet = 1.0f / det;
        // Solve J * (du,dv) = -c  =>  (du,dv) = -J^{-1} c.
        const float du = -invDet * ( c.j11 * c.residual.u - c.j01 * c.residual.v) * cfg.damping;
        const float dv = -invDet * (-c.j10 * c.residual.u + c.j00 * c.residual.v) * cfg.damping;

        Vec3 nx, nn, ndpu, ndpv, ndnu, ndnv;
        if (!reproject(R.x1, c.s, c.t, du, dv, nx, nn, ndpu, ndpv, ndnu, ndnv)) break;
        R.x1 = nx; R.n1 = nn;
        R.dp_du = ndpu; R.dp_dv = ndpv; R.dn_du = ndnu; R.dn_dv = ndnv;
    }
    return R;
}

}  // namespace astroray::manifold

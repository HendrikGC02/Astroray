#pragma once
// pkg106 Chunk C — multi-vertex specular manifold chain (block-tridiagonal
// Newton). A prism rainbow needs TWO refractive vertices (entry + exit face);
// the single-vertex solver (half_vector_constraint.h) cannot represent it.
//
// Ports Cycles mnee.h mnee_compute_constraint_derivatives (the a=prev / b=current
// / c=next block-tridiagonal Jacobian, lines 248-365, Apache-2.0) + the
// manifold-walk Newton, for a chain x0 -> v[0] -> ... -> v[N-1] -> light.
// Astroray +h convention (h = wi + eta*wo); Hanika 2015 §5. Validated
// analytic-vs-finite-difference to ~1e-11 and damped-Newton convergence on a
// forward-traced 2-refraction chain (4 iters) — see
// pkg106-research-2026-05-28.md.

#include "../../raytracer.h"
#include "half_vector_constraint.h"
#include "newton_iterate.h"   // NewtonConfig
#include <cmath>
#include <functional>

namespace astroray::manifold {

inline constexpr int kMaxChainVertices = 4;  // prism uses 2; headroom for chains

struct ChainVertex {
    Vec3  p, n;                      // position + unit normal
    Vec3  dp_du, dp_dv;              // surface position partials
    Vec3  dn_du, dn_dv;              // unit-normal partials (perp to n; 0 if flat)
    float eta = 1.0f;                // material IOR ratio (1 = reflection)
};

// 2x2 block written row-major into a (2N x 2N) dense matrix at block (bi, bj).
inline void mnee_writeBlock(float* J, int n2, int bi, int bj,
                            float m00, float m01, float m10, float m11) {
    J[(2 * bi + 0) * n2 + (2 * bj + 0)] = m00;
    J[(2 * bi + 0) * n2 + (2 * bj + 1)] = m01;
    J[(2 * bi + 1) * n2 + (2 * bj + 0)] = m10;
    J[(2 * bi + 1) * n2 + (2 * bj + 1)] = m11;
}

// Evaluate the chain constraint residual (length 2N) and the block-tridiagonal
// Jacobian J (row-major 2N x 2N) and per-vertex tangent frames (s[i], t[i]).
// `refraction` selects h = wi + eta*wo (true) vs wi + wo (false, reflection).
// Returns false on a degenerate vertex (zero-length direction / half-vector).
inline bool chainEval(const ChainVertex* v, int N, const Vec3& x0, const Vec3& light,
                      bool refraction, float* residual, float* J, Vec3* sOut, Vec3* tOut) {
    const int n2 = 2 * N;
    for (int k = 0; k < n2 * n2; ++k) J[k] = 0.0f;

    for (int i = 0; i < N; ++i) {
        const ChainVertex& vi = v[i];
        const Vec3 prev = (i == 0)     ? x0    : v[i - 1].p;
        const Vec3 next = (i == N - 1) ? light : v[i + 1].p;

        Vec3 wi = prev - vi.p; float li = std::sqrt(wi.length2());
        Vec3 wo = next - vi.p; float lo = std::sqrt(wo.length2());
        if (li < 1e-12f || lo < 1e-12f) return false;
        float ili = 1.0f / li; wi = wi * ili;
        float ilo = 1.0f / lo; wo = wo * ilo;

        float eta = refraction ? vi.eta : 1.0f;
        if (wi.dot(vi.n) < 0.0f) eta = 1.0f / eta;  // entering from inside

        Vec3 h = wi + wo * eta; float lh = std::sqrt(h.length2());
        if (lh < 1e-12f) return false;
        const float ilh = 1.0f / lh; h = h * ilh;
        ilo *= eta * ilh;
        ili *= ilh;

        const float dpdn = vi.dp_du.dot(vi.n);
        Vec3 s = vi.dp_du - vi.n * dpdn;
        float ls = std::sqrt(s.length2());
        if (ls < 1e-12f) return false;
        const float inv_len_s = 1.0f / ls; s = s * inv_len_s;
        const Vec3 t = vi.n.cross(s);
        sOut[i] = s; tOut[i] = t;

        residual[2 * i + 0] = s.dot(h);
        residual[2 * i + 1] = t.dot(h);

        // b block (current vertex) — includes tangent-frame ds/dt terms (0 if flat).
        Vec3 dH_du = vi.dp_du * (-(ili + ilo)) + wi * (wi.dot(vi.dp_du) * ili) + wo * (wo.dot(vi.dp_du) * ilo);
        Vec3 dH_dv = vi.dp_dv * (-(ili + ilo)) + wi * (wi.dot(vi.dp_dv) * ili) + wo * (wo.dot(vi.dp_dv) * ilo);
        dH_du = dH_du - h * dH_du.dot(h);
        dH_dv = dH_dv - h * dH_dv.dot(h);
        Vec3 ds_du = (vi.n * vi.dp_du.dot(vi.dn_du) + vi.dn_du * dpdn) * (-inv_len_s);
        Vec3 ds_dv = (vi.n * vi.dp_du.dot(vi.dn_dv) + vi.dn_dv * dpdn) * (-inv_len_s);
        ds_du = ds_du - s * s.dot(ds_du);
        ds_dv = ds_dv - s * s.dot(ds_dv);
        const Vec3 dt_du = vi.dn_du.cross(s) + vi.n.cross(ds_du);
        const Vec3 dt_dv = vi.dn_dv.cross(s) + vi.n.cross(ds_dv);
        mnee_writeBlock(J, n2, i, i,
                        dH_du.dot(s) + h.dot(ds_du), dH_dv.dot(s) + h.dot(ds_dv),
                        dH_du.dot(t) + h.dot(dt_du), dH_dv.dot(t) + h.dot(dt_dv));

        // a block (w.r.t. previous manifold vertex) — projected on this vertex's frame.
        if (i > 0) {
            const ChainVertex& vp = v[i - 1];
            Vec3 a_du = (vp.dp_du - wi * wi.dot(vp.dp_du)) * ili;
            Vec3 a_dv = (vp.dp_dv - wi * wi.dot(vp.dp_dv)) * ili;
            a_du = a_du - h * a_du.dot(h);
            a_dv = a_dv - h * a_dv.dot(h);
            mnee_writeBlock(J, n2, i, i - 1,
                            a_du.dot(s), a_dv.dot(s), a_du.dot(t), a_dv.dot(t));
        }
        // c block (w.r.t. next manifold vertex).
        if (i < N - 1) {
            const ChainVertex& vn = v[i + 1];
            Vec3 c_du = (vn.dp_du - wo * wo.dot(vn.dp_du)) * ilo;
            Vec3 c_dv = (vn.dp_dv - wo * wo.dot(vn.dp_dv)) * ilo;
            c_du = c_du - h * c_du.dot(h);
            c_dv = c_dv - h * c_dv.dot(h);
            mnee_writeBlock(J, n2, i, i + 1,
                            c_du.dot(s), c_dv.dot(s), c_du.dot(t), c_dv.dot(t));
        }
    }
    return true;
}

// Dense linear solve A x = b (row-major A, size m<=2*kMaxChainVertices) via
// Gaussian elimination with partial pivoting. Returns false if singular.
inline bool mnee_solveDense(float* A, float* b, int m) {
    for (int col = 0; col < m; ++col) {
        int piv = col; float best = std::fabs(A[col * m + col]);
        for (int r = col + 1; r < m; ++r) {
            float val = std::fabs(A[r * m + col]);
            if (val > best) { best = val; piv = r; }
        }
        if (best < 1e-12f) return false;
        if (piv != col) {
            for (int c = 0; c < m; ++c) std::swap(A[col * m + c], A[piv * m + c]);
            std::swap(b[col], b[piv]);
        }
        const float inv = 1.0f / A[col * m + col];
        for (int r = col + 1; r < m; ++r) {
            const float f = A[r * m + col] * inv;
            if (f == 0.0f) continue;
            for (int c = col; c < m; ++c) A[r * m + c] -= f * A[col * m + c];
            b[r] -= f * b[col];
        }
    }
    for (int r = m - 1; r >= 0; --r) {
        float sum = b[r];
        for (int c = r + 1; c < m; ++c) sum -= A[r * m + c] * b[c];
        b[r] = sum / A[r * m + r];
    }
    return true;
}

struct ChainResult {
    bool  converged = false;
    int   iterations = 0;
    float residualNorm = 0.0f;
};

// Reproject one chain vertex `i` after a tangent step (du,dv) in its (s,t)
// frame back onto its surface, refreshing position/normal/partials.
using ReprojectChainFn = std::function<bool(
    int i, const Vec3& s, const Vec3& t, float du, float dv, ChainVertex& v)>;

// Damped, step-clamped block Newton on the chain (mirrors Cycles' beta step
// control). Updates v[] in place; returns convergence.
inline ChainResult solveChain(ChainVertex* v, int N, const Vec3& x0, const Vec3& light,
                              bool refraction, const ReprojectChainFn& reproject,
                              const NewtonConfig& cfg = {}, float maxStep = 0.3f) {
    ChainResult R;
    if (N <= 0 || N > kMaxChainVertices) return R;
    const int n2 = 2 * N;
    float residual[2 * kMaxChainVertices];
    float J[(2 * kMaxChainVertices) * (2 * kMaxChainVertices)];
    Vec3  s[kMaxChainVertices], t[kMaxChainVertices];

    for (int it = 0; it < cfg.maxIterations; ++it) {
        R.iterations = it + 1;
        if (!chainEval(v, N, x0, light, refraction, residual, J, s, t)) break;
        float rn = 0.0f;
        for (int k = 0; k < n2; ++k) rn += residual[k] * residual[k];
        rn = std::sqrt(rn);
        R.residualNorm = rn;
        if (rn < cfg.tolerance) { R.converged = true; break; }

        float rhs[2 * kMaxChainVertices];
        for (int k = 0; k < n2; ++k) rhs[k] = -residual[k];
        if (!mnee_solveDense(J, rhs, n2)) break;  // step now in rhs

        // Clamp the largest component (Cycles beta-style) for stability.
        float mx = 0.0f;
        for (int k = 0; k < n2; ++k) mx = std::max(mx, std::fabs(rhs[k]));
        const float beta = (mx > maxStep) ? (maxStep / mx) : 1.0f;

        bool ok = true;
        for (int i = 0; i < N && ok; ++i) {
            ok = reproject(i, s[i], t[i], rhs[2 * i] * cfg.damping * beta,
                           rhs[2 * i + 1] * cfg.damping * beta, v[i]);
        }
        if (!ok) break;
    }
    return R;
}

// ---------------------------------------------------------------------------
// Generalized geometry term (MNEE transfer matrix).
//
// Ports Cycles intern/cycles/kernel/integrator/mnee.h
// mnee_compute_transfer_matrix (lines 663-731, Apache-2.0) — the area-light
// (positional) branch. The crude clamped solid-angle factor cannot localize a
// caustic; this is the term that concentrates energy where the chain Jacobian
// is near-singular (the caustic) and ~0 elsewhere. Validated analytic-vs-
// brute-force-finite-difference (re-solving the manifold under a light
// perturbation) to ~1e-10 — see scratch_pkg106_geom.py / pkg106 research note.
// ---------------------------------------------------------------------------

// 2x2 matrix, row-major [[a b],[c d]] (Cycles stores these as a float4).
struct Mat2 { float a, b, c, d; };
inline float  mnee_mat2_det(const Mat2& m) { return m.a * m.d - m.b * m.c; }
inline Mat2   mnee_mat2_sub(const Mat2& x, const Mat2& y) {
    return Mat2{x.a - y.a, x.b - y.b, x.c - y.c, x.d - y.d};
}
inline Mat2   mnee_mat2_mul(const Mat2& x, const Mat2& y) {
    return Mat2{x.a * y.a + x.b * y.c, x.a * y.b + x.b * y.d,
                x.c * y.a + x.d * y.c, x.c * y.b + x.d * y.d};
}
inline Mat2   mnee_mat2_neg(const Mat2& m) { return Mat2{-m.a, -m.b, -m.c, -m.d}; }
// Inverse via cofactors; returns the determinant (0 if singular -> inv unset).
inline float  mnee_mat2_inverse(const Mat2& m, Mat2& inv) {
    const float det = mnee_mat2_det(m);
    if (std::fabs(det) < 1e-20f) return 0.0f;
    const float id = 1.0f / det;
    inv = Mat2{m.d * id, -m.b * id, -m.c * id, m.a * id};
    return det;
}
// Read the 2x2 block (bi,bj) out of the dense row-major Jacobian (size n2).
inline Mat2 mnee_block(const float* J, int n2, int bi, int bj) {
    return Mat2{J[(2 * bi + 0) * n2 + (2 * bj + 0)], J[(2 * bi + 0) * n2 + (2 * bj + 1)],
                J[(2 * bi + 1) * n2 + (2 * bj + 0)], J[(2 * bi + 1) * n2 + (2 * bj + 1)]};
}
// Orthonormal in-plane (du,dv) frame for the light surface (Cycles
// make_orthonormals); |det| of the transfer matrix is invariant to the
// in-plane rotation, so any orthonormal choice gives the same geometry term.
inline void mnee_lightFrame(const Vec3& n, Vec3& du, Vec3& dv) {
    const Vec3 a = (std::fabs(n.x) < 0.9f) ? Vec3(1.0f, 0.0f, 0.0f) : Vec3(0.0f, 1.0f, 0.0f);
    Vec3 s = a - n * a.dot(n);
    const float ls = std::sqrt(s.length2());
    du = (ls > 1e-12f) ? s * (1.0f / ls) : Vec3(1.0f, 0.0f, 0.0f);
    dv = n.cross(du);
}

// dx1_dxlight = |det(transfer matrix)| (area-on-light -> area-at-first-vertex
// Jacobian on the converged manifold). `lightN` is the emitter-surface normal
// (its tangent plane is the measure that must match the light-sampling area
// pdf). Returns 0 on a singular pivot block. `dhdxOut` (optional) receives
// |det| of the full constraint Jacobian (Cycles det_dh_dx; unused by the
// contribution but handy for diagnostics).
// `lightFixedDir` selects the collimated/distant-light branch (Cycles
// l.700-722): the constant light direction `lightDir` (= ls->D, toward the sun)
// replaces the positional light, and the result is dx1 per unit SOLID ANGLE
// (dxn_dwn = 1/|sin_theta|), matching a distant light's solid-angle pdf. The
// chain must be solved with a far light along lightDir so chainEval's b-block
// finite-distance terms vanish. Validated against the positional branch in the
// D->inf limit (dx1_area*D^2 -> dx1_solidangle) to ~2e-4 — scratch_pkg106_geom.py.
inline float chainGeometryTerm(const ChainVertex* v, int N, const Vec3& x0,
                               const Vec3& light, const Vec3& lightN,
                               float* dhdxOut = nullptr,
                               bool lightFixedDir = false,
                               const Vec3& lightDir = Vec3(0.0f)) {
    if (N <= 0 || N > kMaxChainVertices) return 0.0f;
    const int n2 = 2 * N;
    float residual[2 * kMaxChainVertices];
    float J[(2 * kMaxChainVertices) * (2 * kMaxChainVertices)];
    Vec3  s[kMaxChainVertices], t[kMaxChainVertices];
    if (!chainEval(v, N, x0, light, /*refraction=*/true, residual, J, s, t)) return 0.0f;

    // Block-tridiagonal LU (Cycles "simplified block tridiagonal LU", l.673-687).
    Mat2 Li, U[kMaxChainVertices];
    Mat2 Lk = mnee_block(J, n2, 0, 0);          // vertices[0].b
    float detLk = mnee_mat2_inverse(Lk, Li);
    if (detLk == 0.0f) return 0.0f;
    float det_dh_dx = detLk;
    for (int k = 1; k < N; ++k) {
        U[k - 1] = mnee_mat2_mul(Li, mnee_block(J, n2, k - 1, k));                // Li * c_{k-1}
        Lk = mnee_mat2_sub(mnee_block(J, n2, k, k),
                           mnee_mat2_mul(mnee_block(J, n2, k, k - 1), U[k - 1]));  // b_k - a_k U
        detLk = mnee_mat2_inverse(Lk, Li);
        if (detLk == 0.0f) return 0.0f;
        det_dh_dx *= detLk;
    }

    // Constraint derivative w.r.t. the light vertex param, at the last free vertex.
    const int mi = N - 1;
    const Vec3 sm = s[mi], tm = t[mi];
    Vec3 wi = (N == 1) ? (x0 - v[mi].p) : (v[mi - 1].p - v[mi].p);
    wi = wi.normalized();
    float eta = v[mi].eta;
    if (wi.dot(v[mi].n) < 0.0f) eta = 1.0f / eta;

    Mat2 dc_dlight;
    float dxn_dwn;
    if (lightFixedDir) {
        // Collimated / distant light (Cycles l.700-722). Constant direction
        // toward the sun; spherical-coord derivatives, result per solid angle.
        const Vec3 wo = lightDir.normalized();
        Vec3 H = (wi + wo * eta) * -1.0f;
        const float ilh = 1.0f / std::sqrt(H.length2());
        H = H * ilh;
        const float ilo = -eta * ilh;
        const float cosTheta = wo.dot(v[mi].n);
        const float sinTheta = std::sqrt(std::max(0.0f, 1.0f - cosTheta * cosTheta));
        const float cosPhi = wo.dot(sm);
        const float sinPhi = std::sqrt(std::max(0.0f, 1.0f - cosPhi * cosPhi));
        Vec3 dH_dtheta = ((sm * cosPhi + tm * sinPhi) * cosTheta - v[mi].n * sinTheta) * ilo;
        Vec3 dH_dphi = (sm * (-sinPhi) + tm * cosPhi) * (ilo * sinTheta);
        dH_dtheta = dH_dtheta - H * dH_dtheta.dot(H);
        dH_dphi = dH_dphi - H * dH_dphi.dot(H);
        dc_dlight = Mat2{dH_dtheta.dot(sm), dH_dphi.dot(sm), dH_dtheta.dot(tm), dH_dphi.dot(tm)};
        dxn_dwn = 1.0f / std::max(1e-6f, std::fabs(sinTheta));
    } else {
        // Positional / area light (Cycles l.689-727).
        Vec3 du_L, dv_L; mnee_lightFrame(lightN, du_L, dv_L);
        Vec3 wo = light - v[mi].p;
        float ilo = 1.0f / std::sqrt(wo.length2());
        wo = wo * ilo;
        Vec3 H = (wi + wo * eta) * -1.0f;
        const float ilh = 1.0f / std::sqrt(H.length2());
        H = H * ilh;
        ilo = ilo * eta * ilh;
        Vec3 dH_du = (du_L - wo * wo.dot(du_L)) * ilo;
        Vec3 dH_dv = (dv_L - wo * wo.dot(dv_L)) * ilo;
        dH_du = dH_du - H * dH_du.dot(H);
        dH_dv = dH_dv - H * dH_dv.dot(H);
        dH_du = dH_du * -1.0f;
        dH_dv = dH_dv * -1.0f;
        dc_dlight = Mat2{dH_du.dot(sm), dH_dv.dot(sm), dH_du.dot(tm), dH_dv.dot(tm)};
        dxn_dwn = 1.0f;
    }

    // Transfer matrix (Cycles back-substitution, l.729-735).
    Mat2 Tp = mnee_mat2_neg(mnee_mat2_mul(Li, dc_dlight));
    for (int k = N - 2; k >= 0; --k) Tp = mnee_mat2_neg(mnee_mat2_mul(U[k], Tp));

    if (dhdxOut) *dhdxOut = std::fabs(det_dh_dx);
    return std::fabs(mnee_mat2_det(Tp)) * dxn_dwn;
}

}  // namespace astroray::manifold

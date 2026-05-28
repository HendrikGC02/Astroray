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

}  // namespace astroray::manifold

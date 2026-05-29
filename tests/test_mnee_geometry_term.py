#!/usr/bin/env python
"""pkg106 Chunk D (radiance) — MNEE generalized geometry term.

The crude clamped solid-angle factor cannot localize a caustic; the rainbow
band needs the full block-tridiagonal transfer-matrix geometry term. This
validates manifold_chain.h::chainGeometryTerm (ported from Cycles mnee.h
mnee_compute_transfer_matrix lines 663-731, Apache-2.0):

  1. dx1_dxlight (C++ float32) matches a float64 BRUTE-FORCE finite-difference:
     perturb the light on its tangent plane, re-solve the manifold, measure
     d(v0 in (s0,t0)) / d(light in (du,dv)) directly.  This is the same
     discipline that caught every bug in Chunks A-C (float32 residuals are too
     noisy to finite-difference; the reference is float64).
  2. dh_dx (product of the LU pivot determinants) matches |det| of the dense
     block-tridiagonal Jacobian from _mnee_chain_eval.

CPU-only; runs on CI. See .astroray_plan/docs/pkg106-research-2026-05-28.md.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


def _has(name):
    return AVAILABLE and hasattr(astroray, name)


def _norm(v):
    return v / np.linalg.norm(v)


def _refract(d, n, eta):
    d = _norm(d)
    cosi = -np.dot(d, n)
    if cosi < 0:
        n = -n
        cosi = -np.dot(d, n)
    s2 = eta * eta * (1 - cosi * cosi)
    if s2 >= 1:
        return None
    return _norm(eta * d + (eta * cosi - np.sqrt(1 - s2)) * n)


def _frame(n):
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    du = _norm(a - np.dot(a, n) * n)
    return du, np.cross(n, du)


def _forward_traced_chain():
    ng = 1.5
    nA = _norm(np.array([-1.0, 0.12, 0.0]))
    nB = _norm(np.array([1.0, 0.12, 0.0]))
    pA = np.array([-0.5, 0.0, 0.0])
    pB = np.array([0.5, 0.0, 0.0])
    L = np.array([-3.0, 0.4, 0.0])
    d0 = _norm(np.array([1.0, -0.12, 0.0]))
    tA = np.dot(pA - L, nA) / np.dot(d0, nA)
    v_entry = L + d0 * tA
    d1 = _refract(d0, nA, 1.0 / ng)
    tB = np.dot(pB - v_entry, nB) / np.dot(d1, nB)
    v_exit = v_entry + d1 * tB
    duB, dvB = _frame(nB)
    duA, dvA = _frame(nA)
    return dict(ps=[v_exit, v_entry], ns=[nB, nA], dpus=[duB, duA],
                dpvs=[dvB, dvA], etas=[ng, ng], x0=v_exit + _refract(d1, nB, ng) * 2.0,
                light=L)


# --- float64 reference (mirrors manifold_chain.h chainEval, +h convention) ---
def _chain_eval(ps, ns, dpus, dpvs, etas, x0, light):
    N = len(ps)
    n2 = 2 * N
    res = np.zeros(n2)
    J = np.zeros((n2, n2))
    S, T = [None] * N, [None] * N
    for i in range(N):
        prev = x0 if i == 0 else ps[i - 1]
        nxt = light if i == N - 1 else ps[i + 1]
        ni = ns[i]
        wi = prev - ps[i]; li = np.linalg.norm(wi); ili = 1.0 / li; wi = wi * ili
        wo = nxt - ps[i]; lo = np.linalg.norm(wo); ilo = 1.0 / lo; wo = wo * ilo
        eta = etas[i]
        if np.dot(wi, ni) < 0.0:
            eta = 1.0 / eta
        h = wi + wo * eta; lh = np.linalg.norm(h); ilh = 1.0 / lh; h = h * ilh
        ilo *= eta * ilh; ili *= ilh
        s = dpus[i] - ni * np.dot(dpus[i], ni); s = s / np.linalg.norm(s)
        t = np.cross(ni, s)
        S[i], T[i] = s, t
        res[2 * i], res[2 * i + 1] = np.dot(s, h), np.dot(t, h)
        dH_du = dpus[i] * (-(ili + ilo)) + wi * (np.dot(wi, dpus[i]) * ili) + wo * (np.dot(wo, dpus[i]) * ilo)
        dH_dv = dpvs[i] * (-(ili + ilo)) + wi * (np.dot(wi, dpvs[i]) * ili) + wo * (np.dot(wo, dpvs[i]) * ilo)
        dH_du -= h * np.dot(dH_du, h); dH_dv -= h * np.dot(dH_dv, h)
        J[2 * i, 2 * i] = np.dot(dH_du, s); J[2 * i, 2 * i + 1] = np.dot(dH_dv, s)
        J[2 * i + 1, 2 * i] = np.dot(dH_du, t); J[2 * i + 1, 2 * i + 1] = np.dot(dH_dv, t)
        if i > 0:
            a_du = (dpus[i - 1] - wi * np.dot(wi, dpus[i - 1])) * ili
            a_dv = (dpvs[i - 1] - wi * np.dot(wi, dpvs[i - 1])) * ili
            a_du -= h * np.dot(a_du, h); a_dv -= h * np.dot(a_dv, h)
            J[2 * i, 2 * i - 2] = np.dot(a_du, s); J[2 * i, 2 * i - 1] = np.dot(a_dv, s)
            J[2 * i + 1, 2 * i - 2] = np.dot(a_du, t); J[2 * i + 1, 2 * i - 1] = np.dot(a_dv, t)
        if i < N - 1:
            c_du = (dpus[i + 1] - wo * np.dot(wo, dpus[i + 1])) * ilo
            c_dv = (dpvs[i + 1] - wo * np.dot(wo, dpvs[i + 1])) * ilo
            c_du -= h * np.dot(c_du, h); c_dv -= h * np.dot(c_dv, h)
            J[2 * i, 2 * i + 2] = np.dot(c_du, s); J[2 * i, 2 * i + 3] = np.dot(c_dv, s)
            J[2 * i + 1, 2 * i + 2] = np.dot(c_du, t); J[2 * i + 1, 2 * i + 3] = np.dot(c_dv, t)
    return res, J, S, T


def _solve_chain(ps0, ns, dpus, dpvs, etas, x0, light, max_iter=80, tol=1e-13):
    ps = [p.copy() for p in ps0]
    N = len(ps)
    rn = 1.0
    for _ in range(max_iter):
        res, J, S, T = _chain_eval(ps, ns, dpus, dpvs, etas, x0, light)
        rn = np.linalg.norm(res)
        if rn < tol:
            break
        step = np.linalg.solve(J, -res)
        mx = np.max(np.abs(step)); beta = (0.3 / mx) if mx > 0.3 else 1.0
        for i in range(N):
            ps[i] = ps[i] + S[i] * step[2 * i] * beta + T[i] * step[2 * i + 1] * beta
    return ps, S, T, rn


def _fd_dx1_dxlight(g, light_n, h=1e-4):
    du_L, dv_L = _frame(light_n)
    ps0, S, _, rn = _solve_chain(g["ps"], g["ns"], g["dpus"], g["dpvs"],
                                 g["etas"], g["x0"], g["light"])
    assert rn < 1e-10
    s0 = S[0]
    t0 = np.cross(g["ns"][0], s0)
    cols = []
    for dL in (du_L, dv_L):
        psp, *_ = _solve_chain(g["ps"], g["ns"], g["dpus"], g["dpvs"],
                               g["etas"], g["x0"], g["light"] + dL * h)
        psm, *_ = _solve_chain(g["ps"], g["ns"], g["dpus"], g["dpvs"],
                               g["etas"], g["x0"], g["light"] - dL * h)
        dv0 = (psp[0] - psm[0]) / (2 * h)
        cols.append(np.array([np.dot(dv0, s0), np.dot(dv0, t0)]))
    return abs(np.linalg.det(np.column_stack(cols)))


@pytest.mark.skipif(not _has("_mnee_geometry_term"),
                    reason="_mnee_geometry_term not in this build")
def test_geometry_term_matches_finite_difference():
    g = _forward_traced_chain()
    light_n = _norm(g["ps"][-1] - g["light"])
    dx1_cpp, _ = astroray._mnee_geometry_term(
        [list(p) for p in g["ps"]], [list(n) for n in g["ns"]],
        [list(d) for d in g["dpus"]], [list(d) for d in g["dpvs"]],
        list(g["etas"]), list(g["x0"]), list(g["light"]), list(light_n))
    dx1_fd = _fd_dx1_dxlight(g, light_n)
    assert dx1_cpp > 0.0
    rel = abs(dx1_cpp - dx1_fd) / max(dx1_fd, 1e-30)
    assert rel < 2e-3, f"dx1_dxlight C++ {dx1_cpp:.6e} vs FD {dx1_fd:.6e} (rel {rel:.2e})"


def _oblique_eq_chain():
    """A converged 2-refraction chain with OBLIQUE last-face incidence (so the
    fixed-direction branch's sin_theta != 0), built from two 60deg-dihedral faces
    + a far light up-sun. Returns (ps, ns, dpus, dpvs, etas, x0, sun, D)."""
    half = np.radians(30.0)
    nL = _norm(np.array([-np.cos(half), np.sin(half), 0.0]))
    nR = _norm(np.array([np.cos(half), np.sin(half), 0.0]))
    bx = 1.0 * np.tan(half)                   # equilateral base half-width (side 1)
    cL = np.array([-bx / 2, 0.0, 0.0]); cR = np.array([bx / 2, 0.0, 0.0])
    x0 = np.array([12.0, 3.0, 0.0])
    sun = _norm(np.array([-1.0, 0.0, 0.0]))   # collimated horizontal sun
    D = 1.0e4
    far = x0 + sun * D
    # seed on the two faces (aim at centroid), then solve to the far light.
    def frame(n):
        up = np.array([0, 1.0, 0]) if abs(n[1]) < 0.9 else np.array([1.0, 0, 0])
        u = _norm(up - np.dot(up, n) * n)
        return u, np.cross(n, u)
    centroid = 0.5 * (cL + cR)
    d_seed = _norm(centroid - x0)            # aim the seed at the caster
    seed_ps, ns, dpus, dpvs = [], [], [], []
    for c, n in ((cR, nR), (cL, nL)):        # nearest x0 first: right face then left
        if np.dot(n, x0 - c) < 0:
            n = -n
        t = np.dot(c - x0, n) / np.dot(d_seed, n)   # x0->centroid ray hits this plane
        seed_ps.append(x0 + d_seed * t)
        u, w = frame(n)
        ns.append(n); dpus.append(u); dpvs.append(w)
    etas = [1.5, 1.5]
    ps, S, T, rn = _solve_chain(seed_ps, ns, dpus, dpvs, etas, x0, far)
    return ps, ns, dpus, dpvs, etas, x0, far, sun, D, rn


@pytest.mark.skipif(not _has("_mnee_geometry_term"),
                    reason="_mnee_geometry_term not in this build")
def test_geometry_term_fixed_direction_matches_positional_limit():
    ps, ns, dpus, dpvs, etas, x0, far, sun, D, rn = _oblique_eq_chain()
    assert rn < 1e-8, f"oblique chain did not converge (residual {rn:.2e})"
    a = dict(ps=[list(p) for p in ps], ns=[list(n) for n in ns],
             dp_dus=[list(d) for d in dpus], dp_dvs=[list(d) for d in dpvs],
             etas=list(etas), x0=list(x0))
    dx_pos, _ = astroray._mnee_geometry_term(light=list(far), light_n=list(-sun),
                                             light_fixed_dir=False, **a)
    dx_fix, _ = astroray._mnee_geometry_term(light=list(far), light_n=list(-sun),
                                             light_fixed_dir=True, light_dir=list(sun), **a)
    # dx1 per solid angle == dx1 per area * D^2 in the distant-light limit.
    rel = abs(dx_fix - dx_pos * D * D) / max(dx_fix, 1e-30)
    assert dx_fix > 0.0
    assert rel < 5e-3, f"fixed-dir {dx_fix:.5e} vs positional*D^2 {dx_pos*D*D:.5e} (rel {rel:.2e})"


@pytest.mark.skipif(not (_has("_mnee_geometry_term") and _has("_mnee_chain_eval")),
                    reason="mnee helpers not in this build")
def test_det_dh_dx_matches_dense_jacobian():
    g = _forward_traced_chain()
    light_n = _norm(g["ps"][-1] - g["light"])
    _, dhdx = astroray._mnee_geometry_term(
        [list(p) for p in g["ps"]], [list(n) for n in g["ns"]],
        [list(d) for d in g["dpus"]], [list(d) for d in g["dpvs"]],
        list(g["etas"]), list(g["x0"]), list(g["light"]), list(light_n))
    z = [[0.0, 0.0, 0.0]] * len(g["ps"])
    ok, _, Jflat = astroray._mnee_chain_eval(
        [list(p) for p in g["ps"]], [list(n) for n in g["ns"]],
        [list(d) for d in g["dpus"]], [list(d) for d in g["dpvs"]],
        z, z, list(g["etas"]), list(g["x0"]), list(g["light"]), True)
    assert ok
    N = len(g["ps"])
    J = np.array(Jflat).reshape(2 * N, 2 * N)
    det_dense = abs(np.linalg.det(J))
    rel = abs(dhdx - det_dense) / max(det_dense, 1e-30)
    assert rel < 1e-3, f"dh_dx {dhdx:.6e} vs dense |det J| {det_dense:.6e} (rel {rel:.2e})"

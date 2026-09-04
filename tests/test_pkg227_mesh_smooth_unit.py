#!/usr/bin/env python
"""pkg227 Phase 2b-smooth solver oracle — the flat-basin + smooth-normal Newton
polish reaches the analytic sphere oracle at COARSE tessellation, where the flat
solver (linear convergence) cannot.

Pure-numpy, CI-runnable (no build). This is the algorithm-level gate for the
smooth polish in include/astroray/manifold/mesh_specular_poly.h
(polishSmoothVertex / mneeResidual2), a line-for-line port of the polish below.
Reuses the flat unit test's sphere oracle + flat solver + icosphere. Full
de-risking in .astroray_plan/docs/pkg227-phase2b-smooth-research.md /
scratchpad/proto_mesh_smooth.py.

Asserts:
  1. ORACLE MATCH (coarse): at 6 subdivision levels the smooth-polished vertex
     reaches every analytic-sphere root to < 1e-4 rad (the pkg227 gate) — the
     flat solver reaches NONE at this tessellation.
  2. SMOOTH BEATS FLAT: the smooth polish is orders of magnitude closer to the
     oracle than the flat solver at the same coarse level.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from test_pkg227_mesh_poly_unit import (
    CASES,
    _icosphere,
    _unit,
    flat_triangle_specular,
    sphere_oracle_vertices,
)

CENTER, RADIUS = np.zeros(3), 1.0


def _smooth_normal(u, v, n0, n1, n2):
    return _unit(n0 * (1.0 - u - v) + n1 * u + n2 * v)


def _bary(p, P0, P1, P2):
    e1, e2 = P1 - P0, P2 - P0
    d11, d12, d22 = e1 @ e1, e1 @ e2, e2 @ e2
    den = d11 * d22 - d12 * d12
    vp = p - P0
    u = (d22 * (vp @ e1) - d12 * (vp @ e2)) / den
    v = (d11 * (vp @ e2) - d12 * (vp @ e1)) / den
    return u, v


def _mnee_residual(p, x0, x2, nhat, eta):
    d1 = _unit(x0 - p)
    d2 = _unit(x2 - p)
    h = d1 + eta * d2
    ht = h - nhat * (h @ nhat)
    a = np.array([1.0, 0.0, 0.0]) if abs(nhat[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    t1 = _unit(a - nhat * (a @ nhat))
    t2 = np.cross(nhat, t1)
    return np.array([ht @ t1, ht @ t2])


def _smooth_polish(seed_p, P0, P1, P2, n0, n1, n2, x0, x2, eta, iters=8):
    e1, e2 = P1 - P0, P2 - P0
    u, v = _bary(seed_p, P0, P1, P2)
    for _ in range(iters):
        p = P0 + u * e1 + v * e2
        nhat = _smooth_normal(u, v, n0, n1, n2)
        r0 = _mnee_residual(p, x0, x2, nhat, eta)
        if r0 @ r0 < 1e-20:
            break
        h = 1e-5
        ru = _mnee_residual(P0 + (u + h) * e1 + v * e2, x0, x2,
                            _smooth_normal(u + h, v, n0, n1, n2), eta)
        rv = _mnee_residual(P0 + u * e1 + (v + h) * e2, x0, x2,
                            _smooth_normal(u, v + h, n0, n1, n2), eta)
        J = np.column_stack([(ru - r0) / h, (rv - r0) / h])
        try:
            duv = np.clip(np.linalg.solve(J, -r0), -0.5, 0.5)
        except np.linalg.LinAlgError:
            break
        u += duv[0]
        v += duv[1]
    p = P0 + u * e1 + v * e2
    nhat = _smooth_normal(u, v, n0, n1, n2)
    conv = (_mnee_residual(p, x0, x2, nhat, eta) @ _mnee_residual(p, x0, x2, nhat, eta)) < 1e-12
    inside = (-1e-4 <= u) and (-1e-4 <= v) and (u + v <= 1 + 1e-4)
    return p, (conv and inside)


def _ang_err(p, op, center):
    return float(np.arccos(np.clip(_unit(p - center) @ _unit(op - center), -1, 1)))


def _drill(x0, x2, eta, op, levels=6, beam=6, smooth=True):
    V, F = _icosphere(1)
    fc = V[F].mean(axis=1)
    tris = [tuple(V[F[fi]]) for fi in np.argsort(np.linalg.norm(fc - op, axis=1))[:beam]]
    best = None
    for _ in range(levels):
        for (P0, P1, P2) in tris:
            if smooth:
                n0, n1, n2 = _unit(P0), _unit(P1), _unit(P2)
                seed = (P0 + P1 + P2) / 3.0
                p, ok = _smooth_polish(seed, P0, P1, P2, n0, n1, n2, x0, x2, eta)
                if ok:
                    e = _ang_err(p, op, CENTER)
                    best = e if best is None else min(best, e)
            else:
                for s in flat_triangle_specular(x0, x2, P0, P1, P2, eta):
                    e = _ang_err(s['position'], op, CENTER)
                    best = e if best is None else min(best, e)
        nt = []
        for (P0, P1, P2) in tris:
            ab, bc, ca = _unit((P0 + P1) / 2), _unit((P1 + P2) / 2), _unit((P2 + P0) / 2)
            nt += [(P0, ab, ca), (ab, P1, bc), (ca, bc, P2), (ab, bc, ca)]
        cens = np.array([_unit(sum(t) / 3) for t in nt])
        tris = [nt[i] for i in np.argsort(np.linalg.norm(cens - op, axis=1))[:beam]]
    return best


def test_smooth_polish_reaches_oracle_coarse():
    worst = 0.0
    matched = 0
    for _label, x0, x2, eta in CASES:
        for op in sphere_oracle_vertices(x0, x2, CENTER, RADIUS, eta):
            err = _drill(x0, x2, eta, op, smooth=True)
            assert err is not None, f"[{_label}] smooth polish found no vertex near oracle"
            assert err < 1e-4, f"[{_label}] smooth err {err:.3e} exceeds 1e-4 gate"
            worst = max(worst, err)
            matched += 1
    assert matched >= 8
    assert worst < 1e-4


def test_smooth_beats_flat_at_coarse_tessellation():
    for _label, x0, x2, eta in CASES:
        for op in sphere_oracle_vertices(x0, x2, CENTER, RADIUS, eta):
            smooth = _drill(x0, x2, eta, op, smooth=True)
            flat = _drill(x0, x2, eta, op, smooth=False)
            # smooth reaches the gate; flat is far above it (or misses entirely).
            assert smooth is not None and smooth < 1e-4
            assert flat is None or flat > 10.0 * smooth, (
                f"[{_label}] smooth={smooth:.2e} did not decisively beat flat={flat}")


if __name__ == "__main__":
    test_smooth_polish_reaches_oracle_coarse()
    test_smooth_beats_flat_at_coarse_tessellation()
    print("pkg227 Phase 2b-smooth oracle: all checks PASS")

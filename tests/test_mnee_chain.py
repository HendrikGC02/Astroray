#!/usr/bin/env python
"""pkg106 Chunk C — multi-vertex specular manifold chain (block-tridiagonal).

A prism rainbow needs TWO refractive vertices (entry + exit face); the single-
vertex solver (Chunks A/B) can't represent it. This validates manifold_chain.h:
  1. The block-tridiagonal Jacobian (a=prev / b=current / c=next) matches a
     float64 finite-difference of the same residual (2-refraction chain).
  2. The damped block Newton converges to a forward-traced 2-refraction chain.

Ports Cycles mnee.h mnee_compute_constraint_derivatives lines 248-365. See
.astroray_plan/docs/pkg106-research-2026-05-28.md. CPU-only; runs on CI.
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


def _planar_partials(n):
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    du = _norm(a - np.dot(a, n) * n)
    return du, np.cross(n, du)


def _forward_traced_prism_chain():
    """Thin prism, near-normal incidence -> transmits (no TIR), small angles.
    Returns the SMS chain x0 -> v_exit(nB) -> v_entry(nA) -> light plus normals,
    partials, etas. (Matches the validated _mnee_chain_proto geometry.)"""
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
    assert d1 is not None
    tB = np.dot(pB - v_entry, nB) / np.dot(d1, nB)
    v_exit = v_entry + d1 * tB
    d2 = _refract(d1, nB, ng)
    assert d2 is not None
    x0 = v_exit + d2 * 2.0
    duB, dvB = _planar_partials(nB)
    duA, dvA = _planar_partials(nA)
    # chain order: x0 -> v1=v_exit(nB) -> v2=v_entry(nA) -> light
    return dict(
        ps=[v_exit, v_entry], ns=[nB, nA], dpus=[duB, duA], dpvs=[dvB, dvA],
        etas=[ng, ng], x0=x0, light=L,
    )


def _chain_residual_py(ps, ns, dpus, x0, light, etas, refraction=True):
    """float64 reference residual (the C++ one is float32 -> FD of it is noise)."""
    N = len(ps)
    out = []
    for i in range(N):
        prev = x0 if i == 0 else ps[i - 1]
        nxt = light if i == N - 1 else ps[i + 1]
        wi = _norm(prev - ps[i])
        wo = _norm(nxt - ps[i])
        e = etas[i] if refraction else 1.0
        if np.dot(wi, ns[i]) < 0:
            e = 1.0 / e
        h = wi + e * wo
        h = h / np.linalg.norm(h)
        s = dpus[i] - np.dot(dpus[i], ns[i]) * ns[i]
        s = s / np.linalg.norm(s)
        t = np.cross(ns[i], s)
        out += [np.dot(s, h), np.dot(t, h)]
    return np.array(out)


def _fd_jacobian_py(g, h=1e-6):
    ps, ns, dpus, dpvs = g["ps"], g["ns"], g["dpus"], g["dpvs"]
    N = len(ps)
    J = np.zeros((2 * N, 2 * N))
    for j in range(N):
        for k, dp in enumerate((dpus[j], dpvs[j])):
            pp = [p.copy() for p in ps]
            pm = [p.copy() for p in ps]
            pp[j] = ps[j] + dp * h
            pm[j] = ps[j] - dp * h
            cp = _chain_residual_py(pp, ns, dpus, g["x0"], g["light"], g["etas"])
            cm = _chain_residual_py(pm, ns, dpus, g["x0"], g["light"], g["etas"])
            J[:, 2 * j + k] = (cp - cm) / (2 * h)
    return J


def _call_eval(g):
    z = [[0.0, 0.0, 0.0]] * len(g["ps"])
    ok, residual, Jflat = astroray._mnee_chain_eval(
        [list(p) for p in g["ps"]], [list(n) for n in g["ns"]],
        [list(d) for d in g["dpus"]], [list(d) for d in g["dpvs"]],
        z, z, list(g["etas"]), list(g["x0"]), list(g["light"]), True,
    )
    N = len(g["ps"])
    return ok, np.array(residual), np.array(Jflat).reshape(2 * N, 2 * N)


@pytest.mark.skipif(not _has("_mnee_chain_eval"),
                    reason="_mnee_chain_eval not in this build")
def test_chain_residual_zero_at_forward_traced_solution():
    g = _forward_traced_prism_chain()
    ok, residual, _ = _call_eval(g)
    assert ok
    assert np.linalg.norm(residual) < 1e-4, f"residual {residual} should vanish"


@pytest.mark.skipif(not _has("_mnee_chain_eval"),
                    reason="_mnee_chain_eval not in this build")
def test_chain_jacobian_matches_fd():
    g = _forward_traced_prism_chain()
    ok, _, Jcpp = _call_eval(g)
    assert ok
    Jfd = _fd_jacobian_py(g)
    err = np.max(np.abs(Jcpp - Jfd))
    assert err < 1e-3, f"chain analytic vs FD Jacobian mismatch {err:.2e}\n{Jcpp}\n{Jfd}"
    # off-diagonal blocks must be non-zero (genuine multi-vertex coupling).
    assert np.max(np.abs(Jcpp[0:2, 2:4])) > 1e-3, "c-block (vertex coupling) is zero"
    assert np.max(np.abs(Jcpp[2:4, 0:2])) > 1e-3, "a-block (vertex coupling) is zero"


@pytest.mark.skipif(not _has("_mnee_chain_solve_flat"),
                    reason="_mnee_chain_solve_flat not in this build")
def test_chain_newton_converges():
    g = _forward_traced_prism_chain()
    true_ps = [p.copy() for p in g["ps"]]
    # Seed each vertex off the solution, on its plane.
    seeded = []
    for i, p in enumerate(g["ps"]):
        s = _norm(g["dpus"][i] - np.dot(g["dpus"][i], g["ns"][i]) * g["ns"][i])
        t = np.cross(g["ns"][i], s)
        seeded.append(p + s * (0.06 * (1 - 2 * (i % 2))) + t * 0.04)
    z = [[0.0, 0.0, 0.0]] * len(g["ps"])
    converged, iters, residual, finalP = astroray._mnee_chain_solve_flat(
        [list(p) for p in seeded], [list(n) for n in g["ns"]],
        [list(d) for d in g["dpus"]], [list(d) for d in g["dpvs"]],
        list(g["etas"]), list(g["x0"]), list(g["light"]), True, 30, 1e-5, 0.3,
    )
    assert converged, f"chain Newton did not converge (residual={residual:.2e})"
    assert iters <= 12
    final = np.array(finalP).reshape(len(g["ps"]), 3)
    for i in range(len(true_ps)):
        assert np.linalg.norm(final[i] - true_ps[i]) < 1e-2, (
            f"vertex {i} converged to {final[i]}, expected {true_ps[i]}"
        )

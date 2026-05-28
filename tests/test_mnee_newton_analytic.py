#!/usr/bin/env python
"""pkg106 Chunk B — surface (u,v) partials + analytic-Jacobian Newton.

Validates:
  1. trianglePartials / spherePartials (surface_partials.h) produce the correct
     position + unit-normal derivatives (dn perpendicular to n, |dn|=1/r sphere).
  2. solveAnalytic (newton_iterate.h) — the analytic-Jacobian manifold Newton —
     converges to the analytic Snell-law refraction on a tilted plane.

The analytic Jacobian (Chunk A) replaces newton_iterate.h's central-difference
Jacobian, which diverges on triangulated casters (a +/-h tangent step crosses a
facet edge into a neighbour with a different normal). See
.astroray_plan/docs/pkg106-research-2026-05-28.md.

Pure-CPU; runs on CI.
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


@pytest.mark.skipif(not _has("_mnee_triangle_partials"),
                    reason="_mnee_triangle_partials not in this build")
def test_triangle_partials():
    v0 = [0.0, 0.0, 0.0]
    v1 = [1.3, 0.2, 0.0]
    v2 = [0.1, 1.1, 0.4]
    dpu, dpv, dnu, dnv = astroray._mnee_triangle_partials(v0, v1, v2)
    assert np.allclose(dpu, [1.3, 0.2, 0.0])           # v1 - v0
    assert np.allclose(dpv, [0.1, 1.1, 0.4])           # v2 - v0
    assert np.allclose(dnu, [0.0, 0.0, 0.0])           # flat facet
    assert np.allclose(dnv, [0.0, 0.0, 0.0])


@pytest.mark.skipif(not _has("_mnee_sphere_partials"),
                    reason="_mnee_sphere_partials not in this build")
def test_sphere_partials():
    center = np.array([0.0, -0.4, 0.15])
    radius = 0.7
    n_dir = _norm(np.array([0.3, 0.8, 0.2]))
    p = center + n_dir * radius
    dpu, dpv, dnu, dnv = (np.array(a) for a in
                          astroray._mnee_sphere_partials(list(center), list(p), radius))
    n = (p - center) / radius
    # tangents perpendicular to n and unit length
    assert abs(np.dot(dpu, n)) < 1e-5
    assert abs(np.dot(dpv, n)) < 1e-5
    assert abs(np.linalg.norm(dpu) - 1.0) < 1e-5
    # unit-normal derivative: dn = dp / r, perpendicular to n
    assert np.allclose(dnu, dpu / radius, atol=1e-5)
    assert np.allclose(dnv, dpv / radius, atol=1e-5)
    assert abs(np.dot(dnu, n)) < 1e-5


def _tilted_plane_snell():
    eta = 1.0 / 1.5
    n1 = _norm(np.array([0.2, 1.0, 0.1]))
    a = np.array([1.0, 0.0, 0.0])
    dp_du = _norm(a - np.dot(a, n1) * n1) * 1.3
    dp_dv = np.cross(n1, dp_du) * 0.9
    s_dir = _norm(dp_du - np.dot(dp_du, n1) * n1)
    theta_i = np.deg2rad(35.0)
    wi = np.cos(theta_i) * n1 + np.sin(theta_i) * s_dir
    wo_t = -np.sin(theta_i) / eta
    wo = -np.sqrt(1 - wo_t ** 2) * n1 + wo_t * s_dir
    x1_star = np.zeros(3)
    x0 = x1_star + wi * 2.0
    x2 = x1_star + wo * 3.0
    return dict(eta=eta, n1=n1, dp_du=dp_du, dp_dv=dp_dv,
                x0=x0, x2=x2, x1_star=x1_star)


@pytest.mark.skipif(not _has("_mnee_newton_solve_flat"),
                    reason="_mnee_newton_solve_flat not in this build")
def test_analytic_newton_converges_to_snell():
    g = _tilted_plane_snell()
    # Seed off the manifold (on the plane), then solve.
    x1_init = g["x1_star"] + g["dp_du"] * 0.25 + g["dp_dv"] * (-0.18)
    converged, iters, residual, ux, uy, uz = astroray._mnee_newton_solve_flat(
        list(g["x0"]), list(g["x2"]), list(g["n1"]),
        list(g["dp_du"]), list(g["dp_dv"]), list(x1_init),
        float(g["eta"]), True, 20, 1e-5,
    )
    x1 = np.array([ux, uy, uz])
    assert converged, f"analytic Newton did not converge (residual={residual:.2e})"
    assert iters <= 10, f"too many iterations: {iters}"
    assert residual < 1e-5
    # Converged to the analytic Snell-law vertex.
    assert np.linalg.norm(x1 - g["x1_star"]) < 1e-3, (
        f"converged to {x1}, expected {g['x1_star']}"
    )


@pytest.mark.skipif(not _has("_mnee_newton_solve_flat"),
                    reason="_mnee_newton_solve_flat not in this build")
def test_analytic_newton_already_at_solution():
    """Seeded exactly at the solution -> converges in 1 iteration (residual ~0)."""
    g = _tilted_plane_snell()
    converged, iters, residual, ux, uy, uz = astroray._mnee_newton_solve_flat(
        list(g["x0"]), list(g["x2"]), list(g["n1"]),
        list(g["dp_du"]), list(g["dp_dv"]), list(g["x1_star"]),
        float(g["eta"]), True, 20, 1e-5,
    )
    assert converged and iters == 1 and residual < 1e-5

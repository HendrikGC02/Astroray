#!/usr/bin/env python
"""pkg106 Chunk A — analytic half-vector constraint Jacobian.

Validates astroray::manifold::halfVectorConstraintJacobian (the analytic
replacement for newton_iterate.h's central-difference Jacobian, which diverges
on triangulated casters). Two properties, per the Chunk A acceptance:

  1. The constraint residual is ~0 at the analytic Snell-law refraction.
  2. The analytic 2x2 Jacobian matches a central-difference Jacobian of the
     SAME C++ residual (flat plane AND a synthetic curved dn != 0 case, which
     exercises the tangent-frame ds/dt derivative terms).

Source: Cycles mnee.h mnee_compute_constraint_derivatives (Apache-2.0,
lines 285-356) + Hanika 2015 §5. See .astroray_plan/docs/pkg106-research-2026-05-28.md.

Pure-CPU; runs on CI (no GPU needed).
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


def _has_binding():
    return AVAILABLE and hasattr(astroray, "_mnee_half_vector_constraint")


def _norm(v):
    return v / np.linalg.norm(v)


def _constraint(x0, x1, x2, n1, dp_du, dp_dv, dn_du, dn_dv, eta, refraction=True):
    """Call the C++ helper; returns (residual(2,), J(2x2), valid)."""
    f = astroray._mnee_half_vector_constraint
    r0, r1, j00, j01, j10, j11, valid = f(
        list(map(float, x0)), list(map(float, x1)), list(map(float, x2)),
        list(map(float, n1)), list(map(float, dp_du)), list(map(float, dp_dv)),
        list(map(float, dn_du)), list(map(float, dn_dv)), float(eta), bool(refraction),
    )
    return np.array([r0, r1]), np.array([[j00, j01], [j10, j11]]), valid


def _py_residual(x0, x1, x2, n1, dp_du, eta):
    """Pure-Python (float64) reference for the C++ constraint residual.

    The C++ helper stores Vec3 in float32, so finite-differencing ITS residual
    suffers catastrophic cancellation (~1e-2 noise) — useless as a Jacobian
    reference. We reproduce the same residual in float64 here and finite-
    difference that instead. (Equivalence of this residual to the C++ one is
    asserted separately in test_residual_helper_matches_cpp.)
    """
    wi = _norm(x0 - x1)
    wo = _norm(x2 - x1)
    h = wi + eta * wo
    h = h / np.linalg.norm(h)
    s = dp_du - np.dot(dp_du, n1) * n1
    s = s / np.linalg.norm(s)
    t = np.cross(n1, s)
    return np.array([np.dot(s, h), np.dot(t, h)])


def _fd_jacobian(x0, x1, x2, n1, dp_du, dp_dv, dn_du, dn_dv, eta, hstep=1e-6):
    """Central-difference Jacobian of the float64 reference residual. Moving x1
    by dp*h and n1 by dn*h (renormalized) mirrors a manifold (u,v) step."""
    cols = []
    for dp, dn in ((dp_du, dn_du), (dp_dv, dn_dv)):
        rp = _py_residual(x0, x1 + dp * hstep, x2, _norm(n1 + dn * hstep), dp_du, eta)
        rm = _py_residual(x0, x1 - dp * hstep, x2, _norm(n1 - dn * hstep), dp_du, eta)
        cols.append((rp - rm) / (2 * hstep))
    return np.column_stack(cols)


def _tilted_plane_snell():
    """Return a flat tilted-plane geometry with a Snell-satisfying (x0,x1,x2)."""
    eta = 1.0 / 1.5  # relative IOR n_out/n_in (air -> glass)
    n1 = _norm(np.array([0.2, 1.0, 0.1]))
    a = np.array([1.0, 0.0, 0.0])
    dp_du = _norm(a - np.dot(a, n1) * n1) * 1.3
    dp_dv = np.cross(n1, dp_du) * 0.9
    dn_du = np.zeros(3)
    dn_dv = np.zeros(3)
    x1 = np.zeros(3)
    # Build wi, wo with h = wi + eta*wo parallel to n1 (Snell in half-vector form).
    s_dir = _norm(dp_du - np.dot(dp_du, n1) * n1)
    theta_i = np.deg2rad(35.0)
    wi = np.cos(theta_i) * n1 + np.sin(theta_i) * s_dir      # toward x0 (above)
    wo_t = -np.sin(theta_i) / eta
    assert abs(wo_t) < 1.0, "total internal reflection — choose a smaller angle"
    wo = -np.sqrt(1 - wo_t ** 2) * n1 + wo_t * s_dir         # toward x2 (below)
    x0 = x1 + wi * 2.0
    x2 = x1 + wo * 3.0
    return dict(x0=x0, x1=x1, x2=x2, n1=n1, dp_du=dp_du, dp_dv=dp_dv,
               dn_du=dn_du, dn_dv=dn_dv, eta=eta)


@pytest.mark.skipif(not _has_binding(),
                    reason="_mnee_half_vector_constraint not in this build")
def test_residual_zero_at_snell_solution():
    g = _tilted_plane_snell()
    r, _, valid = _constraint(**g)
    assert valid
    assert np.linalg.norm(r) < 1e-5, (
        f"half-vector residual should vanish at the Snell solution, got {r}"
    )


@pytest.mark.skipif(not _has_binding(),
                    reason="_mnee_half_vector_constraint not in this build")
def test_analytic_jacobian_matches_fd_flat():
    g = _tilted_plane_snell()
    # Check on-manifold AND off-manifold (the Jacobian must be correct everywhere).
    for offset in (np.zeros(3), g["dp_du"] * 0.15 + g["dp_dv"] * 0.10):
        gg = dict(g)
        gg["x1"] = g["x1"] + offset
        _, J, valid = _constraint(**gg)
        assert valid
        Jfd = _fd_jacobian(**gg)
        err = np.max(np.abs(J - Jfd))
        assert err < 1e-3, f"flat analytic vs FD Jacobian mismatch {err:.2e}\n{J}\n{Jfd}"


@pytest.mark.skipif(not _has_binding(),
                    reason="_mnee_half_vector_constraint not in this build")
def test_analytic_jacobian_matches_fd_curved():
    """Synthetic curvature (dn != 0, perpendicular to n) exercises the ds/dt terms."""
    eta = 1.0 / 1.5
    n1 = _norm(np.array([0.1, 1.0, -0.2]))
    a = np.array([1.0, 0.0, 0.0])
    dp_du = _norm(a - np.dot(a, n1) * n1) * 1.1
    dp_dv = np.cross(n1, dp_du) * 0.8
    dn_du = np.array([0.15, -0.05, 0.10])
    dn_dv = np.array([-0.08, 0.04, 0.12])
    dn_du = dn_du - np.dot(dn_du, n1) * n1   # valid unit-normal derivative (perp to n)
    dn_dv = dn_dv - np.dot(dn_dv, n1) * n1
    x1 = np.zeros(3)
    x0 = x1 + _norm(np.array([0.3, 1.0, 0.1])) * 2.0
    x2 = x1 + _norm(np.array([0.1, -1.0, -0.2])) * 2.5
    g = dict(x0=x0, x1=x1, x2=x2, n1=n1, dp_du=dp_du, dp_dv=dp_dv,
             dn_du=dn_du, dn_dv=dn_dv, eta=eta)
    _, J, valid = _constraint(**g)
    assert valid
    Jfd = _fd_jacobian(**g, hstep=1e-5)
    err = np.max(np.abs(J - Jfd))
    assert err < 1e-3, f"curved analytic vs FD Jacobian mismatch {err:.2e}\n{J}\n{Jfd}"


@pytest.mark.skipif(not _has_binding(),
                    reason="_mnee_half_vector_constraint not in this build")
def test_residual_helper_matches_cpp():
    """The float64 reference residual equals the C++ (float32) residual to float
    precision — justifying its use as the finite-difference reference above."""
    g = _tilted_plane_snell()
    g["x1"] = g["x1"] + g["dp_du"] * 0.2 + g["dp_dv"] * 0.13  # off-manifold
    r_cpp, _, valid = _constraint(**g)
    assert valid
    r_py = _py_residual(g["x0"], g["x1"], g["x2"], g["n1"], g["dp_du"], g["eta"])
    assert np.max(np.abs(r_cpp - r_py)) < 1e-5, (
        f"C++ residual {r_cpp} != float64 reference {r_py}"
    )


@pytest.mark.skipif(not _has_binding(),
                    reason="_mnee_half_vector_constraint not in this build")
def test_degenerate_inputs_return_invalid():
    # Coincident x0 == x1 -> zero-length wi -> invalid (no crash).
    g = _tilted_plane_snell()
    _, _, valid = _constraint(x0=g["x1"], x1=g["x1"], x2=g["x2"], n1=g["n1"],
                              dp_du=g["dp_du"], dp_dv=g["dp_dv"],
                              dn_du=g["dn_du"], dn_dv=g["dn_dv"], eta=g["eta"])
    assert valid is False

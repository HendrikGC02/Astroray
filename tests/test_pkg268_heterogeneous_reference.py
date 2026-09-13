"""pkg268 — delta/ratio tracking over a heterogeneous GridMedium vs a numpy
brute-force ray-march reference (tests/volume_reference.py).

Identity transforms (index space == world space). The engine estimators
(``volume_transmittance_estimate`` = ratio tracking; ``volume_single_scatter_
estimate`` = equiangular+distance-MIS single scatter) must converge to the
independent ray-march oracle within tolerance.
"""

from __future__ import annotations

import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

import astroray
import volume_reference as ref

IDENTITY = [1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0]

N = 16


def _analytic_field(seed=3):
    """Smooth, strictly-positive density on an N^3 grid (nz,ny,nx)."""
    zz, yy, xx = np.meshgrid(np.arange(N), np.arange(N), np.arange(N), indexing="ij")
    c = (N - 1) / 2.0
    r2 = ((xx - c) ** 2 + (yy - c) ** 2 + (zz - c) ** 2) / (N * N)
    dens = (0.4 + 1.6 * np.exp(-4.0 * r2)).astype(np.float32)  # peak center, ~0.4 edges
    return np.ascontiguousarray(dens)


def _grid(dens):
    gm = astroray.GridMedium()
    gm.set_density(dens, bbox_min=(0, 0, 0),
                   index_to_object=IDENTITY, object_to_world=IDENTITY, supervoxel=8)
    return gm


def _aabb_overlap(o, d, mn, mx):
    return ref._aabb_overlap(np.asarray(o, float), np.asarray(d, float), mn, mx, 1e-4, 1e9)


def test_ratio_tracking_transmittance_matches_raymarch():
    dens = _analytic_field()
    gm = _grid(dens)
    extinction = 0.5
    mn, mx = [0.0, 0.0, 0.0], [float(N)] * 3
    cases = [((8.0, 8.0, -5.0), (0.0, 0.0, 1.0)),
             ((-5.0, 8.0, 8.0), (1.0, 0.0, 0.0)),
             ((-5.0, -5.0, -5.0), (1.0, 1.0, 1.0))]
    for o, d in cases:
        dn = np.asarray(d, float); dn = dn / np.linalg.norm(dn)
        ov = _aabb_overlap(o, dn, mn, mx)
        assert ov is not None
        t0, t1 = ov
        expected = ref.transmittance_raymarch(dens, (0, 0, 0), extinction, o, dn,
                                               t0, t1, n_steps=6000)
        got = astroray.volume_transmittance_estimate(
            gm, list(o), list(dn), extinction, 40000, 2024)
        print(f"[pkg268 hetero Tr] o={o} d={tuple(dn.round(3))}: "
              f"engine={got:.4f} raymarch={expected:.4f}")
        assert abs(got - expected) < 0.02 + 0.05 * expected, (
            f"ratio-tracking Tr {got:.4f} != raymarch {expected:.4f}")


def test_single_scatter_matches_raymarch():
    dens = _analytic_field()
    gm = _grid(dens)
    extinction = 0.4
    albedo = [0.9, 0.5, 0.2]
    g = 0.0
    light_pos = [8.0, 30.0, 8.0]
    light_rgb = [200.0, 200.0, 200.0]
    o = [8.0, 8.0, -6.0]
    d = [0.0, 0.0, 1.0]
    mn, mx = [0.0, 0.0, 0.0], [float(N)] * 3

    expected = ref.single_scatter_raymarch(dens, (0, 0, 0), extinction, albedo, g,
                                           o, d, mn, mx, np.asarray(light_pos),
                                           np.asarray(light_rgb), n_steps=2500)
    got = np.array(astroray.volume_single_scatter_estimate(
        gm, o, d, extinction, albedo, g, light_pos, light_rgb, 120000, 7))
    print(f"[pkg268 single-scatter] engine={got.round(4)} raymarch={expected.round(4)}")
    for c in range(3):
        denom = max(expected[c], 1e-4)
        assert abs(got[c] - expected[c]) / denom < 0.12, (
            f"channel {c}: engine {got[c]:.5f} vs raymarch {expected[c]:.5f}")
    # colour ordering preserved (red > green > blue albedo).
    assert got[0] > got[1] > got[2], f"albedo colour ordering lost: {got}"

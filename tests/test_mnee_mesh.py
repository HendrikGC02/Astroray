#!/usr/bin/env python
"""pkg106 Chunk D (part 1) — mesh seed-ray + chain solve on a triangulated caster.

Validates manifold/mesh_caustic.h: casting x0 -> light through a triangulated
two-face prism collects the ordered caster intersections (exit face, then entry
face) as a 2-vertex seed chain, and the damped block Newton walks them onto the
specular manifold (residual -> 0). Mirrors Cycles mnee.h seed-ray construction
(lines 29-44). CPU-only; runs on CI.
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


def _big_face_triangle(point, normal, extent=3.0):
    """A large triangle lying on the plane(point, normal); winding gives +normal."""
    n = _norm(normal)
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    s = _norm(a - np.dot(a, n) * n)
    t = np.cross(n, s)
    v0 = point + s * (-extent) + t * (-extent)
    v1 = point + s * (2 * extent)
    v2 = point + t * (2 * extent)
    return [*v0, *v1, *v2]


def _prism_scene():
    """Thin two-face prism between receiver x0 and light L (matches the validated
    chain geometry). Returns (tris, x0, light, ior)."""
    ior = 1.5
    nA = _norm(np.array([-1.0, 0.12, 0.0]))   # entry face (toward light)
    nB = _norm(np.array([1.0, 0.12, 0.0]))    # exit face (toward receiver)
    pA = np.array([-0.5, 0.0, 0.0])
    pB = np.array([0.5, 0.0, 0.0])
    x0 = np.array([2.4435, -0.5022, 0.0])     # receiver-side point
    L = np.array([-3.0, 0.4, 0.0])            # light
    tris = [_big_face_triangle(pB, nB), _big_face_triangle(pA, nA)]
    return tris, x0, L, ior


@pytest.mark.skipif(not _has("_mnee_mesh_solve"),
                    reason="_mnee_mesh_solve not in this build")
def test_seed_ray_finds_two_faces_and_converges():
    tris, x0, L, ior = _prism_scene()
    N, converged, iters, residual, finalP = astroray._mnee_mesh_solve(
        [list(map(float, t)) for t in tris], list(x0), list(L), float(ior),
        40, 1e-5, 0.25,
    )
    assert N == 2, f"seed ray should cross both prism faces, got {N} vertices"
    assert converged, f"mesh chain Newton did not converge (residual={residual:.2e})"
    assert residual < 1e-5
    final = np.array(finalP).reshape(N, 3)
    # Converged vertices lie near the two face planes (x ~ +0.5 exit, -0.5 entry).
    assert final[0][0] > 0.0 > final[1][0], (
        f"vertices not on the expected faces: {final}"
    )


@pytest.mark.skipif(not _has("_mnee_mesh_solve"),
                    reason="_mnee_mesh_solve not in this build")
def test_seed_ray_misses_returns_zero():
    """A light segment that doesn't cross either face plane yields no seed chain."""
    tris, _, _, ior = _prism_scene()
    # Both points on the +x side of both faces (x > 0.5), so the segment never
    # crosses the exit (x~0.5) or entry (x~-0.5) face plane.
    x0 = np.array([3.0, 0.0, 0.0])
    L = np.array([1.7, 0.0, 0.0])
    N, converged, _, _, _ = astroray._mnee_mesh_solve(
        [list(map(float, t)) for t in tris], list(x0), list(L), float(ior),
        40, 1e-5, 0.25,
    )
    assert N == 0 and not converged

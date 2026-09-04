#!/usr/bin/env python
"""pkg227 Phase 2b-smooth render gate — interpolated shading normals bring the
tessellated-mesh caustic into structural agreement with the ANALYTIC sphere
caustic, where the flat-facet mesh is faceted and structurally wrong.

Three seed-pinned renders (camera-side SMS poly, spectral_newton=1,
sms_specular_poly=1), same glass/light/camera:
  A) analytic sphere primitive (add_sphere)          -> runSMSAttemptPoly (oracle)
  F) FLAT tessellated glass icosphere (no normals)   -> runMeshSMSAttemptPoly flat
  S) SMOOTH icosphere (per-vertex sphere normals)    -> flat basin + smooth polish

The caustic on the floor is compared to the analytic reference by normalized
cross-correlation (NCC) over the floor ROI. Smooth shading recovers the smooth-
sphere caustic (high NCC); the flat facets scatter it into a triangular pattern
(low NCC). Self-contained (procedural icosphere, no external asset). The solver
math is proven separately at < 1e-4 rad vs the sphere oracle (see
scratchpad/proto_mesh_smooth.py / pkg227-phase2b-smooth-research.md).

Measured (subdiv 2, 256 spp, seed 17): NCC(smooth) ~0.86, NCC(flat) ~0.40.
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
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

WIDTH, HEIGHT, SAMPLES, MAX_DEPTH, SEED = 320, 220, 256, 10, 17
CENTER = np.array([0.0, -0.35, 0.15])
RADIUS = 0.72
SUBDIV = 2


def _unit(v):
    return v / np.linalg.norm(v)


def _icosphere(subdiv):
    t = (1.0 + np.sqrt(5.0)) / 2.0
    verts = [_unit(v) for v in np.array([
        [-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t],
        [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]], float)]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9),
             (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2),
             (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10),
             (8, 6, 7), (9, 8, 1)]
    cache = {}

    def mid(i, j):
        key = (min(i, j), max(i, j))
        if key not in cache:
            verts.append(_unit((verts[i] + verts[j]) * 0.5))
            cache[key] = len(verts) - 1
        return cache[key]

    for _ in range(subdiv):
        nf = []
        for a, b, c in faces:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)]
        faces = nf
    return np.array(verts), np.array(faces, int)


def _base(r):
    r.set_background_color([0.02, 0.025, 0.03])
    floor = r.create_material("lambertian", [0.72, 0.72, 0.68], {})
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, -2.2], [2.4, -1.2, 1.6], floor)
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, 1.6], [-2.4, -1.2, 1.6], floor)
    light = r.create_material("light", [1.0, 0.97, 0.90], {"intensity": 12.0})
    r.add_sphere([0.0, 1.55, 1.0], 0.22, light)
    return r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.52})


def _cam_int(r):
    r.set_integrator("sms_caustic_path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("caustic_chain_iters", 3)
    r.set_integrator_param("spectral_newton", 1)
    r.set_integrator_param("sms_specular_poly", 1)
    r.setup_camera([0.0, 1.2, 3.4], [0.0, -0.8, 0.0], [0.0, 1.0, 0.0],
                   38.0, WIDTH / HEIGHT, 0.0, 3.6, WIDTH, HEIGHT)


def _scene_analytic():
    r = astroray.Renderer()
    glass = _base(r)
    r.add_sphere([float(x) for x in CENTER], RADIUS, glass)
    _cam_int(r)
    return r


def _scene_mesh(smooth: bool):
    r = astroray.Renderer()
    glass = _base(r)
    V, F = _icosphere(SUBDIV)
    Vw = V * RADIUS + CENTER
    for (i0, i1, i2) in F:
        idx = r.scene_object_count()
        if smooth:
            r.add_triangle([float(x) for x in Vw[i0]], [float(x) for x in Vw[i1]],
                           [float(x) for x in Vw[i2]], glass, [], [], [],
                           [float(x) for x in V[i0]], [float(x) for x in V[i1]],
                           [float(x) for x in V[i2]])   # outward sphere normals
        else:
            r.add_triangle([float(x) for x in Vw[i0]], [float(x) for x in Vw[i1]],
                           [float(x) for x in Vw[i2]], glass)
        r.set_object_caustic_caster(idx, True)
    _cam_int(r)
    return r


def _render(r):
    r.set_seed(SEED)
    pix = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float32)
    if pix.ndim == 1:
        pix = pix.reshape(HEIGHT, WIDTH, 3)
    return pix, r.get_integrator_stats()


def _lum(a):
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def _ncc(x, y):
    x = x - x.mean()
    y = y - y.mean()
    d = np.sqrt((x * x).sum() * (y * y).sum())
    return float((x * y).sum() / d) if d > 1e-12 else 0.0


@pytest.fixture(scope="module")
def _tri():
    a, _sa = _render(_scene_analytic())
    f, _sf = _render(_scene_mesh(False))
    s, s_s = _render(_scene_mesh(True))
    roi = (slice(int(HEIGHT * 0.55), HEIGHT), slice(0, WIDTH))
    la, lf, ls_ = _lum(a)[roi], _lum(f)[roi], _lum(s)[roi]
    return {
        "ncc_flat": _ncc(lf, la),
        "ncc_smooth": _ncc(ls_, la),
        "e_smooth": s_s.get("sms_energy", 0),
        "conv_smooth": s_s.get("sms_converged", 0),
    }


def test_smooth_fires(_tri):
    assert _tri["conv_smooth"] > 1000, f"smooth path barely fired ({_tri['conv_smooth']})"
    assert _tri["e_smooth"] > 3.0, f"smooth caustic energy too low ({_tri['e_smooth']:.3f})"


def test_smooth_matches_analytic(_tri):
    # The smooth mesh caustic structurally matches the analytic sphere caustic.
    assert _tri["ncc_smooth"] > 0.65, (
        f"smooth caustic not aligned with analytic (NCC {_tri['ncc_smooth']:.3f})")


def test_smooth_beats_flat(_tri):
    # Interpolated normals decisively out-correlate the faceted flat caustic.
    assert _tri["ncc_smooth"] > _tri["ncc_flat"] + 0.15, (
        f"smooth NCC {_tri['ncc_smooth']:.3f} not decisively above flat "
        f"NCC {_tri['ncc_flat']:.3f}")


def test_flat_is_faceted(_tri):
    # Guard: the flat baseline really is structurally worse (a faceted caustic),
    # so the smooth win is meaningful, not a trivially-passing comparison.
    assert _tri["ncc_flat"] < 0.6, (
        f"flat caustic unexpectedly well-aligned (NCC {_tri['ncc_flat']:.3f}) — "
        f"the smooth/flat contrast is the whole point of 2b-smooth")


if __name__ == "__main__":
    import time
    t0 = time.time()
    a, _ = _render(_scene_analytic())
    f, _ = _render(_scene_mesh(False))
    s, _ = _render(_scene_mesh(True))
    roi = (slice(int(HEIGHT * 0.55), HEIGHT), slice(0, WIDTH))
    la, lf, ls_ = _lum(a)[roi], _lum(f)[roi], _lum(s)[roi]
    print(f"[{time.time()-t0:.1f}s] NCC flat={_ncc(lf, la):.4f} smooth={_ncc(ls_, la):.4f}")

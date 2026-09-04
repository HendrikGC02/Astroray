#!/usr/bin/env python
"""pkg227 Phase 2b-flat render gate — the deterministic flat-triangle
specular-polynomial solver produces a real caustic from a triangle-MESH caster,
where the single-seed Newton mesh path nearly fails.

Camera-side SMS on a triangle mesh: a tessellated glass icosphere (each facet
flagged a caustic caster) on the sms_caustic_path_tracer, spectral_newton=1 (the
hero-wavelength mesh path). Compares sms_specular_poly OFF (the existing
single-seed Newton mesh solver, runMeshSMSAttempt) vs ON (the pkg227 2b-flat
deterministic enumeration, runMeshSMSAttemptPoly / mesh_specular_poly.h).

Self-contained (a procedural icosphere via add_triangle — no external .obj, so no
dependence on the gitignored samples/Glass.obj the forward glass-mesh-caustic
showcase needs) and seed-pinned. The solver-level exactness is gated separately
by tests/test_pkg227_mesh_poly_unit.py (< 1e-4 rad vs the analytic sphere
oracle); this gate proves the C++ engine integration end-to-end.

Asserts (measured subdiv=1, 128 spp, seed 17):
  1. FIRES: the poly path enumerates valid single-vertex mesh caustics.
  2. BEATS NEWTON: the poly caustic carries far more energy than the single-seed
     Newton path, whose Newton-from-one-seed misses almost every mesh vertex
     (measured Newton E ~0.1 vs poly E ~12).
  3. DETERMINISTIC: nearly every enumerated poly solution is valid (converged/
     attempts ~1.0), vs Newton's ~0.1% seed-convergence rate — the deterministic-
     enumeration-vs-stochastic-seed signature.
  4. CONCENTRATED: the poly caustic energy clusters in a band (a real caustic),
     not uniform scatter.
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

WIDTH, HEIGHT, SAMPLES, MAX_DEPTH, SEED = 256, 180, 128, 10, 17
CENTER = np.array([0.0, -0.35, 0.15])
RADIUS = 0.72


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


def _scene(poly: int):
    r = astroray.Renderer()
    r.set_background_color([0.02, 0.025, 0.03])
    floor = r.create_material("lambertian", [0.72, 0.72, 0.68], {})
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, -2.2], [2.4, -1.2, 1.6], floor)
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, 1.6], [-2.4, -1.2, 1.6], floor)
    light = r.create_material("light", [1.0, 0.97, 0.90], {"intensity": 12.0})
    r.add_sphere([0.0, 1.55, 1.0], 0.22, light)
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.52})
    V, F = _icosphere(1)
    V = V * RADIUS + CENTER
    for (i0, i1, i2) in F:
        idx = r.scene_object_count()
        r.add_triangle([float(x) for x in V[i0]], [float(x) for x in V[i1]],
                       [float(x) for x in V[i2]], glass)
        r.set_object_caustic_caster(idx, True)
    r.set_integrator("sms_caustic_path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("caustic_chain_iters", 3)
    r.set_integrator_param("spectral_newton", 1)   # hero-wavelength mesh path
    r.set_integrator_param("sms_specular_poly", poly)
    r.setup_camera([0.0, 1.2, 3.4], [0.0, -0.8, 0.0], [0.0, 1.0, 0.0],
                   38.0, WIDTH / HEIGHT, 0.0, 3.6, WIDTH, HEIGHT)
    return r


def _render(poly: int):
    r = _scene(poly)
    r.set_seed(SEED)
    pix = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float32)
    if pix.ndim == 1:
        pix = pix.reshape(HEIGHT, WIDTH, 3)
    return pix, r.get_integrator_stats()


@pytest.fixture(scope="module")
def _caustic():
    off, s_off = _render(0)   # Newton mesh path
    on, s_on = _render(1)     # pkg227 2b-flat deterministic poly path
    diff = np.clip(on - off, 0.0, None)
    return off, on, diff, s_off, s_on


def test_poly_fires(_caustic):
    _, _, _, _, s_on = _caustic
    assert s_on.get("sms_converged", 0) > 100, (
        f"poly path enumerated no valid mesh caustics (nValid={s_on.get('sms_converged',0)})")
    assert s_on.get("sms_energy", 0) > 3.0, (
        f"poly caustic energy too low ({s_on.get('sms_energy',0):.3f})")


def test_poly_beats_newton(_caustic):
    _, _, _, s_off, s_on = _caustic
    e_off = s_off.get("sms_energy", 0)
    e_on = s_on.get("sms_energy", 0)
    # Newton-from-one-seed misses almost every mesh vertex; the deterministic
    # enumeration recovers the caustic (measured ~0.1 vs ~12).
    assert e_on > 5.0 * max(e_off, 1e-3), (
        f"poly ({e_on:.3f}) did not decisively beat Newton ({e_off:.3f})")


def test_poly_is_deterministic(_caustic):
    _, _, _, s_off, s_on = _caustic
    att_on = s_on.get("sms_attempts", 0)
    conv_on = s_on.get("sms_converged", 0)
    att_off = s_off.get("sms_attempts", 0)
    conv_off = s_off.get("sms_converged", 0)
    rate_on = conv_on / max(att_on, 1.0)
    rate_off = conv_off / max(att_off, 1.0)
    # Every enumerated poly solution is valid by construction (rate ~1); the
    # stochastic Newton seed converges on well under 1% of attempts.
    assert rate_on > 0.5, f"poly convergence rate unexpectedly low ({rate_on:.3f})"
    assert rate_on > 20.0 * rate_off, (
        f"poly rate {rate_on:.3f} not >> Newton rate {rate_off:.5f}")


def test_poly_caustic_is_concentrated(_caustic):
    _, _, diff, _, _ = _caustic
    dl = diff.max(axis=2)
    rowE = dl.sum(axis=1)
    conc = float(np.sort(rowE)[-16:].sum() / max(rowE.sum(), 1e-9))
    # A caustic concentrates its energy in a band; uniform scatter would be ~16/H.
    assert conc > 0.3, f"poly caustic energy not banded (top-16-rows fraction {conc:.3f})"


if __name__ == "__main__":
    off, s_off = _render(0)
    on, s_on = _render(1)
    print(f"Newton: att={s_off.get('sms_attempts',0):.0f} conv={s_off.get('sms_converged',0):.0f} "
          f"E={s_off.get('sms_energy',0):.3f}")
    print(f"Poly:   att={s_on.get('sms_attempts',0):.0f} conv={s_on.get('sms_converged',0):.0f} "
          f"E={s_on.get('sms_energy',0):.3f}")

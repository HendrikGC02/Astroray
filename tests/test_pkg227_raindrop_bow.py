#!/usr/bin/env python
"""pkg227 Phase 2a render-level gate — the raindrop rainbow chain adds chromatic
caustic energy in the physically-correct band.

A single-drop primary bow rendered via camera-side SMS is intrinsically a faint,
noisy caustic (this is why the prism showcase uses a forward light-tracer, not
SMS). So this gate does NOT demand a clean arc image; it asserts the physics that
Phase 2a delivers, deterministically (seed-pinned), by comparing the DEFAULT
integrator with the internal-reflection chain OFF vs ON:

  1. FIRES: chain ON adds SMS energy the single-vertex lens caustic lacked.
  2. CONCENTRATED: the added energy clusters in a horizontal band (the 42-deg
     caustic), not uniformly — a real caustic, not scatter.
  3. CHROMATIC: the added energy carries dispersion — both red-dominant and
     blue-dominant pixels appear (red->violet bow), the rainbow signature.

Geometry is physically honest: a collimated (soft/hazy 7-deg) sun elevated behind
the camera, a dispersive water drop, a diffuse floor; the bow's lower edge lands
on the floor. No brightening tricks. See scratchpad/proto_sphere_chain.py and
tests/test_pkg227_sphere_chain_unit.py for the solver-level oracle.
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

WIDTH, HEIGHT, SAMPLES, MAX_DEPTH, SEED = 240, 200, 320, 8, 17
SUN_DIR = [0.0, -0.35, -1.0]     # elevated sun behind camera (~19 deg)
DROP_C, DROP_R = [0.0, 0.9, 0.0], 0.6


def _scene(reflections: int):
    r = astroray.Renderer()
    r.set_background_color([0.12, 0.16, 0.24])
    r.set_use_refractive_caustics(True)
    floor = r.create_material("lambertian", [0.55, 0.55, 0.5], {})
    r.add_triangle([-12, -1.0, -14], [12, -1.0, -14], [12, -1.0, 6], floor)
    r.add_triangle([-12, -1.0, -14], [12, -1.0, 6], [-12, -1.0, 6], floor)
    d = np.array(SUN_DIR, float); d /= np.linalg.norm(d)
    r.add_sun_light_dedicated([float(d[0]), float(d[1]), float(d[2])],
                              float(np.radians(7.0)),
                              {"mode": "rgb", "color": [1.0, 0.98, 0.95]}, 6.0)
    water = r.create_material("dielectric", [1, 1, 1], {"sellmeier_preset": "water"})
    idx = r.scene_object_count()
    r.add_sphere(DROP_C, DROP_R, water)
    r.set_object_caustic_caster(idx, True)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("sms_specular_poly", 1)
    r.set_integrator_param("sphere_chain_reflections", reflections)
    r.setup_camera([0.0, 4.0, 11.0], [0.0, -1.0, 4.0], [0, 1, 0],
                   55.0, WIDTH / HEIGHT, 0.0, 11.0, WIDTH, HEIGHT)
    return r


def _render(reflections: int):
    r = _scene(reflections)
    r.set_seed(SEED)
    pix = np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float32)
    if pix.ndim == 1:
        pix = pix.reshape(HEIGHT, WIDTH, 3)
    return pix, r.get_integrator_stats()


@pytest.fixture(scope="module")
def _bow():
    off, s_off = _render(0)
    on, s_on = _render(1)
    diff = np.clip(on - off, 0.0, None)
    return off, on, diff, s_off, s_on


def test_chain_fires(_bow):
    _, _, _, s_off, s_on = _bow
    assert s_on.get("sms_energy", 0) > s_off.get("sms_energy", 0) + 1.0, (
        f"chain added no energy: off={s_off.get('sms_energy',0):.3f} "
        f"on={s_on.get('sms_energy',0):.3f}")


def test_added_energy_is_concentrated(_bow):
    _, _, diff, _, _ = _bow
    dl = diff.max(axis=2)
    rowE = dl.sum(axis=1)
    conc = float(np.sort(rowE)[-16:].sum() / max(rowE.sum(), 1e-9))
    # A caustic concentrates its energy in a band; uniform scatter would be ~16/H.
    assert conc > 0.25, f"chain energy not banded (top-16-rows fraction {conc:.3f})"


def test_added_energy_is_chromatic(_bow):
    _, _, diff, _, _ = _bow
    dl = diff.max(axis=2)
    thr = max(0.02, float(np.percentile(dl[dl > 0], 90)) if (dl > 0).any() else 1.0)
    mask = dl >= thr
    px = diff[mask]
    assert px.shape[0] >= 20, f"too few bright chain pixels ({px.shape[0]})"
    red_dom = np.count_nonzero(px[:, 0] > px[:, 2] * 1.15)
    blue_dom = np.count_nonzero(px[:, 2] > px[:, 0] * 1.15)
    # Dispersion: the bow carries BOTH red-leaning and blue-leaning pixels.
    assert red_dom >= 3 and blue_dom >= 3, (
        f"no chromatic spread: red_dom={red_dom} blue_dom={blue_dom} of {px.shape[0]}")

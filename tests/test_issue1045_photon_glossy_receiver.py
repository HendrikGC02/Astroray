#!/usr/bin/env python
"""#1045: the photon-map caustic gather evaluated every receiver as Lambertian
(albedo/pi * E), so a caustic landing on rough metal was too bright and had no
view dependence. The gather now evaluates the receiver BSDF per photon
(Jensen 2001 Eq. 8: L_r = sum_p f_r(x, w_p, w_o) dPhi_p / (pi r^2)).

Gate (same technique as test_959_caustic_photon_split): photons ON must equal
brute-force path tracing (photons OFF) on the arbitration prism's caustic beams,
now with a rough-metal floor; the Lambertian floor is the unchanged control.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "benchmarks", "reference_corpus", "arbitration"))

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

import mitsuba_scenes as MS  # noqa: E402

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

W = H = 96
LUM = np.array([0.2126, 0.7152, 0.0722])
REGIONS = {"tir_beam": (58, 72, 0, 40), "rainbow": (0, 45, 66, 92), "whole": (0, H, 0, W)}

FLOORS = {
    "lambertian": ("lambertian", [0.5] * 3, {}),
    "rough_metal": ("principled", [0.8, 0.8, 0.8], {"metallic": 1.0, "roughness": 0.5}),
}


def _yup(p):
    return [p[0], p[2], -p[1]]


def _scene(floor_key, photons, cam_from=(-0.75, 9.0, -0.75)):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    prism = MS.PARAMS["arb_prism_sun"]["prism"]
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": prism["ior_d"]})
    for a, b, c in MS.prism_triangles(prism):
        i = r.scene_object_count()
        r.add_triangle(_yup(a), _yup(b), _yup(c), glass)
        r.set_object_caustic_caster(i, True)
    kind, color, params = FLOORS[floor_key]
    floor = r.create_material(kind, color, params)
    e = 8.0
    r.add_triangle([-e, 0, -e], [e, 0, e], [e, 0, -e], floor)
    r.add_triangle([-e, 0, -e], [-e, 0, e], [e, 0, e], floor)
    sun = MS.PARAMS["arb_prism_sun"]["sun"]
    r.add_sun_light_dedicated(_yup(MS.sun_direction(sun)), math.radians(8.0),
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 9.0)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 16)
    r.set_use_refractive_caustics(True)
    r.set_use_reflective_caustics(True)
    r.set_adaptive_sampling(False)
    r.set_use_gpu(False)
    r.set_use_photon_caustics(photons)
    r.setup_camera(list(cam_from), [-0.75, 0.0, -0.75], [0.0, 0.0, -1.0],
                   28.0, 1.0, 0.0, 9.0, W, H)
    return r


def _lum(floor_key, photons, spp, seed, cam_from=(-0.75, 9.0, -0.75)):
    r = _scene(floor_key, photons, cam_from)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, 16, None, False), dtype=np.float64).reshape(H, W, 3)
    return img @ LUM


def _regions(img):
    return {k: float(img[y0:y1, x0:x1].mean()) for k, (y0, y1, x0, x1) in REGIONS.items()}


def _ratios(floor_key, spp_pt, seeds_pt, cam_from=(-0.75, 9.0, -0.75)):
    on = np.mean([_lum(floor_key, True, 64, s, cam_from) for s in (1, 2)], axis=0)
    off = np.mean([_lum(floor_key, False, spp_pt, s, cam_from) for s in seeds_pt], axis=0)
    a, b = _regions(on), _regions(off)
    ratios = {k: a[k] / b[k] for k in REGIONS}
    print(f"\n[#1045] {floor_key}: photons ON / path traced: "
          + ", ".join(f"{k} {v:.3f}" for k, v in ratios.items()))
    return ratios


@pytest.mark.slow
def test_lambertian_floor_photons_match_path_tracing_unchanged():
    for k, v in _ratios("lambertian", 1024, (1, 2)).items():
        assert abs(v - 1.0) <= 0.04, (k, v)


@pytest.mark.slow
def test_rough_metal_floor_photons_match_path_tracing():
    # The Lambertian gather read albedo/pi * E on the metal floor: far from 1.
    for k, v in _ratios("rough_metal", 1024, (1, 2)).items():
        assert abs(v - 1.0) <= 0.08, (k, v)


@pytest.mark.slow
def test_rough_metal_floor_view_dependence():
    # Oblique camera (~45 deg): the glossy lobe is view dependent, the Lambertian
    # estimate is not. Only the whole-frame mean is compared (REGIONS are top-down).
    ratios = _ratios("rough_metal", 1024, (1, 2), cam_from=(5.25, 6.0, -0.75))
    assert abs(ratios["whole"] - 1.0) <= 0.08, ratios

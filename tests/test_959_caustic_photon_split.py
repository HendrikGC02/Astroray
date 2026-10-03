#!/usr/bin/env python
"""#959 / #1025: caustic photons and the path-traced split count every caster chain once.

The photon loops refracted deterministically (weight T) and reflected only on TIR, while
the #909 split dropped a path-traced lamp hit only after a strict enter/exit chain. A chain
with a TIR inside the glass (T r T) was therefore in the map AND path traced: the GPU
caustic of the SF11 arbitration prism read 1.39x an independent oracle on its TIR beam
and 1.14x on the reflection beam (.astroray_plan/docs/caustic-photon-fresnel-split-research.md).
Now the photons Fresnel-sample reflect/refract (pbrt-v3 FresnelSpecular) and the split
drops any receiver -> caster+ -> lamp chain, so photons ON must equal brute-force path
tracing (photons OFF) on every beam. An 8 deg sun keeps the path-traced reference cheap.
The CPU builds the same map when ``set_use_photon_caustics`` is on (the addon's switch).
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

import mitsuba_scenes as MS  # noqa: E402  (pure python: the arbitration prism geometry)

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

W = H = 96
LUM = np.array([0.2126, 0.7152, 0.0722])
# Top-down floor regions (rows, cols): the T r T beam, the external-reflection + T r T beam,
# the dispersed refraction beam (T T), and the whole frame. Located on a photons-ON render.
REGIONS = {"tir_beam": (58, 72, 0, 40), "reflection_beam": (72, 96, 66, 86),
           "rainbow": (0, 45, 66, 92), "whole": (0, H, 0, W)}


def _yup(p):
    return [p[0], p[2], -p[1]]   # arbitration scenes are +Z up; the Python API is +Y up


def _scene(photons: bool, gpu: bool, reflective: bool = True):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    prism = MS.PARAMS["arb_prism_sun"]["prism"]
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": prism["ior_d"]})
    for a, b, c in MS.prism_triangles(prism):   # closed, outward wound, 5 mm above the floor
        i = r.scene_object_count()
        r.add_triangle(_yup(a), _yup(b), _yup(c), glass)
        r.set_object_caustic_caster(i, True)
    floor = r.create_material("lambertian", [0.5] * 3, {})
    e = 8.0
    r.add_triangle([-e, 0, -e], [e, 0, e], [e, 0, -e], floor)
    r.add_triangle([-e, 0, -e], [-e, 0, e], [e, 0, e], floor)
    sun = MS.PARAMS["arb_prism_sun"]["sun"]
    r.add_sun_light_dedicated(_yup(MS.sun_direction(sun)), math.radians(8.0),
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 9.0)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 16)
    r.set_use_refractive_caustics(True)
    r.set_use_reflective_caustics(reflective)
    r.set_adaptive_sampling(False)   # adaptive stops bias heavy-tailed caustic pixels low
    r.set_use_gpu(gpu)
    r.set_use_photon_caustics(photons)
    r.setup_camera([-0.75, 9.0, -0.75], [-0.75, 0.0, -0.75], [0.0, 0.0, -1.0],
                   28.0, 1.0, 0.0, 9.0, W, H)
    return r


def _lum(photons, gpu, spp, seed, reflective=True):
    r = _scene(photons, gpu, reflective)
    r.set_seed(seed)
    img = np.asarray(r.render(spp, 16, None, False), dtype=np.float64).reshape(H, W, 3)
    return img @ LUM, r


def _regions(img):
    return {k: float(img[y0:y1, x0:x1].mean()) for k, (y0, y1, x0, x1) in REGIONS.items()}


def _gpu_ok():
    return AVAILABLE and astroray.__features__.get("cuda", False) and astroray.Renderer().gpu_available


def test_arbitration_prism_base_is_not_coplanar_with_the_floor():
    """#1025: a base on the floor plane z-fights; the TIR glint then survived ~50 % per engine."""
    assert MS.PARAMS["arb_prism_sun"]["prism"]["loc"][2] >= 0.005


def test_cpu_use_photon_caustics_builds_the_photon_map():
    _, on = _lum(True, False, 1, 3)
    _, off = _lum(False, False, 1, 3)
    on_stats, off_stats = on.get_integrator_stats(), off.get_integrator_stats()
    assert on_stats.get("pm_ready") == 1.0 and on_stats.get("pm_stored_photons", 0) > 1000
    assert off_stats.get("pm_ready", 0.0) == 0.0


def _check_split(gpu, spp_pt, seeds_pt, tol, reflective=True):
    on = np.mean([_lum(True, gpu, 64, s, reflective)[0] for s in (1, 2)], axis=0)
    off = np.mean([_lum(False, gpu, spp_pt, s, reflective)[0] for s in seeds_pt], axis=0)
    a, b = _regions(on), _regions(off)
    ratios = {k: a[k] / b[k] for k in REGIONS}
    print(f"\n[#959] photons ON / path traced ({'gpu' if gpu else 'cpu'}): "
          + ", ".join(f"{k} {v:.3f}" for k, v in ratios.items()))
    for k, v in ratios.items():
        assert abs(v - 1.0) <= tol, (k, v)


@pytest.mark.slow   # ~25 s
def test_cpu_photon_split_matches_path_tracing():
    # 2 x 1024 spp path traced: region SE <= 1 %; the double count was +32 % (TIR) / +8 %.
    _check_split(False, 1024, (1, 2), 0.04)


@pytest.mark.skipif(not _gpu_ok(), reason="CUDA GPU not available")
def test_gpu_photon_split_matches_path_tracing():
    # Before #959: tir_beam 1.322, reflection_beam 1.080, whole 1.047 (RTX 5070 Ti).
    _check_split(True, 4096, (1, 2), 0.03)


@pytest.mark.skipif(not _gpu_ok(), reason="CUDA GPU not available")
def test_gpu_photon_split_matches_path_tracing_reflective_caustics_off():
    # Reflective caustics off: the photon loop drops reflected photons (TIR too), as the
    # path tracer's caustic gate drops the reflection after the receiver (Terra #959 review).
    _check_split(True, 4096, (1, 2), 0.03, reflective=False)


@pytest.mark.skipif(not _gpu_ok(), reason="CUDA GPU not available")
def test_cpu_and_gpu_photon_caustics_agree():
    cpu = _regions(np.mean([_lum(True, False, 64, s)[0] for s in (1, 2)], axis=0))
    gpu = _regions(np.mean([_lum(True, True, 64, s)[0] for s in (1, 2)], axis=0))
    for k in REGIONS:
        assert abs(cpu[k] / gpu[k] - 1.0) <= 0.02, (k, cpu[k], gpu[k])

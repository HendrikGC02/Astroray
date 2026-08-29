#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pkg201 Stage 3 (Finding E) — native caustic-toggle honour (CPU + GPU).

Cycles' caustics_reflective / caustics_refractive drop a specular/refractive
closure once the path already has a diffuse ancestor, so a diffuse->specular->light
caustic path is culled when the toggle is off. Astroray mirrors this with a sticky
`hadDiffuseAncestor` flag (CPU local / GPU SoA) + a runtime cull in
pathTraceSpectral / shadePathSlot, gated behind a __constant__ c_wfCausticGate.

Robust invariants (independent of how strong the path-traced caustic is):
  1. Default (both toggles on) is INERT — byte-identical (CPU) / within GPU noise.
  2. Turning a toggle OFF can only REMOVE energy (culls paths), never add it.
  3. On a glass-sphere-over-floor scene the refractive toggle measurably changes
     pixels (the p_changes_pixels honour signal).

Scene: a smooth dielectric sphere between a bright overhead light and a diffuse
floor — camera->floor->glass->light is the refractive caustic path. Photon
caustics are NOT enabled (item E honours the wavefront path tracer's own caustic).
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
import astroray  # noqa: E402

SPP = 96
MAX_DEPTH = 8
SEED = 5
W, H = 140, 110


def _build(use_gpu):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_integrator("path_tracer")
    r.set_seed(SEED)
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    r.add_sphere([0.0, 0.0, 0.0], 0.6, glass)
    floor = r.create_material("lambertian", [0.85, 0.85, 0.85], {})
    r.add_triangle([-3.0, -1.1, -3.0], [4.0, -1.1, -3.0], [4.0, -1.1, 3.0], floor)
    r.add_triangle([-3.0, -1.1, -3.0], [4.0, -1.1, 3.0], [-3.0, -1.1, 3.0], floor)
    # Bright emissive quad directly above the sphere (mesh emitter, samplable by
    # both NEE and a BSDF-sampled continuation ray) so refracted light reaches the
    # floor as a path-traced caustic.
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 40.0})
    r.add_triangle([-1.0, 2.2, -1.0], [1.0, 2.2, -1.0], [1.0, 2.2, 1.0], light)
    r.add_triangle([-1.0, 2.2, -1.0], [1.0, 2.2, 1.0], [-1.0, 2.2, 1.0], light)
    r.setup_camera(look_from=[0.0, 0.6, 4.2], look_at=[0.0, -0.6, 0.0],
                   vup=[0, 1, 0], vfov=42, aspect_ratio=W / H,
                   aperture=0.0, focus_dist=4.0, width=W, height=H)
    if use_gpu:
        r.set_use_gpu(True)
    return r


def _render(r):
    return np.asarray(r.render(SPP, MAX_DEPTH, None, False), dtype=np.float32)


def _lum(img):
    return img @ np.array([0.2126, 0.7152, 0.0722], np.float32)


# ---- CPU -----------------------------------------------------------------

def test_cpu_caustic_toggle_default_inert():
    """Both toggles on (default) == a plain render, exactly (CPU is deterministic)."""
    r = _build(False)
    plain = _render(r)
    r2 = _build(False)
    r2.set_use_reflective_caustics(True)
    r2.set_use_refractive_caustics(True)
    np.testing.assert_array_equal(plain, _render(r2),
                                  "default caustic toggles changed the CPU render")


def test_cpu_refractive_off_removes_energy_and_changes_pixels():
    on = _render(_build(False))
    r = _build(False)
    r.set_use_refractive_caustics(False)
    off = _render(r)
    # (2) culling can only remove energy.
    assert float(np.mean(_lum(off))) <= float(np.mean(_lum(on))) * 1.002, \
        "refractive-off INCREASED energy — cull is wrong-signed"
    # (3) it measurably changes the image (the honour p_changes_pixels signal).
    assert float(np.max(np.abs(_lum(off) - _lum(on)))) > 1e-3, \
        "refractive-off produced no visible change on a glass scene"


# ---- GPU -----------------------------------------------------------------

_gpu = pytest.mark.skipif(not bool(astroray.__features__.get("cuda", False)),
                          reason="needs a CUDA build")


@_gpu
def test_gpu_caustic_toggle_default_inert():
    """Both-on == plain within the GPU atomic-accumulation noise floor."""
    a = _render(_build(True))
    b = _render(_build(True))
    r = _build(True)
    r.set_use_reflective_caustics(True)
    r.set_use_refractive_caustics(True)
    with_toggles = _render(r)
    noise = float(np.max(np.abs(a - b)))
    feat = float(np.max(np.abs(a - with_toggles)))
    assert feat <= max(noise * 2.0, 1e-5), \
        f"default toggles exceeded GPU noise floor: feat={feat:.3g} noise={noise:.3g}"


@_gpu
def test_gpu_refractive_off_removes_energy_and_changes_pixels():
    on = _render(_build(True))
    r = _build(True)
    r.set_use_refractive_caustics(False)
    off = _render(r)
    assert float(np.mean(_lum(off))) <= float(np.mean(_lum(on))) * 1.005, \
        "GPU refractive-off INCREASED energy — cull is wrong-signed"
    assert float(np.max(np.abs(_lum(off) - _lum(on)))) > 1e-3, \
        "GPU refractive-off produced no visible change on a glass scene"

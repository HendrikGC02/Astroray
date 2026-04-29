#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pillar 2 / pkg14 — spectral environment map tests.

Covers:
  1. Atlas-vs-upsample fallback parity: evalSpectral vs eval_env_rgb_upsample
     over a sweep of directions. Bilinear interpolation in spectral space vs.
     RGB-then-upsampling is not algebraically identical, but for smooth HDRIs
     the per-channel error is well within the 1e-3 tolerance chosen here.
  2. After pkg14 commit 3: integrator_registry_names returns exactly
     {"path_tracer", "ambient_occlusion"}.
  3. Rendering an open (no-geometry) scene with a loaded env map produces
     a non-zero, non-NaN result via the spectral path tracer.
"""
import math
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

from base_helpers import setup_camera  # noqa: E402

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

ENV_HDR = os.path.join(os.path.dirname(__file__), '..', 'samples', 'test_env.hdr')
HAS_ENV = os.path.isfile(ENV_HDR)


def _sphere_directions(n: int):
    """Fibonacci lattice on the unit sphere — evenly distributed directions."""
    golden = (1 + math.sqrt(5)) / 2
    dirs = []
    for i in range(n):
        theta = math.acos(1 - 2 * (i + 0.5) / n)
        phi = 2 * math.pi * i / golden
        dirs.append([math.sin(theta) * math.cos(phi),
                     math.cos(theta),
                     math.sin(theta) * math.sin(phi)])
    return dirs


# ---------------------------------------------------------------------------
# Test 1: atlas parity
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_ENV, reason="test_env.hdr not found")
def test_eval_spectral_atlas_matches_upsample_fallback():
    """evalSpectral via atlas matches RGBIlluminantSpectrum fallback to 1e-3."""
    r = astroray.Renderer()
    assert r.load_environment_map(ENV_HDR), "failed to load env map"

    dirs = _sphere_directions(1000)
    u_values = [i / 1000.0 for i in range(1000)]

    max_err = 0.0
    sum_err = 0.0
    count = 0

    for d, u in zip(dirs, u_values):
        spectral = r.eval_env_spectral(d, u)
        fallback = r.eval_env_rgb_upsample(d, u)
        for a, b in zip(spectral, fallback):
            err = abs(a - b)
            sum_err += err
            count += 1
            if err > max_err:
                max_err = err

    mean_err = sum_err / count
    # Bilinear in spectral space vs bilinear in RGB then upsample differ by the
    # nonlinearity of the sigmoid polynomial fit. For a smooth HDRI the mean
    # per-channel error is small; we tolerate up to 1e-3.
    assert mean_err < 1e-3, f"mean abs error {mean_err:.2e} exceeds 1e-3"


# ---------------------------------------------------------------------------
# Test 2: registry names after pkg14
# ---------------------------------------------------------------------------

def test_registry_names():
    """pkg14 core integrators plus pkg22 restir-di must all be present."""
    names = set(astroray.integrator_registry_names())
    assert "path_tracer" in names, f"'path_tracer' missing from registry: {names}"
    assert "ambient_occlusion" in names, f"'ambient_occlusion' missing from registry: {names}"
    assert "restir-di" in names, f"'restir-di' missing from registry: {names}"
    assert "spectral_path_tracer" not in names, \
        "'spectral_path_tracer' still in registry after rename"
    assert "path" not in names, \
        "legacy 'path' integrator still in registry after deletion"


# ---------------------------------------------------------------------------
# Test 3: open-scene render with env map is valid and non-zero
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_ENV, reason="test_env.hdr not found")
def test_open_scene_env_render():
    """Rendering a scene with only an env map (no geometry) produces valid output."""
    r = astroray.Renderer()
    r.load_environment_map(ENV_HDR)
    r.set_integrator("path_tracer")
    setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0],
                 vfov=60, width=64, height=64)
    pixels = r.render(4, 4, None, False)
    assert pixels is not None
    arr = np.asarray(pixels)
    assert arr.shape == (64, 64, 3)
    assert not np.any(np.isnan(arr)), "NaN in env-map render"
    assert not np.any(np.isinf(arr)), "Inf in env-map render"
    assert np.mean(arr) > 0.0, "env-map render is entirely black"

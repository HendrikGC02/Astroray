#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pillar 2 / pkg11 — spectral path tracer integration tests.

Covers:
  1. Plugin registration: "path_tracer" is the canonical spectral-first
     integrator after pkg14.
  2. Cornell deterministic A/B: rendering the same scene twice with the same
     seed produces identical output and a non-trivial image.

Both renders are also written to PNG under test_results/ for visual review.

The prism / dispersion criterion from the original plan is deferred to
pkg13 (no dispersive material override exists yet — direction-spread
dispersion is physically impossible until a wavelength-dependent dielectric
ships).
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'build'))
sys.path.insert(0, os.path.dirname(__file__))

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from base_helpers import (  # noqa: E402
    create_cornell_box, save_image, setup_camera,
)


pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


SPP = 32
WIDTH = 200
HEIGHT = 150
MAX_DEPTH = 8


def _output_dir():
    d = os.path.join(os.path.dirname(__file__), '..', 'test_results')
    os.makedirs(d, exist_ok=True)
    return d


def _render_cornell(integrator_name: str, seed: int = 1) -> np.ndarray:
    r = astroray.Renderer()
    create_cornell_box(r)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=WIDTH, height=HEIGHT)
    r.set_integrator(integrator_name)
    r.set_seed(seed)
    pixels = r.render(SPP, MAX_DEPTH, None, True)
    return np.asarray(pixels, dtype=np.float32)


def test_spectral_path_tracer_registered():
    """Since pkg14, the integrator is registered as 'path_tracer' (the sole path)."""
    names = astroray.integrator_registry_names()
    assert "path_tracer" in names, (
        f"path_tracer not registered; available: {names}")
    assert "spectral_path_tracer" not in names, (
        f"old name 'spectral_path_tracer' still present after pkg14 rename")


def test_cornell_ab_match(test_results_dir):
    """path_tracer Cornell render is valid and consistent across two identical seeds.

    Since pkg14 deleted the legacy RGB path, this is a deterministic
    same-integrator A/B check rather than an RGB-vs-spectral parity test.
    """
    render_a = _render_cornell("path_tracer")
    render_b = _render_cornell("path_tracer")

    save_image(render_a, os.path.join(test_results_dir, 'pkg11_cornell_spectral_a.png'))
    save_image(render_b, os.path.join(test_results_dir, 'pkg11_cornell_spectral_b.png'))

    mean_a = render_a.reshape(-1, 3).mean(axis=0)
    print(f"\n  Cornell mean: {mean_a}")
    assert np.all(mean_a > 0.01), f"spectral image too dark, mean={mean_a}"
    assert not np.any(np.isnan(render_a)), "render contains NaN"
    assert np.allclose(render_a, render_b, rtol=0.0, atol=1e-7), \
        "same seed should produce deterministic path_tracer output"


def test_spectral_render_no_nan_no_inf():
    """The path_tracer must not emit NaN/Inf — would indicate divide-by-zero
    in the SampledSpectrum operators or a malformed Jakob-Hanika upsample."""
    spec = _render_cornell("path_tracer", seed=2)
    assert not np.any(np.isnan(spec)), "spectral render contains NaN"
    assert not np.any(np.isinf(spec)), "spectral render contains Inf"
    # And not entirely black / white.
    assert 0.001 < float(spec.mean()) < 0.95


def test_explicit_path_tracer_renders_cornell():
    """set_integrator('path_tracer') must produce a valid non-black Cornell render.

    Since pkg14, 'path_tracer' is the canonical (and only) full-spectrum
    integrator.  A Renderer with no set_integrator() produces all-black output;
    callers must set it explicitly (or use base_helpers.create_renderer()).
    """
    r = astroray.Renderer()
    create_cornell_box(r)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=WIDTH, height=HEIGHT)
    r.set_integrator("path_tracer")
    r.set_seed(3)
    pixels = np.asarray(r.render(SPP, MAX_DEPTH, None, True), dtype=np.float32)
    assert pixels.shape == (HEIGHT, WIDTH, 3)
    assert not np.any(np.isnan(pixels))
    assert 0.001 < float(pixels.mean()) < 0.95

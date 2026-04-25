#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pillar 2 / pkg11 — spectral path tracer integration tests.

Covers:
  1. Plugin registration: "spectral_path_tracer" appears in the registry.
  2. Cornell A/B match: rendering Cornell with the legacy RGB `path` and the
     new `spectral_path_tracer` produces near-identical mean RGB. The default
     evalSpectral / emittedSpectral fall back to a Jakob-Hanika upsample of
     the existing RGB BSDF / emission, so any chromatic delta is the
     hero-wavelength MC noise floor — it should be small at 32 spp.

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
    """The plugin must be in the integrator registry under the canonical name."""
    names = astroray.integrator_registry_names()
    assert "spectral_path_tracer" in names, (
        f"spectral_path_tracer not registered; available: {names}")


def test_cornell_ab_match(test_results_dir):
    """RGB and spectral integrators must agree on Cornell within tolerance.

    Default evalSpectral upsamples the legacy RGB eval(); the only divergence
    is the Jakob-Hanika roundtrip noise on 4 hero wavelengths. At 32 spp the
    per-channel mean delta should comfortably stay under ~5%.
    """
    rgb = _render_cornell("path")
    spec = _render_cornell("spectral_path_tracer")

    save_image(rgb, os.path.join(test_results_dir, 'pkg11_cornell_rgb.png'))
    save_image(spec, os.path.join(test_results_dir, 'pkg11_cornell_spectral.png'))
    diff = np.clip(np.abs(rgb - spec) * 5.0, 0.0, 1.0)
    save_image(diff, os.path.join(test_results_dir, 'pkg11_cornell_diff_x5.png'))

    rgb_mean = rgb.reshape(-1, 3).mean(axis=0)
    spec_mean = spec.reshape(-1, 3).mean(axis=0)
    print(f"\n  RGB  mean: {rgb_mean}")
    print(f"  Spec mean: {spec_mean}")
    assert np.all(spec_mean > 0.01), \
        f"spectral image too dark, mean={spec_mean}"

    rel_delta = np.abs(rgb_mean - spec_mean) / (rgb_mean + 1e-3)
    print(f"  rel delta: {rel_delta}")
    # 5% per-channel tolerance — accommodates 4-hero-wavelength MC noise at
    # 32 spp. The Jakob-Hanika upsample is faithful in mean; any larger
    # divergence indicates a real bug.
    assert np.all(rel_delta < 0.05), (
        f"spectral mean diverges from RGB by {rel_delta} (threshold 0.05); "
        f"rgb={rgb_mean}, spec={spec_mean}")


def test_spectral_render_no_nan_no_inf():
    """The spectral path must not emit NaN/Inf — would indicate divide-by-zero
    in the SampledSpectrum operators or a malformed Jakob-Hanika upsample."""
    spec = _render_cornell("spectral_path_tracer", seed=2)
    assert not np.any(np.isnan(spec)), "spectral render contains NaN"
    assert not np.any(np.isinf(spec)), "spectral render contains Inf"
    # And not entirely black / white.
    assert 0.001 < float(spec.mean()) < 0.95


def test_legacy_default_unchanged():
    """A Renderer with no set_integrator() call must still run the legacy
    pathTrace pipeline (this is the pkg14 invariant — pkg11 must not flip
    the default by accident)."""
    r = astroray.Renderer()
    create_cornell_box(r)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=WIDTH, height=HEIGHT)
    r.set_seed(3)
    pixels = np.asarray(r.render(SPP, MAX_DEPTH, None, True), dtype=np.float32)
    assert pixels.shape == (HEIGHT, WIDTH, 3)
    assert not np.any(np.isnan(pixels))
    assert 0.001 < float(pixels.mean()) < 0.95

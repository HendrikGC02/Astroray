#!/usr/bin/env python
"""pkg29 — spectral dielectric prism validation."""

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

from base_helpers import save_image  # noqa: E402
from scenes.prism_reference import (  # noqa: E402
    HEIGHT,
    WIDTH,
    red_blue_centroid_separation,
    render_prism,
)


pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


def test_dispersive_prism_render_is_finite_and_saved(test_results_dir):
    pixels = render_prism(astroray, dispersive=True, seed=17)
    save_image(pixels, os.path.join(test_results_dir, "pkg29_dispersive_prism.png"))

    assert pixels.shape == (HEIGHT, WIDTH, 3)
    assert np.isfinite(pixels).all()
    assert float(pixels.mean()) > 0.01
    assert float(pixels.max()) > 0.1


def test_dispersive_prism_has_measurable_color_spread(test_results_dir):
    flat = render_prism(astroray, dispersive=False, seed=17)
    dispersive = render_prism(astroray, dispersive=True, seed=17)

    save_image(flat, os.path.join(test_results_dir, "pkg29_flat_prism.png"))
    save_image(dispersive, os.path.join(test_results_dir, "pkg29_bk7_prism.png"))

    diff = np.abs(dispersive - flat)
    flat_sep = red_blue_centroid_separation(flat)
    dispersive_sep = red_blue_centroid_separation(dispersive)

    print(f"\n  flat red/blue centroid separation: {flat_sep:.3f}px")
    print(f"  BK7 red/blue centroid separation:  {dispersive_sep:.3f}px")
    print(f"  max absolute RGB diff:             {float(diff.max()):.4f}")

    assert np.isfinite(dispersive).all()
    assert float(diff.mean()) > 0.02
    assert float(diff.max()) > 0.25
    assert dispersive_sep - flat_sep > 3.0

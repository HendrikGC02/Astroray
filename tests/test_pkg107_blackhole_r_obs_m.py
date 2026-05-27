"""pkg107 regression: BlackHole r_obs_M parameter changes visible shadow size.

The world-to-GR scale factor is `worldToGR = r_obs_M / influence_radius`.
Smaller `r_obs_M` shrinks the world-to-GR scale → grows the visible
shadow at the same camera distance. Default 100.0 preserves pkg40-44
baselines; new code paths can pass smaller values (e.g. pkg104's GR
scenes use 20.0) for dramatic shadows.

This test renders the same Schwarzschild scene twice — once with the
default r_obs_M and once with r_obs_M=20 — and asserts the dark-pixel
fraction is materially larger in the second case.
"""

from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


WIDTH = 96
HEIGHT = 96
SAMPLES = 8
MAX_DEPTH = 4


def _render_schwarzschild(r_obs_M_param):
    """Render the same fixed-geometry Schwarzschild scene with the given r_obs_M."""
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_seed(17)
    r.set_adaptive_sampling(False)

    dist = 12.0
    r.setup_camera(
        [0.0, 0.0, dist], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
        45.0,
        WIDTH / HEIGHT,
        0.0,
        dist,
        WIDTH, HEIGHT,
    )

    params = {
        "spin": 0.0,
        "disk_outer": 0.0,
        "accretion_rate": 0.0,
        "inclination": 0.0,
        "enable_adaf": False,
    }
    if r_obs_M_param is not None:
        params["r_obs_M"] = r_obs_M_param

    r.add_black_hole([0.0, 0.0, 0.0], 4.0e6, 5.0, params)
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, True), dtype=np.float32)


def _dark_fraction(img, luminance_threshold=0.05):
    luma = img @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    return float((luma < luminance_threshold).sum()) / luma.size


def test_default_r_obs_M_preserves_small_shadow():
    """With default r_obs_M=100, visible shadow should be small (preserves
    pkg40-pkg44 baseline behaviour)."""
    img = _render_schwarzschild(r_obs_M_param=None)  # use default
    dark = _dark_fraction(img)
    assert dark < 0.02, (
        f"default-r_obs_M dark fraction {dark:.4f} unexpectedly large; "
        f"may indicate r_obs_M default changed"
    )


def test_small_r_obs_M_grows_shadow():
    """With r_obs_M=20, visible shadow should be at least 10x larger than
    the default. Verifies the parameter actually flows through."""
    default = _dark_fraction(_render_schwarzschild(r_obs_M_param=None))
    smaller = _dark_fraction(_render_schwarzschild(r_obs_M_param=20.0))
    assert smaller >= 0.03, (
        f"r_obs_M=20 should produce a visible shadow ≥3% of frame; "
        f"got {smaller:.4f}"
    )
    assert smaller > default * 5.0, (
        f"r_obs_M=20 produced {smaller:.4f}, only {smaller/max(default,1e-6):.1f}x "
        f"the default {default:.4f}; expected ≥5x"
    )


def test_r_obs_M_explicitly_set_to_default_matches_omitted():
    """Setting r_obs_M=100.0 explicitly should match the omit-the-param path."""
    a = _dark_fraction(_render_schwarzschild(r_obs_M_param=None))
    b = _dark_fraction(_render_schwarzschild(r_obs_M_param=100.0))
    assert abs(a - b) < 0.005, (
        f"explicit r_obs_M=100 ({b:.4f}) differs from omitted ({a:.4f}); "
        f"default should be 100.0"
    )

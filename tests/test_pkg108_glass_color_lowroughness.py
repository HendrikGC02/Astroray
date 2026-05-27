"""pkg108 BUG-14 probe: glass color at low roughness.

Reported behaviour: a dielectric (glass) material's base-color tint
does not visibly affect the rendered transmission at near-zero
roughness — light passes through "white" regardless of the tint.

This test exercises the hypothesis with the simplest possible scene:
a glass slab between a strong light and a white floor. Render twice
with two different tints (strong red vs strong blue) and assert the
floor's mean RGB differs measurably in the expected channels.

If this test FAILS, BUG-14 is confirmed (tints aren't reaching the
BSDF). If it PASSES, BUG-14 either was already fixed or doesn't
reproduce in this configuration. Either way it's a useful gate.
"""

from __future__ import annotations

import sys
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
HEIGHT = 64
SAMPLES = 64
MAX_DEPTH = 8


def _render_through_glass(tint_rgb):
    """Render a scene with a glass slab tinted with the given RGB.

    Layout: light above, glass slab in middle of frame, white floor below.
    Camera looks down at the floor through the glass. Tinted transmission
    should colour the rectangle under the slab.
    """
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(31)

    # White floor.
    white = r.create_material("lambertian", [0.92, 0.92, 0.92], {})
    r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], white)
    r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], white)

    # Bright overhead light.
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 25.0})
    r.add_triangle([-0.6, 2.5, -0.6], [0.6, 2.5, -0.6], [0.6, 2.5, 0.6], light)
    r.add_triangle([-0.6, 2.5, -0.6], [0.6, 2.5, 0.6], [-0.6, 2.5, 0.6], light)

    # Tinted glass slab — VERY LOW roughness, just covering the central area.
    # 0.02 roughness = near-mirror smoothness; this is the regime BUG-14 reports.
    glass = r.create_material("dielectric", tint_rgb, {"ior": 1.5, "roughness": 0.02})
    # Thin horizontal glass slab at y=1.2, 1.0 wide × 1.0 deep, ~0.1 thick.
    y_top, y_bot = 1.25, 1.15
    # Top face
    r.add_triangle([-0.5, y_top, -0.5], [0.5, y_top, -0.5], [0.5, y_top, 0.5], glass)
    r.add_triangle([-0.5, y_top, -0.5], [0.5, y_top, 0.5], [-0.5, y_top, 0.5], glass)
    # Bottom face
    r.add_triangle([-0.5, y_bot, -0.5], [0.5, y_bot, 0.5], [0.5, y_bot, -0.5], glass)
    r.add_triangle([-0.5, y_bot, -0.5], [-0.5, y_bot, 0.5], [0.5, y_bot, 0.5], glass)

    # Camera looking down-and-forward at the floor area under the slab.
    r.setup_camera(
        [0.0, 1.4, 2.0], [0.0, -0.5, 0.0], [0.0, 1.0, 0.0],
        38.0,
        WIDTH / HEIGHT,
        0.0,
        2.5,
        WIDTH, HEIGHT,
    )
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, True), dtype=np.float32)


def test_red_vs_blue_glass_tints_floor_differently():
    """Glass with red tint should produce a redder transmission than blue tint."""
    red_img = _render_through_glass([0.95, 0.05, 0.05])
    blue_img = _render_through_glass([0.05, 0.05, 0.95])

    # Sample the floor area under the slab — bottom half of frame, center.
    h, w, _ = red_img.shape
    floor_red  = red_img[h // 2:, w // 4:3 * w // 4, :]
    floor_blue = blue_img[h // 2:, w // 4:3 * w // 4, :]

    # Channel means in the floor ROI.
    red_means  = floor_red.mean(axis=(0, 1))   # (3,) = [R, G, B]
    blue_means = floor_blue.mean(axis=(0, 1))

    # Red-tint render must have higher R and lower B than blue-tint render.
    # Ratio rather than absolute difference to robust to overall exposure.
    r_ratio = (red_means[0] + 1e-4) / (blue_means[0] + 1e-4)
    b_ratio = (red_means[2] + 1e-4) / (blue_means[2] + 1e-4)

    assert r_ratio > 1.3, (
        f"Red tint did not produce visibly redder floor than blue tint. "
        f"Red-tint R={red_means[0]:.4f}, blue-tint R={blue_means[0]:.4f}, "
        f"ratio={r_ratio:.2f} (want >1.3)"
    )
    assert b_ratio < 0.77, (
        f"Red tint did not produce visibly bluer-less floor than blue tint. "
        f"Red-tint B={red_means[2]:.4f}, blue-tint B={blue_means[2]:.4f}, "
        f"ratio={b_ratio:.2f} (want <0.77)"
    )

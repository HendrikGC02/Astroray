"""pkg108 BUG-14 probe via Disney transmission path.

The audit hypothesised that 'glass color at low roughness' may be lost
in the Blender addon's Principled-BSDF routing (kind='principled',
transmission=1, low roughness → Disney material delta-transmission branch).

This test exercises that path directly: create a Disney material with
transmission=1, low roughness, and a red tint. Render a glass sphere
backlit by a bright source. Compare to the same setup with blue tint —
the floor patch in front of the sphere should differ measurably.

Confirms or refutes the addon-side BUG-14 hypothesis.
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
HEIGHT = 96
SAMPLES = 64
MAX_DEPTH = 8


def _render_with_disney_tint(tint_rgb):
    """Same scene as pkg108 BUG-14 probe but the glass is a Disney material
    with transmission=1 + low roughness (Blender Principled-BSDF routing)."""
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(31)

    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 35.0})
    r.add_sphere([0.0, 0.0, -2.0], 0.4, light)

    floor = r.create_material("lambertian", [0.92, 0.92, 0.92], {})
    r.add_triangle([-3, -1, -3], [3, -1, -3], [3, -1, 3], floor)
    r.add_triangle([-3, -1, -3], [3, -1, 3], [-3, -1, 3], floor)

    # Disney path: transmission=1, very low roughness (delta-transmission branch).
    # This mirrors what the Blender addon's "Principled BSDF, transmission=1" route
    # would produce.
    mat = r.create_material("disney", tint_rgb, {
        "transmission": 1.0,
        "roughness": 0.02,
        "metallic": 0.0,
        "ior": 1.5,
    })
    r.add_sphere([0.0, 0.0, 0.0], 0.6, mat)

    r.setup_camera(
        [0.0, 0.4, 2.4], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
        32.0,
        WIDTH / HEIGHT,
        0.0,
        2.4,
        WIDTH, HEIGHT,
    )
    # LINEAR (apply_gamma=False). The light is intensity 35, so the transmitted
    # light is far above 1.0 in both tinted channels: a gamma render clips them
    # to 1 and the colour comparison below degenerates (memory
    # gamma-vs-linear-comparison-artifact / gamma-furnace-cannot-detect-energy-gain).
    return np.asarray(r.render(SAMPLES, MAX_DEPTH, None, False), dtype=np.float32)


def test_disney_glass_tint_at_low_roughness_visible():
    """Disney glass (transmission=1, low roughness) with red vs blue tint must
    produce visibly different renders. If identical, BUG-14 reproduces via the
    Blender Principled-BSDF routing path.

    Rewritten 2026-09-20 (#767 / PR #837) from gamma to LINEAR. The old form
    compared gamma-encoded ROI means, and at this exposure R and B clip to 1.0
    in BOTH renders, so it measured the clipped fraction, not the tint. It
    passed on the pre-#767 build only because the CIE 1964 10 deg observer
    drove the blue tint's red channel negative (1 nm quadrature: the blue tint
    reconstructs (0.00, 0.12, 0.96) under 10 deg vs (0.05, 0.05, 0.95) under
    1931 2 deg), which inflated the red-vs-blue contrast. In LINEAR the tint is
    unmistakable on both builds: in-render R/B is 25.2 (red tint) and 0.118
    (blue tint) here, 38.7 / 0.042 pre-#767; cross-render R ratio 8.0 (19.4
    pre-#767). A tint-ignoring engine returns ~1 for all four and fails.
    """
    red = _render_with_disney_tint([0.95, 0.05, 0.05])
    blue = _render_with_disney_tint([0.05, 0.05, 0.95])

    # ROI = central region where the tinted transmission lands.
    h, w, _ = red.shape
    cy0, cy1 = h // 4, 3 * h // 4
    cx0, cx1 = w // 4, 3 * w // 4

    red_mean = red[cy0:cy1, cx0:cx1].mean(axis=(0, 1)).astype(np.float64)
    blue_mean = blue[cy0:cy1, cx0:cx1].mean(axis=(0, 1)).astype(np.float64)

    # Within each render: the tinted channel dominates its opposite.
    red_rb = (red_mean[0] + 1e-6) / (red_mean[2] + 1e-6)
    blue_rb = (blue_mean[0] + 1e-6) / (blue_mean[2] + 1e-6)
    # Across renders: the red render is redder, the blue render bluer.
    r_ratio = (red_mean[0] + 1e-6) / (blue_mean[0] + 1e-6)
    b_ratio = (red_mean[2] + 1e-6) / (blue_mean[2] + 1e-6)
    msg = (f"red mean={np.round(red_mean, 3)} blue mean={np.round(blue_mean, 3)}; "
           f"in-render R/B red={red_rb:.2f} blue={blue_rb:.3f}; "
           f"cross R={r_ratio:.2f} B={b_ratio:.3f}")

    assert red_rb > 4.0, f"Disney transmission ignores the red tint: {msg}"
    assert blue_rb < 0.5, f"Disney transmission ignores the blue tint: {msg}"
    assert r_ratio > 3.0, f"red tint does not brighten red vs the blue tint: {msg}"
    assert b_ratio < 0.35, f"red tint does not darken blue vs the blue tint: {msg}"

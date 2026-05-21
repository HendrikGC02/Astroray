"""pkg99 regression: ADAF VolumetricEmission must reach the renderer.

Before pkg99 fix (commit pre-2026-05-22): ADAF ON and ADAF OFF produced
pixel-identical output because `black_hole.h` multiplied volumetric emission
by `exposureScale = 5e-14`, a Novikov-Thorne disk normalization factor that
made all volumetric contributions effectively zero.

After fix: ADAF ON must produce a measurably different image than ADAF OFF.

This is a wiring regression test, not a physics correctness test. It does not
assert a particular glow shape, brightness, or radial profile — only that
toggling `enable_adaf` materially changes pixel values.
"""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pytest

SCENE_DIR = Path(__file__).resolve().parent / "scenes"
if str(SCENE_DIR) not in sys.path:
    sys.path.insert(0, str(SCENE_DIR))


def _build_adaf_scene(astroray, enable_adaf: bool, width=32, height=32):
    """Single-black-hole scene; ADAF emission toggleable."""
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0.0, 0.0, 30.0],
        look_at=[0.0, 0.0, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=20.0,
        aspect_ratio=width / height,
        aperture=0.0,
        focus_dist=30.0,
        width=width,
        height=height,
    )
    r.add_black_hole(
        [0.0, 0.0, 0.0], 4.0e6, 16.0,
        {
            "enable_adaf": enable_adaf,
            "adaf_mdot_eddington": 1.0e-4,
            "adaf_electron_temp": 1.0e10,
            "adaf_beta_mag": 0.1,
            "adaf_r_inner": 1.5,
            "adaf_r_outer": 100.0,
            "adaf_flattening": 0.0,
            "adaf_alpha": 0.1,
            "adaf_s": 0.3,
            "adaf_intensity_scale": 1.0e30,
        },
    )
    r.set_integrator("path_tracer")
    return r


def test_adaf_on_differs_from_off():
    """ADAF ON must produce different pixels than ADAF OFF.

    Pre-pkg99-fix this failed (pixel-identical due to 5e-14 multiplication
    in black_hole.h annihilating the volumetric contribution).
    """
    import astroray

    r_off = _build_adaf_scene(astroray, enable_adaf=False)
    pixels_off = np.asarray(r_off.render(8, 1))

    r_on = _build_adaf_scene(astroray, enable_adaf=True)
    pixels_on = np.asarray(r_on.render(8, 1))

    # Identical RNG seed + identical scene (except enable_adaf) must give
    # measurably different pixels.
    max_abs_diff = float(np.max(np.abs(pixels_on - pixels_off)))
    assert max_abs_diff > 1e-6, (
        f"pkg99 regression: ADAF ON == OFF (max abs diff {max_abs_diff:.2e}). "
        "VolumetricEmission contribution is not reaching the renderer. "
        "Check black_hole.h traceGRSpectral does not multiply volumetric "
        "emission by exposureScale."
    )

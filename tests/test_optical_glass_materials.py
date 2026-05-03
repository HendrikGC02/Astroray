#!/usr/bin/env python
"""Optical glass presets and thin-glass material coverage."""

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


pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


def _setup_camera(r, width=64, height=64):
    r.setup_camera(
        [0.0, 0.0, 3.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
        38.0, width / height, 0.0, 3.0, width, height)


def test_optical_glass_presets_are_registered():
    names = set(astroray.optical_glass_preset_names())
    expected = {
        "bk7", "fused_silica", "flint_sf11", "diamond",
        "water", "ice", "ruby", "sapphire", "emerald",
    }
    assert expected.issubset(names)


def test_optical_glass_presets_render_finite_contact_tiles(test_results_dir):
    presets = ["bk7", "flint_sf11", "diamond", "emerald"]
    tiles = []
    for i, preset in enumerate(presets):
        r = astroray.Renderer()
        r.set_integrator("path_tracer")
        r.set_seed(210 + i)
        r.set_background_color([0.55, 0.68, 0.95])
        mat = r.create_material("dielectric", [1.0, 1.0, 1.0], {"glass_preset": preset})
        r.add_sphere([0.0, 0.0, 0.0], 0.75, mat)
        _setup_camera(r, 56, 56)
        pixels = np.asarray(r.render(12, 8, None, True), dtype=np.float32)
        save_image(pixels, os.path.join(test_results_dir, f"material_preset_{preset}.png"))
        assert pixels.shape == (56, 56, 3)
        assert np.isfinite(pixels).all()
        assert float(pixels.mean()) > 0.01
        tiles.append(pixels)

    contact = np.concatenate(tiles, axis=1)
    save_image(contact, os.path.join(test_results_dir, "material_optical_glass_presets.png"))


def test_thin_glass_transmits_background_and_saves_image(test_results_dir):
    def render_pane(material_type, color, params):
        r = astroray.Renderer()
        r.set_integrator("path_tracer")
        r.set_seed(310)
        r.set_background_color([0.08, 0.86, 0.22])
        mat = r.create_material(material_type, color, params)
        r.add_triangle([-1.15, -0.9, 0.0], [1.15, -0.9, 0.0], [1.15, 0.9, 0.0], mat)
        r.add_triangle([-1.15, -0.9, 0.0], [1.15, 0.9, 0.0], [-1.15, 0.9, 0.0], mat)
        _setup_camera(r, 64, 64)
        return np.asarray(r.render(24, 6, None, True), dtype=np.float32)

    thin = render_pane("thin_glass", [1.0, 1.0, 1.0], {"ior": 1.5, "transmission": 1.0})
    opaque = render_pane("lambertian", [0.0, 0.0, 0.0], {})

    save_image(thin, os.path.join(test_results_dir, "material_thin_glass_pane.png"))
    save_image(opaque, os.path.join(test_results_dir, "material_thin_glass_opaque_ref.png"))

    center = thin[20:44, 20:44]
    opaque_center = opaque[20:44, 20:44]
    green_ratio = float(np.mean(center[..., 1]) / (np.mean(center) + 1e-6))

    assert np.isfinite(thin).all()
    assert float(np.mean(center)) > float(np.mean(opaque_center)) + 0.25
    assert green_ratio > 1.45

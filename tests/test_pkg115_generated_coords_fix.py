"""pkg115 GENERATED-coordinate regression test (real bound APIs).

The mesh bug: triangle hits carry no object-level hitObject, so GENERATED
coordinate mode silently fell back to UV — a checker on a mesh rendered
concentric UV rings instead of Blender/Cycles' 3D bbox-normalized blocks.
The fix bakes an explicit per-object bbox onto the texture
(set_texture_generated_bbox; see advanced_features.h CoordMode::Generated).

This test exercises the EXPLICIT-bbox path end-to-end through a real
render: a flat 2-triangle quad spanning x,z in [0,4] textured with a
checker in GENERATED mode and a baked bbox of min=(0,-1,0), size=(4,2,4).
With checker scale 4, the generated coords g = (p-min)/size traverse
[0,1] across the quad, so the pattern must alternate a handful of times
along x — and, critically, must DIFFER from the UV-mode rendering of the
same quad (the pre-fix fallback).

(The previous version of this test used invented APIs — add_mesh_sphere /
set_material_albedo_texture / set_camera — and could never run; pkg98
review caught it. Everything below is verified against the real
bindings: create_procedural_texture, set_texture_coord_mode,
set_texture_generated_bbox, create_material(params={'texture': name}),
add_triangle, setup_camera, render.)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")


def _render_quad(coord_mode: str) -> np.ndarray:
    r = astroray.Renderer()

    tex = f"gen_test_checker_{coord_mode}"
    # checker params: [r1,g1,b1, r2,g2,b2, scale]
    r.create_procedural_texture(tex, "checker",
                                [1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 4.0])
    if coord_mode == "GENERATED":
        r.set_texture_coord_mode(tex, "GENERATED")
        r.set_texture_generated_bbox(tex, [0.0, -1.0, 0.0], [4.0, 2.0, 4.0])

    mat = r.create_material("lambertian", [1.0, 1.0, 1.0],
                            {"texture": tex})
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 4.0})

    # Flat quad spanning x,z in [0,4] at y=0. UVs are whatever add_triangle
    # assigns (the pre-fix fallback path); generated coords come from the
    # baked bbox.
    r.add_triangle([0, 0, 0], [4, 0, 0], [4, 0, 4], mat)
    r.add_triangle([0, 0, 0], [4, 0, 4], [0, 0, 4], mat)
    # Overhead light quad so the surface is lit.
    r.add_triangle([0, 3, 0], [4, 3, 0], [4, 3, 4], light)
    r.add_triangle([0, 3, 0], [4, 3, 4], [0, 3, 4], light)

    # Camera straight down at the quad, BELOW the light plane (y=3) so
    # the emissive quad doesn't block the view.
    r.setup_camera([2.0, 2.5, 2.0], [2.0, 0.0, 2.0], [0.0, 0.0, 1.0],
                   80.0, 1.0, 0.0, 2.5, 96, 96)
    r.set_integrator("path_tracer")
    r.set_seed(7)
    img = np.asarray(r.render(32, 4, None, False),
                     dtype=np.float32).reshape(96, 96, 3)
    return img


def _flips(scanline: np.ndarray) -> int:
    """Count dark<->bright alternations along a luminance scanline."""
    lum = scanline.mean(axis=-1)
    lo, hi = np.percentile(lum, 20), np.percentile(lum, 80)
    if hi - lo < 1e-4:
        return 0
    binary = lum > (lo + hi) / 2.0
    return int(np.count_nonzero(binary[1:] != binary[:-1]))


def test_generated_mode_uses_baked_bbox():
    gen = _render_quad("GENERATED")
    assert np.all(np.isfinite(gen))
    assert float(gen.mean()) > 1e-3, "scene unexpectedly black"

    # Center scanline must show a small number of large 3D checker blocks:
    # checker scale 4 over generated x in [0,1] -> ~4 cells -> 3-5 flips.
    flips = _flips(gen[48, 8:88])
    assert 2 <= flips <= 7, (
        f"GENERATED checker scanline flips={flips}, expected ~4 large "
        f"blocks (3-5 flips) from the baked-bbox path"
    )


def test_generated_differs_from_uv_fallback():
    gen = _render_quad("GENERATED")
    uv = _render_quad("UV")
    # The modes must produce materially different patterns (the pre-fix bug
    # made GENERATED silently identical to UV on meshes).
    diff = float(np.abs(gen - uv).mean())
    assert diff > 0.02, (
        f"GENERATED and UV renders nearly identical (mean|diff|={diff:.4f}) "
        f"— the baked-bbox path is not taking effect"
    )

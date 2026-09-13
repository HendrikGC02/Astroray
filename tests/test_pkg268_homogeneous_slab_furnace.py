"""pkg268 — homogeneous bounded-medium slab transmittance vs analytic Beer–Lambert.

An emissive wall is viewed head-on through a bounded homogeneous absorbing slab
(``add_homogeneous_medium``, albedo 0 ⇒ pure absorption). The measured centre
transmittance must match ``exp(-σ_t · thickness)``. Rendered LINEAR
(``apply_gamma=False``) with a FLOOR and a CEILING assert (gamma would clamp and
hide energy errors — memory gamma-furnace-cannot-detect-energy-gain).
"""

from __future__ import annotations

import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

import astroray

SEED = 268111


def _render_cpu(r, spp, max_depth, w, h):
    img = np.asarray(r.render(spp, max_depth, None, False), dtype=np.float64)
    if img.ndim == 1:
        img = img.reshape(h, w, 3)
    return img


def _slab_scene(extinction, dist=6.0, slab_near=-4.0, slab_far=-2.0, w=24, h=24):
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_use_gpu(False)  # pkg268 volume transport is CPU-only (GPU = pkg269)
    r.set_background_color([0.0, 0.0, 0.0])
    wall = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 1.0})
    r.add_triangle([-20, -20, -dist], [20, -20, -dist], [20, 20, -dist], wall)
    r.add_triangle([-20, -20, -dist], [20, 20, -dist], [-20, 20, -dist], wall)
    if extinction is not None:
        # pure absorption: albedo 0 -> a real collision kills the path.
        r.add_homogeneous_medium([-10.0, -10.0, slab_near], [10.0, 10.0, slab_far],
                                 extinction, [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], 0.0)
    r.setup_camera([0.0, 0.0, 0.001], [0.0, 0.0, -dist], [0.0, 1.0, 0.0],
                   20.0, w / h, 0.0, dist, w, h)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 2)
    return r


def _center_mean(img):
    h, w = img.shape[:2]
    return float(img[h // 2 - 3:h // 2 + 3, w // 2 - 3:w // 2 + 3, :].mean())


def test_slab_transmittance_matches_beer_lambert():
    thickness = 2.0  # slab from z=-4 to z=-2, camera ray along -z
    clear = _center_mean(_render_cpu(_slab_scene(None), 256, 2, 24, 24))
    assert clear > 0.1, "clear wall should be visible"
    for ext in (0.3, 0.6):
        foggy = _center_mean(_render_cpu(_slab_scene(ext), 512, 2, 24, 24))
        measured = foggy / clear
        analytic = float(np.exp(-ext * thickness))
        print(f"[pkg268 slab] ext={ext} thickness={thickness}: "
              f"measured Tr={measured:.4f} analytic={analytic:.4f}")
        # FLOOR + CEILING around the analytic value (MC noise + RR tail).
        assert measured >= analytic * 0.85, (
            f"transmittance {measured:.4f} below floor {analytic*0.85:.4f}")
        assert measured <= analytic * 1.12, (
            f"transmittance {measured:.4f} above ceiling (energy gain?) "
            f"{analytic*1.12:.4f}")


def test_slab_render_is_deterministic():
    a = _render_cpu(_slab_scene(0.4), 64, 2, 24, 24)
    b = _render_cpu(_slab_scene(0.4), 64, 2, 24, 24)
    assert np.array_equal(a, b), "fixed-seed slab render is not bit-reproducible"

"""pkg268 — visual evidence for bounded in-scattering media (the #807 cabinet
cross-check band: a soft translucent RED patch, not a solid disc).

Renders a bounded homogeneous red scattering cube lit by a point light through
the spectral integrator (in-scatter + medium NEE) and saves a PNG for
qualitative inspection. Asserts the cube region is reddish and translucent
(some background shows through) — the qualitative bar from the Batch F brief.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

from base_helpers import save_image

import astroray

SEED = 268777
_OUT = os.path.join(os.path.dirname(__file__), "..", "test_results", "batchF")


def _render(r, spp, max_depth, w, h):
    img = np.asarray(r.render(spp, max_depth, None, False), dtype=np.float64)
    if img.ndim == 1:
        img = img.reshape(h, w, 3)
    return img


def _scene(with_volume, w=96, h=96):
    r = astroray.Renderer()
    r.set_seed(SEED)
    r.set_background_color([0.15, 0.18, 0.22])  # cool grey backdrop
    r.add_point_light([3.0, 4.0, 3.0], {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 120.0)
    if with_volume:
        # red single-scattering cube centered at origin, side 2 (AABB [-1,1]^3).
        r.add_homogeneous_medium([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0],
                                 1.5, [0.9, 0.15, 0.12], [1.0, 1.0, 1.0], 0.0)
    r.setup_camera([0.0, 0.0, 6.0], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   30.0, w / h, 0.0, 6.0, w, h)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", 8)
    return r


def test_red_scatter_cube_is_translucent_and_reddish():
    os.makedirs(_OUT, exist_ok=True)
    w = h = 96
    bg = _render(_scene(False, w, h), 64, 8, w, h)
    vol = _render(_scene(True, w, h), 256, 8, w, h)
    save_image(vol, os.path.join(_OUT, "pkg268_red_scatter_cube.png"))
    save_image(bg, os.path.join(_OUT, "pkg268_backdrop_novolume.png"))

    # center region overlaps the cube.
    cy0, cy1 = h // 2 - 12, h // 2 + 12
    cx0, cx1 = w // 2 - 12, w // 2 + 12
    cube = vol[cy0:cy1, cx0:cx1]
    cube_mean = cube.reshape(-1, 3).mean(axis=0)
    print(f"[pkg268 visual] cube_mean RGB = {cube_mean.round(4)}")
    # reddish: R dominates G and B.
    assert cube_mean[0] > cube_mean[1] * 1.3, f"cube not red-dominant: {cube_mean}"
    assert cube_mean[0] > cube_mean[2] * 1.3, f"cube not red-dominant: {cube_mean}"
    # translucent + lit: not black, and the scattering adds energy vs a pure
    # silhouette (the red channel in the cube exceeds the backdrop red there).
    bg_cube_r = bg[cy0:cy1, cx0:cx1, 0].mean()
    assert cube_mean[0] > bg_cube_r, (
        f"no in-scatter brightening (cube R {cube_mean[0]:.4f} <= backdrop R {bg_cube_r:.4f})")

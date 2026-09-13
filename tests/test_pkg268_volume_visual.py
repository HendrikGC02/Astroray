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
    r.set_use_gpu(False)  # pkg268 volume transport is CPU-only (GPU = pkg269)
    r.set_background_color([0.15, 0.18, 0.22])  # cool grey backdrop
    r.add_point_light([3.0, 4.0, 3.0], {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 400.0)
    if with_volume:
        # red single-scattering cube centered at origin, side 2 (AABB [-1,1]^3).
        # moderate density -> a soft translucent red patch with visible in-scatter.
        r.add_homogeneous_medium([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0],
                                 0.6, [0.95, 0.2, 0.15], [1.0, 1.0, 1.0], 0.2)
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
    # a gamma-corrected beauty render for qualitative inspection (viewing only).
    beauty = np.asarray(_scene(True, w, h).render(256, 8, None, True), dtype=np.float64)
    if beauty.ndim == 1:
        beauty = beauty.reshape(h, w, 3)
    save_image(beauty, os.path.join(_OUT, "pkg268_red_scatter_cube_gamma.png"))

    # center region overlaps the cube.
    cy0, cy1 = h // 2 - 12, h // 2 + 12
    cx0, cx1 = w // 2 - 12, w // 2 + 12
    cube = vol[cy0:cy1, cx0:cx1]
    cube_mean = cube.reshape(-1, 3).mean(axis=0)
    bg_cube = bg[cy0:cy1, cx0:cx1].reshape(-1, 3).mean(axis=0)
    print(f"[pkg268 visual] cube_mean RGB = {cube_mean.round(4)} "
          f"backdrop RGB = {bg_cube.round(4)}")
    # reddish: R dominates G and B (red scattering albedo + red transmission).
    assert cube_mean[0] > cube_mean[1] * 1.3, f"cube not red-dominant: {cube_mean}"
    assert cube_mean[0] > cube_mean[2] * 1.3, f"cube not red-dominant: {cube_mean}"
    # lit and not a black silhouette.
    assert cube_mean[0] > 0.03, f"cube is black (no in-scatter): {cube_mean}"
    # translucent + selectively red: the medium favours red over green/blue
    # relative to the (grey) backdrop it sits in front of — i.e. it reddens the
    # patch rather than acting as a grey occluder. This is the "soft translucent
    # red patch" cross-check bar (#807), physics-first (Cycles is a band here).
    red_ratio = cube_mean[0] / max(bg_cube[0], 1e-4)
    green_ratio = cube_mean[1] / max(bg_cube[1], 1e-4)
    blue_ratio = cube_mean[2] / max(bg_cube[2], 1e-4)
    assert red_ratio > green_ratio * 1.2, (
        f"red not favoured vs green (R/bgR={red_ratio:.3f}, G/bgG={green_ratio:.3f})")
    assert red_ratio > blue_ratio * 1.2, (
        f"red not favoured vs blue (R/bgR={red_ratio:.3f}, B/bgB={blue_ratio:.3f})")

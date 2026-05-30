"""Kerr black hole (a/M=0.94) with a thin disk, lensing a structured grid sky.

Spin=0.94 BH with a Novikov-Thorne thin disk, viewed against the same
high-contrast equirectangular grid/checker background used by
`gr-schwarzschild` (regenerated locally here so the scene is self-contained).
The escaped camera geodesics sample the env map along their *deflected* exit
direction (raytracer.h: GR `exitDirection` continuation ray), so the straight
grid warps into the classic gravitational-lensing pattern, and on top of it the
gravitationally-lensed disk emission forms a bright photon-sphere ring.

The image shows:
  - a sharp circular dark region (the BH shadow) in the centre
  - a bright photon-sphere ring (lensed thin-disk emission) hugging the shadow
  - the surrounding grid bending into concentric Einstein-ring arcs

Why the structured background (design doc 2026-05-30, owner feedback #1): the
old black-background frame rendered the disk as a featureless white annulus, so
a small lensing regression was lost. The grid makes the lensing + photon ring +
shadow edge crisp and high-contrast, giving SSIM/pHash real structure to lock
onto. This is the distinguished partner of `gr-schwarzschild`: same grid + same
shadow, but the bright disk ring (absent in Schwarzschild) keeps the pair pHash-
distinct and exercises the Kerr metric plugin + disk emission dispatch.

Scene name retains the historical "faceon" suffix for owner-spec alignment.
Regression target: if GR lensing breaks the disk vanishes / the grid renders
flat and unlensed — `bright_coverage` + `dark_disk` + SSIM + pHash all trip.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


NAME = "gr-kerr-94-faceon"
WIDTH = 512
HEIGHT = 512
SAMPLES = 64
MAX_DEPTH = 5
SEED = 17

# Background brightness / film exposure balance: keeps the disk a *defined*
# photon-ring (not a blown-out blob) while the lensed grid stays readable.
_BG_STRENGTH = 0.5
_FILM_EXPOSURE = 0.5

_BG_PATH = Path(__file__).resolve().parent / "background_grid.png"
_BG_W, _BG_H = 3072, 1536


def _ensure_background() -> Path:
    """Write the deterministic high-contrast equirect grid sky if missing.

    Identical generator to `gr-schwarzschild/scene.py` so the pair shares one
    background (kept local here to avoid cross-scene file coupling). Y is the
    polar axis (raytracer.h:EnvironmentMap::lookup equirect convention).
    """
    if _BG_PATH.exists():
        return _BG_PATH
    u = (np.arange(_BG_W) / _BG_W)[None, :] * np.ones((_BG_H, 1))
    v = (np.arange(_BG_H) / _BG_H)[:, None] * np.ones((1, _BG_W))

    nu, nv = 12, 6
    checker = (((u * nu).astype(int) + (v * nv).astype(int)) % 2)
    img = np.empty((_BG_H, _BG_W, 3), np.float32)
    img[checker == 0] = [0.10, 0.12, 0.18]
    img[checker == 1] = [0.16, 0.20, 0.30]

    ng_u, ng_v, lw = 36, 18, 0.040
    gu = (u * ng_u) % 1.0
    gv = (v * ng_v) % 1.0
    fine = (gu < lw) | (gu > 1 - lw) | (gv < lw) | (gv > 1 - lw)
    img[fine] = [0.95, 0.98, 1.00]

    lw2 = 0.013
    cu = (u * nu) % 1.0
    cv = (v * nv) % 1.0
    coarse = (cu < lw2) | (cu > 1 - lw2) | (cv < lw2) | (cv > 1 - lw2)
    img[coarse] = [1.00, 0.66, 0.18]

    out = (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    Image.fromarray(out).save(_BG_PATH)
    return _BG_PATH


def make_scene(astroray):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_seed(SEED)
    r.set_adaptive_sampling(False)
    r.load_environment_map(str(_ensure_background()), _BG_STRENGTH)
    r.set_film_exposure(_FILM_EXPOSURE)

    dist = 12.0
    r.setup_camera(
        [0.0, 0.0, dist], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
        45.0,
        WIDTH / HEIGHT,
        0.0,
        dist,
        WIDTH, HEIGHT,
    )

    r.add_black_hole(
        [0.0, 0.0, 0.0],
        4.0e6,
        5.0,
        {
            "spin": 0.94,
            "disk_outer": 18.0,        # disk extends to ~18 M (Novikov-Thorne)
            "accretion_rate": 1.0,
            "inclination": 78.0,       # near edge-on
            "enable_adaf": False,
            "r_obs_M": 20.0,
        },
    )
    return r

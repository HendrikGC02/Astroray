"""Schwarzschild black hole gravitationally lensing a structured grid sky.

A static, non-rotating BH (spin=0) at the origin with no accretion disk,
viewed against a high-contrast equirectangular grid/checker background. The
escaped camera geodesics sample the environment map along their *deflected*
exit direction (raytracer.h: GR `exitDirection` spawns a continuation ray that
hits the env map), so the straight background grid is warped into the classic
gravitational-lensing pattern:
  - a sharp circular dark region (the BH shadow) in the centre
  - a thin photon ring just outside the shadow where the background grid piles
    up into infinitely-compressed concentric arcs (Einstein-ring structure)
  - the surrounding grid bending continuously toward the shadow edge

Why the structured background (design doc 2026-05-30, owner feedback #1): the
old uniform-white frame was too featureless, so a small lensing regression got
lost. A high-contrast grid makes the shadow edge + photon ring crisp and gives
the SSIM/pHash gates real structure to lock onto — a deflection-map regression
now visibly bends the grid wrongly instead of nudging a flat field.

Regression target: if GR dispatch breaks (geodesic integrator failure, metric
param plumbing bug, etc.) the dark disk vanishes and the grid renders flat and
unlensed — `dark_disk` + SSIM + pHash all trip.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


NAME = "gr-schwarzschild"
WIDTH = 512
HEIGHT = 512
SAMPLES = 64
MAX_DEPTH = 5
SEED = 17

# Equirectangular background asset (gitignored *.png; regenerated deterministically
# on each render so it never needs to be checked in).
_BG_PATH = Path(__file__).resolve().parent / "background_grid.png"
_BG_W, _BG_H = 3072, 1536


def _ensure_background() -> Path:
    """Write a deterministic high-contrast equirect grid sky if missing.

    Two-tone coarse colour checker (large-scale orientation cue) + a finer
    bright-white grid (fine lensed detail near the ring) + warm accent lines on
    the coarse cell borders (the dramatic Einstein-cross arcs). Y is the polar
    axis, matching EnvironmentMap's equirect convention (raytracer.h:lookup).
    """
    if _BG_PATH.exists():
        return _BG_PATH
    u = (np.arange(_BG_W) / _BG_W)[None, :] * np.ones((_BG_H, 1))
    v = (np.arange(_BG_H) / _BG_H)[:, None] * np.ones((1, _BG_W))

    # Coarse colour checker — few large cells so the unlensed sky reads clearly.
    nu, nv = 12, 6
    checker = (((u * nu).astype(int) + (v * nv).astype(int)) % 2)
    img = np.empty((_BG_H, _BG_W, 3), np.float32)
    img[checker == 0] = [0.10, 0.12, 0.18]
    img[checker == 1] = [0.16, 0.20, 0.30]

    # Fine bright grid — carries the fine lensed structure piling up at the ring.
    ng_u, ng_v, lw = 36, 18, 0.040
    gu = (u * ng_u) % 1.0
    gv = (v * ng_v) % 1.0
    fine = (gu < lw) | (gu > 1 - lw) | (gv < lw) | (gv > 1 - lw)
    img[fine] = [0.95, 0.98, 1.00]

    # Warm accent on the coarse-cell borders — the high-contrast Einstein arcs.
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
    r.load_environment_map(str(_ensure_background()), 1.0)

    # pkg107 (implemented 2026-05-27): r_obs_M=20 shrinks the world-to-GR
    # scale 5x vs the previous 100.0 default, growing the visible shadow.
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
            "spin": 0.0,
            "disk_outer": 0.0,
            "accretion_rate": 0.0,
            "inclination": 0.0,
            "enable_adaf": False,
            "r_obs_M": 20.0,
        },
    )
    return r

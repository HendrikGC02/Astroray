"""Schwarzschild black hole shadow against a white background.

A static, non-rotating BH (spin=0) at the origin with no accretion disk,
viewed against a uniform white sky. The image should show:
  - a sharp circular dark region (the BH shadow, ~2.6 R_s in apparent size)
  - a thin lensed ring just outside the shadow (photon ring)
  - white background otherwise

Regression target: if GR dispatch breaks (geodesic integrator failure,
metric param plumbing bug, etc.), the dark disk vanishes and we get a
uniform-white image — `dark_disk` gate fails immediately.
"""

from __future__ import annotations


NAME = "gr-schwarzschild"
WIDTH = 256
HEIGHT = 256
SAMPLES = 16
MAX_DEPTH = 4
SEED = 17


def make_scene(astroray):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([1.0, 1.0, 1.0])
    r.set_seed(SEED)
    r.set_adaptive_sampling(False)

    # pkg107 (implemented 2026-05-27): r_obs_M=20 shrinks the world-to-GR
    # scale 5x vs the previous 100.0 default, growing the visible shadow.
    # At camera dist 12, influence_radius 5, r_obs_M 20:
    #   shadow_angular_radius ≈ 5.196 * 5 / (20 * 12) = 0.108 rad ≈ 6.2°
    #   frame half-width at FOV 45° = 22.5°
    #   shadow occupies ~28% of frame width — substantial visible feature.
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

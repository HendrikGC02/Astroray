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

    dist = 8.0
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
        },
    )
    return r

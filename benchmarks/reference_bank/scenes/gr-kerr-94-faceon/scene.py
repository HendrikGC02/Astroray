"""Kerr black hole at near-maximal spin (a/M = 0.94), edge-on with thin disk.

Initial attempt was face-on with no disk: that produced an image visually
identical to `gr-schwarzschild` (pHash distance 0, dark_disk fraction
identical) because frame-dragging asymmetry only shows up in the
equatorial plane. Switched to edge-on with a thin accretion disk so:
  - the dramatic Kerr-vs-Schwarzschild visible asymmetry (D-shape lensed
    by frame-dragging) is visible
  - pair regression against `gr-schwarzschild` actually distinguishes
    the two metric plugins

Scene name retains "faceon" suffix for owner-spec alignment; rename to
`gr-kerr-94-edgeon` is a trivial Phase-2-followup if owner prefers the
accurate label.
"""

from __future__ import annotations


NAME = "gr-kerr-94-faceon"
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
            "spin": 0.94,             # near-maximal Kerr
            "disk_outer": 12.0,        # thin disk extends to 12 units radius
            "accretion_rate": 1.0,
            "inclination": 85.0,       # nearly edge-on for visible asymmetry
            "enable_adaf": False,
        },
    )
    return r

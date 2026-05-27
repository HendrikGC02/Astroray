"""Phase 2b — Synchrotron jet (M87-like bipolar) scene.

Adapted from `tests/scenes/synchrotron_jet.py` (pkg42) scaled to 256×256
with pkg107's r_obs_M=20.

**Status: Phase 2b (low priority per owner 2026-05-27).** Reference
captured at bless time; gates permissive. The scene exists so the
owner can see what the bipolar jet emission currently looks like.
"""

from __future__ import annotations


NAME = "synchrotron-jet-m87"
WIDTH = 256
HEIGHT = 256
SAMPLES = 32
MAX_DEPTH = 4
SEED = 42


def make_scene(astroray):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(SEED)
    r.set_adaptive_sampling(False)

    r.setup_camera(
        [0.0, 28.0, 70.0],
        [0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        28.0,
        WIDTH / HEIGHT,
        0.0,
        70.0,
        WIDTH, HEIGHT,
    )

    r.add_black_hole(
        [0.0, 0.0, 0.0],
        4.0e6,
        16.0,
        {
            "disk_outer": 30.0,
            "accretion_rate": 0.0,
            "inclination": 45.0,
            "enable_jet": True,
            "lorentz_factor": 5.0,
            "half_angle_degrees": 12.0,
            "power_law_index": 2.5,
            "base_density": 1.0e12,
            "magnetic_field": 1.0e6,
            "intensity_scale": 5.0e13,
            "r_base": 1.0,
            "r_max": 120.0,
            "r_obs_M": 20.0,
        },
    )
    return r

"""Phase 2b — ADAF Sgr A*-like accretion glow scene.

Adapted from `tests/scenes/adaf_sgra.py` (pkg44) scaled up to 256×256
with pkg107's r_obs_M=20 so the BH structure is visible.

**Status: Phase 2b (low priority per owner 2026-05-27).** The reference
is captured at bless time but gates are intentionally permissive — the
scene exists so the owner can SEE what the ADAF emission currently
looks like, not to enforce regression yet. pkg99 documented that ADAF
visual tuning is owner-empirical; this scene gives the bank a captured
target for the future tuning pass.
"""

from __future__ import annotations


NAME = "adaf-sgrA-faceon"
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

    # Camera ~face-on (small inclination from disk plane).
    dist = 70.0
    r.setup_camera(
        [0.0, dist * 0.20, dist * 0.98],   # 11.5° from disk normal
        [0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        24.0,
        WIDTH / HEIGHT,
        0.0,
        dist,
        WIDTH, HEIGHT,
    )

    r.add_black_hole(
        [0.0, 0.0, 0.0],
        4.0e6,                  # Sgr A* mass
        16.0,                   # influence radius in render units
        {
            "spin": 0.9,
            "disk_outer": 0.0,
            "accretion_rate": 0.0,
            "inclination": 11.5,
            "enable_adaf": True,
            "adaf_mdot_edd": 1.0e-8,
            "adaf_electron_temp": 1.0e10,
            "adaf_beta_mag": 0.1,
            "adaf_r_inner": 1.5,
            "adaf_r_outer": 100.0,
            "adaf_flattening": 0.0,
            "adaf_alpha": 0.1,
            "adaf_s": 0.3,
            "adaf_intensity_scale": 1.0e30,
            "r_obs_M": 20.0,
        },
    )
    return r

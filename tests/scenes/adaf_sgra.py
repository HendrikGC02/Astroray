"""pkg44 ADAF Sgr A*-like scene helper.

Sgr A* parameters:
- M = 4.0e6 M_sun
- mdot/mdot_Edd ≈ 10^-8 (radiatively inefficient)
- T_e ~ 10^10 K at outer boundary
- Observer at 45° inclination
- Observed at 230 GHz (EHT band)

The scene exercises the registered ``adaf`` emitter through the black-hole
GR dispatch. It is intentionally low-resolution to keep CI fast while still
validating the quasi-spherical glow and shadow visibility.
"""

from __future__ import annotations


def build_scene(astroray, width: int = 32, height: int = 32):
    """Build Sgr A*-like ADAF scene.

    Returns a renderer configured with:
    - Kerr black hole (a = 0.9, M = 4e6 M_sun)
    - ADAF emitter with Sgr A*-like parameters
    - Camera at 45° inclination, observing at 230 GHz
    """
    renderer = astroray.Renderer()
    renderer.set_integrator("path_tracer")
    renderer.set_seed(42)
    renderer.set_adaptive_sampling(False)

    # Camera: observer at 1e6 M from the black hole, 45° inclination.
    # Field of view spans ~10 Schwarzschild radii at the BH distance.
    # For M = 4e6 M_sun, 1 M_sun = 1.477 km, so M = 5.9e9 km.
    # Observer distance: 1e6 M ~ 5.9e15 km ~ 39 AU (safe from tidal forces).
    # Shadow angular size: ~5 R_S at 1e6 M ~ 10 / 1e6 rad ~ 10 μas.
    # FOV = 40 deg to capture the shadow + surrounding glow.
    renderer.setup_camera(
        [0.0, 1.0e6 * 0.707, 1.0e6 * 0.707],  # 45° from equator
        [0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        40.0,  # FOV degrees
        width / height,
        0.0,
        1.0e6 * 1.414,  # focal distance
        width,
        height,
    )

    renderer.add_black_hole(
        [0.0, 0.0, 0.0],
        4.0e6,  # M = 4e6 M_sun (Sgr A*)
        20.0,   # horizon radius in render units (visual only, not physical)
        {
            "spin": 0.9,            # Kerr a = 0.9 (rapidly rotating)
            "disk_outer": 0.0,       # no thin disk
            "accretion_rate": 0.0,   # no thin disk
            "inclination": 45.0,
            "enable_adaf": True,
            "adaf_mdot_edd": 1.0e-8,  # radiatively inefficient
            "adaf_electron_temp": 1.0e10,  # T_e0 = 10^10 K
            "adaf_beta_mag": 0.1,    # p_mag / p_gas = 0.1
            "adaf_r_inner": 1.5,     # just outside horizon
            "adaf_r_outer": 100.0,   # ~50 Schwarzschild radii
            "adaf_flattening": 0.0,  # spherical (H/r ~ 1)
            "adaf_alpha": 0.1,       # viscosity
            "adaf_s": 0.3,           # outflow exponent
            "adaf_intensity_scale": 1.0e30,  # scale to visible range
        },
    )
    return renderer

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

    # Camera in RENDER units (not physical km/AU). `add_black_hole`'s 3rd
    # arg (20 below) is the BH GR influence-sphere radius in world units —
    # ADAF emission is bounded by that sphere, so the visible structure is
    # ~20 units in radius (NOT the 100 in adaf_r_outer, which is M units).
    # Calibrated to the working synchrotron_jet scene (same M, same GR
    # dispatch: camera dist ~75, FOV 28° for an influence-sphere arg of 16).
    # The old physical 1e6 M observer distance collapsed the whole BH+ADAF
    # to ~0.02 px → flat field. D=75, FOV 30° → ~1.25 render units/px at
    # 32², resolving the quasi-spherical glow and the central dark-silhouette
    # shadow. 45° inclination per spec. FOV 35° gives the ~40-unit glow
    # margin inside the frame (avoids edge-clipping at 30°).
    dist = 75.0
    renderer.setup_camera(
        [0.0, dist * 0.707, dist * 0.707],  # 45° from equator
        [0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        35.0,  # FOV degrees
        width / height,
        0.0,
        dist,  # focal distance ~ distance to target
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

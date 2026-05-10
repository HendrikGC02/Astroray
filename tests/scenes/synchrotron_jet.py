"""pkg42 synchrotron jet scene helper.

The scene is intentionally tiny: it exercises the registered
``synchrotron_jet`` emitter through the black-hole GR dispatch without making
CI depend on a high-sample astrophysical render.
"""

from __future__ import annotations


def build_scene(astroray, width: int = 24, height: int = 24):
    renderer = astroray.Renderer()
    renderer.set_integrator("path_tracer")
    renderer.set_seed(42)
    renderer.set_adaptive_sampling(False)
    renderer.setup_camera(
        [0.0, 28.0, 70.0],
        [0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        28.0,
        width / height,
        0.0,
        70.0,
        width,
        height,
    )
    renderer.add_black_hole(
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
            "intensity_scale": 1.0e28,
            "r_base": 1.0,
            "r_max": 120.0,
        },
    )
    return renderer


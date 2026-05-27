"""SMS refractive caustic — non-dispersive glass sphere + area emitter.

Tests the SMS Newton path-finding for refractive caustics WITHOUT
the per-wavelength complication. Glass is a plain dielectric with
scalar IOR (no sellmeier_preset), so the caustic is achromatic
("white"). Pair with `prism-bk7-collimated` as the regression
distinguisher: that scene catches per-wavelength regressions, this
one catches scalar-IOR path-finding regressions.

Geometry mirrors `tests/scenes/caustic_validation.make_glass_caustic_scene`.
"""

from __future__ import annotations


NAME = "sms-refractive-glass-sphere"
WIDTH = 384
HEIGHT = 256
SAMPLES = 1024
MAX_DEPTH = 10
SEED = 17


def make_scene(astroray):
    r = astroray.Renderer()
    r.set_background_color([0.02, 0.025, 0.03])

    floor = r.create_material("lambertian", [0.72, 0.72, 0.68], {})
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, -2.2], [2.4, -1.2, 1.6], floor)
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, 1.6], [-2.4, -1.2, 1.6], floor)

    light = r.create_material("light", [1.0, 0.97, 0.90], {"intensity": 12.0})
    r.add_sphere([0.0, 1.55, 1.0], 0.22, light)

    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.52})
    r.add_sphere([0.0, -0.35, 0.15], 0.72, glass)

    r.set_integrator("sms_caustic_path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("caustic_chain_iters", 3)
    r.set_integrator_param("spectral_newton", 0)  # achromatic — scalar IOR path

    r.setup_camera(
        [0.0, 1.2, 3.4], [0.0, -0.8, 0.0], [0.0, 1.0, 0.0],
        38.0, WIDTH / HEIGHT, 0.0, 3.6, WIDTH, HEIGHT)
    return r

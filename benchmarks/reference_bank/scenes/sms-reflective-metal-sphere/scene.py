"""SMS reflective caustic — polished metal sphere + area emitter.

Tests the SMS Newton path-finding for REFLECTIVE caustic chains.
Geometry parallels `sms-refractive-glass-sphere` but with a polished
metal sphere replacing the glass; the resulting caustic on the floor
is the focused reflection rather than refraction.
"""

from __future__ import annotations


NAME = "sms-reflective-metal-sphere"
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

    # Brighter area emitter — reflective caustic from a convex sphere is
    # geometrically diffuse (focal point at infinity behind the sphere),
    # so we need more total flux to make the caustic ring visible.
    light = r.create_material("light", [1.0, 0.97, 0.90], {"intensity": 30.0})
    r.add_sphere([0.0, 1.55, 1.0], 0.30, light)

    metal = r.create_material("metal", [0.95, 0.95, 0.95], {"roughness": 0.02})
    r.add_sphere([0.0, -0.35, 0.15], 0.72, metal)

    r.set_integrator("sms_caustic_path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("caustic_chain_iters", 3)
    r.set_integrator_param("spectral_newton", 0)
    r.set_use_reflective_caustics(True)

    r.setup_camera(
        [0.0, 1.2, 3.4], [0.0, -0.8, 0.0], [0.0, 1.0, 0.0],
        38.0, WIDTH / HEIGHT, 0.0, 3.6, WIDTH, HEIGHT)
    return r

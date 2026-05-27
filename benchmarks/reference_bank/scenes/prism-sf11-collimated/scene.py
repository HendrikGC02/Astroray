"""Spectral-dispersion reference scene — SF11 flint glass caustic.

Identical geometry to `prism-bk7-collimated` but with SF11 flint glass
(IOR 1.785, Abbe 25) replacing BK7 (IOR 1.517, Abbe 64). SF11's higher
dispersion produces a visibly wider chromatic spread, giving us:
  - a stronger signal-to-noise on the hue_spread gate
  - direct A/B value: BK7 vs SF11 outputs should differ measurably
    in the chromatic-band width, catching cases where the sellmeier
    preset dispatch is silently sharing BK7 coefficients across both.

See `../prism-bk7-collimated/notes.md` for why this category uses sphere
geometry rather than triangular prisms.
"""

from __future__ import annotations


NAME = "prism-sf11-collimated"
WIDTH = 384
HEIGHT = 256
SAMPLES = 1024
MAX_DEPTH = 10
SEED = 17


def make_scene(astroray):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])

    floor = r.create_material("lambertian", [0.92, 0.92, 0.92], {})
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, -2.2], [2.4, -1.2, 1.6], floor)
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, 1.6], [-2.4, -1.2, 1.6], floor)

    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 18.0})
    r.add_sphere([0.0, 1.6, 1.0], 0.22, light)

    # SF11 flint glass: higher IOR + higher dispersion (Abbe 25) than BK7 (Abbe 64).
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {
        "sellmeier_preset": "flint_sf11",
    })
    r.add_sphere([0.0, -0.4, 0.15], 0.7, glass)

    r.set_integrator("sms_caustic_path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("caustic_chain_iters", 3)
    r.set_integrator_param("spectral_newton", 1)

    r.setup_camera(
        [0.0, 1.2, 3.4], [0.0, -0.8, 0.0], [0.0, 1.0, 0.0],
        38.0, WIDTH / HEIGHT, 0.0, 3.6, WIDTH, HEIGHT)
    return r

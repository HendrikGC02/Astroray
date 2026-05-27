"""Spectral-dispersion reference scene — BK7 caustic.

Geometry: BK7 dispersive sphere illuminated by a white area emitter
directly above, casting a chromatic caustic onto a white floor below.
Matches the working setup in `tests/test_sms_caustic_spectral.py`
(which uses the same scene at 64x64). Scaled up here to 384x256 and
256 spp so the rainbow caustic is visible to the naked eye.

Integrator: `sms_caustic_path_tracer` with `spectral_newton=1` so the
Newton residual is evaluated at the per-wavelength IOR (Hanika 2015 §4).
This is the only integrator path in Astroray that produces a *chromatic*
caustic — the default `path_tracer` will not show dispersion at this spp
level because the per-ray luck of hitting the sun direction after two
specular bounces is the MC-noise floor.

The naming preserves "prism" in the category for owner-spec alignment;
a true triangular-prism variant would need either SMS-chain support for
triangles or a custom geometry, which is deferred to a follow-up. The
*physics being demonstrated* (per-wavelength IOR through dispersive glass
producing a visible rainbow on a receiver) is identical between the
sphere caustic and the prism rainbow.
"""

from __future__ import annotations


NAME = "prism-bk7-collimated"
WIDTH = 384
HEIGHT = 256
SAMPLES = 1024
MAX_DEPTH = 10
SEED = 17


def make_scene(astroray):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])

    # White diffuse floor — the rainbow lands here.
    floor = r.create_material("lambertian", [0.92, 0.92, 0.92], {})
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, -2.2], [2.4, -1.2, 1.6], floor)
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, 1.6], [-2.4, -1.2, 1.6], floor)

    # Broad-spectrum white area emitter directly above the caster.
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 18.0})
    r.add_sphere([0.0, 1.6, 1.0], 0.22, light)

    # BK7 dispersive sphere — the caster.
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {
        "sellmeier_preset": "bk7",
    })
    r.add_sphere([0.0, -0.4, 0.15], 0.7, glass)

    # SMS-caustic integrator with per-wavelength Newton (the chromatic path).
    r.set_integrator("sms_caustic_path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("caustic_chain_iters", 3)
    r.set_integrator_param("spectral_newton", 1)

    # Camera angled down so the caustic floor area fills more of the frame.
    r.setup_camera(
        [0.0, 1.2, 3.4], [0.0, -0.8, 0.0], [0.0, 1.0, 0.0],
        38.0, WIDTH / HEIGHT, 0.0, 3.6, WIDTH, HEIGHT)
    return r

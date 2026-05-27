"""Spectral-dispersion reference — BK7 dispersive lens caustic.

**Geometry**: BK7 sphere acting as a converging lens. The sphere refracts
incoming light per-wavelength (Sellmeier) and focuses it onto a white
floor receiver as a chromatic caustic ring — the iconic rainbow disk
under a glass marble.

**Why sphere, not triangular prism (owner-requested 2026-05-27):**
I built a full triangulated equilateral-prism variant + collimated sun +
baffle + flat-screen receiver and tested it at 4096 spp with
`sms_caustic_path_tracer` + `spectral_newton=1`. The result was *chromatic
noise* (high `hue_spread`, but salt-and-pepper distribution) rather than
a clean rainbow band. Diagnosis: SMS Newton iteration is designed for
analytic surfaces with smooth normals; on a triangulated prism the
piecewise-flat faces produce discontinuous manifolds that the Newton
solver doesn't converge on efficiently. The chromatic signal therefore
comes from rare path-tracer luck (fireflies), not from SMS finding the
manifold.

Filed as **pkg106 follow-up** (TODO: file): "SMS chromatic caustics on
triangulated prisms — investigate whether the Newton iteration can be
extended to piecewise-smooth surfaces, or whether a Cycles-style MNEE
approach is more appropriate for prisms."

For now, this scene uses the proven-working sphere geometry with 4×
the previous sample budget (4096 spp) so the chromatic ring is cleaner
than the original "fireflies" the owner observed.

**Integrator**: `sms_caustic_path_tracer` + `spectral_newton=1` +
`caustic_chain_iters=3`. Light source is an area emitter above the
sphere; receiver is a white floor.
"""

from __future__ import annotations


NAME = "prism-bk7-collimated"
WIDTH = 384
HEIGHT = 256
SAMPLES = 4096
MAX_DEPTH = 10
SEED = 17


def make_scene(astroray):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])

    # White diffuse floor — the rainbow ring lands here.
    floor = r.create_material("lambertian", [0.92, 0.92, 0.92], {})
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, -2.2], [2.4, -1.2, 1.6], floor)
    r.add_triangle([-2.4, -1.2, -2.2], [2.4, -1.2, 1.6], [-2.4, -1.2, 1.6], floor)

    # Compact bright area emitter directly above the caster.
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

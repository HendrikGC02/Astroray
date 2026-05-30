"""Spectral-dispersion reference — BK7 triangulated-prism rainbow caustic.

**Geometry**: a triangulated equilateral BK7 prism (two refracting faces, each a
finite quad = 2 triangles, flagged as caustic casters), a collimated "sun"
(distant directional light) entering the prism, and a white diffuse floor that
catches the dispersed spectrum. Each wavelength refracts by its own Sellmeier
IOR and lands at a different floor position -> a clean continuous red->violet
rainbow band.

**Why forward light-tracing, not camera-side SMS/MNEE (pkg106 finish, 2026-05-29):**
The original plan refracted the caustic with the camera-side SMS/MNEE integrator.
The full MNEE machinery was implemented and unit-tested (analytic transfer-matrix
geometry term, positional + collimated branches, caster-aimed seed — see
include/astroray/manifold/ and tests/test_mnee_*.py), and it does produce a
*localized dispersive* caustic. But a flat prism does not focus: its dispersion
is weak and the camera-side specular connection is a near-delta whose Newton
basin is spatially chaotic, so the result is salt-and-pepper chromatic noise that
does not clean up with samples (deterministic structure). A prism rainbow is a
forward light-transport phenomenon, so this scene uses the `light_tracer_caustic`
integrator (Arvo 1986 backward ray tracing / Jensen 1996 photon deposition):
wavelengths are traced FROM the sun through the prism and deposited on the floor,
giving a smooth spectrum with no specular-connection noise. The MNEE math remains
for genuinely focusing casters (lenses, spheres).

**Integrator**: `light_tracer_caustic` (CPU forward light-tracer; the caustic is
baked in beginFrame so the camera pass needs few samples).
"""

from __future__ import annotations

import math


NAME = "prism-bk7-collimated"
WIDTH = 512
HEIGHT = 512
SAMPLES = 96
MAX_DEPTH = 8
SEED = 17


def _norm(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v]


def _quad_from_plane(p, n, half_u, half_v):
    """Finite quad on plane(p, n): pick an in-plane (u,v) frame -> 4 CCW corners."""
    n = _norm(n)
    up = [0.0, 1.0, 0.0] if abs(n[1]) < 0.9 else [1.0, 0.0, 0.0]
    d = sum(up[i] * n[i] for i in range(3))
    u = _norm([up[i] - d * n[i] for i in range(3)])
    v = [n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0]]
    def corner(su, sv):
        return [p[i] + su * half_u * u[i] + sv * half_v * v[i] for i in range(3)]
    return [corner(-1, -1), corner(1, -1), corner(1, 1), corner(-1, 1)]


def _add_quad(r, corners, mat):
    i0 = r.scene_object_count()
    a, b, c, d = corners
    r.add_triangle(a, b, c, mat)
    r.add_triangle(a, c, d, mat)
    return [i0, i0 + 1]


def make_scene(astroray):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])

    # BK7 dispersive prism — two refracting faces of an equilateral prism
    # (60deg dihedral, apex +y), each a finite quad flagged as a caustic caster.
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"sellmeier_preset": "bk7"})
    apex_y, base_y, half_v = 0.5, -0.5, 0.7
    half = math.radians(30.0)
    bx = (apex_y - base_y) * math.tan(half)
    cy = (apex_y + base_y) / 2.0
    faces = [
        ([-bx / 2, cy, 0.0], _norm([-math.cos(half), math.sin(half), 0.0])),  # left
        ([bx / 2, cy, 0.0], _norm([math.cos(half), math.sin(half), 0.0])),    # right
    ]
    casters = []
    for p, n in faces:
        casters += _add_quad(r, _quad_from_plane(p, n, 0.62, half_v), glass)
    for idx in casters:
        r.set_object_caustic_caster(idx, True)

    # Collimated sun: distant directional light travelling +x into the prism.
    r.add_sun_light_dedicated([1.0, 0.0, 0.0], 0.01,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 6.0)

    # White diffuse floor — the dispersed spectrum lands here (beam deviates
    # ~52deg down; lands ~x=1.9 at y=-3).
    floor = r.create_material("lambertian", [0.9, 0.9, 0.9], {})
    _add_quad(r, [[-1.0, -3.0, -2.5], [9.0, -3.0, -2.5], [9.0, -3.0, 2.5], [-1.0, -3.0, 2.5]], floor)

    # Forward light-tracer: bakes the prism caustic onto the floor in beginFrame.
    r.set_integrator("light_tracer_caustic")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("photon_count", 3000000)
    # pkg-integrator-float-param: caustic_boost is now a direct float multiplier
    # (1.2 == the old int-knob 12 x 0.1) routed via set_integrator_param_float.
    r.set_integrator_param_float("caustic_boost", 1.2)

    # Camera zoomed tight onto the rainbow band (pkg104 showcase composition):
    # aim at the band center and narrow the vfov so the continuous red->violet
    # spectrum fills the frame instead of floating small in a wide black field.
    r.setup_camera([2.4, 0.3, 2.9], [2.4, -3.0, 0.1], [0.0, 1.0, 0.0],
                   19.0, WIDTH / HEIGHT, 0.0, 4.0, WIDTH, HEIGHT)
    return r

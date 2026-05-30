"""Focusing-caster caustic — clear glass SPHERE + collimated sun (pkg110).

The pkg106/109 forward light-tracer was prism-specific (a hard-coded 2-face
refraction). pkg110 makes the photon bounce BSDF-driven, so photons traverse ANY
glass shape via the material's sampleSpectral. This scene is the acceptance gate:
a primitive glass *sphere* (a NON-triangle caustic caster the old 2-face code
could not handle) FOCUSES a collimated sun into a concentrated caustic on the
floor — a "burning-glass" spot/cardioid, much brighter than the surrounding
direct-lit floor.

Geometry: a clear ior-1.5 glass sphere flagged as a caustic caster; a distant
collimated sun angled down (+x, -y) so the focused caustic lands on the floor
offset from the sphere (not occluded by it); a white diffuse floor below; camera
looking at the caustic landing zone.

Integrator: `light_tracer_caustic` (forward; caustic baked in beginFrame).
"""

from __future__ import annotations

import math


NAME = "glass-sphere-caustic"
WIDTH = 384
HEIGHT = 288
SAMPLES = 64
MAX_DEPTH = 12
SEED = 17


def _norm(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v]


def _add_quad(r, corners, mat):
    a, b, c, d = corners
    r.add_triangle(a, b, c, mat)
    r.add_triangle(a, c, d, mat)


def make_scene(astroray):
    r = astroray.Renderer()
    r.set_background_color([0.0, 0.0, 0.0])

    # Clear glass sphere (ior 1.5), flagged as a caustic caster. A sphere is a
    # primitive (non-triangle) caster — the pkg110 general BSDF photon loop traces
    # through it via Sphere::hit + dielectric sampleSpectral.
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    sphere_idx = r.scene_object_count()
    r.add_sphere([0.0, 0.0, 0.0], 0.6, glass)
    r.set_object_caustic_caster(sphere_idx, True)

    # Distant collimated sun, angled down and +x so the focused caustic lands on
    # the floor at ~x=+0.7 (offset from the sphere at the origin).
    r.add_sun_light_dedicated(_norm([0.45, -1.0, 0.0]), 0.01,
                              {"mode": "rgb", "color": [1.0, 1.0, 1.0]}, 6.0)

    # White diffuse floor below the sphere.
    floor = r.create_material("lambertian", [0.85, 0.85, 0.85], {})
    _add_quad(r, [[-3.0, -1.6, -3.0], [4.0, -1.6, -3.0],
                  [4.0, -1.6, 3.0], [-3.0, -1.6, 3.0]], floor)

    r.set_integrator("light_tracer_caustic")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("photon_count", 3000000)
    # Direct float brightness multiplier (pkg-integrator-float-param route).
    r.set_integrator_param_float("caustic_boost", 1.4)

    # Camera looks at the caustic landing zone (~x=0.7 on the floor).
    r.setup_camera([0.7, 1.1, 3.2], [0.7, -1.6, 0.0], [0.0, 1.0, 0.0],
                   42.0, WIDTH / HEIGHT, 0.0, 3.6, WIDTH, HEIGHT)
    return r

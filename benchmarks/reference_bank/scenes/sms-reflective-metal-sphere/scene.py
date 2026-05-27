"""SMS reflective caustic — coffee-cup interior (concave reflector).

Replaces the previous convex-metal-sphere scene per owner feedback
2026-05-27: a convex sphere doesn't focus light — it disperses it.
A reflective caustic needs a *concave* reflector.

Geometry: a vertical metallic cylinder (a coffee-cup interior) open at
the top, closed at the bottom with a metal floor. Camera looks down
into the cup at a steep angle so the inside walls + floor fill the
frame. An area emitter is placed at the rim of one side; light
bounces off the curved interior and focuses as a bright crescent
caustic on the opposite-side wall + cup floor.

Path topology (the classical coffee-mug caustic):
  emitter at rim → opposite inside wall → focused reflection → near
  inside wall (the caustic crescent) → camera.

The cylinder is triangulated with N=32 segments. The inside surface
is "polished metal" with low roughness so the SMS Newton iteration
finds the reflective manifold despite the discontinuous-normal
piecewise-flat approximation; the smoothness benefit of using many
segments outweighs the per-segment normal discontinuities here.
"""

from __future__ import annotations

import math


NAME = "sms-reflective-metal-sphere"
WIDTH = 384
HEIGHT = 256
SAMPLES = 1024
MAX_DEPTH = 10
SEED = 17

N_SEGMENTS = 32
RADIUS = 1.0
HEIGHT_CUP = 1.6


def _add_cup_walls(r, mat):
    """Triangulated open-top cylinder (axis Y), radius R, height H.
    Closed at the bottom with a disk (triangle fan)."""
    out_ids = []
    y0, y1 = -HEIGHT_CUP / 2, +HEIGHT_CUP / 2

    # Side wall: 32 vertical segments.
    for i in range(N_SEGMENTS):
        a0 = i * 2 * math.pi / N_SEGMENTS
        a1 = (i + 1) * 2 * math.pi / N_SEGMENTS
        x0, z0 = RADIUS * math.cos(a0), RADIUS * math.sin(a0)
        x1, z1 = RADIUS * math.cos(a1), RADIUS * math.sin(a1)
        # Two triangles per segment, wound so the OUTWARD-from-axis face is on
        # the cup's OUTSIDE. Reflection works on whichever side the ray hits.
        v00 = [x0, y0, z0]; v10 = [x1, y0, z1]
        v01 = [x0, y1, z0]; v11 = [x1, y1, z1]
        r.add_triangle(v00, v10, v11, mat)
        out_ids.append(r.scene_object_count() - 1)
        r.add_triangle(v00, v11, v01, mat)
        out_ids.append(r.scene_object_count() - 1)

    # Bottom disk (triangle fan from centre).
    c = [0.0, y0, 0.0]
    for i in range(N_SEGMENTS):
        a0 = i * 2 * math.pi / N_SEGMENTS
        a1 = (i + 1) * 2 * math.pi / N_SEGMENTS
        x0, z0 = RADIUS * math.cos(a0), RADIUS * math.sin(a0)
        x1, z1 = RADIUS * math.cos(a1), RADIUS * math.sin(a1)
        r.add_triangle(c, [x0, y0, z0], [x1, y0, z1], mat)
        out_ids.append(r.scene_object_count() - 1)
    return out_ids


def make_scene(astroray):
    r = astroray.Renderer()
    r.set_background_color([0.02, 0.025, 0.03])

    # Outer floor (so the cup isn't floating in void).
    floor_mat = r.create_material("lambertian", [0.30, 0.30, 0.32], {})
    r.add_triangle([-4, -HEIGHT_CUP / 2 - 0.001, -4],
                   [ 4, -HEIGHT_CUP / 2 - 0.001, -4],
                   [ 4, -HEIGHT_CUP / 2 - 0.001,  4], floor_mat)
    r.add_triangle([-4, -HEIGHT_CUP / 2 - 0.001, -4],
                   [ 4, -HEIGHT_CUP / 2 - 0.001,  4],
                   [-4, -HEIGHT_CUP / 2 - 0.001,  4], floor_mat)

    # Cup body: polished metal, low roughness so reflections focus.
    metal = r.create_material("metal", [0.96, 0.96, 0.96], {"roughness": 0.03})
    cup_ids = _add_cup_walls(r, metal)

    # Area emitter at the rim on the +X side, positioned so it shines
    # ACROSS the cup interior toward the -X inside wall.
    light_mat = r.create_material("light", [1.0, 0.97, 0.92], {"intensity": 35.0})
    light_x = 0.92 * RADIUS    # just inside the rim on +X side
    light_y = HEIGHT_CUP / 2 - 0.05
    light_r = 0.16
    r.add_sphere([light_x, light_y, 0.0], light_r, light_mat)

    # SMS-caustic integrator. Reflective branch enabled.
    r.set_integrator("sms_caustic_path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("caustic_chain_iters", 3)
    r.set_integrator_param("spectral_newton", 0)
    r.set_use_reflective_caustics(True)
    for oid in cup_ids:
        r.set_object_caustic_caster(oid, True)

    # Camera: high front-quarter view looking down into the cup.
    r.setup_camera(
        look_from=[2.4, 2.4, 2.4],
        look_at=[0.0, -0.2, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=34.0,
        aspect_ratio=WIDTH / HEIGHT,
        aperture=0.0,
        focus_dist=3.6,
        width=WIDTH,
        height=HEIGHT,
    )
    return r

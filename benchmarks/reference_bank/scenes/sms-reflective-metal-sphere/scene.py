"""SMS reflective caustic — coffee-cup interior (concave reflector).

Replaces the previous convex-metal-sphere scene per owner feedback
2026-05-27: a convex sphere doesn't focus light — it disperses it.
A reflective caustic needs a *concave* reflector.

Geometry: a vertical metallic cylinder (a coffee-cup interior) open at
the top, closed at the bottom with a matte disk. The camera looks
steeply DOWN into the cup so the inside walls + the bottom — where the
focused reflective caustic crescent lands — fill and center the frame.
A distant area emitter is placed high and off to one side; light
bounces off the curved metal interior and focuses as a bright nephroid
crescent on the matte bottom — the classical coffee-mug caustic.

Path topology:
  emitter (high, off-axis) → inside wall → focused reflection →
  matte bottom (the caustic crescent) → camera.

The cylinder is triangulated with N segments but carries SMOOTH
per-vertex (radial) normals so it shades as a continuous curved
surface — not a faceted polygon — which both reads as a proper cup and
helps the reflective focus stay clean (per the 2026-05-30
reference-bank polish, fix #2). The bottom is a separate MATTE diffuse
material so the focused reflective caustic actually lands on a receiver
and reads as a bright crescent (an all-metal bottom would re-reflect
the focus away and the crescent would be invisible).
"""

from __future__ import annotations

import math


NAME = "sms-reflective-metal-sphere"
WIDTH = 512
HEIGHT = 512
SAMPLES = 2048
MAX_DEPTH = 10
SEED = 17

N_SEGMENTS = 64
RADIUS = 1.0
HEIGHT_CUP = 1.6


def _add_cup_walls(r, wall_mat, floor_mat):
    """Triangulated open-top cylinder (axis Y), radius R, height H.

    Returns (wall_ids, floor_ids). The SIDE WALL is polished metal with
    SMOOTH per-vertex (radial) normals — it is the concave reflector that
    focuses the light, and the only caustic caster. The BOTTOM DISK is a
    matte diffuse floor (its own material) so the focused reflective
    caustic actually LANDS on a diffuse receiver and reads as a bright
    crescent — the classic coffee-mug nephroid: shiny walls, matte
    bottom."""
    wall_ids = []
    floor_ids = []
    y0, y1 = -HEIGHT_CUP / 2, +HEIGHT_CUP / 2

    # Side wall: N vertical segments. The smooth per-vertex normal is the
    # outward radial direction (cos a, 0, sin a); the renderer flips it to
    # face the incoming ray, so the inside reflection is unaffected. With
    # interpolated radial normals across each facet the wall shades as a
    # continuous cylinder instead of N flat facets.
    for i in range(N_SEGMENTS):
        a0 = i * 2 * math.pi / N_SEGMENTS
        a1 = (i + 1) * 2 * math.pi / N_SEGMENTS
        c0, s0 = math.cos(a0), math.sin(a0)
        c1, s1 = math.cos(a1), math.sin(a1)
        x0, z0 = RADIUS * c0, RADIUS * s0
        x1, z1 = RADIUS * c1, RADIUS * s1
        n0 = [c0, 0.0, s0]
        n1 = [c1, 0.0, s1]
        v00 = [x0, y0, z0]; v10 = [x1, y0, z1]
        v01 = [x0, y1, z0]; v11 = [x1, y1, z1]
        # tri A: v00, v10, v11  -> normals n0, n1, n1
        r.add_triangle(v00, v10, v11, wall_mat, n0=n0, n1=n1, n2=n1)
        wall_ids.append(r.scene_object_count() - 1)
        # tri B: v00, v11, v01  -> normals n0, n1, n0
        r.add_triangle(v00, v11, v01, wall_mat, n0=n0, n1=n1, n2=n0)
        wall_ids.append(r.scene_object_count() - 1)

    # Bottom disk (triangle fan from centre) — flat matte receiver.
    c = [0.0, y0, 0.0]
    for i in range(N_SEGMENTS):
        a0 = i * 2 * math.pi / N_SEGMENTS
        a1 = (i + 1) * 2 * math.pi / N_SEGMENTS
        x0, z0 = RADIUS * math.cos(a0), RADIUS * math.sin(a0)
        x1, z1 = RADIUS * math.cos(a1), RADIUS * math.sin(a1)
        r.add_triangle(c, [x0, y0, z0], [x1, y0, z1], floor_mat)
        floor_ids.append(r.scene_object_count() - 1)
    return wall_ids, floor_ids


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

    # Cup body: polished-metal side wall (the concave reflector) + a matte
    # diffuse bottom so the focused reflective caustic lands on a receiver.
    metal = r.create_material("metal", [0.96, 0.96, 0.96], {"roughness": 0.03})
    cup_floor = r.create_material("lambertian", [0.62, 0.60, 0.58], {})
    wall_ids, floor_ids = _add_cup_walls(r, metal, cup_floor)

    # Area emitter placed HIGH and OFF-AXIS on the +X side (well above the
    # rim and outside the cup), so it shines down ACROSS the interior. Moving
    # it off the rim (it previously sat at light_y ~= 0.75 of the cup height)
    # keeps it out of frame and makes the focused crescent the hero, not the
    # lamp.
    light_mat = r.create_material("light", [1.0, 0.97, 0.92], {"intensity": 200.0})
    light_x = 1.7 * RADIUS
    light_y = HEIGHT_CUP / 2 + 2.6
    light_r = 0.3
    r.add_sphere([light_x, light_y, 0.0], light_r, light_mat)

    # SMS-caustic integrator. Reflective branch enabled.
    r.set_integrator("sms_caustic_path_tracer")
    r.set_integrator_param("max_depth", MAX_DEPTH)
    r.set_integrator_param("caustic_chain_iters", 3)
    r.set_integrator_param("spectral_newton", 0)
    r.set_use_reflective_caustics(True)
    for oid in wall_ids:
        r.set_object_caustic_caster(oid, True)

    # Camera: high on the -X side (opposite the light), looking steeply DOWN
    # into the cup so the inside walls + the matte bottom — where the focused
    # reflective caustic crescent lands — fill and center the frame. The sight
    # line clears the near rim and reaches the far inside wall and floor.
    r.setup_camera(
        look_from=[-1.45, 3.7, 0.0],
        look_at=[0.0, -0.55, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=35.0,
        aspect_ratio=WIDTH / HEIGHT,
        aperture=0.0,
        focus_dist=4.5,
        width=WIDTH,
        height=HEIGHT,
    )
    return r

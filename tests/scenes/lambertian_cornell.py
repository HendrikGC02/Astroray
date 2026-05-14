"""pkg55 Phase B' Session 2 — Lambertian-only Cornell box.

Test scene for the CPU wavefront reference oracle harness. Intentionally
narrow scope: only Lambertian BSDFs + one emissive area light. No metal,
no dielectric, no Disney, no env map. This is the feature surface the
Session 2 CPU wavefront and both reference path tracers cover.

The reference PTs (`reference_pt_production`, `reference_pt_wavefront`) and
the CPU wavefront driver MUST refuse to render any scene containing a
material outside the {lambertian, diffuse_light} set; this scene is the
in-scope reference.

Layout: classic Cornell box — 6 walls + 1 Lambertian sphere + 1 ceiling
area light. White walls, red left, green right, neutral floor/ceiling.
"""


def build_scene(renderer):
    """Populate *renderer* with the Lambertian Cornell scene.

    Returns the material id map. Caller may set the seed / integrator / spp.
    """
    white_id = renderer.create_material("lambertian", [0.73, 0.73, 0.73], {})
    red_id   = renderer.create_material("lambertian", [0.65, 0.05, 0.05], {})
    green_id = renderer.create_material("lambertian", [0.12, 0.45, 0.15], {})
    sphere_id = renderer.create_material("lambertian", [0.55, 0.55, 0.85], {})
    light_id = renderer.create_material("light", [1.0, 1.0, 1.0], {"intensity": 8.0})

    S = 1.0  # half-extent of the box
    # Floor (white)
    renderer.add_triangle([-S, -S, -S], [ S, -S, -S], [ S, -S,  S], white_id)
    renderer.add_triangle([-S, -S, -S], [ S, -S,  S], [-S, -S,  S], white_id)
    # Ceiling (white)
    renderer.add_triangle([-S,  S, -S], [ S,  S,  S], [ S,  S, -S], white_id)
    renderer.add_triangle([-S,  S, -S], [-S,  S,  S], [ S,  S,  S], white_id)
    # Back wall (white)
    renderer.add_triangle([-S, -S, -S], [ S,  S, -S], [ S, -S, -S], white_id)
    renderer.add_triangle([-S, -S, -S], [-S,  S, -S], [ S,  S, -S], white_id)
    # Left wall (red)
    renderer.add_triangle([-S, -S, -S], [-S, -S,  S], [-S,  S,  S], red_id)
    renderer.add_triangle([-S, -S, -S], [-S,  S,  S], [-S,  S, -S], red_id)
    # Right wall (green)
    renderer.add_triangle([ S, -S, -S], [ S,  S,  S], [ S, -S,  S], green_id)
    renderer.add_triangle([ S, -S, -S], [ S,  S, -S], [ S,  S,  S], green_id)
    # Front wall (white) — closes the box behind the camera. Camera sits inside
    # the box at z = +0.95 looking toward -z, so the front wall acts only as a
    # bounce surface for indirect light, not as an occluder of the primary ray.
    renderer.add_triangle([-S, -S,  S], [ S, -S,  S], [ S,  S,  S], white_id)
    renderer.add_triangle([-S, -S,  S], [ S,  S,  S], [-S,  S,  S], white_id)

    # Lambertian sphere (slightly off-centre)
    renderer.add_sphere([0.3, -0.55, 0.1], 0.45, sphere_id)

    # Ceiling area light (just below the ceiling)
    LY = S - 0.001
    LH = 0.3
    renderer.add_triangle([-LH, LY, -LH], [ LH, LY, -LH], [ LH, LY,  LH], light_id)
    renderer.add_triangle([-LH, LY, -LH], [ LH, LY,  LH], [-LH, LY,  LH], light_id)

    return dict(white=white_id, red=red_id, green=green_id,
                sphere=sphere_id, light=light_id)


def setup_camera(renderer, width=64, height=64):
    renderer.setup_camera(
        look_from=[0, 0.0, 0.95], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=60, aspect_ratio=width / height,
        aperture=0.0, focus_dist=1.0,
        width=width, height=height,
    )
    renderer.set_background_color([0.0, 0.0, 0.0])

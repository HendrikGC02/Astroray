"""pkg55 Phase B' Session 3 — Metal + Lambertian Cornell box.

Test scene for the CPU wavefront Session 3 expansion. Extends the
Lambertian-Cornell base with a metal sphere, adding GGX conductor BSDF
to the growing-oracle feature surface.

Scope: Lambertian BSDFs + metal (GGX conductor) + emissive area light.
No dielectric, no Disney, no env map.

The reference PTs and the CPU wavefront driver now cover
{lambertian, metal, diffuse_light}. This scene validates that Session 3's
metal support achieves bit-identity CPU↔CPU.

Layout: classic Cornell box — 6 walls + 1 Lambertian sphere + 1 metal
sphere + 1 ceiling area light. White walls, red left, green right,
neutral floor/ceiling.
"""


def build_scene(renderer):
    """Populate *renderer* with the Metal + Lambertian Cornell scene.

    Returns the material id map. Caller may set the seed / integrator / spp.
    """
    white_id = renderer.create_material("lambertian", [0.73, 0.73, 0.73], {})
    red_id   = renderer.create_material("lambertian", [0.65, 0.05, 0.05], {})
    green_id = renderer.create_material("lambertian", [0.12, 0.45, 0.15], {})
    lamb_sphere_id = renderer.create_material("lambertian", [0.55, 0.55, 0.85], {})

    # Session 3 addition: metal sphere (GGX conductor, moderate roughness).
    # Roughness = 0.15 keeps it non-delta (kNearDeltaThreshold = 0.1), so NEE
    # is active. Albedo = gold-ish color.
    metal_sphere_id = renderer.create_material("metal",
                                                [0.95, 0.71, 0.29],
                                                {"roughness": 0.15})

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
    # Front wall (white) — closes the box behind the camera.
    renderer.add_triangle([-S, -S,  S], [ S, -S,  S], [ S,  S,  S], white_id)
    renderer.add_triangle([-S, -S,  S], [ S,  S,  S], [-S,  S,  S], white_id)

    # Lambertian sphere (left side, slightly off-centre)
    renderer.add_sphere([0.3, -0.55, 0.1], 0.45, lamb_sphere_id)

    # Metal sphere (right side, smaller, elevated) — Session 3 addition.
    renderer.add_sphere([-0.35, -0.4, 0.15], 0.3, metal_sphere_id)

    # Ceiling area light (just below the ceiling)
    LY = S - 0.001
    LH = 0.3
    renderer.add_triangle([-LH, LY, -LH], [ LH, LY, -LH], [ LH, LY,  LH], light_id)
    renderer.add_triangle([-LH, LY, -LH], [ LH, LY,  LH], [-LH, LY,  LH], light_id)

    return dict(white=white_id, red=red_id, green=green_id,
                lamb_sphere=lamb_sphere_id, metal_sphere=metal_sphere_id,
                light=light_id)


def setup_camera(renderer, width=64, height=64):
    renderer.setup_camera(
        look_from=[0, 0.0, 0.95], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=60, aspect_ratio=width / height,
        aperture=0.0, focus_dist=1.0,
        width=width, height=height,
    )
    renderer.set_background_color([0.0, 0.0, 0.0])

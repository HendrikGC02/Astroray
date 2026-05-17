"""pkg55 Phase B' Session 8 — Closure Graph (closure_matte) + Diffuse Light + Thin Glass + Disney + Dielectric + Metal + Lambertian Cornell box.

Test scene for the CPU wavefront Session 8 expansion. Extends the
diffuse_light_cornell base with a closure_matte sphere, adding
closure-graph-based materials to the growing-oracle feature surface.

Scope: Lambertian BSDFs + metal (GGX conductor) + dielectric (glass) + disney
       + thin_glass + diffuse_light (pure emissive, no BSDF) + closure_matte
       (closure-graph-based diffuse).
No env map.

The reference PTs and the CPU wavefront driver now cover
{lambertian, metal, dielectric, disney, thin_glass, diffuse_light, closure_matte}.
This scene validates that Session 8's closure_matte support (closure-graph-based
diffuse material) achieves bit-identity CPU↔CPU.

Layout: classic Cornell box — 6 walls + 1 Lambertian sphere + 1 metal
sphere + 1 dielectric sphere + 1 disney sphere + 1 thin_glass sphere
+ 1 diffuse_light emissive sphere + 1 closure_matte sphere + 1 ceiling area light.
White walls, red left, green right, neutral floor/ceiling.
"""


def build_scene(renderer):
    """Populate *renderer* with the Closure Graph + Diffuse Light + Thin Glass + Disney + Dielectric + Metal + Lambertian Cornell scene.

    Returns the material id map. Caller may set the seed / integrator / spp.
    """
    white_id = renderer.create_material("lambertian", [0.73, 0.73, 0.73], {})
    red_id   = renderer.create_material("lambertian", [0.65, 0.05, 0.05], {})
    green_id = renderer.create_material("lambertian", [0.12, 0.45, 0.15], {})
    lamb_sphere_id = renderer.create_material("lambertian", [0.55, 0.55, 0.85], {})

    # Session 3 addition: metal sphere (GGX conductor, moderate roughness).
    metal_sphere_id = renderer.create_material("metal",
                                                [0.95, 0.71, 0.29],
                                                {"roughness": 0.15})

    # Session 4 addition: dielectric sphere (glass, IOR 1.5).
    dielectric_sphere_id = renderer.create_material("dielectric",
                                                     [1.0, 1.0, 1.0],
                                                     {"ior": 1.5})

    # Session 5 addition: disney sphere (moderate roughness, some metallic/specular, non-delta).
    disney_sphere_id = renderer.create_material("disney",
                                                 [0.8, 0.3, 0.2],
                                                 {"metallic": 0.3,
                                                  "roughness": 0.4,
                                                  "specular": 0.6})

    # Session 6 addition: thin_glass sphere (tinted green-ish, IOR 1.45, low roughness).
    thin_glass_sphere_id = renderer.create_material("thin_glass",
                                                     [0.9, 1.0, 0.9],
                                                     {"ior": 1.45,
                                                      "roughness": 0.05,
                                                      "transmission": 0.95})

    # Session 7 addition: diffuse_light emissive sphere (pure emission, no BSDF).
    # Warm orange emission, moderate intensity. This is distinct from the area light
    # triangles — it's a sphere that emits but has no scattering BSDF.
    diffuse_light_sphere_id = renderer.create_material("diffuse_light",
                                                        [1.0, 0.7, 0.4],
                                                        {"intensity": 3.0})

    # Session 8 addition: closure_matte sphere (closure-graph-based diffuse).
    # This validates that materials using the closure-graph mechanism (not a
    # hardcoded GPU type name) work correctly in the wavefront.
    closure_matte_sphere_id = renderer.create_material("closure_matte",
                                                        [0.2, 0.65, 0.9],
                                                        {})

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

    # Dielectric sphere (center-back, mid-sized) — Session 4 addition.
    renderer.add_sphere([0.0, -0.6, -0.4], 0.35, dielectric_sphere_id)

    # Disney sphere (left-back, small, elevated) — Session 5 addition.
    renderer.add_sphere([0.4, -0.3, -0.3], 0.25, disney_sphere_id)

    # Thin glass sphere (right-front, small, low) — Session 6 addition.
    renderer.add_sphere([-0.45, -0.7, 0.35], 0.25, thin_glass_sphere_id)

    # Diffuse light emissive sphere (center-front, small, slightly elevated) — Session 7 addition.
    # This is the key addition: an emissive sphere that terminates paths on hit
    # (no BSDF continuation).
    renderer.add_sphere([0.0, -0.5, 0.5], 0.2, diffuse_light_sphere_id)

    # Closure matte sphere (left-front, small, elevated) — Session 8 addition.
    # This validates closure-graph-based materials in the wavefront.
    renderer.add_sphere([-0.5, -0.35, 0.45], 0.2, closure_matte_sphere_id)

    # Ceiling area light (just below the ceiling)
    LY = S - 0.001
    LH = 0.3
    renderer.add_triangle([-LH, LY, -LH], [ LH, LY, -LH], [ LH, LY,  LH], light_id)
    renderer.add_triangle([-LH, LY, -LH], [ LH, LY,  LH], [-LH, LY,  LH], light_id)

    return dict(white=white_id, red=red_id, green=green_id,
                lamb_sphere=lamb_sphere_id, metal_sphere=metal_sphere_id,
                dielectric_sphere=dielectric_sphere_id, disney_sphere=disney_sphere_id,
                thin_glass_sphere=thin_glass_sphere_id,
                diffuse_light_sphere=diffuse_light_sphere_id,
                closure_matte_sphere=closure_matte_sphere_id, light=light_id)


def setup_camera(renderer, width=64, height=64):
    renderer.setup_camera(
        look_from=[0, 0.0, 0.95], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=60, aspect_ratio=width / height,
        aperture=0.0, focus_dist=1.0,
        width=width, height=height,
    )
    renderer.set_background_color([0.0, 0.0, 0.0])

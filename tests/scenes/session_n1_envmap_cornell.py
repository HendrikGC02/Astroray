"""pkg55 Phase B' Session N+1 — env-map Cornell test scene.

Cornell box with a mix of all 7 material types (lambertian, metal, dielectric,
disney, thin_glass, diffuse_light, closure_graph) PLUS an environment map
(sky gradient by default, or solid color if set_background_color is called).

This scene exercises env-map miss handling — rays that escape the box should
accumulate environment radiance, matching production pathTraceSpectral.
"""


def build_scene(renderer):
    """Populate *renderer* with a mixed-material Cornell box + env map.

    Returns the material id map.
    """
    # All 7 material types (matching Session 8 scope).
    lambertian_id = renderer.create_material("lambertian", [0.73, 0.73, 0.73], {})
    metal_id = renderer.create_material("metal", [0.92, 0.78, 0.35],
                                        {"roughness": 0.15})
    dielectric_id = renderer.create_material("dielectric", [1.0, 1.0, 1.0],
                                             {"ior": 1.5})
    disney_id = renderer.create_material("disney", [0.8, 0.2, 0.3],
                                         {"metallic": 0.3, "roughness": 0.4,
                                          "specular": 0.6})
    thin_glass_id = renderer.create_material("thin_glass", [0.9, 1.0, 0.95],
                                             {"ior": 1.45, "roughness": 0.05,
                                              "transmission": 0.95})
    diffuse_light_id = renderer.create_material("diffuse_light", [1.0, 0.8, 0.5],
                                                {"intensity": 3.0})
    # Closure graph — closure_matte (blue-tinted diffuse).
    closure_matte_id = renderer.create_material("closure_matte", [0.2, 0.65, 0.9], {})

    # Cornell box walls (leave top open so rays can miss to env map).
    # Floor — lambertian
    renderer.add_triangle([-1, -1, -1], [ 1, -1, -1], [ 1, -1,  1], lambertian_id)
    renderer.add_triangle([-1, -1, -1], [ 1, -1,  1], [-1, -1,  1], lambertian_id)
    # Left wall — metal
    renderer.add_triangle([-1, -1, -1], [-1, -1,  1], [-1,  1,  1], metal_id)
    renderer.add_triangle([-1, -1, -1], [-1,  1,  1], [-1,  1, -1], metal_id)
    # Right wall — dielectric
    renderer.add_triangle([ 1, -1, -1], [ 1,  1, -1], [ 1,  1,  1], dielectric_id)
    renderer.add_triangle([ 1, -1, -1], [ 1,  1,  1], [ 1, -1,  1], dielectric_id)
    # Back wall — disney
    renderer.add_triangle([-1, -1, -1], [-1,  1, -1], [ 1,  1, -1], disney_id)
    renderer.add_triangle([-1, -1, -1], [ 1,  1, -1], [ 1, -1, -1], disney_id)
    # NO CEILING — leave top open so camera rays looking up will miss to env.

    # Spheres (mix of materials).
    # Left sphere — thin_glass
    renderer.add_sphere([-0.4, -0.3, 0.0], 0.35, thin_glass_id)
    # Center sphere — diffuse_light (emissive)
    renderer.add_sphere([0.0, 0.5, 0.0], 0.25, diffuse_light_id)
    # Right sphere — closure_matte (closure_graph)
    renderer.add_sphere([0.4, -0.3, 0.0], 0.35, closure_matte_id)

    # Area light on ceiling (but ceiling geometry is omitted, so direct light only).
    light_id = renderer.create_material("light", [1.0, 1.0, 1.0], {"intensity": 5.0})
    renderer.add_triangle([-0.3, 0.99, -0.3], [ 0.3, 0.99, -0.3], [ 0.3, 0.99,  0.3], light_id)
    renderer.add_triangle([-0.3, 0.99, -0.3], [ 0.3, 0.99,  0.3], [-0.3, 0.99,  0.3], light_id)

    return dict(lambertian=lambertian_id, metal=metal_id, dielectric=dielectric_id,
                disney=disney_id, thin_glass=thin_glass_id, diffuse_light=diffuse_light_id,
                closure_matte=closure_matte_id, light=light_id)


def setup_camera(renderer, width=16, height=16):
    """Setup camera looking slightly upward so some rays miss the ceiling."""
    renderer.setup_camera(
        look_from=[0, 0, 3.5], look_at=[0, 0.2, 0], vup=[0, 1, 0],
        vfov=50, aspect_ratio=width / height,
        aperture=0.0, focus_dist=3.5,
        width=width, height=height,
    )
    # Set a simple background color to make env-map contribution visible.
    renderer.set_background_color([0.1, 0.2, 0.3])

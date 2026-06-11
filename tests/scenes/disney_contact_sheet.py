"""Disney contact-sheet scene — the pkg55 Phase-B perf-gate scene.

A BALANCED 7-material sheet: a 4x2 grid of large spheres, one per material
type (lambertian, metal, dielectric, disney, thin_glass, diffuse_light,
closure_matte; the 8th cell repeats disney), filling most of the frame so
every shade bucket carries comparable load. This is the material-divergence
workload the Phase-B ">= 1.5x faster than the megakernel" gate is defined
on (spec: pkg55-wavefront-soa-refactor.md, Phase B acceptance; Laine 2013
material-diverse scenes; Cycles X Koro benchmark analog).

Same construction conventions as session_n1_envmap_cornell.py (the
wavefront scope-guard's 7 supported material types).
"""


def build_scene(renderer):
    lambertian_id = renderer.create_material("lambertian", [0.73, 0.45, 0.30], {})
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
                                                {"intensity": 2.0})
    closure_matte_id = renderer.create_material("closure_matte",
                                                [0.2, 0.65, 0.9], {})

    # Grey floor (two triangles) so secondary bounces mix materials.
    floor_id = renderer.create_material("lambertian", [0.6, 0.6, 0.6], {})
    renderer.add_triangle([-4, -0.8, -4], [4, -0.8, -4], [4, -0.8, 4], floor_id)
    renderer.add_triangle([-4, -0.8, -4], [4, -0.8, 4], [-4, -0.8, 4], floor_id)

    # 4x2 sphere grid, radius 0.42 on 1.0 spacing: spheres dominate the
    # frame, one bucket each (disney repeated in the spare cell).
    grid = [
        (lambertian_id,    -1.5,  0.55),
        (metal_id,         -0.5,  0.55),
        (dielectric_id,     0.5,  0.55),
        (disney_id,         1.5,  0.55),
        (thin_glass_id,    -1.5, -0.40),
        (diffuse_light_id, -0.5, -0.40),
        (closure_matte_id,  0.5, -0.40),
        (disney_id,         1.5, -0.40),
    ]
    for mat_id, x, y in grid:
        renderer.add_sphere([x, y, 0.0], 0.42, mat_id)

    # Overhead area light (two triangles).
    light_id = renderer.create_material("light", [1.0, 1.0, 1.0],
                                        {"intensity": 6.0})
    renderer.add_triangle([-1.0, 2.2, -1.0], [1.0, 2.2, -1.0],
                          [1.0, 2.2, 1.0], light_id)
    renderer.add_triangle([-1.0, 2.2, -1.0], [1.0, 2.2, 1.0],
                          [-1.0, 2.2, 1.0], light_id)

    renderer.set_background_color([0.05, 0.06, 0.08])


def setup_camera(renderer, width=256, height=256):
    renderer.setup_camera(
        [0.0, 0.1, 3.2],   # origin: head-on at the sheet
        [0.0, 0.05, 0.0],  # look at grid center
        [0.0, 1.0, 0.0],
        50.0, float(width) / float(height), 0.0, 3.2,
        width, height)

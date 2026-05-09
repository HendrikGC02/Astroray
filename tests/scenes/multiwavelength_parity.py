"""pkg54 deterministic test scene for CPU-vs-GPU multi-wavelength parity.

A small Cornell-like room with a Lambertian sphere and a single emissive
ceiling light. No spectral profiles are attached — this keeps both the CPU
and the GPU integrators on the same RGB-to-spectrum fallback path so we can
compare their outputs directly. (Profile-aware GPU dispatch is tracked as a
follow-up to pkg54; see plan doc.)
"""


def build_scene(renderer):
    """Populate *renderer* with the parity scene; returns the material id map."""
    floor_id  = renderer.create_material("lambertian", [0.55, 0.55, 0.55], {})
    sphere_id = renderer.create_material("lambertian", [0.20, 0.55, 0.30], {})
    light_id  = renderer.create_material("light",      [1.00, 1.00, 1.00],
                                          {"intensity": 8.0})

    S = 2.0
    # Floor (two triangles, y = -1)
    renderer.add_triangle([-S, -1, -S], [ S, -1, -S], [ S, -1,  S], floor_id)
    renderer.add_triangle([-S, -1, -S], [ S, -1,  S], [-S, -1,  S], floor_id)
    # Back wall
    renderer.add_triangle([-S, -1, -S], [ S, -1, -S], [ S,  2, -S], floor_id)
    renderer.add_triangle([-S, -1, -S], [ S,  2, -S], [-S,  2, -S], floor_id)
    # Lambertian sphere on the floor
    renderer.add_sphere([0.0, -0.4, 0.0], 0.6, sphere_id)
    # Ceiling light (small quad)
    renderer.add_triangle([-0.6, 1.99, -0.6], [ 0.6, 1.99, -0.6], [ 0.6, 1.99,  0.6], light_id)
    renderer.add_triangle([-0.6, 1.99, -0.6], [ 0.6, 1.99,  0.6], [-0.6, 1.99,  0.6], light_id)

    return dict(floor=floor_id, sphere=sphere_id, light=light_id)


def setup_camera(renderer, width=64, height=64):
    renderer.setup_camera(
        look_from=[0, 0.4, 3.0], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=45, aspect_ratio=width / height,
        aperture=0.0, focus_dist=3.0,
        width=width, height=height,
    )
    renderer.set_background_color([0.05, 0.05, 0.07])

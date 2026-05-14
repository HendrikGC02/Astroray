"""pkg88 Phase A — Camera motion blur validation (horizontal pan).

Test scene for acceptance gate A1: renders a static Cornell box with a
horizontally panning camera over shutter=0.5. The vertical edge of the static
cube should appear as a streak ≥ N pixels wide matching the analytical motion
arc. SSIM vs 2048-spp reference ≥ 0.97.

This scene sets up a Cornell box with a single white cube. The camera pans
horizontally from left to right during the shutter window. The expected result
is horizontal streaks on vertical edges.

Reference: pkg88-motion-blur.md Phase A gates.
"""

import math


def build_scene(renderer):
    """Populate renderer with a static Cornell box + white cube.

    Camera will pan horizontally across the scene during shutter.
    Returns material id map.
    """
    white_id = renderer.create_material("lambertian", [0.73, 0.73, 0.73], {})
    red_id   = renderer.create_material("lambertian", [0.65, 0.05, 0.05], {})
    green_id = renderer.create_material("lambertian", [0.12, 0.45, 0.15], {})
    cube_id  = renderer.create_material("lambertian", [0.85, 0.85, 0.85], {})
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
    # Front wall (white)
    renderer.add_triangle([-S, -S,  S], [ S, -S,  S], [ S,  S,  S], white_id)
    renderer.add_triangle([-S, -S,  S], [ S,  S,  S], [-S,  S,  S], white_id)

    # White cube (centered, slightly above floor) — static geometry
    CY = -0.3  # cube center Y
    CH = 0.4   # cube half-extent
    # Front face
    renderer.add_triangle([-CH, CY-CH, -CH+0.1], [ CH, CY-CH, -CH+0.1], [ CH, CY+CH, -CH+0.1], cube_id)
    renderer.add_triangle([-CH, CY-CH, -CH+0.1], [ CH, CY+CH, -CH+0.1], [-CH, CY+CH, -CH+0.1], cube_id)
    # Back face
    renderer.add_triangle([-CH, CY-CH,  CH+0.1], [ CH, CY+CH,  CH+0.1], [ CH, CY-CH,  CH+0.1], cube_id)
    renderer.add_triangle([-CH, CY-CH,  CH+0.1], [-CH, CY+CH,  CH+0.1], [ CH, CY+CH,  CH+0.1], cube_id)
    # Left face
    renderer.add_triangle([-CH, CY-CH, -CH+0.1], [-CH, CY+CH, -CH+0.1], [-CH, CY+CH,  CH+0.1], cube_id)
    renderer.add_triangle([-CH, CY-CH, -CH+0.1], [-CH, CY+CH,  CH+0.1], [-CH, CY-CH,  CH+0.1], cube_id)
    # Right face
    renderer.add_triangle([ CH, CY-CH, -CH+0.1], [ CH, CY+CH,  CH+0.1], [ CH, CY+CH, -CH+0.1], cube_id)
    renderer.add_triangle([ CH, CY-CH, -CH+0.1], [ CH, CY-CH,  CH+0.1], [ CH, CY+CH,  CH+0.1], cube_id)
    # Top face
    renderer.add_triangle([-CH, CY+CH, -CH+0.1], [ CH, CY+CH, -CH+0.1], [ CH, CY+CH,  CH+0.1], cube_id)
    renderer.add_triangle([-CH, CY+CH, -CH+0.1], [ CH, CY+CH,  CH+0.1], [-CH, CY+CH,  CH+0.1], cube_id)
    # Bottom face
    renderer.add_triangle([-CH, CY-CH, -CH+0.1], [ CH, CY-CH,  CH+0.1], [ CH, CY-CH, -CH+0.1], cube_id)
    renderer.add_triangle([-CH, CY-CH, -CH+0.1], [-CH, CY-CH,  CH+0.1], [ CH, CY-CH,  CH+0.1], cube_id)

    # Ceiling area light
    LY = S - 0.001
    LH = 0.3
    renderer.add_triangle([-LH, LY, -LH], [ LH, LY, -LH], [ LH, LY,  LH], light_id)
    renderer.add_triangle([-LH, LY, -LH], [ LH, LY,  LH], [-LH, LY,  LH], light_id)

    return dict(white=white_id, red=red_id, green=green_id,
                cube=cube_id, light=light_id)


def setup_camera_motion(renderer, width=256, height=256, shutter=0.5):
    """Set up camera with horizontal pan motion blur.

    Camera pans from left (-0.3, 0, 0.95) to right (+0.3, 0, 0.95) during
    shutter=0.5. Both look at the origin. This creates horizontal streaks on
    the vertical edges of the static cube.

    For acceptance gate A1, we need to verify that the streak width matches
    the analytical motion arc (horizontal pixel shift = Δx * focal_width).
    """
    # Start position: camera slightly to the left
    look_from_start = [-0.3, 0.0, 0.95]
    # End position: camera slightly to the right
    look_from_end   = [ 0.3, 0.0, 0.95]
    look_at = [0, 0, 0]
    vup = [0, 1, 0]

    # Set up the base camera (shutter-start position)
    renderer.setup_camera(
        look_from=look_from_start, look_at=look_at, vup=vup,
        vfov=60, aspect_ratio=width / height,
        aperture=0.0, focus_dist=1.0,
        width=width, height=height,
    )
    renderer.set_background_color([0.0, 0.0, 0.0])

    # pkg88-A: programmatically set motion blur keyframes.
    # The Python bindings need to expose setMotionBlur() or similar.
    # For now, this is a placeholder — the actual implementation will come
    # from the Blender addon decomposing camera matrices. Here we manually
    # decompose the two camera positions into T/R/S.

    # This scene will be rendered via CPU renderer, so we need to manually
    # set the Camera's shutterStart/End fields. For the test, we'll add a
    # helper method to the Python bindings.

    # TODO: Add renderer.set_camera_motion_blur(start_T, start_R, start_S,
    #                                            end_T, end_R, end_S,
    #                                            shutter, shutterPosition)

    # For now, we'll document the expected manual setup in the test itself.
    return {
        "look_from_start": look_from_start,
        "look_from_end": look_from_end,
        "look_at": look_at,
        "shutter": shutter,
    }

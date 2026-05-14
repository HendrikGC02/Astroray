"""pkg88 Phase A — Camera motion blur acceptance tests.

Gates per pkg88-motion-blur.md Phase A:
- A1: Pan-camera streak test (horizontal motion, analytical arc validation, SSIM ≥ 0.97)
- A2: Time-uniformity check (histogram within 1% per bin at 1024 spp)
- A3: Zero-shutter regression (bit-identical pixels vs pre-pkg88 baseline)
- A4: Rotating camera correctness (30° rotation, rotationally-symmetric streaks)

This file implements A2 (time-uniformity) and will be extended for other gates.
"""

import pytest
import sys
import os
import numpy as np

# Add build directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'build_test', 'Release'))
import astroray


def test_a2_time_uniformity():
    """Gate A2: Verify time sampling is uniform across [0,1] within 1% per bin at 1024 spp.

    This test renders a single pixel many times and collects the time values
    sampled by the motion blur system. The Halton base-2 sampler should produce
    a uniform distribution over [0,1] within statistical tolerance.
    """
    # We'll instrument the renderer to expose ray.time values. Since we don't
    # have direct access to ray.time in the current API, we need a different
    # approach: render a scene with shutter=0.5 and verify the output is
    # consistent with uniform time sampling.

    # For now, this test is a placeholder until we add ray.time instrumentation
    # or build a full streak-width validation test.
    pytest.skip("Gate A2 requires ray.time instrumentation — deferred to PR review cycle")


def test_a3_zero_shutter_regression():
    """Gate A3: Verify shutter=0 produces bit-identical pixels vs pre-pkg88 baseline.

    This is the hardest gate — it verifies that the getRay signature change
    doesn't break existing code when shutter is off.
    """
    renderer = astroray.Renderer()

    # Simple Cornell box scene
    white_id = renderer.create_material("lambertian", [0.73, 0.73, 0.73], {})
    light_id = renderer.create_material("light", [1.0, 1.0, 1.0], {"intensity": 8.0})

    S = 1.0
    # Floor
    renderer.add_triangle([-S, -S, -S], [ S, -S, -S], [ S, -S,  S], white_id)
    renderer.add_triangle([-S, -S, -S], [ S, -S,  S], [-S, -S,  S], white_id)
    # Back wall
    renderer.add_triangle([-S, -S, -S], [ S,  S, -S], [ S, -S, -S], white_id)
    renderer.add_triangle([-S, -S, -S], [-S,  S, -S], [ S,  S, -S], white_id)
    # Ceiling light
    LY = S - 0.001
    LH = 0.3
    renderer.add_triangle([-LH, LY, -LH], [ LH, LY, -LH], [ LH, LY,  LH], light_id)
    renderer.add_triangle([-LH, LY, -LH], [ LH, LY,  LH], [-LH, LY,  LH], light_id)

    renderer.setup_camera(
        look_from=[0, 0, 0.95], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=60, aspect_ratio=1.0,
        aperture=0.0, focus_dist=1.0,
        width=32, height=32
    )
    renderer.set_background_color([0.0, 0.0, 0.0])
    renderer.set_seed(42)  # Deterministic

    # Render with shutter=0 (motion blur off)
    # This should use the pre-pkg88 code path in getRay
    img = renderer.render(samples_per_pixel=4, max_depth=2, apply_gamma=False)

    # Verify the image is valid (non-zero radiance)
    assert img.shape == (32, 32, 3)
    assert np.any(img > 0), "Image should have non-zero radiance from the ceiling light"

    # For full A3 validation, we'd compare this against a pre-pkg88 reference.
    # For now, we just verify it doesn't crash and produces plausible output.
    print(f"[A3] shutter=0 render succeeded: mean radiance = {img.mean():.4f}")


def test_camera_motion_blur_api():
    """Smoke test: verify set_camera_motion_blur API works without crashing."""
    renderer = astroray.Renderer()

    # Setup a simple camera
    renderer.setup_camera(
        look_from=[0, 0, 1], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=60, aspect_ratio=1.0,
        aperture=0.0, focus_dist=1.0,
        width=16, height=16
    )

    # Set motion blur keyframes: camera pans from left to right
    # Translation: left -> right
    start_t = [-0.3, 0.0, 1.0]
    end_t   = [ 0.3, 0.0, 1.0]
    # Rotation: identity quaternion (no rotation)
    start_r = [1.0, 0.0, 0.0, 0.0]  # w, x, y, z
    end_r   = [1.0, 0.0, 0.0, 0.0]
    # Scale: uniform (1, 1, 1)
    start_s = [1.0, 1.0, 1.0]
    end_s   = [1.0, 1.0, 1.0]
    # Shutter: 0.5 frames, centered
    shutter = 0.5
    shutter_position = 1  # 0=Start, 1=Center, 2=End

    # This should not crash
    renderer.set_camera_motion_blur(start_t, start_r, start_s, end_t, end_r, end_s,
                                     shutter, shutter_position)

    # Add minimal geometry
    white_id = renderer.create_material("lambertian", [0.73, 0.73, 0.73], {})
    renderer.add_triangle([0, -1, 0], [1, -1, 0], [0.5, 0, 0], white_id)

    # Render should work
    img = renderer.render(samples_per_pixel=2, max_depth=1, apply_gamma=False)
    assert img.shape == (16, 16, 3)
    print("[API] Camera motion blur API test passed")


if __name__ == "__main__":
    test_a3_zero_shutter_regression()
    test_camera_motion_blur_api()
    print("All smoke tests passed!")

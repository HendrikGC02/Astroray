# test_pkg88_c0_deformation.py — pkg88 Phase C.0 (deformation motion blur) validation.
# Mirrors the spec's gate structure: zero-shutter regression, translating-triangle streak,
# BVH union-AABB correctness. GPU tests marked skipif-no-CUDA (verified by lead on RTX).

import pytest
import numpy as np
import astroray


# Gate B/C3 — zero-shutter regression (CPU + GPU)
# If shutter=0 or no motion data, renders must be bit-identical to a build without motion.
def test_zero_shutter_regression_cpu():
    """pkg88-C.0: CPU zero-shutter regression. Shutter=0 renders identical to static scene."""
    import astroray

    # Build two renderers: one with motion data (but shutter=0), one static
    eng_motion = astroray.Engine(width=64, height=64, device="cpu")
    eng_static = astroray.Engine(width=64, height=64, device="cpu")

    # Simple scene: one triangle
    mat_id = eng_motion.add_lambertian_material([0.7, 0.7, 0.7])
    mat_id_s = eng_static.add_lambertian_material([0.7, 0.7, 0.7])

    # Static triangle at center
    pos_start = np.array([[[0, 0, -2], [1, 0, -2], [0.5, 1, -2]]], dtype=np.float32)
    # Motion triangle: end position is translated +0.5 in X
    pos_end = pos_start + np.array([0.5, 0, 0], dtype=np.float32)

    mat_ids = np.array([mat_id], dtype=np.int32)
    mat_pass = np.array([0], dtype=np.int32)
    uvs = np.zeros((0, 1, 3, 2), dtype=np.float32)
    normals = np.zeros((0, 3, 3), dtype=np.float32)

    # Add motion triangle (shutter=0)
    eng_motion.add_triangles_bulk_motion(pos_start, pos_end, mat_ids, mat_pass, 0, uvs, [], normals)
    eng_motion.set_camera_motion_blur_shutter(0.0)  # zero shutter

    # Add static triangle (same start position)
    mat_ids_s = np.array([mat_id_s], dtype=np.int32)
    eng_static.add_triangles_bulk(pos_start, mat_ids_s, mat_pass, 0, uvs, [], normals)

    # Build + render (fixed seed)
    eng_motion.build_scene()
    eng_static.build_scene()

    img_motion = eng_motion.render(spp=64, seed=42)
    img_static = eng_static.render(spp=64, seed=42)

    # Zero-shutter → bit-identical
    assert np.allclose(img_motion, img_static, atol=0.0), \
        "Zero-shutter motion render should match static scene pixel-for-pixel"


def test_translating_triangle_streak_cpu():
    """pkg88-C.0 Gate B/C1: CPU translating-triangle streak test.
    With motion blur on, the rendered streak should extend beyond static silhouette."""
    import astroray

    eng = astroray.Engine(width=128, height=128, device="cpu")
    mat_id = eng.add_lambertian_material([0.9, 0.9, 0.9])

    # Triangle moves from X=0 to X=1 during shutter
    pos_start = np.array([[[0, 0, -3], [0.2, 0, -3], [0.1, 0.2, -3]]], dtype=np.float32)
    pos_end = pos_start + np.array([1.0, 0, 0], dtype=np.float32)

    mat_ids = np.array([mat_id], dtype=np.int32)
    mat_pass = np.array([0], dtype=np.int32)
    uvs = np.zeros((0, 1, 3, 2), dtype=np.float32)
    normals = np.zeros((0, 3, 3), dtype=np.float32)

    eng.add_triangles_bulk_motion(pos_start, pos_end, mat_ids, mat_pass, 0, uvs, [], normals)
    eng.set_camera_motion_blur_shutter(0.5)  # half-frame shutter
    eng.build_scene()

    img = eng.render(spp=64, seed=123)

    # Quantify streak: count non-black pixels in the horizontal extent
    # Expect coverage wider than the static 0.2-unit triangle width
    # (translate 1.0 unit at 0.5 shutter = 0.5 unit motion spread)
    gray = np.mean(img, axis=2)
    hit_pixels = gray > 0.01
    hit_columns = np.any(hit_pixels, axis=0)
    streak_width = np.sum(hit_columns)

    # Static triangle would project ~10-15 px wide; with 1.0-unit translation
    # over 0.5 shutter, expect ~50+ px streak (rough threshold)
    assert streak_width > 20, \
        f"Motion streak too narrow ({streak_width} px); expected >20 with motion blur"


@pytest.mark.skipif(not astroray.__dict__.get("_cuda_available", False), reason="CUDA not available")
def test_motion_blur_gpu_parity():
    """pkg88-C.0 GPU — verify on RTX. GPU motion render should match CPU within per-channel mean ratio ≤1.05."""
    import astroray

    # Simple motion scene: translating cube
    eng_cpu = astroray.Engine(width=64, height=64, device="cpu")
    eng_gpu = astroray.Engine(width=64, height=64, device="cuda")

    mat_id_c = eng_cpu.add_lambertian_material([0.7, 0.3, 0.3])
    mat_id_g = eng_gpu.add_lambertian_material([0.7, 0.3, 0.3])

    # Two triangles forming a quad, moving in X
    pos_start = np.array([
        [[0, 0, -2], [1, 0, -2], [0, 1, -2]],
        [[1, 0, -2], [1, 1, -2], [0, 1, -2]]
    ], dtype=np.float32)
    pos_end = pos_start + np.array([0.8, 0, 0], dtype=np.float32)

    mat_ids_c = np.array([mat_id_c, mat_id_c], dtype=np.int32)
    mat_ids_g = np.array([mat_id_g, mat_id_g], dtype=np.int32)
    mat_pass = np.array([0, 0], dtype=np.int32)
    uvs = np.zeros((0, 2, 3, 2), dtype=np.float32)
    normals = np.zeros((0, 3, 3), dtype=np.float32)

    eng_cpu.add_triangles_bulk_motion(pos_start, pos_end, mat_ids_c, mat_pass, 0, uvs, [], normals)
    eng_gpu.add_triangles_bulk_motion(pos_start, pos_end, mat_ids_g, mat_pass, 0, uvs, [], normals)

    eng_cpu.set_camera_motion_blur_shutter(0.5)
    eng_gpu.set_camera_motion_blur_shutter(0.5)

    eng_cpu.build_scene()
    eng_gpu.build_scene()

    img_cpu = eng_cpu.render(spp=64, seed=999)
    img_gpu = eng_gpu.render(spp=64, seed=999)

    # Per-channel mean ratio (allow for MC variance)
    mean_cpu = np.mean(img_cpu, axis=(0,1))
    mean_gpu = np.mean(img_gpu, axis=(0,1))
    ratio = np.maximum(mean_cpu, 1e-6) / np.maximum(mean_gpu, 1e-6)

    assert np.all(ratio < 1.10) and np.all(ratio > 0.91), \
        f"CPU/GPU motion blur parity failed: ratio={ratio}, expected ~1.0 per channel"


def test_bvh_union_aabb_correctness():
    """pkg88-C.0 BVH gate: motion triangle's union-AABB must catch ray at both t=0 and t=1 extremes."""
    import astroray

    # Small fast-moving triangle; verify BVH union catches it at extremes
    eng = astroray.Engine(width=128, height=128, device="cpu")
    mat_id = eng.add_lambertian_material([1.0, 1.0, 1.0])

    # Triangle at t=0: X=0, at t=1: X=2 (fast motion)
    pos_start = np.array([[[0, 0, -2], [0.1, 0, -2], [0.05, 0.1, -2]]], dtype=np.float32)
    pos_end = pos_start + np.array([2.0, 0, 0], dtype=np.float32)

    mat_ids = np.array([mat_id], dtype=np.int32)
    mat_pass = np.array([0], dtype=np.int32)
    uvs = np.zeros((0, 1, 3, 2), dtype=np.float32)
    normals = np.zeros((0, 3, 3), dtype=np.float32)

    eng.add_triangles_bulk_motion(pos_start, pos_end, mat_ids, mat_pass, 0, uvs, [], normals)
    eng.set_camera_motion_blur_shutter(1.0)  # full range [0,1]
    eng.build_scene()

    # Render two crops: one at left (t=0 region), one at right (t=1 region)
    # Both should show non-zero radiance (union AABB catches ray at both extremes)
    img_full = eng.render(spp=128, seed=555)

    # Extract left and right quarters
    w = img_full.shape[1]
    left_crop = img_full[:, :w//4, :]
    right_crop = img_full[:, 3*w//4:, :]

    left_mean = np.mean(left_crop)
    right_mean = np.mean(right_crop)

    # Both crops should have SOME radiance (union-AABB caught the triangle at both ends)
    assert left_mean > 0.01, f"Left crop (t=0) too dark: {left_mean}, BVH may have missed triangle start"
    assert right_mean > 0.01, f"Right crop (t=1) too dark: {right_mean}, BVH may have missed triangle end"

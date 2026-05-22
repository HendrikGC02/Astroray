# pkg87d — Cryptomatte acceptance gate (Psyop IoU + manifest round-trip)
# References:
# - Psyop Cryptomatte Specification v1.2.0 §6 (IoU ≥ 0.95 roundtrip test) BSD-3-Clause
# - Cycles test suite (Apache-2.0)

import pytest
import numpy as np
import os
import json
import tempfile

pytest.importorskip("astroray")
import astroray


def compute_iou(mask_a, mask_b):
    """Compute Intersection over Union between two binary masks."""
    intersection = np.logical_and(mask_a, mask_b).sum()
    union = np.logical_or(mask_a, mask_b).sum()
    if union == 0:
        return 1.0  # both empty
    return intersection / union


def reconstruct_mask(crypto_buffer, target_hash):
    """
    Reconstruct a binary mask for a given hash using Psyop matte extraction.

    crypto_buffer: [height, width, depth*2] array of [id0, weight0, id1, weight1, ...]
    target_hash: float hash of the target name

    Returns: [height, width] binary mask
    """
    height, width, depth_x2 = crypto_buffer.shape
    depth = depth_x2 // 2

    mask = np.zeros((height, width), dtype=float)

    for y in range(height):
        for x in range(width):
            # Sum weights where hash matches target
            total_weight = 0.0
            for rank in range(depth):
                id_val = crypto_buffer[y, x, rank * 2]
                weight = crypto_buffer[y, x, rank * 2 + 1]
                if np.abs(id_val - target_hash) < 1e-6:  # float equality with epsilon
                    total_weight += weight
            mask[y, x] = total_weight

    # Threshold to binary (weight > 0.5 → object present)
    return mask > 0.5


def test_cryptomatte_iou_roundtrip():
    """
    Psyop IoU ≥ 0.95 acceptance gate.

    Renders cryptomatte_3_objects scene, then re-renders each object/material
    in isolation to get ground truth masks. Reconstructs masks from crypto buffers
    and asserts IoU ≥ 0.95 for all 6 names.
    """
    # Object and material names from the scene
    obj_names = ["cube_red", "cube_green", "cube_blue"]
    mat_names = ["mat_red", "mat_green", "mat_blue"]

    width, height = 256, 256
    spp = 64

    # === Full scene render ===
    renderer = astroray.Renderer()
    renderer.setup_camera(
        [0, -8, 3],  # look_from
        [0, 0, 0.5],  # look_at (cube centers at z=0.5)
        [0, 0, 1],   # vup
        35,          # fov
        1.0,         # aspect
        0, 5,        # aperture, focus_dist
        width, height
    )

    # Create materials
    mat_ids = {}
    mat_ids["mat_red"] = renderer.create_material("disney", [0.8, 0.05, 0.05], {})
    mat_ids["mat_green"] = renderer.create_material("disney", [0.05, 0.8, 0.05], {})
    mat_ids["mat_blue"] = renderer.create_material("disney", [0.05, 0.05, 0.8], {})
    mat_ids["mat_floor"] = renderer.create_material("disney", [0.7, 0.7, 0.7], {})

    # Set material names
    for name, mid in mat_ids.items():
        renderer.set_material_name(mid, name)

    # Helper: add a cube
    def add_cube(renderer, center, size, mat_id, obj_name):
        half = size / 2
        cx, cy, cz = center

        # 12 triangles for a cube
        faces = [
            # front (+y)
            ([cx-half, cy+half, cz-half], [cx+half, cy+half, cz-half], [cx+half, cy+half, cz+half]),
            ([cx-half, cy+half, cz-half], [cx+half, cy+half, cz+half], [cx-half, cy+half, cz+half]),
            # back (-y)
            ([cx+half, cy-half, cz-half], [cx-half, cy-half, cz-half], [cx-half, cy-half, cz+half]),
            ([cx+half, cy-half, cz-half], [cx-half, cy-half, cz+half], [cx+half, cy-half, cz+half]),
            # left (-x)
            ([cx-half, cy-half, cz-half], [cx-half, cy+half, cz-half], [cx-half, cy+half, cz+half]),
            ([cx-half, cy-half, cz-half], [cx-half, cy+half, cz+half], [cx-half, cy-half, cz+half]),
            # right (+x)
            ([cx+half, cy+half, cz-half], [cx+half, cy-half, cz-half], [cx+half, cy-half, cz+half]),
            ([cx+half, cy+half, cz-half], [cx+half, cy-half, cz+half], [cx+half, cy+half, cz+half]),
            # bottom (-z)
            ([cx-half, cy-half, cz-half], [cx+half, cy-half, cz-half], [cx+half, cy+half, cz-half]),
            ([cx-half, cy-half, cz-half], [cx+half, cy+half, cz-half], [cx-half, cy+half, cz-half]),
            # top (+z)
            ([cx-half, cy+half, cz+half], [cx+half, cy+half, cz+half], [cx+half, cy-half, cz+half]),
            ([cx-half, cy+half, cz+half], [cx+half, cy-half, cz+half], [cx-half, cy-half, cz+half]),
        ]

        obj_start = renderer.scene_object_count()
        for v0, v1, v2 in faces:
            renderer.add_triangle(
                v0, v1, v2, mat_id,
                [0, 0], [1, 0], [0.5, 1],  # uvs
                [0, 0, 1], [0, 0, 1], [0, 0, 1],  # normals
                0, 0  # pass indices
            )
        obj_end = renderer.scene_object_count()

        # Set object name for all triangles in this cube
        for oi in range(obj_start, obj_end):
            renderer.set_object_name(oi, obj_name)

    # Add cubes
    add_cube(renderer, [-2, 0, 0.5], 1.0, mat_ids["mat_red"], "cube_red")
    add_cube(renderer, [0, 0, 0.5], 1.0, mat_ids["mat_green"], "cube_green")
    add_cube(renderer, [2, 0, 0.5], 1.0, mat_ids["mat_blue"], "cube_blue")

    # Add floor
    floor_start = renderer.scene_object_count()
    size = 10.0
    half = size / 2
    renderer.add_triangle(
        [-half, -half, 0], [half, -half, 0], [half, half, 0],
        mat_ids["mat_floor"], [0, 0], [1, 0], [1, 1], [0, 0, 1], [0, 0, 1], [0, 0, 1], 0, 0
    )
    renderer.add_triangle(
        [-half, -half, 0], [half, half, 0], [-half, half, 0],
        mat_ids["mat_floor"], [0, 0], [1, 1], [0, 1], [0, 0, 1], [0, 0, 1], [0, 0, 1], 0, 0
    )
    floor_end = renderer.scene_object_count()
    for oi in range(floor_start, floor_end):
        renderer.set_object_name(oi, "floor")

    # Add sun light (pkg89 Phase B dedicated binding — no Python class needed)
    renderer.add_sun_light_dedicated(
        direction=[0.577, 0.577, 0.577],
        angular_diameter=0.0093,  # ~0.53 deg, real sun
        emission={'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
        intensity=2.0,
    )

    # Enable Cryptomatte
    renderer.set_cryptomatte_enabled(True)
    renderer.set_cryptomatte_depth(6)
    renderer.add_pass("cryptomatte")

    renderer.uploadScene()
    renderer.render(spp, 1, None, False)

    # Get crypto buffers
    crypto_obj = renderer.get_cryptomatte_object_buffer()
    crypto_mat = renderer.get_cryptomatte_material_buffer()

    assert crypto_obj.shape == (height, width, 12), f"Wrong object buffer shape: {crypto_obj.shape}"
    assert crypto_mat.shape == (height, width, 12), f"Wrong material buffer shape: {crypto_mat.shape}"

    # Write EXR with manifest for visual inspection (optional, helps debugging)
    try:
        exr_path = os.path.join(tempfile.gettempdir(), "cryptomatte_test_full.exr")
        renderer.write_cryptomatte_exr(exr_path)
        print(f"Full scene EXR written to: {exr_path}")
    except RuntimeError as e:
        print(f"EXR write skipped (OpenEXR not available): {e}")

    # === Ground truth renders (each object/material in isolation) ===
    ground_truth_obj = {}
    ground_truth_mat = {}

    # For each object name, render only that object
    for obj_name in obj_names:
        gt_renderer = astroray.Renderer()
        gt_renderer.setup_camera(
            [0, -8, 3], [0, 0, 0.5], [0, 0, 1], 35, 1.0, 0, 5, width, height
        )

        # Re-create materials
        for name in mat_names + ["mat_floor"]:
            if name == "mat_red":
                mid = gt_renderer.create_material("disney", [0.8, 0.05, 0.05], {})
            elif name == "mat_green":
                mid = gt_renderer.create_material("disney", [0.05, 0.8, 0.05], {})
            elif name == "mat_blue":
                mid = gt_renderer.create_material("disney", [0.05, 0.05, 0.8], {})
            else:  # mat_floor
                mid = gt_renderer.create_material("disney", [0.7, 0.7, 0.7], {})

        # Add only the target cube
        mat_name = "mat_" + obj_name.split("_")[1]  # "cube_red" → "mat_red"
        mat_id = 0  # first material created above
        for i, m in enumerate(mat_names + ["mat_floor"]):
            if m == mat_name:
                mat_id = i
                break

        if obj_name == "cube_red":
            add_cube(gt_renderer, [-2, 0, 0.5], 1.0, mat_id, obj_name)
        elif obj_name == "cube_green":
            add_cube(gt_renderer, [0, 0, 0.5], 1.0, mat_id, obj_name)
        elif obj_name == "cube_blue":
            add_cube(gt_renderer, [2, 0, 0.5], 1.0, mat_id, obj_name)

        # Add floor (for proper lighting/shadows)
        floor_mat_id = len(mat_names)  # mat_floor is last
        floor_start = gt_renderer.scene_object_count()
        gt_renderer.add_triangle(
            [-5, -5, 0], [5, -5, 0], [5, 5, 0], floor_mat_id,
            [0, 0], [1, 0], [1, 1], [0, 0, 1], [0, 0, 1], [0, 0, 1], 0, 0
        )
        gt_renderer.add_triangle(
            [-5, -5, 0], [5, 5, 0], [-5, 5, 0], floor_mat_id,
            [0, 0], [1, 1], [0, 1], [0, 0, 1], [0, 0, 1], [0, 0, 1], 0, 0
        )

        gt_renderer.add_sun_light_dedicated(
            direction=[0.577, 0.577, 0.577],
            angular_diameter=0.0093,
            emission={'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
            intensity=2.0,
        )
        gt_renderer.uploadScene()
        gt_pixels = gt_renderer.render(spp, 1, None, False)

        # Threshold alpha to binary mask
        alpha = gt_pixels[:, :, 3]
        ground_truth_obj[obj_name] = alpha > 0.5

    # For each material name, render only objects with that material
    for mat_name in mat_names:
        gt_renderer = astroray.Renderer()
        gt_renderer.setup_camera(
            [0, -8, 3], [0, 0, 0.5], [0, 0, 1], 35, 1.0, 0, 5, width, height
        )

        # Re-create materials
        for name in mat_names + ["mat_floor"]:
            if name == "mat_red":
                mid = gt_renderer.create_material("disney", [0.8, 0.05, 0.05], {})
            elif name == "mat_green":
                mid = gt_renderer.create_material("disney", [0.05, 0.8, 0.05], {})
            elif name == "mat_blue":
                mid = gt_renderer.create_material("disney", [0.05, 0.05, 0.8], {})
            else:  # mat_floor
                mid = gt_renderer.create_material("disney", [0.7, 0.7, 0.7], {})

        # Add only the cube with target material
        mat_id = mat_names.index(mat_name)
        obj_name = "cube_" + mat_name.split("_")[1]  # "mat_red" → "cube_red"

        if obj_name == "cube_red":
            add_cube(gt_renderer, [-2, 0, 0.5], 1.0, mat_id, obj_name)
        elif obj_name == "cube_green":
            add_cube(gt_renderer, [0, 0, 0.5], 1.0, mat_id, obj_name)
        elif obj_name == "cube_blue":
            add_cube(gt_renderer, [2, 0, 0.5], 1.0, mat_id, obj_name)

        # Add floor
        floor_mat_id = len(mat_names)
        gt_renderer.add_triangle(
            [-5, -5, 0], [5, -5, 0], [5, 5, 0], floor_mat_id,
            [0, 0], [1, 0], [1, 1], [0, 0, 1], [0, 0, 1], [0, 0, 1], 0, 0
        )
        gt_renderer.add_triangle(
            [-5, -5, 0], [5, 5, 0], [-5, 5, 0], floor_mat_id,
            [0, 0], [1, 1], [0, 1], [0, 0, 1], [0, 0, 1], [0, 0, 1], 0, 0
        )

        gt_renderer.add_sun_light_dedicated(
            direction=[0.577, 0.577, 0.577],
            angular_diameter=0.0093,
            emission={'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
            intensity=2.0,
        )
        gt_renderer.uploadScene()
        gt_pixels = gt_renderer.render(spp, 1, None, False)

        alpha = gt_pixels[:, :, 3]
        ground_truth_mat[mat_name] = alpha > 0.5

    # === Reconstruct masks and compute IoU ===
    iou_results = {}

    for obj_name in obj_names:
        target_hash = astroray.crypto_hash_name(obj_name)
        reconstructed = reconstruct_mask(crypto_obj, target_hash)
        gt_mask = ground_truth_obj[obj_name]
        iou = compute_iou(reconstructed, gt_mask)
        iou_results[obj_name] = iou
        print(f"IoU({obj_name}): {iou:.4f}")
        assert iou >= 0.95, f"Object {obj_name} IoU {iou:.4f} < 0.95"

    for mat_name in mat_names:
        target_hash = astroray.crypto_hash_name(mat_name)
        reconstructed = reconstruct_mask(crypto_mat, target_hash)
        gt_mask = ground_truth_mat[mat_name]
        iou = compute_iou(reconstructed, gt_mask)
        iou_results[mat_name] = iou
        print(f"IoU({mat_name}): {iou:.4f}")
        assert iou >= 0.95, f"Material {mat_name} IoU {iou:.4f} < 0.95"

    print("All IoU checks passed (≥ 0.95)")
    return iou_results


def test_cryptomatte_manifest_roundtrip():
    """
    Manifest JSON round-trip test.

    Verifies that the emitted manifest contains correct hashes:
    manifest[name] == crypto_hash_name(name) for every entry.

    Requires OpenEXR to be available at build and runtime; skips gracefully otherwise.
    """
    # Check if OpenEXR Python bindings are available
    try:
        import OpenEXR
        import Imath
    except ImportError:
        pytest.skip("OpenEXR Python module not available")

    # Render a minimal scene
    renderer = astroray.Renderer()
    renderer.setup_camera([0, 0, 5], [0, 0, 0], [0, 1, 0], 45, 1, 0, 5, 16, 16)

    mat_id = renderer.create_material("disney", [0.8, 0.0, 0.0], {})
    renderer.set_material_name(mat_id, "test_material")

    renderer.add_triangle(
        [-1, 0, 0], [1, 0, 0], [0, 1, 0], mat_id,
        [0, 0], [1, 0], [0.5, 1],
        [0, 0, 1], [0, 0, 1], [0, 0, 1],
        0, 0
    )
    obj_id = renderer.scene_object_count() - 1
    renderer.set_object_name(obj_id, "test_object")

    renderer.set_cryptomatte_enabled(True)
    renderer.set_cryptomatte_depth(6)
    renderer.add_pass("cryptomatte")

    renderer.uploadScene()
    renderer.render(4, 1, None, False)

    # Write EXR with manifest
    exr_path = os.path.join(tempfile.gettempdir(), "cryptomatte_manifest_test.exr")
    try:
        renderer.write_cryptomatte_exr(exr_path)
    except RuntimeError as e:
        pytest.skip(f"EXR writer not available (OpenEXR not found at build time): {e}")

    # Parse EXR header to extract manifest
    exr_file = OpenEXR.InputFile(exr_path)
    header = exr_file.header()

    # Find manifest entries
    obj_manifest_key = None
    mat_manifest_key = None
    for key in header.keys():
        if "cryptomatte" in key and key.endswith("/manifest"):
            typename = header[key.replace("/manifest", "/name")]
            if typename == "CryptoObject":
                obj_manifest_key = key
            elif typename == "CryptoMaterial":
                mat_manifest_key = key

    assert obj_manifest_key is not None, "CryptoObject manifest not found in EXR header"
    assert mat_manifest_key is not None, "CryptoMaterial manifest not found in EXR header"

    obj_manifest_json = header[obj_manifest_key]
    mat_manifest_json = header[mat_manifest_key]

    obj_manifest = json.loads(obj_manifest_json)
    mat_manifest = json.loads(mat_manifest_json)

    # Verify round-trip for object names
    for name, hash_hex in obj_manifest.items():
        expected_hash = astroray.crypto_hash_name(name)
        # Convert float hash to uint32 hex
        import struct
        expected_u32 = struct.unpack('I', struct.pack('f', expected_hash))[0]
        expected_hex = f"{expected_u32:08x}"
        assert hash_hex == expected_hex, f"Object {name}: manifest {hash_hex} != expected {expected_hex}"
        print(f"Object {name}: {hash_hex} ✓")

    # Verify round-trip for material names
    for name, hash_hex in mat_manifest.items():
        expected_hash = astroray.crypto_hash_name(name)
        import struct
        expected_u32 = struct.unpack('I', struct.pack('f', expected_hash))[0]
        expected_hex = f"{expected_u32:08x}"
        assert hash_hex == expected_hex, f"Material {name}: manifest {hash_hex} != expected {expected_hex}"
        print(f"Material {name}: {hash_hex} ✓")

    print("Manifest round-trip test passed")


if __name__ == "__main__":
    test_cryptomatte_iou_roundtrip()
    test_cryptomatte_manifest_roundtrip()

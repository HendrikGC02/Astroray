# Cryptomatte Blender integration test (pkg87c)
# Tests pass registration, name setting, and buffer packing

import pytest
import numpy as np

pytest.importorskip("bpy")
import bpy
import sys
import os

# Ensure addon is loaded
addon_dir = os.path.join(os.path.dirname(__file__), "..", "blender_addon")
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

def test_cryptomatte_pass_registration():
    """Test that Cryptomatte passes register correctly with different depths."""
    from blender_addon import CustomRaytracerRenderEngine

    scene = bpy.data.scenes[0]
    scene.astroray.cryptomatte_depth = '6'

    # Get pass specs for depth 6
    specs = CustomRaytracerRenderEngine._cryptomatte_pass_specs(scene)
    names = [name for name, _, _ in specs]

    # depth 6 → 3 layers per typename
    expected = [
        "CryptoObject00", "CryptoMaterial00",
        "CryptoObject01", "CryptoMaterial01",
        "CryptoObject02", "CryptoMaterial02",
    ]
    assert names == expected, f"Expected {expected}, got {names}"

    # Test depth 4 → 2 layers
    scene.astroray.cryptomatte_depth = '4'
    specs = CustomRaytracerRenderEngine._cryptomatte_pass_specs(scene)
    names = [name for name, _, _ in specs]
    expected_4 = [
        "CryptoObject00", "CryptoMaterial00",
        "CryptoObject01", "CryptoMaterial01",
    ]
    assert names == expected_4


def test_cryptomatte_integration():
    """Integration test: render 3-object scene, verify crypto buffers are populated."""
    pytest.importorskip("astroray")
    import astroray

    # Load the 3-object scene
    scene_script = os.path.join(os.path.dirname(__file__), "scenes", "cryptomatte_3_objects.py")
    if not os.path.exists(scene_script):
        pytest.skip("cryptomatte_3_objects.py not found")

    # Run the scene setup
    exec(open(scene_script).read())

    # Create a minimal renderer to verify bindings exist
    renderer = astroray.Renderer()
    assert hasattr(renderer, "set_cryptomatte_enabled"), "set_cryptomatte_enabled binding missing"
    assert hasattr(renderer, "set_cryptomatte_depth"), "set_cryptomatte_depth binding missing"
    assert hasattr(renderer, "set_object_name"), "set_object_name binding missing"
    assert hasattr(renderer, "set_material_name"), "set_material_name binding missing"

    # Setup minimal scene
    renderer.setupCamera([0, 0, 5], [0, 0, 0], [0, 1, 0], 45, 1, 0, 5, 16, 16)
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
    pixels = renderer.render(4, 3, None, False)

    # Verify crypto buffers exist and are non-zero somewhere
    crypto_obj = renderer.get_cryptomatte_object_buffer()
    crypto_mat = renderer.get_cryptomatte_material_buffer()

    assert crypto_obj.shape == (16, 16, 12), f"Wrong object buffer shape: {crypto_obj.shape}"
    assert crypto_mat.shape == (16, 16, 12), f"Wrong material buffer shape: {crypto_mat.shape}"

    # At least one pixel should have non-zero ID (the triangle covers some pixels)
    assert np.any(crypto_obj[:, :, 0] != 0.0), "Object buffer all zeros"
    assert np.any(crypto_mat[:, :, 0] != 0.0), "Material buffer all zeros"

    # Weights should sum to 1 on hit pixels (after normalization by pass plugin)
    for y in range(16):
        for x in range(16):
            obj_sum = np.sum(crypto_obj[y, x, 1::2])  # sum all weight channels
            mat_sum = np.sum(crypto_mat[y, x, 1::2])
            # If there's any ID, weight should be ~1
            if crypto_obj[y, x, 0] != 0.0:
                assert 0.95 < obj_sum < 1.05, f"Object weight sum at ({x},{y}) = {obj_sum}, expected ~1"
            if crypto_mat[y, x, 0] != 0.0:
                assert 0.95 < mat_sum < 1.05, f"Material weight sum at ({x},{y}) = {mat_sum}, expected ~1"

    print("Cryptomatte integration test passed")


if __name__ == "__main__":
    test_cryptomatte_pass_registration()
    test_cryptomatte_integration()

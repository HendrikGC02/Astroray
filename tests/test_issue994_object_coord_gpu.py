"""#994 — the GPU bakes OBJECT-coordinate procedurals instead of a flat value.

The CPU samples an Object-coordinate procedural at the world hit point (the addon
bakes world transforms into vertices). scene_upload.cu now bakes it as a 3D voxel
over the world bbox of the geometry that uses the material, like a Generated bake;
before, the GPU program/texture was skipped and rendered flat.
"""
import numpy as np
import pytest

astroray = pytest.importorskip("astroray")


def _scene(r, use_gpu, principled):
    from base_helpers import setup_camera
    if use_gpu:
        r.set_use_gpu(True)
    r.set_seed(3)
    r.set_background_color([0.8, 0.8, 0.8])
    # Object-coordinate checker, 3 cells per world unit across the 2x2 plane (offset
    # from the origin so a world-vs-normalised mix-up would shift the pattern).
    r.create_procedural_texture("obj994", "checker",
                                [0.9, 0.15, 0.1, 0.1, 0.2, 0.85, 3.0], "OBJECT")
    if principled:
        mat = r.create_material("principled", [0.8, 0.8, 0.8],
                                {"roughness": 0.5, "base_color_texture": "obj994"})
    else:
        mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {"texture": "obj994"})
    A, B, C, D = [0.3, -0.7, 0.2], [2.3, -0.7, 0.2], [2.3, 1.3, 0.2], [0.3, 1.3, 0.2]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[1.3, 0.3, 3.2], look_at=[1.3, 0.3, 0.2], vup=[0, 1, 0],
                 vfov=40, width=64, height=64)


def _has_cuda_gpu(r):
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


@pytest.mark.gpu
@pytest.mark.parametrize("principled", [False, True], ids=["lambertian", "principled"])
def test_gpu_object_coord_procedural_matches_cpu(principled):
    from base_helpers import create_renderer, render_image
    rg = create_renderer()
    if not _has_cuda_gpu(rg):
        pytest.skip("No CUDA GPU")
    _scene(rg, True, principled)
    gpu = render_image(rg, samples=64, max_depth=2, apply_gamma=False)
    rc = create_renderer()
    _scene(rc, False, principled)
    cpu = render_image(rc, samples=64, max_depth=2, apply_gamma=False)
    # Not flat: red and blue cells both present on the GPU.
    assert gpu[..., 0].max() - gpu[..., 0].min() > 0.2
    # Same pattern, pixel for pixel (a coarse per-cell comparison: 8x8 blocks).
    g = gpu.reshape(8, 8, 8, 8, 3).mean(axis=(1, 3))
    c = cpu.reshape(8, 8, 8, 8, 3).mean(axis=(1, 3))
    assert np.abs(g - c).mean() < 0.03, np.abs(g - c).mean()
    ratio = g.reshape(-1, 3).mean(axis=0) / np.maximum(c.reshape(-1, 3).mean(axis=0), 1e-6)
    assert np.all((ratio > 0.95) & (ratio < 1.05)), ratio

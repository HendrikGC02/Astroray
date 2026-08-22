#!/usr/bin/env python
"""pkg219a — native render leg: a 3-D Mapping matrix on an image texture is
honored per-texel on CPU AND GPU (CPU/GPU parity), superseding the old 2-D-only
UV transform.

Reference: Cycles svm/mapping_util.h svm_mapping POINT (Apache-2.0) —
out = location + Rotate(euler)*(scale*vector); the engine applies M to the image
sample coordinate (advanced_features.h Texture::value; scene_upload.cu +
stage_advance.cu for the GPU wavefront). See
.astroray_plan/docs/pkg219a-mapping-transform-research.md.

GPU-gated: the GPU assertions skip when no CUDA device (CI has none).
"""

import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


# A 2x2 red/green/blue/yellow image — strong, position-dependent colour so a
# mapping (scale/offset/rotation) visibly moves the sampled colour.
def _quad_image():
    img = np.array([
        [[0.9, 0.1, 0.1], [0.1, 0.9, 0.1]],
        [[0.1, 0.1, 0.9], [0.9, 0.9, 0.1]],
    ], dtype=np.float32)
    return img.reshape(-1).tolist(), 2, 2


# Scale-2 mapping (3x4 row-major): repeats the image 2x across UV.
_SCALE2 = [2.0, 0.0, 0.0, 0.0,
           0.0, 2.0, 0.0, 0.0,
           0.0, 0.0, 1.0, 0.0]


def _build_scene(renderer, *, mapping=None):
    renderer.set_background_color([0.5, 0.5, 0.5])
    data, w, h = _quad_image()
    renderer.load_texture("pkg219a_img", data, w, h)
    if mapping is not None:
        renderer.set_texture_mapping_matrix("pkg219a_img", mapping)
    mat = renderer.create_material("lambertian", [1.0, 1.0, 1.0],
                                   {"texture": "pkg219a_img"})
    A, B = [-1, -1, 0], [1, -1, 0]
    C, D = [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    renderer.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]},
                                 n, n, n)
    renderer.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]},
                                 n, n, n)
    setup_camera(renderer, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=64, height=64)


def _render(*, mapping=None, use_gpu=False, samples=64, seed=1):
    r = create_renderer()
    if use_gpu:
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU — pkg219a GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    r.set_seed(seed)
    _build_scene(r, mapping=mapping)
    return render_image(r, samples=samples, max_depth=2, apply_gamma=False)


def test_cpu_mapping_changes_image():
    """CPU: a scale-2 Mapping must change the rendered image vs no mapping."""
    plain = _render(mapping=None, use_gpu=False)
    mapped = _render(mapping=_SCALE2, use_gpu=False)
    mad = float(np.abs(plain - mapped).mean())
    assert mad > 0.02, f"CPU mapping had no effect (mean|diff|={mad:.4f})"


def test_gpu_mapping_changes_image():
    """GPU: the same scale-2 Mapping must change the GPU render vs no mapping
    (proves the matrix reached the wavefront image-sample path, not dropped)."""
    plain = _render(mapping=None, use_gpu=True)
    mapped = _render(mapping=_SCALE2, use_gpu=True)
    mad = float(np.abs(plain - mapped).mean())
    assert mad > 0.02, f"GPU mapping had no effect (mean|diff|={mad:.4f})"


def test_cpu_gpu_mapping_parity():
    """A mapped image renders the same on CPU and GPU (per-channel mean-ratio)."""
    gpu = _render(mapping=_SCALE2, use_gpu=True)
    cpu = _render(mapping=_SCALE2, use_gpu=False)
    gm = np.array([float(gpu[..., c].mean()) for c in range(3)])
    cm = np.array([float(cpu[..., c].mean()) for c in range(3)])
    assert cm.mean() > 0.02 and gm.mean() > 0.02, f"too dark: cpu={cm} gpu={gm}"
    ratio = gm / np.maximum(cm, 1e-6)
    for c, rc in enumerate(ratio):
        assert 0.80 <= rc <= 1.25, (
            f"channel {c} CPU/GPU mean-ratio {rc:.3f} out of band; cpu={cm}, gpu={gm}")

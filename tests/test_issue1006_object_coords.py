"""#1006 - Texture Coordinate > Object is OBJECT-local (CPU + GPU).

Cycles svm/tex_coord.h NODE_TEXCO_OBJECT applies object_inverse_position_transform to
the shading point. The addon bakes world transforms into the vertices, so the engine
used the world point (Object coordinate procedurals slid / rotated / scaled with the
object's placement). The addon now bakes matrix_world^-1 back onto every triangle as
per-vertex object-local positions (set_objects_object_transform); the hit interpolates
them (exact: the transform is affine).

Camera-model-free gates (the same renderer on both sides):
  * similarity invariance: applying one transform M (rotation, uniform scale,
    translation) to the object AND the camera, with M^-1 as the object frame,
    reproduces the identity render; without the frame (world point) it does not;
  * two copies of one mesh (B = A rotated 180 deg about the camera axis, each with
    its own frame - flattened duplis / instances) render point-symmetric.
"""
import math

import numpy as np
import pytest

astroray = pytest.importorskip("astroray")
from base_helpers import create_renderer, render_image, setup_camera  # noqa: E402

_TEX = "issue1006_noise"
_HALF = 0.5


def _has_cuda_gpu(r):
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


def _rot(axis, deg):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    t = math.radians(deg)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(t) * k + (1 - math.cos(t)) * (k @ k)


def _affine(lin, trans):
    m = np.eye(4)
    m[:3, :3] = lin
    m[:3, 3] = trans
    return m


def _xf(m, p):
    return list((m @ np.append(np.asarray(p, float), 1.0))[:3])


def _render(backend, objects, cam=np.eye(4), use_frames=True, size=96):
    """objects: list of 4x4 object->world matrices applied to one local quad."""
    r = create_renderer()
    if backend == "gpu":
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU available - #1006 GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    else:
        r.set_use_gpu(False)
    r.set_seed(11)
    r.set_background_color([1.0, 1.0, 1.0])
    r.create_procedural_texture(_TEX, "noise_perlin", [3.0, 2.0, 0.5, 2.0, 0, 1, 0, 0, 1],
                                "OBJECT")
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {"texture": _TEX})
    local = [[-_HALF, -_HALF, 0.0], [_HALF, -_HALF, 0.0], [_HALF, _HALF, 0.0],
             [-_HALF, _HALF, 0.0]]
    for m in objects:
        a, b, c, d = (_xf(m, v) for v in local)
        n = list(m[:3, :3] @ np.array([0.0, 0.0, 1.0]))
        n = list(np.asarray(n) / np.linalg.norm(n))
        before = r.scene_object_count()
        r.add_triangle(a, b, c, mat, [], [], [], n, n, n)
        r.add_triangle(a, c, d, mat, [], [], [], n, n, n)
        if use_frames:
            inv = np.linalg.inv(m)[:3, :].reshape(-1)
            assert r.set_objects_object_transform(
                before, r.scene_object_count(), [float(x) for x in inv]) == 2
    setup_camera(r, look_from=_xf(cam, [0, 0, 3]), look_at=_xf(cam, [0, 0, 0]),
                 vup=list(cam[:3, :3] @ np.array([0.0, 1.0, 0.0])),
                 vfov=30, width=size, height=size)
    return np.asarray(render_image(r, samples=8, max_depth=2, apply_gamma=False))


def _corr(a, b, mask):
    x, y = a[mask].ravel(), b[mask].ravel()
    return float(np.corrcoef(x, y)[0, 1])


def _quad_mask(img):
    # Background radiance is 1.0; the textured quad (albedo noise <= ~0.8) is darker.
    return img.mean(axis=-1) < 0.95


_M = _affine(_rot([0.3, 0.5, 0.8], 35.0) * 1.7, [0.7, -1.2, 0.4])


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_object_coords_follow_the_object(backend):
    ref = _render(backend, [np.eye(4)])
    moved = _render(backend, [_M], cam=_M)
    mask = _quad_mask(ref) & _quad_mask(moved)
    assert mask.sum() > 2000, f"quad too small on screen ({mask.sum()} px)"
    assert _corr(ref, moved, mask) > 0.99
    assert float(np.abs(ref - moved)[mask].mean()) < 0.01


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_world_point_fallback_is_not_attached(backend):
    """Non-vacuity: without the object frame the texture reads the world point, so the
    same similarity transform moves the pattern relative to the object."""
    ref = _render(backend, [np.eye(4)])
    moved = _render(backend, [_M], cam=_M, use_frames=False)
    mask = _quad_mask(ref) & _quad_mask(moved)
    assert _corr(ref, moved, mask) < 0.5


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_copies_keep_their_own_frame(backend):
    a = _affine(np.eye(3) * 0.6, [-0.55, 0.0, 0.0])
    b = _affine(_rot([0, 0, 1], 180.0), [0.0, 0.0, 0.0]) @ a
    img = _render(backend, [a, b])
    flip = img[::-1, ::-1]
    mask = _quad_mask(img) & _quad_mask(flip)
    assert mask.sum() > 1000
    assert _corr(img, flip, mask) > 0.98
    # The same copies without frames are not symmetric (world point differs).
    img_w = _render(backend, [a, b], use_frames=False)
    assert _corr(img_w, img_w[::-1, ::-1], mask) < 0.5

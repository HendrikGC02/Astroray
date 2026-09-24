"""#847 — Generated coordinates in OBJECT space, per object (CPU + GPU).

The engine used to evaluate Generated from one axis-aligned WORLD box per
texture (set_texture_generated_bbox): wrong for rotated objects and last-writer-
wins for a material shared by several objects. Cycles evaluates Generated per
vertex in object space (blender/mesh.cpp mesh_texture_space). The engine now
bakes a per-object world->Generated affine onto each triangle's vertices
(set_objects_generated_transform) and interpolates it at the hit.

Pixel-exact gates without camera modelling (same camera, same geometry):
  * identity object frame == the old bbox frame (0 deg regression);
  * a 90 deg object rotation of a scale-4 checker inverts every cell
    (pointwise: parity changes by 3 - 2*floor(4u), always odd);
  * two objects sharing one material each keep their own frame.
"""

import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera

_RED, _BLUE = (0.9, 0.1, 0.1), (0.1, 0.1, 0.9)
_TEX = "issue847_checker"


def _has_cuda_gpu(r):
    return bool(astroray.__features__.get("cuda", False)) and bool(getattr(r, "gpu_available", False))


def _affine(center, deg, half, z_off=0.05):
    """World -> Generated for a quad object at `center`, rotated `deg` about z,
    texspace = its own square (loc 0, size half): g = R^-1 (p - c) * 0.5/half + 0.5."""
    a = np.radians(deg)
    rinv = np.array([[np.cos(a), np.sin(a), 0.0], [-np.sin(a), np.cos(a), 0.0], [0.0, 0.0, 1.0]])
    lin = rinv * (0.5 / half)
    off = 0.5 - lin @ np.asarray(center, float)
    # Default plane at g.z = 0.55, off the z*4 = 2 checker face; the on-face
    # case (Blender's default flat plane, g.z = 0.5) has its own test below.
    off[2] += z_off
    return [float(x) for x in np.hstack([lin, off[:, None]]).reshape(-1)]


def _add_quad(r, mat, center, half):
    cx, cy = center[0], center[1]
    A, B = [cx - half, cy - half, 0.0], [cx + half, cy - half, 0.0]
    C, D = [cx + half, cy + half, 0.0], [cx - half, cy + half, 0.0]
    n = [0.0, 0.0, 1.0]
    r.add_triangle(A, B, C, mat, [], [], [], n, n, n)
    r.add_triangle(A, C, D, mat, [], [], [], n, n, n)


def _render(backend, objects, bbox=None, z_off=0.05):
    """objects: list of (center, deg, half, use_affine)."""
    r = create_renderer()
    if backend == "gpu":
        if not _has_cuda_gpu(r):
            pytest.skip("No CUDA GPU available — #847 GPU leg runs on the RTX box.")
        r.set_use_gpu(True)
    else:
        r.set_use_gpu(False)
    r.set_seed(7)
    r.set_background_color([0.8, 0.8, 0.8])
    r.create_procedural_texture(_TEX, "checker", [*_RED, *_BLUE, 4.0], "GENERATED")
    if bbox is not None:
        r.set_texture_generated_bbox(_TEX, *bbox)
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {"texture": _TEX})
    for center, deg, half, use_affine in objects:
        before = r.scene_object_count()
        _add_quad(r, mat, center, half)
        if use_affine:
            assert r.set_objects_generated_transform(
                before, r.scene_object_count(), _affine(center, deg, half, z_off)) == 2
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=96, height=96)
    return np.asarray(render_image(r, samples=16, max_depth=2, apply_gamma=False))


def _cells(img):
    """+1 red cell, -1 blue cell, 0 background / ambiguous edge pixel. Cells
    give |r-b| ~ 0.6; the grey background's spectral noise stays below 0.3."""
    d = img[..., 0] - img[..., 2]
    return np.where(d > 0.3, 1, np.where(d < -0.3, -1, 0))


def _agree(a, b, invert=False):
    # Same camera on both sides, so no edge band here. The Cycles gate
    # (astra_run/batchY/y847/run_gate.py) excludes a 1-px band around cell
    # edges for the camera (W-1)/W pixel-mapping bug (fixed by lane u845); that
    # fix should shrink edge mismatches further.
    m = (a != 0) & (b != 0)
    assert m.sum() > 500, f"too few textured pixels ({m.sum()})"
    return float(np.mean((a[m] == -b[m]) if invert else (a[m] == b[m])))


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_identity_object_frame_matches_bbox_frame(backend):
    old = _render(backend, [((0, 0, 0), 0.0, 1.0, False)], bbox=([-1, -1, -1.1], [2, 2, 2]))
    new = _render(backend, [((0, 0, 0), 0.0, 1.0, True)])
    assert _agree(_cells(old), _cells(new)) >= 0.99


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_rotated_object_rotates_generated(backend):
    c0 = _cells(_render(backend, [((0, 0, 0), 0.0, 1.0, True)]))
    c90 = _cells(_render(backend, [((0, 0, 0), 90.0, 1.0, True)]))
    assert np.unique(c0[c0 != 0]).size == 2, "checker not visible"
    assert _agree(c0, c90, invert=True) >= 0.97


@pytest.mark.parametrize("backend", ["cpu", "gpu"])
def test_shared_material_objects_keep_own_frames(backend):
    left, right = ((-0.65, 0, 0), 0.0, 0.5, True), ((0.65, 0, 0), 90.0, 0.5, True)
    both = _cells(_render(backend, [left, right]))
    only_l = _cells(_render(backend, [left]))
    only_r = _cells(_render(backend, [right]))
    assert _agree(both[:, :48], only_l[:, :48]) >= 0.97
    assert _agree(both[:, 48:], only_r[:, 48:]) >= 0.97


def test_gpu_matches_cpu_on_checker_face():
    """Flat plane at Generated z = 0.5 with scale 4: z*4 = 2 lies on a checker
    face. Cycles/CPU round it down (svm_checker epsilon); the GPU voxel fetch
    used to pick the upper cell and invert every cell."""
    obj = [((0, 0, 0), 30.0, 1.0, True)]
    cpu = _cells(_render("cpu", obj, z_off=0.0))
    gpu = _cells(_render("gpu", obj, z_off=0.0))
    assert _agree(cpu, gpu) >= 0.97
"""pkg88 Phase C.0 — deformation motion blur validation gates.

Gate structure per .astroray_plan/packages/pkg88-motion-blur.md:
- A3-style regression: motion API with end == start must render BIT-IDENTICAL
  to the static bulk API (the renderer interpolates over [0,1] always; shutter
  scaling is the addon's Phase-B job — it bakes shutter-scaled deltas, so
  shutter=0 means zero deltas, i.e. exactly this no-op case).
- B/C1 streak: a translating emissive triangle's rendered footprint extends
  well beyond its static silhouette.
- BVH union-AABB: a fast mover is visible at BOTH time extremes (the grown
  AABB keeps it traversable across the whole shutter).
- GPU parity: the CUDA path (MW megakernel) blurs like the CPU (per-channel
  mean ratio) — exercised on the RTX box, skipped on CI.
"""

from __future__ import annotations

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray  # noqa: E402
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

W = H = 96
SPP = 64
DEPTH = 3

_EMPTY_UV = np.zeros((0, 0, 3, 2), dtype=np.float32)
_EMPTY_N = np.zeros((0, 3, 3), dtype=np.float32)


def _make_renderer(use_gpu=False):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(42)
    if use_gpu:
        r.set_use_gpu(True)
    r.setup_camera([0.5, 0.3, 3.0], [0.5, 0.3, 0.0], [0.0, 1.0, 0.0],
                   45.0, W / H, 0.0, 3.0, W, H)
    return r


def _emissive_tri(r):
    return r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 4.0})


def _tri_arrays(offset_x=0.0):
    pos = np.array([[[0.0, 0.0, 0.0], [0.35, 0.0, 0.0], [0.175, 0.55, 0.0]]],
                   dtype=np.float32)
    pos[:, :, 0] += offset_x
    mids = np.array([0], dtype=np.int32)   # patched by caller
    mpass = np.array([0], dtype=np.int32)
    return pos, mids, mpass


def _render(r):
    img = np.asarray(r.render(SPP, DEPTH, None, True), dtype=np.float32)
    return img.reshape(H, W, 3) if img.ndim == 1 else img


def _lit_columns(img, thresh=0.02):
    return int(np.sum(np.any(np.mean(img, axis=2) > thresh, axis=0)))


def test_motion_noop_is_bit_identical():
    """end == start through the motion API must match the static bulk API
    bit-for-bit (the interpolation collapses; no RNG stream change)."""
    r_static = _make_renderer()
    mat_s = _emissive_tri(r_static)
    pos, mids, mpass = _tri_arrays()
    mids[:] = mat_s
    r_static.add_triangles_bulk(pos, mids, mpass, 0, _EMPTY_UV, [], _EMPTY_N)

    r_motion = _make_renderer()
    mat_m = _emissive_tri(r_motion)
    pos2, mids2, mpass2 = _tri_arrays()
    mids2[:] = mat_m
    r_motion.add_triangles_bulk_motion(pos2, pos2.copy(), mids2, mpass2, 0,
                                       _EMPTY_UV, [], _EMPTY_N)

    img_s = _render(r_static)
    img_m = _render(r_motion)
    assert np.array_equal(img_s, img_m), (
        "motion API with end == start must be bit-identical to the static API "
        f"(max abs diff {np.max(np.abs(img_s - img_m)):.3g})"
    )


def test_translating_triangle_streak_cpu():
    """Gate B/C1: a triangle translating +1.2 in X renders a footprint much
    wider than its static silhouette."""
    r_static = _make_renderer()
    mat = _emissive_tri(r_static)
    pos, mids, mpass = _tri_arrays()
    mids[:] = mat
    r_static.add_triangles_bulk(pos, mids, mpass, 0, _EMPTY_UV, [], _EMPTY_N)
    static_cols = _lit_columns(_render(r_static))

    r_motion = _make_renderer()
    mat2 = _emissive_tri(r_motion)
    pos2, mids2, mpass2 = _tri_arrays()
    mids2[:] = mat2
    pos_end = pos2.copy()
    pos_end[:, :, 0] += 1.2
    r_motion.add_triangles_bulk_motion(pos2, pos_end, mids2, mpass2, 0,
                                       _EMPTY_UV, [], _EMPTY_N)
    motion_cols = _lit_columns(_render(r_motion))

    assert static_cols > 0, "static triangle not visible — scene/camera broken"
    assert motion_cols > static_cols * 2, (
        f"motion streak too narrow: {motion_cols} lit columns vs static "
        f"{static_cols} (expected >2x)"
    )


def test_bvh_union_aabb_correctness():
    """The union AABB must keep a fast mover traversable at BOTH extremes:
    the streak must include the static (t=0) footprint AND columns near the
    t=1 destination."""
    r = _make_renderer()
    mat = _emissive_tri(r)
    pos, mids, mpass = _tri_arrays()
    mids[:] = mat
    pos_end = pos.copy()
    pos_end[:, :, 0] += 1.2
    r.add_triangles_bulk_motion(pos, pos_end, mids, mpass, 0,
                                _EMPTY_UV, [], _EMPTY_N)
    img = _render(r)

    gray = np.mean(img, axis=2)
    lit = np.any(gray > 0.02, axis=0)
    lit_idx = np.nonzero(lit)[0]
    assert lit_idx.size > 0, "moving triangle entirely invisible"
    # Camera is centered at x=0.5 looking at the [0, 1.55] world span; the
    # start silhouette lives in the left half, the end silhouette in the right.
    assert lit_idx.min() < W // 2 - 5, (
        f"t=0 extreme missing (leftmost lit column {lit_idx.min()})"
    )
    assert lit_idx.max() > W // 2 + 5, (
        f"t=1 extreme missing (rightmost lit column {lit_idx.max()})"
    )


_NEEDS_CUDA = pytest.mark.skipif(
    AVAILABLE and not astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build — GPU half verified on the RTX box",
)


@_NEEDS_CUDA
def test_motion_blur_gpu_streak_and_parity():
    """GPU half: the CUDA path (MW megakernel) must blur — streak wider than
    the GPU static silhouette — and motion must shift scene energy the SAME
    way on both backends. The gate is a ratio-of-ratios (motion/static per
    backend) so the pre-existing small CPU-vs-GPU pipeline energy offset
    (independent RNG, spectral vs RGB upsampling) doesn't confound it
    (memory: ssim-wrong-gate-for-independent-rng)."""
    def static_scene(use_gpu):
        r = _make_renderer(use_gpu=use_gpu)
        m = _emissive_tri(r)
        p, mi, mp = _tri_arrays()
        mi[:] = m
        r.add_triangles_bulk(p, mi, mp, 0, _EMPTY_UV, [], _EMPTY_N)
        return _render(r)

    def motion_scene(use_gpu):
        r = _make_renderer(use_gpu=use_gpu)
        m = _emissive_tri(r)
        p, mi, mp = _tri_arrays()
        mi[:] = m
        p_end = p.copy()
        p_end[:, :, 0] += 1.2
        r.add_triangles_bulk_motion(p, p_end, mi, mp, 0, _EMPTY_UV, [], _EMPTY_N)
        return _render(r)

    img_gpu_static = static_scene(use_gpu=True)
    img_gpu_motion = motion_scene(use_gpu=True)
    img_cpu_static = static_scene(use_gpu=False)
    img_cpu_motion = motion_scene(use_gpu=False)

    gpu_cols = _lit_columns(img_gpu_motion)
    gpu_static_cols = _lit_columns(img_gpu_static)
    assert gpu_cols > gpu_static_cols * 2, (
        f"GPU motion streak too narrow: {gpu_cols} vs static {gpu_static_cols} "
        "(d_motionVertices not reaching the kernel?)"
    )

    # Motion-induced energy change must match across backends.
    gpu_shift = (img_gpu_motion.mean() + 1e-5) / (img_gpu_static.mean() + 1e-5)
    cpu_shift = (img_cpu_motion.mean() + 1e-5) / (img_cpu_static.mean() + 1e-5)
    rel = gpu_shift / cpu_shift
    assert 0.93 < rel < 1.08, (
        f"motion/static energy shift diverges across backends: GPU {gpu_shift:.4f} "
        f"vs CPU {cpu_shift:.4f} (ratio {rel:.4f})"
    )

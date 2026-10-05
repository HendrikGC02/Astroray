"""#1037 -- a ray leaving a curve segment must not re-hit that segment.

Thick-curve hits (pbrt-v3 flattened test) sit at the centreline depth, INSIDE
the tube, so before #1037 every continuation/shadow ray whose closest approach
lay ahead re-entered the same fibre. Cycles skips the originating primitive
(kernel/bvh/util.h intersection_skip_self); Astroray now does the same on the
CPU (Ray::self) and the GPU software BVH (skipPrim); #1092 widened the skip to
the whole strand (Cycles prim_index is the curve). See
.astroray_plan/docs/1037-curve-self-intersection-research.md.

Gates (single straight one-segment strand, so no other geometry can be hit):
  1. Depth 2 adds nothing over depth 1 under a point light: a continuation ray
     leaving the only segment has nothing left to hit. Before #1037 the
     self-hit vertex added several times the direct light.
  2. White furnace: unpigmented hair (Ap sums to 1) in a uniform white world
     reads ~1 (no re-entry, no self-shadowing).
  3. GPU matches CPU on both.
"""

from __future__ import annotations

import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray not built")

W = H = 48
SPP = 256
SEED = 103701


def _gpu_ok() -> bool:
    return AVAILABLE and bool(astroray.__features__.get("cuda", False))


STRAIGHT = [(0.0, 1.2, 0.0), (0.0, -1.2, 0.0)]
# Two segments (n points -> n-1) meeting at a sharp bend.
VEE = [(-0.9, 1.2, 0.0), (0.0, -0.9, 0.0), (0.9, 1.2, 0.0)]


def _scene(gpu: bool, furnace: bool, depth: int, strand=STRAIGHT):
    r = astroray.Renderer()
    r.set_background_color([1.0, 1.0, 1.0] if furnace else [0.0, 0.0, 0.0])
    hair = r.create_material(
        "principled_hair", [0.5, 0.5, 0.5],
        {"roughness": 0.3, "radial_roughness": 0.3, "coat": 0.0,
         "parametrization": "melanin", "melanin": 0.0, "melanin_redness": 0.0})
    pts = np.asarray(strand, dtype=np.float32)
    r.add_curves_bulk(pts, np.full(len(pts), 0.3, dtype=np.float32), [len(pts)], hair)
    if not furnace:
        r.add_point_light([2.2, 1.4, 1.6], {"mode": "rgb", "color": [1, 1, 1]}, 200.0, 0.0)
    r.setup_camera([0.0, 0.0, 4.2], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                   40.0, 1.0, 0.0, 4.2, W, H)
    r.set_integrator("path_tracer")
    r.set_integrator_param("max_depth", depth)
    r.set_curve_thick_mode(True)
    r.set_adaptive_sampling(False)  # independent-RNG parity (#1036)
    if gpu:
        r.set_use_gpu(True)
    r.set_seed(SEED)
    return np.asarray(r.render(SPP, depth, None, False), dtype=np.float32)


def _hair_mask():
    # Pixels whose primary ray hits the strand: furnace image differs from the
    # pure white background there (depth 1 = no continuation, ~0.8 on hair).
    img = _scene(False, True, 1)
    return np.abs(img - 1.0).sum(-1) > 1e-3


BACKENDS = [False] + ([True] if _gpu_ok() else [])


@pytest.mark.parametrize("gpu", BACKENDS, ids=lambda g: "gpu" if g else "cpu")
def test_continuation_does_not_re_enter_own_segment(gpu):
    d1 = float(_scene(gpu, False, 1).sum())
    d2 = float(_scene(gpu, False, 2).sum())
    print(f"  depth1={d1:.4f} depth2={d2:.4f} ratio={d2 / d1:.4f}")
    assert d1 > 1.0
    assert d2 / d1 < 1.01, (
        f"#1037: depth 2 adds {d2 / d1 - 1:.1%} over depth 1 on a lone strand; "
        "continuation rays re-hit their own curve segment")


@pytest.mark.parametrize("gpu", BACKENDS, ids=lambda g: "gpu" if g else "cpu")
def test_adjacent_segment_of_same_strand_skipped(gpu):
    # #1092: Cycles' intersection_skip_self compares prim_index, which for a curve is
    # the CURVE index (bvh/build.cpp add_reference_curves), so a ray leaving one segment
    # of a bent strand never re-hits the strand's other segments either. Re-pinned from
    # the #1037 assertion "adjacent segment stays hittable" (depth2/depth1 = 1.11-1.16),
    # which encoded the segment-only skip; the strand-level gate vs Cycles 5.2 is in
    # test_issue1092_strand_self_skip.py.
    d1 = float(_scene(gpu, False, 1, VEE).sum())
    d2 = float(_scene(gpu, False, 2, VEE).sum())
    print(f"  vee depth1={d1:.4f} depth2={d2:.4f} ratio={d2 / d1:.4f}")
    assert d2 / d1 < 1.01, "continuation off a bent strand must not re-hit the same strand"


@pytest.mark.parametrize("gpu", BACKENDS, ids=lambda g: "gpu" if g else "cpu")
def test_hair_white_furnace(gpu):
    mask = _hair_mask()
    img = _scene(gpu, True, 6)
    m = img[mask].mean(0)
    print(f"  furnace hair mean RGB = {np.round(m, 4)} over {int(mask.sum())} px")
    assert mask.sum() > 100
    assert np.all(m > 0.95) and np.all(m < 1.02), m


@pytest.mark.skipif(not _gpu_ok(), reason="needs the CUDA build")
def test_gpu_matches_cpu_point_light():
    c = _scene(False, False, 4).sum((0, 1))
    g = _scene(True, False, 4).sum((0, 1))
    ratio = g / c
    print(f"  GPU/CPU RGB = {np.round(ratio, 4)}")
    assert np.all(np.abs(ratio - 1.0) < 0.03), ratio

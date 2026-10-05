"""#947 GPU twin of test_947_motion_blur_shading_normals.py (RTX box; skipped without CUDA).

The wavefront intersect stage's gpu_triangle_hit_motion must light a rotating plate with
the normal at ray time, flat (facet recomputed from the interpolated vertices) and smooth
(normals / normals_end lerped by time) -- the same time-average gate as the CPU test.
"""

from __future__ import annotations

import pytest

import test_947_motion_blur_shading_normals as t

pytestmark = pytest.mark.skipif(
    not t.AVAILABLE or not t.astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build -- verified on the RTX box",
)


def test_gpu_flat_motion_triangle_normal_follows_pose():
    ref = t._reference_mean(use_gpu=True)
    got = t._motion_mean(smooth=False, use_gpu=True)
    assert abs(got / ref - 1.0) < 0.08, f"GPU flat motion plate {got:.4f} vs time-average {ref:.4f}"


def test_gpu_smooth_motion_triangle_normals_follow_pose():
    ref = t._reference_mean(use_gpu=True)
    got = t._motion_mean(smooth=True, use_gpu=True)
    assert abs(got / ref - 1.0) < 0.08, f"GPU smooth motion plate {got:.4f} vs time-average {ref:.4f}"

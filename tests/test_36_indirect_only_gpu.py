"""#36 GPU twin of test_36_indirect_only.py (RTX box; skipped without CUDA).

The wavefront intersect stage re-traces camera rays past GPRIM_FLAG_INDIRECT_ONLY prims;
reflections and shadow rays still hit them. Same three gates as the CPU test.
"""

from __future__ import annotations

import pytest

import test_36_indirect_only as t

pytestmark = pytest.mark.skipif(
    not t.AVAILABLE or not t.astroray.__features__.get("cuda", False),
    reason="CUDA feature not in this build -- verified on the RTX box",
)


def test_gpu_indirect_only_invisible_to_camera():
    imgs = t._scene_renders("mirror", use_gpu=True)
    vis, ind, ab = (t.roi(imgs[m], *t.SPHERE_UV) for m in ("visible", "indirect", "absent"))
    assert t.red_fraction(vis) > 0.6, f"visible red sphere should be red, got {vis}"
    assert abs(t.red_fraction(ind) - t.red_fraction(ab)) < 0.05, (ind, ab)
    assert t.red_fraction(ind) < 0.45, f"indirect-only sphere visible to the camera: {ind}"


def test_gpu_indirect_only_visible_in_mirror_reflection():
    imgs = t._scene_renders("mirror", use_gpu=True)
    vis, ind, ab = (t.roi(imgs[m], *t.MIRROR_UV) for m in ("visible", "indirect", "absent"))
    assert t.red_fraction(vis) > t.red_fraction(ab) + 0.1, "scene broken: mirror does not show the sphere"
    assert t.red_fraction(ind) > t.red_fraction(ab) + 0.1, f"indirect-only sphere missing from the mirror: {ind} vs {ab}"
    assert abs(t.red_fraction(ind) - t.red_fraction(vis)) < 0.1, (ind, vis)


def test_gpu_indirect_only_casts_shadow():
    imgs = t._scene_renders("shadow", use_gpu=True)
    vis, ind, ab = (t.roi(imgs[m], *t.SHADOW_UV, half=3).sum() for m in ("visible", "indirect", "absent"))
    assert vis < 0.6 * ab, f"scene broken: sphere casts no shadow ({vis} vs {ab})"
    assert ind < 0.6 * ab, f"indirect-only sphere casts no shadow ({ind} vs unshadowed {ab})"
    assert abs(ind - vis) < 0.3 * ab, (ind, vis)

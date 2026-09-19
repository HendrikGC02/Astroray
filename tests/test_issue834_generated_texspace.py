"""#834 — Generated coordinates follow Blender's mesh texture space.

Cycles reads Generated from the mesh texture space (intern/cycles/blender/
mesh.cpp mesh_texture_space: texspace_location / texspace_size), and Blender's
BKE_mesh_texspace_calc forces a zero-size axis to size 1. So for a flat plane
Generated z = 0.5, not 0 (the addon's old bounding-box frame gave 0). With the
Cycles checker (svm_checker: floor(((p*scale) + 1e-6) * 0.999999)) that flips
the cell parity for scales 3, 4, 7, 8, ...; 3-D noise on a plane differs too.

Measured on the issue's scene (checker scale 6): no parity flip there (z*6 = 3
floors to 2, even, like 0); both backends match the Cycles checker formula at
97-99 % of ground pixels. The remaining <= 1 px boundary offset is the camera's
(res - 1) raster divisor (pkg212 spec, deferred), not Generated coordinates.
"""

import types

import numpy as np
import pytest

from _batch_a_stub import load_addon


class _M:
    """Minimal 4x4 affine for `matrix @ mathutils.Vector(c)` in the helper."""

    def __init__(self, A=np.eye(3), t=(0.0, 0.0, 0.0)):
        self.A, self.t = np.asarray(A, float), np.asarray(t, float)

    def __matmul__(self, v):
        return self.A @ np.array([v.x, v.y, v.z], float) + self.t


def _plane(loc=(0.0, 0.0, 0.0), size=(4.0, 4.0, 1.0), half=4.0):
    bb = [(sx * half, sy * half, 0.0) for sx in (-1, 1) for sy in (-1, 1) for _ in (0, 1)]
    return types.SimpleNamespace(
        data=types.SimpleNamespace(texspace_location=loc, texspace_size=size),
        bound_box=bb)


def _blender_generated(co_local, loc, size):
    """Cycles mesh_texture_space: generated = (co - loc) * 0.5 / size + 0.5."""
    return (np.asarray(co_local) - np.asarray(loc)) * 0.5 / np.asarray(size) + 0.5


def _engine_generated(p_world, bmin, bsize):
    """advanced_features.h CoordMode::Generated: (p - genMin) / genSize."""
    return (np.asarray(p_world) - np.asarray(bmin)) / np.asarray(bsize)


def _checker_parity(g, scale):
    """Cycles kernel/svm/checker.h svm_checker verbatim (Blender 5.2): the same
    formula on both sides, so the tests compare the Generated COORDINATES."""
    sp = (np.asarray(g, np.float32) * np.float32(scale) + np.float32(1e-6)) * np.float32(0.999999)
    xi, yi, zi = (abs(int(np.floor(c))) for c in sp)
    return (xi % 2 == yi % 2) == (zi % 2)


@pytest.fixture
def helper(monkeypatch):
    return load_addon(monkeypatch, "issue834")._generated_texspace_bbox


def test_flat_plane_generated_z_is_half(helper):
    bmin, bsize = helper(_plane(), _M())
    assert bmin == pytest.approx([-4.0, -4.0, -1.0])
    assert bsize == pytest.approx([8.0, 8.0, 2.0])
    for co in ((1.3, -2.1, 0.0), (-3.9, 3.9, 0.0), (0.0, 0.0, 0.0)):
        np.testing.assert_allclose(_engine_generated(co, bmin, bsize),
                                   _blender_generated(co, (0, 0, 0), (4, 4, 1)), atol=1e-9)


def test_transformed_plane_matches_blender_local_generated(helper):
    A, t = np.diag([2.0, 3.0, 1.0]), (5.0, -1.0, 0.5)
    loc, size = (0.2, -0.1, 0.0), (4.0, 4.0, 1.0)
    bmin, bsize = helper(_plane(loc=loc, size=size), _M(A, t))
    for co in ((1.3, -2.1, 0.0), (-3.5, 3.0, 0.0)):
        world = A @ np.asarray(co) + np.asarray(t)
        np.testing.assert_allclose(_engine_generated(world, bmin, bsize),
                                   _blender_generated(co, loc, size), atol=1e-9)


@pytest.mark.parametrize("scale", [3.0, 4.0, 6.0, 7.0])
def test_checker_parity_matches_blender_on_flat_plane(helper, scale):
    bmin, bsize = helper(_plane(), _M())
    rng = np.random.default_rng(834)
    for x, y in rng.uniform(-3.9, 3.9, size=(64, 2)):
        co = (x, y, 0.0)
        want = _checker_parity(_blender_generated(co, (0, 0, 0), (4, 4, 1)), scale)
        got = _checker_parity(_engine_generated(co, bmin, bsize), scale)
        assert got == want, (scale, co)


def test_without_texspace_falls_back_to_bound_box(helper):
    obj = _plane()
    obj.data = types.SimpleNamespace()
    bmin, bsize = helper(obj, _M())
    assert bmin[:2] == pytest.approx([-4.0, -4.0])
    assert bsize[:2] == pytest.approx([8.0, 8.0])


def test_zero_texspace_axis_follows_bke_rule(helper):
    """BKE_mesh_texspace_calc: a zero-size axis becomes 1 (never a 1e-6 divide)."""
    bmin, bsize = helper(_plane(size=(4.0, 4.0, 0.0)), _M())
    assert bmin[2] == pytest.approx(-1.0) and bsize[2] == pytest.approx(2.0)


@pytest.mark.xfail(strict=True, reason=(
    "#834 scope: rotated objects -- the engine's Generated frame is an axis-aligned "
    "WORLD box (genMin/genSize), so Blender's object-space texture space cannot be "
    "expressed for a rotated object; needs a per-texture affine (#847)."))
def test_rotated_plane_matches_blender_local_generated(helper):
    a = np.radians(30.0)
    A = np.array([[np.cos(a), -np.sin(a), 0.0], [np.sin(a), np.cos(a), 0.0], [0.0, 0.0, 1.0]])
    bmin, bsize = helper(_plane(), _M(A))
    co = (1.3, -2.1, 0.0)
    np.testing.assert_allclose(_engine_generated(A @ np.asarray(co), bmin, bsize),
                               _blender_generated(co, (0, 0, 0), (4, 4, 1)), atol=1e-6)

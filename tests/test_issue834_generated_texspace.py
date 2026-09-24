"""#834 — Generated coordinates follow Blender's mesh texture space.

Cycles reads Generated from the mesh texture space (intern/cycles/blender/
mesh.cpp mesh_texture_space: texspace_location / texspace_size), and Blender's
BKE_mesh_texspace_calc forces a zero-size axis to size 1. So for a flat plane
Generated z = 0.5, not 0 (the addon's old bounding-box frame gave 0). With the
Cycles checker (svm_checker: floor(((p*scale) + 1e-6) * 0.999999)) that flips
the cell parity for scales 3, 4, 7, 8, ...; 3-D noise on a plane differs too.

Measured on the issue's scene (checker scale 6): no parity flip there (z*6 = 3
floors to 2, even, like 0); both backends match the Cycles checker formula at
97-99 % of ground pixels. The remaining <= 1 px boundary offset was the camera's
(res - 1) raster divisor (fixed in #845), not Generated coordinates.
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

    def __getitem__(self, r):
        """mathutils.Matrix row access (4x4 homogeneous)."""
        return list(self.A[r]) + [self.t[r]] if r < 3 else [0.0, 0.0, 0.0, 1.0]


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


@pytest.fixture
def affine_helper(monkeypatch):
    return load_addon(monkeypatch, "issue847")._generated_texspace_affine


def _engine_generated_affine(p_world, m12):
    """#847 engine frame: g = M * p (row-major 3x4 world -> Generated)."""
    return np.asarray(m12, float).reshape(3, 4) @ np.append(np.asarray(p_world, float), 1.0)


def _rot(axis, deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return {"z": np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]),
            "x": np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])}[axis]


def test_rotated_plane_matches_blender_local_generated(affine_helper):
    """#847: a rotated object's Generated follows its OBJECT-space texture space."""
    A = _rot("z", 30.0)
    m12 = affine_helper(_plane(), _M(A))
    co = (1.3, -2.1, 0.0)
    np.testing.assert_allclose(_engine_generated_affine(A @ np.asarray(co), m12),
                               _blender_generated(co, (0, 0, 0), (4, 4, 1)), atol=1e-6)


@pytest.mark.parametrize("deg", [0.0, 45.0, 90.0])
@pytest.mark.parametrize("axis", ["z", "x"])
def test_affine_matches_blender_under_rotation_scale_translation(affine_helper, deg, axis):
    A = _rot(axis, deg) @ np.diag([2.0, 0.5, 3.0])
    t = (5.0, -1.0, 0.5)
    loc, size = (0.2, -0.1, 0.3), (4.0, 3.0, 1.5)
    m12 = affine_helper(_plane(loc=loc, size=size), _M(A, t))
    rng = np.random.default_rng(847)
    for co in rng.uniform(-3.5, 3.5, size=(16, 3)):
        world = A @ co + np.asarray(t)
        np.testing.assert_allclose(_engine_generated_affine(world, m12),
                                   _blender_generated(co, loc, size), atol=1e-9)


def test_affine_bound_box_fallback_and_zero_axis(affine_helper):
    obj = _plane()
    obj.data = types.SimpleNamespace()
    m12 = affine_helper(obj, _M(_rot("z", 90.0)))
    # bound_box x,y in [-4,4], z flat -> 1e-6 size guard (no divide blow-up).
    world = _rot("z", 90.0) @ np.array([2.0, -4.0, 0.0])
    np.testing.assert_allclose(_engine_generated_affine(world, m12)[:2], [0.75, 0.0], atol=1e-9)
    m12 = affine_helper(_plane(size=(4.0, 4.0, 0.0)), _M())
    assert _engine_generated_affine((0.0, 0.0, 0.0), m12)[2] == pytest.approx(0.5)


def test_affine_singular_matrix_returns_none(affine_helper):
    assert affine_helper(_plane(), _M(np.diag([1.0, 0.0, 1.0]))) is None

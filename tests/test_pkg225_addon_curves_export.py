"""pkg225 Stage 6 — `extract_curves_bulk` headless validation.

A fake Blender ``Curves`` data-block implementing the documented ``foreach_get``
contract is fed through the helper; the world-space control points, per-point
radii, and per-strand counts are checked against a hand-computed reference. No
Blender, no engine .pyd (mirrors test_bulk_geometry_helper).
"""
import os
import sys

import numpy as np
import pytest

_ADDON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "blender_addon")
if _ADDON_DIR not in sys.path:
    sys.path.insert(0, _ADDON_DIR)
import _bulk_geometry  # noqa: E402


class _Coll:
    def __init__(self, n, attrs):
        self._n = n
        self._attrs = {k: np.asarray(v, dtype=np.float64) for k, v in attrs.items()}

    def __len__(self):
        return self._n

    def foreach_get(self, name, buf):
        if name not in self._attrs:
            raise RuntimeError(f"no attribute {name}")
        buf[:] = self._attrs[name]


class _Curves:
    def __init__(self, points, offsets, curve_offsets=True, attributes=None):
        self.points = points
        self.attributes = attributes
        if curve_offsets:
            self.curve_offsets = _Coll(len(offsets), {"value": offsets})
        else:
            self.curve_offsets = None
            counts = np.diff(offsets)
            self.curves = [type("S", (), {"points_length": int(c)})() for c in counts]


def _matrix(scale=2.0):
    # Uniform scale 2 + translation, so radius*scale and positions*scale+t are exact.
    M = np.eye(4, dtype=np.float64)
    M[0, 0] = M[1, 1] = M[2, 2] = scale
    M[:3, 3] = [1.0, -2.0, 0.5]
    return M


def _make_curves(**kw):
    # 2 strands: 5 points then 3 points = 8 points.
    pos = np.array([[0, 0, 0], [0, 1, 0], [0, 2, 0], [0, 3, 0], [0, 4, 0],
                    [1, 0, 0], [1, 1, 0], [1, 2, 0]], dtype=np.float64)
    rad = np.array([0.01, 0.02, 0.03, 0.02, 0.01, 0.05, 0.04, 0.03], dtype=np.float64)
    pts = _Coll(8, {"position": pos.reshape(-1), "radius": rad})
    offsets = np.array([0, 5, 8], dtype=np.int64)
    return _Curves(pts, offsets, **kw), pos, rad, [5, 3]


@pytest.mark.parametrize("use_offsets", [True, False])
def test_extract_curves_bulk_matches_reference(use_offsets):
    curves, pos, rad, counts = _make_curves(curve_offsets=use_offsets)
    M = _matrix(scale=2.0)
    out_pos, out_rad, out_counts = _bulk_geometry.extract_curves_bulk(curves, M)

    assert out_counts == counts
    assert out_pos.shape == (8, 3)
    assert out_pos.dtype == np.float32 and out_rad.dtype == np.float32

    ref_pos = pos @ M[:3, :3].T + M[:3, 3]
    np.testing.assert_allclose(out_pos, ref_pos, rtol=1e-5, atol=1e-5)
    # Uniform scale 2 -> radius doubles.
    np.testing.assert_allclose(out_rad, rad * 2.0, rtol=1e-5, atol=1e-6)


def test_extract_curves_bulk_drops_degenerate_strand():
    # 3 strands with counts [2, 1, 3] -> the 1-point strand (and its point) drop.
    pos = np.array([[0, 0, 0], [0, 1, 0],       # strand A (2)
                    [5, 5, 5],                   # strand B (1) - degenerate
                    [1, 0, 0], [1, 1, 0], [1, 2, 0]], dtype=np.float64)  # strand C (3)
    rad = np.full(6, 0.02, dtype=np.float64)
    pts = _Coll(6, {"position": pos.reshape(-1), "radius": rad})
    curves = _Curves(pts, np.array([0, 2, 3, 6], dtype=np.int64))
    out_pos, out_rad, out_counts = _bulk_geometry.extract_curves_bulk(curves, np.eye(4))
    assert out_counts == [2, 3]
    assert out_pos.shape == (5, 3)          # the lone degenerate point is gone
    # Surviving points are strands A + C, in order (the [5,5,5] point removed).
    expected = np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0], [1, 1, 0], [1, 2, 0]],
                        dtype=np.float32)
    np.testing.assert_allclose(out_pos, expected, atol=1e-6)


def test_extract_curves_bulk_radius_fallback():
    # No 'radius' point attribute and no attributes collection -> default radius.
    pos = np.array([[0, 0, 0], [0, 1, 0], [0, 2, 0]], dtype=np.float64)
    pts = _Coll(3, {"position": pos.reshape(-1)})  # no "radius"
    curves = _Curves(pts, np.array([0, 3], dtype=np.int64), attributes=None)
    _, out_rad, out_counts = _bulk_geometry.extract_curves_bulk(
        curves, np.eye(4), default_radius=0.007)
    assert out_counts == [3]
    np.testing.assert_allclose(out_rad, np.full(3, 0.007, dtype=np.float32), atol=1e-7)


def test_extract_curves_bulk_empty():
    curves = _Curves(_Coll(0, {"position": np.zeros(0), "radius": np.zeros(0)}),
                     np.array([0], dtype=np.int64))
    out_pos, out_rad, out_counts = _bulk_geometry.extract_curves_bulk(curves, np.eye(4))
    assert out_counts == [] and out_pos.shape == (0, 3) and out_rad.shape == (0,)

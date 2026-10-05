"""#947 -- motion-blurred rotating geometry must shade with the normal at ray time.

A moving triangle interpolated its VERTICES by ray time but kept the shutter-open
facet / vertex normals, so a rotating diffuse plate was lit as if frozen at one
pose (corpus ``v2_camera_geometry`` vane read 0.84x / 0.40x of Cycles). Cycles
interpolates the motion vertex normals (``motion_triangle_smooth_normal``) and
recomputes the facet normal from the interpolated vertices
(``motion_triangle_normal``), Apache-2.0.

Gate: a diffuse plate rotating -15..+15 deg about Y under a side light renders, at
its centre, the time-average of static renders over the same poses -- through the
flat path (no normals) and the smooth path (``normals`` + ``normals_end``). The
motion plate used to render ~40 % off (it was lit at the shutter-open pose).
"""

from __future__ import annotations

import math

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

W = H = 64
SPP = 96
ALPHA = math.radians(15.0)
_EMPTY_UV = np.zeros((0, 0, 3, 2), dtype=np.float32)
_EMPTY_N = np.zeros((0, 3, 3), dtype=np.float32)


def _renderer(use_gpu=False):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_use_gpu(use_gpu)  # explicit: a CUDA build otherwise auto-selects the GPU
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(7)
    r.setup_camera(look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=30,
                   aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=W, height=H)
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 20.0})
    r.add_sphere([3.0, 0.0, 2.0], 0.5, light)  # off-screen side light, 56 deg from +Z
    plate = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    return r, plate


def _plate(phi):
    """(2,3,3) quad corners, a unit plate rotated by `phi` about Y; +Z faces the camera."""
    c, s = math.cos(phi), math.sin(phi)
    def p(x, y):
        return [x * c, y, -x * s]
    quad = [p(-0.5, -0.5), p(0.5, -0.5), p(0.5, 0.5), p(-0.5, 0.5)]
    return np.array([[quad[0], quad[1], quad[2]], [quad[0], quad[2], quad[3]]], dtype=np.float32)


def _normals(phi):
    n = [math.sin(phi), 0.0, math.cos(phi)]
    return np.tile(np.array(n, dtype=np.float32), (2, 3, 1))


def _center(r):
    img = np.asarray(r.render(SPP, 3, None, False), dtype=np.float32).reshape(H, W, 3)
    return float(img[H // 2 - 6:H // 2 + 6, W // 2 - 6:W // 2 + 6].mean())


def _ids(plate):
    return np.array([plate, plate], dtype=np.int32), np.zeros(2, dtype=np.int32)


def _static_mean(phi, use_gpu=False):
    r, plate = _renderer(use_gpu)
    mids, mpass = _ids(plate)
    r.add_triangles_bulk(_plate(phi), mids, mpass, 0, _EMPTY_UV, [], _EMPTY_N)
    return _center(r)


def _reference_mean(use_gpu=False):
    # The motion API lerps the corner positions over t in [0,1]: the plate's tilt angle
    # is atan(tan(alpha) * (2t - 1)). Average static renders over bin-centred t.
    ts = (np.arange(9) + 0.5) / 9.0
    return float(np.mean([_static_mean(math.atan(math.tan(ALPHA) * (2 * t - 1)), use_gpu) for t in ts]))


def _motion_mean(smooth, with_end_normals=True, use_gpu=False):
    r, plate = _renderer(use_gpu)
    mids, mpass = _ids(plate)
    if smooth:
        n0, n1 = _normals(-ALPHA), _normals(+ALPHA)
        extra = (n1,) if with_end_normals else ()
        r.add_triangles_bulk_motion(_plate(-ALPHA), _plate(+ALPHA), mids, mpass, 0,
                                    _EMPTY_UV, [], n0, *extra)
    else:
        r.add_triangles_bulk_motion(_plate(-ALPHA), _plate(+ALPHA), mids, mpass, 0,
                                    _EMPTY_UV, [], _EMPTY_N)
    return _center(r)


def test_flat_motion_triangle_normal_follows_pose():
    ref = _reference_mean()
    got = _motion_mean(smooth=False)
    assert ref > 0.0
    assert abs(got / ref - 1.0) < 0.08, f"flat motion plate {got:.4f} vs time-average {ref:.4f}"


def test_smooth_motion_triangle_normals_follow_pose():
    ref = _reference_mean()
    got = _motion_mean(smooth=True)
    assert abs(got / ref - 1.0) < 0.08, f"smooth motion plate {got:.4f} vs time-average {ref:.4f}"


def test_missing_normals_end_keeps_legacy_static_normals():
    """Omitting normals_end keeps the pre-#947 behaviour (start normals) -- the test
    above is non-vacuous: without end normals the plate is mis-lit."""
    ref = _reference_mean()
    legacy = _motion_mean(smooth=True, with_end_normals=False)
    assert abs(legacy / ref - 1.0) > 0.2, f"legacy {legacy:.4f} vs {ref:.4f}"

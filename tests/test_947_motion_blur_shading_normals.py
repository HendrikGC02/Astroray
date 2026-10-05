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


def _blend_normal_reference(w, u, v, normalise_first):
    """Shading normal at t = 0.5 and barycentrics (w, u, v) of a triangle whose vertex
    normals rotate non-rigidly over the shutter: n0 +Z -> +X, n1 / n2 stay +Z. The
    first-hit normal AOV is the sample-0 hit, whose time is halton(1, 2) = 0.5."""
    n0 = np.array([0.5, 0.0, 0.5])  # lerp((0,0,1), (1,0,0), 0.5)
    if normalise_first:
        n0 = n0 / np.linalg.norm(n0)
    n = w * n0 + (u + v) * np.array([0.0, 0.0, 1.0])
    return n / np.linalg.norm(n)


def test_smooth_motion_normals_normalise_each_lerped_vertex_normal_first():
    """Cycles motion_triangle_smooth_normal normalises each time-lerped vertex normal
    BEFORE the barycentric blend. With a non-rigid rotation (one vertex normal swings
    90 deg, the others stay) the lerped vertex normal shortens to 0.707 mid-shutter, so
    blending first would under-weight the rotating vertex. A huge static triangle keeps
    the barycentrics at the view centre constant, w = 0.495 (v0), u = 0.495, v = 0.0099."""
    wpx = hpx = 32
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_use_gpu(False)
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(5)
    r.setup_camera(look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0], vfov=40,
                   aspect_ratio=1.0, aperture=0.0, focus_dist=5.0, width=wpx, height=hpx)
    mat = r.create_material("lambertian", [0.8, 0.8, 0.8], {})
    pos = np.array([[[-100, -1, 0], [100, -1, 0], [0, 100, 0]]], dtype=np.float32)
    n_open = np.array([[[0, 0, 1], [0, 0, 1], [0, 0, 1]]], dtype=np.float32)
    n_end = np.array([[[1, 0, 0], [0, 0, 1], [0, 0, 1]]], dtype=np.float32)
    r.add_triangles_bulk_motion(pos, pos, np.array([mat], dtype=np.int32),
                                np.zeros(1, dtype=np.int32), 0, _EMPTY_UV, [], n_open, n_end)
    r.render(4, 2, None, False)
    nb = np.asarray(r.get_normal_buffer(), dtype=np.float32).reshape(hpx, wpx, 3)
    got = nb[hpx // 2 - 2:hpx // 2 + 3, wpx // 2 - 2:wpx // 2 + 3].reshape(-1, 3).mean(axis=0)
    got = got / np.linalg.norm(got)
    v = 1.0 / 101.0
    u = 0.5 - 0.5 * v
    new = _blend_normal_reference(1.0 - u - v, u, v, True)
    old = _blend_normal_reference(1.0 - u - v, u, v, False)
    assert abs(new[0] - old[0]) > 0.03, "scene does not separate the two blends"
    assert abs(got[0] - new[0]) < 0.4 * abs(new[0] - old[0]), (got, new, old)


def test_motion_stride_guard_rejects_more_than_two_steps():
    """The 6-Vec3 per-triangle stride (verts + normals) and the GPU twin are valid only
    for motionSteps == 2; Triangle::setMotionData must reject a layout it cannot index.
    (Not reachable from Python -- add_triangles_bulk_motion always passes 2 -- so this
    pins the guard in source.)"""
    from pathlib import Path
    src = (Path(__file__).parent.parent / "include" / "astroray" / "shapes.h").read_text(encoding="utf-8")
    body = src[src.index("void setMotionData("):]
    body = body[:body.index("}")]
    assert "steps != 2 && steps != 1" in body and "invalid_argument" in body

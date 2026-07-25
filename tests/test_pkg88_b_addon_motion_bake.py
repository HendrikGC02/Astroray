"""pkg88 Phase B — object motion blur addon bake, renderer-integration half.

The addon-wiring tests (test_blender_object_motion_blur_wiring.py) mock bpy
and only prove convert_scene/convert_objects call the right renderer method
with the right arrays. This file closes the loop: it feeds
`_bulk_geometry.mesh_world_positions` output -- the actual function the
addon uses to compute `add_triangles_bulk_motion`'s `positions_end` argument
-- into the REAL compiled renderer, and checks it produces a real motion
streak (same style as tests/test_pkg88_c0_deformation.py's C.0 gates, which
this Phase-B path sits on top of). No bpy/Blender needed: `_bulk_geometry.py`
is dependency-free (numpy + a fake foreach_get mesh), matching its existing
test convention in test_bulk_geometry_helper.py.

NOTE ON `get_motion_buffer()`: the dispatch for this package suggested
asserting against `Renderer.get_motion_buffer()`. That binding is pkg72's
per-pixel camera-only screen-space motion-vector AOV
(`Camera::motionBuffer`, populated by comparing two full `render()` calls'
camera reprojection -- see module/blender_module.cpp:1833 and
include/raytracer.h:3133-3153, "Camera-only motion: animated geometry is
out of scope per the pkg72 spec"). It is unrelated to object-vertex motion
and would read all-zero here regardless of whether add_triangles_bulk_motion
blurred correctly. This file asserts on the actual rendered streak instead,
matching test_pkg88_c0_deformation.py's established gate style.
"""
from __future__ import annotations

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

import sys
import os
_ADDON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "blender_addon")
if _ADDON_DIR not in sys.path:
    sys.path.insert(0, _ADDON_DIR)
import _bulk_geometry  # noqa: E402 -- pure module, no bpy needed

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


class _Coll:
    """Same fake-Blender-collection stub as test_bulk_geometry_helper.py."""
    def __init__(self, n, attrs):
        self._n = n
        self._attrs = {k: np.asarray(v, dtype=np.float64) for k, v in attrs.items()}

    def __len__(self):
        return self._n

    def foreach_get(self, name, buf):
        buf[:] = self._attrs[name]


class _Mesh:
    def __init__(self, vertices, tri_verts):
        self.vertices = vertices
        self.loop_triangles = _Coll(len(tri_verts) // 3,
                                    {"vertices": tri_verts})


def _triangle_mesh(offset_x=0.0):
    """A single upward-pointing triangle, matching
    test_pkg88_c0_deformation.py's _tri_arrays geometry."""
    verts = np.array([[0.0, 0.0, 0.0], [0.35, 0.0, 0.0], [0.175, 0.55, 0.0]],
                     dtype=np.float64)
    verts[:, 0] += offset_x
    return _Mesh(_Coll(3, {"co": verts.reshape(-1)}), [0, 1, 2])


def _make_renderer():
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.0, 0.0, 0.0])
    r.set_seed(42)
    r.setup_camera([0.5, 0.3, 3.0], [0.5, 0.3, 0.0], [0.0, 1.0, 0.0],
                   45.0, W / H, 0.0, 3.0, W, H)
    return r


def _render(r):
    img = np.asarray(r.render(SPP, DEPTH, None, True), dtype=np.float32)
    return img.reshape(H, W, 3) if img.ndim == 1 else img


def _lit_columns(img, thresh=0.02):
    return int(np.sum(np.any(np.mean(img, axis=2) > thresh, axis=0)))


def _identity4():
    return np.eye(4, dtype=np.float32)


def _translate4(dx, dy=0.0, dz=0.0):
    M = np.eye(4, dtype=np.float32)
    M[:3, 3] = [dx, dy, dz]
    return M


def test_static_object_addon_bake_matches_static_bulk_render():
    """Requirement 2, renderer half: a STATIC object baked via
    mesh_world_positions(mesh, current_matrix) at BOTH ends (the same
    matrix, i.e. what convert_objects would use for a non-moving object if
    it were fed through the motion API) must render bit-identical to the
    static add_triangles_bulk path -- but convert_objects' real behaviour
    is to skip the motion API entirely for static objects (see
    test_convert_objects_static_object_uses_bulk_not_motion). This proves
    the underlying math is safe even in the API's declared no-op case,
    matching the pkg88-C.0 gate `test_motion_noop_is_bit_identical`."""
    mesh = _triangle_mesh()
    matrix = _identity4()
    mat_id = 0

    r_static = _make_renderer()
    mat_s = r_static.create_material("light", [1.0, 1.0, 1.0], {"intensity": 4.0})
    positions = _bulk_geometry.mesh_world_positions(mesh, matrix)
    r_static.add_triangles_bulk(
        positions, np.array([mat_s], dtype=np.int32), np.array([0], dtype=np.int32),
        0, _EMPTY_UV, [], _EMPTY_N)

    r_noop_motion = _make_renderer()
    mat_m = r_noop_motion.create_material("light", [1.0, 1.0, 1.0], {"intensity": 4.0})
    positions_start = _bulk_geometry.mesh_world_positions(mesh, matrix)
    positions_end = _bulk_geometry.mesh_world_positions(mesh, matrix)  # same matrix
    r_noop_motion.add_triangles_bulk_motion(
        positions_start, positions_end, np.array([mat_m], dtype=np.int32),
        np.array([0], dtype=np.int32), 0, _EMPTY_UV, [], _EMPTY_N)

    img_static = _render(r_static)
    img_motion = _render(r_noop_motion)
    assert np.array_equal(img_static, img_motion), (
        "mesh_world_positions fed through the motion API with start==end "
        f"must render bit-identical (max abs diff "
        f"{np.max(np.abs(img_static - img_motion)):.3g})"
    )


def test_moving_object_addon_bake_produces_streak():
    """The addon's actual shutter-close position function
    (mesh_world_positions), fed with the object's CURRENT matrix
    (positions_start) and its matrix at shutter-close (positions_end, here
    a +1.2 world-x translation), must render a footprint much wider than
    the static silhouette -- the same B/C1 gate test_pkg88_c0_deformation.py
    already established for the raw add_triangles_bulk_motion API, now
    exercised through the addon's actual position-computation path."""
    mesh = _triangle_mesh()
    matrix_start = _identity4()
    matrix_end = _translate4(1.2)

    r_static = _make_renderer()
    mat_s = r_static.create_material("light", [1.0, 1.0, 1.0], {"intensity": 4.0})
    positions = _bulk_geometry.mesh_world_positions(mesh, matrix_start)
    r_static.add_triangles_bulk(
        positions, np.array([mat_s], dtype=np.int32), np.array([0], dtype=np.int32),
        0, _EMPTY_UV, [], _EMPTY_N)
    static_cols = _lit_columns(_render(r_static))

    r_motion = _make_renderer()
    mat_m = r_motion.create_material("light", [1.0, 1.0, 1.0], {"intensity": 4.0})
    positions_start = _bulk_geometry.mesh_world_positions(mesh, matrix_start)
    positions_end = _bulk_geometry.mesh_world_positions(mesh, matrix_end)
    r_motion.add_triangles_bulk_motion(
        positions_start, positions_end, np.array([mat_m], dtype=np.int32),
        np.array([0], dtype=np.int32), 0, _EMPTY_UV, [], _EMPTY_N)
    motion_cols = _lit_columns(_render(r_motion))

    assert static_cols > 0, "static triangle not visible -- scene/camera broken"
    assert motion_cols > static_cols * 2, (
        f"addon-bake motion streak too narrow: {motion_cols} lit columns vs "
        f"static {static_cols} (expected >2x)"
    )

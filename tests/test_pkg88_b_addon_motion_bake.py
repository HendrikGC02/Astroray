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

The final test in this file
(`test_end_to_end_shutter_position_streaks`) drives the REAL
convert_scene -> convert_objects pipeline against the REAL compiled renderer
for all three shutter positions, because the hand-fed tests above cannot
catch a wrong shutter-open POSE -- they supply the matrices directly instead
of letting convert_scene's t_start/t_end arithmetic pick them.
"""
from __future__ import annotations

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

import sys
import os
import types
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
    """The addon's actual position function (mesh_world_positions), fed a
    shutter-open and a shutter-close matrix, must render a footprint much
    wider than the static silhouette -- the same B/C1 gate
    test_pkg88_c0_deformation.py established for the raw
    add_triangles_bulk_motion API, now exercised through the addon's actual
    position-computation path.

    NOTE: this test hand-picks both matrices, so it can NOT detect the
    pipeline feeding a wrong shutter-open pose. That is what
    test_end_to_end_shutter_position_streaks below exists for."""
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


# ---------------------------------------------------------------------------
# End-to-end: real convert_scene -> convert_objects -> real renderer.
# ---------------------------------------------------------------------------

# Reuse the mocked-bpy addon loader from the wiring test module (tests/ is on
# sys.path). Only bpy is mocked -- the renderer below is the REAL engine.
from test_blender_object_motion_blur_wiring import (  # noqa: E402
    _load_blender_addon, _make_settings,
)

E2E_W = E2E_H = 128
BASE_FRAME = 10
SHUTTER = 0.5
# World-units of travel per frame. With SHUTTER=0.5 every shutter position
# sweeps SPEED*SHUTTER = 1.2 world units, so all three must streak the SAME
# width -- only the streak's CENTRE differs. That is the discriminator: the
# pre-fix code produced a half-width CENTER streak and no END streak at all.
SPEED = 2.4


class _E2EMatrix:
    """4x4 translate-in-x matrix exposing everything convert_objects touches:
    [r][c] indexing (_matrices_differ), __array__ (mesh_to_bulk_arrays /
    mesh_world_positions), and to_3x3() (normal matrix)."""
    def __init__(self, dx):
        self.dx = float(dx)

    @property
    def _rows(self):
        return [[1.0, 0.0, 0.0, self.dx],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0]]

    def __getitem__(self, i):
        return self._rows[i]

    def __array__(self, dtype=None):
        return np.array(self._rows, dtype=dtype or np.float32)

    def to_3x3(self):
        class _M3:
            def inverted_safe(self_):
                return self_
            def transposed(self_):
                return self_
            def __array__(self_, dtype=None):
                return np.eye(3, dtype=dtype or np.float32)
        return _M3()

    def copy(self):
        return _E2EMatrix(self.dx)


class _E2EUVLayers:
    active = None
    def __iter__(self):
        return iter([])


class _E2EMesh:
    """Fake Blender mesh over one triangle, supporting the foreach_get calls
    mesh_to_bulk_arrays and mesh_world_positions make. corner_normals is
    deliberately absent so the helper's normal fallback (empty) kicks in."""
    def __init__(self):
        verts = np.array([[0.0, 0.0, 0.0], [0.35, 0.0, 0.0], [0.175, 0.55, 0.0]],
                         dtype=np.float64)
        self.vertices = _Coll(3, {"co": verts.reshape(-1)})
        self.loop_triangles = _Coll(1, {"vertices": [0, 1, 2],
                                        "loops": [0, 1, 2],
                                        "material_index": [0]})
        self.loops = _Coll(3, {})
        self.uv_layers = _E2EUVLayers()

    def calc_loop_triangles(self):
        pass


class _E2EMovingObj:
    """matrix_world tracks scene.frame_current + frame_subframe, exactly as a
    real depsgraph re-cook would after frame_set()."""
    def __init__(self, name, scene, mesh):
        self.name = name
        self.type = 'MESH'
        self.data = mesh
        self.pass_index = 0
        self._scene = scene
        self.material_slots = [types.SimpleNamespace(
            material=types.SimpleNamespace(name="Emit"))]

    @property
    def matrix_world(self):
        f = float(self._scene.frame_current) + float(self._scene.frame_subframe)
        return _E2EMatrix((f - BASE_FRAME) * SPEED)


def _e2e_render_streak(monkeypatch, position):
    """Run the REAL convert_scene for `position` against the REAL renderer and
    return (lit_column_indices, image)."""
    addon = _load_blender_addon(monkeypatch, renderer_cls=object)
    engine = addon.CustomRaytracerRenderEngine()

    settings = _make_settings(device_mode='cpu')  # keeps pkg114 instancing off
    scene = types.SimpleNamespace(
        custom_raytracer=settings,
        # Real seed (not 0 -- that is the engine's random sentinel) so the
        # render is deterministic.
        cycles=types.SimpleNamespace(seed=42, use_animated_seed=False,
                                     film_exposure=1.0,
                                     pixel_filter_type='GAUSSIAN',
                                     filter_width=1.5,
                                     film_transparent_glass=False),
        render=types.SimpleNamespace(use_motion_blur=True,
                                     motion_blur_shutter=SHUTTER,
                                     motion_blur_position=position,
                                     film_transparent=False),
        camera=None,          # camera blur is pkg88-A; isolate object blur here
        frame_current=BASE_FRAME,
        frame_subframe=0.0,
    )

    def _frame_set(frame, subframe):
        scene.frame_current = frame
        scene.frame_subframe = subframe
    scene.frame_set = _frame_set

    mesh = _E2EMesh()
    obj = _E2EMovingObj('Mover', scene, mesh)
    inst = types.SimpleNamespace(object=obj, matrix_world=obj.matrix_world,
                                 is_instance=False)
    depsgraph = types.SimpleNamespace(
        scene=scene, objects=[obj], object_instances=[inst],
        update=lambda: None, mode='RENDER',
        view_layer=types.SimpleNamespace(name='ViewLayer'),
    )

    renderer = astroray.Renderer()
    renderer.set_integrator("path_tracer")

    # Only the pieces unrelated to object geometry are stubbed; convert_objects
    # itself runs for real.
    engine.setup_camera = lambda sc, r, w, h: r.setup_camera(
        [0.0, 0.25, 4.5], [0.0, 0.25, 0.0], [0.0, 1.0, 0.0],
        45.0, 1.0, 0.0, 4.5, E2E_W, E2E_H)
    engine.convert_materials = lambda dg, r: {
        "Emit": r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 4.0})}
    engine.convert_lights = lambda dg, r: None
    engine.setup_world = lambda sc, r: r.set_background_color([0.0, 0.0, 0.0])

    engine.convert_scene(depsgraph, renderer, E2E_W, E2E_H)

    img = np.asarray(renderer.render(SPP, DEPTH, None, True), dtype=np.float32)
    img = img.reshape(E2E_H, E2E_W, 3) if img.ndim == 1 else img
    lit = np.any(np.mean(img, axis=2) > 0.02, axis=0)
    return np.nonzero(lit)[0], img


@pytest.mark.parametrize("position", ['START', 'CENTER', 'END'])
def test_end_to_end_shutter_position_streaks(monkeypatch, position):
    """Every shutter position must produce a real motion streak through the
    full convert_scene -> convert_objects -> renderer path.

    Regression guard. The first implementation sampled only t_end and reused
    the current-frame pose as positions_start, which made END a SILENT NO-OP
    (t_end == frame there, so the object never registered as moving) and
    halved the CENTER arc. A test covering only CENTER would still have let
    the END bug ship, so all three are parameterised."""
    lit_idx, _img = _e2e_render_streak(monkeypatch, position)
    assert lit_idx.size > 0, f"{position}: object entirely invisible"

    width = int(lit_idx.max() - lit_idx.min() + 1)
    # Measured at this camera: correct sweep = 49 columns for ALL three
    # positions. The pre-fix build gave CENTER 30 (half arc) and END 13 --
    # and 13 is exactly the static silhouette, i.e. motion never fired.
    # Threshold 40 sits clear of both failure modes and of the correct value.
    assert width > 40, (
        f"{position}: streak only {width} columns wide (lit {lit_idx.min()}.."
        f"{lit_idx.max()}) -- motion blur did not fire for this shutter position"
    )


def test_end_to_end_shutter_positions_shift_streak_centre(monkeypatch):
    """The three shutter positions sweep the SAME arc width but centred at
    different places: END covers [frame-shutter, frame], CENTER straddles
    frame, START covers [frame, frame+shutter]. So the streak centre must be
    strictly ordered END < CENTER < START, and the widths must match.

    This is the assertion that pins positions_start to the shutter-OPEN pose:
    if it were the current-frame pose, START would be unchanged, CENTER would
    collapse to half width, and END would not streak at all."""
    centres, widths = {}, {}
    for position in ('START', 'CENTER', 'END'):
        lit_idx, _ = _e2e_render_streak(monkeypatch, position)
        centres[position] = float(lit_idx.min() + lit_idx.max()) / 2.0
        widths[position] = int(lit_idx.max() - lit_idx.min() + 1)

    # Measured (correct): END 48.0 < CENTER 68.0 < START 89.0, ~20.5 px apart,
    # matching the 0.6-world-unit shutter offset at this camera's ~34 px/unit.
    assert centres['END'] < centres['CENTER'] < centres['START'], (
        f"shutter positions must shift the streak monotonically, got {centres}"
    )
    # All three sweep SPEED*SHUTTER world units, so widths must agree (measured
    # spread 0; the pre-fix build gave START 49 / CENTER 30 / END 13).
    spread = max(widths.values()) - min(widths.values())
    assert spread <= 6, (
        f"all shutter positions sweep the same arc width; got {widths} "
        f"(spread {spread} px) -- a short CENTER/END streak means "
        "positions_start is not the shutter-open pose"
    )

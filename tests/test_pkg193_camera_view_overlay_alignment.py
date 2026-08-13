"""pkg193 — camera-view overlay vs preview/F12 render alignment gate.

Diagnosis (measured on Blender 5.1, see fixture
tests/data/pkg193_blender51_camera_capture.json):

  * VIEWPORT (numpad-0): the addon dropped the off-center frustum terms
    window_matrix[0][2]/[1][2] and re-derived the image-plane shift from the
    camera datablock + view_camera_offset. That matched Blender's overlay only
    for AUTO-landscape / no-shift; with lens shift or a non-AUTO sensor fit the
    rendered cube corners were 25-223 px off the overlay.
  * F12 render: the datablock path passed camera.shift_x/shift_y raw, without
    Blender's film-fit `viewfac` scaling, so a shifted / non-square camera
    framed the cube 20-42 px off Blender's own world_to_camera_view (= what
    Cycles renders), breaking compositing trust.

Fix (blender_addon/__init__.py::_apply_camera):
  * viewport: invert OpenGL perspective_m4 from window_matrix directly —
    vfov=2atan(1/m11), aspect=m11/m00, shiftX=m02/2, shiftY=m12/2. Astroray's
    symmetric-vfov+shift camera reproduces any axis-aligned perspective frustum
    exactly (4 dof), so this is a lossless match to the overlay.
  * F12: scale datablock shift by Blender's film-fit factor (Cycles
    blender_camera_viewplane, Apache-2.0): shiftX=shift_x*viewfac/winx,
    shiftY=shift_y*viewfac/winy, viewfac = winx for HORIZONTAL fit else winy.

These tests replay REAL captured Blender 5.1 camera-view state (window_matrix,
view_matrix, cube corners, and both the window_matrix@view_matrix overlay pixels
and world_to_camera_view render pixels) through the actual addon code and assert
the addon's projected corners agree with Blender to <= 1 px across the four
condition axes: aspect match/mismatch, lens shift on/off, viewport zoom/pan
on/off, sensor_fit AUTO/HORIZONTAL/VERTICAL.
"""

import importlib.util
import json
import math
import sys
import types
from pathlib import Path

import numpy as np
import pytest

FIXTURE = Path(__file__).parent / "data" / "pkg193_blender51_camera_capture.json"
TOL_PX = 1.0


# ---------------------------------------------------------------------------
# Addon loader + stubs (mirrors test_addon_viewport_camera_vfov.py)
# ---------------------------------------------------------------------------

def _load_blender_addon(monkeypatch):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _RenderEngineBase:
        def report(self, *_a, **_k): return None
        def update_progress(self, *_a, **_k): return None
        def update_stats(self, *_a, **_k): return None
        def test_break(self): return False

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _RenderEngineBase
    bpy_module.types = bpy_types_module
    for name in ("BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
                 "PointerProperty", "FloatVectorProperty", "EnumProperty"):
        setattr(bpy_props_module, name, lambda **_kwargs: None)
    bpy_module.props = bpy_props_module
    bpy_module.path = types.SimpleNamespace(abspath=lambda p: p)

    shader_blending_module = types.ModuleType("shader_blending")
    shader_blending_module.blend_shader_specs = {}
    shader_blending_module.add_shader_specs = {}

    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda values: values

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.material_registry_names = lambda: ["lambertian"]
    astroray_module.pass_registry_names = list

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    module_path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_pkg193", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _Vec3:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Quat:
    def __matmul__(self, vec):
        return _Vec3(vec[0], vec[1], vec[2])


class _CamMatrix4:
    def __init__(self, loc=(0.0, 0.0, 0.0)):
        self._loc = loc

    @property
    def translation(self):
        return _Vec3(*self._loc)

    def decompose(self):
        return _Vec3(*self._loc), _Quat(), _Vec3(1.0, 1.0, 1.0)


class _WinMatrix:
    """Supports mat[i][j] indexing over a captured 4x4 list-of-lists."""
    def __init__(self, rows):
        self.rows = rows

    def __getitem__(self, i):
        return self.rows[i]


class _RecordingRenderer:
    def __init__(self):
        self.setup_camera_calls = []

    def setup_camera(self, *args, **_kw):
        self.setup_camera_calls.append(args)


def _make_camera_obj(cam):
    dof = types.SimpleNamespace(use_dof=False, aperture_fstop=0.0,
                                focus_object=None, focus_distance=10.0)
    data = types.SimpleNamespace(
        type='PERSP', lens=cam['lens'], sensor_fit=cam['sensor_fit'],
        sensor_width=cam['sensor_width'], sensor_height=cam['sensor_height'],
        shift_x=cam['shift_x'], shift_y=cam['shift_y'], dof=dof,
    )
    return types.SimpleNamespace(data=data, matrix_world=_CamMatrix4())


# ---------------------------------------------------------------------------
# Projection helpers (Astroray camera forward projection)
# ---------------------------------------------------------------------------

def _basis_from_view(view_matrix):
    world = np.linalg.inv(np.array(view_matrix, dtype=np.float64))
    loc = world[:3, 3]
    upv = world[:3, 1]
    fwd = -world[:3, 2]
    w = -fwd / np.linalg.norm(fwd)
    vup = upv / np.linalg.norm(upv)
    u = np.cross(vup, w); u /= np.linalg.norm(u)
    v = np.cross(w, u)
    return loc, u, v, w


def _astroray_project(loc, u, v, w, vfov_deg, aspect, shift_x, shift_y, W, H, P):
    vh = 2.0 * math.tan(math.radians(vfov_deg) / 2.0)
    vw = aspect * vh
    dvec = np.array(P) - loc
    depth = float(np.dot(dvec, -w))
    a = float(np.dot(dvec, u)); b = float(np.dot(dvec, v))
    s = 0.5 - shift_x + a / (depth * vw)
    t = 0.5 - shift_y + b / (depth * vh)
    return np.array([s * W, t * H])


def _load_conditions():
    data = json.loads(FIXTURE.read_text())
    return [c for c in data["conditions"] if "error" not in c]


CONDITIONS = _load_conditions()
COND_IDS = [c["name"] for c in CONDITIONS]


# ---------------------------------------------------------------------------
# Viewport (numpad-0) overlay alignment
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cond", CONDITIONS, ids=COND_IDS)
def test_viewport_overlay_corner_alignment(monkeypatch, cond):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    W, H = cond["region"]
    cam_obj = _make_camera_obj(cond["camera"])
    rv3d = types.SimpleNamespace(
        window_matrix=_WinMatrix(cond["window_matrix"]),
        view_perspective='CAMERA',
        view_camera_zoom=cond["view_camera_zoom"],
        view_camera_offset=tuple(cond["view_camera_offset"]),
    )
    scene = types.SimpleNamespace(camera=cam_obj)
    context = types.SimpleNamespace(region_data=rv3d, space_data=None, scene=scene)

    engine._setup_viewport_camera(renderer, context, W, H)
    args = renderer.setup_camera_calls[-1]
    vfov, aspect, shift_x, shift_y = args[3], args[4], args[9], args[10]

    loc, u, v, w = _basis_from_view(cond["view_matrix"])
    max_err = 0.0
    for P, ref in zip(cond["corners_world"], cond["ref_px"]):
        if ref is None:
            continue
        px = _astroray_project(loc, u, v, w, vfov, aspect, shift_x, shift_y, W, H, P)
        max_err = max(max_err, float(np.linalg.norm(px - np.array(ref))))
    assert max_err <= TOL_PX, (
        f"[{cond['name']}] viewport overlay corner offset {max_err:.3f} px > {TOL_PX} px"
    )


# ---------------------------------------------------------------------------
# F12 render framing vs Blender world_to_camera_view (compositing trust)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cond", CONDITIONS, ids=COND_IDS)
def test_f12_render_corner_alignment(monkeypatch, cond):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    W, H = cond["render_res"]
    cam_obj = _make_camera_obj(cond["camera"])
    engine._apply_camera(renderer, cam_obj, W, H)  # rv3d=None → F12 datablock path
    args = renderer.setup_camera_calls[-1]
    vfov, aspect, shift_x, shift_y = args[3], args[4], args[9], args[10]

    loc, u, v, w = _basis_from_view(cond["view_matrix"])
    max_err = 0.0
    for P, w2c in zip(cond["corners_world"], cond["world_to_camera_view"]):
        ref = np.array([w2c[0] * W, w2c[1] * H])
        px = _astroray_project(loc, u, v, w, vfov, aspect, shift_x, shift_y, W, H, P)
        max_err = max(max_err, float(np.linalg.norm(px - ref)))
    assert max_err <= TOL_PX, (
        f"[{cond['name']}] F12 render corner offset {max_err:.3f} px > {TOL_PX} px "
        f"vs Blender world_to_camera_view"
    )


def test_fixture_covers_all_four_condition_axes():
    """Guard: the fixture must exercise aspect match+mismatch, lens shift on+off,
    zoom/pan on+off, and sensor_fit AUTO/HORIZONTAL/VERTICAL."""
    fits = {c["camera"]["sensor_fit"] for c in CONDITIONS}
    assert {"AUTO", "HORIZONTAL", "VERTICAL"} <= fits
    assert any(c["camera"]["shift_x"] or c["camera"]["shift_y"] for c in CONDITIONS)
    assert any(not (c["camera"]["shift_x"] or c["camera"]["shift_y"]) for c in CONDITIONS)
    assert any(c["view_camera_zoom"] != 0.0 for c in CONDITIONS)
    assert any(c["view_camera_offset"] != [0.0, 0.0] for c in CONDITIONS)
    aspects = {tuple(c["render_res"]) for c in CONDITIONS}
    assert len(aspects) >= 2

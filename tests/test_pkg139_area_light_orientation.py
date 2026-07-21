"""pkg139: AREA-light orientation convention + world strength-0 background fix.

Root cause (verified in code, `blender_addon/__init__.py` `convert_lights`
AREA branch): the engine's `AreaLight` emits along its normal `u x v`
(`include/astroray/lights/area_light.h:59`), but Blender/Cycles area lights
emit along the light's local -Z axis (Cycles `BlenderSync::sync_light`,
`intern/cycles/blender/light.cpp`: `axisu` = local X, `axisv` = local Y,
emission direction = -Z of the light transform) -- the same convention the
addon itself already uses for SUN (`__init__.py:3941`) and SPOT
(`__init__.py:3971`). Before the fix, `axis_u = local +X`, `axis_v = local
+Y` gave `u x v = +Z`, pointing every default-orientation area light AWAY
from the scene (measured 0.089-0.116x vs Cycles by the pkg122 hardware
verifier; 180 deg local-X flip measured 1.07-1.09x).

These tests exercise the real `convert_lights`/`setup_world` code paths
(loaded from `blender_addon/__init__.py` via `importlib`, matching the
pattern in `test_addon_instanced_lights.py`) with a minimal but REAL 3-D
vector/matrix implementation standing in for `mathutils` -- rotation
matrices and cross products are undergraduate-textbook math (CLAUDE.md
Sec 6 "trivial"), not the thing under test. What IS under test is the
addon's convention: for an arbitrary light-to-world basis, is the emitted
normal (`axis_u x axis_v`) equal to `basis @ (0, 0, -1)`, matching Cycles?

This validates the fix's math/convention. It does NOT replace a live
headless-Blender-vs-Cycles pixel A/B (this implementer cannot build the
`.pyd`; the hardware-verifier owns that gate per the spec's verification
checklist).
"""

import importlib.util
import math
import sys
import types
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Minimal real 3-D vector/matrix stand-ins for mathutils (undergrad math).
# ---------------------------------------------------------------------------

class _FakeVector:
    def __init__(self, xyz):
        self._v = tuple(float(c) for c in xyz)

    def normalized(self):
        x, y, z = self._v
        n = math.sqrt(x * x + y * y + z * z)
        if n == 0.0:
            return _FakeVector((0.0, 0.0, 0.0))
        return _FakeVector((x / n, y / n, z / n))

    def __iter__(self):
        return iter(self._v)

    def __len__(self):
        return 3

    def __getitem__(self, i):
        return self._v[i]

    @property
    def x(self):
        return self._v[0]

    @property
    def y(self):
        return self._v[1]

    @property
    def z(self):
        return self._v[2]


class _FakeMatrix3:
    """3x3 matrix given as 3 row tuples; supports `matrix @ vector`."""

    def __init__(self, rows):
        self.rows = rows

    def __matmul__(self, vec):
        x, y, z = tuple(vec)
        return _FakeVector((
            self.rows[0][0] * x + self.rows[0][1] * y + self.rows[0][2] * z,
            self.rows[1][0] * x + self.rows[1][1] * y + self.rows[1][2] * z,
            self.rows[2][0] * x + self.rows[2][1] * y + self.rows[2][2] * z,
        ))


def _rot_x(theta):
    c, s = math.cos(theta), math.sin(theta)
    return ((1, 0, 0), (0, c, -s), (0, s, c))


def _rot_y(theta):
    c, s = math.cos(theta), math.sin(theta)
    return ((c, 0, s), (0, 1, 0), (-s, 0, c))


def _rot_z(theta):
    c, s = math.cos(theta), math.sin(theta)
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def _matmul3(a, b):
    return tuple(
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
        for i in range(3)
    )


def _cross(u, v):
    ux, uy, uz = u
    vx, vy, vz = v
    return (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)


def _dot(u, v):
    return sum(a * b for a, b in zip(u, v))


IDENTITY = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
# Composed, non-axis-aligned rotation (three Euler-like rotations chained) --
# an arbitrary basis, not tied to any single axis, to catch a fix that only
# happens to work at identity or about one axis.
ROTATED = _matmul3(_matmul3(_rot_z(math.radians(37.0)), _rot_y(math.radians(52.0))),
                    _rot_x(math.radians(19.0)))


# ---------------------------------------------------------------------------
# Addon loader (mirrors tests/test_addon_instanced_lights.py).
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
    mathutils_module.Vector = _FakeVector

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.material_registry_names = lambda: ["lambertian"]
    astroray_module.pass_registry_names = lambda: []

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    module_path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_pkg139_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _RecordingRenderer:
    def __init__(self):
        self.area_light_calls = []
        self.background_calls = []

    def add_area_light_dedicated(self, *args, **_kw):
        self.area_light_calls.append(args)

    def add_point_light(self, *a, **k): pass
    def add_sun_light_dedicated(self, *a, **k): pass
    def add_spot_light_dedicated(self, *a, **k): pass

    def set_background_color(self, color):
        self.background_calls.append(list(color))

    def set_world_volume(self, *a, **k): pass
    def set_world_max_bounces(self, *a, **k): pass


def _make_area_light_instance(basis_rows, size_x=1.0, size_y=1.0, shape='SQUARE'):
    light = types.SimpleNamespace(
        type='AREA',
        color=(1.0, 1.0, 1.0),
        energy=100.0,
        shape=shape,
        spread=1.0,
        size=size_x,
        size_y=size_y,
    )
    obj = types.SimpleNamespace(type='LIGHT', data=light, pass_index=0)
    matrix = types.SimpleNamespace(
        translation=[0.0, 0.0, 0.0],
        to_3x3=lambda: _FakeMatrix3(basis_rows),
    )
    return types.SimpleNamespace(object=obj, matrix_world=matrix, is_instance=False)


def _convert_one_area_light(monkeypatch, basis_rows, size_x=1.0, size_y=1.0, shape='SQUARE'):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    instance = _make_area_light_instance(basis_rows, size_x=size_x, size_y=size_y, shape=shape)
    depsgraph = types.SimpleNamespace(object_instances=[instance], objects=[])
    engine.convert_lights(depsgraph, renderer)
    assert len(renderer.area_light_calls) == 1
    return renderer.area_light_calls[0]


@pytest.mark.parametrize("basis_rows,label", [(IDENTITY, "identity"), (ROTATED, "rotated")])
def test_area_light_normal_matches_cycles_minus_z(monkeypatch, basis_rows, label):
    """u x v must equal basis @ (0, 0, -1) -- the Cycles emission convention
    (BlenderSync::sync_light: axisu=local X, axisv=local Y, direction=-Z of
    the light transform), for both identity and an arbitrary rotated basis.
    Pre-fix this failed at identity (u x v = +Z, measured 0.089-0.116x vs
    Cycles); a fix that only special-cased identity would still fail here.
    """
    call = _convert_one_area_light(monkeypatch, basis_rows)
    _position, axis_u, axis_v, size_x, size_y, shape, _emission, _intensity, _spread = call[:9]

    normal = _cross(tuple(axis_u), tuple(axis_v))
    n = math.sqrt(sum(c * c for c in normal))
    normal = tuple(c / n for c in normal)

    expected = tuple(_FakeMatrix3(basis_rows) @ _FakeVector((0.0, 0.0, -1.0)))

    cos_angle = _dot(normal, expected)
    assert cos_angle > 0.999, (
        f"[{label}] AREA light normal (u x v = {normal}) does not match the "
        f"Cycles -Z emission convention (expected {expected}), cos={cos_angle:.6f}"
    )


def test_area_light_axis_u_still_maps_size_x(monkeypatch):
    """Non-square RECTANGLE: axis_u must remain local +X (unchanged by the
    -Z fix) so size_x still maps to u -- only axis_v flips sign, which is a
    no-op for the centered RECTANGLE/ELLIPSE/DISK shapes (symmetric about
    the light's origin), so the long axis is not mirrored or swapped.
    """
    call = _convert_one_area_light(
        monkeypatch, IDENTITY, size_x=3.0, size_y=1.0, shape='RECTANGLE')
    _position, axis_u, axis_v, size_x, size_y, shape, _emission, _intensity, _spread = call[:9]

    assert tuple(round(c, 6) for c in axis_u) == (1.0, 0.0, 0.0), (
        f"axis_u changed by the orientation fix: {axis_u} (expected local +X, unchanged)"
    )
    assert tuple(round(c, 6) for c in axis_v) == (0.0, -1.0, 0.0), (
        f"axis_v not flipped to local -Y: {axis_v}"
    )
    assert size_x == 3.0 and size_y == 1.0, (
        f"size_x/size_y mapping changed by the orientation fix: ({size_x}, {size_y})"
    )
    assert shape == 'RECTANGLE'


def test_area_light_ellipse_normal_matches_cycles(monkeypatch):
    """Same -Z check for ELLIPSE (non-square, rotated) -- the shape/basis
    fix must be convention-correct across shapes, not just RECTANGLE.
    """
    call = _convert_one_area_light(
        monkeypatch, ROTATED, size_x=2.0, size_y=0.6, shape='ELLIPSE')
    _position, axis_u, axis_v, size_x, size_y, shape, _emission, _intensity, _spread = call[:9]

    normal = _cross(tuple(axis_u), tuple(axis_v))
    n = math.sqrt(sum(c * c for c in normal))
    normal = tuple(c / n for c in normal)
    expected = tuple(_FakeMatrix3(ROTATED) @ _FakeVector((0.0, 0.0, -1.0)))
    assert _dot(normal, expected) > 0.999
    assert shape == 'ELLIPSE'
    assert size_x == 2.0 and size_y == 0.6


# ---------------------------------------------------------------------------
# setup_world: strength-0 background must render black, not the engine
# default (previously skipped by the `strength > 0.01` guard).
# ---------------------------------------------------------------------------

def _make_world(strength, color=(0.3, 0.4, 0.5)):
    bg_node = types.SimpleNamespace(
        type='BACKGROUND',
        inputs={
            'Strength': types.SimpleNamespace(default_value=strength),
            'Color': types.SimpleNamespace(is_linked=False, default_value=(*color, 1.0)),
        },
    )
    node_tree = types.SimpleNamespace(nodes=[bg_node])
    return types.SimpleNamespace(
        node_tree=node_tree,
        light_settings=types.SimpleNamespace(max_bounces=1024),
    )


def test_world_strength_zero_sets_explicit_black_background(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    scene = types.SimpleNamespace(world=_make_world(strength=0.0))

    engine.setup_world(scene, renderer)

    assert renderer.background_calls == [[0.0, 0.0, 0.0]], (
        f"strength=0.0 world must set an explicit black background, "
        f"got {renderer.background_calls} (engine default would otherwise show through)"
    )


def test_world_nonzero_strength_still_scales_background(monkeypatch):
    """Regression: the strength>0 path (pre-existing behavior) must be
    unchanged by dropping the `> 0.01` guard.
    """
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()
    scene = types.SimpleNamespace(world=_make_world(strength=2.0, color=(0.1, 0.2, 0.3)))

    engine.setup_world(scene, renderer)

    assert len(renderer.background_calls) == 1
    got = renderer.background_calls[0]
    expected = [0.2, 0.4, 0.6]
    assert all(abs(a - b) < 1e-6 for a, b in zip(got, expected)), (
        f"expected {expected}, got {got}"
    )

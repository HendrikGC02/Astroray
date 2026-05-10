"""pkg56 Phase C — depsgraph-driven dispatch tests.

Phase C wires `bpy.types.Depsgraph.updates` into the persistent viewport
session so that idle frames pay zero upload cost and per-domain edits
run only the matching Phase B uploader. These tests lock down the
dispatch table without exercising real CUDA — a spy renderer records
which uploader entry points were called for each update kind.

Mirror Cycles `BlenderSync::sync_recalc`: the dispatcher buckets
incoming updates by domain (env / materials / lights / geometry /
transforms) and runs them in fixed order. Unrecognised id types fall
back to the existing `_sync_viewport_scene` full-sync path.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# stub bpy with the bpy.types.* hierarchy the dispatcher classifies on
# ---------------------------------------------------------------------------

class _BpyId:
    """Stand-in for bpy.types.ID. Real Blender Ids are C-defined; the
    addon's dispatcher classifies via isinstance + class __name__, so any
    Python class with a matching __name__ is sufficient."""
    def __init__(self, name="x"):
        self.name = name


# Each subclass mirrors a real bpy.types.ID subclass.
class World(_BpyId): pass
class Light(_BpyId): pass
class Material(_BpyId): pass
class NodeTree(_BpyId): pass
class Image(_BpyId): pass
class Scene(_BpyId): pass


class Object(_BpyId):
    def __init__(self, name="obj", matrix_world=None):
        super().__init__(name)
        self.matrix_world = matrix_world or [
            [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]
        ]


class _DepsgraphUpdate:
    """Minimal Blender DepsgraphUpdate stand-in."""
    def __init__(self, id, *, geometry=False, transform=False, shading=False):
        self.id = id
        self.is_updated_geometry = geometry
        self.is_updated_transform = transform
        self.is_updated_shading = shading


def _load_addon(monkeypatch, renderer_cls):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base: pass

    class _RenderEngineBase:
        def report(self, *_a, **_k): return None
        def update_progress(self, *_a, **_k): return None
        def update_stats(self, *_a, **_k): return None
        def test_break(self): return False
        def tag_redraw(self): pass

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _RenderEngineBase
    # bpy.types.* classes the dispatcher will isinstance-check against.
    bpy_types_module.World = World
    bpy_types_module.Light = Light
    bpy_types_module.Material = Material
    bpy_types_module.NodeTree = NodeTree
    bpy_types_module.ShaderNodeTree = NodeTree
    bpy_types_module.Image = Image
    bpy_types_module.Object = Object
    bpy_types_module.Scene = Scene
    bpy_module.types = bpy_types_module

    for name in ("BoolProperty", "IntProperty", "FloatProperty",
                 "StringProperty", "PointerProperty", "FloatVectorProperty",
                 "EnumProperty"):
        setattr(bpy_props_module, name, lambda **_kw: None)
    bpy_module.props = bpy_props_module
    bpy_module.path = types.SimpleNamespace(abspath=lambda p: p)

    shader_blending_module = types.ModuleType("shader_blending")
    shader_blending_module.blend_shader_specs = {}
    shader_blending_module.add_shader_specs = {}
    mathutils_module = types.ModuleType("mathutils")
    mathutils_module.Vector = lambda values: values

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": False}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.Renderer = renderer_cls
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
    spec = importlib.util.spec_from_file_location(
        "astroray_blender_addon_pkg56c_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Spy renderer — records every uploader entry point hit
# ---------------------------------------------------------------------------

class _SpyRenderer:
    def __init__(self):
        self.calls = []

    def _rec(self, name, *args):
        self.calls.append((name,) + args)

    # Phase B uploader surface
    def upload_geometry(self):    self._rec("upload_geometry")
    def upload_materials(self):   self._rec("upload_materials")
    def upload_lights(self):      self._rec("upload_lights")
    def upload_environment(self): self._rec("upload_environment")
    def upload_scene(self):       self._rec("upload_scene")
    def update_object_transform(self, obj_id, mat16):
        self._rec("update_object_transform", obj_id, tuple(mat16))

    # noop stubs the dispatcher / sync don't touch but the addon class
    # methods may reach for during a fallback path.
    def clear(self):                                self._rec("clear")
    def set_adaptive_sampling(self, *_):            pass
    def set_clamp_direct(self, *_):                 pass
    def set_clamp_indirect(self, *_):               pass
    def set_filter_glossy(self, *_):                pass
    def set_use_reflective_caustics(self, *_):      pass
    def set_use_refractive_caustics(self, *_):      pass


def _engine(monkeypatch):
    addon = _load_addon(monkeypatch, _SpyRenderer)
    eng = addon.CustomRaytracerRenderEngine()
    eng._viewport_renderer = _SpyRenderer()
    eng._viewport_full_synced = True  # so dispatcher runs, not fallback
    return addon, eng, eng._viewport_renderer


def _depsgraph(updates, scene=None):
    return types.SimpleNamespace(updates=list(updates), scene=scene)


# ---------------------------------------------------------------------------
# 1. Idle frame — empty .updates → no uploader runs
# ---------------------------------------------------------------------------

def test_idle_frame_calls_no_uploaders(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    res = eng._apply_depsgraph_updates(spy, _depsgraph([]), settings=None)
    assert res == "idle"
    assert spy.calls == []


# ---------------------------------------------------------------------------
# 2. Per-domain dispatch — only the matching uploader runs
# ---------------------------------------------------------------------------

def test_world_update_dispatches_environment_only(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    res = eng._apply_depsgraph_updates(
        spy, _depsgraph([_DepsgraphUpdate(World("W"))]), settings=None)
    assert res == "dispatched"
    names = [c[0] for c in spy.calls]
    assert "upload_environment" in names
    assert "upload_geometry" not in names
    assert "upload_materials" not in names
    assert "upload_lights" not in names


def test_light_update_dispatches_lights_only(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    res = eng._apply_depsgraph_updates(
        spy, _depsgraph([_DepsgraphUpdate(Light("L"))]), settings=None)
    assert res == "dispatched"
    names = [c[0] for c in spy.calls]
    assert "upload_lights" in names
    assert "upload_geometry" not in names
    assert "upload_environment" not in names
    assert "upload_materials" not in names


def test_material_update_dispatches_materials_only(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    res = eng._apply_depsgraph_updates(
        spy, _depsgraph([_DepsgraphUpdate(Material("M"))]), settings=None)
    assert res == "dispatched"
    names = [c[0] for c in spy.calls]
    assert "upload_materials" in names
    assert "upload_geometry" not in names
    assert "upload_environment" not in names
    assert "upload_lights" not in names


def test_image_update_dispatches_materials_only(monkeypatch):
    """An Image update (texture reload from disk) routes through the
    materials path — Phase C ships without a dedicated texture uploader,
    spec §C key-design 3 promotes Image → materials."""
    _addon, eng, spy = _engine(monkeypatch)
    res = eng._apply_depsgraph_updates(
        spy, _depsgraph([_DepsgraphUpdate(Image("img"))]), settings=None)
    assert res == "dispatched"
    names = [c[0] for c in spy.calls]
    assert "upload_materials" in names


def test_object_geometry_dispatches_geometry_only(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    res = eng._apply_depsgraph_updates(
        spy, _depsgraph([_DepsgraphUpdate(Object("Cube"), geometry=True)]),
        settings=None)
    assert res == "dispatched"
    names = [c[0] for c in spy.calls]
    assert "upload_geometry" in names
    assert "upload_materials" not in names
    assert "upload_lights" not in names
    assert "upload_environment" not in names


def test_object_shading_dispatches_materials_only(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    res = eng._apply_depsgraph_updates(
        spy, _depsgraph([_DepsgraphUpdate(Object("Cube"), shading=True)]),
        settings=None)
    assert res == "dispatched"
    names = [c[0] for c in spy.calls]
    assert "upload_materials" in names
    assert "upload_geometry" not in names


# ---------------------------------------------------------------------------
# 3. Coalescing — geometry + shading on one Object → each uploader once
# ---------------------------------------------------------------------------

def test_coalesce_geometry_and_shading_one_run_each(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    obj = Object("Cube")
    res = eng._apply_depsgraph_updates(
        spy,
        _depsgraph([
            _DepsgraphUpdate(obj, geometry=True),
            _DepsgraphUpdate(obj, shading=True),
        ]),
        settings=None,
    )
    assert res == "dispatched"
    names = [c[0] for c in spy.calls]
    assert names.count("upload_geometry") == 1
    assert names.count("upload_materials") == 1


def test_coalesce_dedupes_repeated_world_update(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    w = World("W")
    res = eng._apply_depsgraph_updates(
        spy,
        _depsgraph([_DepsgraphUpdate(w), _DepsgraphUpdate(w)]),
        settings=None,
    )
    assert res == "dispatched"
    assert [c[0] for c in spy.calls].count("upload_environment") == 1


# ---------------------------------------------------------------------------
# 4. Dispatch order — env → materials → lights → geometry
# ---------------------------------------------------------------------------

def test_fixed_dispatch_order(monkeypatch):
    """The dispatcher runs uploaders in env → materials → lights →
    geometry order regardless of the order the updates arrive in."""
    _addon, eng, spy = _engine(monkeypatch)
    res = eng._apply_depsgraph_updates(
        spy,
        _depsgraph([
            _DepsgraphUpdate(Object("Cube"), geometry=True),  # geometry first
            _DepsgraphUpdate(Light("L")),                     # lights
            _DepsgraphUpdate(Material("M")),                  # materials
            _DepsgraphUpdate(World("W")),                     # env last
        ]),
        settings=None,
    )
    assert res == "dispatched"
    upload_calls = [c[0] for c in spy.calls if c[0].startswith("upload_")]
    assert upload_calls == [
        "upload_environment", "upload_materials",
        "upload_lights", "upload_geometry",
    ]


# ---------------------------------------------------------------------------
# 5. Unrecognised update type → fallback (caller runs full sync)
# ---------------------------------------------------------------------------

class _UnknownId(_BpyId): pass


def test_unknown_id_type_returns_fallback(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    res = eng._apply_depsgraph_updates(
        spy,
        _depsgraph([_DepsgraphUpdate(_UnknownId("???"), geometry=True)]),
        settings=None,
    )
    assert res == "fallback"
    assert spy.calls == []  # no dispatch — caller falls back


def test_missing_updates_attr_returns_fallback(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    res = eng._apply_depsgraph_updates(
        spy, types.SimpleNamespace(scene=None), settings=None)
    assert res == "fallback"
    assert spy.calls == []


# ---------------------------------------------------------------------------
# 6. Object transform-only — no obj-id mapping → promote to upload_geometry
# ---------------------------------------------------------------------------

def test_transform_only_without_id_map_promotes_to_geometry(monkeypatch):
    """Phase C ships without a Blender-Object → renderer-primitive-id
    tracker (would require touching Phase B's `convert_objects` surface,
    out of scope per CLAUDE.md §3). The dispatcher promotes transform-only
    edits to a geometry rebuild — same cost on the single-level BVH."""
    _addon, eng, spy = _engine(monkeypatch)
    res = eng._apply_depsgraph_updates(
        spy,
        _depsgraph([_DepsgraphUpdate(Object("Cube"), transform=True)]),
        settings=None,
    )
    assert res == "dispatched"
    names = [c[0] for c in spy.calls]
    assert "upload_geometry" in names
    assert "update_object_transform" not in names


def test_transform_only_with_id_map_uses_update_object_transform(monkeypatch):
    """When the addon DOES have an obj→prim-id map populated (a future
    package will populate it inside `convert_objects`), transform-only
    edits route to the surgical `update_object_transform` binding."""
    _addon, eng, spy = _engine(monkeypatch)
    eng._renderer_object_id_map = {"Cube": 7}
    obj = Object("Cube", matrix_world=[
        [1, 0, 0, 5], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]
    ])
    res = eng._apply_depsgraph_updates(
        spy, _depsgraph([_DepsgraphUpdate(obj, transform=True)]),
        settings=None)
    assert res == "dispatched"
    names = [c[0] for c in spy.calls]
    assert "update_object_transform" in names
    assert "upload_geometry" not in names
    # Verify the obj id and matrix were forwarded.
    transform_call = next(c for c in spy.calls
                          if c[0] == "update_object_transform")
    assert transform_call[1] == 7
    assert len(transform_call[2]) == 16


# ---------------------------------------------------------------------------
# 7. Scene/frame update — accumulation reset, no upload
# ---------------------------------------------------------------------------

def test_scene_only_update_is_idle_with_accum_reset(monkeypatch):
    _addon, eng, spy = _engine(monkeypatch)
    eng._viewport_accum_pixels = object()  # pretend an accumulator exists
    eng._viewport_current_spp = 17
    res = eng._apply_depsgraph_updates(
        spy, _depsgraph([_DepsgraphUpdate(Scene("S"))]), settings=None)
    assert res == "idle"
    assert spy.calls == []
    # Reset cleared the accumulator.
    assert eng._viewport_accum_pixels is None
    assert eng._viewport_current_spp == 0


# ---------------------------------------------------------------------------
# 8. Empty-Object update (selection-only) — no domain bits set → idle
# ---------------------------------------------------------------------------

def test_object_update_with_no_bits_set_is_idle(monkeypatch):
    """Blender emits Object updates on selection changes with no
    geometry/transform/shading bits set. The dispatcher must treat
    these as idle."""
    _addon, eng, spy = _engine(monkeypatch)
    res = eng._apply_depsgraph_updates(
        spy, _depsgraph([_DepsgraphUpdate(Object("Cube"))]), settings=None)
    assert res == "idle"
    assert spy.calls == []

"""pkg116 — Exporter/cache refactor: per-domain cache diff() tests.

Tests the real implementation (not stubs): each cache's diff() fires on its own
update type and not others, the aggregator ORs correctly, dispatch order is
preserved (spy call-order assertion), idle returns 'idle' with zero uploader calls.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# stub bpy with the bpy.types.* hierarchy the caches classify on
# ---------------------------------------------------------------------------

class _BpyId:
    """Stand-in for bpy.types.ID."""
    def __init__(self, name="x"):
        self.name = name


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


def _load_exporter_module():
    """Load exporter.py as a standalone module."""
    module_path = Path(__file__).parent.parent / "blender_addon" / "exporter.py"
    spec = importlib.util.spec_from_file_location("astroray_exporter", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _stub_bpy():
    """Create a stub bpy module with types namespace."""
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_types_module.World = World
    bpy_types_module.Light = Light
    bpy_types_module.Material = Material
    bpy_types_module.NodeTree = NodeTree
    bpy_types_module.ShaderNodeTree = NodeTree
    bpy_types_module.Image = Image
    bpy_types_module.Object = Object
    bpy_types_module.Scene = Scene
    bpy_module.types = bpy_types_module
    return bpy_module


def _stub_depsgraph(updates):
    return types.SimpleNamespace(updates=list(updates), scene=None)


# ---------------------------------------------------------------------------
# 1. Change enum: verify bitflag structure
# ---------------------------------------------------------------------------

def test_change_enum_exists():
    exp = _load_exporter_module()
    assert hasattr(exp, 'Change')
    Change = exp.Change
    assert hasattr(Change, 'NONE')
    assert hasattr(Change, 'ENVIRONMENT')
    assert hasattr(Change, 'MATERIALS')
    assert hasattr(Change, 'LIGHTS')
    assert hasattr(Change, 'GEOMETRY')
    assert hasattr(Change, 'TRANSFORMS')
    assert hasattr(Change, 'BACKEND_CONFIG')
    assert hasattr(Change, 'ACCUMULATION_ONLY')


def test_change_enum_bitflag_or():
    exp = _load_exporter_module()
    Change = exp.Change
    # ORing flags produces the union
    combined = Change.MATERIALS | Change.LIGHTS
    assert combined & Change.MATERIALS
    assert combined & Change.LIGHTS
    assert not (combined & Change.GEOMETRY)


def test_change_enum_none_is_zero():
    exp = _load_exporter_module()
    Change = exp.Change
    assert Change.NONE == 0
    assert not (Change.NONE & Change.MATERIALS)


# ---------------------------------------------------------------------------
# 2. Per-domain cache diff() fires on its own update type, not others
# ---------------------------------------------------------------------------

def test_world_cache_diff_fires_on_world_update_only():
    exp = _load_exporter_module()
    bpy = _stub_bpy()
    cache = exp.WorldCache(bpy)

    # World update → True
    dg_world = _stub_depsgraph([_DepsgraphUpdate(World("W"))])
    assert cache.diff(dg_world) is True

    # Material update → False
    dg_mat = _stub_depsgraph([_DepsgraphUpdate(Material("M"))])
    assert cache.diff(dg_mat) is False

    # Light update → False
    dg_light = _stub_depsgraph([_DepsgraphUpdate(Light("L"))])
    assert cache.diff(dg_light) is False


def test_materials_cache_diff_fires_on_material_nodetree_image():
    exp = _load_exporter_module()
    bpy = _stub_bpy()
    cache = exp.MaterialsCache(bpy)

    # Material → True
    assert cache.diff(_stub_depsgraph([_DepsgraphUpdate(Material("M"))])) is True
    # NodeTree → True
    assert cache.diff(_stub_depsgraph([_DepsgraphUpdate(NodeTree("N"))])) is True
    # Image → True
    assert cache.diff(_stub_depsgraph([_DepsgraphUpdate(Image("I"))])) is True
    # Object.is_updated_shading → True
    assert cache.diff(_stub_depsgraph([_DepsgraphUpdate(Object("O"), shading=True)])) is True

    # World → False
    assert cache.diff(_stub_depsgraph([_DepsgraphUpdate(World("W"))])) is False
    # Light → False
    assert cache.diff(_stub_depsgraph([_DepsgraphUpdate(Light("L"))])) is False


def test_lights_cache_diff_fires_on_light_only():
    exp = _load_exporter_module()
    bpy = _stub_bpy()
    cache = exp.LightsCache(bpy)

    # Light → True
    assert cache.diff(_stub_depsgraph([_DepsgraphUpdate(Light("L"))])) is True

    # World → False
    assert cache.diff(_stub_depsgraph([_DepsgraphUpdate(World("W"))])) is False
    # Material → False
    assert cache.diff(_stub_depsgraph([_DepsgraphUpdate(Material("M"))])) is False


def test_objects_cache_diff_returns_geometry_flag_on_geometry_update():
    exp = _load_exporter_module()
    bpy = _stub_bpy()

    def no_id_map(obj):
        return None

    cache = exp.ObjectsCache(bpy, no_id_map)

    # Object.is_updated_geometry → geometry=True
    dg = _stub_depsgraph([_DepsgraphUpdate(Object("O"), geometry=True)])
    geom, has_xforms, xforms = cache.diff(dg)
    assert geom is True
    assert has_xforms is False
    assert xforms == []


def test_objects_cache_diff_returns_transforms_on_transform_only_with_id_map():
    exp = _load_exporter_module()
    bpy = _stub_bpy()

    def id_map(obj):
        return 42  # fake id

    cache = exp.ObjectsCache(bpy, id_map)

    # Object.is_updated_transform (no geometry) → transforms list
    obj = Object("O")
    dg = _stub_depsgraph([_DepsgraphUpdate(obj, transform=True)])
    geom, has_xforms, xforms = cache.diff(dg)
    assert geom is False
    assert has_xforms is True
    assert len(xforms) == 1
    assert xforms[0][0] == 42  # obj_id
    assert len(xforms[0][1]) == 16  # mat16


def test_config_cache_diff_fires_on_scene():
    exp = _load_exporter_module()
    bpy = _stub_bpy()
    cache = exp.ConfigCache(bpy)

    # Scene → backend_config=True, accumulation_only=True
    backend, accum = cache.diff(_stub_depsgraph([_DepsgraphUpdate(Scene("S"))]))
    assert backend is True
    assert accum is True

    # World → False, False
    backend, accum = cache.diff(_stub_depsgraph([_DepsgraphUpdate(World("W"))]))
    assert backend is False
    assert accum is False


# ---------------------------------------------------------------------------
# 3. Exporter aggregates cache diff() into Change flags + dispatch order
# ---------------------------------------------------------------------------

class _SpyRenderer:
    """Spy renderer that records uploader entry point calls."""
    def __init__(self):
        self.calls = []

    def _rec(self, name, *args):
        self.calls.append((name,) + args)

    def upload_geometry(self):    self._rec("upload_geometry")
    def upload_materials(self):   self._rec("upload_materials")
    def upload_lights(self):      self._rec("upload_lights")
    def upload_environment(self): self._rec("upload_environment")
    def update_object_transform(self, obj_id, mat16):
        self._rec("update_object_transform", obj_id, tuple(mat16))


def test_exporter_apply_depsgraph_updates_dispatch_order():
    """Dispatch order: backend_config → env → materials → lights → geometry → transforms"""
    exp = _load_exporter_module()
    bpy = _stub_bpy()

    class _StubEngine:
        def setup_world(self, scene, renderer):
            renderer._rec("setup_world")

    engine = _StubEngine()
    astroray = types.SimpleNamespace(Renderer=_SpyRenderer)
    exporter = exp.Exporter(engine, bpy, astroray)

    spy = _SpyRenderer()

    # Multiple updates: World + Material + Light
    # Provide a scene so setup_world gets called
    dg = types.SimpleNamespace(
        updates=[
            _DepsgraphUpdate(World("W")),
            _DepsgraphUpdate(Material("M")),
            _DepsgraphUpdate(Light("L")),
        ],
        scene=types.SimpleNamespace()  # non-None scene
    )

    def noop_config(renderer, settings, report):
        pass

    result = exporter.apply_depsgraph_updates(spy, dg, None, noop_config, None)

    assert result == 'dispatched'

    # Check call order: env (setup_world + upload_environment) → materials → lights
    call_names = [c[0] for c in spy.calls]
    env_idx = call_names.index("setup_world")
    mat_idx = call_names.index("upload_materials")
    light_idx = call_names.index("upload_lights")

    assert env_idx < mat_idx < light_idx


def test_exporter_apply_depsgraph_updates_idle_on_empty():
    """Empty updates → 'idle' with zero uploader calls"""
    exp = _load_exporter_module()
    bpy = _stub_bpy()

    class _StubEngine:
        pass

    engine = _StubEngine()
    astroray = types.SimpleNamespace(Renderer=_SpyRenderer)
    exporter = exp.Exporter(engine, bpy, astroray)

    spy = _SpyRenderer()
    dg = _stub_depsgraph([])

    result = exporter.apply_depsgraph_updates(spy, dg, None, lambda *_: None, None)

    assert result == 'idle'
    assert spy.calls == []


def test_exporter_apply_depsgraph_updates_materials_only_skips_geometry():
    """Material-only update → upload_materials called, upload_geometry NOT called"""
    exp = _load_exporter_module()
    bpy = _stub_bpy()

    class _StubEngine:
        pass

    engine = _StubEngine()
    astroray = types.SimpleNamespace(Renderer=_SpyRenderer)
    exporter = exp.Exporter(engine, bpy, astroray)

    spy = _SpyRenderer()
    dg = _stub_depsgraph([_DepsgraphUpdate(Material("M"))])

    result = exporter.apply_depsgraph_updates(spy, dg, None, lambda *_: None, None)

    assert result == 'dispatched'
    call_names = [c[0] for c in spy.calls]
    assert "upload_materials" in call_names
    assert "upload_geometry" not in call_names
    assert "upload_lights" not in call_names
    assert "upload_environment" not in call_names

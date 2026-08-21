"""pkg57 — Native Astroray shader-node tests.

Covers:
1. The 5 ShaderNode subclasses + 2 NodeSocket subclasses + the
   AstrorayMaterialSettings PropertyGroup all register without error.
2. The Add-menu draw function emits an Astroray submenu when the active
   engine is CUSTOM_RAYTRACER and emits nothing when it is CYCLES.
3. convert_node_material with a tree containing AstrorayOutputNode →
   AstrorayShaderNodeSellmeierGlass produces a 'dielectric' material with
   a Sellmeier preset (NOT a plain disney).
4. convert_node_material with a tree containing only OUTPUT_MATERIAL →
   BSDF_PRINCIPLED reaches the existing Cycles-fallback path unchanged.
5. The PointerProperty on bpy.types.Material is set/unset by the nodes
   register()/unregister() pair.

These are stub-Blender tests — no live Blender process is required.
The shape mirrors tests/test_blender_principled_texture.py.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Shared stub-bpy fixture
# --------------------------------------------------------------------------- #

def _make_stub_bpy(engine_id: str = "CUSTOM_RAYTRACER"):
    """Build a fresh stub bpy module hierarchy + helpers for one test."""
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")
    bpy_utils_module = types.ModuleType("bpy.utils")

    class _Base:
        pass

    class _RenderEngineBase:
        def report(self, *a, **k): return None
        def update_progress(self, *a, **k): return None
        def test_break(self): return False

    class _Material:
        pass

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _RenderEngineBase
    bpy_types_module.ShaderNode = _Base
    bpy_types_module.NodeSocket = _Base
    bpy_types_module.Menu = _Base
    bpy_types_module.Material = _Material
    bpy_module.types = bpy_types_module

    for name in ("BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
                 "PointerProperty", "FloatVectorProperty", "EnumProperty"):
        # Each property factory returns a sentinel — the addon code only stores
        # the return value as a class attribute, never inspects it.
        setattr(bpy_props_module, name, lambda **_kwargs: None)
    bpy_module.props = bpy_props_module

    registered: list[type] = []

    def _register_class(cls):
        registered.append(cls)

    def _unregister_class(cls):
        if cls in registered:
            registered.remove(cls)

    bpy_utils_module.register_class = _register_class
    bpy_utils_module.unregister_class = _unregister_class
    bpy_module.utils = bpy_utils_module

    bpy_module.path = types.SimpleNamespace(abspath=lambda p: p)

    # Context with a settable engine.
    class _NodeMTAdd:
        _appended = []

        @classmethod
        def append(cls, fn):
            cls._appended.append(fn)

        @classmethod
        def remove(cls, fn):
            if fn in cls._appended:
                cls._appended.remove(fn)

    bpy_types_module.NODE_MT_add = _NodeMTAdd

    bpy_module.context = types.SimpleNamespace(
        scene=types.SimpleNamespace(
            render=types.SimpleNamespace(engine=engine_id),
        ),
        space_data=types.SimpleNamespace(tree_type="ShaderNodeTree"),
    )

    return bpy_module, registered


def _load_nodes_module(monkeypatch, engine_id="CUSTOM_RAYTRACER"):
    bpy_module, registered = _make_stub_bpy(engine_id)
    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_module.types)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_module.props)
    monkeypatch.setitem(sys.modules, "bpy.utils", bpy_module.utils)

    # Force a fresh import — the test runs may share an interpreter.
    sys.modules.pop("astroray_blender_nodes_test", None)
    nodes_init = REPO_ROOT / "blender_addon" / "nodes" / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "astroray_blender_nodes_test", nodes_init)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod, bpy_module, registered


# --------------------------------------------------------------------------- #
# 1. Registration
# --------------------------------------------------------------------------- #

def test_all_classes_register_without_error(monkeypatch):
    nodes_mod, _bpy, registered = _load_nodes_module(monkeypatch)
    nodes_mod.register()
    names = {cls.__name__ for cls in registered}

    # All five node classes
    for cls in nodes_mod.NODE_CLASSES:
        assert cls.__name__ in names, f"{cls.__name__} missing from registered set"
    # Both socket classes
    for cls in nodes_mod.SOCKET_CLASSES:
        assert cls.__name__ in names, f"{cls.__name__} missing from registered set"
    # Property group + Add-menu submenu
    assert "AstrorayMaterialSettings" in names
    assert "NODE_MT_astroray_add" in names


def test_property_group_registers_on_material(monkeypatch):
    nodes_mod, bpy_module, _ = _load_nodes_module(monkeypatch)
    assert not hasattr(bpy_module.types.Material, "astroray")
    nodes_mod.register()
    assert hasattr(bpy_module.types.Material, "astroray"), (
        "register() must attach the PointerProperty to bpy.types.Material")
    nodes_mod.unregister()
    assert not hasattr(bpy_module.types.Material, "astroray"), (
        "unregister() must remove the PointerProperty from bpy.types.Material")


# --------------------------------------------------------------------------- #
# 2. Add-menu visibility per engine
# --------------------------------------------------------------------------- #

def test_add_menu_appended_on_register(monkeypatch):
    nodes_mod, bpy_module, _ = _load_nodes_module(monkeypatch)
    nodes_mod.register()
    appended = bpy_module.types.NODE_MT_add._appended
    assert nodes_mod.draw_astroray_nodes in appended, (
        "register() must append the Astroray draw function to NODE_MT_add")
    nodes_mod.unregister()
    assert nodes_mod.draw_astroray_nodes not in bpy_module.types.NODE_MT_add._appended


def test_draw_astroray_nodes_emits_only_for_astroray_engine(monkeypatch):
    """When the active engine is Astroray, the draw function must call
    layout.menu(...) for the Astroray submenu. When it is Cycles, the
    function must return without calling layout."""
    # --- Astroray engine: must emit ---
    nodes_mod, bpy_module, _ = _load_nodes_module(monkeypatch, engine_id="CUSTOM_RAYTRACER")

    calls = []
    class _Layout:
        def separator(self): calls.append(("separator",))
        def menu(self, name, text=""): calls.append(("menu", name, text)); return None

    fake_self = types.SimpleNamespace(layout=_Layout())
    nodes_mod.draw_astroray_nodes(fake_self, bpy_module.context)
    assert any(c[0] == "menu" for c in calls), (
        f"Astroray engine should produce a menu entry; calls={calls}")

    # --- Cycles engine: must NOT emit ---
    nodes_mod2, bpy_module2, _ = _load_nodes_module(monkeypatch, engine_id="CYCLES")
    calls2 = []
    fake_self2 = types.SimpleNamespace(layout=_Layout())
    # Replace calls list by overriding draw_color stand-in
    class _Layout2:
        def separator(self): calls2.append(("separator",))
        def menu(self, name, text=""): calls2.append(("menu", name, text))
    fake_self2.layout = _Layout2()
    nodes_mod2.draw_astroray_nodes(fake_self2, bpy_module2.context)
    assert calls2 == [], (
        f"Cycles engine must produce no Astroray menu entries; calls={calls2}")


# --------------------------------------------------------------------------- #
# 3 + 4. convert_node_material — Astroray pre-check vs Cycles fallback
# --------------------------------------------------------------------------- #

def _load_blender_addon(monkeypatch):
    """Same shape as tests/test_blender_principled_texture.py:_load_blender_addon."""
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base: pass
    class _RenderEngineBase:
        def report(self, *a, **k): return None
        def update_progress(self, *a, **k): return None
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
    astroray_module.material_registry_names = lambda: ["lambertian", "disney", "dielectric"]
    astroray_module.pass_registry_names = lambda: []

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    sys.modules.pop("astroray_blender_addon_test", None)
    module_path = REPO_ROOT / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# --- Stub Blender data primitives ---

class _Socket:
    def __init__(self, default=0.0, linked_to=None, output_name=""):
        self.default_value = default
        self.is_linked = linked_to is not None
        self.links = []
        if linked_to is not None:
            self.links.append(types.SimpleNamespace(
                from_node=linked_to,
                from_socket=types.SimpleNamespace(name=output_name or "BSDF"),
            ))


class _Node:
    def __init__(self, ntype="", bl_idname="", inputs=None, **extra):
        self.type = ntype
        self.bl_idname = bl_idname
        self.inputs = inputs or {}
        self.is_active_output = True
        for k, v in extra.items():
            setattr(self, k, v)


class _NodeTree:
    def __init__(self, nodes):
        self.nodes = nodes


class _Material:
    def __init__(self, node_tree, custom_raytracer=None, astroray=None):
        self.name = "TestMat"
        self.node_tree = node_tree
        self.custom_raytracer = custom_raytracer
        self.astroray = astroray

    def inline_shader_nodes(self):
        # Pre-5.0 stand-in: raise so the addon falls back to mat.node_tree.
        raise AttributeError("stub: no inline_shader_nodes")


class _RecordingRenderer:
    def __init__(self):
        self.created_materials = []
        self._next_id = 1

    def create_material(self, mat_type, color, params):
        self.created_materials.append((mat_type, list(color), dict(params)))
        mid = self._next_id
        self._next_id += 1
        return mid

    def set_material_spectral_profile(self, *a, **k): pass
    def clear_material_spectral_profile(self, *a, **k): pass


def _principled_node():
    return _Node(
        ntype="BSDF_PRINCIPLED",
        bl_idname="ShaderNodeBsdfPrincipled",
        inputs={
            'Base Color':         _Socket(default=(0.6, 0.3, 0.2, 1.0)),
            'Metallic':           _Socket(default=0.0),
            'Roughness':          _Socket(default=0.5),
            'IOR':                _Socket(default=1.45),
            'Anisotropic':        _Socket(default=0.0),
            'Emission Color':     _Socket(default=(0.0, 0.0, 0.0, 1.0)),
            'Emission Strength':  _Socket(default=0.0),
            'Normal':             _Socket(),
            'Transmission Weight':_Socket(default=0.0),
            'Coat Weight':        _Socket(default=0.0),
            'Coat Roughness':     _Socket(default=0.0),
            'Sheen Weight':       _Socket(default=0.0),
            'Subsurface Weight':  _Socket(default=0.0),
        },
    )


def test_cycles_principled_path_unchanged(monkeypatch):
    """Tree with only OUTPUT_MATERIAL → BsdfPrincipled must hit the standard
    _principled_shader_spec conversion — no AstrorayOutputNode intercept.

    Original intent (pkg57): assert the standard Principled path runs, not the
    Astroray-node intercept. pkg178 Stage 5 flipped the standard path's DEFAULT
    to the native 'principled' material (was the Disney approximation), so the
    non-intercept path now produces 'principled'. The intercept case would give
    'dielectric' (see the Sellmeier test below) — 'principled' still proves no
    intercept fired."""
    addon = _load_blender_addon(monkeypatch)

    p = _principled_node()
    output = _Node(
        ntype="OUTPUT_MATERIAL",
        bl_idname="ShaderNodeOutputMaterial",
        inputs={
            'Surface': _Socket(linked_to=p, output_name="BSDF"),
            'Volume':  _Socket(),
        },
    )
    tree = _NodeTree([p, output])
    mat = _Material(tree)

    renderer = _RecordingRenderer()
    engine = addon.CustomRaytracerRenderEngine()
    engine._volume_material_map = {}
    mat_id = engine.convert_node_material(mat, renderer)
    assert mat_id == 1
    assert len(renderer.created_materials) == 1
    mat_type, color, params = renderer.created_materials[0]
    assert mat_type == "principled", (
        f"standard BsdfPrincipled path must produce the native 'principled' "
        f"material (pkg178 Stage 5 default); got {mat_type!r}")
    assert abs(color[0] - 0.6) < 1e-5


def test_astroray_output_takes_precedence_with_sellmeier_glass(monkeypatch):
    """A tree containing an AstrorayOutputNode → AstrorayShaderNodeSellmeierGlass
    must take the Astroray path and produce a 'dielectric' material with a
    Sellmeier preset — NOT the existing 'disney' fallback."""
    addon = _load_blender_addon(monkeypatch)

    sellmeier = _Node(
        bl_idname="AstrorayShaderNodeSellmeierGlass",
        inputs={
            'Sellmeier B': _Socket(default=(1.04, 0.23, 1.01)),
            'Sellmeier C': _Socket(default=(0.006, 0.020, 103.5)),
            'Tint':        _Socket(default=(1.0, 1.0, 1.0, 1.0)),
        },
        preset="bk7",
        use_preset=True,
        ior_design=1.5168,
    )
    astroray_out = _Node(
        bl_idname="AstrorayOutputNode",
        inputs={
            'Surface': _Socket(linked_to=sellmeier, output_name="BSDF"),
            'Volume':  _Socket(),
        },
    )
    # Also include a dummy Cycles output to prove the Astroray path wins.
    cycles_out = _Node(
        ntype="OUTPUT_MATERIAL",
        bl_idname="ShaderNodeOutputMaterial",
        inputs={'Surface': _Socket(), 'Volume': _Socket()},
    )
    tree = _NodeTree([sellmeier, astroray_out, cycles_out])
    mat = _Material(tree)

    renderer = _RecordingRenderer()
    engine = addon.CustomRaytracerRenderEngine()
    engine._volume_material_map = {}
    mat_id = engine.convert_node_material(mat, renderer)
    assert mat_id == 1
    assert len(renderer.created_materials) == 1
    mat_type, color, params = renderer.created_materials[0]
    assert mat_type == "dielectric", (
        f"AstrorayOutputNode → SellmeierGlass must route to 'dielectric'; "
        f"got {mat_type!r}. Astroray pre-check did not fire.")
    assert params.get("sellmeier_preset") == "bk7", (
        f"Sellmeier preset 'bk7' must reach the dielectric plugin params; "
        f"got {params}")


def test_sellmeier_glass_on_standard_material_output(monkeypatch):
    """Regression (2026-08-21): a native Astroray node wired into Blender's
    STANDARD 'Material Output' (ShaderNodeOutputMaterial) — NOT an
    AstrorayOutputNode — must still convert to its native material, exactly as
    the AstrorayOutputNode path does. Before the fix it fell through to
    convert_shader_node and silently rendered neutral grey, the #1
    'dispersion/spectral nodes don't work' report (Cycles users wire everything
    to Material Output)."""
    addon = _load_blender_addon(monkeypatch)

    sellmeier = _Node(
        bl_idname="AstrorayShaderNodeSellmeierGlass",
        inputs={
            'Sellmeier B': _Socket(default=(1.04, 0.23, 1.01)),
            'Sellmeier C': _Socket(default=(0.006, 0.020, 103.5)),
            'Tint':        _Socket(default=(1.0, 1.0, 1.0, 1.0)),
        },
        preset="bk7",
        use_preset=True,
        ior_design=1.5168,
    )
    output = _Node(
        ntype="OUTPUT_MATERIAL",
        bl_idname="ShaderNodeOutputMaterial",
        inputs={
            'Surface': _Socket(linked_to=sellmeier, output_name="BSDF"),
            'Volume':  _Socket(),
        },
    )
    tree = _NodeTree([sellmeier, output])
    mat = _Material(tree)

    renderer = _RecordingRenderer()
    engine = addon.CustomRaytracerRenderEngine()
    engine._volume_material_map = {}
    mat_id = engine.convert_node_material(mat, renderer)
    assert mat_id == 1
    assert len(renderer.created_materials) == 1
    mat_type, _color, params = renderer.created_materials[0]
    assert mat_type == "dielectric", (
        f"SellmeierGlass on the STANDARD Material Output must route to "
        f"'dielectric' (dispersive glass), not the grey disney/principled "
        f"fallback; got {mat_type!r}.")
    assert params.get("sellmeier_preset") == "bk7", (
        f"Sellmeier preset 'bk7' must reach the dielectric plugin params; "
        f"got {params}")


def test_astroray_output_without_surface_falls_back(monkeypatch):
    """An AstrorayOutputNode with no Surface link must produce a neutral
    material rather than crashing."""
    addon = _load_blender_addon(monkeypatch)

    astroray_out = _Node(
        bl_idname="AstrorayOutputNode",
        inputs={'Surface': _Socket(), 'Volume': _Socket()},
    )
    tree = _NodeTree([astroray_out])
    mat = _Material(tree)

    renderer = _RecordingRenderer()
    engine = addon.CustomRaytracerRenderEngine()
    engine._volume_material_map = {}
    mat_id = engine.convert_node_material(mat, renderer)
    assert mat_id == 1
    assert len(renderer.created_materials) == 1
    mat_type, _color, _params = renderer.created_materials[0]
    assert mat_type == "disney", (
        f"unwired AstrorayOutputNode must fall back to disney; got {mat_type!r}")

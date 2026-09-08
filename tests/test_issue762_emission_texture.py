"""#762 - procedural/image textures wired directly into an Emission node's
Color input rendered flat white on Astroray (Cycles shows the pattern).

Root cause: `_shader_spec_from_node`'s EMISSION branch (blender_addon/__init__.py)
read Emission Color via `get_color_input`, which follows Mix/Ramp/etc.
constant-EVALUATING chains but returns None (-> the hardcoded [1,1,1] default)
for TEX_IMAGE and any procedural texture node (memory:
addon-constant-folds-shader-graph). The Principled Base Color path already
carries a real per-texel texture name through the spec via
`get_base_color_texture` (see test_blender_principled_texture.py); Emission
never did.

Fix: route Emission Color through the same `get_base_color_texture` lowering,
carry `emission_color_texture` through the shader spec, and pass it as the
`light` material's `texture` param (module/blender_module.cpp
makeLegacyMaterial + the new TexturedLight class in
include/advanced_features.h -- neither DiffuseLightPlugin nor EmissivePlugin
had a texture slot before this).

These are addon-level (stub-bpy, no real Blender/astroray) tests of the
spec-building and material-param plumbing -- the same level
test_blender_principled_texture.py exercises for the Base Color path.
tests/test_issue762_headless_render.py covers the real C++ TexturedLight
material end-to-end via a headless-Blender render.
"""

import importlib.util
import sys
import types
from pathlib import Path


def _load_blender_addon(monkeypatch):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

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
    astroray_module.material_registry_names = lambda: ["lambertian", "disney", "light"]
    astroray_module.pass_registry_names = lambda: []

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    module_path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_issue762_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# Fake Blender node tree primitives (same shape as test_blender_principled_texture.py
# / test_pkg115_addon_texture_translation.py)
# --------------------------------------------------------------------------- #

class _Socket:
    def __init__(self, default=0.0, linked_to=None, output_name="Color"):
        self.default_value = default
        self.is_linked = linked_to is not None
        self.links = []
        if linked_to is not None:
            self.links.append(types.SimpleNamespace(
                from_node=linked_to,
                from_socket=types.SimpleNamespace(name=output_name),
            ))


class _Node:
    def __init__(self, ntype, inputs=None, **extra):
        self.type = ntype
        self.inputs = inputs or {}
        for k, v in extra.items():
            setattr(self, k, v)


class _RecordingRenderer:
    def __init__(self):
        self.created_materials = []   # (type, color, params)
        self.proc_texture_calls = []  # (name, ttype, params)
        self._next_id = 1

    def create_procedural_texture(self, name, ttype, params):
        self.proc_texture_calls.append((name, ttype, list(params)))

    def set_texture_coord_mode(self, name, mode): pass
    def set_texture_uv_transform(self, name, sx, sy, ox, oy, rotation=0.0): pass

    def create_material(self, mat_type, color, params):
        self.created_materials.append((mat_type, list(color), dict(params)))
        mid = self._next_id
        self._next_id += 1
        return mid


def _emission_node(color_link=None, strength=1.0):
    return _Node('EMISSION', inputs={
        'Color': _Socket(default=(1.0, 1.0, 1.0, 1.0), linked_to=color_link),
        'Strength': _Socket(default=strength),
    })


def _checker_node():
    return _Node('TEX_CHECKER', inputs={
        'Vector': _Socket(),  # unlinked -> GENERATED
        'Color1': _Socket(default=(0.9, 0.9, 0.9, 1.0)),
        'Color2': _Socket(default=(0.1, 0.1, 0.1, 1.0)),
        'Scale': _Socket(default=8.0),
    })


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_checker_into_emission_color_routes_texture_through_spec(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    node = _emission_node(color_link=_checker_node())
    spec = engine._shader_spec_from_node(node, renderer, node_tree=None)

    assert spec is not None
    assert spec.get('kind') == 'emission'
    assert spec.get('emission_color_texture'), (
        f"Checker->Emission Color must carry a texture name through the spec, got: {spec}"
    )
    assert renderer.proc_texture_calls, "load_procedural_texture never called create_procedural_texture"
    assert renderer.proc_texture_calls[0][1] == 'checker'


def test_checker_into_emission_color_reaches_light_material_texture_param(monkeypatch):
    """Full pipeline: spec -> _create_material_from_shader_spec -> create_material('light', ..., {'texture': ...})."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    node = _emission_node(color_link=_checker_node(), strength=2.0)
    spec = engine._shader_spec_from_node(node, renderer, node_tree=None)
    mat_id = engine._create_material_from_shader_spec(spec, renderer)

    assert mat_id == 1
    assert len(renderer.created_materials) == 1
    mat_type, color, params = renderer.created_materials[0]
    assert mat_type == 'light'
    assert params.get('intensity') == 2.0
    assert params.get('texture'), (
        f"textured Emission must reach create_material('light', ...) with a "
        f"'texture' param, got params={params}"
    )
    assert params['texture'] == spec['emission_color_texture']


def test_constant_color_emission_has_no_texture_param(monkeypatch):
    """Regression: an unlinked (plain constant-colour) Emission node must NOT
    gain a spurious 'texture' param -- only a linked procedural/image chain does."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    node = _emission_node(color_link=None, strength=1.0)
    node.inputs['Color'].default_value = (0.2, 0.4, 0.8, 1.0)
    spec = engine._shader_spec_from_node(node, renderer, node_tree=None)
    mat_id = engine._create_material_from_shader_spec(spec, renderer)

    assert 'emission_color_texture' not in spec
    mat_type, color, params = renderer.created_materials[0]
    assert mat_type == 'light'
    assert 'texture' not in params
    assert [round(c, 3) for c in color] == [0.2, 0.4, 0.8]


def test_unsupported_linked_chain_warns_instead_of_silent_white(monkeypatch):
    """A Color input linked to something neither get_color_input() nor the
    texture lowering can evaluate must surface a degradation warning rather
    than silently rendering the [1,1,1] default (pkg119 Phase C policy)."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    # An unrecognised node type with no evaluable color/texture path.
    weird = _Node('UNKNOWN_NODE_TYPE', inputs={})
    node = _emission_node(color_link=weird)
    spec = engine._shader_spec_from_node(node, renderer, node_tree=None)

    assert 'emission_color_texture' not in spec
    report = engine._degradation_report()
    assert not report.is_empty(), (
        "expected a degradation-report entry for the unsupported Emission Color chain"
    )
    assert any('EMISSION' in feature for feature, _detail in report.approximated), (
        f"expected an 'EMISSION' entry in approximated, got: {report.approximated}"
    )

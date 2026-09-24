"""#880 - a linked Checker/Image/etc. texture on a standalone BSDF's Color
input (Diffuse, Glossy/Anisotropic, Glass, Refraction, Translucent, Sheen)
rendered flat grey through the addon; the same graph on Principled BSDF
rendered the texture.

Root cause: `_standalone_bsdf_spec` (blender_addon/__init__.py, ~2841 code
pointer in the issue) read Color via `get_color_input`, which only
constant-folds a node chain and never carries a per-texel texture through the
spec (memory: addon-constant-folds-shader-graph). The Principled Base Color
path and the #762 Emission fix both route through `get_base_color_texture`
instead, which returns a real texture name for Image/procedural chains.

Fix: `_standalone_bsdf_spec` now accepts the `renderer` and calls
`get_base_color_texture` for each of the branches above, carrying
'base_color_texture' through the 'principled'-kind spec so
`_create_material_from_shader_spec` routes it through the existing
textured-Lambertian fallback (same compromise already accepted for a
textured Principled BSDF).

Same stub-bpy level as test_issue762_emission_texture.py -- no real Blender
or astroray import.
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
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_issue880_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# Fake Blender node tree primitives (same shape as test_issue762_emission_texture.py)
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


def _checker_node():
    return _Node('TEX_CHECKER', inputs={
        'Vector': _Socket(),  # unlinked -> GENERATED
        'Color1': _Socket(default=(0.9, 0.9, 0.9, 1.0)),
        'Color2': _Socket(default=(0.1, 0.1, 0.1, 1.0)),
        'Scale': _Socket(default=8.0),
    })


def _diffuse_node(color_link=None, roughness=0.0):
    return _Node('BSDF_DIFFUSE', inputs={
        'Color': _Socket(default=(0.8, 0.8, 0.8, 1.0), linked_to=color_link),
        'Roughness': _Socket(default=roughness),
    })


def _glossy_node(color_link=None):
    return _Node('BSDF_GLOSSY', inputs={
        'Color': _Socket(default=(0.8, 0.8, 0.8, 1.0), linked_to=color_link),
        'Roughness': _Socket(default=0.5),
    })


def _glass_node(color_link=None):
    return _Node('BSDF_GLASS', inputs={
        'Color': _Socket(default=(1.0, 1.0, 1.0, 1.0), linked_to=color_link),
        'Roughness': _Socket(default=0.0),
        'IOR': _Socket(default=1.5),
    })


def _translucent_node(color_link=None):
    return _Node('BSDF_TRANSLUCENT', inputs={
        'Color': _Socket(default=(0.8, 0.8, 0.8, 1.0), linked_to=color_link),
    })


def _refraction_node(color_link=None):
    return _Node('BSDF_REFRACTION', inputs={
        'Color': _Socket(default=(1.0, 1.0, 1.0, 1.0), linked_to=color_link),
        'Roughness': _Socket(default=0.0),
        'IOR': _Socket(default=1.5),
    })


def _sheen_node(color_link=None):
    return _Node('BSDF_SHEEN', inputs={
        'Color': _Socket(default=(0.8, 0.8, 0.8, 1.0), linked_to=color_link),
        'Roughness': _Socket(default=0.5),
        'Weight': _Socket(default=1.0),
    })


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_checker_into_diffuse_color_routes_texture_through_spec(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    node = _diffuse_node(color_link=_checker_node())
    spec = engine._shader_spec_from_node(node, renderer, node_tree=None)

    assert spec is not None
    assert spec.get('kind') == 'principled'
    assert spec.get('base_color_texture'), (
        f"Checker->Diffuse Color must carry a texture name through the spec, got: {spec}"
    )
    assert renderer.proc_texture_calls, "load_procedural_texture never called create_procedural_texture"
    assert renderer.proc_texture_calls[0][1] == 'checker'


def test_checker_into_diffuse_reaches_lambertian_texture_param(monkeypatch):
    """Full pipeline: spec -> _create_material_from_shader_spec -> create_material('lambertian', ..., {'texture': ...})."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    node = _diffuse_node(color_link=_checker_node())
    spec = engine._shader_spec_from_node(node, renderer, node_tree=None)
    mat_id = engine._create_material_from_shader_spec(spec, renderer)

    assert mat_id == 1
    assert len(renderer.created_materials) == 1
    mat_type, color, params = renderer.created_materials[0]
    assert mat_type == 'lambertian'
    assert params.get('texture') == spec['base_color_texture']


def test_constant_color_diffuse_has_no_texture_param(monkeypatch):
    """Regression: an unlinked (plain constant-colour) Diffuse must NOT gain
    a spurious 'base_color_texture' -- only a linked procedural/image chain does."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    node = _diffuse_node(color_link=None)
    node.inputs['Color'].default_value = (0.2, 0.4, 0.8, 1.0)
    spec = engine._shader_spec_from_node(node, renderer, node_tree=None)
    mat_id = engine._create_material_from_shader_spec(spec, renderer)

    assert 'base_color_texture' not in spec
    mat_type, color, params = renderer.created_materials[0]
    assert mat_type in ('disney', 'principled')
    assert 'texture' not in params
    assert [round(c, 3) for c in color] == [0.2, 0.4, 0.8]


def test_diffuse_texture_without_renderer_falls_back_to_constant_fold(monkeypatch):
    """When no renderer is passed (spec-shape-only callers, e.g. existing
    tests), behaviour must stay byte-identical to before this fix."""
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()

    node = _diffuse_node(color_link=_checker_node())
    spec = engine._standalone_bsdf_spec(node)

    assert spec.get('kind') == 'principled'
    assert 'base_color_texture' not in spec


import pytest


@pytest.mark.parametrize("node_factory,expected_ttype", [
    (_glossy_node, 'checker'),
    (_glass_node, 'checker'),
    (_translucent_node, 'checker'),
    (_refraction_node, 'checker'),
    (_sheen_node, 'checker'),
])
def test_other_standalone_bsdfs_route_linked_color_texture(monkeypatch, node_factory, expected_ttype):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    node = node_factory(color_link=_checker_node())
    spec = engine._shader_spec_from_node(node, renderer, node_tree=None)

    assert spec is not None
    assert spec.get('base_color_texture'), (
        f"{node.type}: linked Checker on Color must carry a texture through the spec, got: {spec}"
    )
    assert renderer.proc_texture_calls
    assert renderer.proc_texture_calls[0][1] == expected_ttype

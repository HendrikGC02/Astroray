"""Regression tests for the Principled BSDF → textured material conversion.

Bug context:
    The default Blender material for a new mesh is `Principled BSDF`. When a
    user wires `Image Texture → Base Color`, the addon's converter previously
    routed the node through `_principled_shader_spec` → `_create_material_from_shader_spec`
    which used `get_color_input` to read the base color. `get_color_input`
    returns `None` for `TEX_IMAGE` and falls back to the default color, so the
    image was silently dropped. The texture-aware `convert_principled_bsdf_v2`
    helper existed but was orphaned (nothing called it).

    The fix carries `base_color_texture` (and normal/bump textures) through
    the spec dict to material-creation time, where a textured base color is
    routed through the `lambertian` path because the registry's Disney plugin
    does not yet have a base-color texture slot.

These tests exercise the conversion path with mocked Blender + renderer
objects and assert the texture name actually reaches the material.
"""

import importlib.util
import sys
import types
from pathlib import Path


# ---------------------------------------------------------------------------
# Shared loader (same shape as test_blender_backend_policy.py)
# ---------------------------------------------------------------------------

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
    astroray_module.material_registry_names = lambda: ["lambertian", "disney"]
    astroray_module.pass_registry_names = lambda: []

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    module_path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fake Blender node tree primitives
# ---------------------------------------------------------------------------

class _Socket:
    """Minimal stand-in for `bpy.types.NodeSocket`."""
    def __init__(self, default=0.0, linked_to=None, output_name=""):
        self.default_value = default
        self.is_linked = linked_to is not None
        self.links = []
        if linked_to is not None:
            self.links.append(types.SimpleNamespace(
                from_node=linked_to,
                from_socket=types.SimpleNamespace(name=output_name or "Color"),
            ))


class _Node:
    """Minimal stand-in for `bpy.types.Node`."""
    def __init__(self, ntype, inputs=None, **extra):
        self.type = ntype
        self.inputs = inputs or {}
        for k, v in extra.items():
            setattr(self, k, v)


class _FakeImage:
    """Stand-in for `bpy.types.Image` consumed by `load_blender_image`."""
    def __init__(self, name="test.png", w=4, h=4):
        self.name = name
        self.size = (w, h)
        self.has_data = True
        # row-major RGBA, bottom-to-top (Blender convention)
        self.pixels = [0.5] * (w * h * 4)

    def reload(self): pass


class _RecordingRenderer:
    """Records create_material / load_texture calls so tests can assert."""
    def __init__(self):
        self.created_materials = []  # list of (type, color, params)
        self.loaded_textures = []    # list of (name, w, h)
        self._next_id = 1

    def load_texture(self, name, rgb, width, height):
        self.loaded_textures.append((name, width, height))

    def create_material(self, mat_type, color, params):
        self.created_materials.append((mat_type, list(color), dict(params)))
        mid = self._next_id
        self._next_id += 1
        return mid


# ---------------------------------------------------------------------------
# Helpers to build a Principled BSDF node
# ---------------------------------------------------------------------------

def _principled_node(base_color_link=None, base_color_default=(0.8, 0.8, 0.8, 1.0)):
    inputs = {
        'Base Color':       _Socket(default=base_color_default, linked_to=base_color_link),
        'Metallic':         _Socket(default=0.0),
        'Roughness':        _Socket(default=0.5),
        'IOR':              _Socket(default=1.45),
        'Anisotropic':      _Socket(default=0.0),
        'Emission Color':   _Socket(default=(0.0, 0.0, 0.0, 1.0)),
        'Emission Strength': _Socket(default=0.0),
        'Normal':           _Socket(default=0.0),
        # Blender 4.x renamed-socket fallbacks
        'Transmission Weight': _Socket(default=0.0),
        'Coat Weight':         _Socket(default=0.0),
        'Coat Roughness':      _Socket(default=0.0),
        'Sheen Weight':        _Socket(default=0.0),
        'Subsurface Weight':   _Socket(default=0.0),
    }
    return _Node('BSDF_PRINCIPLED', inputs=inputs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_principled_with_image_texture_routes_to_textured_lambertian(monkeypatch):
    """Wiring an Image Texture into Base Color must produce a 'lambertian'
    material with `texture=<name>` — NOT a grey 'disney' material.

    This is the regression that hid the user's screenshot bug: textures were
    silently dropped because the live converter never carried the image name
    through the spec dict.
    """
    addon = _load_blender_addon(monkeypatch)

    image = _FakeImage(name="20191206_160143.jpg", w=4, h=4)
    tex_image_node = _Node('TEX_IMAGE', image=image)
    node = _principled_node(base_color_link=tex_image_node)

    renderer = _RecordingRenderer()
    engine = addon.CustomRaytracerRenderEngine()
    spec = engine._principled_shader_spec(node, renderer)

    # The spec must carry the texture name through.
    assert spec.get('base_color_texture') == "20191206_160143.jpg", (
        f"base_color_texture missing from spec: {spec}"
    )

    # The texture must have been uploaded.
    assert renderer.loaded_textures == [("20191206_160143.jpg", 4, 4)], (
        f"Expected one load_texture call, got: {renderer.loaded_textures}"
    )

    # Material creation must use the textured-Lambertian path.
    mat_id = engine._create_material_from_shader_spec(spec, renderer)
    assert mat_id == 1
    assert len(renderer.created_materials) == 1, (
        f"Expected one create_material call, got: {renderer.created_materials}"
    )
    mat_type, color, params = renderer.created_materials[0]
    assert mat_type == "lambertian", (
        f"Textured Principled must route to 'lambertian' (until Disney has "
        f"a texture slot); got {mat_type!r}."
    )
    assert params.get('texture') == "20191206_160143.jpg", (
        f"Texture name missing from material params: {params}"
    )


def test_principled_without_texture_still_renders_disney(monkeypatch):
    """Regression guard: a Principled BSDF with NO texture link must NOT be
    routed through the lambertian (textured) path. This exercises the Disney
    fallback explicitly (pkg178 Stage 5's native default is covered separately
    in test_pkg178_stage5_native_routing.py); with native routing off, a
    non-textured Principled must produce 'disney', never 'lambertian'."""
    addon = _load_blender_addon(monkeypatch)

    node = _principled_node(base_color_default=(0.7, 0.2, 0.2, 1.0))

    renderer = _RecordingRenderer()
    engine = addon.CustomRaytracerRenderEngine()
    # pkg178 Stage 5: pin the Disney fallback for this guard.
    engine._use_native_principled_flag = False
    spec = engine._principled_shader_spec(node, renderer)

    assert 'base_color_texture' not in spec
    assert renderer.loaded_textures == []

    engine._create_material_from_shader_spec(spec, renderer)
    assert len(renderer.created_materials) == 1
    mat_type, color, _params = renderer.created_materials[0]
    assert mat_type == "disney"
    # Color preserved (within float quantisation).
    assert color[0] == 0.7
    assert color[1] == 0.2
    assert color[2] == 0.2


def test_principled_spec_without_renderer_omits_textures(monkeypatch):
    """Calling `_principled_shader_spec(node)` (no renderer) must not crash
    and must omit texture keys. Used by code paths that only need the spec
    shape (e.g. shader-blending in `_shader_spec_from_node`'s mix branch)."""
    addon = _load_blender_addon(monkeypatch)

    image = _FakeImage(name="ignored.png")
    tex_image_node = _Node('TEX_IMAGE', image=image)
    node = _principled_node(base_color_link=tex_image_node)

    engine = addon.CustomRaytracerRenderEngine()
    spec = engine._principled_shader_spec(node)  # no renderer

    assert 'base_color_texture' not in spec
    assert 'normal_map_texture' not in spec
    assert 'bump_map_texture' not in spec
    # Spec shape still valid for downstream shader-blending.
    assert spec['kind'] == 'principled'
    assert 'base_color' in spec
    assert 'params' in spec

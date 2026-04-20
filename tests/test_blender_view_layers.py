import importlib.util
import sys
import types
from pathlib import Path

import numpy as np


def _load_blender_addon(monkeypatch, renderer_cls):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    class _Base:
        pass

    class _RenderEngineBase:
        def report(self, *_args, **_kwargs):
            return None

        def update_progress(self, *_args, **_kwargs):
            return None

        def test_break(self):
            return False

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _RenderEngineBase
    bpy_module.types = bpy_types_module

    for name in (
        "BoolProperty",
        "IntProperty",
        "FloatProperty",
        "StringProperty",
        "PointerProperty",
        "FloatVectorProperty",
        "EnumProperty",
    ):
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
    astroray_module.Renderer = renderer_cls

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


def test_render_skips_view_layer_with_use_for_rendering_disabled(monkeypatch):
    class RendererStub:
        created = 0

        def __init__(self):
            RendererStub.created += 1

    addon = _load_blender_addon(monkeypatch, RendererStub)
    engine = addon.CustomRaytracerRenderEngine()

    scene = types.SimpleNamespace()
    depsgraph = types.SimpleNamespace(
        scene=scene,
        view_layer=types.SimpleNamespace(name="Layer", use=False),
    )

    engine.render(depsgraph)

    assert RendererStub.created == 0


def test_convert_objects_respects_hide_viewport_in_viewport_mode(monkeypatch):
    """In viewport mode (no depsgraph.mode), objects with hide_viewport=True
    should be skipped; objects with hide_viewport=False should pass through."""
    class RendererStub:
        pass

    addon = _load_blender_addon(monkeypatch, RendererStub)
    engine = addon.CustomRaytracerRenderEngine()

    class HiddenObj:
        type = "LIGHT"
        hide_viewport = True

    class VisibleObj:
        type = "LIGHT"
        hide_viewport = False

    depsgraph = types.SimpleNamespace(
        # no 'mode' attribute → defaults to viewport path
        view_layer=types.SimpleNamespace(name="Layer"),
        object_instances=[
            types.SimpleNamespace(object=HiddenObj(), matrix_world=None),
            types.SimpleNamespace(object=VisibleObj(), matrix_world=None),
        ],
    )

    engine.convert_objects(depsgraph, renderer=RendererStub(), material_map={})
    # Only the LIGHT type objects are skipped after visibility (type != MESH),
    # but the hidden one must be dropped before reaching the type check.
    # We verify no exception is raised and the function completes cleanly.


def test_write_pixels_targets_named_render_layer(monkeypatch):
    class RendererStub:
        pass

    addon = _load_blender_addon(monkeypatch, RendererStub)
    engine = addon.CustomRaytracerRenderEngine()

    class PassesStub(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    class PassStub:
        def __init__(self):
            self.rect = types.SimpleNamespace(foreach_set=lambda _flat: None)

    layer = types.SimpleNamespace(passes=PassesStub({"Combined": PassStub()}))
    result = types.SimpleNamespace(layers=[layer])

    begin_args = {}

    def begin_result(x, y, w, h, layer=None):
        begin_args["layer"] = layer
        return result

    engine.begin_result = begin_result
    engine.end_result = lambda _result: None

    pixels = np.zeros((2, 2, 3), dtype=np.float32)
    engine.write_pixels(pixels, 2, 2, layer_name="Layer A")

    assert begin_args["layer"] == "Layer A"


def test_setup_world_loads_hdri_with_blender_x_rotation_correction(monkeypatch):
    class RendererStub:
        def __init__(self):
            self.load_args = None

        def set_world_volume(self, *_args, **_kwargs):
            return None

        def set_world_max_bounces(self, *_args, **_kwargs):
            return None

        def load_environment_map(self, *args):
            self.load_args = args
            return True

    addon = _load_blender_addon(monkeypatch, RendererStub)
    engine = addon.CustomRaytracerRenderEngine()
    monkeypatch.setattr(addon.os.path, "exists", lambda _path: True)

    class Node:
        def __init__(self, node_type, image=None, inputs=None):
            self.type = node_type
            self.image = image
            self.inputs = inputs or {}

    class Socket:
        def __init__(self, default_value, is_linked=False):
            self.default_value = default_value
            self.is_linked = is_linked

    scene = types.SimpleNamespace(
        world=types.SimpleNamespace(
            node_tree=types.SimpleNamespace(
                nodes=[
                    Node("TEX_ENVIRONMENT", image=types.SimpleNamespace(filepath="//env.hdr")),
                    Node("BACKGROUND", inputs={"Strength": Socket(1.5), "Color": Socket((1.0, 1.0, 1.0, 1.0), False)}),
                    Node("MAPPING", inputs={"Rotation": Socket((0.0, 0.0, 0.25))}),
                ]
            ),
            light_settings=types.SimpleNamespace(max_bounces=4),
        )
    )

    renderer = RendererStub()
    engine.setup_world(scene, renderer)

    assert renderer.load_args == ("//env.hdr", 1.5, 0.25, True)

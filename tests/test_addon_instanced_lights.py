"""Instanced-light coverage: convert_lights must iterate
`depsgraph.object_instances` (not `depsgraph.objects`) so lights created by
instancing (collection instances, particle/dupli systems) are rendered, the
same way convert_objects already does.

This test puts a POINT light ONLY in `object_instances` (with `objects` empty,
simulating a light that exists solely via instancing) and asserts the renderer
receives one add_point_light call. If convert_lights regressed to iterating
`depsgraph.objects`, zero lights would be added and this test would fail.
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
    astroray_module.pass_registry_names = lambda: []

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    module_path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_lights_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _RecordingRenderer:
    def __init__(self):
        self.point_light_calls = []

    def add_point_light(self, *args, **_kw):
        self.point_light_calls.append(args)

    # Other light types are not exercised by this test.
    def add_sun_light_dedicated(self, *a, **k): pass
    def add_area_light_dedicated(self, *a, **k): pass
    def add_spot_light_dedicated(self, *a, **k): pass


def _make_point_light_instance():
    light = types.SimpleNamespace(
        type='POINT',
        color=(1.0, 1.0, 1.0),
        energy=100.0,
        shadow_soft_size=0.0,
    )
    obj = types.SimpleNamespace(type='LIGHT', data=light, pass_index=0)
    matrix = types.SimpleNamespace(translation=[0.0, 0.0, 5.0])
    return types.SimpleNamespace(object=obj, matrix_world=matrix, is_instance=True)


def test_instance_only_light_is_rendered(monkeypatch):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _RecordingRenderer()

    instance = _make_point_light_instance()
    # `objects` is empty: the light exists ONLY via instancing. A loop over
    # depsgraph.objects would add nothing; the fix iterates object_instances.
    depsgraph = types.SimpleNamespace(object_instances=[instance], objects=[])

    engine.convert_lights(depsgraph, renderer)

    assert len(renderer.point_light_calls) == 1, (
        "instance-only POINT light was not rendered — convert_lights is likely "
        "iterating depsgraph.objects instead of depsgraph.object_instances"
    )

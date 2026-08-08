"""pkg66: Blender live material preview operator tests."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np


def _load_blender_addon(monkeypatch, renderer_cls):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

    registered = []

    class _Base:
        def report(self, *_args):
            pass

    class _RenderEngineBase(_Base):
        pass

    class _Images:
        def load(self, *_args, **_kwargs):
            return None

        def new(self, *_args, **_kwargs):
            return types.SimpleNamespace(
                pixels=types.SimpleNamespace(foreach_set=lambda *_a: None),
                save=lambda: None,
                filepath_raw="",
                file_format="PNG",
            )

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _RenderEngineBase
    bpy_types_module.Scene = type("Scene", (), {})
    bpy_types_module.Material = type("Material", (), {})
    bpy_types_module.Object = type("Object", (), {})

    # pkg176 Stage 2: register() now adopts the native Cycles Light Paths panels
    # (fail-loud if absent), which real Blender always provides. Mirror them here
    # so register() proceeds. All Cycles panels share ONE inherited COMPAT_ENGINES.
    class _CyclesButtonsPanel:
        COMPAT_ENGINES = {'CYCLES'}
    for _name in ("CYCLES_RENDER_PT_light_paths",
                  "CYCLES_RENDER_PT_light_paths_max_bounces",
                  "CYCLES_RENDER_PT_light_paths_clamping",
                  "CYCLES_RENDER_PT_light_paths_caustics"):
        setattr(bpy_types_module, _name, type(_name, (_CyclesButtonsPanel,), {}))
    bpy_module.types = bpy_types_module
    bpy_module.data = types.SimpleNamespace(materials=[], images=_Images())
    bpy_module.path = types.SimpleNamespace(abspath=lambda p: p)
    bpy_module.utils = types.SimpleNamespace(
        register_class=lambda cls: registered.append(cls),
        unregister_class=lambda cls: None,
    )
    for name in [
        "BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
        "PointerProperty", "FloatVectorProperty", "EnumProperty",
    ]:
        setattr(bpy_props_module, name, lambda **kwargs: kwargs.get("default"))
    bpy_module.props = bpy_props_module

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {}
    astroray_module.Renderer = renderer_cls
    astroray_module.material_registry_names = lambda: ["lambertian", "disney", "light"]
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.integrator_capabilities = lambda _name: {}

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)
    monkeypatch.setitem(sys.modules, "mathutils", types.ModuleType("mathutils"))

    module_path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_preview_test", module_path)
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon._registered_classes = registered
    return addon


class _PreviewRenderer:
    instances = []

    def __init__(self):
        self.created_materials = []
        self.render_calls = []
        self.camera = None
        _PreviewRenderer.instances.append(self)

    def set_integrator(self, name):
        self.integrator = name

    def set_seed(self, seed):
        self.seed = seed

    def set_background_color(self, color):
        self.background = color

    def create_material(self, mat_type, color, params):
        mat_id = len(self.created_materials) + 1
        self.created_materials.append((mat_id, mat_type, list(color), dict(params)))
        return mat_id

    def add_sun_light(self, direction, angular_diameter, material_id):
        self.sun = (list(direction), angular_diameter, material_id)

    def add_sphere(self, center, radius, material_id):
        self.sphere = (list(center), radius, material_id)

    def setup_camera(self, *args, **kwargs):
        self.camera = (args, kwargs)

    def render(self, samples, max_depth, progress_callback=None, apply_gamma=True):
        self.render_calls.append((samples, max_depth, progress_callback, apply_gamma))
        return np.ones((4, 4, 3), dtype=np.float32) * 0.5


class _Material(dict):
    name = "Preview Mat"
    use_nodes = False
    node_tree = None
    diffuse_color = [0.25, 0.5, 0.75, 1.0]

    def __init__(self):
        super().__init__()
        self.custom_raytracer = types.SimpleNamespace(
            live_preview_resolution="128",
            live_preview_samples=13,
            use_disney=True,
            metallic=0.0,
            roughness=0.5,
            transmission=0.0,
            ior=1.45,
            clearcoat=0.0,
            clearcoat_gloss=1.0,
        )


def test_live_preview_operator_is_registered(monkeypatch):
    addon = _load_blender_addon(monkeypatch, _PreviewRenderer)
    addon.register()

    assert any(cls.__name__ == "MATERIAL_OT_astroray_live_preview"
               for cls in addon._registered_classes)


def test_live_preview_operator_generates_file(monkeypatch):
    addon = _load_blender_addon(monkeypatch, _PreviewRenderer)
    mat = _Material()
    context = types.SimpleNamespace(
        material=mat,
        active_object=types.SimpleNamespace(active_material=mat),
    )

    result = addon.MATERIAL_OT_astroray_live_preview().execute(context)

    assert result == {'FINISHED'}
    path = Path(mat["astroray_preview_path"])
    assert path.exists()
    assert path.stat().st_size > 0


def test_live_preview_honors_resolution_and_samples(monkeypatch):
    _PreviewRenderer.instances.clear()
    addon = _load_blender_addon(monkeypatch, _PreviewRenderer)
    mat = _Material()
    mat.custom_raytracer.live_preview_resolution = "256"
    mat.custom_raytracer.live_preview_samples = 21
    context = types.SimpleNamespace(
        material=mat,
        active_object=types.SimpleNamespace(active_material=mat),
    )

    addon.MATERIAL_OT_astroray_live_preview().execute(context)

    renderer = _PreviewRenderer.instances[-1]
    assert renderer.render_calls[-1] == (21, 4, None, True)
    assert renderer.camera[1]["width"] == 256
    assert renderer.camera[1]["height"] == 256

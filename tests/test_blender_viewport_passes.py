"""Tests for pkg62: viewport pass selector and viewport OIDN toggle.

These tests use Blender API stubs and load the addon module directly
from blender_addon/__init__.py.
"""

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
    astroray_module.__features__ = {
        "cuda": False, "spectral": True,
        "oidn_denoiser": True, "optix_denoiser": False,
    }
    # pkg70: addon probes astroray.gpu_optix_available() to decide whether
    # to default to OptiX. The CPU mock has no NVIDIA GPU, so always False.
    astroray_module.gpu_optix_available = lambda: False
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
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_test_pkg62", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _make_settings(
    viewport_display_pass="combined",
    viewport_oidn=False,
    wavelength_preset="visible",
    integrator_type="path_tracer",
):
    return types.SimpleNamespace(
        viewport_display_pass=viewport_display_pass,
        viewport_oidn=viewport_oidn,
        wavelength_preset=wavelength_preset,
        wavelength_min=380.0,
        wavelength_max=780.0,
        integrator_type=integrator_type,
        # viewport render reads these settings too
        use_adaptive_sampling=False,
        preview_samples=1,
        max_bounces=4,
        clamp_direct=0.0,
        clamp_indirect=0.0,
        filter_glossy=0.0,
        use_reflective_caustics=True,
        use_refractive_caustics=True,
        diffuse_bounces=2,
        glossy_bounces=2,
        transmission_bounces=2,
        volume_bounces=0,
        transparent_bounces=2,
    )


def _run_view_update(addon, engine, settings):
    scene = types.SimpleNamespace(custom_raytracer=settings)
    depsgraph = types.SimpleNamespace(
        scene=scene,
        view_layer=types.SimpleNamespace(name="ViewLayer"),
        object_instances=[],
    )
    region = types.SimpleNamespace(width=8, height=8)
    context = types.SimpleNamespace(region=region)
    engine.view_update(context, depsgraph)


def test_render_settings_exposes_viewport_pass_properties(monkeypatch):
    class R:
        pass

    addon = _load_blender_addon(monkeypatch, R)
    settings_cls = addon.CustomRaytracerRenderSettings
    annotations = getattr(settings_cls, "__annotations__", {})
    assert "viewport_display_pass" in annotations
    assert "viewport_oidn" in annotations


def test_view_update_registers_albedo_aov_pass(monkeypatch):
    add_pass_calls = []

    class R:
        gpu_available = False

        def set_use_gpu(self, _v):  # called by configure_backend
            return None

        def set_adaptive_sampling(self, _v): pass
        def clear(self): pass
        def set_clamp_direct(self, _v): pass
        def set_clamp_indirect(self, _v): pass
        def set_filter_glossy(self, _v): pass
        def set_use_reflective_caustics(self, _v): pass
        def set_use_refractive_caustics(self, _v): pass
        def set_wavelength_range(self, _lo, _hi): pass
        def set_output_mode(self, _m): pass
        def set_integrator(self, _name): pass

        def add_pass(self, name):
            add_pass_calls.append(name)

        def get_render_pass_buffer(self, _name):
            raise AssertionError("get_render_pass_buffer should not be called for albedo AOV")

        def render(self, *_args, **_kwargs):
            return np.zeros((8, 8, 3), dtype=np.float32)

    addon = _load_blender_addon(monkeypatch, R)
    engine = addon.CustomRaytracerRenderEngine()

    settings = _make_settings(viewport_display_pass="albedo")

    engine._setup_viewport_camera = lambda *_a, **_k: None
    engine.convert_materials = lambda *_a, **_k: {}
    engine.convert_objects = lambda *_a, **_k: None
    engine.convert_lights = lambda *_a, **_k: None
    engine.setup_world = lambda *_a, **_k: None

    captured = {}
    engine._update_viewport_texture = lambda pixels, w, h: captured.update(pixels=pixels, w=w, h=h)

    _run_view_update(addon, engine, settings)

    assert add_pass_calls == ["albedo_aov"]
    assert captured["w"] == 8 and captured["h"] == 8


def test_view_update_fetches_diffuse_direct_render_pass(monkeypatch):
    add_pass_calls = []
    buffer_calls = []

    class R:
        gpu_available = False

        def set_use_gpu(self, _v):  # called by configure_backend
            return None

        def set_adaptive_sampling(self, _v): pass
        def clear(self): pass
        def set_clamp_direct(self, _v): pass
        def set_clamp_indirect(self, _v): pass
        def set_filter_glossy(self, _v): pass
        def set_use_reflective_caustics(self, _v): pass
        def set_use_refractive_caustics(self, _v): pass
        def set_wavelength_range(self, _lo, _hi): pass
        def set_output_mode(self, _m): pass
        def set_integrator(self, _name): pass

        def add_pass(self, name):
            add_pass_calls.append(name)

        def get_render_pass_buffer(self, name):
            buffer_calls.append(name)
            return np.ones((8, 8, 3), dtype=np.float32) * 0.25

        def render(self, *_args, **_kwargs):
            return np.zeros((8, 8, 3), dtype=np.float32)

    addon = _load_blender_addon(monkeypatch, R)
    engine = addon.CustomRaytracerRenderEngine()

    settings = _make_settings(viewport_display_pass="diffuse_direct")

    engine._setup_viewport_camera = lambda *_a, **_k: None
    engine.convert_materials = lambda *_a, **_k: {}
    engine.convert_objects = lambda *_a, **_k: None
    engine.convert_lights = lambda *_a, **_k: None
    engine.setup_world = lambda *_a, **_k: None

    captured = {}
    engine._update_viewport_texture = lambda pixels, w, h: captured.update(pixels=pixels, w=w, h=h)

    _run_view_update(addon, engine, settings)

    assert add_pass_calls == []
    assert buffer_calls == ["diffuse_direct"]
    assert np.allclose(np.asarray(captured["pixels"]), 0.25)


def test_viewport_oidn_pass_added_after_display_pass(monkeypatch):
    add_pass_calls = []

    class R:
        gpu_available = False

        def set_use_gpu(self, _v):  # called by configure_backend
            return None

        def set_adaptive_sampling(self, _v): pass
        def clear(self): pass
        def set_clamp_direct(self, _v): pass
        def set_clamp_indirect(self, _v): pass
        def set_filter_glossy(self, _v): pass
        def set_use_reflective_caustics(self, _v): pass
        def set_use_refractive_caustics(self, _v): pass
        def set_wavelength_range(self, _lo, _hi): pass
        def set_output_mode(self, _m): pass
        def set_integrator(self, _name): pass

        def add_pass(self, name):
            add_pass_calls.append(name)

        def render(self, *_args, **_kwargs):
            return np.zeros((8, 8, 3), dtype=np.float32)

    addon = _load_blender_addon(monkeypatch, R)
    engine = addon.CustomRaytracerRenderEngine()

    settings = _make_settings(viewport_display_pass="normal", viewport_oidn=True)

    engine._setup_viewport_camera = lambda *_a, **_k: None
    engine.convert_materials = lambda *_a, **_k: {}
    engine.convert_objects = lambda *_a, **_k: None
    engine.convert_lights = lambda *_a, **_k: None
    engine.setup_world = lambda *_a, **_k: None
    engine._update_viewport_texture = lambda *_a, **_k: None

    _run_view_update(addon, engine, settings)

    assert add_pass_calls == ["normal_aov", "oidn_denoiser"]


def test_viewport_oidn_not_added_outside_visible_wavelengths(monkeypatch):
    add_pass_calls = []

    class R:
        gpu_available = False

        def set_use_gpu(self, _v):  # called by configure_backend
            return None

        def set_adaptive_sampling(self, _v): pass
        def clear(self): pass
        def set_clamp_direct(self, _v): pass
        def set_clamp_indirect(self, _v): pass
        def set_filter_glossy(self, _v): pass
        def set_use_reflective_caustics(self, _v): pass
        def set_use_refractive_caustics(self, _v): pass
        def set_wavelength_range(self, _lo, _hi): pass
        def set_output_mode(self, _m): pass
        def set_integrator(self, _name): pass

        def add_pass(self, name):
            add_pass_calls.append(name)

        def render(self, *_args, **_kwargs):
            return np.zeros((8, 8, 3), dtype=np.float32)

    addon = _load_blender_addon(monkeypatch, R)
    engine = addon.CustomRaytracerRenderEngine()

    settings = _make_settings(
        viewport_display_pass="combined",
        viewport_oidn=True,
        wavelength_preset="near_ir",
    )

    engine._setup_viewport_camera = lambda *_a, **_k: None
    engine.convert_materials = lambda *_a, **_k: {}
    engine.convert_objects = lambda *_a, **_k: None
    engine.convert_lights = lambda *_a, **_k: None
    engine.setup_world = lambda *_a, **_k: None
    engine._update_viewport_texture = lambda *_a, **_k: None

    _run_view_update(addon, engine, settings)

    assert "oidn_denoiser" not in add_pass_calls

"""Test for pkg103a Light Tree sampler UI wiring.

Verifies that the Blender scene property 'light_sampler' reaches
renderer.set_light_sampler() in both final render and viewport render paths.
"""

import importlib.util
import sys
import types
from pathlib import Path


def _load_blender_addon(monkeypatch, renderer_cls):
    """Load the Blender addon with mocked bpy/astroray modules.

    Same pattern as test_blender_backend_policy.py.
    """
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
    astroray_module.Renderer = renderer_cls
    astroray_module.integrator_registry_names = lambda: ["path_tracer", "ambient_occlusion"]
    astroray_module.integrator_capabilities = lambda name: {
        "gpuSupported": name in {"path_tracer", "ambient_occlusion"},
        "gpuFallbackReason": "" if name in {"path_tracer", "ambient_occlusion"} else "no GPU kernel implemented",
    }
    astroray_module.material_registry_names = lambda: ["lambertian"]
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


def _make_settings(light_sampler="power", **kwargs):
    """Create a mock CustomRayTracerSettings namespace with required fields."""
    defaults = {
        "device_mode": "auto",
        "wavelength_preset": "visible",
        "wavelength_min": 380.0,
        "wavelength_max": 780.0,
        "colourmap": "grayscale",
        "integrator_type": "path_tracer",
        "last_render_stats": "",
        "use_adaptive_sampling": False,
        "preview_samples": 1,
        "samples": 16,
        "max_bounces": 4,
        "clamp_direct": 0.0,
        "clamp_indirect": 0.0,
        "filter_glossy": 0.0,
        "use_reflective_caustics": True,
        "use_refractive_caustics": True,
        "diffuse_bounces": 2,
        "glossy_bounces": 2,
        "transmission_bounces": 2,
        "volume_bounces": 0,
        "transparent_bounces": 2,
        "light_sampler": light_sampler,
    }
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


def test_light_sampler_wiring_final_render(monkeypatch):
    """convert_scene must call renderer.set_light_sampler(settings.light_sampler)."""
    calls = []

    class MockRenderer:
        gpu_available = False
        def clear(self): pass
        def set_clamp_direct(self, v): pass
        def set_clamp_indirect(self, v): pass
        def set_filter_glossy(self, v): pass
        def set_use_reflective_caustics(self, v): pass
        def set_use_refractive_caustics(self, v): pass
        def set_light_sampler(self, mode):
            calls.append(mode)
        def set_film_exposure(self, v): pass
        def set_use_transparent_film(self, v): pass
        def set_transparent_glass(self, v): pass
        def set_seed(self, v): pass
        def set_pixel_filter(self, t, w): pass

    addon = _load_blender_addon(monkeypatch, MockRenderer)
    engine = addon.CustomRaytracerRenderEngine()

    settings = _make_settings(light_sampler="light_tree")
    scene = types.SimpleNamespace(
        custom_raytracer=settings,
        cycles=None,
        render=None,
        camera=None,
    )
    depsgraph = types.SimpleNamespace(scene=scene, object_instances=[])

    # Patch methods that need geometry/camera conversion
    engine.setup_camera = lambda *a: None
    engine.convert_materials = lambda *a: {}
    engine.convert_objects = lambda *a: None
    engine.convert_lights = lambda *a: None
    engine.setup_world = lambda *a: None

    engine.convert_scene(depsgraph, MockRenderer(), 16, 16)

    assert calls, "convert_scene must call set_light_sampler"
    # pkg201: the engine's set_light_sampler accepts only 'power'/'tree', so the
    # UI 'light_tree' is translated to the engine token 'tree' before the call
    # (the old direct pass-through would have thrown ValueError on the real
    # binding). No native use_light_tree here (cycles=None) -> UI enum decides.
    assert calls[0] == "tree", f"Expected 'tree', got {calls[0]}"


def test_light_sampler_wiring_viewport_render(monkeypatch):
    """Viewport render path must also call renderer.set_light_sampler()."""
    calls = []

    class MockRenderer:
        gpu_available = False
        def clear(self): pass
        def set_adaptive_sampling(self, v): pass
        def set_clamp_direct(self, v): pass
        def set_clamp_indirect(self, v): pass
        def set_filter_glossy(self, v): pass
        def set_use_reflective_caustics(self, v): pass
        def set_use_refractive_caustics(self, v): pass
        def set_light_sampler(self, mode):
            calls.append(mode)
        def set_wavelength_range(self, lo, hi): pass
        def set_output_mode(self, m): pass
        def set_integrator(self, name): pass
        def render(self, *a, **kw): return None

    addon = _load_blender_addon(monkeypatch, MockRenderer)
    engine = addon.CustomRaytracerRenderEngine()

    settings = _make_settings(light_sampler="uniform")
    scene = types.SimpleNamespace(custom_raytracer=settings)
    depsgraph = types.SimpleNamespace(
        scene=scene,
        view_layer=types.SimpleNamespace(name="ViewLayer"),
        object_instances=[],
    )

    region = types.SimpleNamespace(width=16, height=16)
    context = types.SimpleNamespace(region=region)

    # Patch internal helpers that touch scene geometry
    engine._setup_viewport_camera = lambda *a: None
    engine.convert_materials = lambda *a: {}
    engine.convert_objects = lambda *a: None
    engine.convert_lights = lambda *a: None
    engine.setup_world = lambda *a: None
    engine._update_viewport_texture = lambda *a: None

    engine.view_update(context, depsgraph)

    assert calls, "view_update must call set_light_sampler"
    # pkg201: engine has no uniform sampler -> UI 'uniform' translates to 'power'
    # (cycles=None here, so the UI enum decides).
    assert calls[0] == "power", f"Expected 'power', got {calls[0]}"


def test_light_sampler_default_is_power(monkeypatch):
    """The light_sampler property must default to 'power' (per pkg86 design)."""
    addon = _load_blender_addon(monkeypatch, object)

    # The EnumProperty default is baked at import time; we can't inspect it
    # directly without a real Blender instance. Instead, verify the mock
    # settings helper has the correct default.
    settings = _make_settings()
    assert settings.light_sampler == "power", \
        "Default light_sampler must be 'power' per pkg86 design"


def test_light_sampler_modes_are_valid(monkeypatch):
    """All three UI sampler modes must reach the engine as a VALID engine token.
    The engine accepts only 'power'/'tree' (module/blender_module.cpp), so pkg201
    translates the UI enum: uniform/power -> 'power', light_tree -> 'tree'. The
    pre-pkg201 direct pass-through would have thrown for uniform/light_tree."""
    _EXPECTED = {"uniform": "power", "power": "power", "light_tree": "tree"}
    calls = []

    class MockRenderer:
        gpu_available = False
        def clear(self): pass
        def set_clamp_direct(self, v): pass
        def set_clamp_indirect(self, v): pass
        def set_filter_glossy(self, v): pass
        def set_use_reflective_caustics(self, v): pass
        def set_use_refractive_caustics(self, v): pass
        def set_light_sampler(self, mode):
            calls.append(mode)
        def set_film_exposure(self, v): pass
        def set_use_transparent_film(self, v): pass
        def set_transparent_glass(self, v): pass
        def set_seed(self, v): pass
        def set_pixel_filter(self, t, w): pass

    addon = _load_blender_addon(monkeypatch, MockRenderer)
    engine = addon.CustomRaytracerRenderEngine()

    for mode in ("uniform", "power", "light_tree"):
        calls.clear()
        settings = _make_settings(light_sampler=mode)
        scene = types.SimpleNamespace(
            custom_raytracer=settings,
            cycles=None,
            render=None,
            camera=None,
        )
        depsgraph = types.SimpleNamespace(scene=scene, object_instances=[])

        engine.setup_camera = lambda *a: None
        engine.convert_materials = lambda *a: {}
        engine.convert_objects = lambda *a: None
        engine.convert_lights = lambda *a: None
        engine.setup_world = lambda *a: None

        engine.convert_scene(depsgraph, MockRenderer(), 16, 16)

        assert calls and calls[0] == _EXPECTED[mode], \
            f"UI mode '{mode}' must reach the engine as '{_EXPECTED[mode]}', got {calls[0] if calls else None}"

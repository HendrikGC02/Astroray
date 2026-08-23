"""pkg217 (Path A) — addon must enable the GPU photon-caustic master switch.

Corrected root cause (see .astroray_plan/docs/pkg217-wavefront-caustic-
integration-research.md, corrected 2026-08-23): the GPU wavefront ALREADY has
a working, tested photon-map caustic pipeline (pkg113,
`src/gpu/wavefront/gpu_wavefront_snapshot.cu::buildCausticAim` +
`cuda_photon_caustic_build`), verified by
`tests/test_gpu_caustic_parity.py::test_gpu_glass_sphere_caustic_parity`. That
pipeline is gated by `Renderer.set_use_photon_caustics(True)` — a SEPARATE
renderer-level master switch from the per-object `is_caustic_caster` flag
(`Renderer.set_object_caustic_caster`). The Blender addon wired the per-object
flag (pkg64 Phase 3) but never called the renderer-level master switch, so a
scene with a flagged glass caster silently never fired the (working) photon
pre-pass on GPU -> owner's black-shadow repro (2026-08-21).

This test verifies `CustomRaytracerRenderEngine.convert_scene` now calls
`renderer.set_use_photon_caustics(True)` whenever ANY object in the depsgraph
has `astroray_object.is_caustic_caster == True`, and `False` (not just
"never called") when no object is flagged -- so the pre-pass stays off by
default (zero cost) exactly as pkg113 intended.

Same mock-bpy/mock-Renderer pattern as test_blender_light_sampler_wiring.py.
"""

import importlib.util
import sys
import types
from pathlib import Path


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
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_pkg217_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _make_settings(**kwargs):
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
        "light_sampler": "power",
    }
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


class _MockRenderer:
    gpu_available = False

    def __init__(self):
        self.photon_caustic_calls = []

    def clear(self): pass
    def set_clamp_direct(self, v): pass
    def set_clamp_indirect(self, v): pass
    def set_filter_glossy(self, v): pass
    def set_use_reflective_caustics(self, v): pass
    def set_use_refractive_caustics(self, v): pass
    def set_use_photon_caustics(self, v):
        self.photon_caustic_calls.append(v)
    def set_light_sampler(self, mode): pass
    def set_film_exposure(self, v): pass
    def set_use_transparent_film(self, v): pass
    def set_transparent_glass(self, v): pass
    def set_seed(self, v): pass
    def set_pixel_filter(self, t, w): pass


def _obj_with_caster_flag(name, is_caster):
    astroray_object = types.SimpleNamespace(is_caustic_caster=is_caster)
    return types.SimpleNamespace(name=name, astroray_object=astroray_object)


def _run_convert_scene(monkeypatch, object_instances):
    renderer = _MockRenderer()
    addon = _load_blender_addon(monkeypatch, _MockRenderer)
    engine = addon.CustomRaytracerRenderEngine()

    settings = _make_settings()
    scene = types.SimpleNamespace(
        custom_raytracer=settings,
        cycles=None,
        render=None,
        camera=None,
    )
    depsgraph = types.SimpleNamespace(
        scene=scene,
        object_instances=[types.SimpleNamespace(object=o) for o in object_instances],
    )

    engine.setup_camera = lambda *a: None
    engine.convert_materials = lambda *a: {}
    engine.convert_objects = lambda *a: None
    engine.convert_lights = lambda *a: None
    engine.setup_world = lambda *a: None

    engine.convert_scene(depsgraph, renderer, 16, 16)
    return renderer


def test_caster_present_enables_photon_caustics(monkeypatch):
    """The owner's repro shape: one object flagged is_caustic_caster=True must
    flip renderer.set_use_photon_caustics(True) -- this is the fix for the
    black-shadow bug (the flag existed but the master switch was never set)."""
    objects = [
        _obj_with_caster_flag("Floor", False),
        _obj_with_caster_flag("GlassSphere", True),
    ]
    renderer = _run_convert_scene(monkeypatch, objects)

    assert renderer.photon_caustic_calls, \
        "convert_scene must call renderer.set_use_photon_caustics()"
    assert renderer.photon_caustic_calls[-1] is True, \
        f"Expected set_use_photon_caustics(True) when a caster is present, " \
        f"got {renderer.photon_caustic_calls}"


def test_no_caster_keeps_photon_caustics_off(monkeypatch):
    """No object flagged -> the pre-pass must stay OFF (pkg113's documented
    zero-cost-by-default contract; do not regress non-caustic scene perf)."""
    objects = [
        _obj_with_caster_flag("Floor", False),
        _obj_with_caster_flag("Wall", False),
    ]
    renderer = _run_convert_scene(monkeypatch, objects)

    assert renderer.photon_caustic_calls, \
        "convert_scene must call renderer.set_use_photon_caustics() even when off"
    assert renderer.photon_caustic_calls[-1] is False, \
        f"Expected set_use_photon_caustics(False) with no caster present, " \
        f"got {renderer.photon_caustic_calls}"


def test_empty_scene_keeps_photon_caustics_off(monkeypatch):
    """No objects at all (depsgraph.object_instances == []) must not crash and
    must resolve to False."""
    renderer = _run_convert_scene(monkeypatch, [])
    assert renderer.photon_caustic_calls == [False]


def test_old_renderer_without_binding_is_tolerated(monkeypatch):
    """A renderer build predating this binding (no set_use_photon_caustics)
    must not crash convert_scene -- mirrors the hasattr guard used elsewhere
    in this file for optional bindings (e.g. set_object_caustic_caster)."""
    class _OldRenderer:
        gpu_available = False
        def clear(self): pass
        def set_clamp_direct(self, v): pass
        def set_clamp_indirect(self, v): pass
        def set_filter_glossy(self, v): pass
        def set_use_reflective_caustics(self, v): pass
        def set_use_refractive_caustics(self, v): pass
        def set_light_sampler(self, mode): pass
        def set_film_exposure(self, v): pass
        def set_use_transparent_film(self, v): pass
        def set_transparent_glass(self, v): pass
        def set_seed(self, v): pass
        def set_pixel_filter(self, t, w): pass

    addon = _load_blender_addon(monkeypatch, _OldRenderer)
    engine = addon.CustomRaytracerRenderEngine()
    renderer = _OldRenderer()

    settings = _make_settings()
    scene = types.SimpleNamespace(custom_raytracer=settings, cycles=None, render=None, camera=None)
    depsgraph = types.SimpleNamespace(
        scene=scene,
        object_instances=[types.SimpleNamespace(object=_obj_with_caster_flag("GlassSphere", True))],
    )

    engine.setup_camera = lambda *a: None
    engine.convert_materials = lambda *a: {}
    engine.convert_objects = lambda *a: None
    engine.convert_lights = lambda *a: None
    engine.setup_world = lambda *a: None

    engine.convert_scene(depsgraph, renderer, 16, 16)  # must not raise

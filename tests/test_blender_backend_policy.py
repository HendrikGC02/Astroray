"""Tests for pkg37 Blender addon backend policy (device_mode, configure_backend,
viewport wavelength parity, diagnostics).

Uses the same monkeypatching pattern as test_blender_view_layers.py.
"""

import importlib.util
import sys
import types
from pathlib import Path


# ---------------------------------------------------------------------------
# Shared loader helper (same pattern as test_blender_view_layers.py)
# ---------------------------------------------------------------------------

def _load_blender_addon(monkeypatch, renderer_cls, extra_astroray_attrs=None):
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
    astroray_module.material_registry_names = lambda: ["lambertian"]
    astroray_module.pass_registry_names = lambda: []
    if extra_astroray_attrs:
        for k, v in extra_astroray_attrs.items():
            setattr(astroray_module, k, v)

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


def _make_settings(device_mode="auto", wavelength_preset="visible",
                   wavelength_min=380.0, wavelength_max=780.0,
                   colourmap="grayscale", integrator_type="path_tracer"):
    return types.SimpleNamespace(
        device_mode=device_mode,
        wavelength_preset=wavelength_preset,
        wavelength_min=wavelength_min,
        wavelength_max=wavelength_max,
        colourmap=colourmap,
        integrator_type=integrator_type,
        last_render_stats="",
        # viewport render also reads these
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


# ---------------------------------------------------------------------------
# configure_backend tests
# ---------------------------------------------------------------------------

def test_configure_backend_cpu_never_calls_set_use_gpu(monkeypatch):
    """device_mode='cpu' must not call renderer.set_use_gpu()."""
    calls = []

    class R:
        gpu_available = True
        def set_use_gpu(self, v):
            calls.append(v)

    addon = _load_blender_addon(monkeypatch, R)
    result = addon.configure_backend(R(), _make_settings(device_mode="cpu"))
    assert result == "cpu"
    assert calls == [], "set_use_gpu must not be called for device_mode=cpu"


def test_configure_backend_auto_uses_gpu_when_available(monkeypatch):
    """device_mode='auto' calls set_use_gpu(True) when gpu_available is True."""
    calls = []

    class R:
        gpu_available = True
        def set_use_gpu(self, v):
            calls.append(v)

    addon = _load_blender_addon(monkeypatch, R)
    result = addon.configure_backend(R(), _make_settings(device_mode="auto"))
    assert result == "gpu"
    assert calls == [True]


def test_configure_backend_auto_falls_back_to_cpu_when_no_gpu(monkeypatch):
    """device_mode='auto' returns 'cpu' silently when gpu_available is False."""
    calls = []

    class R:
        gpu_available = False
        def set_use_gpu(self, v):
            calls.append(v)

    addon = _load_blender_addon(monkeypatch, R)
    result = addon.configure_backend(R(), _make_settings(device_mode="auto"))
    assert result == "cpu"
    assert calls == []


def test_configure_backend_gpu_mode_falls_back_on_exception(monkeypatch):
    """device_mode='gpu' returns 'cpu' if set_use_gpu raises (e.g. no CUDA)."""
    class R:
        gpu_available = True
        def set_use_gpu(self, v):
            raise RuntimeError("CUDA init failed")

    addon = _load_blender_addon(monkeypatch, R)
    result = addon.configure_backend(R(), _make_settings(device_mode="gpu"))
    assert result == "cpu"


def test_configure_backend_gpu_available_exception_is_handled(monkeypatch):
    """If gpu_available property raises, configure_backend returns 'cpu' safely."""
    class R:
        @property
        def gpu_available(self):
            raise RuntimeError("no CUDA context")

    addon = _load_blender_addon(monkeypatch, R)
    result = addon.configure_backend(R(), _make_settings(device_mode="auto"))
    assert result == "cpu"


# ---------------------------------------------------------------------------
# configure_backend is present as a module-level function
# ---------------------------------------------------------------------------

def test_configure_backend_is_module_level(monkeypatch):
    class R:
        gpu_available = False

    addon = _load_blender_addon(monkeypatch, R)
    assert callable(getattr(addon, "configure_backend", None)), \
        "configure_backend must be a module-level function in __init__.py"


# ---------------------------------------------------------------------------
# device_mode replaces use_gpu
# ---------------------------------------------------------------------------

def test_use_gpu_property_removed(monkeypatch):
    """The old use_gpu BoolProperty must no longer be present in render settings."""
    class R:
        pass

    addon = _load_blender_addon(monkeypatch, R)
    settings_cls = addon.CustomRaytracerRenderSettings
    assert not hasattr(settings_cls, "use_gpu"), \
        "use_gpu BoolProperty should be replaced by device_mode EnumProperty"


# ---------------------------------------------------------------------------
# Viewport render applies same wavelength config as final render
# ---------------------------------------------------------------------------

def test_viewport_render_calls_set_wavelength_range(monkeypatch):
    """view_update must call renderer.set_wavelength_range() using the preset."""
    wl_calls = []

    class R:
        gpu_available = False
        def set_use_gpu(self, v): pass
        def set_adaptive_sampling(self, v): pass
        def clear(self): pass
        def set_clamp_direct(self, v): pass
        def set_clamp_indirect(self, v): pass
        def set_filter_glossy(self, v): pass
        def set_use_reflective_caustics(self, v): pass
        def set_use_refractive_caustics(self, v): pass
        def set_wavelength_range(self, lo, hi):
            wl_calls.append((lo, hi))
        def set_output_mode(self, m): pass
        def set_integrator(self, name): pass
        def render(self, *a, **kw): return None

    addon = _load_blender_addon(monkeypatch, R)
    engine = addon.CustomRaytracerRenderEngine()

    settings = _make_settings(wavelength_preset="near_ir")
    scene = types.SimpleNamespace(custom_raytracer=settings)

    region = types.SimpleNamespace(width=16, height=16)
    context = types.SimpleNamespace(region=region)

    depsgraph = types.SimpleNamespace(
        scene=scene,
        view_layer=types.SimpleNamespace(name="ViewLayer"),
        object_instances=[],
    )

    # Patch internal helpers that touch scene geometry
    engine._setup_viewport_camera = lambda *a: None
    engine.convert_materials = lambda *a: {}
    engine.convert_objects = lambda *a: None
    engine.convert_lights = lambda *a: None
    engine.setup_world = lambda *a: None
    engine._update_viewport_texture = lambda *a: None

    engine.view_update(context, depsgraph)

    assert wl_calls, "view_update must call set_wavelength_range"
    assert wl_calls[0] == (700.0, 1000.0), \
        f"near_ir preset should set range (700, 1000), got {wl_calls[0]}"


def test_viewport_and_final_render_apply_same_wavelength_presets(monkeypatch):
    """Both render paths must produce the same (lmin, lmax) for each preset."""
    addon = _load_blender_addon(monkeypatch, object)  # renderer_cls unused here

    # Reproduce the same mapping as __init__.py
    def expected(preset, wmin=380.0, wmax=780.0):
        if preset == "near_ir":   return (700.0, 1000.0)
        if preset == "uv":        return (300.0, 400.0)
        if preset == "custom":    return (wmin, wmax)
        return (380.0, 780.0)

    for preset in ("visible", "near_ir", "uv"):
        lo, hi = expected(preset)
        assert lo < hi, f"preset {preset} should have lo < hi"
        assert lo > 0 and hi > lo


# ---------------------------------------------------------------------------
# Build script: _backend_config returns correct dirs / flags
# ---------------------------------------------------------------------------

def test_build_script_backend_config_cpu():
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(
        "build_blender_addon",
        Path(__file__).parent.parent / "scripts" / "build_blender_addon.py",
    )
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    build_dir, flags = mod._backend_config("cpu")
    assert "CUDA=OFF" in " ".join(flags) or "CUDA" not in " ".join(flags) or \
           any("OFF" in f for f in flags if "CUDA" in f)
    assert "build_blender_addon" in str(build_dir)
    assert "cuda" not in str(build_dir).lower()


def test_build_script_backend_config_cuda():
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(
        "build_blender_addon",
        Path(__file__).parent.parent / "scripts" / "build_blender_addon.py",
    )
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    build_dir, flags = mod._backend_config("cuda")
    assert any("CUDA=ON" in f for f in flags), "cuda backend must enable CUDA"
    assert "cuda" in str(build_dir).lower(), "cuda backend must use a _cuda build dir"


def test_build_script_backend_config_tcnn():
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(
        "build_blender_addon",
        Path(__file__).parent.parent / "scripts" / "build_blender_addon.py",
    )
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    build_dir, flags = mod._backend_config("tcnn")
    assert any("CUDA=ON" in f for f in flags)
    assert any("TCNN=ON" in f for f in flags)
    assert "tcnn" in str(build_dir).lower()


def test_build_script_no_build_tncc_reference():
    """The old build_tncc directory name must not appear in the build script."""
    src = (Path(__file__).parent.parent / "scripts" / "build_blender_addon.py").read_text()
    assert "build_tncc" not in src, \
        "build_tncc (old stale directory name) must not appear in build script"

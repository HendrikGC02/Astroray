"""#814 item 4 — PREETHAM / HOSEK_WILKIE sky types route to the engine Nishita
sky with a degradation warning (blender_addon/__init__.py setup_world).

Astroray implements only the vendored Nishita (SINGLE/MULTIPLE_SCATTERING)
sky. Blender's legacy PREETHAM / HOSEK_WILKIE models are not implemented, so
setup_world renders them as MULTIPLE_SCATTERING and MUST emit a degradation
warning naming the substitution (pkg200 rule: never silently dropped). Unit
level (stub bpy, real setup_world code path — no Blender, no GPU)."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


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

    astroray_module = types.ModuleType("astroray")
    astroray_module.__version__ = "test"
    astroray_module.__features__ = {"cuda": False, "spectral": True}
    astroray_module.__file__ = "/fake/astroray.pyd"
    astroray_module.integrator_registry_names = lambda: ["path_tracer"]
    astroray_module.material_registry_names = lambda: ["lambertian"]
    astroray_module.pass_registry_names = list
    # NOTE: no nishita_sky/nishita_sun on the stub — the bake attempt raises and
    # is caught by setup_world's guard AFTER the degradation warning fires, which
    # is exactly what we assert. Keeps the test free of numpy/HDR temp files.

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    module_path = REPO_ROOT / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_batchl_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _RecordingRenderer:
    def set_background_color(self, color): pass
    def set_world_volume(self, *a, **k): pass
    def set_world_max_bounces(self, *a, **k): pass
    def load_environment_map(self, *a, **k): return False
    def add_sun_light_dedicated(self, *a, **k): pass


def _sky_world(sky_type):
    sky_node = types.SimpleNamespace(type='TEX_SKY', sky_type=sky_type,
                                     sun_elevation=0.4, sun_rotation=0.6,
                                     sun_disc=True)
    node_tree = types.SimpleNamespace(nodes=[sky_node])
    return types.SimpleNamespace(node_tree=node_tree, cycles=None)


def _run(monkeypatch, sky_type):
    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()
    warnings = []
    engine._warn_shader_fallback = lambda node_type, message: warnings.append((node_type, message))
    scene = types.SimpleNamespace(world=_sky_world(sky_type))
    engine.setup_world(scene, _RecordingRenderer())
    return warnings


@pytest.mark.parametrize("sky_type", ["PREETHAM", "HOSEK_WILKIE"])
def test_legacy_sky_type_warns_rendered_as_nishita(monkeypatch, sky_type):
    warnings = _run(monkeypatch, sky_type)
    msgs = [m for (nt, m) in warnings if nt == 'TEX_SKY']
    assert any("Nishita" in m and sky_type in m for m in msgs), (
        f"{sky_type} must warn it is rendered as the Nishita sky; got {warnings}")


@pytest.mark.parametrize("sky_type", ["SINGLE_SCATTERING", "MULTIPLE_SCATTERING"])
def test_nishita_types_do_not_get_legacy_warning(monkeypatch, sky_type):
    """Native Nishita types must NOT emit the 'not implemented' legacy warning."""
    warnings = _run(monkeypatch, sky_type)
    msgs = [m for (nt, m) in warnings if nt == 'TEX_SKY']
    assert not any("is not implemented" in m for m in msgs), (
        f"{sky_type} is native Nishita and must not warn 'not implemented'; got {warnings}")

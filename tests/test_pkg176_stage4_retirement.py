"""pkg176 Stage 4 - custom-UI retirement unit tests.

Pure Python, no live Blender / engine / GPU. Loads ``blender_addon/__init__.py``
under a stub ``bpy`` (same monkeypatch pattern as test_pkg176_stage2_panel_adoption.py)
extended with a ``bpy.utils`` class-registration recorder and Scene/Material/Object
id-types so ``register()`` / ``unregister()`` can be driven end-to-end.

Acceptance covered:
  (a) the 14 DIRECT-mapped custom alias properties are GONE from
      CustomRaytracerRenderSettings, while the genuinely engine-unique /
      semantically-mismatched props remain;
  (b) no retired custom panel/property-group class lingers in ``classes``; the
      single object-level "Astroray" panel and the astroray-only render panels
      are still registered;
  (c) register()/unregister() are consistent - every class registered is
      unregistered exactly once, and nothing is unregistered that was never
      registered;
  (d) after register() the adopted native Cycles Light Paths panels honour
      CUSTOM_RAYTRACER, and after unregister() they no longer do.
"""

import importlib.util
import sys
import types
from pathlib import Path
from typing import ClassVar

import pytest

_ADDON = Path(__file__).resolve().parents[1] / "blender_addon"

# The retired DIRECT-mapped custom duplicates (former custom_raytracer.* attrs).
RETIRED_ALIAS_ATTRS = {
    "samples", "preview_samples",
    "max_bounces", "diffuse_bounces", "glossy_bounces",
    "transmission_bounces", "volume_bounces", "transparent_bounces",
    "clamp_direct", "clamp_indirect", "filter_glossy",
    "use_reflective_caustics", "use_refractive_caustics", "use_denoising",
}

# Genuinely engine-unique / mismatched props that MUST survive retirement.
KEPT_ASTRORAY_ONLY_ATTRS = {
    "wavelength_preset", "wavelength_min", "wavelength_max", "colourmap",
    "device_mode", "integrator_type", "viewport_display_pass",
    "denoiser_backend", "cryptomatte_depth",
    # not-yet-plumbed native controls kept custom-only (approximated / dropped):
    "light_sampler", "use_adaptive_sampling", "adaptive_threshold",
}

ADOPTED = (
    "CYCLES_RENDER_PT_light_paths",
    "CYCLES_RENDER_PT_light_paths_max_bounces",
    "CYCLES_RENDER_PT_light_paths_clamping",
    "CYCLES_RENDER_PT_light_paths_caustics",
)


def _make_cycles_types(bpy_types_module):
    """Fake Cycles panels sharing ONE inherited COMPAT_ENGINES set (as in real
    Blender), so an in-place mutation leak would be detectable."""

    class CyclesButtonsPanel:
        COMPAT_ENGINES: ClassVar[set] = {'CYCLES'}

    for name in (*ADOPTED, "CYCLES_RENDER_PT_sampling_render"):
        setattr(bpy_types_module, name, type(name, (CyclesButtonsPanel,), {}))


def _load_addon(monkeypatch):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")
    bpy_utils_module = types.ModuleType("bpy.utils")

    class _Base:
        pass

    class _RenderEngineBase:
        def report(self, *_a, **_k):
            return None

        def update_progress(self, *_a, **_k):
            return None

        def test_break(self):
            return False

    bpy_types_module.Panel = _Base
    bpy_types_module.Operator = _Base
    bpy_types_module.AddonPreferences = _Base
    bpy_types_module.PropertyGroup = _Base
    bpy_types_module.RenderEngine = _RenderEngineBase

    # id-types register() attaches PointerProperties to.
    class _Scene: pass
    class _Material: pass
    class _Object: pass
    bpy_types_module.Scene = _Scene
    bpy_types_module.Material = _Material
    bpy_types_module.Object = _Object

    # bpy.utils.register_class / unregister_class recorder.
    registered = []
    unregistered = []
    bpy_utils_module.register_class = lambda cls: registered.append(cls)
    bpy_utils_module.unregister_class = lambda cls: unregistered.append(cls)

    bpy_module.types = bpy_types_module
    bpy_module.utils = bpy_utils_module

    for name in ("BoolProperty", "IntProperty", "FloatProperty", "StringProperty",
                 "PointerProperty", "FloatVectorProperty", "EnumProperty"):
        setattr(bpy_props_module, name, lambda **_k: None)
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

    _make_cycles_types(bpy_types_module)

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "bpy.utils", bpy_utils_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    spec = importlib.util.spec_from_file_location(
        "astroray_addon_pkg176s4_test", _ADDON / "__init__.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, bpy_types_module, registered, unregistered


# --------------------------------------------------------------------------- #
# (a) the retired alias props are gone; astroray-only props remain
# --------------------------------------------------------------------------- #

def test_retired_alias_props_removed_kept_ones_remain(monkeypatch):
    addon, _bt, _reg, _unreg = _load_addon(monkeypatch)
    ann = set(addon.CustomRaytracerRenderSettings.__annotations__)

    leaked = RETIRED_ALIAS_ATTRS & ann
    assert not leaked, f"retired alias props still declared: {sorted(leaked)}"

    missing = KEPT_ASTRORAY_ONLY_ATTRS - ann
    assert not missing, f"engine-unique props wrongly removed: {sorted(missing)}"


def test_retired_set_equals_stage0_direct_aliases(monkeypatch):
    """The props removed here are EXACTLY the direct-mapped custom duplicates the
    Stage-0 contract / Stage-1 resolver enumerate - the retirement stays tied to
    the single source of truth (native_settings.DIRECT_ALIASES)."""
    _addon, _bt, _reg, _unreg = _load_addon(monkeypatch)
    spec = importlib.util.spec_from_file_location(
        "pkg176s4_native_settings", _ADDON / "native_settings.py")
    ns = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ns)
    assert {c for _, c in ns.DIRECT_ALIASES} == RETIRED_ALIAS_ATTRS


# --------------------------------------------------------------------------- #
# (b) no retired panel/property-group class lingers; the kept ones remain
# --------------------------------------------------------------------------- #

def test_no_retired_panel_classes_kept_ones_present(monkeypatch):
    addon, _bt, _reg, _unreg = _load_addon(monkeypatch)
    class_names = {c.__name__ for c in addon.classes}

    # Stage 2 already retired the custom Light Paths panel; it must stay gone.
    assert "RENDER_PT_custom_raytracer_light_paths" not in class_names
    assert not hasattr(addon, "RENDER_PT_custom_raytracer_light_paths")

    # single object-level "Astroray" panel + astroray-only render panels remain.
    assert "OBJECT_PT_astroray_object" in class_names
    for kept in ("RENDER_PT_custom_raytracer_sampling",
                 "RENDER_PT_custom_raytracer_performance",
                 "RENDER_PT_custom_raytracer_wavelength",
                 "RENDER_PT_custom_raytracer_diagnostics"):
        assert kept in class_names, kept


def test_classes_list_has_no_duplicates(monkeypatch):
    addon, _bt, _reg, _unreg = _load_addon(monkeypatch)
    assert len(addon.classes) == len(set(addon.classes))


# --------------------------------------------------------------------------- #
# (c)+(d) register()/unregister() are consistent and drive panel adoption
# --------------------------------------------------------------------------- #

def test_register_unregister_consistent_and_adopts_panels(monkeypatch):
    addon, bt, registered, unregistered = _load_addon(monkeypatch)

    addon.register()

    # every declared class was registered exactly once, in order.
    assert registered == list(addon.classes)
    # adopted native panels now honour our engine.
    for name in ADOPTED:
        assert 'CUSTOM_RAYTRACER' in getattr(bt, name).COMPAT_ENGINES, name
    # pointer properties attached.
    assert hasattr(bt.Scene, "custom_raytracer")
    assert hasattr(bt.Object, "astroray_object")

    addon.unregister()

    # nothing unregistered that was never registered, and all are torn down.
    assert set(unregistered) == set(registered)
    assert len(unregistered) == len(registered)
    # adopted panels released.
    for name in ADOPTED:
        assert 'CUSTOM_RAYTRACER' not in getattr(bt, name).COMPAT_ENGINES, name
    # pointer properties removed.
    assert not hasattr(bt.Scene, "custom_raytracer")
    assert not hasattr(bt.Object, "astroray_object")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

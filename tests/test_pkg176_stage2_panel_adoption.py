"""pkg176 Stage 2 - native Cycles panel adoption unit tests.

Pure Python, no live Blender / engine / GPU. Loads ``blender_addon/__init__.py``
under a stub ``bpy`` (same monkeypatch pattern as test_blender_backend_policy.py)
and injects fake Cycles panel classes into ``bpy.types`` that mirror the real
Blender 5.1 inheritance shape (all Cycles panels share ONE ``COMPAT_ENGINES``
set inherited from ``CyclesButtonsPanel``).

Acceptance covered:
  (a) each adopted native panel gets 'CUSTOM_RAYTRACER' in its COMPAT_ENGINES
      after _adopt_native_panels(), and a NON-adopted Cycles panel does NOT
      (proves the shared-base set is not mutated in place -> no leak);
  (b) the retired custom duplicate panel (RENDER_PT_custom_raytracer_light_paths)
      is gone, while the kept custom panels (Sampling/Performance) remain;
  (c) _adopt_native_panels() RAISES a clear, panel-naming error if an adopted
      panel is missing from bpy.types (a Blender rename/removal).
"""

import importlib.util
import sys
import types
from pathlib import Path
from typing import ClassVar

import pytest

_ADDON = Path(__file__).resolve().parents[1] / "blender_addon"


def _make_cycles_types(bpy_types_module):
    """Attach fake Cycles panel classes to the stub bpy.types, reproducing the
    real inheritance: every panel shares ONE COMPAT_ENGINES set from the base."""

    class CyclesButtonsPanel:
        COMPAT_ENGINES: ClassVar[set] = {'CYCLES'}

    names = (
        "CYCLES_RENDER_PT_light_paths",
        "CYCLES_RENDER_PT_light_paths_max_bounces",
        "CYCLES_RENDER_PT_light_paths_clamping",
        "CYCLES_RENDER_PT_light_paths_caustics",
        # a non-adopted Cycles panel that shares the SAME inherited set:
        "CYCLES_RENDER_PT_sampling_render",
    )
    for name in names:
        setattr(bpy_types_module, name, type(name, (CyclesButtonsPanel,), {}))
    return CyclesButtonsPanel


def _load_addon(monkeypatch):
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_props_module = types.ModuleType("bpy.props")

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
    bpy_module.types = bpy_types_module

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

    base = _make_cycles_types(bpy_types_module)

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    spec = importlib.util.spec_from_file_location(
        "astroray_addon_pkg176s2_test", _ADDON / "__init__.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, bpy_types_module, base


ADOPTED = (
    "CYCLES_RENDER_PT_light_paths",
    "CYCLES_RENDER_PT_light_paths_max_bounces",
    "CYCLES_RENDER_PT_light_paths_clamping",
    "CYCLES_RENDER_PT_light_paths_caustics",
)


def test_adopted_list_is_exactly_the_honest_light_path_panels(monkeypatch):
    addon, _types, _base = _load_addon(monkeypatch)
    assert tuple(addon.ADOPTED_NATIVE_PANELS) == ADOPTED
    # fast-GI (dropped use_fast_gi) and any sampling panel must NOT be adopted.
    assert "CYCLES_RENDER_PT_light_paths_fast_gi" not in addon.ADOPTED_NATIVE_PANELS
    assert not any(n.startswith("CYCLES_RENDER_PT_sampling")
                   for n in addon.ADOPTED_NATIVE_PANELS)


def test_adopt_adds_engine_without_leaking_to_shared_base(monkeypatch):
    """(a) adopted panels honour our engine; a non-adopted Cycles panel sharing
    the inherited COMPAT_ENGINES set is untouched."""
    addon, bt, base = _load_addon(monkeypatch)

    addon._adopt_native_panels()

    for name in ADOPTED:
        panel = getattr(bt, name)
        assert 'CUSTOM_RAYTRACER' in panel.COMPAT_ENGINES, name
        assert 'CYCLES' in panel.COMPAT_ENGINES, name

    # The shared base set (and thus every non-adopted Cycles panel) must stay
    # Cycles-only. If _adopt mutated the inherited set in place this would fail.
    assert base.COMPAT_ENGINES == {'CYCLES'}
    non_adopted = bt.CYCLES_RENDER_PT_sampling_render
    assert 'CUSTOM_RAYTRACER' not in non_adopted.COMPAT_ENGINES


def test_release_removes_engine(monkeypatch):
    addon, bt, _base = _load_addon(monkeypatch)
    addon._adopt_native_panels()
    addon._release_native_panels()
    for name in ADOPTED:
        assert 'CUSTOM_RAYTRACER' not in getattr(bt, name).COMPAT_ENGINES, name


def test_missing_panel_fails_loud_at_adopt(monkeypatch):
    """(c) a renamed/removed adopted panel raises a clear, panel-naming error."""
    addon, bt, _base = _load_addon(monkeypatch)
    delattr(bt, "CYCLES_RENDER_PT_light_paths_clamping")
    with pytest.raises(RuntimeError) as exc:
        addon._adopt_native_panels()
    msg = str(exc.value)
    assert "CYCLES_RENDER_PT_light_paths_clamping" in msg
    assert "ADOPTED_NATIVE_PANELS" in msg


def test_redundant_custom_panel_retired_kept_ones_remain(monkeypatch):
    """(b) the custom Light Paths duplicate is gone; the astroray-only custom
    Sampling / Performance panels are retained."""
    addon, _bt, _base = _load_addon(monkeypatch)

    assert not hasattr(addon, "RENDER_PT_custom_raytracer_light_paths")
    class_names = {c.__name__ for c in addon.classes}
    assert "RENDER_PT_custom_raytracer_light_paths" not in class_names
    # kept: samples has no honest native home; performance holds astroray-only device_mode.
    assert "RENDER_PT_custom_raytracer_sampling" in class_names
    assert "RENDER_PT_custom_raytracer_performance" in class_names

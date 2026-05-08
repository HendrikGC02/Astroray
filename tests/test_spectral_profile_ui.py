"""pkg58: Spectral profile dropdown + preview panel.

These tests stub the Blender Python API and load the addon module directly
from blender_addon/__init__.py, while using the real `astroray` module.
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

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)

    module_path = Path(__file__).parent.parent / "blender_addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("astroray_blender_addon_test_pkg58", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_spectral_profile_enum_items_match_astroray_names(monkeypatch, astroray_module):
    addon = _load_blender_addon(monkeypatch)

    names = list(astroray_module.spectral_profile_names())
    items = addon._spectral_profile_items(None, None)

    assert items and items[0][0] == "__none__"
    item_names = [i[0] for i in items if i[0] != "__none__"]
    assert item_names == names


def test_curve_samples_match_reflectance_within_one_percent(monkeypatch, astroray_module):
    addon = _load_blender_addon(monkeypatch)

    names = list(astroray_module.spectral_profile_names())
    assert names, "spectral_profile_names() should return at least one name"

    name = names[0]
    lmin, lmax = 700.0, 1000.0
    samples = addon._spectral_profile_curve_samples(name, lmin, lmax, n=32)

    assert len(samples) == 32
    assert abs(samples[0][0] - lmin) < 1e-6
    assert abs(samples[-1][0] - lmax) < 1e-6

    for wl, r in samples:
        ref = float(astroray_module.spectral_profile_reflectance(name, float(wl)))
        if abs(ref) > 1e-6:
            assert abs(r - ref) / abs(ref) <= 0.01
        else:
            assert abs(r - ref) <= 0.01


def test_preview_panel_poll_hides_for_visible_preset(monkeypatch, astroray_module):
    addon = _load_blender_addon(monkeypatch)

    material = types.SimpleNamespace(custom_raytracer=types.SimpleNamespace(spectral_profile="__none__"))
    scene = types.SimpleNamespace(
        render=types.SimpleNamespace(engine="CUSTOM_RAYTRACER"),
        custom_raytracer=types.SimpleNamespace(wavelength_preset="visible"),
    )
    ctx = types.SimpleNamespace(scene=scene, material=material)

    panel_cls = addon.MATERIAL_PT_AstroraySpectralPreview
    assert panel_cls.poll(ctx) is False

    scene.custom_raytracer.wavelength_preset = "near_ir"
    assert panel_cls.poll(ctx) is True


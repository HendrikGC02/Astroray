"""pkg213 — expose light intensity (Power) in the Astroray light panel.

The package is a one-line UI-surfacing fix: ``DATA_PT_custom_raytracer_light.draw``
now draws ``layout.prop(light, "energy")``. The engine has always consumed that
value (``convert_lights`` reads ``intensity = float(light.energy)`` at
``blender_addon/__init__.py:4632`` and passes it to every ``add_*_light*`` call),
so the intensity is *wired but not exposed* — this package only surfaces it.

Three gates live here (all machine-verifiable, no live Blender session needed):

1. **Render-brighter gate** (engine-level): a white Lambertian sphere lit by a
   point lamp at two intensities (30 vs 120) renders LINEAR; the higher
   intensity's mean linear RGB must be >= 1.5x the lower (proportional scaling
   is the expected physics). This locks the value the slider edits to a
   measurably brighter render — the property can't be a no-op.
2. **UI-wiring gate** (stub-bpy): the addon's ``convert_lights`` is driven with
   a POINT light datablock at ``energy = 200`` and a recording renderer; it must
   pass ``intensity == 200.0`` to ``add_point_light``, proving the property the
   new control edits reaches the engine end-to-end.
3. **Panel-draws-control smoke** (stub-bpy): ``DATA_PT_custom_raytracer_light.draw``
   runs without exception in ``native`` and ``preset`` spectrum modes and
   references ``light.energy`` (a ``prop(light, "energy")`` call).

The real (headless-Blender) end-to-end legs are in
``tests/test_pkg213_headless_blender.py``; these stub-bpy tests are the CI-safe
backstop that runs even without a Blender install (same monkeypatch pattern as
``test_blender_light_sampler_wiring.py`` / ``test_pkg176_stage2_panel_adoption.py``).
"""

import importlib.util
import sys
import types
from pathlib import Path

import numpy as np

_ADDON = Path(__file__).resolve().parents[1] / "blender_addon"


# ---------------------------------------------------------------------------
# Gate 1 — render-brighter (engine-level, linear)
# ---------------------------------------------------------------------------

def _sphere_mean(module, intensity, spp=128, width=64, height=64, seed=101):
    """Mean linear RGB of a white Lambertian sphere lit by a point lamp at the
    given intensity. LINEAR output (apply_gamma=False) per the gamma-furnace
    memory: a gamma render clamps to [0,1] and cannot see brightness scaling."""
    r = module.Renderer()
    r.set_use_gpu(False)
    r.set_seed(seed)
    r.set_background_color([0.0, 0.0, 0.0])
    r.setup_camera(
        look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=35, aspect_ratio=1.0, aperture=0.0, focus_dist=3.0,
        width=width, height=height,
    )
    mat = r.create_material("lambertian", [1.0, 1.0, 1.0], {})  # white sphere
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.add_point_light(position=[2.0, 2.0, 2.0],
                      emission={'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
                      intensity=intensity, radius=0.0)
    pixels = np.array(r.render(spp, 6, None, False), dtype=np.float32)  # linear
    return pixels.reshape(-1, 3).mean(axis=0)


def test_render_brighter_higher_intensity(astroray_module):
    """A point lamp at intensity 120 is >= 1.5x brighter (linear) than at 30.

    The engine multiplies the emission by ``intensity`` unconditionally, so the
    expected mean-linear-RGB ratio is ~4.0. The 1.5x floor catches any gross
    non-scaling (e.g. the slider value being ignored) while tolerating MC noise.
    """
    low = _sphere_mean(astroray_module, 30.0)
    high = _sphere_mean(astroray_module, 120.0)
    low_mean = float(low.mean())
    high_mean = float(high.mean())
    ratio = high_mean / max(low_mean, 1e-9)
    print(f"[pkg213] mean linear RGB @30 = {low_mean:.5f}, "
          f"@120 = {high_mean:.5f}, ratio = {ratio:.3f}")
    assert high_mean > low_mean, "higher intensity must be brighter"
    assert ratio >= 1.5, (
        f"intensity does not scale brightness: mean(120)/mean(30) = {ratio:.3f} "
        f"(expected ~4.0, floor 1.5)"
    )


# ---------------------------------------------------------------------------
# Gates 2 & 3 — stub-bpy addon load + UI-wiring + panel smoke
# ---------------------------------------------------------------------------

def _load_blender_addon(monkeypatch):
    """Load ``blender_addon/__init__.py`` under a stub bpy (no live Blender),
    returning the loaded module. Same pattern as test_blender_light_sampler_wiring."""
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

    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    monkeypatch.setitem(sys.modules, "bpy.types", bpy_types_module)
    monkeypatch.setitem(sys.modules, "bpy.props", bpy_props_module)
    monkeypatch.setitem(sys.modules, "shader_blending", shader_blending_module)
    monkeypatch.setitem(sys.modules, "mathutils", mathutils_module)
    monkeypatch.setitem(sys.modules, "astroray", astroray_module)

    spec = importlib.util.spec_from_file_location(
        "astroray_addon_pkg213_test", _ADDON / "__init__.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_convert_lights_passes_energy_to_add_point_light(monkeypatch):
    """Gate 2 (UI-wiring): light.data.energy = 200 -> add_point_light(intensity=200).

    Drives the real ``convert_lights`` export path with a POINT light datablock at
    energy 200 and a recording renderer. ``convert_lights`` reads
    ``intensity = float(light.energy)`` (:4632) and forwards it as the 3rd arg of
    ``add_point_light`` — this must be exactly 200.0.
    """
    calls = []

    class MockRenderer:
        def add_point_light(self, position, emission, intensity,
                            radius, ies_path, pass_idx, obj_idx):
            calls.append(("point", float(intensity)))

    addon = _load_blender_addon(monkeypatch)
    engine = addon.CustomRaytracerRenderEngine()

    light_data = types.SimpleNamespace(
        type="POINT",
        energy=200.0,
        color=[1.0, 1.0, 1.0],
        shadow_soft_size=0.0,
    )
    light_obj = types.SimpleNamespace(type="LIGHT", data=light_data, pass_index=0)
    matrix = types.SimpleNamespace(translation=[0.0, 0.0, 0.0])
    inst = types.SimpleNamespace(object=light_obj, matrix_world=matrix)
    depsgraph = types.SimpleNamespace(object_instances=[inst])

    engine.convert_lights(depsgraph, MockRenderer())

    assert calls, "convert_lights converted no lights"
    assert len(calls) == 1, f"expected 1 light, got {calls}"
    kind, intensity = calls[0]
    assert kind == "point"
    assert intensity == 200.0, (
        f"add_point_light received intensity={intensity}, expected 200.0"
    )


class _RecordingLayout:
    """Records every prop()/label() call so a panel draw() can be inspected
    without a real Blender UILayout."""

    def __init__(self):
        self.props = []
        self.labels = []
        self.use_property_split = False
        self.use_property_decorate = False

    def prop(self, obj, attr, *args, **kwargs):
        self.props.append((obj, attr))
        return 0.0

    def label(self, text="", **kwargs):
        self.labels.append(text)


def _draw_panel(addon, spectrum_mode):
    light = types.SimpleNamespace(
        energy=200.0,
        custom_raytracer=types.SimpleNamespace(
            spectrum_mode=spectrum_mode,
            preset_profile="sodium_vapor",
            custom_profile="__none__",
        ),
    )
    layout = _RecordingLayout()
    ctx = types.SimpleNamespace(light=light)
    addon.DATA_PT_custom_raytracer_light.draw(
        types.SimpleNamespace(layout=layout), ctx
    )
    return light, layout


def test_panel_draw_runs_and_references_energy_native(monkeypatch):
    """Gate 3 (native): draw() runs clean and calls prop(light, "energy")."""
    addon = _load_blender_addon(monkeypatch)
    light, layout = _draw_panel(addon, "native")
    prop_attrs = [attr for (_obj, attr) in layout.props]
    assert (light, "energy") in layout.props, (
        f"draw() must reference light.energy; saw props {prop_attrs}"
    )


def test_panel_draw_runs_and_references_energy_preset(monkeypatch):
    """Gate 3 (preset): draw() runs clean (incl. SPD-range label path) and still
    references light.energy — the Power control is visible in ALL spectrum modes."""
    addon = _load_blender_addon(monkeypatch)
    light, layout = _draw_panel(addon, "preset")
    prop_attrs = [attr for (_obj, attr) in layout.props]
    assert (light, "energy") in layout.props, (
        f"draw() must reference light.energy in preset mode; saw props {prop_attrs}"
    )

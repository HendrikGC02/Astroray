"""pkg213 — real headless-Blender legs for the light-intensity slider.

Companion to ``tests/test_pkg213_light_intensity.py`` (the CI-safe stub-bpy and
engine gates). This file runs the two spec'd "headless Blender" acceptance
checks inside a real ``blender --background`` process, skipping cleanly when no
Blender is installed (CI runners have none):

1. **UI-wiring**: create a real POINT light, set ``light.data.energy = 200``,
   run the addon's ``convert_lights`` export path, assert ``add_point_light``
   receives ``intensity == 200.0``.
2. **Panel smoke**: with ``CUSTOM_RAYTRACER`` engine semantics and a light
   selected, ``DATA_PT_custom_raytracer_light.draw()`` runs without exception in
   ``native`` and ``preset`` modes and references ``light.energy``.

Usage:
    pytest tests/test_pkg213_headless_blender.py -v
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPT = r"""
import sys
import types
import importlib.util

# Blender always passes the addon dir as the first arg after '--'.
addon_dir = sys.argv[sys.argv.index("--") + 1]
sys.path.insert(0, addon_dir)

import bpy

# Start from an empty scene: --factory-startup still leaves Cube/Camera/Light,
# which would otherwise add a second point light to convert_lights' output.
bpy.ops.wm.read_factory_settings(use_empty=True)

spec = importlib.util.spec_from_file_location(
    "astroray_addon_pkg213_hb", addon_dir + "/__init__.py")
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)

failures = []

# --- Gate 2 (UI-wiring): light.data.energy = 200 -> add_point_light(intensity=200) ---
light_data = bpy.data.lights.new("Pkg213Point", type="POINT")
light_data.energy = 200.0
light_obj = bpy.data.objects.new("Pkg213PointObj", light_data)
bpy.context.scene.collection.objects.link(light_obj)
bpy.context.view_layer.update()

class RecRenderer:
    def __init__(self):
        self.point_calls = []
    def add_point_light(self, position, emission, intensity,
                        radius, ies_path, pass_idx, obj_idx):
        self.point_calls.append(float(intensity))

rec = RecRenderer()
depsgraph = bpy.context.evaluated_depsgraph_get()
# convert_lights is a plain method that never touches `self` (its only inputs are
# depsgraph + renderer), so call it unbound — real Blender forbids constructing a
# RenderEngine subclass directly (bpy_struct.__new__ TypeError, the pkg95 BUG-15
# pattern).
addon.CustomRaytracerRenderEngine.convert_lights(None, depsgraph, rec)

if not rec.point_calls:
    failures.append("convert_lights converted no point light")
else:
    intensity = rec.point_calls[0]
    print("[pkg213-HB] add_point_light received intensity=%.1f" % intensity)
    if intensity != 200.0:
        failures.append("add_point_light intensity %.1f != 200.0" % intensity)

# --- Gate 3 (panel smoke): draw() runs in native + preset, references light.energy ---
bpy.utils.register_class(addon.CustomRaytracerLightSettings)
bpy.types.Light.custom_raytracer = bpy.props.PointerProperty(
    type=addon.CustomRaytracerLightSettings)

class RecLayout:
    def __init__(self):
        self.props = []
        self.labels = []
        self.use_property_split = False
        self.use_property_decorate = False
    def prop(self, obj, attr, *a, **k):
        self.props.append((obj, attr))
        return 0.0
    def label(self, text="", **k):
        self.labels.append(text)

panel_cls = addon.DATA_PT_custom_raytracer_light
for mode in ("native", "preset"):
    light_data.custom_raytracer.spectrum_mode = mode
    if mode == "preset":
        light_data.custom_raytracer.preset_profile = "sodium_vapor"
    layout = RecLayout()
    ctx = types.SimpleNamespace(light=light_data)
    try:
        panel_cls.draw(types.SimpleNamespace(layout=layout), ctx)
    except Exception as exc:
        failures.append("draw() raised in %s mode: %s: %s"
                        % (mode, type(exc).__name__, exc))
        continue
    prop_attrs = [attr for (_obj, attr) in layout.props]
    refs_energy = "energy" in prop_attrs
    print("[pkg213-HB] %s mode draw ok; energy referenced=%s; props=%s"
          % (mode, refs_energy, prop_attrs))
    if not refs_energy:
        failures.append("draw() in %s mode did not reference light.energy" % mode)

bpy.utils.unregister_class(addon.CustomRaytracerLightSettings)
del bpy.types.Light.custom_raytracer

if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("[pkg213-HB] ALL PASS")
sys.exit(0)
"""


def _find_blender():
    blender_exe = os.environ.get('BLENDER_EXE', '')
    if blender_exe and Path(blender_exe).is_file():
        return Path(blender_exe)
    for candidate in (
        Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"),
    ):
        if candidate.is_file():
            return candidate
    return None


BLENDER_EXE = _find_blender()
SKIP_REASON = "Blender not found (set BLENDER_EXE or install at default path)"


@pytest.mark.skipif(BLENDER_EXE is None, reason=SKIP_REASON)
def test_headless_blender_light_intensity_end_to_end():
    """Real headless-Blender UI-wiring + panel-smoke (see module docstring)."""
    addon_dir = Path(__file__).resolve().parents[1] / "blender_addon"

    tmp = Path(tempfile.mkstemp(suffix=".py", prefix="pkg213_hb_")[1])
    tmp.write_text(_SCRIPT, encoding="utf-8")

    cmd = [
        str(BLENDER_EXE), "--background", "--factory-startup",
        "--python", str(tmp), "--", str(addon_dir),
    ]
    try:
        print(f"\n[test_pkg213_headless_blender] Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                                check=False)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr, file=sys.stderr)
        assert result.returncode == 0, (
            "headless-Blender light-intensity check failed (see output above)"
        )
    finally:
        # Blender may briefly hold the script file open after exit on Windows;
        # unlinking is best-effort (temp dir is scrubbed by the OS regardless).
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass

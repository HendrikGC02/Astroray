"""#762 - real headless-Blender render proving textured Emission Color works
end-to-end (the new C++ TexturedLight material, include/advanced_features.h +
module/blender_module.cpp makeLegacyMaterial + the addon plumbing in
tests/test_issue762_emission_texture.py's unit level).

Builds two materials on identical plane+camera setups and renders each with
the staged CPU addon:
  1. Checker Texture -> Emission (Color) -> Material Output
  2. a constant-colour Emission -> Material Output (same average brightness)

Acceptance bar (from the issue): "Checker -> Emission plane must differ from
a constant-colour Emission plane." Asserts the checker render has real pixel
variance (the pattern) while the constant render is ~uniform, and that the
two renders differ from each other -- not just each individually plausible.

Skips cleanly without Blender or a prior staged CPU addon build.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_DIR = REPO_ROOT / "dist" / "astroray"

_SCRIPT = r"""
import sys
import glob
import importlib.util

addon_dir = sys.argv[sys.argv.index("--") + 1]
out_stem = sys.argv[sys.argv.index("--") + 2]
sys.path.insert(0, addon_dir)

import bpy
import numpy as np

spec = importlib.util.spec_from_file_location(
    "astroray_addon_issue762_hb", addon_dir + "/__init__.py")
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)
addon.register()

failures = []


def _build_scene(checker):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    # Explicit BACKGROUND node forced to black -- do not rely on the #772 fix
    # (a shader-less World falling back to the engine's ~0.15 default sky
    # gradient instead of black); this branch is cut from origin/main before
    # #772 lands, and either way an explicit black background is the correct,
    # version-independent way to isolate the plane's own emission in std().
    world = bpy.data.worlds.new("Issue762World")
    world.use_nodes = True
    world.node_tree.nodes.clear()
    bg = world.node_tree.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    out = world.node_tree.nodes.new("ShaderNodeOutputWorld")
    world.node_tree.links.new(bg.outputs["Background"], out.inputs["Surface"])
    scene.world = world

    cam_data = bpy.data.cameras.new("Cam")
    cam_obj = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam_obj)
    cam_obj.location = (0.0, 0.0, 3.0)
    scene.camera = cam_obj

    # Deliberately huge relative to the default ~40deg-fov camera at distance
    # 3 (frame half-width there is ~1.1) so the plane overfills the frame with
    # a wide margin -- no world-background edge pixels to contaminate the
    # std() comparison below (the actual bug fix is unrelated to framing).
    bpy.ops.mesh.primitive_plane_add(size=20.0, location=(0.0, 0.0, 0.0))
    plane = bpy.context.active_object

    mat = bpy.data.materials.new("Issue762Mat")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emission = nt.nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = 1.0
    nt.links.new(emission.outputs["Emission"], out.inputs["Surface"])

    if checker:
        chk = nt.nodes.new("ShaderNodeTexChecker")
        chk.inputs["Color1"].default_value = (1.0, 1.0, 1.0, 1.0)
        chk.inputs["Color2"].default_value = (0.0, 0.0, 0.0, 1.0)
        chk.inputs["Scale"].default_value = 4.0
        nt.links.new(chk.outputs["Color"], emission.inputs["Color"])
    else:
        emission.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)

    plane.data.materials.append(mat)

    scene.render.engine = "CUSTOM_RAYTRACER"
    scene.render.resolution_x = 48
    scene.render.resolution_y = 48
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    if hasattr(scene, "cycles"):
        scene.cycles.samples = 4
        scene.cycles.use_denoising = False
        scene.cycles.use_adaptive_sampling = False
        scene.cycles.seed = 7
    if hasattr(scene, "custom_raytracer"):
        cr = scene.custom_raytracer
        cr.samples = 4
        if hasattr(cr, "preview_samples"):
            cr.preview_samples = 4
        if hasattr(cr, "device_mode"):
            cr.device_mode = "cpu"
        if hasattr(cr, "use_adaptive_sampling"):
            cr.use_adaptive_sampling = False
    return scene


def _render(stem):
    scene = bpy.context.scene
    for f in glob.glob(stem + "*"):
        try:
            import os
            os.remove(f)
        except OSError:
            pass
    scene.render.filepath = stem
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    bpy.ops.render.render(write_still=True)
    matches = sorted(glob.glob(stem + "*"))
    if not matches:
        raise RuntimeError("no render output for stem %r" % stem)
    img = bpy.data.images.load(matches[0])
    w, h = img.size
    px = np.asarray(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[:, :, :3]
    bpy.data.images.remove(img)
    return px


_build_scene(checker=True)
checker_px = _render(out_stem + "_checker")

_build_scene(checker=False)
constant_px = _render(out_stem + "_constant")

checker_std = float(checker_px.std())
constant_std = float(constant_px.std())
print("[issue762-HB] checker std=%.6f  constant std=%.6f" % (checker_std, constant_std))

# The constant-colour plane must render (near-)uniformly.
if constant_std > 0.02:
    failures.append("constant-colour Emission plane is not uniform (std=%.6f)" % constant_std)

# The checker plane must show real per-texel variance (the pattern), not a
# flat colour -- this is the exact bug: it used to render flat white.
if checker_std < 0.05:
    failures.append("Checker->Emission plane has no visible pattern (std=%.6f) "
                     "-- looks flat, the #762 bug" % checker_std)

# And the two renders must differ from each other.
maxabsdiff = float(np.max(np.abs(checker_px - constant_px)))
if maxabsdiff < 0.1:
    failures.append("checker and constant Emission renders are nearly identical "
                     "(maxabsdiff=%.6f)" % maxabsdiff)

if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("[issue762-HB] ALL PASS")
sys.exit(0)
"""


def _find_blender():
    for candidate in (
        Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe"),
    ):
        if candidate.is_file():
            return candidate
    return None


BLENDER_EXE = _find_blender()


@pytest.mark.skipif(BLENDER_EXE is None, reason="Blender not found at a default install path")
def test_checker_emission_differs_from_constant_emission_headless():
    if not (STAGE_DIR / "build_report.json").exists():
        pytest.skip("no prior staged build (run scripts/build/build_blender_addon.py)")

    tmp_script = Path(tempfile.mkstemp(suffix=".py", prefix="issue762_hb_")[1])
    tmp_script.write_text(_SCRIPT, encoding="utf-8")
    tmp_dir = Path(tempfile.mkdtemp(prefix="issue762_render_"))
    out_stem = tmp_dir / "emission"

    cmd = [
        str(BLENDER_EXE), "--background", "--factory-startup",
        "--python", str(tmp_script), "--", str(STAGE_DIR), str(out_stem),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr, file=sys.stderr)
        assert result.returncode == 0, "headless checker-emission render check failed (see output above)"
    finally:
        import shutil
        try:
            tmp_script.unlink(missing_ok=True)
        except OSError:
            pass
        shutil.rmtree(tmp_dir, ignore_errors=True)

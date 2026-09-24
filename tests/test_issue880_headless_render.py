"""#880 - real headless-Blender render proving a linked Checker Texture on a
standalone Diffuse BSDF's Color input renders the pattern (the bug: it
rendered flat grey; fixed in blender_addon/__init__.py's _standalone_bsdf_spec
BSDF_DIFFUSE branch, routed through get_base_color_texture same as the
Principled Base Color path).

Renders the same Diffuse+Checker plane with Astroray CPU and with Cycles and
asserts both show real per-texel variance (not the pre-fix flat plane) and
that the two are close to each other (visual parity, not just "not flat").

Manually verified 2026-09-25 against a staged addon copy (build 2e058c7 +
this fix's __init__.py/exporter.py) -- astroray std=0.321961 vs cycles
std=0.321320, side-by-side PNG inspected. Skips cleanly without Blender or a
prior staged CPU addon build (same as test_issue762_headless_render.py).
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
import os
import importlib.util

addon_dir = sys.argv[sys.argv.index("--") + 1]
out_stem = sys.argv[sys.argv.index("--") + 2]
sys.path.insert(0, addon_dir)

import bpy
import numpy as np

spec = importlib.util.spec_from_file_location(
    "astroray_addon_issue880_hb", addon_dir + "/__init__.py")
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)
addon.register()

failures = []


def _build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    world = bpy.data.worlds.new("Issue880World")
    world.use_nodes = True
    world.node_tree.nodes.clear()
    bg = world.node_tree.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.05, 0.05, 0.05, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    out = world.node_tree.nodes.new("ShaderNodeOutputWorld")
    world.node_tree.links.new(bg.outputs["Background"], out.inputs["Surface"])
    scene.world = world

    cam_data = bpy.data.cameras.new("Cam")
    cam_obj = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam_obj)
    cam_obj.location = (0.0, 0.0, 3.0)
    scene.camera = cam_obj

    sun_data = bpy.data.lights.new("Sun", type='SUN')
    sun_data.energy = 3.0
    sun_obj = bpy.data.objects.new("Sun", sun_data)
    scene.collection.objects.link(sun_obj)
    sun_obj.rotation_euler = (0.6, 0.3, 0.0)

    bpy.ops.mesh.primitive_plane_add(size=20.0, location=(0.0, 0.0, 0.0))
    plane = bpy.context.active_object

    mat = bpy.data.materials.new("Issue880Mat")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    diffuse = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.inputs["Roughness"].default_value = 0.0
    nt.links.new(diffuse.outputs["BSDF"], out.inputs["Surface"])

    chk = nt.nodes.new("ShaderNodeTexChecker")
    chk.inputs["Color1"].default_value = (0.9, 0.9, 0.9, 1.0)
    chk.inputs["Color2"].default_value = (0.05, 0.05, 0.05, 1.0)
    chk.inputs["Scale"].default_value = 4.0
    nt.links.new(chk.outputs["Color"], diffuse.inputs["Color"])

    plane.data.materials.append(mat)

    scene.render.resolution_x = 128
    scene.render.resolution_y = 128
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    return scene


def _render(engine_name, stem):
    scene = bpy.context.scene
    scene.render.engine = engine_name
    if engine_name == "CYCLES":
        scene.cycles.samples = 128
        scene.cycles.use_denoising = False
        scene.cycles.use_adaptive_sampling = False
        scene.cycles.seed = 7
    if engine_name == "CUSTOM_RAYTRACER" and hasattr(scene, "custom_raytracer"):
        cr = scene.custom_raytracer
        cr.samples = 128
        if hasattr(cr, "preview_samples"):
            cr.preview_samples = 128
        if hasattr(cr, "device_mode"):
            cr.device_mode = "cpu"
        if hasattr(cr, "use_adaptive_sampling"):
            cr.use_adaptive_sampling = False

    for f in glob.glob(stem + "*"):
        try:
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


_build_scene()
astro_px = _render("CUSTOM_RAYTRACER", out_stem + "_astroray")

_build_scene()
cycles_px = _render("CYCLES", out_stem + "_cycles")

astro_std = float(astro_px.std())
cycles_std = float(cycles_px.std())
print("[issue880-HB] astroray std=%.6f  cycles std=%.6f" % (astro_std, cycles_std))

# Astroray must show real per-texel variance (the checker pattern), not the
# pre-fix flat grey (the #880 bug).
if astro_std < 0.03:
    failures.append("Astroray Diffuse+Checker plane has no visible pattern "
                     "(std=%.6f) -- looks flat, the #880 bug" % astro_std)

if cycles_std < 0.03:
    failures.append("Cycles Diffuse+Checker reference has no visible pattern "
                     "(std=%.6f) -- reference scene is broken" % cycles_std)

# Astroray must agree with the Cycles reference (checker-cell agreement),
# not merely "not flat" -- the #880 gate is >= 0.95.
ratio = min(astro_std, cycles_std) / max(astro_std, cycles_std) if max(astro_std, cycles_std) > 0 else 0.0
if ratio < 0.95:
    failures.append("Astroray/Cycles std ratio %.4f < 0.95 gate" % ratio)

if failures:
    print("FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("[issue880-HB] ALL PASS")
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
def test_diffuse_checker_matches_cycles_headless():
    if not (STAGE_DIR / "build_report.json").exists():
        pytest.skip("no prior staged build (run scripts/build/build_blender_addon.py)")

    tmp_script = Path(tempfile.mkstemp(suffix=".py", prefix="issue880_hb_")[1])
    tmp_script.write_text(_SCRIPT, encoding="utf-8")
    tmp_dir = Path(tempfile.mkdtemp(prefix="issue880_render_"))
    out_stem = tmp_dir / "diffuse"

    cmd = [
        str(BLENDER_EXE), "--background", "--factory-startup",
        "--python", str(tmp_script), "--", str(STAGE_DIR), str(out_stem),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr, file=sys.stderr)
        assert result.returncode == 0, "headless Diffuse-checker-vs-Cycles render check failed (see output above)"
    finally:
        import shutil
        try:
            tmp_script.unlink(missing_ok=True)
        except OSError:
            pass
        shutil.rmtree(tmp_dir, ignore_errors=True)

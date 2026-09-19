"""pkg271 — Blender headless: an imported Volume object renders F12 on CPU and GPU.

Real ``blender --background`` with the STAGED addon (dist/astroray, the same
exec_module + register() pattern as tests/test_issue762_headless_render.py):
  1. write a small synthetic smoke+fire ``.vdb`` (density + temperature grids)
     with Blender's bundled ``openvdb``;
  2. a Volume object referencing it, Principled Volume material (density,
     blackbody from the temperature attribute), black World, a sun lamp;
  3. F12 with device_mode 'cpu' and then 'gpu' (addon raises if CUDA is absent);
  4. non-vacuity per device: finite, not black, spatial variation from the
     density grid, and a warm blackbody core (R > B) -- a black frame, a flat
     frame or a fire without blackbody fails. CPU vs GPU mean within 10 %.

Skips without Blender or a staged build (``scripts/build/build_blender_addon.py``).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
# ASTRORAY_ADDON_STAGE_DIR: point at another staged addon (a lane verifying a
# fresh build_cuda .pyd before the addon is restaged).
STAGE_DIR = Path(os.environ.get("ASTRORAY_ADDON_STAGE_DIR", str(REPO_ROOT / "dist" / "astroray")))

_SCRIPT = r'''
import sys, glob, os, json, importlib.util
addon_dir = sys.argv[sys.argv.index("--") + 1]
out_dir = sys.argv[sys.argv.index("--") + 2]
sys.path.insert(0, addon_dir)
import bpy, openvdb
import numpy as np

spec = importlib.util.spec_from_file_location("astroray_addon_pkg271_hb", addon_dir + "/__init__.py")
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)
addon.register()

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# --- synthetic smoke + fire: density ball with lumps, hot core ---------------
N = 32
z, y, x = np.mgrid[0:N, 0:N, 0:N].astype(np.float32)
c = (N - 1) / 2.0
r2 = ((x - c) ** 2 + (y - c) ** 2 + (z - c) ** 2) / (c * c)
lumps = 0.6 + 0.4 * np.sin(x * 0.7) * np.cos(y * 0.5) * np.sin(z * 0.6)
dens = (np.clip(1.0 - r2, 0.0, 1.0) * lumps).astype(np.float32)
temp = (np.clip(1.0 - 2.5 * r2, 0.0, 1.0) ** 2).astype(np.float32)
vdb_path = os.path.join(out_dir, "smoke_fire.vdb")
grids = []
for name, arr in (("density", dens), ("temperature", temp)):
    g = openvdb.FloatGrid()
    g.copyFromArray(np.ascontiguousarray(arr.transpose(2, 1, 0)))  # [x, y, z]
    g.name = name
    g.transform = openvdb.createLinearTransform(voxelSize=2.0 / N)
    grids.append(g)
openvdb.write(vdb_path, grids=grids)

vol = bpy.data.volumes.new("SmokeFire")
vol.filepath = vdb_path
obj = bpy.data.objects.new("SmokeFire", vol)
obj.location = (-1.0, -1.0, -1.0)   # grid index 0..N at voxel 2/N -> centred at origin
scene.collection.objects.link(obj)

mat = bpy.data.materials.new("SmokeFireMat")
mat.use_nodes = True
nt = mat.node_tree
nt.nodes.clear()
out = nt.nodes.new("ShaderNodeOutputMaterial")
pv = nt.nodes.new("ShaderNodeVolumePrincipled")
pv.inputs["Density"].default_value = 4.0
pv.inputs["Color"].default_value = (0.7, 0.7, 0.7, 1.0)
pv.inputs["Blackbody Intensity"].default_value = 1.0
pv.inputs["Temperature"].default_value = 2500.0
nt.links.new(pv.outputs["Volume"], out.inputs["Volume"])
vol.materials.append(mat)

world = bpy.data.worlds.new("Black")
world.use_nodes = True
world.node_tree.nodes.clear()
bg = world.node_tree.nodes.new("ShaderNodeBackground")
bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
wout = world.node_tree.nodes.new("ShaderNodeOutputWorld")
world.node_tree.links.new(bg.outputs["Background"], wout.inputs["Surface"])
scene.world = world

sun = bpy.data.lights.new("Sun", "SUN")
sun.energy = 1.0
sun_obj = bpy.data.objects.new("Sun", sun)
sun_obj.rotation_euler = (0.6, 0.3, 0.8)
scene.collection.objects.link(sun_obj)

cam = bpy.data.cameras.new("Cam")
cam_obj = bpy.data.objects.new("Cam", cam)
cam_obj.location = (0.0, -5.0, 0.0)
cam_obj.rotation_euler = (1.5708, 0.0, 0.0)
scene.collection.objects.link(cam_obj)
scene.camera = cam_obj

scene.render.engine = "CUSTOM_RAYTRACER"
scene.render.resolution_x = 48
scene.render.resolution_y = 48
scene.render.resolution_percentage = 100
scene.view_settings.view_transform = "Standard"
if hasattr(scene, "cycles"):
    scene.cycles.samples = 256
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.cycles.seed = 11
cr = scene.custom_raytracer
cr.samples = 256
if hasattr(cr, "use_adaptive_sampling"):
    cr.use_adaptive_sampling = False

results = {}
for device in ("cpu", "gpu"):
    cr.device_mode = device
    stem = os.path.join(out_dir, "vol_" + device)
    scene.render.filepath = stem
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    bpy.ops.render.render(write_still=True)
    files = sorted(glob.glob(stem + "*"))
    if not files:
        results[device] = {"error": "no render output"}
        continue
    img = bpy.data.images.load(files[0])
    w, h = img.size
    px = np.asarray(img.pixels[:], dtype=np.float64).reshape(h, w, 4)[:, :, :3]
    bpy.data.images.remove(img)
    core = px[h // 2 - 4:h // 2 + 4, w // 2 - 4:w // 2 + 4].reshape(-1, 3).mean(axis=0)
    results[device] = {
        "finite": bool(np.isfinite(px).all()),
        "mean": px.reshape(-1, 3).mean(axis=0).tolist(),
        "max": float(px.max()),
        "std": float(px.mean(axis=2).std()),
        "core": core.tolist(),
    }
print("PKG271_HB_RESULTS:" + json.dumps(results))
'''


def _find_blender():
    for candidate in (
        Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"),
        Path(r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"),
    ):
        if candidate.is_file():
            return candidate
    return None


BLENDER_EXE = _find_blender()


@pytest.mark.serial
@pytest.mark.skipif(BLENDER_EXE is None, reason="Blender not found at a default install path")
def test_volume_object_renders_f12_cpu_and_gpu_headless():
    if not (STAGE_DIR / "build_report.json").exists():
        pytest.skip("no staged addon build (run scripts/build/build_blender_addon.py)")
    tmp_dir = Path(tempfile.mkdtemp(prefix="pkg271_hb_"))
    script = tmp_dir / "pkg271_hb.py"
    script.write_text(_SCRIPT, encoding="utf-8")
    cmd = [str(BLENDER_EXE), "--background", "--factory-startup", "--python", str(script),
           "--", str(STAGE_DIR), str(tmp_dir)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
        out = proc.stdout + proc.stderr
        print(proc.stdout[-4000:])
        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("PKG271_HB_RESULTS:")), None)
        assert line is not None, "headless script produced no results:\n" + out[-4000:]
        assert "volume export failed" not in out, out[-4000:]
        res = json.loads(line.split(":", 1)[1])
        for device in ("cpu", "gpu"):
            r = res[device]
            assert "error" not in r, (device, r)
            assert r["finite"], (device, r)
            assert r["max"] > 0.05, f"{device}: black frame {r}"
            assert r["std"] > 0.01, f"{device}: no spatial variation {r}"
            core = r["core"]
            assert core[0] > 1.5 * core[2], f"{device}: core not a warm blackbody glow {core}"
        mc = sum(res["cpu"]["mean"])
        mg = sum(res["gpu"]["mean"])
        assert abs(mg / mc - 1.0) < 0.10, (res["cpu"]["mean"], res["gpu"]["mean"])
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

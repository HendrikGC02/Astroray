"""pkg217 Path A -- headless Blender repro/verification script.

Run inside Blender (background mode):
    "<blender.exe>" --background --factory-startup --python scripts/pkg217_headless_repro.py

Builds the owner's exact repro shape (glass sphere caster + delta sun light +
diffuse floor), renders through the real Astroray Blender addon/engine on
GPU, and reports whether the floor under the sphere shows a caustic (not a
black shadow). Confirms the Path A addon fix
(blender_addon/__init__.py::convert_scene calling
renderer.set_use_photon_caustics(True) when a caster is present) reaches the
GPU end-to-end.
"""
import importlib.util
import math
import os
import sys

import bpy

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# dist/astroray/ is the STAGED addon dir from build_blender_addon.py --backend
# cuda: it has both __init__.py (copied from blender_addon/, so it carries our
# Path A fix) AND the freshly-built astroray*.pyd + CUDA DLLs side by side.
# Loading blender_addon/__init__.py directly (source tree) would find no
# astroray module at all -- Blender's bundled Python has no astroray install.
# The staged dir is a FLAT layout (not a "blender_addon" package dir), so we
# load __init__.py by file path -- same technique as
# scripts/verify_pkg175_smoke_blender.py's _bootstrap().
ADDON_DIR = os.path.join(REPO_ROOT, "dist", "astroray")
OUT_PNG = os.path.join(REPO_ROOT, "test_results", "pkg217_headless_repro.png")

if hasattr(os, "add_dll_directory"):
    for d in (ADDON_DIR, os.path.join(ADDON_DIR, "oidn")):
        if os.path.isdir(d):
            os.add_dll_directory(d)
sys.path.insert(0, ADDON_DIR)

_spec = importlib.util.spec_from_file_location(
    "blender_addon", os.path.join(ADDON_DIR, "__init__.py"))
blender_addon = importlib.util.module_from_spec(_spec)
sys.modules["blender_addon"] = blender_addon
_spec.loader.exec_module(blender_addon)
blender_addon.register()

import astroray  # noqa: E402
print(f"[pkg217-repro] astroray.__file__ = {astroray.__file__}")
print(f"[pkg217-repro] astroray.__features__ = {astroray.__features__}")

# Clear the default scene.
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = "CUSTOM_RAYTRACER"

# --- Floor (diffuse) ---
bpy.ops.mesh.primitive_plane_add(size=8.0, location=(0, 0, -1.1))
floor = bpy.context.active_object
floor.name = "Floor"
floor_mat = bpy.data.materials.new("FloorDiffuse")
floor_mat.use_nodes = True
bsdf = floor_mat.node_tree.nodes.get("Principled BSDF")
if bsdf is not None:
    bsdf.inputs["Base Color"].default_value = (0.85, 0.85, 0.85, 1.0)
    bsdf.inputs["Roughness"].default_value = 1.0
floor.data.materials.append(floor_mat)

# --- Glass sphere caster ---
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.6, location=(0, 0, 0), segments=48, ring_count=24)
sphere = bpy.context.active_object
sphere.name = "GlassSphere"
sphere.astroray_object.is_caustic_caster = True
glass_mat = bpy.data.materials.new("Glass")
glass_mat.use_nodes = True
bsdf_g = glass_mat.node_tree.nodes.get("Principled BSDF")
if bsdf_g is not None:
    bsdf_g.inputs["Transmission Weight"].default_value = 1.0
    bsdf_g.inputs["Roughness"].default_value = 0.0
    bsdf_g.inputs["IOR"].default_value = 1.5
sphere.data.materials.append(glass_mat)

# --- Delta sun light (collimated) ---
sun_data = bpy.data.lights.new("Sun", type="SUN")
sun_data.energy = 4.0
sun_data.angle = 0.01  # near-delta
sun_obj = bpy.data.objects.new("Sun", sun_data)
scene.collection.objects.link(sun_obj)
sun_obj.rotation_euler = (math.radians(20), math.radians(10), 0)

# --- Camera ---
cam_data = bpy.data.cameras.new("Cam")
cam_obj = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam_obj)
scene.camera = cam_obj
cam_obj.location = (2.5, -3.5, 1.6)
import mathutils  # noqa: E402
direction = mathutils.Vector((0, 0, -0.3)) - cam_obj.location
cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

# --- Render settings ---
scene.render.resolution_x = 320
scene.render.resolution_y = 240
scene.render.filepath = OUT_PNG
crt = scene.custom_raytracer
crt.samples = 64
crt.max_bounces = 8
crt.device_mode = "gpu"

print(f"[pkg217-repro] is_caustic_caster on sphere = {sphere.astroray_object.is_caustic_caster}")
print(f"[pkg217-repro] engine = {scene.render.engine}, device_mode = {crt.device_mode}")

os.makedirs(os.path.dirname(OUT_PNG), exist_ok=True)
bpy.ops.render.render(write_still=True)

# --- Analyze the rendered PNG for a caustic (not a black shadow) ---
img = bpy.data.images.load(OUT_PNG)
w, h = img.size
pixels = list(img.pixels)  # RGBA flattened, bottom-to-top rows
import numpy as np  # noqa: E402
arr = np.array(pixels, dtype=np.float32).reshape(h, w, 4)
lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]

# Floor occupies the lower half of the frame in this camera framing.
floor_region = lum[: h // 2, :]
peak = float(floor_region.max())
mean = float(floor_region.mean())
print(f"[pkg217-repro] floor-region peak luminance = {peak:.4f}, mean = {mean:.4f}")
print(f"[pkg217-repro] PNG written to {OUT_PNG}")
print("[pkg217-repro] RESULT:", "CAUSTIC (not black)" if peak >= 0.20 else "BLACK SHADOW (bug still present)")

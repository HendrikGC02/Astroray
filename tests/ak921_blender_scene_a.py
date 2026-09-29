"""Blender-side helper for test_ak921_addon_area_lamp_parity.py (runs INSIDE Blender).

pkg288 scene (a), z-up twin: Diffuse-BSDF 0.8 floor, two coloured square area lamps
(20 W / 1.2 m at z=2, 60 W / 3.0 m at z=3.5, both facing down), black world, 60 deg
vertical FOV camera at (0,-6,1) looking at the origin. Renders through the Astroray
addon (CPU) and prints ``AK921_MEAN r g b``.
"""
import math
import os
import sys

import bpy

REPO = os.environ["AK921_REPO"]
os.add_dll_directory(os.environ["ASTRORAY_PYD_DIR"])
for d in os.environ.get("AK921_DLL_DIRS", "").split(os.pathsep):
    if d and os.path.isdir(d):
        os.add_dll_directory(d)
sys.path.insert(0, os.environ["ASTRORAY_PYD_DIR"])
sys.path.insert(0, REPO)
import astroray  # noqa: E402,F401
import blender_addon  # noqa: E402

try:
    blender_addon.register()
except Exception as exc:  # noqa: BLE001
    if "already registered" not in str(exc):
        raise

spp, res = int(sys.argv[-2]), int(sys.argv[-1])
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
world = bpy.data.worlds.new("W")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0, 0, 0, 1)
sc.world = world

mat = bpy.data.materials.new("floor")
mat.use_nodes = True
nt = mat.node_tree
nt.nodes.remove(next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"))
diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
diff.inputs["Color"].default_value = (0.8, 0.8, 0.8, 1)
nt.links.new(diff.outputs[0], next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL").inputs[0])
bpy.ops.mesh.primitive_plane_add(size=12, location=(0, 0, 0))
bpy.context.object.data.materials.append(mat)


def lamp(z, size, col, watts):
    data = bpy.data.lights.new("a%s" % z, "AREA")
    data.shape, data.size, data.color, data.energy = "SQUARE", size, col, watts
    obj = bpy.data.objects.new("a%s" % z, data)
    obj.location = (0, 0, z)
    sc.collection.objects.link(obj)


lamp(2.0, 1.2, (1.0, 0.2, 0.2), 20.0)
lamp(3.5, 3.0, (0.2, 0.4, 1.0), 60.0)
cam_data = bpy.data.cameras.new("c")
cam_data.sensor_fit = "VERTICAL"  # set BEFORE angle (angle is derived from the fit)
cam_data.angle = math.radians(60)
cam = bpy.data.objects.new("c", cam_data)
cam.location = (0, -6, 1)
sc.collection.objects.link(cam)
target = bpy.data.objects.new("t", None)
sc.collection.objects.link(target)
track = cam.constraints.new("TRACK_TO")
track.target, track.track_axis, track.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
sc.camera = cam

sc.render.resolution_x = sc.render.resolution_y = res
sc.render.resolution_percentage = 100
sc.view_settings.view_transform = "Standard"
sc.render.image_settings.file_format = "OPEN_EXR"
sc.render.image_settings.color_depth = "32"
sc.render.engine = "CUSTOM_RAYTRACER"
sc.cycles.samples = spp
sc.cycles.use_denoising = False
sc.cycles.seed = 3
cr = sc.custom_raytracer
cr.samples = spp
cr.device_mode = "cpu"
cr.use_adaptive_sampling = False
sc.render.filepath = os.path.join(os.environ["AK921_OUT"], "scene_a")
bpy.ops.render.render(write_still=True)
img = bpy.data.images.load(sc.render.filepath + ".exr")
px = list(img.pixels[:])
n = len(px) // 4
means = [sum(px[c::4]) / n for c in range(3)]
print("AK921_MEAN %.8f %.8f %.8f" % tuple(means), flush=True)

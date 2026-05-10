"""Author the pkg76 synthetic test fixture.

Run **once** with a real Blender:

    blender --background --python tests/fixtures/build_synthetic_min.py

The output is committed at tests/fixtures/synthetic_min.blend (≪10 KB) and
exercised by `tests/test_blend_import_format.py` and
`tests/test_blend_import_roundtrip.py`. CI does not run this script — bpy is
not a CI dependency.

Determinism: known scalar values are baked into the script so unit tests can
hardcode the expected fields (vert/face count, focal length, base colour, ...).
"""

import bpy
import sys
from pathlib import Path


# --- Scene wipe -------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)

# --- Camera -----------------------------------------------------------------
cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 42.0
cam_data.sensor_width = 36.0
cam_data.sensor_height = 24.0
cam_data.clip_start = 0.05
cam_data.clip_end = 250.0
cam_obj = bpy.data.objects.new("Cam", cam_data)
cam_obj.location = (4.0, -4.0, 3.0)
cam_obj.rotation_euler = (1.1, 0.0, 0.78)

# --- Light ------------------------------------------------------------------
sun_data = bpy.data.lights.new("Sun", type="SUN")
sun_data.color = (1.0, 0.9, 0.8)
sun_data.energy = 3.5
sun_obj = bpy.data.objects.new("Sun", sun_data)
sun_obj.location = (2.0, 2.0, 5.0)

# --- Material ---------------------------------------------------------------
mat = bpy.data.materials.new("Cube_Mat")
mat.use_nodes = True
ntree = mat.node_tree
ntree.nodes.clear()
out = ntree.nodes.new("ShaderNodeOutputMaterial")
bsdf = ntree.nodes.new("ShaderNodeBsdfPrincipled")
bsdf.inputs["Base Color"].default_value = (0.42, 0.18, 0.71, 1.0)
ntree.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

# --- Cube mesh --------------------------------------------------------------
verts = [
    (-1, -1, -1), ( 1, -1, -1), ( 1,  1, -1), (-1,  1, -1),
    (-1, -1,  1), ( 1, -1,  1), ( 1,  1,  1), (-1,  1,  1),
]
faces = [
    (0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
    (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
]
mesh = bpy.data.meshes.new("CubeMesh")
mesh.from_pydata(verts, [], faces)
mesh.update()
mesh.materials.append(mat)
cube_obj = bpy.data.objects.new("Cube", mesh)
cube_obj.location = (0.0, 0.0, 0.0)

# --- Collection wiring ------------------------------------------------------
scene = bpy.context.scene
collection = scene.collection
for obj in (cam_obj, sun_obj, cube_obj):
    collection.objects.link(obj)
scene.camera = cam_obj

# --- World ------------------------------------------------------------------
world = bpy.data.worlds.new("World") if scene.world is None else scene.world
scene.world = world
world.use_nodes = True
wtree = world.node_tree
wtree.nodes.clear()
wout = wtree.nodes.new("ShaderNodeOutputWorld")
bg = wtree.nodes.new("ShaderNodeBackground")
bg.inputs["Color"].default_value = (0.05, 0.07, 0.11, 1.0)
bg.inputs["Strength"].default_value = 1.25
wtree.links.new(bg.outputs["Background"], wout.inputs["Surface"])

# --- Save -------------------------------------------------------------------
out_path = Path(__file__).parent / "synthetic_min.blend"
# compress=False keeps the file uncompressed so the format-level test can run
# without zstandard available.
bpy.ops.wm.save_as_mainfile(filepath=str(out_path), compress=False, copy=True)
print(f"Wrote {out_path} ({out_path.stat().st_size} bytes)")

"""pkg294 Phase 0 — one-lamp / three-lamp scatter-cube scenes (run inside Blender).

  blender --background --factory-startup --python build_scenes.py -- <out_dir>

Writes cube1.blend, cube3.blend and rois.json (top-down pixel boxes). Scatter
cube = the geometry_zoo cabinet's Volume Scatter cube (colour 0.95/0.96/1.0,
density 4, g 0.55, 0.55 m), backlit by a 900 W rectangle; cube3 adds unequal
key (650 W) and fill (220 W) rectangles. Black world, no surfaces (a diffuse
floor under a tilted rectangle renders a spurious bright footprint in Astroray,
pre-existing, reported separately), clamp off, lamps invisible to camera. One-off verification script; delete when pkg294 closes.
"""
import json
import math
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

RES = 256


def _rect_lamp(name, energy, size, loc, target):
    data = bpy.data.lights.new(name, type="AREA")
    data.energy = energy
    data.shape = "RECTANGLE"
    data.size, data.size_y = size, size * 0.75
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = loc
    d = Vector(target) - Vector(loc)
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    obj.visible_camera = False
    return obj


def _mat(name, builder):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    builder(nt, out)
    return m


def build(three_lamps):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs[0].default_value = (0, 0, 0, 1)
    bg.inputs[1].default_value = 0.0
    scene.world = world

    bpy.ops.mesh.primitive_cube_add(size=0.55, location=(0, 0, 0.45))
    cube = bpy.context.active_object

    def scatter(nt, out):
        v = nt.nodes.new("ShaderNodeVolumeScatter")
        v.inputs["Color"].default_value = (0.95, 0.96, 1.0, 1.0)
        v.inputs["Density"].default_value = 4.0
        v.inputs["Anisotropy"].default_value = 0.55
        nt.links.new(v.outputs[0], out.inputs["Volume"])
    cube.data.materials.append(_mat("Scatter", scatter))

    _rect_lamp("Backlight", 900.0, 1.5, (0.0, 1.2, 0.9), (0.0, 0.0, 0.45))
    if three_lamps:
        _rect_lamp("Key", 650.0, 1.0, (-2.0, -1.5, 2.5), (0.0, 0.0, 0.45))
        _rect_lamp("Fill", 220.0, 0.8, (2.0, -1.0, 1.2), (0.0, 0.0, 0.45))

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = 50.0
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, -2.6, 0.75)
    cam.rotation_euler = (Vector((0, 0, 0.45)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    scene.render.engine = "CYCLES"
    scene.render.resolution_x = scene.render.resolution_y = RES
    scene.render.resolution_percentage = 100
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 8
    c = scene.cycles
    c.device = "CPU"
    c.samples = 64
    c.use_denoising = False
    c.use_adaptive_sampling = False
    c.sample_clamp_direct = 0.0
    c.sample_clamp_indirect = 0.0
    c.use_animated_seed = False
    c.seed = 1
    scene.view_settings.view_transform = "Standard"

    # Cube ROI: projected bbox of the cube corners, shrunk 20 % (top-down px).
    bpy.context.view_layer.update()
    pts = [world_to_camera_view(scene, cam, cube.matrix_world @ Vector(v)) for v in cube.bound_box]
    xs = [p.x * RES for p in pts]
    ys = [(1.0 - p.y) * RES for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sx, sy = 0.2 * (x1 - x0), 0.2 * (y1 - y0)
    roi_cube = [int(math.ceil(y0 + sy)), int(math.floor(y1 - sy)),
                int(math.ceil(x0 + sx)), int(math.floor(x1 - sx))]
    return {"cube": roi_cube}


def main():
    out = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    rois = {}
    for name, three in (("cube1", False), ("cube3", True)):
        rois[name] = build(three)
        bpy.ops.wm.save_as_mainfile(filepath=str(out / f"{name}.blend"))
    (out / "rois.json").write_text(json.dumps(rois, indent=1))
    print("PKG294_BUILD", json.dumps(rois))


main()

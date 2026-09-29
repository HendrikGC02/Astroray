"""pkg298 — Cycles leg of the Cornell-pair perf harness (runs inside Blender).

Invoked by benchmarks/wavefront_baseline.py --cornell-pair --cycles as
    blender -b --factory-startup --python cycles_leg.py -- '<json cfg>'
Builds one mesh from the shared <kind>_pos.npy / <kind>_mid.npy (the triangles
Astroray renders), sets diffuse + emission materials, renders `calls` times on
the requested Cycles device (OPTIX / CUDA) and prints one line
    PKG298_JSON {"calls": [{"wall_s": ...}, ...], ...}
Settings mirror the Astroray leg: square res, samples, max bounces = depth,
no adaptive sampling, no denoiser, black world, camera (0,0,6.8) vfov 39.6.
"""
import json
import math
import sys
import time

import bpy
import numpy as np


def _cfg():
    argv = sys.argv
    return json.loads(argv[argv.index("--") + 1])


def _enable_device(kind):
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = kind
    prefs.get_devices()
    used = []
    for d in prefs.devices:
        d.use = d.type == kind
        if d.use:
            used.append(d.name)
    if not used:
        raise RuntimeError(f"no Cycles {kind} device")
    return used


def _material(name, color, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    if strength > 0:
        sh = nt.nodes.new("ShaderNodeEmission")
        sh.inputs["Color"].default_value = (*color, 1.0)
        sh.inputs["Strength"].default_value = strength
    else:
        sh = nt.nodes.new("ShaderNodeBsdfDiffuse")
        sh.inputs["Color"].default_value = (*color, 1.0)
    nt.links.new(sh.outputs[0], out.inputs["Surface"])
    return m


def main():
    cfg = _cfg()
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)

    pos = np.load(cfg["pos"]).astype(np.float32).reshape(-1, 3)
    mid = np.load(cfg["mid"]).astype(np.int32)
    nt = len(mid)
    me = bpy.data.meshes.new("pair")
    me.vertices.add(len(pos))
    me.vertices.foreach_set("co", pos.ravel())
    me.loops.add(nt * 3)
    me.loops.foreach_set("vertex_index", np.arange(nt * 3, dtype=np.int32))
    me.polygons.add(nt)
    me.polygons.foreach_set("loop_start", np.arange(0, nt * 3, 3, dtype=np.int32))
    me.polygons.foreach_set("material_index", mid)
    me.update(calc_edges=False)
    for name, col, strength in cfg["materials"]:
        me.materials.append(_material(name, col, strength))
    obj = bpy.data.objects.new("pair", me)
    scene = bpy.context.scene
    scene.collection.objects.link(obj)

    cam_data = bpy.data.cameras.new("cam")
    cam_data.sensor_fit = "VERTICAL"
    cam_data.angle_y = math.radians(cfg["camera"]["vfov"])
    cam = bpy.data.objects.new("cam", cam_data)
    cam.location = cfg["camera"]["look_from"]   # looks down -Z at the origin
    scene.collection.objects.link(cam)
    scene.camera = cam

    world = bpy.data.worlds.new("black")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0, 0, 0, 1)
    scene.world = world

    scene.render.engine = "CYCLES"
    scene.render.resolution_x = scene.render.resolution_y = cfg["res"]
    scene.render.resolution_percentage = 100
    cy = scene.cycles
    devices = _enable_device(cfg["device"])
    cy.device = "GPU"
    cy.samples = cfg["spp"]
    cy.use_adaptive_sampling = False
    cy.use_denoising = False
    cy.max_bounces = cfg["depth"]
    for k in ("diffuse_bounces", "glossy_bounces", "transmission_bounces",
              "volume_bounces", "transparent_max_bounces"):
        setattr(cy, k, cfg["depth"])
    scene.render.filepath = "//pkg298_cycles_unused.png"

    calls = []
    for _ in range(cfg["calls"]):
        t0 = time.perf_counter()
        bpy.ops.render.render(write_still=False)
        calls.append({"wall_s": time.perf_counter() - t0})
    print("PKG298_JSON " + json.dumps({
        "calls": calls, "triangles": int(nt), "devices": devices,
        "blender": bpy.app.version_string,
        "persistent_data": scene.render.use_persistent_data}), flush=True)


main()

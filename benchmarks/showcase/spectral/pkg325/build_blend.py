"""pkg325: build the acceptance scene as a .blend (runs INSIDE Blender 5.2).

Same triangles as the engine-only tests: ``scene_geometry.scene_meshes()``.

    blender -b --factory-startup --python benchmarks/showcase/spectral/pkg325/build_blend.py -- --out <file.blend>
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy  # type: ignore
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO / "benchmarks" / "blender_parity"))
sys.path.insert(0, str(HERE))
import scene_library as sl  # noqa: E402
import scene_geometry as G  # noqa: E402

SEED = 325
SMOOTH_ANGLE_DEG = 40.0


def _mesh_object(m: G.Mesh):
    flat = m.tris.reshape(-1, 3)
    verts, inv = np.unique(np.round(flat, 9), axis=0, return_inverse=True)
    faces = inv.reshape(-1, 3).tolist()
    me = bpy.data.meshes.new(m.name)
    me.from_pydata(verts.tolist(), [], faces)
    me.update()
    if m.smooth:
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(me)
        for e in bm.edges:
            if len(e.link_faces) == 2 and e.calc_face_angle() > math.radians(SMOOTH_ANGLE_DEG):
                e.smooth = False
        for f in bm.faces:
            f.smooth = True
        bm.to_mesh(me)
        bm.free()
    obj = bpy.data.objects.new(m.name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _glass(name="Glass"):
    mat, nt, out = sl._bare_material(bpy, name)
    g = nt.nodes.new("ShaderNodeBsdfGlass")
    sl._sock(g.inputs, "Color").default_value = (1.0, 1.0, 1.0, 1.0)
    sl._sock(g.inputs, "Roughness").default_value = 0.0
    sl._sock(g.inputs, "IOR").default_value = 1.5
    nt.links.new(g.outputs[0], sl._sock(out.inputs, "Surface"))
    return mat


def _diffuse(name, color):
    mat, nt, out = sl._bare_material(bpy, name)
    d = nt.nodes.new("ShaderNodeBsdfDiffuse")
    sl._sock(d.inputs, "Color").default_value = (*color, 1.0)
    nt.links.new(d.outputs[0], sl._sock(out.inputs, "Surface"))
    return mat


def build(res=(640, 480), spp=128, max_bounces=12):
    for coll in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                 bpy.data.cameras, bpy.data.worlds):
        for item in list(coll):
            coll.remove(item)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Standard"
    c = scene.cycles
    c.samples, c.seed, c.use_animated_seed = spp, SEED, False
    c.use_adaptive_sampling = c.use_denoising = False
    c.sample_clamp_indirect = 0.0
    c.max_bounces = max_bounces
    for k in ("diffuse_bounces", "glossy_bounces", "transmission_bounces", "transparent_max_bounces"):
        setattr(c, k, max_bounces)
    c.caustics_reflective = c.caustics_refractive = True
    world = bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
    bg.inputs[1].default_value = 1.0
    glass = _glass()
    for m in G.scene_meshes():
        obj = _mesh_object(m)
        mat = glass if m.kind == "glass" else _diffuse(m.name + "Mat", m.color)
        obj.data.materials.append(mat)
    cam = sl._add_pinned_camera(bpy, scene, G.CAMERA["loc"], G.CAMERA["target"], lens=G.CAMERA["lens"])
    cam.data.sensor_width = G.CAMERA["sensor"]
    cam.data.sensor_fit = "HORIZONTAL"
    return scene


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = argv[argv.index("--out") + 1]
    build()
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
    print(f"[pkg325] wrote {out}")


if __name__ == "__main__":
    main()

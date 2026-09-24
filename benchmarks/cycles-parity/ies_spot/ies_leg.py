# -*- coding: utf-8 -*-
"""pkg276 controlled single-light IES A/B — one render leg (runs INSIDE Blender).

Builds the ies_reference.SpotScene in Blender (grey Diffuse plane, one POINT or
SPOT light with an optional INTERNAL TexIES node wired into Emission Strength,
black world, top-down camera), renders with CYCLES or the Astroray addon, and
writes LINEAR top-down pixels to <out>.npy.

  blender -b --factory-startup --python ies_leg.py -- --engine CYCLES \
      --out <stem> [--ies <file.ies>] [--kind SPOT|POINT] [--samples 64]

Prints ``PKG276_LEG PASS`` on success, ``PKG276_LEG FAIL <reason>`` otherwise.
The addon bootstrap and EXR->npy readback are reused from
benchmarks/cycles-parity/thin_film/render_leg.py (its pixels are Blender
bottom-up; this leg flips them to top-down before saving).
"""

import argparse
import importlib.util
import json
import math
import sys
import traceback
from pathlib import Path

SENTINEL = "PKG276_LEG"
_HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # @dataclass resolves its module via sys.modules
    spec.loader.exec_module(mod)
    return mod


def build_scene(bpy, sc, ies_text):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    world = bpy.data.worlds.new("Black")
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
    bg.inputs[1].default_value = 0.0
    scene.world = world

    mesh = bpy.data.meshes.new("Plane")
    s = 6.0
    mesh.from_pydata([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], [], [(0, 1, 2, 3)])
    plane = bpy.data.objects.new("Plane", mesh)
    scene.collection.objects.link(plane)
    mat = bpy.data.materials.new("Grey")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.inputs["Color"].default_value = (sc.albedo, sc.albedo, sc.albedo, 1.0)
    diff.inputs["Roughness"].default_value = 0.0
    nt.links.new(diff.outputs[0], out.inputs["Surface"])
    mesh.materials.append(mat)

    ld = bpy.data.lights.new("Light", type=sc.kind)
    ld.energy = sc.power
    ld.color = (1.0, 1.0, 1.0)
    ld.shadow_soft_size = sc.radius
    if hasattr(ld, "use_soft_falloff"):
        ld.use_soft_falloff = sc.soft_falloff
    if sc.kind == "SPOT":
        ld.spot_size = sc.spot_size
        ld.spot_blend = sc.spot_blend
    if sc.kind == "AREA":  # #852 spread A/B
        ld.shape = sc.area_shape
        ld.size, ld.size_y = sc.area_size
        ld.spread = sc.spread
    if ies_text:
        ld.use_nodes = True
        lnt = ld.node_tree
        emission = next(n for n in lnt.nodes if n.type == "EMISSION")
        text = bpy.data.texts.new("pkg276.ies")
        text.write(ies_text)
        ies = lnt.nodes.new("ShaderNodeTexIES")
        ies.mode = "INTERNAL"
        ies.ies = text
        lnt.links.new(ies.outputs[0], emission.inputs["Strength"])
    lobj = bpy.data.objects.new("Light", ld)
    scene.collection.objects.link(lobj)
    lobj.location = sc.light_pos
    lobj.rotation_euler = (math.radians(sc.light_rot_x_deg), 0.0,
                           math.radians(sc.light_rot_z_deg))

    cd = bpy.data.cameras.new("Cam")
    cd.lens_unit = "FOV"
    cd.sensor_fit = "AUTO"
    cd.angle = math.radians(sc.fov_deg)
    cam = bpy.data.objects.new("Cam", cd)
    scene.collection.objects.link(cam)
    cam.location = (0.0, 0.0, sc.cam_height)
    cam.rotation_euler = (0.0, 0.0, 0.0)
    scene.camera = cam
    return scene


def configure(scene, engine, device, res, samples, seed=7):
    scene.render.resolution_x = res
    scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.exr_codec = "NONE"
    scene.render.engine = engine
    c = scene.cycles
    c.samples = samples
    c.use_denoising = False
    c.use_adaptive_sampling = False
    c.seed = seed
    c.sample_clamp_direct = 0.0
    c.sample_clamp_indirect = 0.0
    c.pixel_filter_type = "BOX"
    c.filter_width = 1.0
    c.device = "CPU"
    if engine == "CUSTOM_RAYTRACER" and hasattr(scene, "custom_raytracer"):
        cr = scene.custom_raytracer
        cr.samples = samples
        if hasattr(cr, "preview_samples"):
            cr.preview_samples = samples
        if hasattr(cr, "device_mode"):
            cr.device_mode = device


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--engine", required=True, choices=("CYCLES", "CUSTOM_RAYTRACER"))
    p.add_argument("--device", default="cpu", choices=("cpu", "gpu"))
    p.add_argument("--out", required=True, help="output stem (no extension)")
    p.add_argument("--ies", default="", help="LM-63 file; empty = no IES node")
    p.add_argument("--scene-json", default="{}", help="SpotScene field overrides")
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--seed", type=int, default=7, help="nonzero (0 = random)")
    p.add_argument("--save-blend", default="")
    args = p.parse_args(argv)
    try:
        import bpy
        import numpy as np
        ref = _load("pkg276_ies_reference", _HERE / "ies_reference.py")
        leg = _load("pkg276_tf_leg", _HERE.parent / "thin_film" / "render_leg.py")
        sc = ref.SpotScene(**json.loads(args.scene_json))
        if isinstance(sc.light_pos, list):
            sc.light_pos = tuple(sc.light_pos)
        if args.engine == "CUSTOM_RAYTRACER":
            leg._bootstrap_astroray_addon(_HERE.parents[2])
        ies_text = Path(args.ies).read_text(encoding="utf-8") if args.ies else ""
        scene = build_scene(bpy, sc, ies_text)
        configure(scene, args.engine, args.device, sc.res, args.samples, args.seed)
        if args.save_blend:
            bpy.ops.wm.save_as_mainfile(filepath=args.save_blend)
        out_stem = Path(args.out)
        out_stem.parent.mkdir(parents=True, exist_ok=True)
        npy = leg._render_to_npy(bpy, scene, out_stem)
        px = np.load(npy)
        np.save(npy, np.ascontiguousarray(px[::-1]))   # Blender bottom-up -> top-down
        print(f"[pkg276-leg] wrote {npy}", flush=True)
        print(f"{SENTINEL} PASS", flush=True)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        print(f"{SENTINEL} FAIL {type(exc).__name__}: {exc}", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()

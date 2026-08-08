# -*- coding: utf-8 -*-
"""pkg180 Phase 2 — Blender A/B leg (runs INSIDE Blender, one engine per process).

Scenes:
  area        : diffuse 0.5 floor, 3x3 AREA lamp 300W at z=3, identity rotation
  area_flip   : same, lamp flipped 180 deg about X (Astroray-leg legacy convention)
  sun         : diffuse 0.5 floor, SUN energy=pi straight down -> analytic L=0.5
  mirror_lamp : glossy(0.05) floor, camera sees the reflection of a 100W 2x2 AREA lamp
  mirror_mesh : same but radiance-matched emissive mesh plane (strength 100/(4*pi))

Usage:
  blender --background --factory-startup --python blender_leg.py -- \
      --scene area --engine CYCLES --out <stem> [--spp 512]
"""
import argparse
import glob
import math
import os
import sys
from pathlib import Path

import bpy

SENTINEL = "PKG180_LEG"
ROOT = Path(r"C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray")


def bootstrap_astroray():
    build_dir = Path(os.environ.get(
        "ASTRORAY_PYD_DIR", str(ROOT / "build_blender_addon_cuda")))
    for entry in (str(build_dir), str(ROOT)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    for dll_dir in [build_dir,
                    ROOT / "build_cuda",
                    Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.8/bin"),
                    Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.8/bin/x64"),
                    Path(r"C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v12.6/bin"),
                    Path(r"C:/Program Files/mingw64/bin"),
                    Path(r"C:/msys64/mingw64/bin"),
                    Path(r"C:/msys64/ucrt64/bin")]:
        if dll_dir.is_dir():
            try:
                os.add_dll_directory(str(dll_dir))
            except (OSError, AttributeError):
                pass
    import astroray  # noqa: F401
    print(f"[pkg180-leg] astroray: {astroray.__file__}", flush=True)
    import blender_addon
    try:
        blender_addon.register()
    except Exception as exc:  # noqa: BLE001
        if "already registered" not in str(exc):
            raise


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    world = bpy.data.worlds.new("W")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
    bg.inputs[1].default_value = 0.0
    return scene


def add_floor(diffuse=True):
    bpy.ops.mesh.primitive_plane_add(size=40.0, location=(0.0, 0.0, 0.0))
    floor = bpy.context.active_object
    mat = bpy.data.materials.new("Floor")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    if diffuse:
        node = nt.nodes.new("ShaderNodeBsdfDiffuse")
        node.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)
        node.inputs["Roughness"].default_value = 0.0
    else:
        node = nt.nodes.new("ShaderNodeBsdfGlossy")
        node.inputs["Color"].default_value = (0.9, 0.9, 0.9, 1.0)
        node.inputs["Roughness"].default_value = 0.05
        try:
            node.distribution = "GGX"
        except Exception:  # noqa: BLE001
            pass
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(node.outputs["BSDF"], out.inputs["Surface"])
    floor.data.materials.append(mat)
    return floor


def add_topdown_camera(scene, tilt_deg=0.0):
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "PERSP"
    cam_data.lens_unit = "FOV"
    cam_data.angle = math.radians(20.0)
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, 0.0, 20.0)
    cam.rotation_euler = (math.radians(tilt_deg), 0.0, 0.0)
    scene.camera = cam
    return cam


def build_scene(name, engine):
    import mathutils
    scene = reset()
    if name in ("area", "area_flip"):
        add_floor(diffuse=True)
        add_topdown_camera(scene)
        ld = bpy.data.lights.new("L", type="AREA")
        ld.energy = 300.0
        ld.shape = "RECTANGLE"
        ld.size = 3.0
        ld.size_y = 3.0
        obj = bpy.data.objects.new("L", ld)
        scene.collection.objects.link(obj)
        obj.location = (0.0, 0.0, 3.0)
        obj.rotation_euler = (math.pi, 0.0, 0.0) if name == "area_flip" else (0.0, 0.0, 0.0)
    elif name == "sun":
        add_floor(diffuse=True)
        add_topdown_camera(scene, tilt_deg=5.0)
        ld = bpy.data.lights.new("L", type="SUN")
        ld.energy = math.pi
        ld.angle = math.radians(0.526)
        obj = bpy.data.objects.new("L", ld)
        scene.collection.objects.link(obj)
        obj.location = (0.0, 0.0, 10.0)
        obj.rotation_euler = (0.0, 0.0, 0.0)
    elif name in ("mirror_lamp", "mirror_mesh"):
        add_floor(diffuse=False)
        cam_data = bpy.data.cameras.new("Cam")
        cam_data.type = "PERSP"
        cam_data.lens_unit = "FOV"
        cam_data.angle = math.radians(30.0)
        cam = bpy.data.objects.new("Cam", cam_data)
        scene.collection.objects.link(cam)
        cam.location = (0.0, 8.0, 3.0)
        look = mathutils.Vector((0.0, -8.0, -3.0)).normalized()
        cam.rotation_euler = look.to_track_quat('-Z', 'Y').to_euler()
        scene.camera = cam
        pos = mathutils.Vector((0.0, -8.0, 3.0))
        aim = (mathutils.Vector((0.0, 0.0, 0.0)) - pos).normalized()
        if name == "mirror_lamp":
            ld = bpy.data.lights.new("L", type="AREA")
            ld.energy = 100.0
            ld.shape = "RECTANGLE"
            ld.size = 2.0
            ld.size_y = 2.0
            obj = bpy.data.objects.new("L", ld)
            scene.collection.objects.link(obj)
            obj.location = pos
            obj.rotation_euler = aim.to_track_quat('-Z', 'Y').to_euler()
        else:
            bpy.ops.mesh.primitive_plane_add(size=2.0, location=pos)
            plane = bpy.context.active_object
            plane.rotation_euler = aim.to_track_quat('Z', 'Y').to_euler()
            mat = bpy.data.materials.new("Emit")
            mat.use_nodes = True
            nt = mat.node_tree
            for n in list(nt.nodes):
                nt.nodes.remove(n)
            em = nt.nodes.new("ShaderNodeEmission")
            em.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
            em.inputs["Strength"].default_value = 100.0 / (math.pi * 4.0)
            out = nt.nodes.new("ShaderNodeOutputMaterial")
            nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
            plane.data.materials.append(mat)
    else:
        raise ValueError(name)
    return scene


def render_and_measure(scene, engine, spp, out_stem, res):
    scene.render.engine = engine
    scene.render.resolution_x = res
    scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.image_settings.exr_codec = "NONE"
    scene.cycles.seed = 7
    if engine == "CYCLES":
        scene.cycles.samples = spp
        scene.cycles.use_denoising = False
        scene.cycles.use_adaptive_sampling = False
    elif hasattr(scene, "custom_raytracer"):
        cr = scene.custom_raytracer
        cr.samples = spp
        if hasattr(cr, "preview_samples"):
            cr.preview_samples = spp
        if hasattr(cr, "device_mode"):
            for mode in ("cpu", "CPU", "auto"):
                try:
                    cr.device_mode = mode
                    break
                except Exception:  # noqa: BLE001
                    continue
            print(f"[pkg180-leg] device_mode={cr.device_mode}", flush=True)

    for f in glob.glob(str(out_stem) + "*"):
        os.remove(f)
    scene.render.filepath = str(out_stem)
    bpy.ops.render.render(write_still=True)

    matches = sorted(glob.glob(str(out_stem) + "*.exr")) or sorted(glob.glob(str(out_stem) + "*"))
    img = bpy.data.images.load(matches[0])
    w, h = img.size
    import numpy as np
    px = np.asarray(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[:, :, :3]
    bpy.data.images.remove(img)
    np.save(str(out_stem) + ".npy", np.ascontiguousarray(px))

    lumin = 0.2126 * px[..., 0] + 0.7152 * px[..., 1] + 0.0722 * px[..., 2]
    cy, cx = h // 2, w // 2
    center = np.mean(lumin[cy - 4:cy + 4, cx - 4:cx + 4])
    top = np.sort(lumin.ravel())[::-1]
    print(f"PKG180_STATS center8_lum={center:.5f} img_mean={lumin.mean():.5f} "
          f"top40_lum={top[:40].mean():.5f} max_lum={top[0]:.5f}", flush=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--scene", required=True)
    p.add_argument("--engine", required=True, choices=("CYCLES", "CUSTOM_RAYTRACER"))
    p.add_argument("--out", required=True)
    p.add_argument("--spp", type=int, default=512)
    args = p.parse_args(argv)
    try:
        if args.engine == "CUSTOM_RAYTRACER":
            bootstrap_astroray()
        scene = build_scene(args.scene, args.engine)
        res = 96 if args.scene.startswith("mirror") else 64
        out_stem = Path(args.out)
        out_stem.parent.mkdir(parents=True, exist_ok=True)
        render_and_measure(scene, args.engine, args.spp, out_stem, res)
        print(f"{SENTINEL} PASS", flush=True)
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"{SENTINEL} FAIL {type(exc).__name__}: {exc}", flush=True)
        sys.exit(0)


main()

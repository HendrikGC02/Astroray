# -*- coding: utf-8 -*-
"""pkg139 hardware verification -- live headless-Cycles A/B oracle for the
AREA-light orientation fix + world strength-0 background fix.

Adapted from Astroray-pkg122/scripts/verify_pkg122_cycles_oracle.py (same
methodology: same bpy light object driven through CYCLES then through the
Astroray CUSTOM_RAYTRACER addon engine). CRITICAL: this script lives in the
pkg139 WORKTREE scripts/ dir; ROOT resolves to the pkg139 worktree so
"import blender_addon" picks up the worktree fixed __init__.py, not
main. astroray (.pyd) is instead loaded via ASTRORAY_BUILD_DIR pointed at
main fresh build_cuda/Release (engine code identical between branch/main).

Run headless, once per --scenario:
    blender --background --factory-startup --python scripts/verify_pkg139_area_orientation_oracle.py -- --scenario identity --out test_results/pkg139_oracle
"""
import argparse
import glob
import math
import os
import sys
from pathlib import Path

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import runtime_setup  # noqa: E402
runtime_setup.configure_test_imports()
sys.path.insert(0, ROOT)


def _bootstrap_astroray_addon():
    import astroray  # noqa: F401
    print(f"[pkg139-oracle] astroray module: {astroray.__file__}")
    import blender_addon
    print(f"[pkg139-oracle] blender_addon module: {blender_addon.__file__}")
    try:
        blender_addon.register()
    except Exception as exc:
        if "already registered" not in str(exc):
            raise


def build_scene(scenario, engine=None):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    world = bpy.data.worlds.new("W")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")

    world_strength_zero = scenario == "world_strength_zero"
    bg.inputs[0].default_value = (0.6, 0.3, 0.1, 1.0)
    bg.inputs[1].default_value = 0.0 if world_strength_zero else 0.0

    bpy.ops.mesh.primitive_plane_add(size=40.0, location=(0.0, 0.0, 0.0))
    floor = bpy.context.active_object
    mat = bpy.data.materials.new("Floor")
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    diff = nt.nodes.new("ShaderNodeBsdfDiffuse")
    diff.inputs["Color"].default_value = (0.5, 0.5, 0.5, 1.0)
    diff.inputs["Roughness"].default_value = 0.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(diff.outputs["BSDF"], out.inputs["Surface"])
    floor.data.materials.append(mat)

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "PERSP"
    cam_data.lens_unit = "FOV"
    cam_data.angle = math.radians(20.0)
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0.0, 0.0, 20.0)
    cam.rotation_euler = (0.0, 0.0, 0.0)
    scene.camera = cam

    if scenario == "world_strength_zero":
        light_data = bpy.data.lights.new("L", type="SPOT")
        light_obj = bpy.data.objects.new("L", light_data)
        scene.collection.objects.link(light_obj)
        light_obj.rotation_euler = (0.0, 0.0, 0.0)
        light_data.energy = 800.0
        light_obj.location = (0.0, 0.0, 3.0)
        light_data.shadow_soft_size = 0.0
        light_data.spot_size = math.radians(20.0)
        light_data.spot_blend = 0.2
        return scene

    light_data = bpy.data.lights.new("L", type="AREA")
    light_obj = bpy.data.objects.new("L", light_data)
    scene.collection.objects.link(light_obj)
    light_data.energy = 300.0
    light_obj.location = (0.0, 0.0, 3.0)
    light_data.shape = "RECTANGLE"

    if scenario == "identity":
        light_data.size = 3.0
        light_data.size_y = 3.0
        light_obj.rotation_euler = (0.0, 0.0, 0.0)
    elif scenario == "rotated45":
        light_data.size = 3.0
        light_data.size_y = 3.0
        light_obj.rotation_euler = (math.radians(45.0), 0.0, 0.0)
    elif scenario == "nonsquare":
        light_data.size = 2.4
        light_data.size_y = 0.4
        light_obj.rotation_euler = (0.0, 0.0, 0.0)
    else:
        raise ValueError(f"unknown scenario {scenario}")

    return scene


def render_engine(scene, engine, spp, out_stem):
    scene.render.engine = engine
    scene.render.resolution_x = 128
    scene.render.resolution_y = 128
    scene.render.resolution_percentage = 100
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
        scene.custom_raytracer.samples = spp
        scene.custom_raytracer.preview_samples = spp
        if hasattr(scene.custom_raytracer, "device_mode"):
            scene.custom_raytracer.device_mode = "gpu"

    for f in glob.glob(str(out_stem) + "*"):
        os.remove(f)
    scene.render.filepath = str(out_stem)
    bpy.ops.render.render(write_still=True)

    matches = sorted(glob.glob(str(out_stem) + "*"))
    if not matches:
        raise RuntimeError(f"no render output found for stem {out_stem}")
    out_path = matches[0]

    img = bpy.data.images.load(out_path)
    w, h = img.size
    px = list(img.pixels[:])
    import array
    arr = array.array("f", px)
    bpy.data.images.remove(img)

    png_stem = str(out_stem) + "_view"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_depth = "8"
    for f in glob.glob(png_stem + "*"):
        os.remove(f)
    scene.render.filepath = png_stem
    bpy.ops.render.render(write_still=True)

    return arr, w, h, out_path


def patch_mean(arr, w, h, cx, cy, patch=8):
    x0, x1 = max(0, cx - patch // 2), min(w, cx + patch // 2)
    y0, y1 = max(0, cy - patch // 2), min(h, cy + patch // 2)
    sums = [0.0, 0.0, 0.0]
    n = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            idx = (y * w + x) * 4
            sums[0] += arr[idx]
            sums[1] += arr[idx + 1]
            sums[2] += arr[idx + 2]
            n += 1
    return [s / n for s in sums] if n else [float("nan")] * 3


def world_to_pixel(wx, wy, w, h, cam_height=20.0, fov_deg=20.0):
    half_width = cam_height * math.tan(math.radians(fov_deg) / 2.0)
    fx = wx / half_width
    fy = wy / half_width
    px = int(round(w / 2 + fx * (w / 2)))
    py = int(round(h / 2 - fy * (h / 2)))
    return px, py


def count_nan(arr):
    n = 0
    for v in arr:
        if v != v:
            n += 1
    return n


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", required=True,
                    choices=["identity", "rotated45", "nonsquare", "world_strength_zero"])
    p.add_argument("--out", type=Path, default=Path("test_results/pkg139_oracle"))
    p.add_argument("--spp", type=int, default=512)
    args = p.parse_args(argv)

    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)

    results = {}
    nan_counts = {}
    paths = {}
    for engine in ("CYCLES", "CUSTOM_RAYTRACER"):
        scene = build_scene(args.scenario, engine=engine)
        if engine == "CUSTOM_RAYTRACER":
            _bootstrap_astroray_addon()
        stem = args.out / f"{args.scenario}_{engine.lower()}"
        arr, w, h, out_path = render_engine(scene, engine, args.spp, stem)
        nan_counts[engine] = count_nan(arr)
        paths[engine] = out_path

        if args.scenario == "world_strength_zero":
            rgb = patch_mean(arr, w, h, w - 10, 10, patch=8)
        elif args.scenario == "nonsquare":
            cx, cy = w // 2, h // 2
            px_x, py_x = world_to_pixel(2.0, 0.0, w, h)
            px_y, py_y = world_to_pixel(0.0, 2.0, w, h)
            rgb = {
                "center": patch_mean(arr, w, h, cx, cy, patch=10),
                "probe_pX_u_sizex": patch_mean(arr, w, h, px_x, py_x, patch=8),
                "probe_pY_v_sizey": patch_mean(arr, w, h, px_y, py_y, patch=8),
            }
        else:
            cx, cy = w // 2, h // 2
            rgb = patch_mean(arr, w, h, cx, cy, patch=10)

        results[engine] = rgb
        print(f"[pkg139-oracle] {args.scenario} {engine}: rgb={rgb} nan={nan_counts[engine]} file={out_path}")

    cyc = results["CYCLES"]
    ast = results["CUSTOM_RAYTRACER"]

    if args.scenario == "nonsquare":
        for key in ("center", "probe_pX_u_sizex", "probe_pY_v_sizey"):
            c = cyc[key]
            a = ast[key]
            ratios = [x / y if y > 1e-9 else float("nan") for x, y in zip(a, c)]
            print(f"[pkg139-oracle] {args.scenario} {key} RESULT cycles_rgb={c} astroray_rgb={a} ratio={ratios}")
    elif args.scenario == "world_strength_zero":
        print(f"[pkg139-oracle] {args.scenario} RESULT cycles_corner_rgb={cyc} astroray_corner_rgb={ast}")
    else:
        ratios = [a / c if c > 1e-9 else float("nan") for a, c in zip(ast, cyc)]
        print(f"[pkg139-oracle] {args.scenario} RESULT cycles_rgb={cyc} astroray_rgb={ast} ratio_astroray_over_cycles={ratios}")

    print(f"[pkg139-oracle] {args.scenario} NAN_COUNTS cycles={nan_counts['CYCLES']} astroray={nan_counts['CUSTOM_RAYTRACER']}")


main()

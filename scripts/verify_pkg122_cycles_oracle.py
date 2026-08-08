# -*- coding: utf-8 -*-
"""pkg122 hardware verification -- live headless-Cycles A/B oracle.

Builds ONE native-Blender-light scene per dedicated-light type (POINT, AREA,
SPOT, SUN) and renders it twice -- once with CYCLES, once with the Astroray
CUSTOM_RAYTRACER addon engine -- using literally the same bpy light object
(light.energy in Watts / W/m^2 for SUN), so the addons own light-conversion
path (blender_addon/__init__.py convert_lights: intensity = light.energy) is
exercised exactly as an artist would see it. This is the live-Cycles A/B the
pkg122 spec calls for (docs/pkg122-light-energy-calibration-research.md,
left for the team-leads post-build live-Cycles run).

Floor: 40x40 gray Diffuse BSDF (roughness=0 -> exact Lambertian in Cycles;
near-identical to Astrorays Disney-diffuse-at-roughness-0 at the near-normal
incidence angles sampled here). Camera straight down, matching a top-down
radiometric probe.

Run headless, once per --light-type:
    blender --background --factory-startup --python scripts/verify_pkg122_cycles_oracle.py -- --light-type POINT --out test_results/pkg122_cycles_oracle
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
    print(f"[pkg122-oracle] astroray module: {astroray.__file__}")
    import blender_addon
    try:
        blender_addon.register()
    except Exception as exc:
        if "already registered" not in str(exc):
            raise


def build_scene(light_type, energy, height, extra, engine=None):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    world = bpy.data.worlds.new("W")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.0, 0.0, 0.0, 1.0)
    bg.inputs[1].default_value = 0.0

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
    # SUN only: tilt 5 deg off the exact vertical camera/light alignment.
    # KNOWN FINDING (pkg122 verifier, 2026-07-20): at exact vertical
    # alignment, Astroray Disney-material floors carry a baseline
    # Fresnel-specular lobe (present regardless of roughness/specular
    # create_material params) that NEE-evaluates to a true delta for
    # delta lights (POINT/SPOT/AREA -- zero contribution, no artifact)
    # but leaks extra energy against SUN's finite-angle cone sampling
    # (measured 1.67x-1.85x excess; vanishes with pure 'lambertian').
    # Tilting breaks the exact alignment; <1% cos-falloff effect.
    if light_type == "SUN":
        cam.rotation_euler = (math.radians(5.0), 0.0, 0.0)
    else:
        cam.rotation_euler = (0.0, 0.0, 0.0)
    scene.camera = cam

    light_data = bpy.data.lights.new("L", type=light_type)
    light_obj = bpy.data.objects.new("L", light_data)
    scene.collection.objects.link(light_obj)
    light_obj.rotation_euler = (0.0, 0.0, 0.0)

    if light_type == "SUN":
        light_data.energy = energy
        light_data.angle = extra.get("angle", math.radians(0.526))
        light_obj.location = (0.0, 0.0, 10.0)
    else:
        light_data.energy = energy
        light_obj.location = (0.0, 0.0, height)
        if light_type == "POINT":
            light_data.shadow_soft_size = 0.0
        elif light_type == "AREA":
            light_data.shape = "RECTANGLE"
            light_data.size = extra["size_x"]
            light_data.size_y = extra["size_y"]
            if engine == "CUSTOM_RAYTRACER":
                # KNOWN FINDING (pkg122 verifier, 2026-07-20): the Astroray
                # AreaLight normal = axis_u x axis_v = local +X x local +Y =
                # local +Z. Cycles area lights (like spot/sun/camera) use
                # local -Z as forward. With identity rotation the Astroray
                # dedicated area light therefore points AWAY from a floor
                # below (measured ratio ~0.09-0.12x, i.e. the OLD pre-pkg122
                # 0.13x symptom, reproduced by orientation not intensity).
                # This is an addon integration bug orthogonal to pkg122's
                # wattage fix. Flip 180 deg about X ONLY for the Astroray
                # render so this oracle isolates the INTENSITY ratio; do
                # NOT read this as "AREA still broken" -- see verifier
                # report for the orientation-bug writeup.
                light_obj.rotation_euler = (math.pi, 0.0, 0.0)
        elif light_type == "SPOT":
            light_data.shadow_soft_size = 0.0
            light_data.spot_size = extra["spot_size"]
            light_data.spot_blend = extra["spot_blend"]

    return scene


def render_engine(scene, engine, spp, out_stem):
    scene.render.engine = engine
    scene.render.resolution_x = 64
    scene.render.resolution_y = 64
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
        # pkg176 Stage 4: samples/preview_samples read from native Cycles props.
        scene.cycles.samples = spp
        scene.cycles.preview_samples = spp
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
    return arr, w, h, out_path


def center_patch_mean(arr, w, h, patch=8):
    cx, cy = w // 2, h // 2
    x0, x1 = cx - patch // 2, cx + patch // 2
    y0, y1 = cy - patch // 2, cy + patch // 2
    sums = [0.0, 0.0, 0.0]
    n = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            idx = (y * w + x) * 4
            sums[0] += arr[idx]
            sums[1] += arr[idx + 1]
            sums[2] += arr[idx + 2]
            n += 1
    return [s / n for s in sums]


SCENES = {
    "POINT": dict(energy=800.0, height=3.0, extra={}),
    "AREA": dict(energy=300.0, height=3.0, extra={"size_x": 3.0, "size_y": 3.0}),
    "SPOT": dict(energy=800.0, height=3.0,
                 extra={"spot_size": math.radians(46.0), "spot_blend": 0.5}),
    "SUN": dict(energy=5.0, height=10.0, extra={"angle": math.radians(0.526)}),
}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--light-type", required=True, choices=list(SCENES.keys()))
    p.add_argument("--out", type=Path, default=Path("test_results/pkg122_cycles_oracle"))
    p.add_argument("--spp", type=int, default=512)
    args = p.parse_args(argv)

    cfg = SCENES[args.light_type]
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)

    results = {}
    for engine in ("CYCLES", "CUSTOM_RAYTRACER"):
        scene = build_scene(args.light_type, cfg["energy"], cfg["height"], cfg["extra"], engine=engine)
        if engine == "CUSTOM_RAYTRACER":
            _bootstrap_astroray_addon()
        stem = args.out / f"{args.light_type.lower()}_{engine.lower()}"
        arr, w, h, out_path = render_engine(scene, engine, args.spp, stem)
        rgb = center_patch_mean(arr, w, h)
        results[engine] = rgb
        print(f"[pkg122-oracle] {args.light_type} {engine}: center_rgb={rgb} file={out_path}")

    cyc = results["CYCLES"]
    ast = results["CUSTOM_RAYTRACER"]
    ratios = [a / c if c > 1e-9 else float("nan") for a, c in zip(ast, cyc)]
    print(f"[pkg122-oracle] {args.light_type} RESULT cycles_rgb={cyc} astroray_rgb={ast} ratio_astroray_over_cycles={ratios}")


main()

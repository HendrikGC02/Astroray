"""pkg257 -- headless Cycles-vs-Astroray Displacement A/B (one-off, delete when
the package closes; the PR + STATUS.md are the record, per CLAUDE.md 5b).

Builds a tiny scene: a plane with a Principled BSDF + an Image-Texture-driven
Displacement node (Height only; displacement_method left at Blender's own
default 'BUMP' so Cycles and Astroray are compared apples-to-apples per the
spec's acceptance criterion 3), a grazing sun, and a top-down camera. Renders
once with Cycles (native BUMP) and once with Astroray (bump-approximated via
this package's new addon path), saving both PNGs under test_results/.

Run headless:
    $env:ASTRORAY_PYD_DIR = "<repo>/dist/astroray"
    & "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" \
        --background --factory-startup --python scripts/pkg257_displacement_ab.py
"""
import os
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "test_results" / "2026-09-08-pkg257"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _bootstrap_addon():
    default_build = REPO_ROOT / "build_cuda"
    if not list(default_build.glob("astroray*.pyd")):
        default_build = REPO_ROOT / "build_cuda" / "Release"
    build_dir = Path(os.environ.get("ASTRORAY_PYD_DIR", default_build))
    for entry in (str(build_dir), str(REPO_ROOT)):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    if build_dir.is_dir():
        try:
            os.add_dll_directory(str(build_dir))
        except (OSError, AttributeError):
            pass
    import astroray  # noqa: F401
    print(f"[pkg257-ab] astroray module: {astroray.__file__}")
    import blender_addon
    try:
        blender_addon.register()
    except Exception as exc:
        if "already registered" not in str(exc):
            raise
    return blender_addon


def _height_image(name="pkg257_height", n=64):
    """A radial bump pattern (a few raised 'bumps') baked into an Image
    datablock -- gives clearly visible, non-uniform relief unlike a flat ramp."""
    img = bpy.data.images.new(name, width=n, height=n, alpha=False)
    ys, xs = np.mgrid[0:n, 0:n].astype(np.float32)
    centers = [(16, 16), (48, 16), (16, 48), (48, 48), (32, 32)]
    height = np.zeros((n, n), dtype=np.float32)
    for cx, cy in centers:
        r = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
        # Sharp falloff (radius 4 texels, not 10): the bump math derives relief
        # from the per-texel HEIGHT GRADIENT, not the strength/distance params
        # alone, so a steep bump edge is what makes the effect visible at this
        # tiny 64x64 test scale.
        height += np.clip(1.0 - r / 4.0, 0.0, 1.0)
    height = np.clip(height, 0.0, 1.0)
    rgba = np.zeros((n, n, 4), dtype=np.float32)
    rgba[..., 0] = height
    rgba[..., 1] = height
    rgba[..., 2] = height
    rgba[..., 3] = 1.0
    img.pixels = rgba.flatten().tolist()
    img.pack()
    return img


def _build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    bpy.ops.mesh.primitive_plane_add(size=2.0, location=(0, 0, 0))
    plane = bpy.context.active_object
    plane.data.polygons[0].use_smooth = True  # bump needs smooth shading (memory: cycles-caustics-need-smooth-shading applies to relief legibility too)

    mat = bpy.data.materials.new("pkg257_disp_mat")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Base Color'].default_value = (0.75, 0.72, 0.68, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.6
    tex_image = nt.nodes.new('ShaderNodeTexImage')
    tex_image.image = _height_image()
    disp = nt.nodes.new('ShaderNodeDisplacement')
    disp.inputs['Midlevel'].default_value = 0.5
    disp.inputs['Scale'].default_value = 0.35
    nt.links.new(tex_image.outputs['Color'], disp.inputs['Height'])
    nt.links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    nt.links.new(disp.outputs['Displacement'], out.inputs['Displacement'])
    mat.displacement_method = 'BUMP'  # Blender's own default -- apples-to-apples (spec criterion 3)
    plane.data.materials.append(mat)

    sun_data = bpy.data.lights.new("pkg257_sun", type='SUN')
    sun_data.energy = 1.0
    sun_data.angle = 0.03  # tight grazing shadows for visible relief
    sun = bpy.data.objects.new("pkg257_sun_obj", sun_data)
    scene.collection.objects.link(sun)
    # Grazing light direction (mirrors pkg223b's own bump test): mostly
    # horizontal with a shallow ~22 deg elevation, so small normal tilts from
    # bump relief swing N.L hard and cast visible micro-shadows.
    light_dir = Vector((-1.0, 0.0, -0.4)).normalized()
    sun.rotation_euler = light_dir.to_track_quat('-Z', 'Y').to_euler()

    cam_data = bpy.data.cameras.new("pkg257_cam")
    cam_data.lens = 35
    cam = bpy.data.objects.new("pkg257_cam_obj", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (0, 0, 3.2)
    cam.rotation_euler = (0, 0, 0)  # looking straight down -Z at the plane
    scene.camera = cam

    scene.render.resolution_x = 64
    scene.render.resolution_y = 64
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'PNG'
    scene.cycles.samples = 64
    scene.cycles.use_denoising = False
    scene.view_settings.view_transform = 'Standard'  # AgX flattens this tiny signal
    scene.view_settings.exposure = 1.0
    return scene, mat


def main():
    addon = _bootstrap_addon()
    scene, mat = _build_scene()

    scene.render.engine = 'CYCLES'
    scene.render.filepath = str(OUT_DIR / "cycles_displacement_bump.png")
    bpy.ops.render.render(write_still=True)
    print(f"[pkg257-ab] wrote {scene.render.filepath}")

    scene.render.engine = 'CUSTOM_RAYTRACER'
    scene.custom_raytracer.device_mode = 'cpu'  # avoid the GPU lock for this A/B
    scene.render.filepath = str(OUT_DIR / "astroray_displacement_bump.png")
    bpy.ops.render.render(write_still=True)
    print(f"[pkg257-ab] wrote {scene.render.filepath}")

    print("[pkg257-ab] done")


if __name__ == "__main__":
    main()

"""Render the Cycles reference for `disney-sweep-cycles-compared`.

Run this script via Blender 5.1 (headless) to produce `reference.png`:

    "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" --background \
        --python benchmarks/reference_bank/scenes/disney-sweep-cycles-compared/cycles_bless.py

The script:
  1. Resets the default scene.
  2. Constructs the same Disney sphere grid + floor + area light + camera
     as the Astroray scene (see scene.py).
  3. Sets Cycles as the render engine, samples = 256.
  4. Renders to `reference.png` next to this script.

Geometry / light / camera params are duplicated here verbatim so the two
scripts can drift independently if needed. If you change scene.py, mirror
the change here AND re-run this bless command.
"""

from __future__ import annotations

import os
import sys


def _build_scene():
    import bpy

    # Wipe the default scene.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    # --- Render settings ---
    scene.render.engine = "CYCLES"
    scene.cycles.device = "GPU" if hasattr(scene.cycles, "device") else "CPU"
    scene.cycles.samples = 256
    scene.render.resolution_x = 384
    scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.color_mode = "RGB"
    # "Standard" view transform applies sRGB encoding for 8-bit PNG output,
    # which matches Astroray's gamma-2.2 output. "Raw" was tested and
    # produced near-black PNGs because the linear-scene-referred values get
    # truncated to 8-bit without gamma encoding.
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    # Filmic is the Blender 5.1 default; explicitly forcing Standard is what
    # gets us closest to Astroray's tonemap.

    # --- Floor ---
    bpy.ops.mesh.primitive_plane_add(size=10.0, location=(0.0, -1.0, 0.0))
    floor = bpy.context.object
    floor_mat = bpy.data.materials.new("floor")
    floor_mat.use_nodes = True
    bsdf = floor_mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.55, 0.55, 0.55, 1.0)
    bsdf.inputs["Roughness"].default_value = 1.0
    bsdf.inputs["Metallic"].default_value = 0.0
    floor.data.materials.append(floor_mat)
    # Plane is XY in Blender by default; rotate to be XZ floor matching Astroray Y-up.
    # But Astroray uses Y-up + floor at y=-1.0 in XZ plane. Blender uses Z-up.
    # We'll set up Blender in Y-up coordinates by adjusting camera+orientation instead.
    # Simpler: build everything in Blender's natural Z-up and translate camera+light.

    # Reset: rebuild floor as XZ (Blender Z-up means floor is at Z=-1).
    bpy.data.objects.remove(floor, do_unlink=True)
    bpy.ops.mesh.primitive_plane_add(size=10.0, location=(0.0, 0.0, -1.0))
    floor = bpy.context.object
    floor.data.materials.append(floor_mat)

    # --- Area light at "top" (Z = +4 in Blender Z-up; matches Astroray Y=+4) ---
    bpy.ops.object.light_add(type="AREA", location=(0.0, 0.0, 4.0))
    area = bpy.context.object
    area.data.shape = "RECTANGLE"
    area.data.size = 3.0   # X
    area.data.size_y = 2.0  # Z (depth)
    # Cycles area-light energy in watts. With Astroray intensity=14 + sRGB-
    # encoded 8-bit output, Cycles needs ~1300W to bring its image mean
    # close to Astroray's (which renders at mean luminance ~0.44 of 1.0
    # for this scene). Without matching exposures, SSIM gates on structural
    # similarity get dragged below 0.5 by brightness mismatch alone.
    area.data.energy = 1300.0
    area.rotation_euler = (3.14159, 0, 0)  # point downward

    # --- Disney sphere grid ---
    roughness_values = [0.1, 0.5, 0.9]
    metallic_values = [0.0, 0.5, 1.0]
    n_x, n_y = len(roughness_values), len(metallic_values)
    sp_x, sp_y = 1.20, 1.20
    x0 = -(n_x - 1) * sp_x / 2
    y0 = -(n_y - 1) * sp_y / 2

    for j, m in enumerate(metallic_values):
        for i, rough in enumerate(roughness_values):
            x = x0 + i * sp_x
            # Astroray Y-up grid in XY plane (Z=0) -> Blender Z-up grid in XZ
            # plane (Y=0). AR's vertical (Y) becomes BL's vertical (Z); AR's
            # depth (Z) becomes BL's depth (-Y). Y=-0.55 offset in AR -> Z=-0.55 in BL.
            z = y0 + j * sp_y - 0.55
            bpy.ops.mesh.primitive_uv_sphere_add(radius=0.45, location=(x, 0.0, z))
            sphere = bpy.context.object
            mat = bpy.data.materials.new(f"sph_{i}_{j}")
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes["Principled BSDF"]
            bsdf.inputs["Base Color"].default_value = (0.72, 0.50, 0.32, 1.0)
            bsdf.inputs["Roughness"].default_value = rough
            bsdf.inputs["Metallic"].default_value = m
            # Specular input name varies by Blender version.
            for key in ("Specular IOR Level", "Specular"):
                if key in bsdf.inputs:
                    bsdf.inputs[key].default_value = 0.5
                    break
            sphere.data.materials.append(mat)
            bpy.ops.object.shade_smooth()

    # --- Camera (Z-up): Astroray's look_from (0,0.3,7.0) → Blender (0,-7.0,0.3)
    cam_pos = (0.0, -7.0, 0.3)
    cam_target = (0.0, 0.0, -0.6)
    bpy.ops.object.camera_add(location=cam_pos)
    cam = bpy.context.object
    import mathutils
    direction = mathutils.Vector(cam_target) - mathutils.Vector(cam_pos)
    rot_quat = direction.to_track_quat("-Z", "Y")
    cam.rotation_euler = rot_quat.to_euler()
    # Match Astroray's 30° vfov via lens-in-mm: with 36mm sensor width and
    # 384x256 (aspect 1.5), vfov 30° corresponds to ~67mm lens. Blender's
    # default sensor_fit='AUTO' picks the larger dimension automatically.
    # Set sensor_fit BEFORE angle: Blender derives lens(mm) from `angle` using the
    # sensor dimension of the CURRENT sensor_fit. If angle is set while sensor_fit is
    # still the default AUTO (which picks the LARGER/horizontal dimension at 1.5
    # aspect), the 30° lands on the horizontal axis and the resulting VERTICAL fov is
    # smaller than Astroray's 30° — the renders then don't line up (the owner-observed
    # FOV mismatch). Setting sensor_fit="VERTICAL" first makes `angle` the vertical fov,
    # matching Astroray's vfov=30. (Re-run this bless via Blender to regenerate reference.png.)
    cam.data.sensor_fit = "VERTICAL"
    cam.data.lens_unit = "FOV"
    cam.data.angle = 0.5236  # radians (30°) — vertical fov, set AFTER sensor_fit
    scene.camera = cam

    # World background: nearly black (Astroray's 0.04, 0.05, 0.06).
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs[0].default_value = (0.04, 0.05, 0.06, 1.0)
        bg.inputs[1].default_value = 1.0


def _render(output_path: str):
    import bpy
    bpy.context.scene.render.filepath = output_path
    bpy.ops.render.render(write_still=True)


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference.png")
    _build_scene()
    _render(out)
    print(f"[cycles_bless] wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()

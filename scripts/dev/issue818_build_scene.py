"""issue #818 — build the evidence .blend by script (run in Blender 5.2).

    blender -b --factory-startup --python scripts/dev/issue818_build_scene.py -- --out <path.blend>

Scene: a ground plane + a sphere, lit by a sun, viewed by a pinned camera.
  * Sphere  M_noise:   Noise(scale 5) -> Math(Multiply 2) -> Color Ramp
                       (black -> orange -> white) -> Principled Base Color.
  * Plane   M_checker: Checker -> Mix (with a constant blue) -> Principled Base Color.
View transform is Standard so Cycles and Astroray are compared in the same space.
Nodes are looked up/created by TYPE (localization-safe).
"""
import sys
import bpy  # type: ignore


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    return ap.parse_args(argv)


def _principled(mat):
    return next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")


def build():
    # Clean slate.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    # Ground plane with the Checker -> Mix chain.
    bpy.ops.mesh.primitive_plane_add(size=8.0, location=(0, 0, 0))
    plane = bpy.context.active_object
    plane.name = "Ground"
    mp = bpy.data.materials.new("M_checker")
    mp.use_nodes = True
    nt = mp.node_tree
    checker = nt.nodes.new("ShaderNodeTexChecker")
    checker.inputs["Scale"].default_value = 6.0
    mix = nt.nodes.new("ShaderNodeMixRGB")   # legacy Mix (Fac/Color1/Color2)
    mix.blend_type = "MIX"
    mix.inputs["Fac"].default_value = 0.5
    mix.inputs["Color2"].default_value = (0.05, 0.20, 0.75, 1.0)  # constant blue
    nt.links.new(checker.outputs["Color"], mix.inputs["Color1"])
    nt.links.new(mix.outputs["Color"], _principled(mp).inputs["Base Color"])
    plane.data.materials.append(mp)

    # Sphere with the Noise -> Math -> Color Ramp chain.
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, location=(0, 0, 1.0))
    sphere = bpy.context.active_object
    sphere.name = "Ball"
    bpy.ops.object.shade_smooth()
    ms = bpy.data.materials.new("M_noise")
    ms.use_nodes = True
    nt = ms.node_tree
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 5.0
    math = nt.nodes.new("ShaderNodeMath")
    math.operation = "MULTIPLY"
    math.inputs[1].default_value = 2.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    el = ramp.color_ramp.elements
    el[0].position = 0.0
    el[0].color = (0.0, 0.0, 0.0, 1.0)          # black
    mid = ramp.color_ramp.elements.new(0.5)
    mid.color = (1.0, 0.45, 0.0, 1.0)            # orange
    el[-1].position = 1.0
    el[-1].color = (1.0, 1.0, 1.0, 1.0)          # white
    nt.links.new(noise.outputs["Fac"], math.inputs[0])
    nt.links.new(math.outputs["Value"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], _principled(ms).inputs["Base Color"])
    sphere.data.materials.append(ms)

    # Sun + camera (pinned).
    light = bpy.data.lights.new("Sun", type="SUN")
    light.energy = 4.0
    lo = bpy.data.objects.new("Sun", light)
    scene.collection.objects.link(lo)
    lo.location = (4, -4, 8)
    lo.rotation_euler = (0.5, 0.2, 0.3)

    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = (6.0, -6.0, 4.2)
    # Aim at the sphere centre (0,0,1).
    import mathutils
    direction = mathutils.Vector((0, 0, 1.0)) - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam

    # Render defaults: modest resolution, Standard view transform (like-for-like).
    scene.render.resolution_x = 480
    scene.render.resolution_y = 360
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Standard"
    scene.render.image_settings.file_format = "PNG"

    # World: a mid-grey so the objects read against a neutral background.
    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = (0.18, 0.18, 0.18, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    scene.world = world

    out = _args().out
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"issue818: wrote scene {out}")


build()

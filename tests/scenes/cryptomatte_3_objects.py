# Cryptomatte 3-object acceptance scene (pkg87c)
# Three named cubes with three named materials on a named floor.
# 256x256, depth 6, 64 spp

import bpy

def setup():
    # Clear existing scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    # Create materials
    mat_red = bpy.data.materials.new(name="mat_red")
    mat_red.use_nodes = True
    mat_red.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.8, 0.05, 0.05, 1.0)

    mat_green = bpy.data.materials.new(name="mat_green")
    mat_green.use_nodes = True
    mat_green.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.05, 0.8, 0.05, 1.0)

    mat_blue = bpy.data.materials.new(name="mat_blue")
    mat_blue.use_nodes = True
    mat_blue.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.05, 0.05, 0.8, 1.0)

    mat_floor = bpy.data.materials.new(name="mat_floor")
    mat_floor.use_nodes = True
    mat_floor.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.7, 0.7, 0.7, 1.0)

    # Create cubes
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-2, 0, 0.5))
    cube_red = bpy.context.active_object
    cube_red.name = "cube_red"
    cube_red.data.materials.append(mat_red)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.5))
    cube_green = bpy.context.active_object
    cube_green.name = "cube_green"
    cube_green.data.materials.append(mat_green)

    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(2, 0, 0.5))
    cube_blue = bpy.context.active_object
    cube_blue.name = "cube_blue"
    cube_blue.data.materials.append(mat_blue)

    # Create floor
    bpy.ops.mesh.primitive_plane_add(size=10.0, location=(0, 0, 0))
    floor = bpy.context.active_object
    floor.name = "floor"
    floor.data.materials.append(mat_floor)

    # Create camera
    bpy.ops.object.camera_add(location=(0, -8, 3))
    camera = bpy.context.active_object
    camera.data.lens = 35
    camera.rotation_euler = (1.2, 0, 0)
    bpy.context.scene.camera = camera

    # Create light
    bpy.ops.object.light_add(type='SUN', location=(5, -5, 10))
    light = bpy.context.active_object
    light.data.energy = 2.0

    # Render settings
    scene = bpy.context.scene
    scene.render.engine = 'CUSTOM_RAYTRACER'
    scene.render.resolution_x = 256
    scene.render.resolution_y = 256
    scene.astroray.samples = 64
    scene.astroray.cryptomatte_depth = '6'

    # Enable Cryptomatte passes
    scene.view_layers[0].use_pass_cryptomatte_object = True
    scene.view_layers[0].use_pass_cryptomatte_material = True

    print("Cryptomatte 3-object scene ready")

if __name__ == "__main__":
    setup()

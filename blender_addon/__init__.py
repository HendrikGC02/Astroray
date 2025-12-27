bl_info = {
    "name": "Custom Raytracer",
    "author": "Your Name",
    "version": (2, 0, 0),
    "blender": (4, 5, 0),
    "location": "Render > Engine > Custom Raytracer",
    "description": "Custom CPU raytracer render engine",
    "category": "Render",
}

import bpy
import mathutils
import math
import numpy as np
import traceback
import sys
import os

# Add the path to your C++ extension
addon_dir = os.path.dirname(__file__)
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

try:
    import raytracer_blender
    RAYTRACER_AVAILABLE = True
    print("Raytracer module loaded successfully")
except ImportError as e:
    RAYTRACER_AVAILABLE = False
    print(f"Failed to load raytracer module: {e}")


class CustomRaytracerRenderEngine(bpy.types.RenderEngine):
    bl_idname = "CUSTOM_RAYTRACER"
    bl_label = "Custom Raytracer"
    bl_use_preview = True
    bl_use_postprocess = True
    
    def render(self, depsgraph):
        """Main F12 render"""
        if not RAYTRACER_AVAILABLE:
            self.report({'ERROR'}, "Raytracer module not available")
            return
        
        scene = depsgraph.scene
        scale = scene.render.resolution_percentage / 100.0
        width = int(scene.render.resolution_x * scale)
        height = int(scene.render.resolution_y * scale)
        
        print("=" * 60)
        print(f"RENDER STARTED: {width}x{height}")
        
        try:
            renderer = raytracer_blender.Renderer()
            print("Renderer created")
            
            self.convert_scene(depsgraph, renderer, width, height)
            print("Scene converted")
            
            samples = getattr(scene.cycles, 'samples', 64) if hasattr(scene, 'cycles') else 64
            max_depth = getattr(scene.cycles, 'max_bounces', 8) if hasattr(scene, 'cycles') else 8
            
            print(f"Rendering with {samples} samples, {max_depth} bounces")
            pixels = renderer.render(samples, max_depth)
            
            # Debug pixel data
            print(f"Pixels type: {type(pixels)}")
            print(f"Pixels shape: {pixels.shape if hasattr(pixels, 'shape') else 'N/A'}")
            print(f"Pixels dtype: {pixels.dtype if hasattr(pixels, 'dtype') else 'N/A'}")
            print(f"Pixels min/max: {np.min(pixels):.3f}/{np.max(pixels):.3f}")
            
            self.write_pixels(pixels, width, height)
            print("RENDER COMPLETE")
            print("=" * 60)
            
        except Exception as e:
            print(f"RENDER ERROR: {e}")
            self.report({'ERROR'}, str(e))
            traceback.print_exc()
    
    def view_update(self, context, depsgraph):
        """Called when viewport needs updating"""
        pass
    
    def view_draw(self, context, depsgraph):
        """Draw viewport render - Blender 4.x compatible"""
        if not RAYTRACER_AVAILABLE:
            return
        
        try:
            region = context.region
            width = region.width
            height = region.height
            
            # Skip if viewport is too small
            if width < 10 or height < 10:
                return
            
            # Create temporary renderer for viewport
            renderer = raytracer_blender.Renderer()
            self.convert_scene(depsgraph, renderer, width, height)
            
            # Get viewport quality settings from Cycles
            scene = depsgraph.scene
            # Use viewport_samples if available, otherwise use a fraction of render samples
            if hasattr(scene.cycles, 'preview_samples'):
                samples = scene.cycles.preview_samples
            elif hasattr(scene.cycles, 'samples'):
                samples = max(1, scene.cycles.samples // 4)  # Use 1/4 of render samples
            else:
                samples = 8
            
            # Use same max_bounces as render, or default
            max_depth = getattr(scene.cycles, 'max_bounces', 5) if hasattr(scene, 'cycles') else 5
            
            pixels = renderer.render(samples, max_depth)
            
            if pixels is None:
                return
            
            # Prepare RGBA data
            rgba = np.ones((height, width, 4), dtype=np.float32)
            rgba[:, :, :3] = pixels
            
            # DON'T flip Y - the renderer already outputs in the correct orientation
            # The issue was that we were flipping when we shouldn't
            
            # Draw to viewport
            self.bind_display_space_shader(context.scene)
            
            try:
                import gpu
                from gpu_extras.presets import draw_texture_2d
                
                # Convert numpy array to GPU buffer
                # Flatten the array and convert to buffer
                buffer = gpu.types.Buffer('FLOAT', width * height * 4, rgba.flatten())
                
                # Create texture from buffer
                texture = gpu.types.GPUTexture((width, height), format='RGBA32F', data=buffer)
                
                # Draw the texture at (0, 0)
                draw_texture_2d(texture, (0, 0), width, height)
                
            except Exception as e:
                print(f"GPU draw error: {e}")
                traceback.print_exc()
            
            self.unbind_display_space_shader()
            
        except Exception as e:
            print(f"Viewport render error: {e}")
            traceback.print_exc()
    
    def convert_scene(self, depsgraph, renderer, width, height):
        """Convert Blender scene to raytracer format"""
        scene = depsgraph.scene
        
        # Clear previous scene
        renderer.clear()
        
        # Setup camera FIRST
        self.setup_camera(scene, renderer, width, height)
        
        # Convert lights
        self.convert_lights(depsgraph, renderer)
        
        # Convert objects
        self.convert_objects(depsgraph, renderer)
        
        # Setup world/environment
        self.setup_world(scene, renderer)
    
    def setup_camera(self, scene, renderer, width, height):
        """Setup camera"""
        camera_obj = scene.camera
        if not camera_obj:
            print("WARNING: No camera in scene, using default")
            look_from = [0, 5, 5]
            look_at = [0, 0, 0]
            vup = [0, 0, 1]
            vfov = 45
        else:
            # Get camera transform
            matrix = camera_obj.matrix_world
            look_from = list(matrix.translation)
            
            # Calculate look_at direction - camera looks down -Z axis
            forward = matrix.to_3x3() @ mathutils.Vector((0, 0, -1))
            look_at = [
                look_from[0] + forward.x,
                look_from[1] + forward.y,
                look_from[2] + forward.z
            ]
            
            # Up vector - camera's local Y axis transformed to world space
            # This fixes the upside-down issue
            up = matrix.to_3x3() @ mathutils.Vector((0, 1, 0))
            vup = [up.x, up.y, up.z]
            
            # Field of view
            if camera_obj.data.type == 'PERSP':
                vfov = math.degrees(camera_obj.data.angle)
            else:
                vfov = 40.0
        
        aspect_ratio = width / height
        aperture = 0.0
        focus_dist = 10.0
        
        renderer.setup_camera(look_from, look_at, vup, vfov, aspect_ratio, 
                             aperture, focus_dist, width, height)
    
    def convert_lights(self, depsgraph, renderer):
        """Convert lights"""
        light_count = 0
        for obj in depsgraph.objects:
            if obj.type != 'LIGHT':
                continue
            
            light = obj.data
            matrix = obj.matrix_world
            position = list(matrix.translation)
            color = list(light.color)
            energy = light.energy
            
            if light.type == 'POINT':
                renderer.add_sphere(position, 0.1, "light", color, energy)
            elif light.type == 'SUN':
                direction = matrix.to_3x3() @ mathutils.Vector((0, 0, -1))
                direction.normalize()
                distance = 1000.0
                sun_pos = [
                    position[0] - direction.x * distance,
                    position[1] - direction.y * distance,
                    position[2] - direction.z * distance
                ]
                renderer.add_sphere(sun_pos, 100.0, "light", color, energy)
            elif light.type == 'AREA':
                size = max(light.size, getattr(light, 'size_y', light.size))
                renderer.add_sphere(position, size / 2, "light", color, energy)
            else:
                renderer.add_sphere(position, 0.1, "light", color, energy)
            
            light_count += 1
        
        # If no lights, add a default light
        if light_count == 0:
            renderer.add_sphere([5, 5, 5], 1.0, "light", [1.0, 1.0, 1.0], 10.0)
    
    def convert_objects(self, depsgraph, renderer):
        """Convert mesh objects"""
        for obj_instance in depsgraph.object_instances:
            obj = obj_instance.object
            
            if obj.type != 'MESH':
                continue
            
            obj_eval = obj.evaluated_get(depsgraph)
            mesh = obj_eval.data
            matrix = obj_instance.matrix_world
            
            mat_type, color, param = self.get_material(obj)
            
            mesh.calc_loop_triangles()
            for tri in mesh.loop_triangles:
                v0 = matrix @ mesh.vertices[tri.vertices[0]].co
                v1 = matrix @ mesh.vertices[tri.vertices[1]].co
                v2 = matrix @ mesh.vertices[tri.vertices[2]].co
                
                renderer.add_triangle(
                    list(v0), list(v1), list(v2),
                    mat_type, color, param
                )
    
    def setup_world(self, scene, renderer):
        """Setup background"""
        world = scene.world
        if not world or not world.use_nodes:
            # Add a default environment light
            renderer.add_sphere([0, 0, 100.0], 20.0, "light", [0.5, 0.7, 1.0], 0.5)
            return
        
        bg_color = [0.05, 0.05, 0.05]
        bg_strength = 1.0
        
        for node in world.node_tree.nodes:
            if node.type == 'BACKGROUND':
                bg_color = list(node.inputs['Color'].default_value[:3])
                bg_strength = node.inputs['Strength'].default_value
                break
        
        if bg_strength > 0.01:
            renderer.add_sphere(
                [0, 0, 100.0], 20.0,
                "light", bg_color, bg_strength * 2.0
            )
    
    def get_material(self, obj):
        """Extract material"""
        if not obj.material_slots or not obj.material_slots[0].material:
            return "diffuse", [0.8, 0.8, 0.8], 0.5
        
        mat = obj.material_slots[0].material
        
        if not mat.use_nodes:
            return "diffuse", list(mat.diffuse_color[:3]), 0.5
        
        output_node = None
        for node in mat.node_tree.nodes:
            if node.type == 'OUTPUT_MATERIAL':
                output_node = node
                break
        
        if not output_node:
            return "diffuse", [0.8, 0.8, 0.5], 0.5
        
        surface_input = output_node.inputs.get('Surface')
        if not surface_input or not surface_input.is_linked:
            return "diffuse", [0.8, 0.8, 0.5], 0.5
        
        surface_node = surface_input.links[0].from_node
        
        if surface_node.type == 'EMISSION':
            color = list(surface_node.inputs['Color'].default_value[:3])
            strength = surface_node.inputs['Strength'].default_value
            return "light", color, strength
        
        if surface_node.type == 'BSDF_PRINCIPLED':
            base_color = list(surface_node.inputs['Base Color'].default_value[:3])
            metallic = surface_node.inputs['Metallic'].default_value
            roughness = surface_node.inputs['Roughness'].default_value
            
            transmission_weight = surface_node.inputs.get('Transmission Weight')
            transmission = surface_node.inputs.get('Transmission')
            
            transmission_value = 0.0
            if transmission_weight:
                transmission_value = transmission_weight.default_value
            elif transmission:
                transmission_value = transmission.default_value
            
            if transmission_value > 0.1:
                ior = surface_node.inputs.get('IOR')
                return "glass", [1.0, 1.0, 1.0], ior.default_value if ior else 1.45
            
            if metallic > 0.5:
                return "metal", base_color, roughness
            
            return "diffuse", base_color, roughness
        
        if surface_node.type == 'BSDF_GLASS':
            ior = surface_node.inputs['IOR'].default_value
            return "glass", [1.0, 1.0, 1.0], ior
        
        if surface_node.type in ('BSDF_GLOSSY', 'BSDF_ANISOTROPIC'):
            color = list(surface_node.inputs['Color'].default_value[:3])
            roughness = surface_node.inputs['Roughness'].default_value
            return "metal", color, roughness
        
        return "diffuse", [0.8, 0.8, 0.5], 0.5
    
    def write_pixels(self, pixels, width, height):
        """Write pixels to Blender's render result"""
        # Convert to RGBA
        rgba = np.ones((height, width, 4), dtype=np.float32)
        rgba[:, :, :3] = pixels
        
        # Convert to list of RGBA pixels
        pixel_list = rgba.reshape(-1, 4).tolist()
        
        # Write to render result
        result = self.begin_result(0, 0, width, height)
        layer = result.layers[0]
        render_pass = layer.passes["Combined"]
        render_pass.rect = pixel_list
        self.end_result(result)


# ============================================================================
# UI PANEL
# ============================================================================

class RENDER_PT_custom_raytracer(bpy.types.Panel):
    bl_label = "Sampling"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"
    bl_options = {'DEFAULT_CLOSED'}
    
    @classmethod
    def poll(cls, context):
        return context.scene.render.engine == 'CUSTOM_RAYTRACER'
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        if hasattr(scene, 'cycles'):
            layout.use_property_split = True
            layout.use_property_decorate = False
            
            col = layout.column(align=True)
            col.prop(scene.cycles, "samples", text="Render")
            col.prop(scene.cycles, "max_bounces", text="Max Bounces")


# ============================================================================
# REGISTRATION
# ============================================================================

def get_panels():
    exclude_panels = {
        'VIEWLAYER_PT_filter',
        'VIEWLAYER_PT_layer_passes',
    }
    
    panels = []
    for panel in bpy.types.Panel.__subclasses__():
        if hasattr(panel, 'COMPAT_ENGINES') and 'CYCLES' in panel.COMPAT_ENGINES:
            if panel.__name__ not in exclude_panels:
                panels.append(panel)
    
    return panels


def register():
    bpy.utils.register_class(CustomRaytracerRenderEngine)
    bpy.utils.register_class(RENDER_PT_custom_raytracer)
    
    for panel in get_panels():
        panel.COMPAT_ENGINES.add('CUSTOM_RAYTRACER')


def unregister():
    for panel in get_panels():
        if 'CUSTOM_RAYTRACER' in panel.COMPAT_ENGINES:
            panel.COMPAT_ENGINES.remove('CUSTOM_RAYTRACER')
    
    bpy.utils.unregister_class(RENDER_PT_custom_raytracer)
    bpy.utils.unregister_class(CustomRaytracerRenderEngine)


if __name__ == "__main__":
    register()
bl_info = {
    "name": "Custom Raytracer Pro",
    "author": "Your Name",
    "version": (3, 0, 0),
    "blender": (4, 5, 0),
    "location": "Render Properties > Render Engine > Custom Raytracer",
    "description": "Advanced path tracer with Disney BRDF, NEE, MIS, and adaptive sampling",
    "warning": "",
    "doc_url": "https://github.com/yourusername/custom-raytracer",
    "category": "Render",
}

import bpy
from bpy.types import (
    Panel, Operator, AddonPreferences,
    PropertyGroup, RenderEngine,
    Menu
)
from bpy.props import (
    BoolProperty, IntProperty, FloatProperty,
    StringProperty, EnumProperty, PointerProperty,
    FloatVectorProperty, CollectionProperty
)
import mathutils
import math
import numpy as np
import traceback
import sys
import os
import time
import threading
from pathlib import Path

# Add the addon directory to path
addon_dir = os.path.dirname(__file__)
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

# Try to import the C++ module
try:
    import raytracer_blender
    RAYTRACER_AVAILABLE = True
    print(f"Custom Raytracer {raytracer_blender.__version__} loaded successfully")
    print(f"Features: {raytracer_blender.__features__}")
except ImportError as e:
    RAYTRACER_AVAILABLE = False
    print(f"Failed to load raytracer module: {e}")

# ============================================================================
# PROPERTY GROUPS
# ============================================================================

class CustomRaytracerRenderSettings(PropertyGroup):
    """Render settings for Custom Raytracer"""
    
    samples: IntProperty(
        name="Samples",
        description="Maximum number of samples per pixel",
        min=1,
        max=65536,
        default=128,
        subtype='UNSIGNED'
    )
    
    preview_samples: IntProperty(
        name="Preview Samples",
        description="Samples for viewport preview",
        min=1,
        max=1024,
        default=32,
        subtype='UNSIGNED'
    )
    
    max_bounces: IntProperty(
        name="Max Bounces",
        description="Maximum ray depth",
        min=0,
        max=1024,
        default=8
    )
    
    use_adaptive_sampling: BoolProperty(
        name="Adaptive Sampling",
        description="Enable adaptive sampling based on pixel variance",
        default=True
    )
    
    adaptive_threshold: FloatProperty(
        name="Noise Threshold",
        description="Adaptive sampling noise threshold",
        min=0.001,
        max=1.0,
        default=0.01,
        precision=4
    )
    
    use_russian_roulette: BoolProperty(
        name="Russian Roulette",
       
        default=True
    )
    
    rr_start_depth: IntProperty(
        name="RR Start Depth",
        description="Start depth for Russian roulette",
        min=1,
        max=100,
        default=3
    )
    
    clamp_indirect: FloatProperty(
        name="Clamp Indirect",
        description="Clamp indirect light contribution to reduce fireflies",
        min=0.0,
        max=100.0,
        default=10.0
    )
    
    use_nee: BoolProperty(
        name="Next Event Estimation",
        description="Use next event estimation for direct lighting",
        default=True
    )
    
    use_mis: BoolProperty(
        name="Multiple Importance Sampling",
        description="Use MIS for combining sampling strategies",
        default=True
    )

class CustomRaytracerWorldSettings(PropertyGroup):
    """World settings for Custom Raytracer"""
    
    hdri_path: StringProperty(
        name="HDRI",
        description="Path to HDRI environment map",
        subtype='FILE_PATH'
    )
    
    hdri_rotation: FloatProperty(
        name="HDRI Rotation",
        description="Rotate environment map",
        min=0,
        max=2*math.pi,
        default=0,
        subtype='ANGLE'
    )
    
    hdri_intensity: FloatProperty(
        name="HDRI Intensity",
        description="Environment light intensity",
        min=0,
        max=100,
        default=1
    )
    
    use_sun: BoolProperty(
        name="Use Sun",
        description="Add sun light to environment",
        default=False
    )
    
    sun_direction: FloatVectorProperty(
        name="Sun Direction",
        description="Direction of sun light",
        size=3,
        default=(0.0, 0.0, -1.0),
        subtype='DIRECTION'
    )
    
    sun_intensity: FloatProperty(
        name="Sun Intensity",
        description="Sun light intensity",
        min=0,
        max=100,
        default=5
    )
    
    sun_color: FloatVectorProperty(
        name="Sun Color",
        description="Sun light color",
        size=3,
        min=0,
        max=1,
        default=(1.0, 0.95, 0.8),
        subtype='COLOR'
    )

class CustomRaytracerMaterialSettings(PropertyGroup):
    """Material settings for Disney BRDF"""
    
    use_disney: BoolProperty(
        name="Use Disney BRDF",
        description="Use full Disney principled BRDF",
        default=True
    )
    
    # Disney BRDF parameters
    metallic: FloatProperty(
        name="Metallic",
        description="Metallic vs dielectric",
        min=0, max=1, default=0
    )
    
    roughness: FloatProperty(
        name="Roughness",
        description="Surface roughness",
        min=0, max=1, default=0.5
    )
    
    anisotropic: FloatProperty(
        name="Anisotropic",
        description="Anisotropic reflection",
        min=0, max=1, default=0
    )
    
    anisotropic_rotation: FloatProperty(
        name="Anisotropic Rotation",
        description="Rotation of anisotropic reflection",
        min=0, max=1, default=0
    )
    
    clearcoat: FloatProperty(
        name="Clearcoat",
        description="Clearcoat layer",
        min=0, max=1, default=0
    )
    
    clearcoat_gloss: FloatProperty(
        name="Clearcoat Gloss",
        description="Clearcoat glossiness",
        min=0, max=1, default=1
    )
    
    transmission: FloatProperty(
        name="Transmission",
        description="Transmission/refraction",
        min=0, max=1, default=0
    )
    
    ior: FloatProperty(
        name="IOR",
        description="Index of refraction",
        min=1, max=3, default=1.45
    )
    
    subsurface: FloatProperty(
        name="Subsurface",
        description="Subsurface scattering",
        min=0, max=1, default=0
    )
    
    subsurface_radius: FloatVectorProperty(
        name="Subsurface Radius",
        description="Subsurface scattering radius",
        size=3,
        min=0,
        max=100,
        default=(1.0, 0.2, 0.1),
        subtype='COLOR'
    )
    
    sheen: FloatProperty(
        name="Sheen",
        description="Sheen for cloth-like materials",
        min=0, max=1, default=0
    )
    
    sheen_tint: FloatProperty(
        name="Sheen Tint",
        description="Sheen color tint",
        min=0, max=1, default=0.5
    )
    
    specular: FloatProperty(
        name="Specular",
        description="Specular reflection amount",
        min=0, max=1, default=0.5
    )
    
    specular_tint: FloatProperty(
        name="Specular Tint",
        description="Specular color tint",
        min=0, max=1, default=0
    )

# ============================================================================
# RENDER ENGINE
# ============================================================================

class CustomRaytracerRenderEngine(RenderEngine):
    bl_idname = "CUSTOM_RAYTRACER"
    bl_label = "Custom Raytracer"
    bl_use_preview = True
    bl_use_postprocess = True
    bl_use_shading_nodes_custom = False
    
    # Supported features
    bl_use_spherical_stereo = False
    bl_use_stereo_viewport = False
    
    # Remove __init__ and __del__ completely - let Blender handle lifecycle
    # Don't store any instance state that could cause issues
    
    # Main render entry point
    def render(self, depsgraph):
        """Main F12 render"""
        if not RAYTRACER_AVAILABLE:
            self.report({'ERROR'}, "Raytracer module not available")
            return
        
        scene = depsgraph.scene
        scale = scene.render.resolution_percentage / 100.0
        width = int(scene.render.resolution_x * scale)
        height = int(scene.render.resolution_y * scale)
        
        # Get render settings
        settings = scene.custom_raytracer
        
        print("=" * 60)
        print(f"Custom Raytracer Render: {width}x{height}")
        print(f"Samples: {settings.samples}, Max Bounces: {settings.max_bounces}")
        print(f"NEE: {settings.use_nee}, MIS: {settings.use_mis}")
        print(f"Adaptive: {settings.use_adaptive_sampling}")
        
        # Create renderer locally - don't store as instance variable
        renderer = None
        
        try:
            # Create renderer fresh each time (avoid memory issues)
            renderer = raytracer_blender.Renderer()
            renderer.set_adaptive_sampling(settings.use_adaptive_sampling)
            
            # Convert scene
            self.convert_scene(depsgraph, renderer, width, height)
            
            # Progress callback
            def progress_callback(value):
                if self.test_break():
                    return False  # Signal to stop
                self.update_progress(value)
                return True  # Continue rendering
            
            # Render
            start_time = time.time()
            pixels = renderer.render(
                settings.samples,
                settings.max_bounces,
                progress_callback
            )
            
            render_time = time.time() - start_time
            print(f"Render completed in {render_time:.2f} seconds")
            
            # Write pixels
            if pixels is not None:
                self.write_pixels(pixels, width, height)
            
        except Exception as e:
            print(f"RENDER ERROR: {e}")
            self.report({'ERROR'}, str(e))
            traceback.print_exc()
        finally:
            # Clean up renderer
            if renderer:
                try:
                    renderer.clear()
                except:
                    pass
            del renderer
    
    # Viewport render
    def view_update(self, context, depsgraph):
        """Called when viewport needs updating"""
        region = context.region
        view3d = context.space_data
        scene = depsgraph.scene
        
        # Check if we should render
        if not self.is_viewport_render_enabled(context):
            return
    
    def view_draw(self, context, depsgraph):
        """Draw viewport render"""
        if not RAYTRACER_AVAILABLE:
            return
        
        region = context.region
        scene = depsgraph.scene
        settings = scene.custom_raytracer
        
        # Skip if viewport is too small
        if region.width < 10 or region.height < 10:
            return
        
        try:
            # Create temporary renderer for viewport
            renderer = raytracer_blender.Renderer()
            renderer.set_adaptive_sampling(False)  # Disable for viewport
            
            self.convert_scene(depsgraph, renderer, region.width, region.height)
            
            # Use preview samples for viewport
            samples = settings.preview_samples
            max_depth = min(settings.max_bounces, 5)  # Limit depth for speed
            
            pixels = renderer.render(samples, max_depth)
            
            if pixels is None:
                return
            
            # Draw to viewport
            self.bind_display_space_shader(scene)
            self.draw_pixels(pixels, region.width, region.height)
            self.unbind_display_space_shader()
            
        except Exception as e:
            print(f"Viewport render error: {e}")
    
    def draw_pixels(self, pixels, width, height):
        """Draw pixels to viewport using GPU module (Blender 4.x compatible)"""
        try:
            import gpu
            from gpu_extras.batch import batch_for_shader
            
            # Prepare RGBA data
            rgba = np.ones((height, width, 4), dtype=np.float32)
            rgba[:, :, :3] = pixels
            
            # For Blender 4.x, we need to use the newer GPU API
            # Create vertices for a full-screen quad
            vertices = [
                (0, 0), (width, 0),
                (width, height), (0, height)
            ]
            
            # Get the built-in shader
            shader = gpu.shader.from_builtin('IMAGE')
            
            # Create batch
            batch = batch_for_shader(
                shader, 'TRI_FAN',
                {"pos": vertices, "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1)]}
            )
            
            # Create texture from buffer
            texture = gpu.types.GPUTexture((width, height), format='RGBA32F')
            
            # Upload pixel data
            buffer = gpu.types.Buffer('FLOAT', width * height * 4, rgba.flatten())
            texture.write(buffer)
            
            # Draw
            shader.bind()
            shader.uniform_sampler("image", texture)
            batch.draw(shader)
            
            # Cleanup
            del texture
            del buffer
            
        except Exception as e:
            print(f"GPU drawing error: {e}")
            # Fallback to simpler method if available
            try:
                import gpu
                from gpu_extras.presets import draw_texture_2d
                
                rgba = np.ones((height, width, 4), dtype=np.float32)
                rgba[:, :, :3] = pixels
                
                buffer = gpu.types.Buffer('FLOAT', width * height * 4, rgba.flatten())
                texture = gpu.types.GPUTexture((width, height), format='RGBA32F', data=buffer)
                
                draw_texture_2d(texture, (0, 0), width, height)
            except:
                print("Unable to draw viewport preview")
    
    # Scene conversion
    def convert_scene(self, depsgraph, renderer, width, height):
        """Convert Blender scene to raytracer format"""
        scene = depsgraph.scene
        settings = scene.custom_raytracer
        
        # Clear previous scene
        renderer.clear()
        
        # Setup camera
        self.setup_camera(scene, renderer, width, height)
        
        # Convert materials first
        material_map = self.convert_materials(depsgraph, renderer)
        
        # Convert objects
        self.convert_objects(depsgraph, renderer, material_map)
        
        # Convert lights
        self.convert_lights(depsgraph, renderer)
        
        # Setup world
        self.setup_world(scene, renderer)
    
    def setup_camera(self, scene, renderer, width, height):
        """Setup camera from Blender camera"""
        camera_obj = scene.camera
        if not camera_obj:
            print("WARNING: No camera in scene")
            return
        
        # Get camera transform
        matrix = camera_obj.matrix_world
        look_from = list(matrix.translation)
        
        # Camera looks down -Z axis
        forward = matrix.to_3x3() @ mathutils.Vector((0, 0, -1))
        look_at = [
            look_from[0] + forward.x,
            look_from[1] + forward.y,
            look_from[2] + forward.z
        ]
        
        # Up vector
        up = matrix.to_3x3() @ mathutils.Vector((0, 1, 0))
        vup = [up.x, up.y, up.z]
        
        # Field of view
        camera = camera_obj.data
        if camera.type == 'PERSP':
            if camera.lens_unit == 'FOV':
                vfov = math.degrees(camera.angle)
            else:
                # Calculate from focal length
                sensor_height = camera.sensor_height
                focal_length = camera.lens
                vfov = 2 * math.degrees(math.atan(sensor_height / (2 * focal_length)))
        else:
            vfov = 40.0
        
        # DOF settings
        aperture = 0.0
        focus_dist = 10.0
        if camera.dof.use_dof:
            aperture = 1.0 / (2 * camera.dof.aperture_fstop) if camera.dof.aperture_fstop > 0 else 0
            if camera.dof.focus_object:
                focus_point = camera.dof.focus_object.location
                focus_dist = (mathutils.Vector(look_from) - focus_point).length
            else:
                focus_dist = camera.dof.focus_distance
        
        aspect_ratio = width / height
        
        renderer.setup_camera(
            look_from, look_at, vup, vfov, aspect_ratio,
            aperture, focus_dist, width, height
        )
    
    def convert_materials(self, depsgraph, renderer):
        """Convert Blender materials to raytracer materials"""
        material_map = {}
        
        for mat in bpy.data.materials:
            if not mat.use_nodes:
                # Simple material
                color = list(mat.diffuse_color[:3])
                params = {
                    'roughness': mat.roughness,
                    'metallic': mat.metallic
                }
                mat_id = renderer.create_material('disney', color, params)
            else:
                # Node-based material
                mat_id = self.convert_node_material(mat, renderer)
            
            material_map[mat.name] = mat_id
        
        return material_map
    
    def convert_node_material(self, mat, renderer):
        """Convert node-based material"""
        # Find output node
        output_node = None
        for node in mat.node_tree.nodes:
            if node.type == 'OUTPUT_MATERIAL':
                output_node = node
                break
        
        if not output_node:
            return renderer.create_material('disney', [0.8, 0.8, 0.8], {})
        
        # Get surface shader
        surface_input = output_node.inputs.get('Surface')
        if not surface_input or not surface_input.is_linked:
            return renderer.create_material('disney', [0.8, 0.8, 0.8], {})
        
        surface_node = surface_input.links[0].from_node
        
        # Convert based on shader type
        if surface_node.type == 'BSDF_PRINCIPLED':
            return self.convert_principled_bsdf(surface_node, renderer)
        elif surface_node.type == 'EMISSION':
            color = list(surface_node.inputs['Color'].default_value[:3])
            strength = surface_node.inputs['Strength'].default_value
            return renderer.create_material('light', color, {'intensity': strength})
        elif surface_node.type == 'BSDF_GLASS':
            ior = surface_node.inputs['IOR'].default_value
            return renderer.create_material('glass', [1, 1, 1], {'ior': ior})
        else:
            # Default material
            return renderer.create_material('disney', [0.8, 0.8, 0.8], {})
    
    def convert_principled_bsdf(self, node, renderer):
        """Convert Principled BSDF to Disney BRDF"""
        # Get all inputs
        def get_value(name, default=0):
            input = node.inputs.get(name)
            if input:
                if input.is_linked:
                    # TODO: Handle textures
                    return default
                return input.default_value
            return default
        
        base_color = list(get_value('Base Color', [0.8, 0.8, 0.8])[:3])
        
        params = {
            'metallic': get_value('Metallic', 0),
            'roughness': get_value('Roughness', 0.5),
            'ior': get_value('IOR', 1.45),
            'transmission': get_value('Transmission', 0),
            'clearcoat': get_value('Coat Weight', 0),
            'clearcoat_gloss': 1.0 - get_value('Coat Roughness', 0),
            'anisotropic': get_value('Anisotropic', 0),
            'anisotropic_rotation': get_value('Anisotropic Rotation', 0),
            'sheen': get_value('Sheen Weight', 0),
            'sheen_tint': get_value('Sheen Tint', 0.5),
            'subsurface': get_value('Subsurface Weight', 0)
        }
        
        # Check for emission
        emission_color = get_value('Emission Color', [0, 0, 0])
        emission_strength = get_value('Emission Strength', 0)
        
        if emission_strength > 0 and any(c > 0 for c in emission_color[:3]):
            params['intensity'] = emission_strength
            return renderer.create_material('light', list(emission_color[:3]), params)
        
        return renderer.create_material('disney', base_color, params)
    
    def convert_objects(self, depsgraph, renderer, material_map):
        """Convert mesh objects"""
        for obj_instance in depsgraph.object_instances:
            obj = obj_instance.object
            
            if obj.type != 'MESH':
                continue
            
            # Skip hidden objects
            if not obj.visible_get():
                continue
            
            obj_eval = obj.evaluated_get(depsgraph)
            mesh = obj_eval.data
            matrix = obj_instance.matrix_world
            
            # Get material
            mat_id = 0
            if obj.material_slots:
                mat = obj.material_slots[0].material
                if mat and mat.name in material_map:
                    mat_id = material_map[mat.name]
            
            # Convert triangles
            mesh.calc_loop_triangles()
            for tri in mesh.loop_triangles:
                # Get vertices
                v0 = matrix @ mesh.vertices[tri.vertices[0]].co
                v1 = matrix @ mesh.vertices[tri.vertices[1]].co
                v2 = matrix @ mesh.vertices[tri.vertices[2]].co
                
                # Get UVs if available
                uv0 = uv1 = uv2 = []
                if mesh.uv_layers.active:
                    uv_layer = mesh.uv_layers.active.data
                    uv0 = list(uv_layer[tri.loops[0]].uv)
                    uv1 = list(uv_layer[tri.loops[1]].uv)
                    uv2 = list(uv_layer[tri.loops[2]].uv)
                
                renderer.add_triangle(
                    list(v0), list(v1), list(v2),
                    mat_id, uv0, uv1, uv2
                )
    
    def convert_lights(self, depsgraph, renderer):
        """Convert lights"""
        for obj in depsgraph.objects:
            if obj.type != 'LIGHT':
                continue
            
            light = obj.data
            matrix = obj.matrix_world
            position = list(matrix.translation)
            color = list(light.color)
            energy = light.energy
            
            # Create emissive material for light
            mat_id = renderer.create_material('light', color, {'intensity': energy})
            
            if light.type == 'POINT':
                renderer.add_sphere(position, 0.1, mat_id)
            elif light.type == 'SUN':
                # Distant light - place far away
                direction = matrix.to_3x3() @ mathutils.Vector((0, 0, -1))
                sun_pos = [
                    position[0] - direction.x * 1000,
                    position[1] - direction.y * 1000,
                    position[2] - direction.z * 1000
                ]
                renderer.add_sphere(sun_pos, 100.0, mat_id)
            elif light.type == 'AREA':
                # Simplified as sphere for now
                size = max(light.size, light.size_y if hasattr(light, 'size_y') else light.size)
                renderer.add_sphere(position, size / 2, mat_id)
    
    def setup_world(self, scene, renderer):
        """Setup world environment"""
        world = scene.world
        if not world:
            return
        
        if world.use_nodes:
            for node in world.node_tree.nodes:
                if node.type == 'BACKGROUND':
                    color = list(node.inputs['Color'].default_value[:3])
                    strength = node.inputs['Strength'].default_value
                    
                    if strength > 0.01:
                        mat_id = renderer.create_material('light', color, {'intensity': strength})
                        # Add environment sphere
                        renderer.add_sphere([0, 0, 0], 500.0, mat_id)
                    break
    
    def write_pixels(self, pixels, width, height):
        """Write pixels to Blender's render result"""
        # Convert to RGBA
        rgba = np.ones((height, width, 4), dtype=np.float32)
        rgba[:, :, :3] = pixels
        
        # Get render result
        result = self.begin_result(0, 0, width, height)
        
        # Get the first layer and pass
        layer = result.layers[0]
        
        # Check available passes
        if "Combined" in layer.passes:
            render_pass = layer.passes["Combined"]
        else:
            # Try to get the first available pass
            render_pass = layer.passes[0] if layer.passes else None
        
        if render_pass:
            # Flatten array and write
            render_pass.rect = rgba.reshape(-1, 4).tolist()
        
        self.end_result(result)
    
    def is_viewport_render_enabled(self, context):
        """Check if viewport rendering should be active"""
        return (
            context.space_data.shading.type == 'RENDERED' and
            context.scene.render.engine == 'CUSTOM_RAYTRACER'
        )

# ============================================================================
# UI PANELS
# ============================================================================

class RENDER_PT_custom_raytracer_sampling(Panel):
    bl_label = "Sampling"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"
    
    @classmethod
    def poll(cls, context):
        return context.scene.render.engine == 'CUSTOM_RAYTRACER'
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        settings = scene.custom_raytracer
        
        layout.use_property_split = True
        layout.use_property_decorate = False
        
        col = layout.column(align=True)
        col.prop(settings, "samples", text="Render")
        col.prop(settings, "preview_samples", text="Viewport")
        
        col.separator()
        
        col.prop(settings, "use_adaptive_sampling")
        if settings.use_adaptive_sampling:
            col.prop(settings, "adaptive_threshold")

class RENDER_PT_custom_raytracer_light_paths(Panel):
    bl_label = "Light Paths"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"
    
    @classmethod
    def poll(cls, context):
        return context.scene.render.engine == 'CUSTOM_RAYTRACER'
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.custom_raytracer
        
        layout.use_property_split = True
        layout.use_property_decorate = False
        
        col = layout.column(align=True)
        col.prop(settings, "max_bounces")
        
        col.separator()
        
        col.prop(settings, "use_russian_roulette")
        if settings.use_russian_roulette:
            col.prop(settings, "rr_start_depth")
        
        col.separator()
        
        col.prop(settings, "clamp_indirect")

class RENDER_PT_custom_raytracer_performance(Panel):
    bl_label = "Performance"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"
    
    @classmethod
    def poll(cls, context):
        return context.scene.render.engine == 'CUSTOM_RAYTRACER'
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.custom_raytracer
        
        layout.use_property_split = True
        layout.use_property_decorate = False
        
        col = layout.column(align=True)
        col.prop(settings, "use_nee")
        col.prop(settings, "use_mis")

class MATERIAL_PT_custom_raytracer_surface(Panel):
    bl_label = "Surface"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"
    
    @classmethod
    def poll(cls, context):
        return (
            context.scene.render.engine == 'CUSTOM_RAYTRACER' and
            context.material is not None
        )
    
    def draw(self, context):
        layout = self.layout
        mat = context.material
        settings = mat.custom_raytracer
        
        layout.use_property_split = True
        layout.use_property_decorate = False
        
        layout.prop(settings, "use_disney")
        
        if settings.use_disney:
            col = layout.column()
            col.prop(settings, "metallic")
            col.prop(settings, "roughness")
            
            col.separator()
            
            col.prop(settings, "transmission")
            if settings.transmission > 0:
                col.prop(settings, "ior")
            
            col.separator()
            
            col.prop(settings, "clearcoat")
            if settings.clearcoat > 0:
                col.prop(settings, "clearcoat_gloss")
            
            col.separator()
            
            col.prop(settings, "anisotropic")
            if settings.anisotropic > 0:
                col.prop(settings, "anisotropic_rotation")

# ============================================================================
# OPERATORS
# ============================================================================

class CUSTOM_RAYTRACER_OT_quick_render(Operator):
    """Quick test render with low samples"""
    bl_idname = "render.custom_raytracer_quick"
    bl_label = "Quick Render"
    
    def execute(self, context):
        scene = context.scene
        settings = scene.custom_raytracer
        
        # Store original settings
        original_samples = settings.samples
        
        # Set quick render settings
        settings.samples = 16
        
        # Render
        bpy.ops.render.render('INVOKE_DEFAULT')
        
        # Restore settings
        settings.samples = original_samples
        
        return {'FINISHED'}

# ============================================================================
# PREFERENCES
# ============================================================================

class CustomRaytracerPreferences(AddonPreferences):
    bl_idname = __name__
    
    debug_mode: BoolProperty(
        name="Debug Mode",
        description="Enable debug output",
        default=False
    )
    
    cache_path: StringProperty(
        name="Cache Path",
        description="Path for caching compiled kernels and textures",
        default="",
        subtype='DIR_PATH'
    )
    
    def draw(self, context):
        layout = self.layout
        
        if RAYTRACER_AVAILABLE:
            layout.label(text=f"Raytracer Version: {raytracer_blender.__version__}", icon='INFO')
            
            # Show features
            box = layout.box()
            box.label(text="Available Features:", icon='CHECKBOX_HLT')
            features = raytracer_blender.__features__
            col = box.column()
            for feature, enabled in features.items():
                icon = 'CHECKBOX_HLT' if enabled else 'CHECKBOX_DEHLT'
                col.label(text=f"  {feature.replace('_', ' ').title()}", icon=icon)
        else:
            layout.label(text="Raytracer module not loaded!", icon='ERROR')
            layout.label(text="Please compile the C++ module")
        
        layout.prop(self, "debug_mode")
        layout.prop(self, "cache_path")

# ============================================================================
# REGISTRATION
# ============================================================================

classes = [
    # Property Groups
    CustomRaytracerRenderSettings,
    CustomRaytracerWorldSettings,
    CustomRaytracerMaterialSettings,
    
    # Render Engine
    CustomRaytracerRenderEngine,
    
    # Panels
    RENDER_PT_custom_raytracer_sampling,
    RENDER_PT_custom_raytracer_light_paths,
    RENDER_PT_custom_raytracer_performance,
    MATERIAL_PT_custom_raytracer_surface,
    
    # Operators
    CUSTOM_RAYTRACER_OT_quick_render,
    
    # Preferences
    CustomRaytracerPreferences,
]

def get_panels():
    """Get compatible panels from Cycles"""
    exclude_panels = {
        'CYCLES_RENDER_PT_sampling',
        'CYCLES_RENDER_PT_light_paths',
        'CYCLES_RENDER_PT_performance',
    }
    
    panels = []
    for panel_cls in Panel.__subclasses__():
        if hasattr(panel_cls, 'COMPAT_ENGINES'):
            if 'CYCLES' in panel_cls.COMPAT_ENGINES:
                if panel_cls.__name__ not in exclude_panels:
                    panels.append(panel_cls)
    
    return panels

def register():
    # Register classes
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Add properties to existing types
    bpy.types.Scene.custom_raytracer = PointerProperty(type=CustomRaytracerRenderSettings)
    bpy.types.World.custom_raytracer = PointerProperty(type=CustomRaytracerWorldSettings)
    bpy.types.Material.custom_raytracer = PointerProperty(type=CustomRaytracerMaterialSettings)
    
    # Add compatibility to Cycles panels
    for panel in get_panels():
        if hasattr(panel, 'COMPAT_ENGINES'):
            panel.COMPAT_ENGINES.add('CUSTOM_RAYTRACER')
    
    print("Custom Raytracer addon registered successfully")

def unregister():
    # Remove from Cycles panels
    for panel in get_panels():
        if hasattr(panel, 'COMPAT_ENGINES'):
            if 'CUSTOM_RAYTRACER' in panel.COMPAT_ENGINES:
                panel.COMPAT_ENGINES.remove('CUSTOM_RAYTRACER')
    
    # Remove properties
    del bpy.types.Scene.custom_raytracer
    del bpy.types.World.custom_raytracer
    del bpy.types.Material.custom_raytracer
    
    # Unregister classes
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    print("Custom Raytracer addon unregistered")

if __name__ == "__main__":
    register()
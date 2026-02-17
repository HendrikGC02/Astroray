bl_info = {
    "name": "Custom Raytracer Pro",
    "author": "Your Name",
    "version": (3, 0, 0),
    "blender": (5, 0, 0),
    "location": "Render Properties > Render Engine > Custom Raytracer",
    "description": "Path tracer with Disney BRDF, NEE, MIS",
    "category": "Render",
}

import bpy
from bpy.types import Panel, Operator, AddonPreferences, PropertyGroup, RenderEngine
from bpy.props import BoolProperty, IntProperty, FloatProperty, StringProperty, PointerProperty, FloatVectorProperty
import mathutils, math, numpy as np, traceback, sys, os, time
from pathlib import Path

addon_dir = os.path.dirname(__file__)
if addon_dir not in sys.path: sys.path.insert(0, addon_dir)

try:
    import raytracer_blender
    RAYTRACER_AVAILABLE = True
    print(f"Custom Raytracer {raytracer_blender.__version__} loaded")
except ImportError as e:
    RAYTRACER_AVAILABLE = False
    print(f"Failed to load raytracer module: {e}")

class CustomRaytracerRenderSettings(PropertyGroup):
    samples: IntProperty(name="Samples", min=1, max=65536, default=128)
    preview_samples: IntProperty(name="Preview Samples", min=1, max=1024, default=32)
    max_bounces: IntProperty(name="Max Bounces", min=0, max=1024, default=8)
    use_adaptive_sampling: BoolProperty(name="Adaptive Sampling", default=True)
    adaptive_threshold: FloatProperty(name="Noise Threshold", min=0.001, max=1.0, default=0.01)
    clamp_indirect: FloatProperty(name="Clamp Indirect", min=0.0, max=100.0, default=10.0)

class CustomRaytracerMaterialSettings(PropertyGroup):
    use_disney: BoolProperty(name="Use Disney BRDF", default=True)
    metallic: FloatProperty(name="Metallic", min=0, max=1, default=0)
    roughness: FloatProperty(name="Roughness", min=0, max=1, default=0.5)
    transmission: FloatProperty(name="Transmission", min=0, max=1, default=0)
    ior: FloatProperty(name="IOR", min=1, max=3, default=1.45)
    clearcoat: FloatProperty(name="Clearcoat", min=0, max=1, default=0)
    clearcoat_gloss: FloatProperty(name="Clearcoat Gloss", min=0, max=1, default=1)

class CustomRaytracerRenderEngine(RenderEngine):
    bl_idname = "CUSTOM_RAYTRACER"
    bl_label = "Custom Raytracer"
    bl_use_preview = True
    bl_use_postprocess = True
    bl_use_shading_nodes_custom = False
    
    def render(self, depsgraph):
        if not RAYTRACER_AVAILABLE:
            self.report({'ERROR'}, "Raytracer module not available")
            return
        scene = depsgraph.scene
        scale = scene.render.resolution_percentage / 100.0
        width = int(scene.render.resolution_x * scale)
        height = int(scene.render.resolution_y * scale)
        settings = scene.custom_raytracer
        
        print(f"Rendering {width}x{height}, {settings.samples} samples")
        renderer = None
        try:
            renderer = raytracer_blender.Renderer()
            renderer.set_adaptive_sampling(settings.use_adaptive_sampling)
            self.convert_scene(depsgraph, renderer, width, height)
            
            def progress_callback(value):
                if self.test_break(): return False
                self.update_progress(value)
                return True
            
            start_time = time.time()
            pixels = renderer.render(settings.samples, settings.max_bounces, progress_callback)
            print(f"Render completed in {time.time() - start_time:.2f}s")
            
            if pixels is not None: self.write_pixels(pixels, width, height)
        except Exception as e:
            print(f"RENDER ERROR: {e}")
            traceback.print_exc()
        finally:
            if renderer:
                try: renderer.clear()
                except: pass
            del renderer
    
    def convert_scene(self, depsgraph, renderer, width, height):
        scene = depsgraph.scene
        renderer.clear()
        self.setup_camera(scene, renderer, width, height)
        material_map = self.convert_materials(depsgraph, renderer)
        self.convert_objects(depsgraph, renderer, material_map)
        self.convert_lights(depsgraph, renderer)
        self.setup_world(scene, renderer)
    
    def setup_camera(self, scene, renderer, width, height):
        cam_obj = scene.camera
        if not cam_obj: return
        matrix = cam_obj.matrix_world
        look_from = list(matrix.translation)
        forward = matrix.to_3x3() @ mathutils.Vector((0, 0, -1))
        look_at = [look_from[0] + forward.x, look_from[1] + forward.y, look_from[2] + forward.z]
        up = matrix.to_3x3() @ mathutils.Vector((0, 1, 0))
        vup = [up.x, up.y, up.z]
        
        camera = cam_obj.data
        if camera.type == 'PERSP':
            vfov = math.degrees(camera.angle) if camera.lens_unit == 'FOV' else 2 * math.degrees(math.atan(camera.sensor_height / (2 * camera.lens)))
        else: vfov = 40.0
        
        aperture, focus_dist = 0.0, 10.0
        if camera.dof.use_dof:
            aperture = 1.0 / (2 * camera.dof.aperture_fstop) if camera.dof.aperture_fstop > 0 else 0
            if camera.dof.focus_object:
                focus_dist = (mathutils.Vector(look_from) - camera.dof.focus_object.location).length
            else: focus_dist = camera.dof.focus_distance
        
        renderer.setup_camera(look_from, look_at, vup, vfov, width/height, aperture, focus_dist, width, height)
    
    def convert_materials(self, depsgraph, renderer):
        material_map = {}
        for mat in bpy.data.materials:
            if not mat.use_nodes:
                mat_id = renderer.create_material('disney', list(mat.diffuse_color[:3]),
                    {'roughness': float(mat.roughness), 'metallic': float(mat.metallic)})
            else: mat_id = self.convert_node_material(mat, renderer)
            material_map[mat.name] = mat_id
        return material_map
    
    def convert_node_material(self, mat, renderer):
        output = next((n for n in mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if not output: return renderer.create_material('disney', [0.8, 0.8, 0.8], {})
        
        surface_input = output.inputs.get('Surface')
        if not surface_input or not surface_input.is_linked:
            return renderer.create_material('disney', [0.8, 0.8, 0.8], {})
        
        node = surface_input.links[0].from_node
        if node.type == 'BSDF_PRINCIPLED': return self.convert_principled_bsdf(node, renderer)
        elif node.type == 'EMISSION':
            return renderer.create_material('light', list(node.inputs['Color'].default_value[:3]),
                {'intensity': node.inputs['Strength'].default_value})
        elif node.type == 'BSDF_GLASS':
            return renderer.create_material('glass', [1, 1, 1], {'ior': node.inputs['IOR'].default_value})
        return renderer.create_material('disney', [0.8, 0.8, 0.8], {})
    
    def convert_principled_bsdf(self, node, renderer):
        def get_val(name, default=0):
            inp = node.inputs.get(name)
            if inp and not inp.is_linked:
                val = inp.default_value
                # Convert to Python float if it's a scalar
                if hasattr(val, '__iter__'):
                    return list(val)  # Convert bpy_prop_array to list
                return float(val)
            return default
        
        base_color = list(get_val('Base Color', [0.8, 0.8, 0.8])[:3])
        params = {
            'metallic': float(get_val('Metallic', 0)),
            'roughness': float(get_val('Roughness', 0.5)),
            'ior': float(get_val('IOR', 1.45)),
            'transmission': float(get_val('Transmission', 0)),
            'clearcoat': float(get_val('Coat Weight', 0)),
            'clearcoat_gloss': float(1.0 - get_val('Coat Roughness', 0)),
            'anisotropic': float(get_val('Anisotropic', 0)),
            'sheen': float(get_val('Sheen Weight', 0)),
            'subsurface': float(get_val('Subsurface Weight', 0))
        }
        
        emission_color = get_val('Emission Color', [0, 0, 0])
        emission_strength = float(get_val('Emission Strength', 0))
        if emission_strength > 0 and any(c > 0 for c in emission_color[:3]):
            return renderer.create_material('light', list(emission_color[:3]), {'intensity': emission_strength})
        return renderer.create_material('disney', base_color, params)
    
    def convert_objects(self, depsgraph, renderer, material_map):
        for obj_instance in depsgraph.object_instances:
            obj = obj_instance.object
            if obj.type != 'MESH' or not obj.visible_get(): continue
            
            obj_eval = obj.evaluated_get(depsgraph)
            mesh = obj_eval.data
            matrix = obj_instance.matrix_world
            
            mat_id = 0
            if obj.material_slots:
                mat = obj.material_slots[0].material
                if mat and mat.name in material_map: mat_id = material_map[mat.name]
            
            mesh.calc_loop_triangles()
            for tri in mesh.loop_triangles:
                v0 = matrix @ mesh.vertices[tri.vertices[0]].co
                v1 = matrix @ mesh.vertices[tri.vertices[1]].co
                v2 = matrix @ mesh.vertices[tri.vertices[2]].co
                uv0 = uv1 = uv2 = []
                if mesh.uv_layers.active:
                    uv_layer = mesh.uv_layers.active.data
                    uv0 = list(uv_layer[tri.loops[0]].uv)
                    uv1 = list(uv_layer[tri.loops[1]].uv)
                    uv2 = list(uv_layer[tri.loops[2]].uv)
                renderer.add_triangle(list(v0), list(v1), list(v2), mat_id, uv0, uv1, uv2)
    
    def convert_lights(self, depsgraph, renderer):
        for obj in depsgraph.objects:
            if obj.type != 'LIGHT': continue
            light = obj.data
            matrix = obj.matrix_world
            position = list(matrix.translation)
            mat_id = renderer.create_material('light', list(light.color), {'intensity': float(light.energy)})
            
            if light.type == 'POINT': renderer.add_sphere(position, 0.1, mat_id)
            elif light.type == 'SUN':
                direction = matrix.to_3x3() @ mathutils.Vector((0, 0, -1))
                sun_pos = [position[0] - direction.x * 1000, position[1] - direction.y * 1000, position[2] - direction.z * 1000]
                renderer.add_sphere(sun_pos, 100.0, mat_id)
            elif light.type == 'AREA':
                size = float(max(light.size, getattr(light, 'size_y', light.size)))
                renderer.add_sphere(position, size / 2, mat_id)
    
    def setup_world(self, scene, renderer):
        world = scene.world
        if not world or not world.use_nodes: return
        for node in world.node_tree.nodes:
            if node.type == 'BACKGROUND':
                color = list(node.inputs['Color'].default_value[:3])
                strength = float(node.inputs['Strength'].default_value)
                if strength > 0.01:
                    mat_id = renderer.create_material('light', color, {'intensity': strength})
                    renderer.add_sphere([0, 0, 0], 500.0, mat_id)
                break
    
    def write_pixels(self, pixels, width, height):
        rgba = np.ones((height, width, 4), dtype=np.float32)
        rgba[:, :, :3] = pixels
        result = self.begin_result(0, 0, width, height)
        layer = result.layers[0]
        render_pass = layer.passes.get("Combined") or (layer.passes[0] if layer.passes else None)
        if render_pass: render_pass.rect = rgba.reshape(-1, 4).tolist()
        self.end_result(result)

class RENDER_PT_custom_raytracer_sampling(Panel):
    bl_label = "Sampling"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"
    
    @classmethod
    def poll(cls, context): return context.scene.render.engine == 'CUSTOM_RAYTRACER'
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.custom_raytracer
        layout.use_property_split = True
        col = layout.column(align=True)
        col.prop(settings, "samples", text="Render")
        col.prop(settings, "preview_samples", text="Viewport")
        col.separator()
        col.prop(settings, "use_adaptive_sampling")
        if settings.use_adaptive_sampling: col.prop(settings, "adaptive_threshold")

class RENDER_PT_custom_raytracer_light_paths(Panel):
    bl_label = "Light Paths"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"
    
    @classmethod
    def poll(cls, context): return context.scene.render.engine == 'CUSTOM_RAYTRACER'
    
    def draw(self, context):
        layout = self.layout
        settings = context.scene.custom_raytracer
        layout.use_property_split = True
        col = layout.column(align=True)
        col.prop(settings, "max_bounces")
        col.prop(settings, "clamp_indirect")

class CustomRaytracerPreferences(AddonPreferences):
    bl_idname = __name__
    debug_mode: BoolProperty(name="Debug Mode", default=False)
    
    def draw(self, context):
        layout = self.layout
        if RAYTRACER_AVAILABLE:
            layout.label(text=f"Raytracer Version: {raytracer_blender.__version__}", icon='INFO')
            box = layout.box()
            box.label(text="Features:", icon='CHECKBOX_HLT')
            for feat, enabled in raytracer_blender.__features__.items():
                box.label(text=f"  {feat.replace('_', ' ').title()}", icon='CHECKBOX_HLT' if enabled else 'CHECKBOX_DEHLT')
        else:
            layout.label(text="Raytracer module not loaded!", icon='ERROR')
        layout.prop(self, "debug_mode")

classes = [
    CustomRaytracerRenderSettings, CustomRaytracerMaterialSettings,
    CustomRaytracerRenderEngine, RENDER_PT_custom_raytracer_sampling,
    RENDER_PT_custom_raytracer_light_paths, CustomRaytracerPreferences,
]

def register():
    for cls in classes: bpy.utils.register_class(cls)
    bpy.types.Scene.custom_raytracer = PointerProperty(type=CustomRaytracerRenderSettings)
    bpy.types.Material.custom_raytracer = PointerProperty(type=CustomRaytracerMaterialSettings)
    print("Custom Raytracer addon registered")

def unregister():
    del bpy.types.Scene.custom_raytracer
    del bpy.types.Material.custom_raytracer
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
    print("Custom Raytracer addon unregistered")

if __name__ == "__main__": register()

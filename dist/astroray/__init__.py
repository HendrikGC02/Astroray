# NOTE: Blender 5.1+ uses blender_manifest.toml (see sibling file). bl_info is kept
# as a fallback for Blender 4.x — Blender prefers the manifest when both exist.
bl_info = {
    "name": "Astroray Renderer",
    "author": "Hendrik Combrinck",
    "version": (4, 0, 0),
    "blender": (5, 0, 0),
    "location": "Render Properties > Render Engine > Astroray",
    "description": "PBR path tracer with Disney BRDF, NEE, MIS, GR black holes",
    "category": "Render",
}

import bpy
from bpy.types import Panel, Operator, AddonPreferences, PropertyGroup, RenderEngine
from bpy.props import BoolProperty, IntProperty, FloatProperty, StringProperty, PointerProperty, FloatVectorProperty
import mathutils, math, numpy as np, traceback, sys, os, time
from pathlib import Path

addon_dir = os.path.dirname(__file__)
if addon_dir not in sys.path: sys.path.insert(0, addon_dir)

# On Windows the compiled .pyd ships with bundled MinGW runtime DLLs
# (libgomp-1.dll, etc.). Python 3.8+ no longer searches PATH for module
# dependencies, so we have to explicitly add the addon directory to the
# DLL search list before importing.
if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
    try:
        os.add_dll_directory(addon_dir)
    except (FileNotFoundError, OSError):
        pass

try:
    import astroray
    RAYTRACER_AVAILABLE = True
    print(f"Custom Raytracer {astroray.__version__} loaded")
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
    use_gpu: BoolProperty(name="Use GPU", default=False,
        description="Use CUDA GPU for rendering (requires NVIDIA GPU)")

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
            renderer = astroray.Renderer()
            renderer.set_adaptive_sampling(settings.use_adaptive_sampling)
            self.convert_scene(depsgraph, renderer, width, height)

            if settings.use_gpu:
                try:
                    renderer.set_use_gpu(True)
                    print(f"GPU rendering: {renderer.gpu_device_name}")
                except Exception as e:
                    print(f"GPU not available, falling back to CPU: {e}")

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
        # In Blender 5.0+ every material is node-based (use_nodes is deprecated
        # and always True), so we always go through the node tree conversion.
        material_map = {}
        for mat in bpy.data.materials:
            material_map[mat.name] = self.convert_node_material(mat, renderer)
        return material_map

    def convert_node_material(self, mat, renderer):
        """Convert a Blender material to Astroray.

        Uses `material.inline_shader_nodes()` (Blender 5.0+) to get a flattened
        node tree with node groups inlined, reroutes removed, and muted nodes
        stripped — this is a MUCH more robust starting point than walking the
        raw user node tree. Falls back to `mat.node_tree` on older Blender.
        """
        # CRITICAL: keep `inlined` alive while accessing `node_tree`. When it's
        # garbage collected the node_tree reference becomes invalid, so we store
        # it locally and only let it drop after this function returns.
        inlined = None
        try:
            inlined = mat.inline_shader_nodes()
            node_tree = inlined.node_tree
        except (AttributeError, RuntimeError):
            # Pre-5.0 Blender: fall back to direct access
            node_tree = getattr(mat, 'node_tree', None)
        if node_tree is None:
            return renderer.create_material('disney', [0.8, 0.8, 0.8], {})

        # Find the active output node (preferred), or any OUTPUT_MATERIAL
        output = None
        for node in node_tree.nodes:
            if node.type == 'OUTPUT_MATERIAL' and getattr(node, 'is_active_output', True):
                output = node
                break
        if output is None:
            output = next((n for n in node_tree.nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if output is None:
            return renderer.create_material('disney', [0.8, 0.8, 0.8], {})

        surface_input = output.inputs.get('Surface')
        if not surface_input or not surface_input.is_linked:
            return renderer.create_material('disney', [0.8, 0.8, 0.8], {})

        shader_node = surface_input.links[0].from_node
        return self.convert_shader_node(shader_node, renderer, node_tree)

    # ------------------------------------------------------------------ #
    # Node-input helpers (unlinked defaults + linked image texture lookup)
    # ------------------------------------------------------------------ #

    def get_float_input(self, node, name, default):
        """Read a scalar input's default_value. Returns `default` if linked or
        missing. We deliberately do NOT follow math-node chains — too much of a
        rabbit hole for the first pass."""
        inp = node.inputs.get(name)
        if not inp or inp.is_linked:
            return default
        val = inp.default_value
        if hasattr(val, '__iter__'):
            # bpy_prop_array for a scalar socket shouldn't happen, but be safe
            try:
                return float(val[0])
            except Exception:
                return default
        return float(val)

    def get_color_input(self, node, name, default):
        """Read an unlinked color input as a list of 3 floats."""
        inp = node.inputs.get(name)
        if not inp or inp.is_linked:
            return list(default)
        val = inp.default_value
        if hasattr(val, '__iter__'):
            return list(val[:3])
        return list(default)

    def get_color_or_texture(self, node, input_name, default_color):
        """Read a color input; if linked to an Image Texture node, also return
        the image datablock. Returns (fallback_color, bpy_image_or_None)."""
        inp = node.inputs.get(input_name)
        if not inp:
            return list(default_color), None

        if not inp.is_linked:
            val = inp.default_value
            if hasattr(val, '__iter__'):
                return list(val[:3]), None
            return list(default_color), None

        try:
            linked_node = inp.links[0].from_node
        except (IndexError, AttributeError):
            return list(default_color), None

        # Follow a single Normal Map / Hue-Saturation / etc. wrapper to its
        # underlying Image Texture if present. Otherwise only direct TEX_IMAGE.
        if linked_node.type == 'TEX_IMAGE' and linked_node.image:
            fallback = list(inp.default_value[:3]) if hasattr(inp.default_value, '__iter__') else list(default_color)
            return fallback, linked_node.image
        if linked_node.type in ('NORMAL_MAP', 'HUE_SAT', 'GAMMA', 'BRIGHTCONTRAST'):
            color_in = linked_node.inputs.get('Color')
            if color_in and color_in.is_linked:
                try:
                    deeper = color_in.links[0].from_node
                    if deeper.type == 'TEX_IMAGE' and deeper.image:
                        return list(default_color), deeper.image
                except (IndexError, AttributeError):
                    pass
        return list(default_color), None

    def load_blender_image(self, bpy_image, renderer):
        """Load a Blender image datablock into the renderer's texture manager.
        Returns the texture name (string) on success, None on failure.

        Blender stores image pixels bottom-to-top; the C++ ImageTexture expects
        top-to-bottom, so we flip vertically before uploading.
        """
        if bpy_image is None:
            return None
        # Deduplicate: a single Blender image is uploaded at most once per
        # conversion pass.
        cache = getattr(self, '_texture_cache', None)
        if cache is None:
            cache = {}
            self._texture_cache = cache
        if bpy_image.name in cache:
            return cache[bpy_image.name]

        try:
            width, height = bpy_image.size
            if width == 0 or height == 0:
                return None
            # Force pixel data to be available (packed/generated images may not
            # have pixels loaded until reload() is called).
            if not bpy_image.has_data:
                try:
                    bpy_image.reload()
                except Exception:
                    pass
            if len(bpy_image.pixels) == 0:
                return None

            # pixels are a flat RGBA float array, row-major, bottom-to-top
            pixels = np.asarray(bpy_image.pixels[:], dtype=np.float32)
            pixels = pixels.reshape(height, width, 4)
            # Flip vertically (Blender stores row 0 = bottom)
            pixels = np.ascontiguousarray(pixels[::-1, :, :])
            # Drop alpha; renderer takes RGB float
            rgb = pixels[:, :, :3].reshape(-1).tolist()

            tex_name = bpy_image.name
            renderer.load_texture(tex_name, rgb, width, height)
            cache[bpy_image.name] = tex_name
            return tex_name
        except Exception as e:
            print(f"Astroray: failed to load texture '{bpy_image.name}': {e}")
            return None

    # ------------------------------------------------------------------ #
    # Shader-node dispatch
    # ------------------------------------------------------------------ #

    def convert_shader_node(self, node, renderer, node_tree):
        """Route a surface-shader node to the appropriate material builder."""
        ntype = node.type
        if ntype == 'BSDF_PRINCIPLED':
            return self.convert_principled_bsdf_v2(node, renderer)
        if ntype == 'EMISSION':
            color = self.get_color_input(node, 'Color', [1, 1, 1])
            strength = self.get_float_input(node, 'Strength', 1.0)
            return renderer.create_material('light', color, {'intensity': strength})
        if ntype == 'BSDF_GLASS':
            ior = self.get_float_input(node, 'IOR', 1.5)
            return renderer.create_material('glass', [1, 1, 1], {'ior': ior})
        if ntype == 'BSDF_DIFFUSE':
            color = self.get_color_input(node, 'Color', [0.8, 0.8, 0.8])
            return renderer.create_material('lambertian', color, {})
        if ntype in ('BSDF_GLOSSY', 'BSDF_ANISOTROPIC'):
            color = self.get_color_input(node, 'Color', [0.8, 0.8, 0.8])
            rough = self.get_float_input(node, 'Roughness', 0.5)
            return renderer.create_material('metal', color, {'roughness': rough})
        if ntype == 'MIX_SHADER':
            # Prefer the first linked BSDF-ish input; this is a simplification
            # that ignores the mix factor but keeps the dominant shader.
            for inp in node.inputs:
                if inp.is_linked:
                    try:
                        src = inp.links[0].from_node
                    except (IndexError, AttributeError):
                        continue
                    if src.type.startswith('BSDF') or src.type == 'EMISSION':
                        return self.convert_shader_node(src, renderer, node_tree)
            return renderer.create_material('disney', [0.8, 0.8, 0.8], {})
        if ntype == 'ADD_SHADER':
            # Just take the first linked shader; the renderer doesn't support
            # additive shader blending directly.
            for inp in node.inputs:
                if inp.is_linked:
                    try:
                        src = inp.links[0].from_node
                    except (IndexError, AttributeError):
                        continue
                    return self.convert_shader_node(src, renderer, node_tree)
        # Unknown — safe default
        return renderer.create_material('disney', [0.8, 0.8, 0.8], {})

    def _float_with_fallback(self, node, new_name, old_name, default):
        """Principled BSDF renamed several inputs between Blender 3.x and 4.x
        ('Transmission' → 'Transmission Weight', etc.). Try the new name first,
        fall back to the old."""
        if node.inputs.get(new_name) is not None:
            return self.get_float_input(node, new_name, default)
        return self.get_float_input(node, old_name, default)

    def convert_principled_bsdf_v2(self, node, renderer):
        """Full Principled BSDF → Disney BRDF conversion with texture support.

        Reads default values from every socket, follows linked Image Texture
        nodes on Base Color (other sockets: defaults only for now), and picks
        up the renamed sockets introduced in Blender 4.0.
        """
        # --- Base Color (may be textured) ---
        base_color, base_color_tex = self.get_color_or_texture(
            node, 'Base Color', [0.8, 0.8, 0.8])

        # --- Scalar parameters (with renamed-input fallbacks) ---
        metallic  = self.get_float_input(node, 'Metallic', 0.0)
        roughness = self.get_float_input(node, 'Roughness', 0.5)
        ior       = self.get_float_input(node, 'IOR', 1.45)

        transmission   = self._float_with_fallback(node, 'Transmission Weight', 'Transmission',  0.0)
        coat_weight    = self._float_with_fallback(node, 'Coat Weight',         'Clearcoat',     0.0)
        coat_roughness = self._float_with_fallback(node, 'Coat Roughness',      'Clearcoat Roughness', 0.0)
        sheen          = self._float_with_fallback(node, 'Sheen Weight',        'Sheen',         0.0)
        subsurface     = self._float_with_fallback(node, 'Subsurface Weight',   'Subsurface',    0.0)
        anisotropic    = self.get_float_input(node, 'Anisotropic', 0.0)

        # --- Emission (combined with surface; we treat strongly-emissive as
        # a pure light until DisneyBRDF gains an emission term) ---
        emission_color    = self.get_color_input(node, 'Emission Color', [0, 0, 0])
        emission_strength = self.get_float_input(node, 'Emission Strength', 0.0)
        if emission_strength > 0.0 and any(c > 0 for c in emission_color):
            # Heuristic: treat as a dedicated light material when emission
            # dominates the surface response.
            if emission_strength >= 1.0 and metallic == 0.0 and transmission == 0.0:
                return renderer.create_material(
                    'light', emission_color, {'intensity': emission_strength})

        params = {
            'metallic':        metallic,
            'roughness':       roughness,
            'ior':             ior,
            'transmission':    transmission,
            'clearcoat':       coat_weight,
            'clearcoat_gloss': 1.0 - coat_roughness,
            'anisotropic':     anisotropic,
            'sheen':           sheen,
            'subsurface':      subsurface,
        }

        # If base color is textured, load it and route through the 'lambertian'
        # textured path (DisneyBRDF doesn't currently accept a texture, and the
        # TexturedLambertian gives correct base color sampling for most PBR
        # scenes while preserving roughness/metallic-less appearance).
        if base_color_tex is not None:
            tex_name = self.load_blender_image(base_color_tex, renderer)
            if tex_name:
                # Use textured lambertian (the only path that currently samples
                # a texture on hit). TODO: extend DisneyBRDF with a base-color
                # texture slot so we can keep metallic/roughness too.
                return renderer.create_material('lambertian', base_color,
                                                {'texture': tex_name})

        return renderer.create_material('disney', base_color, params)
    
    def convert_objects(self, depsgraph, renderer, material_map):
        for obj_instance in depsgraph.object_instances:
            obj = obj_instance.object

            # Black hole empties
            if obj.type == 'EMPTY' and hasattr(obj, 'astroray_black_hole'):
                bh = obj.astroray_black_hole
                if bh.mass > 0:
                    try:
                        renderer.add_black_hole(
                            list(obj.location),
                            bh.mass,
                            bh.influence_radius,
                            {
                                'disk_outer':     bh.disk_outer,
                                'accretion_rate': bh.accretion_rate,
                                'inclination':    bh.inclination,
                            }
                        )
                    except Exception as e:
                        print(f"Black hole conversion error: {e}")
                continue

            if obj.type != 'MESH' or not obj.visible_get():
                continue

            obj_eval = obj.evaluated_get(depsgraph)
            mesh = obj_eval.data
            matrix = obj_instance.matrix_world

            # -------- Per-slot material map --------
            # Blender meshes carry one material_index per face; resolve each
            # slot once up front, then look up by index inside the hot loop.
            slot_to_id = {}
            for slot_idx, slot in enumerate(obj.material_slots):
                mat = slot.material
                if mat is not None and mat.name in material_map:
                    slot_to_id[slot_idx] = material_map[mat.name]
                else:
                    slot_to_id[slot_idx] = 0
            default_mat_id = slot_to_id.get(0, 0)

            # -------- Normal transform --------
            # Normals transform by the INVERSE TRANSPOSE of the model matrix's
            # 3x3 rotation/scale block. Using the model matrix directly would
            # skew normals under non-uniform scaling.
            try:
                normal_matrix = matrix.to_3x3().inverted_safe().transposed()
            except Exception:
                normal_matrix = matrix.to_3x3()

            mesh.calc_loop_triangles()
            # split_normals carries the correct per-corner normal for
            # smooth/flat/custom shading. Available since Blender 4.1; on
            # older versions we silently skip it (fall back to face normals).
            uv_data = mesh.uv_layers.active.data if mesh.uv_layers.active else None

            for tri in mesh.loop_triangles:
                v0 = matrix @ mesh.vertices[tri.vertices[0]].co
                v1 = matrix @ mesh.vertices[tri.vertices[1]].co
                v2 = matrix @ mesh.vertices[tri.vertices[2]].co

                # Per-face material index
                mat_id = slot_to_id.get(tri.material_index, default_mat_id)

                # UVs
                uv0 = uv1 = uv2 = []
                if uv_data is not None:
                    uv0 = list(uv_data[tri.loops[0]].uv)
                    uv1 = list(uv_data[tri.loops[1]].uv)
                    uv2 = list(uv_data[tri.loops[2]].uv)

                # Per-corner normals (Blender 4.1+). Fall back gracefully.
                n0 = n1 = n2 = []
                try:
                    sn = tri.split_normals
                    raw_n0 = mathutils.Vector(sn[0])
                    raw_n1 = mathutils.Vector(sn[1])
                    raw_n2 = mathutils.Vector(sn[2])
                    n0 = list((normal_matrix @ raw_n0).normalized())
                    n1 = list((normal_matrix @ raw_n1).normalized())
                    n2 = list((normal_matrix @ raw_n2).normalized())
                except (AttributeError, IndexError):
                    n0 = n1 = n2 = []

                renderer.add_triangle(
                    list(v0), list(v1), list(v2), mat_id,
                    uv0, uv1, uv2,
                    n0, n1, n2,
                )
    
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
                angle = float(getattr(light, 'angle', 0.0))
                renderer.add_sun_light([direction.x, direction.y, direction.z], angle, mat_id)
            elif light.type == 'AREA':
                size = float(max(light.size, getattr(light, 'size_y', light.size)))
                renderer.add_sphere(position, size / 2, mat_id)
    
    def setup_world(self, scene, renderer):
        world = scene.world
        if not world:
            return

        # Check for node tree (use_nodes is deprecated in Blender 5.x, always True)
        node_tree = getattr(world, 'node_tree', None)
        if not node_tree:
            return

        # Look for Environment Texture -> Background -> World Output chain
        hdri_path = None
        strength = 1.0
        rotation = 0.0
        bg_color = None

        for node in node_tree.nodes:
            if node.type == 'TEX_ENVIRONMENT' and node.image:
                hdri_path = bpy.path.abspath(node.image.filepath)
            elif node.type == 'BACKGROUND':
                strength = float(node.inputs['Strength'].default_value)
                # If Color input is not linked, it's a solid background color
                color_input = node.inputs.get('Color')
                if color_input and not color_input.is_linked:
                    bg_color = list(color_input.default_value[:3])
            elif node.type == 'MAPPING':
                rot_input = node.inputs.get('Rotation')
                if rot_input:
                    rotation = float(rot_input.default_value[2])  # Z rotation

        # Try loading HDRI first
        if hdri_path and os.path.exists(hdri_path):
            success = renderer.load_environment_map(hdri_path, strength, rotation)
            if success:
                print(f"Loaded HDRI: {hdri_path} (strength={strength}, rotation={rotation:.2f})")
                return
            else:
                print(f"Failed to load HDRI: {hdri_path}")

        # Fallback: solid background color
        if bg_color and strength > 0.01:
            scaled_color = [c * strength for c in bg_color]
            renderer.set_background_color(scaled_color)
            print(f"Set background color: {scaled_color}")
    
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
        col.separator()
        col.prop(settings, "use_gpu")
        if RAYTRACER_AVAILABLE and hasattr(astroray.Renderer(), 'gpu_available'):
            try:
                r = astroray.Renderer()
                if r.gpu_available:
                    col.label(text=f"GPU: {r.gpu_device_name}", icon='CHECKMARK')
                else:
                    col.label(text="No CUDA GPU detected", icon='INFO')
            except Exception:
                pass

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
            layout.label(text=f"Raytracer Version: {astroray.__version__}", icon='INFO')
            box = layout.box()
            box.label(text="Features:", icon='CHECKBOX_HLT')
            for feat, enabled in astroray.__features__.items():
                box.label(text=f"  {feat.replace('_', ' ').title()}", icon='CHECKBOX_HLT' if enabled else 'CHECKBOX_DEHLT')
        else:
            layout.label(text="Raytracer module not loaded!", icon='ERROR')
        layout.prop(self, "debug_mode")

class AstrorayBlackHoleProperties(PropertyGroup):
    mass: FloatProperty(name="Mass (M\u2609)", min=0.1, max=1e10, default=10.0,
                        description="Black hole mass in solar masses")
    influence_radius: FloatProperty(name="Influence Radius", min=1.0, max=10000.0, default=100.0,
                                    description="World-space radius of the GR influence sphere")
    disk_outer: FloatProperty(name="Disk Outer Radius (M)", min=6.0, max=1000.0, default=30.0,
                               description="Accretion disk outer radius in units of M")
    accretion_rate: FloatProperty(name="Accretion Rate", min=0.01, max=100.0, default=1.0,
                                   description="Dimensionless accretion rate (sets disk brightness)")
    inclination: FloatProperty(name="Inclination (\u00b0)", min=0.0, max=90.0, default=75.0,
                                description="Observer inclination from the spin axis")
    show_disk: BoolProperty(name="Show Accretion Disk", default=True)


class ASTRORAY_OT_add_black_hole(Operator):
    bl_idname = "astroray.add_black_hole"
    bl_label = "Add Black Hole"
    bl_description = "Add a black hole empty to the scene"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        bpy.ops.object.empty_add(type='SPHERE')
        obj = context.active_object
        obj.name = "BlackHole"
        obj.empty_display_size = 5.0
        return {'FINISHED'}


class OBJECT_PT_astroray_black_hole(Panel):
    bl_label = "Astroray Black Hole"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (obj is not None and obj.type == 'EMPTY'
                and hasattr(obj, 'astroray_black_hole'))

    def draw(self, context):
        layout = self.layout
        bh = context.active_object.astroray_black_hole
        layout.use_property_split = True
        col = layout.column(align=True)
        col.prop(bh, "mass")
        col.prop(bh, "influence_radius")
        col.separator()
        col.prop(bh, "disk_outer")
        col.prop(bh, "accretion_rate")
        col.prop(bh, "inclination")
        col.prop(bh, "show_disk")


classes = [
    CustomRaytracerRenderSettings, CustomRaytracerMaterialSettings,
    AstrorayBlackHoleProperties,
    CustomRaytracerRenderEngine, RENDER_PT_custom_raytracer_sampling,
    RENDER_PT_custom_raytracer_light_paths, CustomRaytracerPreferences,
    ASTRORAY_OT_add_black_hole, OBJECT_PT_astroray_black_hole,
]

def register():
    for cls in classes: bpy.utils.register_class(cls)
    bpy.types.Scene.custom_raytracer = PointerProperty(type=CustomRaytracerRenderSettings)
    bpy.types.Material.custom_raytracer = PointerProperty(type=CustomRaytracerMaterialSettings)
    bpy.types.Object.astroray_black_hole = PointerProperty(type=AstrorayBlackHoleProperties)
    print("Custom Raytracer addon registered")

def unregister():
    del bpy.types.Scene.custom_raytracer
    del bpy.types.Material.custom_raytracer
    del bpy.types.Object.astroray_black_hole
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
    print("Custom Raytracer addon unregistered")

if __name__ == "__main__": register()

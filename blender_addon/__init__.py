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
from shader_blending import blend_shader_specs, add_shader_specs

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
    samples: IntProperty(name="Samples", min=1, max=65536, default=2,
        description="Samples per pixel for final F12 renders")
    preview_samples: IntProperty(name="Viewport Samples", min=1, max=1024, default=1,
        description="Samples per pixel for rendered-shading viewport preview")
    max_bounces: IntProperty(name="Max Bounces", min=0, max=1024, default=10,
        description="Maximum path-trace depth — caps how many times a ray can scatter")
    use_adaptive_sampling: BoolProperty(name="Adaptive Sampling", default=True,
        description="Stop sampling pixels that have already converged")
    adaptive_threshold: FloatProperty(name="Noise Threshold", min=0.001, max=1.0, default=0.01)
    clamp_direct: FloatProperty(name="Clamp Direct", min=0.0, max=100.0, default=0.0,
        description="Clamp direct lighting contribution luminance (0 disables)")
    clamp_indirect: FloatProperty(name="Clamp Indirect", min=0.0, max=100.0, default=0.0,
        description="Clamp indirect lighting contribution luminance (0 disables)")
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
    bl_label = "Astroray"
    bl_use_preview = True
    bl_use_postprocess = True
    bl_use_shading_nodes_custom = False
    bl_use_eevee_viewport = True  # fall back to Eevee for Material/Solid shading
    bl_use_gpu_context = False

    # RenderEngine is a C-backed class; we deliberately do NOT override
    # __init__ (Blender has caveats around RenderEngine constructor overrides,
    # see `bpy.types.RenderEngine` docs). Viewport state is lazily created
    # inside view_update instead.
    _viewport_texture = None
    _viewport_width = 0
    _viewport_height = 0

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
            pixels = renderer.render(settings.samples, settings.max_bounces, progress_callback, False)
            print(f"Render completed in {time.time() - start_time:.2f}s")
            
            if pixels is not None:
                alpha = None
                try:
                    alpha = renderer.get_alpha_buffer()
                except Exception:
                    alpha = None
                self.write_pixels(pixels, width, height, alpha)
        except Exception as e:
            print(f"RENDER ERROR: {e}")
            traceback.print_exc()
        finally:
            if renderer:
                try: renderer.clear()
                except: pass
            del renderer

    # ------------------------------------------------------------------ #
    # Viewport preview (rendered shading mode in 3D View)
    # ------------------------------------------------------------------ #

    def view_update(self, context, depsgraph):
        """Called when the scene or viewport changes. We do a fresh low-sample
        render here and stash the result as a GPUTexture so `view_draw` can
        just blit it every frame."""
        if not RAYTRACER_AVAILABLE:
            return
        region = context.region
        width = max(1, region.width)
        height = max(1, region.height)
        scene = depsgraph.scene
        settings = scene.custom_raytracer

        renderer = None
        try:
            renderer = astroray.Renderer()
            renderer.set_adaptive_sampling(settings.use_adaptive_sampling)
            renderer.clear()
            renderer.set_clamp_direct(settings.clamp_direct)
            renderer.set_clamp_indirect(settings.clamp_indirect)
            self._setup_viewport_camera(renderer, context, width, height)
            material_map = self.convert_materials(depsgraph, renderer)
            self.convert_objects(depsgraph, renderer, material_map)
            self.convert_lights(depsgraph, renderer)
            self.setup_world(scene, renderer)

            samples = max(1, settings.preview_samples)
            depth = max(2, settings.max_bounces // 2)
            pixels = renderer.render(samples, depth, None, False)
            if pixels is None:
                return
            self._update_viewport_texture(pixels, width, height)
        except Exception as e:
            print(f"Astroray viewport preview error: {e}")
            traceback.print_exc()
        finally:
            if renderer:
                try: renderer.clear()
                except Exception: pass

    def view_draw(self, context, depsgraph):
        """Called every frame inside rendered-shading mode to paint our
        cached preview texture into the 3D View."""
        if self._viewport_texture is None:
            return
        try:
            import gpu
            from gpu_extras.presets import draw_texture_2d
            region = context.region
            scene = depsgraph.scene

            # Cycles/Eevee wrap the draw in bind_display_space_shader so the
            # viewport color management pipeline is applied. We do the same —
            # the raytracer outputs linear scene-referred values and Blender
            # applies the view/display transform here.
            self.bind_display_space_shader(scene)
            draw_texture_2d(self._viewport_texture, (0, 0), region.width, region.height)
            self.unbind_display_space_shader()
        except Exception as e:
            print(f"Astroray view_draw error: {e}")

    def _setup_viewport_camera(self, renderer, context, width, height):
        """Build a lookFrom/lookAt from the 3D View's RegionView3D state.

        - In CAMERA view (numpad 0): use the scene camera as-is.
        - In PERSP / ORTHO view: derive position + direction from
          `rv3d.view_matrix.inverted()` and use `space_data.lens` for vfov.
        """
        rv3d = context.region_data
        space = context.space_data

        if rv3d is not None and rv3d.view_perspective == 'CAMERA' and context.scene.camera:
            self._apply_camera(renderer, context.scene.camera, width, height)
            return

        view_inv = rv3d.view_matrix.inverted()
        loc = view_inv.translation
        rot = view_inv.to_3x3()
        forward = rot @ mathutils.Vector((0.0, 0.0, -1.0))
        up      = rot @ mathutils.Vector((0.0, 1.0,  0.0))

        look_from = [loc.x, loc.y, loc.z]
        look_at   = [loc.x + forward.x, loc.y + forward.y, loc.z + forward.z]
        vup       = [up.x, up.y, up.z]

        # Blender's viewport uses a fixed 32mm sensor width and exposes the
        # effective focal length via space_data.lens (in mm).
        sensor_width = 32.0
        lens = getattr(space, 'lens', 50.0)
        aspect = width / max(1, height)
        hfov = 2.0 * math.atan(sensor_width / (2.0 * lens))
        vfov_rad = 2.0 * math.atan(math.tan(hfov / 2.0) / aspect)
        vfov = math.degrees(vfov_rad)

        renderer.setup_camera(look_from, look_at, vup, vfov, aspect,
                              0.0, 10.0, width, height)

    def _update_viewport_texture(self, pixels, width, height):
        import gpu
        # Flip vertically — Blender's GPU draw expects row 0 = bottom.
        rgba = np.ones((height, width, 4), dtype=np.float32)
        rgba[:, :, :3] = pixels
        rgba = np.ascontiguousarray(rgba[::-1])
        flat = rgba.reshape(-1)
        buf = gpu.types.Buffer('FLOAT', flat.shape[0], flat.tolist())
        self._viewport_texture = gpu.types.GPUTexture(
            (width, height), format='RGBA16F', data=buf)
        self._viewport_width = width
        self._viewport_height = height

    def convert_scene(self, depsgraph, renderer, width, height):
        scene = depsgraph.scene
        renderer.clear()
        settings = scene.custom_raytracer
        renderer.set_clamp_direct(settings.clamp_direct)
        renderer.set_clamp_indirect(settings.clamp_indirect)
        cycles = getattr(scene, 'cycles', None)
        render_settings = getattr(scene, 'render', None)
        exposure = float(getattr(cycles, 'film_exposure', 1.0)) if cycles else 1.0
        renderer.set_film_exposure(exposure)
        use_transparent_film = bool(getattr(render_settings, 'film_transparent', False)) if render_settings else False
        transparent_glass = bool(getattr(cycles, 'film_transparent_glass', False)) if cycles else False
        renderer.set_use_transparent_film(use_transparent_film)
        renderer.set_transparent_glass(transparent_glass)
        self.setup_camera(scene, renderer, width, height)
        material_map = self.convert_materials(depsgraph, renderer)
        self.convert_objects(depsgraph, renderer, material_map)
        self.convert_lights(depsgraph, renderer)
        self.setup_world(scene, renderer)
    
    def setup_camera(self, scene, renderer, width, height):
        cam_obj = scene.camera
        if not cam_obj: return
        self._apply_camera(renderer, cam_obj, width, height)

    def _compute_vfov_degrees(self, camera, width, height):
        """Vertical FOV in degrees for a Blender camera datablock.

        Cycles/Eevee pick the sensor axis from `sensor_fit`, then derive the
        image FOV from `lens` (focal length). We need VERTICAL FOV specifically
        because the raytracer's Camera class uses it to compute the view
        frustum height. So for HORIZONTAL/AUTO-wide fits we convert hfov→vfov
        using the final image aspect."""
        if camera.type != 'PERSP':
            # ORTHO / PANO: fall back to a plausible vfov so at least the
            # scene is visible. A full ortho-camera implementation would
            # require plumbing an orthographic flag into the C++ camera.
            return 40.0

        aspect = width / max(1, height)
        fit = camera.sensor_fit
        # AUTO picks the axis with the larger image dimension
        if fit == 'AUTO':
            fit = 'HORIZONTAL' if width >= height else 'VERTICAL'

        if fit == 'VERTICAL':
            sensor = camera.sensor_height
            vfov_rad = 2.0 * math.atan(sensor / (2.0 * camera.lens))
        else:  # HORIZONTAL
            sensor = camera.sensor_width
            hfov_rad = 2.0 * math.atan(sensor / (2.0 * camera.lens))
            vfov_rad = 2.0 * math.atan(math.tan(hfov_rad / 2.0) / aspect)
        return math.degrees(vfov_rad)

    def _apply_camera(self, renderer, cam_obj, width, height):
        """Extract lookFrom/lookAt/vup from a Blender camera object and push
        it to the renderer. Blender cameras point along their local -Z and
        use local +Y as 'up'; we rotate those unit vectors by the camera's
        world rotation to get world-space directions."""
        matrix = cam_obj.matrix_world
        loc, rot_quat, _scale = matrix.decompose()

        forward = rot_quat @ mathutils.Vector((0.0, 0.0, -1.0))
        up      = rot_quat @ mathutils.Vector((0.0, 1.0,  0.0))

        look_from = [loc.x, loc.y, loc.z]
        look_at   = [loc.x + forward.x, loc.y + forward.y, loc.z + forward.z]
        vup       = [up.x, up.y, up.z]

        camera = cam_obj.data
        vfov = self._compute_vfov_degrees(camera, width, height)

        aperture, focus_dist = 0.0, 10.0
        if camera.dof.use_dof:
            if camera.dof.aperture_fstop > 0:
                aperture = 1.0 / (2 * camera.dof.aperture_fstop)
            if camera.dof.focus_object:
                focus_dist = (loc - camera.dof.focus_object.matrix_world.translation).length
            else:
                focus_dist = camera.dof.focus_distance

        renderer.setup_camera(look_from, look_at, vup, vfov,
                              width / max(1, height),
                              aperture, focus_dist, width, height)
    
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

    def get_image_from_socket(self, socket):
        """Resolve a directly linked Image Texture datablock from a socket."""
        if not socket or not socket.is_linked:
            return None
        try:
            src = socket.links[0].from_node
        except (IndexError, AttributeError):
            return None
        if src.type == 'TEX_IMAGE' and src.image:
            return src.image
        return None

    def get_normal_inputs(self, node):
        """Extract normal-map / bump-map inputs wired into Principled Normal."""
        result = {
            'normal_image': None,
            'normal_strength': 1.0,
            'bump_image': None,
            'bump_strength': 1.0,
            'bump_distance': 0.01,
        }
        visited = set()

        def walk_normal_chain(socket):
            if not socket or not socket.is_linked:
                return
            try:
                src = socket.links[0].from_node
            except (IndexError, AttributeError):
                return
            key = id(src)
            if key in visited:
                return
            visited.add(key)

            if src.type == 'NORMAL_MAP':
                result['normal_strength'] = self.get_float_input(src, 'Strength', 1.0)
                result['normal_image'] = self.get_image_from_socket(src.inputs.get('Color'))
                walk_normal_chain(src.inputs.get('Normal'))
                return

            if src.type == 'BUMP':
                result['bump_strength'] = self.get_float_input(src, 'Strength', 1.0)
                result['bump_distance'] = self.get_float_input(src, 'Distance', 0.01)
                result['bump_image'] = self.get_image_from_socket(src.inputs.get('Height'))
                walk_normal_chain(src.inputs.get('Normal'))
                return

        walk_normal_chain(node.inputs.get('Normal'))
        return result

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

    def _shader_input_node(self, node, input_name):
        inp = node.inputs.get(input_name)
        if not inp or not inp.is_linked:
            return None
        try:
            return inp.links[0].from_node
        except (IndexError, AttributeError):
            return None

    def _principled_shader_spec(self, node):
        base_color = self.get_color_input(node, 'Base Color', [0.8, 0.8, 0.8])
        return {
            'kind': 'principled',
            'base_color': list(base_color),
            'params': {
                'metallic':        self.get_float_input(node, 'Metallic', 0.0),
                'roughness':       self.get_float_input(node, 'Roughness', 0.5),
                'ior':             self.get_float_input(node, 'IOR', 1.45),
                'transmission':    self._float_with_fallback(node, 'Transmission Weight', 'Transmission', 0.0),
                'clearcoat':       self._float_with_fallback(node, 'Coat Weight', 'Clearcoat', 0.0),
                'clearcoat_gloss': 1.0 - self._float_with_fallback(node, 'Coat Roughness', 'Clearcoat Roughness', 0.0),
                'anisotropic':     self.get_float_input(node, 'Anisotropic', 0.0),
                'sheen':           self._float_with_fallback(node, 'Sheen Weight', 'Sheen', 0.0),
                'subsurface':      self._float_with_fallback(node, 'Subsurface Weight', 'Subsurface', 0.0),
            },
            'emission_color': self.get_color_input(node, 'Emission Color', [0.0, 0.0, 0.0]),
            'emission_strength': self.get_float_input(node, 'Emission Strength', 0.0),
        }

    def _shader_spec_from_node(self, node, renderer, node_tree, depth=0):
        if node is None or depth > 32:
            return None
        ntype = node.type

        if ntype == 'BSDF_PRINCIPLED':
            return self._principled_shader_spec(node)
        if ntype == 'BSDF_DIFFUSE':
            return {'kind': 'principled', 'base_color': self.get_color_input(node, 'Color', [0.8, 0.8, 0.8]), 'params': {}}
        if ntype == 'BSDF_GLOSSY' or ntype == 'BSDF_ANISOTROPIC':
            return {'kind': 'principled', 'base_color': self.get_color_input(node, 'Color', [0.8, 0.8, 0.8]), 'params': {'metallic': 1.0, 'roughness': self.get_float_input(node, 'Roughness', 0.5)}}
        if ntype == 'BSDF_GLASS':
            return {'kind': 'principled', 'base_color': [1.0, 1.0, 1.0], 'params': {'transmission': 1.0, 'ior': self.get_float_input(node, 'IOR', 1.5), 'roughness': self.get_float_input(node, 'Roughness', 0.0)}}
        if ntype == 'BSDF_TRANSPARENT':
            return {'kind': 'transparent'}
        if ntype == 'EMISSION':
            return {'kind': 'emission', 'base_color': self.get_color_input(node, 'Color', [1.0, 1.0, 1.0]), 'emission_strength': self.get_float_input(node, 'Strength', 1.0)}
        if ntype == 'MIX_SHADER':
            fac = self.get_float_input(node, 'Fac', 0.5)
            a = self._shader_spec_from_node(self._shader_input_node(node, 'Shader'), renderer, node_tree, depth + 1)
            b = self._shader_spec_from_node(self._shader_input_node(node, 'Shader_001'), renderer, node_tree, depth + 1)
            return blend_shader_specs(fac, a, b)
        if ntype == 'ADD_SHADER':
            a = self._shader_spec_from_node(self._shader_input_node(node, 'Shader'), renderer, node_tree, depth + 1)
            b = self._shader_spec_from_node(self._shader_input_node(node, 'Shader_001'), renderer, node_tree, depth + 1)
            return add_shader_specs(a, b)
        return None

    def _create_material_from_shader_spec(self, spec, renderer):
        if spec is None:
            return renderer.create_material('disney', [0.8, 0.8, 0.8], {})

        kind = spec.get('kind')
        if kind == 'emission':
            return renderer.create_material('light', spec.get('base_color', [1, 1, 1]),
                                            {'intensity': float(spec.get('emission_strength', 1.0))})

        if kind == 'principled':
            color = list(spec.get('base_color', [0.8, 0.8, 0.8]))
            params = dict(spec.get('params', {}))
            emission_strength = float(spec.get('emission_strength', 0.0))
            emission_color = list(spec.get('emission_color', [0.0, 0.0, 0.0]))

            # Renderer has no explicit alpha channel; approximate transparency.
            alpha = params.pop('alpha', None)
            if alpha is not None:
                params['transmission'] = max(float(params.get('transmission', 0.0)), 1.0 - float(alpha))

            # Add-Shader / Mix-with-Emission approximation:
            # preserve surface and bias base color towards emission.
            if emission_strength > 0.0 and any(c > 0.0 for c in emission_color):
                if emission_strength >= 1.0 and float(params.get('metallic', 0.0)) == 0.0 and float(params.get('transmission', 0.0)) == 0.0:
                    return renderer.create_material('light', emission_color, {'intensity': emission_strength})
                glow = min(1.0, 0.2 * emission_strength)
                color = [max(0.0, min(1.0, (1.0 - glow) * color[i] + glow * emission_color[i])) for i in range(3)]

            return renderer.create_material('disney', color, params)

        return renderer.create_material('disney', [0.8, 0.8, 0.8], {})

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
            spec = self._shader_spec_from_node(node, renderer, node_tree)
            return self._create_material_from_shader_spec(spec, renderer)
        if ntype == 'ADD_SHADER':
            spec = self._shader_spec_from_node(node, renderer, node_tree)
            return self._create_material_from_shader_spec(spec, renderer)
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

        normal_inputs = self.get_normal_inputs(node)
        if normal_inputs['normal_image'] is not None:
            tex_name = self.load_blender_image(normal_inputs['normal_image'], renderer)
            if tex_name:
                params['normal_map_texture'] = tex_name
                params['normal_strength'] = normal_inputs['normal_strength']
        if normal_inputs['bump_image'] is not None:
            tex_name = self.load_blender_image(normal_inputs['bump_image'], renderer)
            if tex_name:
                params['bump_map_texture'] = tex_name
                params['bump_strength'] = normal_inputs['bump_strength']
                params['bump_distance'] = normal_inputs['bump_distance']

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
                lambert_params = {'texture': tex_name}
                for key in ('normal_map_texture', 'normal_strength',
                            'bump_map_texture', 'bump_strength', 'bump_distance'):
                    if key in params:
                        lambert_params[key] = params[key]
                return renderer.create_material('lambertian', base_color,
                                                lambert_params)

        return renderer.create_material('disney', base_color, params)
    
    def convert_objects(self, depsgraph, renderer, material_map):
        tri_count = 0
        obj_count = 0
        for obj_instance in depsgraph.object_instances:
            # DepsgraphObjectInstance.object is already the evaluated object;
            # the render-layer depsgraph only yields render-visible items, so
            # we must NOT filter again with `visible_get()` (which reflects
            # viewport visibility and can hide render-enabled objects during
            # an F12 render).
            obj = obj_instance.object

            # Black hole empties
            if obj.type == 'EMPTY' and hasattr(obj, 'astroray_black_hole'):
                bh = obj.astroray_black_hole
                if bh.mass > 0:
                    try:
                        mw = obj_instance.matrix_world
                        renderer.add_black_hole(
                            [mw.translation.x, mw.translation.y, mw.translation.z],
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

            if obj.type != 'MESH':
                continue

            mesh = obj.data
            if mesh is None:
                continue
            matrix = obj_instance.matrix_world
            obj_count += 1

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
                tri_count += 1

        print(f"Astroray: converted {obj_count} meshes, {tri_count} triangles")

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
    
    def write_pixels(self, pixels, width, height, alpha=None):
        # The raytracer returns pixels with y=0 at the TOP of the image (standard
        # image convention). Blender's render_pass.rect expects y=0 at the BOTTOM,
        # so we flip vertically before handing it off — otherwise the output ends
        # up mirrored across the horizontal axis (upside-down).
        rgba = np.ones((height, width, 4), dtype=np.float32)
        rgba[:, :, :3] = pixels
        if alpha is not None:
            alpha_arr = np.asarray(alpha, dtype=np.float32)
            if alpha_arr.shape == (height, width):
                rgba[:, :, 3] = np.clip(alpha_arr, 0.0, 1.0)
        rgba = np.ascontiguousarray(rgba[::-1])

        result = self.begin_result(0, 0, width, height)
        layer = result.layers[0]
        render_pass = layer.passes.get("Combined") or (layer.passes[0] if layer.passes else None)
        if render_pass:
            # foreach_set is ~100x faster than assigning a Python list to .rect
            flat = rgba.reshape(-1)
            try:
                render_pass.rect.foreach_set(flat)
            except AttributeError:
                render_pass.rect = rgba.reshape(-1, 4).tolist()
        self.end_result(result)

class AstrorayPanelBase:
    """Mixin for every Astroray panel: restricts visibility to scenes where
    our engine is active, and keeps COMPAT_ENGINES consistent for Blender's
    panel-filter machinery."""
    COMPAT_ENGINES = {'CUSTOM_RAYTRACER'}

    @classmethod
    def poll(cls, context):
        return context.scene.render.engine == 'CUSTOM_RAYTRACER'


class RENDER_PT_custom_raytracer_sampling(AstrorayPanelBase, Panel):
    bl_label = "Sampling"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        settings = context.scene.custom_raytracer

        col = layout.column(align=True)
        col.prop(settings, "samples", text="Render")
        col.prop(settings, "preview_samples", text="Viewport")

        layout.separator()
        layout.prop(settings, "use_adaptive_sampling")
        sub = layout.column()
        sub.active = settings.use_adaptive_sampling
        sub.prop(settings, "adaptive_threshold")


class RENDER_PT_custom_raytracer_light_paths(AstrorayPanelBase, Panel):
    bl_label = "Light Paths"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        settings = context.scene.custom_raytracer

        col = layout.column(align=True)
        col.prop(settings, "max_bounces", text="Max Bounces")
        col.prop(settings, "clamp_direct")
        col.prop(settings, "clamp_indirect")


class RENDER_PT_custom_raytracer_performance(AstrorayPanelBase, Panel):
    bl_label = "Performance"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        settings = context.scene.custom_raytracer

        col = layout.column(align=True)
        col.prop(settings, "use_gpu")
        if RAYTRACER_AVAILABLE:
            try:
                r = astroray.Renderer()
                if r.gpu_available:
                    col.label(text=f"GPU: {r.gpu_device_name}", icon='CHECKMARK')
                else:
                    col.label(text="No CUDA GPU detected", icon='INFO')
            except Exception:
                pass


class AstrorayWorldPanelBase(AstrorayPanelBase):
    """World panels only poll when there IS a world to edit."""
    @classmethod
    def poll(cls, context):
        return (context.scene.render.engine == 'CUSTOM_RAYTRACER'
                and context.world is not None)


class WORLD_PT_custom_raytracer_surface(AstrorayWorldPanelBase, Panel):
    bl_label = "Surface"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "world"

    def draw(self, context):
        layout = self.layout
        world = context.world
        layout.prop(world, "use_nodes", icon='NODETREE')
        layout.separator()
        if world.use_nodes and world.node_tree:
            # Let Cycles' world node drawing handle the detail — we just
            # expose the output node's Surface socket for quick edits.
            output = next((n for n in world.node_tree.nodes
                           if n.type == 'OUTPUT_WORLD'), None)
            if output is not None:
                layout.template_node_view(world.node_tree, output,
                                          output.inputs.get('Surface'))
        else:
            layout.prop(world, "color", text="Color")


class MATERIAL_PT_custom_raytracer_surface(AstrorayPanelBase, Panel):
    bl_label = "Surface"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        return (context.scene.render.engine == 'CUSTOM_RAYTRACER'
                and context.material is not None)

    def draw(self, context):
        layout = self.layout
        mat = context.material
        layout.prop(mat, "use_nodes", icon='NODETREE')
        layout.separator()
        if mat.use_nodes and mat.node_tree:
            output = next((n for n in mat.node_tree.nodes
                           if n.type == 'OUTPUT_MATERIAL' and getattr(n, 'is_active_output', True)),
                          None)
            if output is None:
                output = next((n for n in mat.node_tree.nodes
                               if n.type == 'OUTPUT_MATERIAL'), None)
            if output is not None:
                layout.template_node_view(mat.node_tree, output,
                                          output.inputs.get('Surface'))
        else:
            layout.prop(mat, "diffuse_color", text="Color")

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
    CustomRaytracerRenderEngine,
    RENDER_PT_custom_raytracer_sampling,
    RENDER_PT_custom_raytracer_light_paths,
    RENDER_PT_custom_raytracer_performance,
    WORLD_PT_custom_raytracer_surface,
    MATERIAL_PT_custom_raytracer_surface,
    CustomRaytracerPreferences,
    ASTRORAY_OT_add_black_hole, OBJECT_PT_astroray_black_hole,
]

# ---------------------------------------------------------------------- #
# Built-in panel compatibility
# ---------------------------------------------------------------------- #
#
# Blender's built-in Properties panels (Output, Dimensions, Color Management,
# Post Processing, Output, Metadata, World, Object, Mesh, Modifiers, etc.)
# only show up for a given render engine if that engine is listed in the
# panel class's COMPAT_ENGINES set. Cycles does this wholesale at add-on
# register time — every panel that advertises BLENDER_EEVEE / CYCLES compat
# gets CUSTOM_RAYTRACER appended too. Panels we explicitly DON'T want (engine-
# specific ones like Eevee Indirect Lighting, Cycles Ray Visibility, etc.)
# are excluded so they don't pollute our Properties editor.

def _is_compatible_panel(panel):
    if not hasattr(panel, 'COMPAT_ENGINES'):
        return False
    if 'BLENDER_RENDER' not in panel.COMPAT_ENGINES:
        return False
    # Skip panels we register ourselves
    if panel.__name__.startswith('RENDER_PT_custom_raytracer'):
        return False
    if panel.__name__.startswith('WORLD_PT_custom_raytracer'):
        return False
    if panel.__name__.startswith('MATERIAL_PT_custom_raytracer'):
        return False
    return True


_EXCLUDE_PANELS = {
    # Eevee-specific light-path / indirect-lighting panels
    'RENDER_PT_eevee_ambient_occlusion',
    'RENDER_PT_eevee_motion_blur',
    'RENDER_PT_eevee_next_motion_blur',
    'RENDER_PT_eevee_motion_blur_curve',
    'RENDER_PT_eevee_depth_of_field',
    'RENDER_PT_eevee_next_depth_of_field',
    'RENDER_PT_eevee_subsurface_scattering',
    'RENDER_PT_eevee_screen_space_reflections',
    'RENDER_PT_eevee_shadows',
    'RENDER_PT_eevee_next_shadows',
    'RENDER_PT_eevee_sampling',
    'RENDER_PT_eevee_next_sampling',
    'RENDER_PT_eevee_indirect_lighting',
    'RENDER_PT_eevee_next_indirect_lighting',
    'RENDER_PT_eevee_indirect_lighting_display',
    'RENDER_PT_eevee_film',
    'RENDER_PT_eevee_next_film',
    'RENDER_PT_eevee_hair',
    'RENDER_PT_eevee_performance',
    'RENDER_PT_eevee_next_performance',
    'RENDER_PT_eevee_next_volumetric',
    'RENDER_PT_eevee_next_volumetric_lighting',
    'RENDER_PT_eevee_next_volumetric_shadows',
    'RENDER_PT_eevee_next_horizon_scan',
    'RENDER_PT_eevee_next_raytracing',
    'RENDER_PT_eevee_next_screen_trace',
    'RENDER_PT_eevee_next_denoise',
    # Cycles-specific sampling panels (we have our own)
    'RENDER_PT_sampling_light_tree',
}


def _iter_compat_panels():
    for panel in bpy.types.Panel.__subclasses__():
        if panel.__name__ in _EXCLUDE_PANELS:
            continue
        if _is_compatible_panel(panel):
            yield panel


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.custom_raytracer = PointerProperty(type=CustomRaytracerRenderSettings)
    bpy.types.Material.custom_raytracer = PointerProperty(type=CustomRaytracerMaterialSettings)
    bpy.types.Object.astroray_black_hole = PointerProperty(type=AstrorayBlackHoleProperties)

    # Opt every compatible built-in panel into our engine.
    for panel in _iter_compat_panels():
        panel.COMPAT_ENGINES.add('CUSTOM_RAYTRACER')

    print("Astroray renderer addon registered")


def unregister():
    for panel in _iter_compat_panels():
        panel.COMPAT_ENGINES.discard('CUSTOM_RAYTRACER')

    del bpy.types.Scene.custom_raytracer
    del bpy.types.Material.custom_raytracer
    del bpy.types.Object.astroray_black_hole
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    print("Astroray renderer addon unregistered")


if __name__ == "__main__":
    register()

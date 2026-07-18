"""Astroray viewport scene exporter and per-domain caches.

Architectural pattern reference (NO code copied):
  - BlendLuxCore export/__init__.py (Exporter, ObjectCache2, MaterialCache,
    CameraCache, WorldCache, Change bitflags)
  - Radeon ProRender addon (view_update → sync_update, datablock-type dispatch)

This module owns scene sync and depsgraph-driven incremental dispatch. The
RenderEngine subclass delegates viewport-related calls here, keeping it a
thin shim that focuses on Blender's RenderEngine protocol.

Design:
  - Per-domain cache objects (Camera, Objects, Materials, Lights, World, Config)
    each implement diff(depsgraph) -> bool with REAL datablock-grained change
    detection (same logic as pkg56's _classify_depsgraph_update, but factored
    into the respective cache classes).
  - Exporter aggregates cache diff() results into Change bitflags and dispatches
    only the flagged uploaders, in the existing order (backend_config → env →
    materials → lights → geometry → transforms).
  - Behavior is IDENTICAL to pkg56 (refactor, not feature change).
  - Datablock-grained granularity (no per-property minimal diffs — RH4 non-goal).
"""

import time
import numpy as np
from enum import IntFlag


class Change(IntFlag):
    """Bitflags for scene-change classification. ORed together to represent
    a set of domains that need re-upload."""
    NONE = 0
    ENVIRONMENT = 1 << 0
    MATERIALS = 1 << 1
    LIGHTS = 1 << 2
    GEOMETRY = 1 << 3
    TRANSFORMS = 1 << 4
    BACKEND_CONFIG = 1 << 5
    ACCUMULATION_ONLY = 1 << 6


# bpy.types.ID subclass names used for classification. Uses class __name__
# (after walking the mro) so classification works under stub bpy (tests) and
# real Blender.
_DEPSGRAPH_ID_TYPE_NAMES = (
    'World', 'Light', 'Material', 'NodeTree', 'ShaderNodeTree',
    'Image', 'Object', 'Scene',
)


def _depsgraph_id_type_name(upd_id, bpy_module):
    """Return the bpy.types.ID subclass name for `upd_id`, or None if we
    can't classify it. Walks the mro so our stub-bpy tests (where
    Object/Light/etc. are plain Python classes) work the same way Blender's
    C-defined types do."""
    if upd_id is None:
        return None
    types_mod = getattr(bpy_module, 'types', None)
    if types_mod is not None:
        for name in _DEPSGRAPH_ID_TYPE_NAMES:
            t = getattr(types_mod, name, None)
            if isinstance(t, type) and isinstance(upd_id, t):
                return name
    for klass in type(upd_id).__mro__:
        if klass.__name__ in _DEPSGRAPH_ID_TYPE_NAMES:
            return klass.__name__
    return None


class CameraCache:
    """Tracks camera state and detects changes via depsgraph updates."""
    def __init__(self, bpy_module):
        self.bpy = bpy_module
        self._last_hash = None

    def diff(self, depsgraph) -> bool:
        """Camera changes aren't in depsgraph.updates (camera moves don't fire
        depsgraph events). Camera detection happens via hash comparison in
        view_draw. This cache always returns False for depsgraph-based diff."""
        return False


class ObjectsCache:
    """Tracks object geometry and transforms."""
    def __init__(self, bpy_module, renderer_object_id_for_fn):
        self.bpy = bpy_module
        self._renderer_object_id_for_fn = renderer_object_id_for_fn
        self._last_ids = set()

    def diff(self, depsgraph):
        """Check if objects/geometry changed. Returns
        (geometry: bool, flat_transforms: list[(obj_id, mat16)], xform_names: list[str]).

          - geometry: a real is_updated_geometry edit occurred.
          - flat_transforms: transform-only edits resolved via the flat
            renderer-object-id map (the update_object_transform path).
          - xform_names: names of transform-only edits with NO flat-map entry —
            candidates for the pkg114 inc-3d instanced-refit fast path or (if not
            instanced) a geometry promote. That decision needs the instance maps,
            which live on the engine, so the dispatcher classifies these.

        Note: is_updated_geometry subsumes is_updated_transform — rebuilding
        geometry already covers a moved object. Only transform-only edits
        route to the transform path."""
        updates = getattr(depsgraph, 'updates', None)
        if updates is None:
            return False, [], []

        geometry = False
        flat_transforms = []
        xform_names = []

        for upd in updates:
            upd_id = getattr(upd, 'id', None)
            type_name = _depsgraph_id_type_name(upd_id, self.bpy)
            if type_name != 'Object':
                continue

            is_geom = bool(getattr(upd, 'is_updated_geometry', False))
            is_xform = bool(getattr(upd, 'is_updated_transform', False))

            if is_geom:
                geometry = True
            elif is_xform:
                # Transform-only edit
                obj_id = self._renderer_object_id_for_fn(upd_id)
                if obj_id is None:
                    # No flat-map entry — hand the name to the dispatcher, which
                    # decides instanced-refit vs geometry-rebuild promote.
                    nm = getattr(upd_id, 'name', None)
                    if nm is not None:
                        xform_names.append(nm)
                    else:
                        geometry = True  # can't identify → safe full rebuild
                else:
                    try:
                        m = list(upd_id.matrix_world)
                        if m and hasattr(m[0], '__iter__'):
                            m = [float(x) for row in m for x in row]
                        flat_transforms.append((obj_id, m))
                    except Exception:
                        geometry = True

        return geometry, flat_transforms, xform_names


class MaterialsCache:
    """Tracks material definitions."""
    def __init__(self, bpy_module):
        self.bpy = bpy_module
        self._last_ids = set()

    def diff(self, depsgraph) -> bool:
        """Check if materials changed (Material/NodeTree/ShaderNodeTree/Image)."""
        updates = getattr(depsgraph, 'updates', None)
        if updates is None:
            return False

        for upd in updates:
            upd_id = getattr(upd, 'id', None)
            type_name = _depsgraph_id_type_name(upd_id, self.bpy)
            if type_name in ('Material', 'NodeTree', 'ShaderNodeTree', 'Image'):
                return True

        # Object.is_updated_shading also triggers material upload
        for upd in updates:
            upd_id = getattr(upd, 'id', None)
            type_name = _depsgraph_id_type_name(upd_id, self.bpy)
            if type_name == 'Object':
                if bool(getattr(upd, 'is_updated_shading', False)):
                    return True

        return False


class LightsCache:
    """Tracks light sources."""
    def __init__(self, bpy_module):
        self.bpy = bpy_module
        self._last_ids = set()

    def diff(self, depsgraph) -> bool:
        """Check if lights changed."""
        updates = getattr(depsgraph, 'updates', None)
        if updates is None:
            return False

        for upd in updates:
            upd_id = getattr(upd, 'id', None)
            type_name = _depsgraph_id_type_name(upd_id, self.bpy)
            if type_name == 'Light':
                return True

        return False


class WorldCache:
    """Tracks world/environment settings."""
    def __init__(self, bpy_module):
        self.bpy = bpy_module
        self._last_hash = None

    def diff(self, depsgraph) -> bool:
        """Check if world changed."""
        updates = getattr(depsgraph, 'updates', None)
        if updates is None:
            return False

        for upd in updates:
            upd_id = getattr(upd, 'id', None)
            type_name = _depsgraph_id_type_name(upd_id, self.bpy)
            if type_name == 'World':
                return True

        return False


class ConfigCache:
    """Tracks backend configuration (device_mode, etc.)."""
    def __init__(self, bpy_module):
        self.bpy = bpy_module
        self._last_config = {}

    def diff(self, depsgraph):
        """Check if backend config changed. Returns (backend_config: bool,
        accumulation_only: bool).

        Scene edits may affect backend config (device_mode) or just
        accumulation (frame change). Backend-affecting props get a real
        domain that routes to configure_backend_for_context."""
        updates = getattr(depsgraph, 'updates', None)
        if updates is None:
            return False, False

        backend_config = False
        accumulation_only = False

        for upd in updates:
            upd_id = getattr(upd, 'id', None)
            type_name = _depsgraph_id_type_name(upd_id, self.bpy)
            if type_name == 'Scene':
                backend_config = True
                accumulation_only = True

        return backend_config, accumulation_only


class Exporter:
    """Viewport scene exporter. Owns the persistent viewport renderer, tracks
    per-domain state via cache objects, and dispatches incremental updates.

    The RenderEngine subclass constructs one Exporter instance and delegates
    view_update / view_draw to it. The Exporter calls back into the engine's
    conversion methods (convert_materials, convert_objects, etc.) as needed.
    """

    def __init__(self, engine, bpy_module, astroray_module):
        """
        Args:
            engine: CustomRaytracerRenderEngine instance (callback target for
                conversion methods like convert_materials, setup_world, etc.)
            bpy_module: The `bpy` module (for bpy.types access)
            astroray_module: The `astroray` module (for Renderer construction)
        """
        self.engine = engine
        self.bpy = bpy_module
        self.astroray = astroray_module

        # Viewport session state (moved from RenderEngine)
        self._viewport_renderer = None
        self._viewport_texture = None
        self._viewport_width = 0
        self._viewport_height = 0
        self._viewport_full_synced = False  # pkg56-C: True after first full sync
        self._viewport_camera_hash = None
        self._viewport_camera_substantive_hash = None
        self._viewport_accum_pixels = None
        self._viewport_current_spp = 0
        self._viewport_target_spp = 0
        self._viewport_accum_key = None
        self._viewport_prewarmed_for_mode = None  # pkg84: CUDA kernel pre-warm state
        self._viewport_skip_upload_next = False  # pkg114 inc 3d: next render is a
        # TLAS-only refit → render(skip_upload=True); set by apply_depsgraph_updates,
        # consumed by view_update.

        # Per-domain caches
        self._camera_cache = CameraCache(bpy_module)
        self._objects_cache = ObjectsCache(bpy_module, self._renderer_object_id_for)
        self._materials_cache = MaterialsCache(bpy_module)
        self._lights_cache = LightsCache(bpy_module)
        self._world_cache = WorldCache(bpy_module)
        self._config_cache = ConfigCache(bpy_module)

    def _get_viewport_renderer(self):
        """Lazy-init the persistent viewport Renderer. Reused across
        view_update and view_draw so we don't reconstruct on every nudge."""
        if self._viewport_renderer is None:
            self._viewport_renderer = self.astroray.Renderer()
        return self._viewport_renderer

    def _reset_viewport_accumulation(self):
        self._viewport_accum_pixels = None
        self._viewport_current_spp = 0
        self._viewport_target_spp = 0
        self._viewport_accum_key = None

    def _renderer_object_id_for(self, blender_id):
        """Resolve a Blender Object → renderer primitive insertion id.
        Returns None if we have no mapping cached."""
        m = getattr(self.engine, '_renderer_object_id_map', None)
        if not m:
            return None
        try:
            return m.get(blender_id.name)
        except AttributeError:
            return None

    def apply_depsgraph_updates(self, renderer, depsgraph, settings,
                                configure_backend_fn, report_fn):
        """Bucket `depsgraph.updates` into domains via per-cache diff(), dispatch
        only the matching Phase B uploader(s). Returns one of:

          - 'fallback'   : caller must run sync_viewport_scene
                           (unrecognised update id or .updates absent).
          - 'idle'       : zero domain edits — caller skips upload AND render.
          - 'dispatched' : one or more uploaders ran — caller renders.

        Dispatch order (backend_config → env → materials → lights → geometry →
        transforms) matches Cycles `BlenderSync::sync_data()` so the device-state
        result is order-independent of Blender's iteration order over
        depsgraph.updates.
        """
        updates = getattr(depsgraph, 'updates', None)
        if updates is None:
            return 'fallback'

        # Query all caches; OR their results into a Change bitset (the
        # aggregator contract from the spec — dispatch below tests flags).
        changes = Change.NONE
        if self._world_cache.diff(depsgraph):
            changes |= Change.ENVIRONMENT
        if self._materials_cache.diff(depsgraph):
            changes |= Change.MATERIALS
        if self._lights_cache.diff(depsgraph):
            changes |= Change.LIGHTS
        geometry, flat_transforms, xform_names = self._objects_cache.diff(depsgraph)
        # pkg114 inc 3d: classify unresolved transform-only edits against the
        # engine's instance maps (populated by convert_objects on GPU only; empty
        # otherwise, so CPU / non-instanced scenes fall through unchanged).
        instance_map = getattr(self.engine, '_renderer_instance_id_map', None) or {}
        instancer_elig = getattr(self.engine, '_renderer_instancer_eligible', None) or {}

        def _fast_ok(nm):
            # Refit-able in place: an instanced source (duplis in the id map) or an
            # eligible instancer empty (all its duplis went through the shared BLAS).
            return (nm in instance_map) or (instancer_elig.get(nm) is True)

        def _related(nm):
            # Touches instancing at all — including a poisoned/nested instancer — so
            # a partial update would leave the scene inconsistent (→ full sync).
            return (nm in instance_map) or (nm in instancer_elig)

        instancing_related = any(_related(nm) for nm in xform_names)

        if geometry:
            changes |= Change.GEOMETRY
        if flat_transforms or xform_names:
            changes |= Change.TRANSFORMS
        backend_config, accumulation_only = self._config_cache.diff(depsgraph)
        if accumulation_only:
            changes |= Change.ACCUMULATION_ONLY

        # Check for unrecognised update types (fallback to full sync)
        for upd in updates:
            upd_id = getattr(upd, 'id', None)
            type_name = _depsgraph_id_type_name(upd_id, self.bpy)
            if type_name is None:
                # Unrecognised id type (skin modifier, particle system,
                # grease pencil, …). Fall back to full sync rather than
                # guess. Mirrors Cycles' has_updates_=true default.
                return 'fallback'
            # Also check for Object updates with no geometry/shading/transform bits
            # (selection-only) — these should be ignored, not trigger fallback
            if type_name == 'Object':
                is_geom = bool(getattr(upd, 'is_updated_geometry', False))
                is_xform = bool(getattr(upd, 'is_updated_transform', False))
                is_shading = bool(getattr(upd, 'is_updated_shading', False))
                if not (is_geom or is_xform or is_shading):
                    # Selection-only — ignore this update
                    continue

        # backend_config only counts as a real domain when settings is present
        if backend_config and settings is not None:
            changes |= Change.BACKEND_CONFIG

        if not (changes & ~Change.ACCUMULATION_ONLY):
            if changes & Change.ACCUMULATION_ONLY:
                # Frame/Scene tick — image unchanged but user may want fresh
                # accumulation. Reset and skip render.
                self._reset_viewport_accumulation()
            return 'idle'

        # pkg114 inc 3d — instanced transform-only dispatch decision. A PURE
        # transform batch (no other image-changing domain) where every changed
        # object is refit-able takes the TLAS-only fast path. A batch that touches
        # instancing any OTHER way (mixed flat+instanced, poisoned/nested instancer,
        # or transform + another domain) can't be kept consistent by a partial
        # update, so it full-syncs. Non-instanced transform-only edits keep the
        # pre-pkg114 behaviour: promote to a geometry rebuild.
        transform_only = (changes & ~(Change.TRANSFORMS | Change.ACCUMULATION_ONLY)) == 0
        do_refit = (transform_only and bool(xform_names) and not flat_transforms
                    and all(_fast_ok(nm) for nm in xform_names))
        if not do_refit and instancing_related:
            return 'fallback'
        if not do_refit and any(not _fast_ok(nm) for nm in xform_names):
            changes |= Change.GEOMETRY

        # pkg96 P2: reconcile-then-upload contract. Each domain re-derives
        # its state from Blender before pushing device buffers.
        if changes & Change.BACKEND_CONFIG:
            # Backend-affecting Scene props (device_mode) — reconfigure
            # before any render.
            configure_backend_fn(renderer, settings, report_fn)

        if changes & Change.ENVIRONMENT:
            # World update — re-parse the world tree before device upload.
            # Guard: tests may pass scene=None.
            if depsgraph.scene is not None:
                self.engine.setup_world(depsgraph.scene, renderer)
            renderer.upload_environment()

        if changes & Change.MATERIALS:
            renderer.upload_materials()
        if changes & Change.LIGHTS:
            renderer.upload_lights()
        if changes & Change.GEOMETRY:
            renderer.upload_geometry()
        elif do_refit:
            # pkg114 inc 3d: TLAS-only refit — push each instance's fresh
            # matrix_world in place, re-upload ONLY d_instances + d_tlas, then
            # signal the caller to render(skip_upload=True) from device state.
            self.engine.refit_instance_transforms(depsgraph, renderer)
            renderer.upload_instance_transforms()
            self._viewport_skip_upload_next = True
        elif changes & Change.TRANSFORMS:
            for obj_id, mat16 in flat_transforms:
                try:
                    renderer.update_object_transform(obj_id, mat16)
                except (RuntimeError, AttributeError, TypeError):
                    # Stale id (object removed) — skip; next full sync
                    # will pick the new state up.
                    pass

        # Any image-changing dispatch resets accumulation
        self._reset_viewport_accumulation()
        return 'dispatched'

    def sync_viewport_scene(self, renderer, depsgraph, settings,
                           configure_backend_fn, viewport_perf_record_fn,
                           effective_integrator_name_fn):
        """Push the depsgraph state into the renderer. Called from view_update
        only — view_draw skips this and just re-renders with a new camera."""
        renderer.set_adaptive_sampling(settings.use_adaptive_sampling)
        renderer.clear()
        renderer.set_clamp_direct(settings.clamp_direct)
        renderer.set_clamp_indirect(settings.clamp_indirect)
        renderer.set_filter_glossy(settings.filter_glossy)
        renderer.set_use_reflective_caustics(settings.use_reflective_caustics)
        renderer.set_use_refractive_caustics(settings.use_refractive_caustics)
        renderer.set_light_sampler(settings.light_sampler)

        t0 = time.perf_counter()
        material_map = self.engine.convert_materials(depsgraph, renderer)
        viewport_perf_record_fn("materials", t0)

        t0 = time.perf_counter()
        self.engine.convert_objects(depsgraph, renderer, material_map)
        viewport_perf_record_fn("geometry", t0)

        t0 = time.perf_counter()
        self.engine.convert_lights(depsgraph, renderer)
        viewport_perf_record_fn("lights", t0)

        t0 = time.perf_counter()
        self.engine.setup_world(depsgraph.scene, renderer)
        viewport_perf_record_fn("environment", t0)

        active_mode = configure_backend_fn(renderer, settings, self.engine.report,
                                          effective_integrator_name_fn(settings))

        # pkg84: CUDA kernel pre-warm
        if active_mode == 'gpu' and self._viewport_prewarmed_for_mode != 'gpu':
            try:
                temp = self.astroray.Renderer()
                temp.set_use_gpu(True)
                temp.prewarm_cuda()
                self._viewport_prewarmed_for_mode = 'gpu'
            except Exception:
                pass  # Pre-warm failure is non-fatal

        # Mark that renderer holds a coherent full snapshot
        self._viewport_full_synced = True

    def render_viewport_frame(self, renderer, context, settings, region,
                             reset_accumulation, engine_methods, skip_upload=False):
        """Set up camera, run render, update cached GPU texture.

        skip_upload (pkg114 inc 3d): render from the CURRENT device state without a
        full geometry re-upload — used after a TLAS-only instance-transform refit
        (update_instance_transform + upload_instance_transforms), so a transform-only
        edit of instanced objects pays only the cheap instance/TLAS re-push."""
        width = max(1, region.width)
        height = max(1, region.height)
        render_key = engine_methods['viewport_render_key'](context, settings, region)

        if reset_accumulation or render_key != self._viewport_accum_key:
            self._reset_viewport_accumulation()
            self._viewport_accum_key = render_key

        self._viewport_target_spp = engine_methods['viewport_target_samples'](settings)
        if self._viewport_current_spp >= self._viewport_target_spp:
            return False

        engine_methods['setup_viewport_camera'](renderer, context, width, height)

        # Wavelength + integrator policy
        lmin, lmax = engine_methods['wavelength_range_from_settings'](settings)
        renderer.set_wavelength_range(lmin, lmax)
        is_outside_visible = (lmax > 780.0 or lmin < 380.0)
        if is_outside_visible:
            renderer.set_output_mode("luminance")
        renderer.set_integrator(engine_methods['effective_integrator_name'](settings))

        # pkg62: viewport pass selector + OIDN toggle
        try:
            renderer.clear_passes()
        except AttributeError:
            pass
        viewport_display_pass = getattr(settings, "viewport_display_pass", "combined")
        if viewport_display_pass == "albedo":
            renderer.add_pass("albedo_aov")
        elif viewport_display_pass == "normal":
            renderer.add_pass("normal_aov")
        elif viewport_display_pass == "depth":
            renderer.add_pass("depth_aov")

        has_denoise = False
        if getattr(settings, "viewport_oidn", False) and not is_outside_visible:
            denoise_pass = engine_methods['resolve_denoiser_pass'](settings)
            if denoise_pass is not None:
                renderer.add_pass(denoise_pass)
                has_denoise = True

        # pkg96 P5: GPU limitations guard
        has_aov_passes = viewport_display_pass in {"albedo", "normal", "depth"}
        engine_methods['check_gpu_limitations_and_report'](
            renderer, settings, self.engine.report,
            has_passes=has_aov_passes, has_denoise=has_denoise)

        samples = engine_methods['viewport_chunk_samples'](settings, self._viewport_current_spp)
        if samples <= 0:
            return False

        depth = max(2, settings.max_bounces // 2)
        pixels = renderer.render(
            samples, depth, None, False,
            min(settings.diffuse_bounces, depth),
            min(settings.glossy_bounces, depth),
            min(settings.transmission_bounces, depth),
            min(settings.volume_bounces, depth),
            min(settings.transparent_bounces, depth),
            skip_upload
        )
        if pixels is None:
            return

        # pkg62: for compositor-style passes, fetch named buffer
        pixels_to_display = pixels
        if viewport_display_pass not in {"combined", "albedo", "normal", "depth"}:
            try:
                pixels_to_display = renderer.get_render_pass_buffer(viewport_display_pass)
            except Exception:
                pixels_to_display = pixels

        # Accumulate pixels
        chunk = np.asarray(pixels_to_display, dtype=np.float32)
        if self._viewport_accum_pixels is None or self._viewport_current_spp <= 0:
            self._viewport_accum_pixels = chunk.copy()
            self._viewport_current_spp = int(samples)
        else:
            old_spp = int(self._viewport_current_spp)
            new_spp = old_spp + int(samples)
            self._viewport_accum_pixels = (
                (self._viewport_accum_pixels * old_spp + chunk * int(samples))
                / float(new_spp)
            )
            self._viewport_current_spp = new_spp

        engine_methods['update_viewport_texture'](self._viewport_accum_pixels,
                                                  width, height)
        engine_methods['update_viewport_status'](self._viewport_current_spp,
                                                 self._viewport_target_spp)
        return True

    def view_update(self, context, depsgraph, raytracer_available,
                   configure_backend_fn, viewport_perf_record_fn,
                   viewport_perf_frame_complete_fn, effective_integrator_name_fn,
                   camera_state_hash_fn, camera_substantive_state_hash_fn,
                   request_viewport_redraw_fn, engine_methods):
        """Called when scene or viewport changes. Re-syncs scene into persistent
        viewport renderer and renders one frame.

        Camera-only changes (pan/zoom/orbit) are NOT routed here by Blender —
        they don't fire depsgraph updates. view_draw owns those."""
        import traceback
        if not raytracer_available:
            return

        scene = depsgraph.scene
        settings = scene.custom_raytracer
        region = context.region

        try:
            renderer = self._get_viewport_renderer()

            # pkg56-C: depsgraph-driven dispatch
            if not self._viewport_full_synced:
                dispatch = 'fallback'
            else:
                dispatch = self.apply_depsgraph_updates(
                    renderer, depsgraph, settings,
                    configure_backend_fn, self.engine.report)

            if dispatch == 'fallback':
                self.sync_viewport_scene(renderer, depsgraph, settings,
                                        configure_backend_fn,
                                        viewport_perf_record_fn,
                                        effective_integrator_name_fn)
                dispatch = 'dispatched'

            if dispatch == 'idle':
                # No domain edits — skip upload and render
                viewport_perf_frame_complete_fn()
                self._viewport_camera_hash = camera_state_hash_fn(context, region)
                self._viewport_camera_substantive_hash = camera_substantive_state_hash_fn(context, region)
                return

            # pkg114 inc 3d: consume the refit flag apply_depsgraph_updates may have
            # set this call — render from device state without a geometry re-upload.
            skip_upload = self._viewport_skip_upload_next
            self._viewport_skip_upload_next = False

            t0 = time.perf_counter()
            self.render_viewport_frame(renderer, context, settings, region,
                                      reset_accumulation=True,
                                      engine_methods=engine_methods,
                                      skip_upload=skip_upload)
            viewport_perf_record_fn("render", t0)
            viewport_perf_frame_complete_fn()

            # Stamp camera hash
            self._viewport_camera_hash = camera_state_hash_fn(context, region)
            self._viewport_camera_substantive_hash = camera_substantive_state_hash_fn(context, region)

            if self._viewport_current_spp < self._viewport_target_spp:
                request_viewport_redraw_fn()

        except Exception as e:
            print(f"Astroray viewport preview error: {e}")
            traceback.print_exc()

    def view_draw(self, context, depsgraph, raytracer_available,
                 configure_backend_fn, viewport_perf_record_fn,
                 effective_integrator_name_fn, camera_state_hash_fn,
                 camera_substantive_state_hash_fn,  request_viewport_redraw_fn,
                 engine_methods):
        """Called every frame inside rendered-shading mode. Detects camera changes
        and re-renders without touching scene state. Otherwise blits cached texture."""
        import traceback
        if not raytracer_available:
            return

        try:
            region = context.region
            scene = depsgraph.scene
            settings = scene.custom_raytracer

            # Camera-change detection
            new_hash = camera_state_hash_fn(context, region)
            target_spp = engine_methods['viewport_target_samples'](settings)
            render_key = engine_methods['viewport_render_key'](context, settings, region)

            camera_changed = (new_hash is not None and new_hash != self._viewport_camera_hash)
            needs_progress = int(self._viewport_current_spp) < target_spp
            settings_changed = render_key != self._viewport_accum_key

            # pkg83: distinguish substantive camera changes from pure transforms
            new_substantive_hash = camera_substantive_state_hash_fn(context, region)
            camera_substantive_changed = (
                new_substantive_hash is not None
                and new_substantive_hash != self._viewport_camera_substantive_hash
            )

            if camera_changed or needs_progress or settings_changed or self._viewport_texture is None:
                renderer = self._get_viewport_renderer()
                # If user opened rendered-shading without ever firing view_update,
                # renderer has no scene. Fall back to full sync.
                if self._viewport_texture is None:
                    self.sync_viewport_scene(renderer, depsgraph, settings,
                                            configure_backend_fn,
                                            viewport_perf_record_fn,
                                            effective_integrator_name_fn)

                self.render_viewport_frame(
                    renderer, context, settings, region,
                    reset_accumulation=(camera_substantive_changed or settings_changed),
                    engine_methods=engine_methods
                )
                self._viewport_camera_hash = new_hash
                self._viewport_camera_substantive_hash = new_substantive_hash

                if self._viewport_current_spp < self._viewport_target_spp:
                    request_viewport_redraw_fn()

            if self._viewport_texture is None:
                return

            # Lazy gpu import AT THE BLIT SITE — mirrors the pre-refactor
            # view_draw. Importing at the top of the frame would abort the
            # whole draw (including the re-render) in environments without
            # the gpu module (headless tests stub bpy but not gpu).
            import gpu  # noqa: F401 — needed by draw_texture_2d's GPUTexture
            from gpu_extras.presets import draw_texture_2d

            # Cycles/Eevee bind_display_space_shader pattern
            self.engine.bind_display_space_shader(scene)
            draw_texture_2d(self._viewport_texture, (0, 0), region.width, region.height)
            self.engine.unbind_display_space_shader()

        except Exception as e:
            print(f"Astroray view_draw error: {e}")
            traceback.print_exc()

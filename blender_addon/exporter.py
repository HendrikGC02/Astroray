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

import os
import queue
import threading
import time
import numpy as np
from enum import IntFlag


# pkg241 Phase 2 A2 spike: the off-thread viewport worker is gated on this env
# var, read once at engine start (design §9 "code touched"). With it unset the
# synchronous path (view_update/view_draw -> render_viewport_frame) is unchanged
# and byte-identical to origin/main (design test 10). Read via a helper so tests
# can monkeypatch the module global directly.
def viewport_worker_enabled():
    """True when ASTRORAY_VIEWPORT_WORKER is set to a truthy value (1/true/on)."""
    v = os.environ.get("ASTRORAY_VIEWPORT_WORKER", "")
    return v.strip().lower() in ("1", "true", "on", "yes")


# pkg241 Phase 2 A2 spike (§9 event schema): an optional module-level sink for
# the generation-tagged lifeline events. The benchmark recorder installs a
# callback here; the worker/main-thread commit emit through it. None in
# production (zero overhead beyond the None check). Signature:
#   sink(name, generation, t_perf_counter, session_epoch, extra_dict)
_spike_event_sink = None

# pkg241 Phase 2 A2 spike (§3.6): process-global quarantine for workers that did
# not acknowledge exit within the teardown timeout. Retaining a STRONG ref keeps
# the leaked renderer alive so Python finalisation cannot destroy it out from
# under a still-running worker thread (never a use-after-free). Terminal.
_WORKER_QUARANTINE = []


def _emit_spike_event(name, generation, session_epoch, **extra):
    """Emit a §9 lifeline event if a sink is installed (recorder-only)."""
    sink = _spike_event_sink
    if sink is not None:
        try:
            sink(name, generation, time.perf_counter(), session_epoch, extra)
        except Exception:
            pass  # a broken recorder sink must never perturb the render path


# pkg196: reduced-resolution viewport navigation.
# Cycles reference: intern/cycles/blender/session.cpp
# BlenderSession::reset + `start_resolution` (Apache-2.0). Cycles renders
# navigation frames at a reduced `start_resolution` and progressively resolves
# to full resolution once the view settles. We mirror that: while the camera is
# actively moving, render at region.width/N x region.height/N and upscale on
# display (draw_texture_2d bilinear), then snap back to full res on settle and
# hand off to the pkg191 progressive still-frame loop. Accumulation is reset on
# every resolution switch so mixed-resolution buffers are never blended.
VIEWPORT_NAV_RES_DIVISOR = 2   # render W/2 x H/2 while the camera is moving.
VIEWPORT_NAV_SETTLE_S = 0.25   # snap back to full res after this quiet window.

# pkg241 Phase 1: interactive-resolution budget. On the "expensive profile"
# (an edit whose estimated full-resolution render exceeds the interaction
# budget) start a fresh edit coarse (W/4 x H/4) for a fast first present, then
# refine one rung toward full res on each settled frame (4 -> 2 -> 1). This
# extends the pkg196 navigation divisor rather than adding a parallel ladder.
# VIEWPORT_INTERACTIVE_BUDGET_MS is the pinned GPU edit->present p95 gate; the
# coarse start engages only above this measured threshold so cheap scenes keep
# rendering full res immediately.
VIEWPORT_START_RES_DIVISOR = 4       # coarse first present on the expensive profile.
VIEWPORT_INTERACTIVE_BUDGET_MS = 100.0  # pinned edit->present p95 budget (GPU).


def _nav_clock():
    """Monotonic clock for the nav-settle debounce (patchable in tests)."""
    return time.perf_counter()


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


class _ViewportSpikeWorker:
    """pkg241 Phase 2 A2 spike — the off-thread viewport render worker (design
    §3.2-§3.4). Single-viewport, GPU-only, camera + material generations. NOT the
    production worker: no multi-viewport arbiter, no F12 gate, no denoise, no full
    lifecycle owner (those are P2.2, after GO).

    Threading contract (§3.1/§3.2/§3.5):
      - A single spike-local token (a threading.Lock). The MAIN thread acquires it,
        commits the snapshot into the persistent renderer (setupCamera + set_* +
        upload_*, via the injected commit_fn), then hands the token to the worker
        for the render() call only. The WORKER releases the token when it reaches
        idle (after render + pass extraction). threading.Lock permits release by a
        different thread than acquired it, which is exactly the hand-off we need.
        At any instant exactly one holder owns the token (main during commit,
        worker during render, or nobody while IDLE) — the §9 single-holder proof.
      - The worker never touches bpy/GPUTexture/tag_redraw. It calls only the
        injected render_fn (renderer.render + get_render_pass_buffer + numpy
        accumulate) on its own daemon thread, publishes each completed chunk into a
        depth-1 latest-frame mailbox, and pushes idle/error onto a separate control
        queue. A main-thread pump (present_fn + the state machine) drains both.

    This class is bpy-free so it is unit-testable with stubbed render/present/report
    callables (tests/test_pkg241_spike_worker.py)."""

    IDLE = "IDLE"
    RENDERING = "RENDERING"
    STOPPING = "STOPPING"
    DEAD = "DEAD"

    def __init__(self, render_fn, present_fn, report_fn=None, session_epoch=0):
        # render_fn(job, cancel_check, publish) -> None  [WORKER thread, under token]
        #   job: the committed snapshot dict; cancel_check() -> bool (True = stop);
        #   publish(buffer, width, height) -> None publishes a chunk for this gen.
        self._render_fn = render_fn
        # present_fn(buffer, width, height, generation) -> None  [MAIN thread]
        self._present_fn = present_fn
        # report_fn(message) -> None  [MAIN thread] — surfaces worker errors.
        self._report_fn = report_fn
        self.session_epoch = session_epoch

        self._token = threading.Lock()
        self._token_holder = None  # 'main' | 'worker' | None (ownership trace)

        # depth-1 latest-frame mailbox (§3.3): a newer frame REPLACES an unconsumed
        # older one; depth never exceeds 1. Protected by _mailbox_lock.
        self._mailbox = None       # (generation, buffer, width, height) or None
        self._mailbox_lock = threading.Lock()
        self.mailbox_depth = 0
        self.mailbox_depth_max = 0

        # control/error queue (§3.3) — never dropped, unlike stale frames.
        self._control = queue.Queue(maxsize=64)

        self.desired_generation = 0     # newest generation the edits have requested
        self.in_flight_generation = None
        self.submitted_generation = None
        self.state = self.IDLE

        # present accounting (§9 present-rate rule)
        self.completed_generations = 0  # generations that reached render_end unsuperseded
        self.presents = 0               # frames actually presented

        self._cancel_event = threading.Event()
        self._current_job = None
        self._job_ready = threading.Event()
        self._stop_worker = False
        self._thread = threading.Thread(
            target=self._worker_loop, name="astroray-viewport-spike", daemon=True)

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        self._thread.start()

    def is_alive(self):
        return self._thread.is_alive()

    # -- main-thread API ---------------------------------------------------
    def request(self):
        """Main thread, on an edit (view_update material / view_draw camera):
        bump desired_generation and request cancel of any in-flight chunk (§3.4).
        Non-blocking: does NOT commit or join. Returns the new desired generation."""
        self.desired_generation += 1
        _emit_spike_event("request", self.desired_generation, self.session_epoch)
        # pkg241 P2.2 item 4 (Terra review 4): emit cancel_request only for the
        # actual in-flight generation, and only on the false->true transition of
        # the cancel flag. A request while IDLE (nothing in flight) or a repeated
        # request for an already-cancelling render is NOT a cancel of a real
        # render — recording those made the settle cancel p99 pair with an
        # unrelated idle and go invalid. The cancel is tagged with the in-flight
        # generation g so the reducer can pair it with idle_ack(g)/idle_drain(g).
        if self.in_flight_generation is not None and not self._cancel_event.is_set():
            _emit_spike_event("cancel_request", self.in_flight_generation,
                              self.session_epoch)
        self._cancel_event.set()
        return self.desired_generation

    def maybe_submit(self, commit_fn):
        """Main thread (has bpy context): if the worker is IDLE and a newer
        generation is desired, acquire the token, commit the snapshot for
        desired_generation via commit_fn (setupCamera + set_* + upload_*), and
        hand the token to the worker for render() only (§3.2). Returns True if a
        job was submitted. commit_fn() -> job(dict) for this generation."""
        if self.state != self.IDLE:
            return False
        if self.desired_generation == self.submitted_generation:
            return False
        gen = self.desired_generation
        # Acquire the token on behalf of the worker (single-holder handoff, §3.5).
        if not self._token.acquire(blocking=False):
            return False  # a stale hold (should not happen while IDLE) — defer
        self._token_holder = "main"
        _emit_spike_event("token_acquire", gen, self.session_epoch, holder="main")
        _emit_spike_event("commit_start", gen, self.session_epoch)
        try:
            job = commit_fn(gen)
        except Exception as exc:
            self._token_holder = None
            self._token.release()
            self._fail(gen, exc)
            return False
        _emit_spike_event("commit_end", gen, self.session_epoch)
        # Hand the token to the worker; it releases at idle.
        self._token_holder = "worker"
        self._cancel_event.clear()
        self._current_job = job
        self.in_flight_generation = gen
        self.submitted_generation = gen
        self.state = self.RENDERING
        self._job_ready.set()
        return True

    def pump(self, present=True):
        """Advance the session state machine (§3.4).

        Always drains the control queue (idle/error notifications — bpy-free, safe
        from any main-thread context, including a bpy.app.timers callback). The
        mailbox drain, which builds a GPUTexture via present_fn, is gated on
        `present`: it MUST run only from a real GPU draw context (view_draw), never
        from the bpy.app.timers liveness pump.

        pkg241 P2.2 item 1 (present-wiring fix): the spike called pump() with the
        present branch from BOTH view_draw and the ~60 Hz timer. Creating a
        GPUTexture off a draw context is unsafe and raised (swallowed by the
        timer's try/except); because _drain_mailbox clears the depth-1 mailbox
        before presenting, the only pending frame was consumed and lost before
        view_draw could present it in a valid context, so _viewport_texture stayed
        None and the blit fell through to Blender's grid. The timer now calls
        pump(present=False) (state advance + tag_redraw only); view_draw calls
        pump() (present=True) inside its draw context, where the GPUTexture upload
        and blit are valid."""
        self._drain_control()
        if present:
            self._drain_mailbox()

    def stop(self, timeout=5.0):
        """Main thread teardown (§3.4/§3.6): request cancel and PUMP the control
        queue (yielding the GIL via queue.get timeout so the worker's cancel
        callback can run) until the worker acknowledges exit, bounded by `timeout`.
        Returns True if the worker acknowledged and the thread joined (safe to
        release the renderer); False on timeout (no-ack: quarantine — the caller
        must keep a STRONG ref and never destroy the renderer, §3.6)."""
        self.state = self.STOPPING
        self._cancel_event.set()
        self._stop_worker = True
        self._job_ready.set()  # wake a parked worker
        deadline = time.monotonic() + float(timeout)
        acked = self.in_flight_generation is None
        while not acked and time.monotonic() < deadline:
            try:
                kind, gen, epoch, payload = self._control.get(timeout=0.05)
            except queue.Empty:
                continue
            if kind == "idle" and gen == self.in_flight_generation:
                self.in_flight_generation = None
                acked = True
            elif kind == "error":
                acked = True  # a dead worker is also "not rendering"
        if self._thread.is_alive():
            self._thread.join(timeout=max(0.0, deadline - time.monotonic()))
        return not self._thread.is_alive()

    # -- internals ---------------------------------------------------------
    def _fail(self, generation, exc):
        self.state = self.DEAD
        if self._report_fn is not None:
            try:
                self._report_fn(f"Astroray viewport worker error (gen {generation}): {exc}")
            except Exception:
                pass

    def _drain_control(self):
        """Validate control-plane notifications by class (§3.4): idle/exited
        against the IN-FLIGHT generation (so a late idle(N) after desired N+2
        still advances the machine); errors for the current session/epoch even
        when their generation is superseded."""
        while True:
            try:
                kind, gen, epoch, payload = self._control.get_nowait()
            except queue.Empty:
                return
            if kind == "idle":
                if epoch != self.session_epoch:
                    continue  # a fully torn-down session — drop
                if gen == self.in_flight_generation:
                    self.in_flight_generation = None
                    if self.state == self.RENDERING:
                        self.state = self.IDLE
                    # pkg241 P2.2 item 3: the idle notification is DRAINED here, on
                    # the main thread. idle_ack was emitted worker-side at enqueue;
                    # idle_drain marks when the main-thread pump actually consumed
                    # it (which waits behind any in-progress commit — bounded by
                    # item 2). cancel_request -> idle_drain is the true end-to-end
                    # cancel-ack the p99 <= 300 ms gate is measured against.
                    _emit_spike_event("idle_drain", gen, self.session_epoch)
            elif kind == "error":
                # Errors are never dropped for a superseded generation (a
                # superseded render can still corrupt the shared WfContext); only
                # a session/epoch mismatch discards them.
                if epoch == self.session_epoch:
                    self._fail(gen, payload)

    def _drain_mailbox(self):
        """Present the mailbox's frame iff it is the current desired generation
        and epoch (data-plane validation, §3.4) — this preserves 'no stale present
        after an edit'. A superseded frame is discarded, never blitted."""
        with self._mailbox_lock:
            frame = self._mailbox
            self._mailbox = None
            depth_before = self.mailbox_depth
            self.mailbox_depth = 0
        if frame is None:
            return
        gen, buffer, width, height = frame
        _emit_spike_event("mailbox_dequeue", gen, self.session_epoch,
                          depth_before=depth_before)
        if gen == self.desired_generation and self.state != self.DEAD:
            self._present_fn(buffer, width, height, gen)
            self.presents += 1
            _emit_spike_event("texture_upload_end", gen, self.session_epoch)
        # else: superseded — discarded (no stale present).

    def _publish_frame(self, generation, buffer, width, height):
        """Worker thread: publish a completed chunk into the depth-1 mailbox,
        REPLACING any unconsumed older frame (§3.3). Depth never exceeds 1."""
        with self._mailbox_lock:
            self._mailbox = (generation, buffer, width, height)
            self.mailbox_depth = 1
            if self.mailbox_depth > self.mailbox_depth_max:
                self.mailbox_depth_max = self.mailbox_depth
        _emit_spike_event("mailbox_enqueue", generation, self.session_epoch,
                          depth_after=1)

    def _worker_loop(self):
        """Worker daemon thread: wait for a committed job, render it (holding the
        token the main thread handed over), publish chunks, then release the token
        and enqueue idle. Only render_fn touches native code; no bpy here."""
        while not self._stop_worker:
            if not self._job_ready.wait(timeout=0.1):
                continue
            self._job_ready.clear()
            job = self._current_job
            self._current_job = None
            if job is None:
                continue
            gen = job.get("generation")
            _emit_spike_event("render_start", gen, self.session_epoch)
            superseded_or_error = False
            try:
                def cancel_check():
                    return self._cancel_event.is_set()

                def publish(buffer, width, height):
                    self._publish_frame(gen, buffer, width, height)

                self._render_fn(job, cancel_check, publish)
                _emit_spike_event("render_end", gen, self.session_epoch)
                if not self._cancel_event.is_set():
                    self.completed_generations += 1
            except Exception as exc:  # worker exception (§3.9): store + report
                superseded_or_error = True
                self._control.put(("error", gen, self.session_epoch, exc))
                _emit_spike_event("error", gen, self.session_epoch)
            finally:
                # pkg241 P2.2 item 4 (Terra review 4): release the token BEFORE
                # enqueueing the idle notification. The main-thread pump that
                # consumes idle immediately tries to acquire the token for the next
                # commit; releasing first removes the race where the pump sees idle
                # but the worker has not yet dropped the token.
                if self._token_holder == "worker":
                    self._token_holder = None
                    _emit_spike_event("token_release", gen, self.session_epoch)
                    try:
                        self._token.release()
                    except RuntimeError:
                        pass  # already released (defensive)
                # Report idle so the main-thread pump can advance the machine.
                self._control.put(("idle", gen, self.session_epoch, None))
                _emit_spike_event("idle_ack", gen, self.session_epoch)
            del superseded_or_error


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
        # pkg196: reduced-resolution navigation state. _viewport_render_divisor is
        # the resolution divisor of the LAST rendered frame (1 = full res);
        # _viewport_nav_last_change_time is the _nav_clock() timestamp of the most
        # recent camera move, used for the settle debounce in view_draw.
        self._viewport_render_divisor = 1
        self._viewport_nav_last_change_time = 0.0
        # pkg241 Phase 1: present-first + interactive-resolution budget.
        # _viewport_present_pending is set when view_update renders and caches a
        # fresh texture it does NOT blit; the next view_draw presents that texture
        # before scheduling its own refinement chunk (removes the material
        # double-render). _viewport_last_full_render_ms is the last render's wall
        # time scaled to full resolution, the measured signal that engages the
        # coarse starting divisor above the interaction budget.
        self._viewport_present_pending = False
        self._viewport_last_full_render_ms = 0.0
        # pkg241 Phase 1b: cooperative-cancellation request flag. Set by
        # view_update / view_draw when a newer camera/settings edit supersedes
        # an in-flight or pending refinement chunk; consumed at the start of
        # render_viewport_frame (drops the cancelled chunk's partial
        # accumulation so it never blends with the new state) and read live by
        # the progress callback passed to renderer.render (returns
        # not _viewport_cancel_requested). In the current synchronous model a
        # chunk is atomic, so this is the plumbing the Phase 2 off-thread
        # render will flip; today it guarantees no mixed accumulation.
        self._viewport_cancel_requested = False

        # pkg241 Phase 2 A2 spike: the off-thread render worker + its liveness
        # timer. Created lazily on the first worker-path view_update/view_draw
        # (only when ASTRORAY_VIEWPORT_WORKER is set); None on the synchronous
        # path, so the default behaviour is unchanged. _worker_engine_methods /
        # _worker_redraw_fn cache the main-thread callables the pump needs.
        self._worker = None
        self._worker_timer = None
        self._worker_engine_methods = None
        self._worker_redraw_fn = None
        # pkg241 P2.2 item 2 (bounded commit): True when a scene/material edit
        # arrived while the worker was busy (token held) and therefore could not
        # be committed incrementally with its live depsgraph. The deferred commit
        # (next idle view_draw) falls back to a full sync_viewport_scene; an
        # edit committed immediately while the worker is idle uses the cheaper
        # incremental apply_depsgraph_updates dispatch instead.
        self._worker_deferred_scene = False

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

    def _request_viewport_cancel(self):
        """pkg241 Phase 1b: request cancellation of the in-flight/pending
        viewport chunk. render_viewport_frame consumes the flag before the
        next render."""
        self._viewport_cancel_requested = True

    def _consume_viewport_cancel(self):
        """pkg241 Phase 1b: if a cancel was requested, drop the cancelled
        chunk's partial accumulation (no mixed accumulation across the
        camera/settings change that requested it) and clear the flag. Returns
        True if a cancel was consumed."""
        if not self._viewport_cancel_requested:
            return False
        self._reset_viewport_accumulation()
        self._viewport_cancel_requested = False
        return True

    def _budget_start_divisor(self):
        """pkg241 Phase 1: interactive-resolution budget. Return the coarse
        starting divisor for a fresh edit when the last render's estimated
        full-resolution wall time exceeds VIEWPORT_INTERACTIVE_BUDGET_MS, else 1
        (full res). The estimate (_viewport_last_full_render_ms) is measured, so
        the coarse profile engages only above the threshold and cheap scenes
        render full res immediately (Cycles start_resolution analogue)."""
        if self._viewport_last_full_render_ms > VIEWPORT_INTERACTIVE_BUDGET_MS:
            return VIEWPORT_START_RES_DIVISOR
        return 1

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
        # pkg217: mirrors CustomRaytracerRenderEngine.convert_scene's wiring
        # (blender_addon/__init__.py) — the GPU photon-map caustic pre-pass
        # (pkg113) needs this SEPARATE renderer-level master switch on top of
        # the per-object is_caustic_caster flag, or a flagged glass caster
        # renders a black shadow in the viewport too.
        if hasattr(renderer, "set_use_photon_caustics"):
            has_caster = any(
                bool(getattr(getattr(inst.object, "astroray_object", None),
                             "is_caustic_caster", False))
                for inst in depsgraph.object_instances
                if inst.object is not None
            )
            renderer.set_use_photon_caustics(has_caster)
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
                             reset_accumulation, engine_methods, skip_upload=False,
                             res_divisor=1):
        """Set up camera, run render, update cached GPU texture.

        skip_upload (pkg114 inc 3d): render from the CURRENT device state without a
        full geometry re-upload — used after a TLAS-only instance-transform refit
        (update_instance_transform + upload_instance_transforms), so a transform-only
        edit of instanced objects pays only the cheap instance/TLAS re-push.

        res_divisor (pkg196): render at region.width/N x region.height/N while the
        camera is moving (N>1), upscaled on display. A change of divisor is a
        resolution switch and resets accumulation so reduced- and full-resolution
        buffers are never blended (Cycles start_resolution semantics)."""
        res_divisor = max(1, int(res_divisor))
        width = max(1, region.width // res_divisor)
        height = max(1, region.height // res_divisor)
        render_key = engine_methods['viewport_render_key'](context, settings, region)

        # pkg241 Phase 1b: if a cancel was requested (a newer camera/settings
        # edit superseded the in-flight/pending chunk), drop that chunk's
        # partial accumulation before starting this render so the two states
        # never blend (no mixed accumulation).
        self._consume_viewport_cancel()

        if (reset_accumulation or render_key != self._viewport_accum_key
                or res_divisor != self._viewport_render_divisor):
            self._reset_viewport_accumulation()
            self._viewport_accum_key = render_key
        self._viewport_render_divisor = res_divisor

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
        # pkg241 Phase 1b: pass a real cooperative-cancellation callback
        # (returns not _viewport_cancel_requested) instead of None, so the
        # native CPU tile loop / GPU wavefront can stop when a cancel is
        # requested. In the current synchronous model the flag cannot flip
        # mid-call, so ordinary completion is unchanged.
        def _viewport_progress(_frac):
            return not self._viewport_cancel_requested
        _render_t0 = time.perf_counter()
        pixels = renderer.render(
            samples, depth, _viewport_progress, False,
            min(settings.diffuse_bounces, depth),
            min(settings.glossy_bounces, depth),
            min(settings.transmission_bounces, depth),
            min(settings.volume_bounces, depth),
            min(settings.transparent_bounces, depth),
            skip_upload
        )
        if pixels is None:
            return
        # pkg241 Phase 1: record the render cost scaled to full resolution so the
        # interactive-resolution budget can engage the coarse starting divisor on
        # expensive edits. render() cost is roughly pixel-count bound, so a
        # divisor-N reduced render estimates the full-res cost as t * N^2.
        _render_ms = (time.perf_counter() - _render_t0) * 1000.0
        self._viewport_last_full_render_ms = _render_ms * (res_divisor * res_divisor)

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

        # pkg241 Phase 2 A2 spike: route material/scene edits through the
        # off-thread worker when the flag is set (§9). Synchronous path unchanged
        # when unset.
        if viewport_worker_enabled():
            self._worker_view_update(
                context, depsgraph, configure_backend_fn,
                effective_integrator_name_fn, viewport_perf_record_fn,
                camera_state_hash_fn, camera_substantive_state_hash_fn,
                request_viewport_redraw_fn, engine_methods)
            return

        scene = depsgraph.scene
        settings = scene.custom_raytracer
        # pkg176 Stage 1: resolve native Blender/Cycles settings for the
        # DIRECT-mapped controls (deprecated custom aliases). view_update fires on
        # scene edits, so log the per-render migration note here (not per frame).
        resolve_fn = engine_methods.get('resolve_settings')
        if resolve_fn is not None:
            settings = resolve_fn(scene, self.engine.report)
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

            # pkg241 Phase 1: render this scene-edit chunk at the interactive-
            # resolution budget's starting divisor (coarse first present on the
            # expensive profile), then flag it so the next view_draw presents THIS
            # texture before scheduling its own refinement chunk — removing the
            # material double-render (view_update render + a second view_draw
            # render before the first present).
            start_divisor = self._budget_start_divisor()
            t0 = time.perf_counter()
            produced = self.render_viewport_frame(
                renderer, context, settings, region,
                reset_accumulation=True,
                engine_methods=engine_methods,
                skip_upload=skip_upload,
                res_divisor=start_divisor)
            viewport_perf_record_fn("render", t0)
            viewport_perf_frame_complete_fn()
            if produced:
                self._viewport_present_pending = True

            # Stamp camera hash
            self._viewport_camera_hash = camera_state_hash_fn(context, region)
            self._viewport_camera_substantive_hash = camera_substantive_state_hash_fn(context, region)

            # Refine to full res / target SPP: pump a redraw while below the SPP
            # target OR while still below full resolution (divisor > 1).
            if (self._viewport_current_spp < self._viewport_target_spp
                    or self._viewport_render_divisor > 1):
                request_viewport_redraw_fn()

        except Exception as e:
            print(f"Astroray viewport preview error: {e}")
            traceback.print_exc()

    def view_draw(self, context, depsgraph, raytracer_available,
                 configure_backend_fn, viewport_perf_record_fn,
                 viewport_perf_frame_complete_fn,
                 effective_integrator_name_fn, camera_state_hash_fn,
                 camera_substantive_state_hash_fn,  request_viewport_redraw_fn,
                 engine_methods):
        """Called every frame inside rendered-shading mode. Detects camera changes
        and re-renders without touching scene state. Otherwise blits cached texture."""
        import traceback
        if not raytracer_available:
            return

        # pkg241 Phase 2 A2 spike: off-thread worker path (§9). view_draw is
        # reduced to: detect a camera edit -> bump generation + request cancel;
        # pump the worker (present the freshest published frame); commit + submit
        # the desired generation when the worker is idle; blit the latest frame.
        if viewport_worker_enabled():
            self._worker_view_draw(
                context, depsgraph, configure_backend_fn,
                effective_integrator_name_fn, viewport_perf_record_fn,
                camera_state_hash_fn, camera_substantive_state_hash_fn,
                request_viewport_redraw_fn, engine_methods)
            return

        try:
            region = context.region
            scene = depsgraph.scene
            settings = scene.custom_raytracer
            # pkg176 Stage 1: native-settings view. view_draw runs per frame, so
            # resolve silently (report=None) to avoid spamming the migration note.
            resolve_fn = engine_methods.get('resolve_settings')
            if resolve_fn is not None:
                settings = resolve_fn(scene, None)

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

            # pkg241 Phase 1b: a substantive camera change or a settings edit
            # supersedes any in-flight / pending refinement chunk. Request
            # cancellation so render_viewport_frame drops the cancelled chunk's
            # partial accumulation (these are exactly the cases that already
            # reset accumulation, so ordinary progressive refine at a fixed
            # view/settings is untouched — no new resets).
            if camera_substantive_changed or settings_changed:
                self._request_viewport_cancel()

            # pkg196 + pkg241 Phase 1: reduced-resolution navigation / interactive-
            # resolution budget. While the camera is actively moving (changed this
            # frame) OR still inside the settle window after the last move, render
            # at a reduced divisor and upscale; once the view has been quiet for
            # VIEWPORT_NAV_SETTLE_S, refine one rung toward full res on each frame
            # (4 -> 2 -> 1) and hand off to the pkg191 progressive loop at full res.
            # Cycles start_resolution analogue (session.cpp BlenderSession::reset).
            now = _nav_clock()
            if camera_changed:
                self._viewport_nav_last_change_time = now
            within_settle = (
                (now - self._viewport_nav_last_change_time) < VIEWPORT_NAV_SETTLE_S)
            # pkg241 Phase 1: a camera move starts coarse at the interaction
            # budget's divisor (at least the pkg196 divisor-2 floor); while the
            # view is settling, hold the current divisor; once settled but still
            # below full res, step down one rung; at full res stay at 1.
            if not self._viewport_full_synced:
                desired_divisor = 1
            elif camera_changed:
                desired_divisor = max(VIEWPORT_NAV_RES_DIVISOR,
                                      self._budget_start_divisor())
            elif within_settle and self._viewport_render_divisor > 1:
                desired_divisor = self._viewport_render_divisor
            elif self._viewport_render_divisor > 1:
                desired_divisor = max(1, self._viewport_render_divisor // 2)
            else:
                desired_divisor = 1
            resolution_switch = (desired_divisor != self._viewport_render_divisor)

            # pkg241 Phase 1: present-first. view_update rendered and cached a
            # fresh texture but does not blit it; present THAT texture before
            # scheduling the next refinement chunk, so a scene/material edit pays
            # one render before first present instead of two. Only present-first
            # when the pending texture still matches the current view (no camera
            # or settings change since it was rendered) — never blit a stale cache.
            present_pending = (self._viewport_present_pending
                               and not camera_changed and not settings_changed)

            render_needed = (camera_changed or needs_progress or settings_changed
                             or self._viewport_texture is None or resolution_switch)

            if present_pending:
                # Show the fresh view_update chunk now; defer the next resolution
                # step-down / SPP refinement to the following redraw.
                self._viewport_present_pending = False
                request_viewport_redraw_fn()
            elif render_needed:
                # pkg241 Phase 1: taking the render path supersedes any pending
                # view_update chunk (its view changed, or we are refining), so
                # drop the present-first flag — it is consumed by this render.
                self._viewport_present_pending = False
                renderer = self._get_viewport_renderer()
                # If user opened rendered-shading without ever firing view_update,
                # renderer has no scene. Fall back to full sync.
                did_fresh_sync = self._viewport_texture is None
                if did_fresh_sync:
                    self.sync_viewport_scene(renderer, depsgraph, settings,
                                            configure_backend_fn,
                                            viewport_perf_record_fn,
                                            effective_integrator_name_fn)

                # pkg192: pure camera moves (orbit / pan / zoom) change ONLY the
                # camera — geometry, BVH, materials, lights and environment are
                # all identical to the last synced frame. Render from the current
                # device state with skip_upload=True so we skip the per-frame CPU
                # BVH rebuild (renderer.buildAcceleration), which the profile
                # showed dominated orbit-frame cost (~48 ms of a ~100 ms render on
                # a 100k-tri scene; benchmarks/viewport_parity). The camera is
                # published separately by setup_viewport_camera, so a camera-only
                # skip_upload render stays correct (verified: identical image at a
                # fixed camera, image updates as the camera moves).
                # view_draw NEVER re-syncs the scene (only view_update does), so
                # on a camera move the geometry/BVH is guaranteed identical to
                # the last sync. Guard: the fresh-sync fallback frame (and any
                # frame before the scene was ever fully synced) still uploads so
                # the BVH is built for the current geometry. Progressive
                # still-frame refine frames (camera unchanged, pkg191's loop) are
                # deliberately left on the upload path — this fix is scoped to
                # camera-motion interactivity only.
                # NOTE: settings_changed is NOT a valid exclusion here — the
                # render key hashes the camera state, so it flips on every camera
                # move; gating on camera_changed is what isolates orbit/pan/zoom.
                camera_only_frame = (
                    not did_fresh_sync
                    and self._viewport_full_synced
                    and camera_changed
                )

                # pkg196: the fresh-sync fallback frame builds the BVH and seeds
                # the still-frame loop — it (and any pre-sync frame) always renders
                # full res. Only a fully-synced camera-motion frame reduces res.
                frame_divisor = desired_divisor if not did_fresh_sync else 1

                t0 = time.perf_counter()
                self.render_viewport_frame(
                    renderer, context, settings, region,
                    reset_accumulation=(camera_substantive_changed or settings_changed
                                        or resolution_switch),
                    engine_methods=engine_methods,
                    skip_upload=camera_only_frame,
                    res_divisor=frame_divisor,
                )
                # pkg192: record orbit/pan/zoom frames through the existing
                # pkg56-A ring buffer. view_draw previously left camera-motion
                # frames unprofiled (only view_update recorded), so the per-stage
                # overlay / viewport_perf_stats never saw the interactive path
                # that the owner's fps complaint is about.
                viewport_perf_record_fn("render", t0)
                viewport_perf_frame_complete_fn()

                self._viewport_camera_hash = new_hash
                self._viewport_camera_substantive_hash = new_substantive_hash

            # pkg196 + pkg241 Phase 1: keep pumping redraws while below full res
            # (divisor > 1, so a coarse first present always resolves up to full
            # res even if the reduced chunk hit the sample target) or while the
            # pkg191 progressive loop is refining at full res. A pending present
            # this frame also needs a follow-up redraw to run its refinement.
            resolving = self._viewport_render_divisor > 1
            if (resolving or present_pending
                    or self._viewport_current_spp < self._viewport_target_spp):
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

    # -----------------------------------------------------------------------
    # pkg241 Phase 2 A2 spike — off-thread worker path (design §3.2-§3.4, §9).
    # Flag-gated (ASTRORAY_VIEWPORT_WORKER=1). GPU-only, single viewport, camera
    # + material generations. All bpy/GPUTexture/tag_redraw stays on the main
    # thread; only renderer.render + pass extraction + numpy accumulate run on the
    # worker thread. Not the production worker (no arbiter/F12/denoise/lifecycle).
    # -----------------------------------------------------------------------
    def _make_worker_render_fn(self):
        """Build the bpy-free render_fn the worker thread runs under the token.
        It renders progressive chunks to the target spp, accumulating into a
        PRIVATE running-mean buffer (same math as render_viewport_frame, but
        worker-owned), publishing each chunk into the depth-1 mailbox. Cancel is
        cooperative (the progress callback returns not cancel_check())."""
        def render_fn(job, cancel_check, publish):
            renderer = job["renderer"]
            target = int(job["target_spp"])
            depth = int(job["depth"])
            chunk = max(1, int(job["chunk"]))
            width = int(job["width"])
            height = int(job["height"])
            display_pass = job["display_pass"]
            b = (job["diffuse"], job["glossy"], job["transmission"],
                 job["volume"], job["transparent"])
            skip_upload = bool(job["skip_upload"])
            accum = None
            accum_spp = 0

            def progress(_frac):
                return not cancel_check()  # True = continue, False = cancel

            while accum_spp < target and not cancel_check():
                samples = min(chunk, target - accum_spp)
                if samples <= 0:
                    break
                pixels = renderer.render(
                    samples, depth, progress, False,
                    b[0], b[1], b[2], b[3], b[4], skip_upload)
                # pkg241 Phase 2 A2 spike (§9): per-generation device readback for
                # the same-device assertion (last_render_info()['device'] is the
                # CUDA device this worker-thread render resolved).
                try:
                    _info = renderer.last_render_info()
                    _emit_spike_event("render_device", job["generation"],
                                      job.get("session_epoch", 0),
                                      device=_info.get("device", -1))
                except Exception:
                    pass
                if cancel_check() or pixels is None:
                    break
                disp = pixels
                if display_pass not in ("combined", "albedo", "normal", "depth"):
                    try:
                        disp = renderer.get_render_pass_buffer(display_pass)
                    except Exception:
                        disp = pixels
                chunk_arr = np.asarray(disp, dtype=np.float32)
                if accum is None or accum_spp <= 0:
                    accum = chunk_arr.copy()
                    accum_spp = int(samples)
                else:
                    new_spp = accum_spp + int(samples)
                    accum = ((accum * accum_spp + chunk_arr * int(samples))
                             / float(new_spp))
                    accum_spp = new_spp
                # Publish an IMMUTABLE snapshot of the accumulator (§3.3): the
                # worker keeps mutating `accum`, so hand out a copy, never the
                # live array.
                publish(np.ascontiguousarray(accum), width, height)
                skip_upload = True  # subsequent chunks reuse device state
        return render_fn

    def _worker_present(self, buffer, width, height, generation):
        """Main-thread present (§3.3): upload the published buffer to a GPUTexture
        and request a redraw. This is where the `flat.tolist()` texture tail the
        §9 measurement watches is paid."""
        em = self._worker_engine_methods
        if em is None:
            return
        self._viewport_width = width
        self._viewport_height = height
        em["update_viewport_texture"](buffer, width, height)
        if self._worker_redraw_fn is not None:
            try:
                self._worker_redraw_fn()
            except Exception:
                pass

    def _ensure_worker(self, engine_methods, request_viewport_redraw_fn):
        if self._worker is not None:
            return self._worker
        self._worker_engine_methods = engine_methods
        self._worker_redraw_fn = request_viewport_redraw_fn

        def _report(msg):
            try:
                self.engine.report({'ERROR'}, msg)
            except Exception:
                pass

        self._worker = _ViewportSpikeWorker(
            render_fn=self._make_worker_render_fn(),
            present_fn=self._worker_present,
            report_fn=_report)
        self._worker.start()
        self._register_worker_timer()
        return self._worker

    def _register_worker_timer(self):
        """Register the §3.3 liveness pump (bpy.app.timers, ~60 Hz): drain the
        mailbox/control queue and request a redraw even when Blender is otherwise
        idle, so a finished frame always reaches the screen. No-op if bpy.app is
        unavailable (headless/stub)."""
        bpy = getattr(self, "bpy", None)
        if bpy is None or not hasattr(bpy, "app") or not hasattr(bpy.app, "timers"):
            return

        def _pump_timer():
            w = self._worker
            if w is None or w.state == _ViewportSpikeWorker.DEAD:
                return None  # unregister
            try:
                # State advance only — never build a GPUTexture off the draw
                # context (P2.2 item 1). tag_redraw so view_draw runs and presents
                # the freshest frame in its own valid draw context, even while
                # Blender is otherwise idle.
                w.pump(present=False)
                if self._worker_redraw_fn is not None:
                    self._worker_redraw_fn()
            except Exception:
                pass
            return 0.016

        try:
            bpy.app.timers.register(_pump_timer, first_interval=0.016)
            self._worker_timer = _pump_timer
        except Exception:
            self._worker_timer = None

    def _worker_commit_and_submit(self, context, depsgraph, settings, region,
                                  configure_backend_fn, viewport_perf_record_fn,
                                  effective_integrator_name_fn, engine_methods,
                                  commit_mode):
        """Main thread: if the worker is IDLE and a newer generation is desired,
        commit the snapshot into the persistent renderer under the token and submit
        render() to the worker (§3.2). The commit reads bpy here, on the main
        thread; the worker only renders.

        pkg241 P2.2 item 2 (bounded commit) — `commit_mode` selects only what
        changed, so the main thread no longer runs a full scene upload for every
        generation (the residual tick-gap p95 in the spike):

          - 'camera'          : camera/settings only, no scene sync, skip_upload=True
                                (a pan/zoom/orbit re-renders from device state).
          - 'scene'           : a scene/material edit committed immediately while the
                                worker is idle, with its LIVE depsgraph — uses the
                                incremental pkg56 dispatch (apply_depsgraph_updates),
                                falling back to a full sync only on first sync or an
                                unrecognised update.
          - 'scene_full'      : a scene edit that was deferred while the worker was
                                busy (its depsgraph is now stale) — full sync.

        In all modes the cheap per-frame config (camera, wavelength, integrator,
        passes) is committed. The commit_start/commit_end lifeline events emitted by
        maybe_submit bracket this so the driver can attribute the per-generation
        commit cost."""
        def commit_fn(gen):
            renderer = self._get_viewport_renderer()
            skip_upload = False
            if commit_mode == 'camera' and self._viewport_full_synced:
                # No scene mutation: refit/render from already-uploaded device state.
                skip_upload = True
            elif commit_mode == 'scene' and self._viewport_full_synced:
                # Incremental dispatch with the live depsgraph (pkg56). 'fallback'
                # => an unrecognised update, so do a full sync; 'idle'/'dispatched'
                # => the matching uploader(s) ran, and skip_upload was set by
                # apply_depsgraph_updates for a refit-only (transform) edit.
                dispatch = self.apply_depsgraph_updates(
                    renderer, depsgraph, settings, configure_backend_fn,
                    self.engine.report)
                if dispatch == 'fallback':
                    self.sync_viewport_scene(
                        renderer, depsgraph, settings, configure_backend_fn,
                        viewport_perf_record_fn, effective_integrator_name_fn)
                else:
                    skip_upload = self._viewport_skip_upload_next
                self._viewport_skip_upload_next = False
            else:
                # 'scene_full', or the first sync in any mode: full scene upload.
                self.sync_viewport_scene(
                    renderer, depsgraph, settings, configure_backend_fn,
                    viewport_perf_record_fn, effective_integrator_name_fn)
                self._viewport_full_synced = True
            width = max(1, int(region.width))
            height = max(1, int(region.height))
            engine_methods['setup_viewport_camera'](renderer, context, width, height)
            lmin, lmax = engine_methods['wavelength_range_from_settings'](settings)
            renderer.set_wavelength_range(lmin, lmax)
            if lmax > 780.0 or lmin < 380.0:
                renderer.set_output_mode("luminance")
            renderer.set_integrator(engine_methods['effective_integrator_name'](settings))
            try:
                renderer.clear_passes()
            except AttributeError:
                pass
            display_pass = getattr(settings, "viewport_display_pass", "combined")
            if display_pass == "albedo":
                renderer.add_pass("albedo_aov")
            elif display_pass == "normal":
                renderer.add_pass("normal_aov")
            elif display_pass == "depth":
                renderer.add_pass("depth_aov")
            depth = max(2, settings.max_bounces // 2)
            target = int(engine_methods['viewport_target_samples'](settings))
            chunk = int(engine_methods['viewport_chunk_samples'](settings, 0))
            return {
                "generation": gen, "renderer": renderer,
                "session_epoch": self._worker.session_epoch,
                "width": width, "height": height, "depth": depth,
                "target_spp": target, "chunk": max(1, chunk),
                "display_pass": display_pass,
                # skip_upload was resolved above per commit_mode: True only for a
                # camera/refit generation (or a refit-only incremental dispatch);
                # a full or material sync must upload + rebuild device state.
                "skip_upload": bool(skip_upload),
                "diffuse": min(settings.diffuse_bounces, depth),
                "glossy": min(settings.glossy_bounces, depth),
                "transmission": min(settings.transmission_bounces, depth),
                "volume": min(settings.volume_bounces, depth),
                "transparent": min(settings.transparent_bounces, depth),
            }

        submitted = self._worker.maybe_submit(commit_fn)
        if submitted and commit_mode in ('scene', 'scene_full'):
            # A committed scene edit clears the deferred-scene debt (item 2).
            self._worker_deferred_scene = False
        return submitted

    def _worker_view_update(self, context, depsgraph, configure_backend_fn,
                            effective_integrator_name_fn, viewport_perf_record_fn,
                            camera_state_hash_fn, camera_substantive_state_hash_fn,
                            request_viewport_redraw_fn, engine_methods):
        """Worker-path view_update (§3.4): a scene/material edit bumps the desired
        generation and requests cancel. pkg241 P2.2 item 2 (bounded commit): if the
        worker is idle the edit is committed immediately with its LIVE depsgraph via
        the incremental pkg56 dispatch (commit_mode='scene'); if the worker is busy
        (token held) the edit is DEFERRED and the next idle view_draw re-commits it
        as a full sync (commit_mode='scene_full'), because the depsgraph.updates it
        would need are only valid during this call."""
        import traceback
        try:
            scene = depsgraph.scene
            settings = scene.custom_raytracer
            resolve_fn = engine_methods.get('resolve_settings')
            if resolve_fn is not None:
                settings = resolve_fn(scene, self.engine.report)
            region = context.region
            worker = self._ensure_worker(engine_methods, request_viewport_redraw_fn)
            worker.request()
            # pkg241 P2.2 item 2 (Terra review 4): view_update is NOT a GPU draw
            # context, so pump here must be control-plane only (present=False). The
            # spike's default pump(present=True) built a GPUTexture off a draw
            # context: the upload raised (swallowed), but _drain_mailbox had already
            # cleared the depth-1 mailbox, losing the queued frame before view_draw
            # could present it. Only view_draw (below) pumps with present=True.
            worker.pump(present=False)
            submitted = self._worker_commit_and_submit(
                context, depsgraph, settings, region, configure_backend_fn,
                viewport_perf_record_fn, effective_integrator_name_fn,
                engine_methods, commit_mode='scene')
            if not submitted:
                # Worker busy: defer. The live depsgraph is gone by the next tick,
                # so the deferred commit falls back to a full sync.
                self._worker_deferred_scene = True
            self._viewport_camera_hash = camera_state_hash_fn(context, region)
            self._viewport_camera_substantive_hash = \
                camera_substantive_state_hash_fn(context, region)
            request_viewport_redraw_fn()
        except Exception as e:
            print(f"Astroray viewport worker view_update error: {e}")
            traceback.print_exc()

    def _worker_view_draw(self, context, depsgraph, configure_backend_fn,
                          effective_integrator_name_fn, viewport_perf_record_fn,
                          camera_state_hash_fn, camera_substantive_state_hash_fn,
                          request_viewport_redraw_fn, engine_methods):
        """Worker-path view_draw (§3.3/§3.4): detect a camera edit (bump + cancel),
        pump the worker (present the freshest published frame), commit+submit the
        desired generation when idle, then blit the latest texture. Never renders
        on the main thread — that is the whole point of the spike."""
        import traceback
        try:
            region = context.region
            scene = depsgraph.scene
            settings = scene.custom_raytracer
            resolve_fn = engine_methods.get('resolve_settings')
            if resolve_fn is not None:
                settings = resolve_fn(scene, None)
            worker = self._ensure_worker(engine_methods, request_viewport_redraw_fn)

            new_hash = camera_state_hash_fn(context, region)
            camera_changed = (new_hash is not None
                              and new_hash != self._viewport_camera_hash)
            if camera_changed:
                worker.request()
                self._viewport_camera_hash = new_hash
                self._viewport_camera_substantive_hash = \
                    camera_substantive_state_hash_fn(context, region)

            # Pump: present the freshest valid published frame + advance state.
            worker.pump()
            # Commit + submit the desired generation if the worker is now idle.
            # pkg241 P2.2 item 2: a scene edit deferred while the worker was busy is
            # re-committed here as a full sync (its live depsgraph is gone); an
            # ordinary camera move commits camera-only with skip_upload.
            commit_mode = 'scene_full' if self._worker_deferred_scene else 'camera'
            self._worker_commit_and_submit(
                context, depsgraph, settings, region, configure_backend_fn,
                viewport_perf_record_fn, effective_integrator_name_fn,
                engine_methods, commit_mode=commit_mode)

            # Keep the loop alive while a render is in flight or a frame is queued.
            if worker.state != _ViewportSpikeWorker.IDLE:
                request_viewport_redraw_fn()

            # Blit the latest published buffer (pure blit — no render, §3.3).
            if self._viewport_texture is None:
                return
            import gpu  # noqa: F401 — needed by draw_texture_2d
            from gpu_extras.presets import draw_texture_2d
            self.engine.bind_display_space_shader(scene)
            draw_texture_2d(self._viewport_texture, (0, 0),
                            region.width, region.height)
            self.engine.unbind_display_space_shader()
        except Exception as e:
            print(f"Astroray worker view_draw error: {e}")
            traceback.print_exc()

    def stop_worker(self):
        """Main-thread teardown (§3.6): request cancel and pump until the worker
        acknowledges exit (bounded 5 s), unregister the timer, and — on a no-ack
        timeout — quarantine the worker (strong ref, never destroyed) instead of
        releasing the renderer. Idempotent."""
        worker = self._worker
        if worker is None:
            return
        acked = worker.stop(timeout=5.0)
        bpy = getattr(self, "bpy", None)
        if (self._worker_timer is not None and bpy is not None
                and hasattr(bpy, "app") and hasattr(bpy.app, "timers")):
            try:
                if bpy.app.timers.is_registered(self._worker_timer):
                    bpy.app.timers.unregister(self._worker_timer)
            except Exception:
                pass
        self._worker_timer = None
        if not acked:
            _WORKER_QUARANTINE.append(worker)  # no-ack: never destroy
        self._worker = None

    def __del__(self):
        # pkg241 Phase 2 A2 spike: best-effort worker teardown so an engine
        # re-create does not leak a live render thread (not the production
        # lifecycle owner — that is P2.2). Short bounded stop; a no-ack worker is
        # quarantined by stop_worker, never destroyed.
        try:
            if getattr(self, "_worker", None) is not None:
                self.stop_worker()
        except Exception:
            pass

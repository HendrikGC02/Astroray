"""pkg266 Viewport Phase 2.3 — coalesced dirty-domain commit + global token.

bpy-free unit tests (bpy stubbed, no CUDA) for the addon side of pkg266:

  * `_record_deferred_dirty` / `_replay_deferred_dirty` (§13 item 2 / Terra (c)):
    N scene edits arriving while the worker is BUSY are classified from the live
    depsgraph and coalesced into ONE dirty-domain mask, replayed as the safe
    material/light/environment upload ops under the token at idle — instead of a
    full sync_viewport_scene for every deferred edit. A geometry (or instancing /
    unrecognised) edit forces a full sync (never guess a domain).

  * the ONE process-global admission token + the F12 pause gate (§3.5): a viewport
    worker is not admitted while another holder owns the global token or while the
    F12 gate is raised, and no commit runs while the worker is not idle.

Mirrors the bpy stub + Exporter construction of tests/test_pkg116_exporter_caches.py.
"""

import importlib.util
import threading
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# bpy stub (matches test_pkg116_exporter_caches.py)
# ---------------------------------------------------------------------------

class _BpyId:
    def __init__(self, name="x"):
        self.name = name


class World(_BpyId): pass
class Light(_BpyId): pass
class Material(_BpyId): pass
class NodeTree(_BpyId): pass
class Image(_BpyId): pass
class Scene(_BpyId): pass


class Object(_BpyId):
    def __init__(self, name="obj", matrix_world=None):
        super().__init__(name)
        self.matrix_world = matrix_world or [
            [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]
        ]


class _DepsgraphUpdate:
    def __init__(self, id, *, geometry=False, transform=False, shading=False):
        self.id = id
        self.is_updated_geometry = geometry
        self.is_updated_transform = transform
        self.is_updated_shading = shading


def _load_exporter_module():
    module_path = Path(__file__).parent.parent / "blender_addon" / "exporter.py"
    spec = importlib.util.spec_from_file_location(
        "astroray_exporter_pkg266", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _stub_bpy():
    bpy_module = types.ModuleType("bpy")
    bpy_types_module = types.ModuleType("bpy.types")
    bpy_types_module.World = World
    bpy_types_module.Light = Light
    bpy_types_module.Material = Material
    bpy_types_module.NodeTree = NodeTree
    bpy_types_module.ShaderNodeTree = NodeTree
    bpy_types_module.Image = Image
    bpy_types_module.Object = Object
    bpy_types_module.Scene = Scene
    bpy_module.types = bpy_types_module
    return bpy_module


def _stub_depsgraph(updates, scene=None):
    return types.SimpleNamespace(updates=list(updates), scene=scene)


class _SpyRenderer:
    def __init__(self):
        self.calls = []

    def _rec(self, name, *args):
        self.calls.append((name,) + args)

    def upload_geometry(self):    self._rec("upload_geometry")
    def upload_materials(self):   self._rec("upload_materials")
    def upload_lights(self):      self._rec("upload_lights")
    def upload_environment(self): self._rec("upload_environment")
    def update_object_transform(self, obj_id, mat16):
        self._rec("update_object_transform", obj_id, tuple(mat16))

    # No-op renderer config the commit_fn (worker path) touches.
    def set_wavelength_range(self, lmin, lmax): pass
    def set_output_mode(self, mode): pass
    def set_integrator(self, name): pass
    def clear_passes(self): pass
    def add_pass(self, name): pass


def _make_exporter(exp):
    bpy = _stub_bpy()

    class _StubEngine:
        def __init__(self):
            # empty instance maps → non-instanced classification
            self._renderer_instance_id_map = {}
            self._renderer_instancer_eligible = {}

        def setup_world(self, scene, renderer):
            renderer._rec("setup_world")

        def report(self, *_a, **_k):
            return None

    engine = _StubEngine()
    astroray = types.SimpleNamespace(Renderer=_SpyRenderer)
    exporter = exp.Exporter(engine, bpy, astroray)
    exporter._viewport_full_synced = True  # so the incremental path runs
    return exporter


# ---------------------------------------------------------------------------
# Coalesced dirty-domain record + replay
# ---------------------------------------------------------------------------

def test_n_material_edits_coalesce_to_one_materials_replay():
    """N material edits while the worker is busy coalesce into ONE materials-only
    replay — upload_materials runs exactly once, no geometry/lights/env."""
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)

    for _ in range(4):
        exporter._record_deferred_dirty(
            _stub_depsgraph([_DepsgraphUpdate(Material("M"))]), settings=None)

    assert exporter._deferred_full_sync is False
    assert exporter._deferred_dirty_mask & exp.Change.MATERIALS
    assert not (exporter._deferred_dirty_mask & exp.Change.GEOMETRY)

    spy = _SpyRenderer()
    replayed = exporter._replay_deferred_dirty(
        spy, _stub_depsgraph([]), None, lambda *_: None, None)
    assert replayed is True
    names = [c[0] for c in spy.calls]
    assert names.count("upload_materials") == 1, names
    assert "upload_geometry" not in names
    assert "upload_lights" not in names
    assert "upload_environment" not in names


def test_mixed_safe_domains_coalesce_and_replay_each_once():
    """Material + light + world edits coalesce into one replay that runs each safe
    uploader exactly once (env, materials, lights) — no full sync."""
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)

    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(Material("M"))]), settings=None)
    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(Light("L"))]), settings=None)
    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(World("W"))]), settings=None)

    assert exporter._deferred_full_sync is False
    spy = _SpyRenderer()
    replayed = exporter._replay_deferred_dirty(
        spy, _stub_depsgraph([], scene=types.SimpleNamespace()),
        None, lambda *_: None, None)
    assert replayed is True
    names = [c[0] for c in spy.calls]
    assert names.count("upload_materials") == 1
    assert names.count("upload_lights") == 1
    assert names.count("upload_environment") == 1


def test_geometry_edit_forces_full_sync():
    """A geometry edit while busy sets the full-sync flag; the replay declines
    (returns False) so the caller runs a full sync — never guess a domain."""
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)

    # A material edit first, then a geometry edit — the geometry edit must poison
    # the coalesced batch into a full sync (the safe-domain replay is abandoned).
    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(Material("M"))]), settings=None)
    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(Object("Cube"), geometry=True)]),
        settings=None)

    assert exporter._deferred_full_sync is True
    spy = _SpyRenderer()
    replayed = exporter._replay_deferred_dirty(
        spy, _stub_depsgraph([]), None, lambda *_: None, None)
    assert replayed is False
    assert spy.calls == []  # no incremental uploader ran; caller full-syncs


def test_unrecognised_update_forces_full_sync():
    """An unrecognised id type (fallback) recorded while busy forces a full sync."""
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)

    class _Weird(_BpyId):  # not in the bpy.types.* classification set
        pass

    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(_Weird("x"))]), settings=None)
    assert exporter._deferred_full_sync is True
    spy = _SpyRenderer()
    assert exporter._replay_deferred_dirty(
        spy, _stub_depsgraph([]), None, lambda *_: None, None) is False


def test_clear_deferred_dirty_resets_state():
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)
    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(Material("M"))]), settings=None)
    exporter._clear_deferred_dirty()
    assert exporter._deferred_dirty_mask == exp.Change.NONE
    assert exporter._deferred_transforms == {}
    assert exporter._deferred_full_sync is False


# ---------------------------------------------------------------------------
# Process-global admission token + F12 pause gate (§3.5)
# ---------------------------------------------------------------------------

def _make_worker(exp, token, gate):
    committed = {"n": 0}

    def render_fn(job, cancel_check, publish):
        pass

    def present_fn(buffer, width, height, gen):
        pass

    worker = exp._ViewportSpikeWorker(
        render_fn=render_fn, present_fn=present_fn,
        token=token, admission_gate=gate)

    def commit_fn(gen):
        committed["n"] += 1
        return {"generation": gen}

    return worker, commit_fn, committed


def test_no_commit_while_worker_not_idle():
    """maybe_submit runs the commit only when the worker is IDLE — a busy
    (RENDERING) worker never runs a commit (no renderer mutation mid-render)."""
    exp = _load_exporter_module()
    worker, commit_fn, committed = _make_worker(exp, threading.Lock(), None)
    worker.desired_generation = 1
    worker.state = worker.RENDERING  # simulate an in-flight render
    assert worker.maybe_submit(commit_fn) is False
    assert committed["n"] == 0


def test_global_token_held_by_another_holder_blocks_admission():
    """When another holder owns the global token, maybe_submit does not block and
    does not commit — the edit stays pending for the next tick (§3.5)."""
    exp = _load_exporter_module()
    token = threading.Lock()
    worker, commit_fn, committed = _make_worker(exp, token, None)
    worker.desired_generation = 1
    token.acquire()  # another viewport (or F12) holds the global token
    try:
        assert worker.maybe_submit(commit_fn) is False
        assert committed["n"] == 0
    finally:
        token.release()
    # Once free, the same worker is admitted and commits.
    assert worker.maybe_submit(commit_fn) is True
    assert committed["n"] == 1


def test_f12_pause_gate_blocks_admission():
    """While the F12 pause gate is raised no viewport is admitted; lowering it
    lets the pending generation commit."""
    exp = _load_exporter_module()
    gate_flag = {"up": True}
    worker, commit_fn, committed = _make_worker(
        exp, threading.Lock(), lambda: gate_flag["up"])
    worker.desired_generation = 1
    assert worker.maybe_submit(commit_fn) is False
    assert committed["n"] == 0
    gate_flag["up"] = False  # F12 lowered the gate
    assert worker.maybe_submit(commit_fn) is True
    assert committed["n"] == 1


def test_f12_admission_helpers_gate_and_token():
    """acquire_f12_admission raises the gate + owns the global token; a viewport
    worker sharing them is blocked; release lowers the gate + frees the token."""
    exp = _load_exporter_module()
    worker, commit_fn, committed = _make_worker(
        exp, exp._GLOBAL_ADMISSION_TOKEN, exp._admission_gate_raised)
    worker.desired_generation = 1
    assert exp.acquire_f12_admission(timeout=1.0) is True
    try:
        assert exp._admission_gate_raised() is True
        assert worker.maybe_submit(commit_fn) is False
        assert committed["n"] == 0
    finally:
        exp.release_f12_admission()
    assert exp._admission_gate_raised() is False
    # Token is free and gate down → the worker is admitted.
    assert worker.maybe_submit(commit_fn) is True
    assert committed["n"] == 1


# ---------------------------------------------------------------------------
# World node-tree classification (Terra review, item 3)
# ---------------------------------------------------------------------------

def test_world_node_tree_edit_replays_environment_not_materials_only():
    """A World shader node-tree edit reaches the depsgraph as a NodeTree/
    ShaderNodeTree update whose id is `scene.world.node_tree` — NOT a World
    update. It must be classified ENVIRONMENT (so the replay re-runs
    setup_world/upload_environment) and must NOT be silently bucketed as a
    materials-only edit that leaves the world stale (the Terra item-3 bug)."""
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)

    world_tree = NodeTree("WorldTree")
    world = World("W")
    world.node_tree = world_tree
    scene = Scene("Scn")
    scene.world = world

    # The world-tree edit arrives while the worker is busy -> recorded.
    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(world_tree, shading=True)],
                        scene=scene),
        settings=None)

    assert exporter._deferred_full_sync is False
    assert exporter._deferred_dirty_mask & exp.Change.ENVIRONMENT
    assert not (exporter._deferred_dirty_mask & exp.Change.MATERIALS)

    spy = _SpyRenderer()
    replayed = exporter._replay_deferred_dirty(
        spy, _stub_depsgraph([], scene=scene), None, lambda *_: None, None)
    assert replayed is True
    names = [c[0] for c in spy.calls]
    assert "upload_environment" in names, names
    assert "setup_world" in names, names            # world re-parsed before upload
    assert "upload_materials" not in names, names   # not a materials-only replay


def test_material_node_tree_edit_still_materials():
    """The world exclusion is narrow: a NON-world shader node tree edit still
    classifies MATERIALS (regression guard so item 3 did not disable material
    node edits)."""
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)

    mat_tree = NodeTree("MatTree")            # not scene.world.node_tree
    world = World("W")
    world.node_tree = NodeTree("WorldTree")   # a DIFFERENT tree owns the world
    scene = Scene("Scn")
    scene.world = world

    exporter._record_deferred_dirty(
        _stub_depsgraph([_DepsgraphUpdate(mat_tree, shading=True)], scene=scene),
        settings=None)
    assert exporter._deferred_dirty_mask & exp.Change.MATERIALS
    assert not (exporter._deferred_dirty_mask & exp.Change.ENVIRONMENT)


# ---------------------------------------------------------------------------
# F12 must never render token-less (Terra review, item 1)
# ---------------------------------------------------------------------------

def _f12_would_render(exp, timeout):
    """Faithful model of blender_addon/__init__.py render()'s pkg266 F12 guard:
    F12 enters native conversion/render ONLY if acquire_f12_admission() returned
    True. On the no-ack path it reports an ERROR and returns without rendering.
    release_f12_admission() runs in a finally on every exit path. Records whether
    the pause gate was still raised at the moment F12 gave up (before cleanup)."""
    holds = exp.acquire_f12_admission(timeout=timeout)
    try:
        if not holds:
            _f12_would_render.entered = False       # report(ERROR) + return
            return
        _f12_would_render.entered = True            # astroray.Renderer() ... render()
    finally:
        _f12_would_render.gate_was_raised = exp._admission_gate_raised()
        exp.release_f12_admission()


def test_f12_no_ack_worker_never_renders():
    """A viewport worker whose cancel hook is stuck never drains and still owns
    the global admission token; F12 must NOT enter native render (the section 13a
    GPU-context race) and must keep the pause gate raised through the attempt.
    Proves the Terra item-1 fix: acquire_f12_admission returns False on the no-ack
    path and the caller aborts."""
    exp = _load_exporter_module()

    stopped = {"n": 0}

    class _HungSession:
        # pause never drains to idle (the stuck cancel hook), so the global token
        # it holds is never released within the drain timeout.
        def pause_worker_for_f12(self, timeout=5.0):
            return False

        def stop_worker(self):
            stopped["n"] += 1

    session = _HungSession()
    # Simulate the hung worker owning the ONE process-global token.
    assert exp._GLOBAL_ADMISSION_TOKEN.acquire(blocking=False) is True
    exp._register_viewport_session(session)
    try:
        _f12_would_render(exp, timeout=0.1)
        assert _f12_would_render.entered is False          # never rendered token-less
        assert _f12_would_render.gate_was_raised is True   # gate held through attempt
        assert exp._F12_HOLDS_TOKEN is False               # F12 never owned the token
        assert stopped["n"] >= 1                            # hung session quarantined
    finally:
        try:
            exp._GLOBAL_ADMISSION_TOKEN.release()
        except RuntimeError:
            pass
        exp._unregister_viewport_session(session)
        exp._F12_PAUSE_GATE.clear()


# ---------------------------------------------------------------------------
# Reduced-resolution first unit on the worker path (Terra review, item 2)
# ---------------------------------------------------------------------------

def _worker_engine_methods(captured):
    return {
        "setup_viewport_camera": lambda r, c, w, h: captured.update(cam_wh=(w, h)),
        "wavelength_range_from_settings": lambda s: (400.0, 700.0),
        "effective_integrator_name": lambda s: "path",
        "viewport_target_samples": lambda s: 64,
        "viewport_chunk_samples": lambda s, cur: 8,
    }


def _worker_settings():
    return types.SimpleNamespace(
        max_bounces=8, viewport_display_pass="combined",
        diffuse_bounces=4, glossy_bounces=4, transmission_bounces=4,
        volume_bounces=4, transparent_bounces=4)


def _idle_worker(exp):
    w = exp._ViewportSpikeWorker(
        render_fn=lambda job, cc, pub: None,
        present_fn=lambda b, w, h, g: None,
        token=exp._GLOBAL_ADMISSION_TOKEN)
    # Do NOT start the thread — maybe_submit stores the built job in _current_job
    # and flips to RENDERING; the test reads the job dimensions directly.
    return w


def test_worker_first_unit_reduced_then_refinement_full_res():
    """When the measured full-res cost exceeds the interactive budget, the FIRST
    submitted worker job renders at the divided (_budget_start_divisor) dimensions
    and the follow-up full-resolution refinement renders at full region size — the
    Terra item-2 reduced-first-unit on the worker path (Cycles start_resolution
    analogue, mirroring the synchronous view_draw)."""
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)
    exporter._worker = _idle_worker(exp)
    captured = {}
    region = types.SimpleNamespace(width=256, height=256)
    context = types.SimpleNamespace(region=region)
    settings = _worker_settings()
    em = _worker_engine_methods(captured)

    # Force the expensive profile so _budget_start_divisor() returns the coarse
    # divisor (> 1). Divisor is exp.VIEWPORT_START_RES_DIVISOR.
    exporter._viewport_last_full_render_ms = exp.VIEWPORT_INTERACTIVE_BUDGET_MS * 10
    div = exp.VIEWPORT_START_RES_DIVISOR

    # First submission (a fresh camera generation).
    exporter._worker.desired_generation = 1
    submitted = exporter._worker_commit_and_submit(
        context, None, settings, region, lambda *a: None, lambda *a: None,
        lambda *a: "path", em, commit_mode='camera')
    assert submitted is True
    job1 = exporter._worker._current_job
    assert job1["width"] == region.width // div, (job1["width"], div)
    assert job1["height"] == region.height // div
    assert job1["res_divisor"] == div
    # The reduced unit owes a full-res refinement.
    assert exporter._worker_refine_pending is True
    assert exporter._worker_refine_gen == 1

    # Simulate the reduced unit completing unsuperseded -> the worker returns to
    # IDLE and releases the token (normally done on the worker thread, which is
    # not started here), then schedule the refinement exactly as
    # _worker_view_draw does.
    exporter._worker.state = exp._ViewportSpikeWorker.IDLE
    exporter._worker._token.release()
    exporter._worker._token_holder = None
    exporter._worker_fullres_next = True
    exporter._worker.request()  # desired -> 2
    submitted2 = exporter._worker_commit_and_submit(
        context, None, settings, region, lambda *a: None, lambda *a: None,
        lambda *a: "path", em, commit_mode='camera')
    assert submitted2 is True
    job2 = exporter._worker._current_job
    assert job2["width"] == region.width, job2["width"]   # full resolution
    assert job2["height"] == region.height
    assert job2["res_divisor"] == 1
    assert exporter._worker_refine_pending is False


def test_worker_refinement_survives_failed_submit():
    """Luna re-review of PR #791: the owed full-resolution refinement must not be
    lost when its submit fails (global token contended). _worker_fullres_next is
    cleared only once a full-res submission actually went out; a failed submit
    leaves it set so the next commit still renders full resolution."""
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)
    exporter._worker = _idle_worker(exp)
    region = types.SimpleNamespace(width=256, height=256)
    context = types.SimpleNamespace(region=region)
    settings = _worker_settings()
    em = _worker_engine_methods({})
    exporter._viewport_last_full_render_ms = exp.VIEWPORT_INTERACTIVE_BUDGET_MS * 10

    exporter._worker.desired_generation = 1
    assert exporter._worker_commit_and_submit(
        context, None, settings, region, lambda *a: None, lambda *a: None,
        lambda *a: "path", em, commit_mode='camera') is True
    assert exporter._worker_refine_pending is True

    # Refinement owed; the submit fails (token contended) -> nothing consumed.
    exporter._worker.state = exp._ViewportSpikeWorker.IDLE
    exporter._worker._token.release()
    exporter._worker._token_holder = None
    exporter._worker_fullres_next = True
    real_submit = exporter._worker.maybe_submit
    exporter._worker.maybe_submit = lambda commit_fn: False
    exporter._worker.request()
    assert exporter._worker_commit_and_submit(
        context, None, settings, region, lambda *a: None, lambda *a: None,
        lambda *a: "path", em, commit_mode='camera') is False
    assert exporter._worker_fullres_next is True, "owed refinement was lost"

    # Next successful commit goes out at full resolution and clears the debt.
    exporter._worker.maybe_submit = real_submit
    assert exporter._worker_commit_and_submit(
        context, None, settings, region, lambda *a: None, lambda *a: None,
        lambda *a: "path", em, commit_mode='camera') is True
    assert exporter._worker._current_job["res_divisor"] == 1
    assert exporter._worker_fullres_next is False
    assert exporter._worker_refine_pending is False


def test_worker_cheap_scene_renders_full_res_first():
    """A cheap scene (measured full-res cost under the budget) submits its first
    unit at full resolution — the reduced-first-unit engages only above the
    threshold, matching the synchronous path."""
    exp = _load_exporter_module()
    exporter = _make_exporter(exp)
    exporter._worker = _idle_worker(exp)
    region = types.SimpleNamespace(width=256, height=256)
    context = types.SimpleNamespace(region=region)
    settings = _worker_settings()
    em = _worker_engine_methods({})

    exporter._viewport_last_full_render_ms = 0.0   # cheap / unmeasured
    exporter._worker.desired_generation = 1
    assert exporter._worker_commit_and_submit(
        context, None, settings, region, lambda *a: None, lambda *a: None,
        lambda *a: "path", em, commit_mode='camera') is True
    assert exporter._worker._current_job["width"] == region.width
    assert exporter._worker_refine_pending is False


def test_worker_view_draw_schedules_fullres_refinement():
    """CALL-SITE test: after a reduced-resolution first unit completes
    unsuperseded (worker idle, its generation still the newest), _worker_view_draw
    schedules the full-resolution refinement as the next generation — it bumps the
    desired generation, sets _worker_fullres_next, and re-commits. A stale state is
    never refined (guarded by desired == submitted)."""
    exp = _load_exporter_module()

    class _FakeWorker:
        IDLE = exp._ViewportSpikeWorker.IDLE

        def __init__(self):
            self.state = self.IDLE
            self.submitted_generation = 5
            self.desired_generation = 5

        def request(self):
            self.desired_generation += 1

        def pump(self, present=True):
            pass

    worker = _FakeWorker()
    calls = []

    fake_self = types.SimpleNamespace()
    fake_self._ensure_worker = lambda em, redraw: worker
    fake_self._worker = worker
    fake_self._worker_deferred_scene = False
    fake_self._worker_refine_pending = True
    fake_self._worker_refine_gen = 5
    fake_self._worker_fullres_next = False
    fake_self._viewport_camera_hash = 1
    fake_self._viewport_camera_substantive_hash = 1
    fake_self._viewport_texture = None  # returns before the gpu blit import

    def _commit(context, depsgraph, settings, region, cfg, perf, integ, em,
                commit_mode):
        calls.append((commit_mode, fake_self._worker_fullres_next))
        return False
    fake_self._worker_commit_and_submit = _commit

    region = types.SimpleNamespace(width=64, height=64)
    context = types.SimpleNamespace(region=region)
    scene = types.SimpleNamespace(custom_raytracer=object())
    depsgraph = types.SimpleNamespace(scene=scene)
    em = {"resolve_settings": lambda sc, rep: object()}

    exp.Exporter._worker_view_draw(
        fake_self, context, depsgraph,
        configure_backend_fn=lambda *a, **k: None,
        effective_integrator_name_fn=lambda *a, **k: "path",
        viewport_perf_record_fn=lambda *a, **k: None,
        camera_state_hash_fn=lambda ctx, reg: 1,        # no camera change
        camera_substantive_state_hash_fn=lambda ctx, reg: 1,
        request_viewport_redraw_fn=lambda: None,
        engine_methods=em)

    # Two commits: the ordinary camera commit, then the scheduled full-res refine.
    assert len(calls) == 2, calls
    assert calls[1][0] == 'camera'
    assert calls[1][1] is True, "refinement commit must run with _worker_fullres_next set"
    assert worker.desired_generation == 6          # refinement bumped the generation
    assert fake_self._worker_refine_pending is False

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

"""pkg241 Phase 2.2 — scene-switch worker-drain regression (PR #777).

The wavefront GPU render reaches ONE process-global WfContext singleton whose
contract is "Single render thread assumed" (gpu_wavefront_snapshot.cu:988). Each
viewport session owns its own worker daemon thread with its own per-instance
token, so render() is serialised only WITHIN a session, never ACROSS sessions.

On a .blend switch Blender frees the old RenderEngine but does not guarantee the
old Exporter.__del__ runs before the new file's engine constructs a fresh worker,
so without an explicit drain the old worker daemon survives the load and races the
new worker's render() into the shared WfContext -> illegal memory access in
stage_env_shadow/stage_shade_bucketed + "cudaMalloc failed for s.pixel_index".

The fix (design §3.6): a process-global live-session registry +
`stop_all_viewport_sessions()`, installed as a bpy `load_pre` handler + `atexit`
hook. `load_pre` fires before the incoming file replaces the scene, so every prior
worker is drained to acknowledged exit (or quarantined) on the main thread before
any new worker touches the WfContext.

These tests model the sequence bpy-free with real daemon threads and a shared
"device" guard that records the maximum number of workers rendering into it at
once. Without the drain that maximum is 2 (the crash); with the drain it is 1.
"""

import importlib.util
import os
import threading
import time

import numpy as np

_EXPORTER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "blender_addon", "exporter.py")
_spec = importlib.util.spec_from_file_location(
    "astroray_exporter_scene_switch", _EXPORTER_PATH)
exporter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(exporter)
Worker = exporter._ViewportSpikeWorker


class _Device:
    """Models the process-global wavefront WfContext: single-render-thread. It
    records the peak number of workers inside render() at once so a cross-session
    overlap (the crash) is observable as max_active > 1."""

    def __init__(self):
        self._active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    @property
    def active(self):
        with self._lock:
            return self._active

    def enter(self):
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)

    def exit(self):
        with self._lock:
            self._active -= 1


def _make_render_fn(dev):
    """A progressive render_fn that touches the shared device each chunk and
    honours cooperative cancel (exactly like the real worker's loop shape)."""
    def render_fn(job, cancel_check, publish):
        for _ in range(400):
            if cancel_check():
                return
            dev.enter()
            time.sleep(0.004)
            dev.exit()
            publish(np.zeros((2, 2, 3), np.float32), 2, 2)
    return render_fn


class _Session:
    """Minimal stand-in for an Exporter's worker-owning session. Its stop_worker
    mirrors Exporter.stop_worker's drain (worker.stop -> unregister), which is the
    exact callable stop_all_viewport_sessions() invokes on every live session."""

    def __init__(self, dev):
        self.worker = Worker(_make_render_fn(dev), present_fn=lambda *a: None)
        self.worker.start()
        exporter._register_viewport_session(self)

    def submit(self):
        self.worker.desired_generation += 1
        return self.worker.maybe_submit(lambda g: {"generation": g})

    def stop_worker(self):
        self.worker.stop(timeout=5.0)
        exporter._unregister_viewport_session(self)


def _clear_registry():
    exporter._LIVE_VIEWPORT_SESSIONS.clear()


def _wait(cond, timeout=5.0, interval=0.005):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(interval)
    return cond()


def test_scene_switch_drains_prior_worker_before_new_session():
    """The regression: an in-flight session A is fully drained by the load_pre
    stop_all before session B starts, so the two never render into the shared
    WfContext concurrently (max_active stays 1)."""
    _clear_registry()
    dev = _Device()
    a = _Session(dev)
    assert a.submit()
    assert _wait(lambda: dev.active >= 1)  # A is now mid-render inside the device

    # Scene switch: the load_pre handler drains every live session on the main
    # thread BEFORE the new file loads.
    exporter.stop_all_viewport_sessions()

    assert dev.active == 0, "session A still inside the device after stop_all"
    assert exporter._LIVE_VIEWPORT_SESSIONS == [], "registry not cleared by stop_all"

    # Only now does the incoming file's session B start rendering.
    b = _Session(dev)
    assert b.submit()
    assert _wait(lambda: dev.active >= 1)
    time.sleep(0.05)
    b.stop_worker()

    assert dev.max_active <= 1, (
        "two workers rendered into the shared WfContext at once "
        "(the scene-switch corruption)")
    _clear_registry()


def test_stop_all_waits_for_inflight_ack():
    """stop_all must not return until each in-flight worker has acknowledged exit
    (cancelled + drained + joined), never leaving a live daemon behind — that ack
    is what makes the subsequent scene load safe."""
    _clear_registry()
    dev = _Device()
    a = _Session(dev)
    assert a.submit()
    assert _wait(lambda: dev.active >= 1)

    exporter.stop_all_viewport_sessions()

    assert not a.worker.is_alive(), "worker thread outlived stop_all (no ack)"
    assert a.worker.in_flight_generation is None
    assert exporter._LIVE_VIEWPORT_SESSIONS == []
    _clear_registry()


def test_without_drain_workers_overlap_negative_control():
    """Documents the hazard the fix removes: if the prior session is NOT drained,
    both workers reach the shared device at once (max_active == 2). This is the
    exact overlap stop_all_viewport_sessions() prevents in the test above."""
    _clear_registry()
    dev = _Device()
    a = _Session(dev)
    assert a.submit()
    assert _wait(lambda: dev.active >= 1)

    # No stop_all: session B starts while A is still rendering.
    b = _Session(dev)
    assert b.submit()
    assert _wait(lambda: dev.max_active >= 2, timeout=2.0), (
        "expected the undrained overlap this fix exists to prevent")

    a.stop_worker()
    b.stop_worker()
    _clear_registry()


def test_install_lifecycle_hooks_is_idempotent_and_registers_atexit():
    """_install_lifecycle_hooks installs the drain hooks once (atexit always;
    load_pre only when bpy is importable). Second call is a no-op."""
    exporter._LIFECYCLE_HOOKS_INSTALLED = False
    exporter._install_lifecycle_hooks()
    assert exporter._LIFECYCLE_HOOKS_INSTALLED is True
    # idempotent — a re-register (e.g. addon reload) must not raise or duplicate.
    exporter._install_lifecycle_hooks()
    assert exporter._LIFECYCLE_HOOKS_INSTALLED is True


def test_load_pre_drain_calls_stop_all():
    """The load_pre handler body drains the live registry (the bpy handler simply
    forwards to this)."""
    _clear_registry()
    dev = _Device()
    a = _Session(dev)
    assert a.submit()
    assert _wait(lambda: dev.active >= 1)

    exporter._load_pre_drain(None)  # bpy passes the loaded filepath; ignored

    assert exporter._LIVE_VIEWPORT_SESSIONS == []
    assert dev.active == 0
    _clear_registry()

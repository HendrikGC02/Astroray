"""pkg291 / #879 - viewport worker lifecycle: one render thread at a time.

Root cause of #879 (live ASTRORAY_VIEWPORT_WORKER flip + Rendered toggle crashed
Blender in nvcuda64.dll): view_update/view_draw re-read the env var on EVERY call,
so flipping it to 0 sent the next view_draw down the synchronous path, which ran
renderer.render() on the main thread while the session's worker thread was still
inside renderer.render() (the GPU render releases the GIL) - two threads in the
process-global wavefront WfContext. Reproduced 2/2 in an isolated Blender 5.2 on
the 100k grid before the fix.

The fix: the path is latched per Exporter (switches only at view_update with no
render in flight; leaving worker mode stops the worker first), and the
synchronous path takes the ONE global admission token like the worker and F12.

bpy-free: a real `_ViewportSpikeWorker` + real `Exporter` with stub engine/bpy,
plus an optional real-GPU leg that serialises a worker-thread render and a
main-thread render on one astroray Renderer.
"""
import importlib.util
import threading
import time
import types
from pathlib import Path

import numpy as np
import pytest


def _load_exporter():
    path = Path(__file__).parent.parent / "blender_addon" / "exporter.py"
    spec = importlib.util.spec_from_file_location("astroray_exporter_pkg291_life", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


exp = _load_exporter()


class _Device:
    """Models the single-render-thread WfContext: peak concurrent renderers."""

    def __init__(self):
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def enter(self):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    def exit(self):
        with self._lock:
            self.active -= 1


def _slow_render_fn(dev, chunks=200, chunk_s=0.005):
    def render_fn(job, cancel_check, publish):
        for _ in range(chunks):
            if cancel_check():
                return
            dev.enter()
            time.sleep(chunk_s)
            dev.exit()
            publish(np.zeros((2, 2, 3), np.float32), 2, 2)
    return render_fn


def _exporter():
    class _Engine:
        def report(self, *_a, **_k):
            return None

        def as_pointer(self):
            return 1  # a live engine: never reaped

    e = exp.Exporter(_Engine(), None, types.SimpleNamespace(Renderer=object))
    return e


def _start_worker(e, dev):
    """Install a worker on the exporter the way _ensure_worker does (global
    token, live-session registry) with a controllable render_fn."""
    w = exp._ViewportSpikeWorker(_slow_render_fn(dev), present_fn=lambda *a: None,
                                 token=exp._GLOBAL_ADMISSION_TOKEN)
    w.start()
    e._worker = w
    exp._register_viewport_session(e)
    return w


def _submit(w):
    w.desired_generation += 1
    assert w.maybe_submit(lambda g: {"generation": g})


def _wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


@pytest.fixture(autouse=True)
def _clean():
    exp._LIVE_VIEWPORT_SESSIONS.clear()
    yield
    for s in exp._LIVE_VIEWPORT_SESSIONS[:]:
        s.stop_worker()
    assert not exp._GLOBAL_ADMISSION_TOKEN.locked()


def _live_spike_threads():
    return [t for t in threading.enumerate() if t.name == "astroray-viewport-spike"]


def test_mode_latched_until_view_update_with_no_render_in_flight(monkeypatch):
    dev = _Device()
    e = _exporter()
    monkeypatch.setenv("ASTRORAY_VIEWPORT_WORKER", "1")
    assert e._resolve_worker_mode(at_view_update=False) is True
    w = _start_worker(e, dev)
    _submit(w)
    assert _wait(lambda: dev.active == 1)
    monkeypatch.setenv("ASTRORAY_VIEWPORT_WORKER", "0")
    # view_draw never switches; view_update does not switch mid-render.
    assert e._resolve_worker_mode(at_view_update=False) is True
    assert e._resolve_worker_mode(at_view_update=True) is True
    assert e._worker is w and w.is_alive()
    # Once the render drains, view_update switches and stops the worker first.
    w.request()
    assert _wait(lambda: (w.pump(present=False), w.in_flight_generation is None)[1])
    assert e._resolve_worker_mode(at_view_update=True) is False
    assert e._worker is None and not w.is_alive()
    assert e not in exp._LIVE_VIEWPORT_SESSIONS
    assert dev.max_active == 1


def test_sync_path_never_overlaps_a_worker_render(monkeypatch):
    """The #879 race: a sync-path render while a worker render is in flight.
    _enter_sync_path waits for the token (bounded), so the device never sees two
    renderers; on timeout it skips the frame instead of rendering."""
    dev = _Device()
    owner = _exporter()
    w = _start_worker(owner, dev)        # e.g. a sibling viewport in worker mode
    _submit(w)
    assert _wait(lambda: dev.active == 1)
    sync = _exporter()
    sync._worker_mode = False
    redraws = []
    monkeypatch.setattr(exp, "SYNC_ADMISSION_TIMEOUT_S", 0.02)
    assert sync._enter_sync_path(lambda: redraws.append(1)) is False  # worker busy
    assert redraws == [1]
    w.request()                          # worker cancels at the next chunk
    monkeypatch.setattr(exp, "SYNC_ADMISSION_TIMEOUT_S", 5.0)
    assert sync._enter_sync_path(lambda: None) is True
    try:
        assert dev.active == 0           # the worker render has fully left
        dev.enter(); dev.exit()          # the main-thread render
    finally:
        sync._exit_sync_path()
    assert dev.max_active == 1


def test_sync_path_does_not_wait_on_f12():
    e = _exporter()
    assert exp._GLOBAL_ADMISSION_TOKEN.acquire(blocking=False)
    exp._F12_PAUSE_GATE.set()
    try:
        t0 = time.perf_counter()
        assert e._enter_sync_path(lambda: None) is False
        assert time.perf_counter() - t0 < 0.05
    finally:
        exp._F12_PAUSE_GATE.clear()
        exp._GLOBAL_ADMISSION_TOKEN.release()


def test_start_stop_start_same_exporter_and_stop_in_flight():
    dev = _Device()
    e = _exporter()
    before = len(_live_spike_threads())
    for _ in range(3):
        w = _start_worker(e, dev)
        _submit(w)
        assert _wait(lambda: dev.active == 1)
        e.stop_worker()                  # stop while a render is in flight
        assert not w.is_alive()
        assert not exp._GLOBAL_ADMISSION_TOKEN.locked()
    assert len(_live_spike_threads()) == before
    assert dev.max_active == 1


def test_teardown_with_queued_present_presents_nothing_after_stop():
    presented = []
    e = _exporter()
    w = exp._ViewportSpikeWorker(
        lambda job, cc, publish: publish(np.zeros((2, 2, 3), np.float32), 2, 2),
        present_fn=lambda *a: presented.append(a), token=exp._GLOBAL_ADMISSION_TOKEN)
    w.start()
    e._worker = w
    exp._register_viewport_session(e)
    _submit(w)
    assert _wait(lambda: w.mailbox_depth == 1)
    e.stop_worker()
    # The queued frame is dropped with the worker: the exporter no longer
    # references it, so no later view_draw can present it.
    assert not w.is_alive() and presented == [] and e._worker is None
    assert not exp._GLOBAL_ADMISSION_TOKEN.locked()


# ---------------------------------------------------------------- real GPU
@pytest.mark.gpu
def test_gpu_worker_then_sync_render_one_context(capfd):
    """Real CUDA: a worker-thread progressive render on a renderer, then a
    live switch to the synchronous path rendering the SAME renderer on the main
    thread. Both resolve the same device (one primary context), the sync render
    starts only after the worker released the token, and no CUDA error is
    logged."""
    import runtime_setup
    runtime_setup.configure_test_imports()
    import astroray

    r = astroray.Renderer()
    if not r.gpu_available:
        pytest.skip("CUDA device not available")
    r.set_use_gpu(True)
    mat = r.create_material("lambertian", [0.7, 0.7, 0.7], {})
    for i in range(200):
        x = (i % 20) * 0.2 - 2.0
        z = (i // 20) * 0.2 - 1.0
        r.add_triangle([x, -0.5, z], [x + 0.2, -0.5, z], [x, -0.5, z + 0.2], mat)
    r.add_sphere([0, 0, 0], 0.5, mat)
    r.setup_camera([0, 0, 3], [0, 0, 0], [0, 1, 0], 40.0, 1.0, 0.0, 3.0, 64, 64)
    r.set_background_color([0.5, 0.5, 0.5])

    devices, spans = [], []
    e = _exporter()

    def render_fn(job, cancel_check, publish):
        for _ in range(400):
            if cancel_check():
                return
            t0 = time.perf_counter()
            px = r.render(1, 4, lambda _f: not cancel_check(), False,
                          4, 4, 4, 4, 4, False, 0)
            spans.append(("worker", t0, time.perf_counter()))
            devices.append(r.last_render_info().get("device", -1))
            if px is not None:
                publish(np.asarray(px), 64, 64)

    w = exp._ViewportSpikeWorker(render_fn, present_fn=lambda *a: None,
                                 token=exp._GLOBAL_ADMISSION_TOKEN)
    w.start()
    e._worker = w
    e._worker_mode = True
    exp._register_viewport_session(e)
    _submit(w)
    assert _wait(lambda: len(spans) >= 3, timeout=30.0)
    # Live flip to the synchronous path at view_update.
    import os
    old = os.environ.get("ASTRORAY_VIEWPORT_WORKER")
    os.environ["ASTRORAY_VIEWPORT_WORKER"] = "0"
    try:
        w.request()
        assert _wait(lambda: (w.pump(present=False), w.in_flight_generation is None)[1], 30.0)
        assert e._resolve_worker_mode(at_view_update=True) is False
        assert not w.is_alive()
        assert e._enter_sync_path(lambda: None)
        try:
            t0 = time.perf_counter()
            r.render(1, 4, None, False, 4, 4, 4, 4, 4, False, 0)
            spans.append(("sync", t0, time.perf_counter()))
            devices.append(r.last_render_info().get("device", -1))
        finally:
            e._exit_sync_path()
    finally:
        if old is None:
            os.environ.pop("ASTRORAY_VIEWPORT_WORKER", None)
        else:
            os.environ["ASTRORAY_VIEWPORT_WORKER"] = old
    worker_end = max(s[2] for s in spans if s[0] == "worker")
    sync_start = next(s[1] for s in spans if s[0] == "sync")
    assert sync_start >= worker_end            # never overlapped
    assert len(set(devices)) == 1 and devices[0] >= 0
    err = capfd.readouterr().err.lower()
    assert "illegal" not in err and "cudaerror" not in err and "invalid value" not in err


def test_refinement_waits_one_draw_behind_a_fresh_present():
    """pkg291 gate (a) lifeline: the coarse unit was uploaded at +34 ms but shown
    at +210 ms because the full-res refinement's commit ran in the same draw,
    before the blit. A draw that presents a new frame defers the refinement to
    the next redraw (requested); the following draw schedules it."""
    class _W:
        IDLE = exp._ViewportSpikeWorker.IDLE

        def __init__(self):
            self.state, self.submitted_generation, self.desired_generation = self.IDLE, 5, 5
            self.presents, self.present_next = 0, True

        def request(self):
            self.desired_generation += 1

        def pump(self, present=True):
            if present and self.present_next:
                self.presents += 1
                self.present_next = False

    w = _W()
    calls, redraws = [], []
    s = types.SimpleNamespace(
        _ensure_worker=lambda em, rd: w, _worker=w, _worker_deferred_scene=False,
        _worker_refine_pending=True, _worker_refine_gen=5, _worker_fullres_next=False,
        _viewport_camera_hash=1, _viewport_camera_substantive_hash=1, _viewport_texture=None)
    s._worker_commit_and_submit = lambda *a, **k: (calls.append(
        (k["commit_mode"], s._worker_fullres_next)), True)[1]
    ctx = types.SimpleNamespace(region=types.SimpleNamespace(width=64, height=64))
    dg = types.SimpleNamespace(scene=types.SimpleNamespace(custom_raytracer=object()))
    kw = dict(configure_backend_fn=None, effective_integrator_name_fn=None,
              viewport_perf_record_fn=None, camera_state_hash_fn=lambda c, r: 1,
              camera_substantive_state_hash_fn=lambda c, r: 1,
              request_viewport_redraw_fn=lambda: redraws.append(1),
              engine_methods={"resolve_settings": lambda sc, rp: object()})
    exp.Exporter._worker_view_draw(s, ctx, dg, **kw)
    assert [c for c in calls if c[1]] == [] and s._worker_refine_pending and redraws
    exp.Exporter._worker_view_draw(s, ctx, dg, **kw)       # next redraw: no new frame
    assert any(c[1] for c in calls) and not s._worker_refine_pending

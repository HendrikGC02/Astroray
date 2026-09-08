"""pkg241 Phase 2 A2 spike — in-process tests for the off-thread viewport worker
state machine (`blender_addon/exporter.py::_ViewportSpikeWorker`, design §3.2-§3.4).

The worker is deliberately bpy-free, so these tests exercise it directly with
stubbed render / present / report callables and a real daemon thread. Each test
controls the worker thread's timing through the injected render_fn (a gate Event
+ cancel_check), so the state-machine assertions are deterministic.

Covers the brief's required scenarios:
  - the worker publishes a frame and the main-thread pump presents it;
  - view_draw-style blit reads the presented frame without triggering a render;
  - a late idle(N) after desired advanced to N+2 advances the machine and the
    next submit is N+2 (never N+1);
  - a frame for a superseded generation is discarded (no stale present);
  - an error for a superseded generation is still processed;
  - the mailbox depth never exceeds 1;
  - stop() pumps the control queue (worker idle acknowledged) before release.
"""

import importlib.util
import os
import threading
import time

import numpy as np


# --- load the standalone exporter module (bpy-free) -----------------------
_EXPORTER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "blender_addon", "exporter.py")
_spec = importlib.util.spec_from_file_location("astroray_exporter_spike", _EXPORTER_PATH)
exporter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(exporter)
Worker = exporter._ViewportSpikeWorker


def _frame(val=0.0):
    return np.full((2, 2, 3), float(val), dtype=np.float32)


def _wait(cond, timeout=5.0, interval=0.005):
    """Spin until cond() is truthy or timeout elapses; returns cond()'s last value."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = cond()
        if v:
            return v
        time.sleep(interval)
    return cond()


class _Harness:
    """Owns the injected callables and accounting for one worker under test."""

    def __init__(self, render_fn):
        self.presented = []          # (buffer, width, height, generation)
        self.commits = []            # generations committed (main thread)
        self.reports = []            # error messages
        self.worker = Worker(
            render_fn=render_fn,
            present_fn=self._present,
            report_fn=self.reports.append,
        )
        self.worker.start()

    def _present(self, buffer, width, height, generation):
        self.presented.append((buffer, width, height, generation))

    def commit(self, generation):
        self.commits.append(generation)
        return {"generation": generation}

    def edit_and_submit(self):
        """Simulate one main-thread edit + immediate submit attempt."""
        self.worker.request()
        return self.worker.maybe_submit(self.commit)

    def teardown(self):
        self.worker.stop(timeout=2.0)


def test_worker_publishes_a_frame_and_pump_presents_it():
    gate = threading.Event()
    entered = threading.Event()

    def render_fn(job, cancel_check, publish):
        entered.set()
        gate.wait(5)
        publish(_frame(0.5), 2, 2)

    h = _Harness(render_fn)
    try:
        assert h.edit_and_submit() is True
        assert h.worker.state == Worker.RENDERING
        assert _wait(entered.is_set)
        gate.set()
        # wait until the worker has enqueued idle (control queue non-empty)
        assert _wait(lambda: not h.worker._control.empty())
        h.worker.pump()
        assert h.worker.state == Worker.IDLE
        assert len(h.presented) == 1
        buf, w, ht, gen = h.presented[0]
        assert gen == 1 and w == 2 and ht == 2
        assert np.allclose(buf, 0.5)
        assert h.worker.presents == 1
        assert h.worker.completed_generations == 1
    finally:
        h.teardown()


def test_control_only_pump_does_not_present_but_preserves_the_frame():
    """pkg241 P2.2 item 1: the bpy.app.timers liveness pump calls pump(present=False)
    so it never builds a GPUTexture off a draw context. It must still advance the
    control-plane state machine (idle -> IDLE) but must NOT consume the mailbox
    frame; a later pump() from the view_draw draw context then presents it. This is
    the fix for the spike's presented=0 (the timer ate the only pending frame in an
    invalid GPU context and it was lost before view_draw could present it)."""
    gate = threading.Event()

    def render_fn(job, cancel_check, publish):
        publish(_frame(0.7), 2, 2)
        gate.set()

    h = _Harness(render_fn)
    try:
        h.edit_and_submit()
        assert _wait(gate.is_set)
        assert _wait(lambda: not h.worker._control.empty())
        assert _wait(lambda: h.worker.mailbox_depth == 1)
        # Timer-style pump: advances the state machine but presents nothing and
        # leaves the frame in the mailbox for the draw-context pump.
        h.worker.pump(present=False)
        assert h.worker.state == Worker.IDLE          # control advanced
        assert h.presented == []                      # nothing presented off-context
        assert h.worker.mailbox_depth == 1            # frame preserved, not lost
        # view_draw-style pump (draw context): now presents the preserved frame.
        h.worker.pump()
        assert len(h.presented) == 1
        assert np.allclose(h.presented[0][0], 0.7)
        assert h.worker.presents == 1
    finally:
        h.teardown()


def test_view_draw_blit_reads_frame_without_triggering_render():
    """After a frame is published, repeated pumps (the view_draw/timer liveness
    loop) must NOT call render_fn again while nothing new is desired — view_draw
    only blits the latest published buffer (§3.3)."""
    gate = threading.Event()
    calls = {"n": 0}

    def render_fn(job, cancel_check, publish):
        calls["n"] += 1
        publish(_frame(0.25), 2, 2)
        gate.set()

    h = _Harness(render_fn)
    try:
        h.edit_and_submit()
        assert _wait(gate.is_set)
        assert _wait(lambda: not h.worker._control.empty())
        h.worker.pump()
        assert calls["n"] == 1
        # Several more pumps (idle viewport / timer ticks) with no new edit:
        for _ in range(5):
            h.worker.pump()
            h.worker.maybe_submit(h.commit)  # no new desired generation
        assert calls["n"] == 1  # render_fn never re-invoked
        assert len(h.presented) == 1  # the one published frame, presented once
    finally:
        h.teardown()


def test_late_idle_after_desired_n_plus_2_submits_n_plus_2():
    """N is cancelled and N+2 requested before idle(N) drains; the late idle(N)
    validates against the in-flight generation and advances the machine, and the
    NEXT submit is N+2, never N+1 (§3.4 control-plane validation)."""
    gate = threading.Event()
    entered = threading.Event()

    def render_fn(job, cancel_check, publish):
        entered.set()
        # respect cancel so the run ends promptly after the edits
        while not gate.is_set() and not cancel_check():
            time.sleep(0.005)

    h = _Harness(render_fn)
    try:
        # submit generation 1
        h.worker.request()
        assert h.worker.maybe_submit(h.commit) is True
        assert h.worker.submitted_generation == 1
        assert _wait(entered.is_set)
        # two further edits while gen 1 is in flight -> desired advances to 3
        h.worker.request()  # desired 2
        h.worker.request()  # desired 3
        assert h.worker.desired_generation == 3
        assert h.worker.maybe_submit(h.commit) is False  # still RENDERING
        # gen 1's render ends (cancelled), worker enqueues idle(1)
        assert _wait(lambda: not h.worker._control.empty())
        h.worker.pump()
        assert h.worker.state == Worker.IDLE
        assert h.worker.in_flight_generation is None
        # the next submit must be generation 3 (N+2), never 2 (N+1)
        assert h.worker.maybe_submit(h.commit) is True
        assert h.worker.submitted_generation == 3
        assert h.commits == [1, 3]  # generation 2 was never committed/submitted
        gate.set()
    finally:
        h.teardown()


def test_frame_for_superseded_generation_is_discarded():
    """A published frame whose generation is older than desired_generation is
    discarded on drain and never presented (no stale present after an edit)."""
    entered = threading.Event()
    gate = threading.Event()

    def render_fn(job, cancel_check, publish):
        publish(_frame(0.9), 2, 2)  # publish for generation 1
        entered.set()
        while not gate.is_set() and not cancel_check():
            time.sleep(0.005)

    h = _Harness(render_fn)
    try:
        h.worker.request()
        h.worker.maybe_submit(h.commit)  # submit gen 1
        assert _wait(entered.is_set)
        assert _wait(lambda: h.worker.mailbox_depth == 1)
        # a new edit supersedes gen 1 before the pump presents it
        h.worker.request()  # desired 2
        h.worker.pump()      # drains mailbox: frame gen 1 < desired 2 -> discard
        assert h.presented == []  # never presented a superseded frame
        gate.set()
    finally:
        h.teardown()


def test_error_for_superseded_generation_is_still_processed():
    """A worker error tagged with a superseded generation is NOT dropped — it is
    processed for the current session/epoch, marking the session dead (§3.4)."""
    entered = threading.Event()
    gate = threading.Event()

    class Boom(RuntimeError):
        pass

    def render_fn(job, cancel_check, publish):
        entered.set()
        gate.wait(5)
        raise Boom("worker CUDA fault")

    h = _Harness(render_fn)
    try:
        h.worker.request()
        h.worker.maybe_submit(h.commit)  # submit gen 1
        assert _wait(entered.is_set)
        h.worker.request()  # desired 2
        h.worker.request()  # desired 3 — gen 1 now superseded
        gate.set()
        assert _wait(lambda: h.worker._control.qsize() >= 1)
        # wait until both error + idle are enqueued
        assert _wait(lambda: h.worker._control.qsize() >= 2)
        h.worker.pump()
        assert h.worker.state == Worker.DEAD
        assert len(h.reports) == 1
        assert "gen 1" in h.reports[0]
    finally:
        h.teardown()


def test_mailbox_depth_never_exceeds_one():
    """Two publishes before a drain leave the depth-1 mailbox at depth 1 — the
    newer frame replaces the unconsumed older one (§3.3)."""
    entered = threading.Event()
    gate = threading.Event()

    def render_fn(job, cancel_check, publish):
        publish(_frame(0.1), 2, 2)
        publish(_frame(0.2), 2, 2)  # replaces the first, unconsumed
        entered.set()
        gate.wait(5)

    h = _Harness(render_fn)
    try:
        h.worker.request()
        h.worker.maybe_submit(h.commit)
        assert _wait(entered.is_set)
        assert h.worker.mailbox_depth == 1
        assert h.worker.mailbox_depth_max == 1
        h.worker.pump()  # presents the newest (0.2)
        buf = h.presented[0][0]
        assert np.allclose(buf, 0.2)
        gate.set()
    finally:
        h.teardown()


def test_stop_pumps_control_queue_before_release():
    """stop() must request cancel, PUMP the control queue until the worker
    acknowledges idle, and only then report it is safe to release (return True).
    The worker thread must be joined (not leaked)."""
    entered = threading.Event()

    def render_fn(job, cancel_check, publish):
        entered.set()
        # a well-behaved worker: run until cancel is requested
        while not cancel_check():
            time.sleep(0.005)

    h = _Harness(render_fn)
    h.worker.request()
    h.worker.maybe_submit(h.commit)
    assert _wait(entered.is_set)
    assert h.worker.state == Worker.RENDERING
    released = h.worker.stop(timeout=3.0)
    assert released is True                       # acknowledged before release
    assert h.worker.in_flight_generation is None  # idle was pumped
    assert not h.worker.is_alive()                # thread joined, not leaked


def test_worker_view_update_pumps_control_only_preserving_the_frame():
    """pkg241 P2.2 item 2 (Terra review 4) — CALL-SITE test: Exporter._worker_
    view_update must pump the worker with present=False (it is not a GPU draw
    context). If it pumped with the default present=True, _drain_mailbox would
    clear the depth-1 mailbox off a draw context and lose the queued frame before
    view_draw could present it — exactly the spike's presented=0 grid. This spies
    the actual view_update call site rather than the worker's pump() in isolation
    (which test_control_only_pump_does_not_present_but_preserves_the_frame covers).
    """
    import types

    pump_calls = []

    class _FakeWorker:
        def request(self):
            pass

        def pump(self, present=True):
            pump_calls.append(present)

    fake_worker = _FakeWorker()

    # Minimal fake Exporter self: only the attributes _worker_view_update touches.
    fake_self = types.SimpleNamespace()
    fake_self.engine = types.SimpleNamespace(report=lambda *a, **k: None)
    fake_self._ensure_worker = lambda em, redraw: fake_worker
    fake_self._worker_deferred_scene = False
    fake_self._viewport_camera_hash = None
    fake_self._viewport_camera_substantive_hash = None
    # commit succeeds (worker idle) so the deferred-scene branch is not taken.
    fake_self._worker_commit_and_submit = lambda *a, **k: True

    settings = object()
    region = types.SimpleNamespace(width=64, height=64)
    context = types.SimpleNamespace(region=region)
    scene = types.SimpleNamespace(custom_raytracer=settings)
    depsgraph = types.SimpleNamespace(scene=scene)
    engine_methods = {"resolve_settings": lambda sc, rep: settings}

    exporter.Exporter._worker_view_update(
        fake_self, context, depsgraph,
        configure_backend_fn=lambda *a, **k: None,
        effective_integrator_name_fn=lambda *a, **k: "path",
        viewport_perf_record_fn=lambda *a, **k: None,
        camera_state_hash_fn=lambda ctx, reg: 1,
        camera_substantive_state_hash_fn=lambda ctx, reg: 1,
        request_viewport_redraw_fn=lambda: None,
        engine_methods=engine_methods)

    # The single pump in view_update must be control-plane only (present=False).
    assert pump_calls == [False]


def test_cancel_request_emitted_only_for_in_flight_generation_once():
    """pkg241 P2.2 item 4 (Terra review 4): request() emits cancel_request only
    for the ACTUAL in-flight generation and only on the false->true transition of
    the cancel flag — never while IDLE, never repeated while already cancelling."""
    gate = threading.Event()
    entered = threading.Event()

    def render_fn(job, cancel_check, publish):
        entered.set()
        while not gate.is_set() and not cancel_check():
            time.sleep(0.005)

    captured = []
    orig_sink = exporter._spike_event_sink
    exporter._spike_event_sink = lambda name, gen, t, epoch, extra: \
        captured.append((name, gen))
    h = _Harness(render_fn)
    try:
        # request while IDLE (nothing in flight) -> NO cancel_request.
        h.worker.request()  # desired 1
        assert [e for e in captured if e[0] == "cancel_request"] == []
        h.worker.maybe_submit(h.commit)  # submit gen 1, clears cancel flag
        assert _wait(entered.is_set)
        # first edit while gen 1 renders -> one cancel_request(1) (false->true).
        h.worker.request()  # desired 2
        cancels = [e for e in captured if e[0] == "cancel_request"]
        assert cancels == [("cancel_request", 1)]
        # repeated edit while already cancelling -> NO further cancel_request.
        h.worker.request()  # desired 3, cancel flag already set
        cancels = [e for e in captured if e[0] == "cancel_request"]
        assert cancels == [("cancel_request", 1)]
        gate.set()
    finally:
        exporter._spike_event_sink = orig_sink
        h.teardown()

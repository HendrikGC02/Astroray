"""pkg266 (#817) — viewport worker: present-while-orbiting + full-res refinement.

bpy-free unit tests (bpy stubbed, no CUDA) for the two worker-path bugs the owner
hit on the #812 default-ON off-thread worker and the pkg266 §9 driver never saw
(it edited camera OBJECTS via view_update; the failure is region-view navigation,
i.e. continuous `view_draw` camera-hash changes):

  Bug 1 — no presentation while orbiting. Every camera-changing view_draw called
    `worker.request()`, which cancelled the in-flight render before it published a
    single chunk; the just-published frame of the superseded generation was then
    discarded by the "== desired_generation" present gate. Nothing presented until
    the camera stopped. Fix: a camera move over a cheap reduced-resolution preview
    uses `cancel_inflight=False` (let the short chunk finish + publish) and the
    mailbox presents any frame at/above `present_floor_generation` (a camera move
    does not raise the floor — only a scene/material edit does).

  Bug 2 — refinement stuck at the reduced first-unit resolution. The reduced first
    unit rendered the FULL target spp at reduced res before scheduling full res, so
    the viewport sat at the coarse resolution for the whole sample sweep. Fix: the
    reduced first unit renders a single coarse chunk, then hands off to the
    full-resolution refinement.

These drive the REAL `_ViewportSpikeWorker` + `_worker_view_draw` /
`_worker_view_update` with a fast fake renderer. The orbit test FAILS against the
pre-fix code (presents == 0 during the orbit).
"""

import importlib.util
import time
import types
from pathlib import Path

import numpy as np


def _load_exporter_module():
    module_path = Path(__file__).parent.parent / "blender_addon" / "exporter.py"
    spec = importlib.util.spec_from_file_location(
        "astroray_exporter_pkg266_orbit", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Material:
    def __init__(self, name="mat"):
        self.name = name


class _DepsgraphUpdate:
    def __init__(self, id, *, geometry=False, transform=False, shading=False):
        self.id = id
        self.is_updated_geometry = geometry
        self.is_updated_transform = transform
        self.is_updated_shading = shading


class _FakeRenderer:
    """Chunk render honouring the cooperative cancel; ~a few ms per sub-pass so an
    orbit frame arriving mid-chunk can cancel it (the GUI failure mode)."""
    def __init__(self, ms_per_subpass=0.01):
        self._units = 0
        self._cancel = -1
        self._ms = ms_per_subpass

    def render(self, samples, depth, progress, gamma, d, g, t, v, tr,
               skip_upload, sub_pass_budget):
        budget = max(1, int(sub_pass_budget))
        self._units = 0
        self._cancel = -1
        p = 0
        while p < samples:
            time.sleep(self._ms)
            self._units += 1
            if progress is not None and not progress(0.0):
                self._cancel = self._units
                return None
            p += budget
        return np.zeros((2, 2, 3), dtype=np.float32)

    def last_render_info(self):
        return {"device": 0, "units_launched": self._units,
                "cancelled_at_unit": self._cancel}

    def set_wavelength_range(self, a, b): pass
    def set_output_mode(self, m): pass
    def set_integrator(self, n): pass
    def clear_passes(self): pass
    def add_pass(self, n): pass
    def get_render_pass_buffer(self, n):
        return np.zeros((2, 2, 3), dtype=np.float32)


def _settings():
    return types.SimpleNamespace(
        max_bounces=8, viewport_display_pass="combined",
        diffuse_bounces=4, glossy_bounces=4, transmission_bounces=4,
        volume_bounces=4, transparent_bounces=4,
        preview_samples=64, viewport_chunk_spp=4)


def _engine_methods(presents):
    def upd(buf, w, h):
        presents.append((w, h))
    return {
        "setup_viewport_camera": lambda r, c, w, h: None,
        "wavelength_range_from_settings": lambda s: (400.0, 700.0),
        "effective_integrator_name": lambda s: "path",
        "viewport_target_samples": lambda s: 64,
        "viewport_chunk_samples": lambda s, cur: min(4, max(0, 64 - int(cur))),
        "resolve_settings": lambda scene, rep: _settings(),
        "update_viewport_texture": upd,
    }


def _build_exporter(exp, presents):
    bpy = types.SimpleNamespace(types=types.SimpleNamespace(Material=_Material))

    class _StubEngine:
        def __init__(self):
            self._renderer_instance_id_map = {}
            self._renderer_instancer_eligible = {}

        def report(self, *_a, **_k):
            return None

    astroray = types.SimpleNamespace(Renderer=_FakeRenderer)
    exporter = exp.Exporter(_StubEngine(), bpy, astroray)
    exporter._viewport_full_synced = True
    fake = _FakeRenderer()
    exporter._get_viewport_renderer = lambda: fake
    exporter.sync_viewport_scene = lambda *a, **k: setattr(
        exporter, "_viewport_full_synced", True)
    exporter.apply_depsgraph_updates = lambda *a, **k: 'dispatched'
    return exporter


def _args(dg, region, em, camhash):
    context = types.SimpleNamespace(region=region)
    redraw = lambda: None
    chash = lambda c, r: camhash[0]
    return (context, dg, (lambda *a, **k: None), (lambda s: "path"),
            (lambda *a, **k: None), chash, chash, redraw, em)


def test_orbit_presents_continuously():
    """#817 bug 1: a continuous region-view orbit must keep presenting frames
    (pre-fix: zero presents until the camera stopped)."""
    exp = _load_exporter_module()
    presents = []
    exporter = _build_exporter(exp, presents)
    em = _engine_methods(presents)
    region = types.SimpleNamespace(width=128, height=128)
    scene = types.SimpleNamespace(custom_raytracer=_settings(), world=None)
    dg = types.SimpleNamespace(scene=scene, updates=[])
    camhash = [1000.0]
    # Expensive profile so the reduced first unit engages (the owner's scene).
    exporter._viewport_last_full_render_ms = 500.0
    a = _args(dg, region, em, camhash)
    try:
        t_end = time.perf_counter() + 1.5
        n = 0
        while time.perf_counter() < t_end:
            camhash[0] += 1.0          # the view rotated this frame (orbit)
            exporter._worker_view_draw(*a)
            n += 1
            time.sleep(0.004)          # ~250 Hz redraw during a drag
        assert exporter._worker.presents > 0, (
            "no frame presented during the orbit — the worker cancelled every "
            "generation before it could publish (#817 bug 1)")
        # The presented frames during a move are the reduced-resolution preview.
        assert any(p != (128, 128) for p in presents), (
            "orbit presents should include the reduced-resolution preview")
    finally:
        exporter._worker.stop(timeout=2.0)


def test_reduced_first_unit_is_brief_then_full_res():
    """#817 bug 2: after the camera settles the reduced first unit is a brief
    coarse preview, then the full-resolution refinement takes over — the viewport
    must NOT sit at the reduced resolution for the whole sample sweep."""
    exp = _load_exporter_module()
    presents = []
    exporter = _build_exporter(exp, presents)
    em = _engine_methods(presents)
    region = types.SimpleNamespace(width=128, height=128)
    scene = types.SimpleNamespace(custom_raytracer=_settings(), world=None)
    dg = types.SimpleNamespace(scene=scene, updates=[])
    camhash = [1000.0]
    exporter._viewport_last_full_render_ms = 500.0
    a = _args(dg, region, em, camhash)
    try:
        # One camera move, then hold the camera still and let it settle.
        camhash[0] += 1.0
        exporter._worker_view_draw(*a)
        t_end = time.perf_counter() + 3.0
        while time.perf_counter() < t_end:
            exporter._worker_view_draw(*a)   # camera stable
            time.sleep(0.01)
        reduced = [p for p in presents if p != (128, 128)]
        full = [p for p in presents if p == (128, 128)]
        assert full, "the full-resolution refinement never presented (#817 bug 2)"
        # The reduced preview is one chunk per reduced generation, not the whole
        # 64-spp sweep (pre-fix: 16 reduced presents before any full-res frame).
        assert len(reduced) <= 3, (
            f"too many reduced-resolution presents ({len(reduced)}): the reduced "
            f"first unit rendered the full sample sweep at reduced res (#817 bug 2)")
    finally:
        exporter._worker.stop(timeout=2.0)


def test_present_floor_blocks_stale_content_after_edit():
    """A scene/material edit raises present_floor_generation so a pre-edit frame is
    never blitted (no stale-content present after an edit)."""
    exp = _load_exporter_module()

    class _W:
        DEAD = exp._ViewportSpikeWorker.DEAD
    presented = []
    w = exp._ViewportSpikeWorker(
        render_fn=lambda *a, **k: None,
        present_fn=lambda buf, wd, ht, g: presented.append(g))
    # Publish a frame for generation 2, then a scene edit moves the floor to 5.
    w.desired_generation = 5
    w.present_floor_generation = 5
    w._publish_frame(2, np.zeros((1, 1, 3), np.float32), 1, 1, spp=1)
    w._drain_mailbox()
    assert presented == [], "a pre-edit (below-floor) frame must not present"
    # A current-content frame (generation 5) presents.
    w._publish_frame(5, np.zeros((1, 1, 3), np.float32), 1, 1, spp=1)
    w._drain_mailbox()
    assert presented == [5]
    # A camera move (desired 6, floor still 5) — a generation-5 preview stays
    # presentable (one-step-stale orbit frame), and so does the newer 6.
    w.desired_generation = 6
    w._publish_frame(5, np.zeros((1, 1, 3), np.float32), 1, 1, spp=1)
    w._drain_mailbox()
    assert presented == [5, 5]


def test_camera_request_does_not_cancel_cheap_preview():
    """request(cancel_inflight=False) bumps the generation without setting the
    cancel event, so a cheap reduced preview in flight finishes and publishes."""
    exp = _load_exporter_module()
    w = exp._ViewportSpikeWorker(
        render_fn=lambda *a, **k: None, present_fn=lambda *a, **k: None)
    w.in_flight_generation = 3
    w._cancel_event.clear()
    w.request(cancel_inflight=False)
    assert w.desired_generation == 1  # bumped from 0
    assert not w._cancel_event.is_set(), "cheap preview must not be cancelled"
    # A full-res in flight IS cancelled by the default.
    w.request(cancel_inflight=True)
    assert w._cancel_event.is_set()

"""pkg266 Viewport Phase 2.3 — present-rate root cause (completed=0 regression).

bpy-free unit test (bpy stubbed, no CUDA) for the present-rate=0 root cause found
in the Batch B §9 GUI data point (worker ON: completed=0 / presented=0 while the
device rendered 285 chunks).

Root cause: Blender fires `view_update` not only on genuine edits but also during
a settle span (a depsgraph re-evaluation triggered by the worker's own
tag_redraw), with an EMPTY or selection-only `depsgraph.updates`. The off-thread
worker requested a NEW generation on EVERY view_update (`worker.request()` is
unconditional), so the in-flight render was cancelled before it reached its
uncancelled `render_end` — no `terminal_publication` ever fired and present-rate
was UNGRADEABLE. The synchronous path returns early on a no-domain ('idle')
dispatch; the fix mirrors that on the worker path (a cache-free
`_depsgraph_has_image_changing_update` peek).

This test drives the REAL `_ViewportSpikeWorker` + `_worker_view_update` /
`_worker_view_draw` with a fast fake renderer: one genuine material edit followed
by a settle span of spurious (empty-`updates`) view_updates. It FAILS against the
pre-fix code (completed == 0) and PASSES with the guard (a generation reaches its
uncancelled terminal).
"""

import importlib.util
import threading
import time
import types
from pathlib import Path

import numpy as np


def _load_exporter_module():
    module_path = Path(__file__).parent.parent / "blender_addon" / "exporter.py"
    spec = importlib.util.spec_from_file_location(
        "astroray_exporter_pkg266_settle", module_path)
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
    """Chunk render that honours the cooperative cancel (progress) hook; ~2 ms
    per sub-pass so a full target completes fast in the test."""
    def __init__(self):
        self._units = 0
        self._cancel = -1

    def render(self, samples, depth, progress, gamma, d, g, t, v, tr,
               skip_upload, sub_pass_budget):
        # ~40 ms per render() chunk (a realistic big-scene chunk) with a cancel
        # poll every sub-pass, so a spurious view_update firing every few ms can
        # cancel the chunk mid-flight (the GUI failure mode). Total generation
        # (target / chunk chunks) >> the spurious view_update interval.
        budget = max(1, int(sub_pass_budget))
        self._units = 0
        self._cancel = -1
        p = 0
        while p < samples:
            time.sleep(0.02)
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


def _build_exporter(exp):
    bpy = types.SimpleNamespace(
        types=types.SimpleNamespace(Material=_Material))

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
    # A no-change depsgraph classification (settle spurious updates) / a cheap full
    # sync for the genuine edit — neither mutates the fake renderer meaningfully.
    exporter.sync_viewport_scene = lambda *a, **k: setattr(
        exporter, "_viewport_full_synced", True)
    exporter.apply_depsgraph_updates = lambda *a, **k: 'dispatched'
    return exporter


def _engine_methods():
    return {
        "setup_viewport_camera": lambda r, c, w, h: None,
        "wavelength_range_from_settings": lambda s: (400.0, 700.0),
        "effective_integrator_name": lambda s: "path",
        "viewport_target_samples": lambda s: 12,
        "viewport_chunk_samples": lambda s, cur: min(4, max(0, 12 - int(cur))),
        "resolve_settings": lambda scene, rep: s_settings(),
        "update_viewport_texture": lambda b, w, h: None,
    }


def s_settings():
    return types.SimpleNamespace(
        max_bounces=8, viewport_display_pass="combined",
        diffuse_bounces=4, glossy_bounces=4, transmission_bounces=4,
        volume_bounces=4, transparent_bounces=4,
        preview_samples=12, viewport_chunk_spp=4)


def _args(exp, exporter, depsgraph_box, region):
    context = types.SimpleNamespace(region=region)
    em = _engine_methods()
    redraw = lambda: None
    chash = lambda c, r: 1000.0  # stable camera (no camera-driven request)
    return (context, depsgraph_box, (lambda *a, **k: None),
            (lambda s: "path"), (lambda *a, **k: None), chash, chash,
            redraw, em)


def test_spurious_view_update_during_settle_does_not_starve_terminals():
    exp = _load_exporter_module()
    exporter = _build_exporter(exp)

    region = types.SimpleNamespace(width=64, height=64)
    settings = s_settings()
    scene = types.SimpleNamespace(custom_raytracer=settings, world=None)

    # A genuine material edit (a real, image-changing update) then a settle span of
    # SPURIOUS view_updates whose depsgraph carries an empty `updates` list — the
    # Blender re-eval that the worker's own tag_redraw triggers.
    real_dg = types.SimpleNamespace(
        scene=scene, updates=[_DepsgraphUpdate(_Material("m"), shading=True)])
    spurious_dg = types.SimpleNamespace(scene=scene, updates=[])

    args_real = _args(exp, exporter, real_dg, region)
    args_spurious = _args(exp, exporter, spurious_dg, region)

    # Genuine edit: submits the first generation.
    exporter._worker_view_update(*args_real)
    worker = exporter._worker
    try:
        # Settle span: ~2 s of spurious view_updates + view_draws at ~300 Hz — a
        # spurious view_update fires several times per render() chunk, so the
        # pre-fix unconditional request() cancels every generation mid-flight.
        t_end = time.perf_counter() + 2.0
        while time.perf_counter() < t_end:
            exporter._worker_view_update(*args_spurious)
            exporter._worker_view_draw(*args_spurious)
            time.sleep(1 / 300.0)
        time.sleep(0.3)
        # A spurious view_update must NOT cancel the settling render: at least one
        # generation reaches its uncancelled terminal in the idle span.
        assert worker.completed_generations >= 1, (
            f"no generation completed in the settle span "
            f"(completed={worker.completed_generations}) — a spurious view_update "
            f"cancelled the in-flight render (present-rate=0 regression)")
    finally:
        worker.stop(timeout=2.0)


def test_depsgraph_has_image_changing_update_classification():
    """The cache-free peek: an empty `updates` list is inert; a real material edit
    is image-changing; an absent `updates` attr is treated conservatively as a real
    edit (first sync / fallback). A selection-only recognised Object is covered by
    the `_classify_depsgraph_domains` suite in test_pkg266_dirty_domain_commit."""
    exp = _load_exporter_module()
    exporter = _build_exporter(exp)

    empty = types.SimpleNamespace(updates=[])
    assert exporter._depsgraph_has_image_changing_update(empty) is False

    real = types.SimpleNamespace(
        updates=[_DepsgraphUpdate(_Material("m"), shading=True)])
    assert exporter._depsgraph_has_image_changing_update(real) is True

    unknown = types.SimpleNamespace(updates=None)
    assert exporter._depsgraph_has_image_changing_update(unknown) is True

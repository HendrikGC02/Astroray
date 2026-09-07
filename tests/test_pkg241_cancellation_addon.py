"""pkg241 Phase 1b — addon-level cooperative-cancellation wiring (pure Python).

Same mock harness as test_pkg241_present_first_budget.py (real addon engine,
stubbed bpy, RecordingRenderer). These tests assert the viewport now:

  1. passes a REAL bool-returning progress callback to renderer.render (not None),
     whose value tracks _viewport_cancel_requested;
  2. exposes _request_viewport_cancel / _consume_viewport_cancel that drop a
     cancelled chunk's partial accumulation (no mixed accumulation);
  3. requests a cancel from view_draw on a substantive camera or settings change.

The native cancellation channel itself is covered by test_pkg241_cancellation.py.
"""

import numpy as np

# Reuse the loader + stubs from the Phase 1a test module (same directory).
from test_pkg241_present_first_budget import (
    IDENTITY,
    _draw,
    _make_context,
    _RecordingRenderer,
    _update,
    _wire,
)


class _CallbackRecordingRenderer(_RecordingRenderer):
    """RecordingRenderer that also captures the progress callback render() got."""

    def __init__(self):
        super().__init__()
        self.last_progress_cb = "unset"

    def render(self, *a, **k):
        # render_viewport_frame calls render(samples, depth, progress_cb, ...)
        self.last_progress_cb = a[2] if len(a) > 2 else k.get("progress_callback")
        return super().render(*a, **k)


def test_viewport_render_uses_bool_cancel_callback(monkeypatch):
    """view_update drives renderer.render with a callable progress callback (not
    None) that returns True normally and False once a cancel is requested."""
    _addon, engine, _clock, _dims = _wire(monkeypatch,
                                         renderer_cls=_CallbackRecordingRenderer)
    exporter = engine._get_exporter()

    ctx = _make_context(IDENTITY)
    _update(engine, ctx)

    renderer = exporter._get_viewport_renderer()
    cb = renderer.last_progress_cb
    assert cb is not None, "viewport must pass a real callback, not None"
    assert callable(cb)
    assert cb(0.5) is True, "callback continues by default"

    exporter._viewport_cancel_requested = True
    assert cb(0.5) is False, "callback cancels when a cancel is requested"


def test_request_and_consume_cancel_resets_accumulation(monkeypatch):
    """_request_viewport_cancel sets the flag; _consume_viewport_cancel drops the
    partial accumulation and clears the flag (no mixed accumulation)."""
    _addon, engine, _clock, _dims = _wire(monkeypatch)
    exporter = engine._get_exporter()

    # Simulate a partially-accumulated in-flight chunk.
    exporter._viewport_accum_pixels = np.ones((2, 2, 3), dtype=np.float32)
    exporter._viewport_current_spp = 8
    exporter._viewport_accum_key = "old-key"

    assert exporter._viewport_cancel_requested is False
    exporter._request_viewport_cancel()
    assert exporter._viewport_cancel_requested is True

    consumed = exporter._consume_viewport_cancel()
    assert consumed is True
    assert exporter._viewport_cancel_requested is False
    # Partial accumulation dropped so it cannot blend with the new state.
    assert exporter._viewport_accum_pixels is None
    assert exporter._viewport_current_spp == 0
    assert exporter._viewport_accum_key is None

    # Idempotent: no cancel pending -> no-op, leaves state alone.
    exporter._viewport_current_spp = 3
    assert exporter._consume_viewport_cancel() is False
    assert exporter._viewport_current_spp == 3


def test_render_viewport_frame_consumes_pending_cancel(monkeypatch):
    """A cancel requested before the next chunk is consumed by
    render_viewport_frame: the fresh chunk is NOT blended onto the pre-cancel
    accumulation (the returned buffer equals the new render, not a mix)."""
    _addon, engine, _clock, _dims = _wire(monkeypatch)
    exporter = engine._get_exporter()

    ctx = _make_context(IDENTITY)
    # First render establishes an accumulation buffer at the current key.
    _update(engine, ctx)
    first_accum = np.array(exporter._viewport_accum_pixels, copy=True)
    assert exporter._viewport_current_spp > 0

    # A cancel is requested (e.g. a superseding edit), then another view_update
    # renders a fresh chunk. The cancelled partial must be dropped, so the new
    # accumulation is a clean copy of the fresh chunk, never a blend with the old.
    exporter._request_viewport_cancel()
    _update(engine, ctx)
    after = exporter._viewport_accum_pixels

    assert not exporter._viewport_cancel_requested
    # The RecordingRenderer returns a distinct constant per call, so a reset
    # accumulation is uniform (single fresh chunk), not the average of two chunks.
    assert np.allclose(after, after.flat[0]), "accumulation should be a fresh chunk"
    assert not np.allclose(after, first_accum), "must not reuse the cancelled chunk"


def test_view_draw_requests_cancel_on_settings_change(monkeypatch):
    """A settings change between draws requests a cancel so the stale chunk's
    accumulation is dropped before the new-settings render."""
    _addon, engine, _clock, _dims = _wire(monkeypatch)
    exporter = engine._get_exporter()

    calls = {"n": 0}
    orig = exporter._request_viewport_cancel

    def _spy():
        calls["n"] += 1
        return orig()
    monkeypatch.setattr(exporter, "_request_viewport_cancel", _spy)

    ctx = _make_context(IDENTITY)
    _update(engine, ctx)
    _draw(engine, ctx)  # present-first / settle

    # Change a setting so the render key flips -> settings_changed in view_draw.
    ctx.scene.custom_raytracer.max_bounces = 9
    _draw(engine, ctx)

    assert calls["n"] >= 1, "a settings change should request a viewport cancel"

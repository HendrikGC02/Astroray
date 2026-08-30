#!/usr/bin/env python
"""pkg131 — GPU wavefront zero-knob adaptive sampling: wiring + convergence.

The GPU adaptive round loop (cuda_wavefront_render) is opt-in and rides on the
pkg224 progressive sampler: it activates only when BOTH set_use_progressive_sampler
and set_adaptive_sampling are on. Default (progressive off) is the byte-identical
flat work pool. Each active round samples the compacted still-unconverged pixel
list; the host convergence check retires pixels below the auto threshold and the
final image divides each pixel by its own sample count.

Gates:
  * test_adaptive_inactive_without_progressive — adaptive ON but progressive OFF
    renders the same as the untouched default (adaptive is gated off, byte-identical
    flat pool within GPU float-atomic tolerance).
  * test_adaptive_unbiased — adaptive ON (+progressive) matches progressive-ON /
    adaptive-OFF in the mean at matched budget: early stopping does not bias the
    image.
  * test_adaptive_changes_and_sane — adaptive ON differs from adaptive-OFF (proof
    the round loop engages) yet stays a sane, non-black render of the same scene.

GPU-gated: skips when no CUDA device (CI has none) — this is an RTX-box leg.
"""

import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


def _build_scene(renderer):
    renderer.set_background_color([0.8, 0.8, 0.8])
    mat = renderer.create_material("lambertian", [0.6, 0.6, 0.6], {})
    A, B = [-1, -1, 0], [1, -1, 0]
    C, D = [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    renderer.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]},
                                 n, n, n)
    renderer.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]},
                                 n, n, n)
    setup_camera(renderer, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=48, height=48)


def _render(adaptive, progressive, samples, seed=1234):
    r = create_renderer()
    if not _has_cuda_gpu(r):
        pytest.skip("No CUDA GPU — pkg131 GPU adaptive gate runs on the RTX box.")
    r.set_use_gpu(True)
    r.set_use_progressive_sampler(progressive)
    r.set_adaptive_sampling(adaptive)
    _build_scene(r)
    try:
        r.set_seed(seed)
    except AttributeError:
        pass
    return render_image(r, samples=samples, max_depth=3, apply_gamma=False)


def test_adaptive_inactive_without_progressive():
    """Adaptive ON but progressive OFF == the untouched flat pool (adaptive gated
    off). Compared within GPU float-atomic tolerance (~1 ULP run-to-run)."""
    adaptive_no_prog = _render(adaptive=True, progressive=False, samples=48, seed=7)
    # Untouched default: adaptive off, progressive off.
    baseline = _render(adaptive=False, progressive=False, samples=48, seed=7)
    assert np.allclose(adaptive_no_prog, baseline, atol=1e-4), (
        "adaptive activated without the progressive sampler — it must be gated off "
        f"(max|diff|={np.abs(adaptive_no_prog - baseline).max():.2e})")


def test_adaptive_unbiased():
    """Adaptive ON (+progressive) is unbiased vs progressive-ON / adaptive-OFF at a
    high budget: early stopping trades bounded noise for samples, not accuracy."""
    on = _render(adaptive=True, progressive=True, samples=256)
    off = _render(adaptive=False, progressive=True, samples=256)
    assert on.shape == off.shape
    assert 0.05 < on.mean(), "adaptive render came out black"
    assert abs(float(on.mean()) - float(off.mean())) < 0.01, (
        "adaptive early-out biased the image mean")


def test_adaptive_changes_and_sane():
    """Adaptive ON must differ from OFF (the round loop actually engaged) but stay a
    sane render of the same scene."""
    on = _render(adaptive=True, progressive=True, samples=128)
    off = _render(adaptive=False, progressive=True, samples=128)
    assert not np.array_equal(on, off), (
        "adaptive produced a byte-identical image to the uniform render — the round "
        "loop / compaction never engaged")
    assert 0.05 < on.mean() and 0.05 < off.mean()

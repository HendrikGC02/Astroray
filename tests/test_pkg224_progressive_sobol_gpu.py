#!/usr/bin/env python
"""pkg224 — GPU progressive (hash-Owen Sobol') sampler: wiring + convergence.

The sampler is opt-in via renderer.set_use_progressive_sampler(True); it is
published into the __constant__ c_wfSamplerMode and consumed by
WavefrontRNG::Uniform() on the device. With it OFF (the default) the GPU render
is unchanged (the byte-identical-default codegen is separately pinned by the
cuobjdump register probe in the pkg224 PR; here we pin the runtime determinism).

Gates:
  * test_default_off_matches_untouched — the sampler explicitly OFF renders the
    same (within GPU float-atomic tolerance) as never touching the flag: the
    unchanged PCG32 path. (Bitwise codegen identity of the OFF path is pinned
    separately by the cuobjdump register probe in the PR; the GPU renderer's
    per-pixel accumulation is ~1 ULP non-deterministic run-to-run regardless.)
  * test_progressive_changes_output — ON vs OFF differ, proving the flag reaches
    the device draw sites.
  * test_progressive_lowers_noise — on a flat, uniformly-lit region at matched
    low spp, the progressive render has lower per-pixel variance than the PCG32
    white-noise render (the convergence benefit that unblocks pkg131 adaptive
    sampling). Spatial variance in a flat patch is reference-free, so it carries
    no same-sampler correlation bias.

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
    """A diffuse quad facing the camera under a bright uniform world — a smooth
    integrand where low-discrepancy sampling converges visibly faster."""
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


def _render(progressive, samples, seed=1234):
    r = create_renderer()
    if not _has_cuda_gpu(r):
        pytest.skip("No CUDA GPU — pkg224 progressive-sampler gate runs on the RTX box.")
    r.set_use_gpu(True)
    r.set_use_progressive_sampler(progressive)
    _build_scene(r)
    try:
        r.set_seed(seed)
    except AttributeError:
        pass
    return render_image(r, samples=samples, max_depth=3, apply_gamma=False)


def test_default_off_matches_untouched():
    """Explicit sampler OFF == the default (flag never set): the unchanged PCG32
    path. Compared within GPU float-atomic tolerance (the accumulation is ~1 ULP
    non-deterministic run-to-run even with no pkg224 code involved)."""
    off = _render(progressive=False, samples=48, seed=7)
    # Untouched default: same scene/seed, never calling set_use_progressive_sampler.
    r = create_renderer()
    if not _has_cuda_gpu(r):
        pytest.skip("No CUDA GPU — pkg224 progressive-sampler gate runs on the RTX box.")
    r.set_use_gpu(True)
    _build_scene(r)
    r.set_seed(7)
    default = render_image(r, samples=48, max_depth=3, apply_gamma=False)
    assert np.allclose(off, default, atol=1e-4), (
        "explicit progressive=False diverges from the untouched default — the OFF "
        "path is not the unchanged PCG32 behaviour "
        f"(max|diff|={np.abs(off - default).max():.2e})")


def test_progressive_changes_output():
    """ON vs OFF must differ — proof the flag reaches the device draw sites."""
    off = _render(progressive=False, samples=32)
    on = _render(progressive=True, samples=32)
    assert off.shape == on.shape
    assert not np.array_equal(off, on), (
        "progressive ON produced a byte-identical image to OFF — the flag is not "
        "reaching WavefrontRNG::Uniform() on the device")
    # Both must be sane, non-black renders of the same scene.
    assert 0.05 < off.mean() and 0.05 < on.mean()
    # Same scene, same converged expectation — means stay close.
    assert abs(off.mean() - on.mean()) < 0.05


def _flat_patch_noise(img):
    """Per-pixel spatial std in the central 16x16 patch (a flat, uniformly-lit
    region → its variation is Monte-Carlo noise, not signal)."""
    h, w = img.shape[:2]
    cy, cx = h // 2, w // 2
    patch = img[cy - 8:cy + 8, cx - 8:cx + 8]
    return float(patch.reshape(-1, patch.shape[-1]).std(axis=0).mean())


def test_progressive_lowers_noise():
    """At matched low spp the progressive render has lower flat-region noise than
    the PCG32 white-noise render (Sobol'-class convergence)."""
    n = 16
    noise_prog = _flat_patch_noise(_render(progressive=True, samples=n))
    noise_white = _flat_patch_noise(_render(progressive=False, samples=n))
    assert noise_prog < noise_white, (
        f"progressive flat-region noise {noise_prog:.4e} not below white-noise "
        f"{noise_white:.4e} at {n} spp — no convergence benefit observed")

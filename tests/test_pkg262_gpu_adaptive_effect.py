#!/usr/bin/env python
"""pkg262 — GPU adaptive-sampling toggle output-effect gate (issue #759).

Issue #759: `gpu_wavefront_snapshot.cu`'s `adaptiveOn` gate additionally
requires `renderer.getUseProgressiveSampler()` on top of
`renderer.getUseAdaptiveSampling()` (pkg131's GPU leg needs the pkg224
progressive sampler's prefix property to stop pixels early without harming
convergence). The Blender addon (`blender_addon/__init__.py` `render()`,
`blender_addon/exporter.py`) calls ONLY `renderer.set_adaptive_sampling(...)`
— there is no `set_use_progressive_sampler` call site anywhere in
`blender_addon/`. Result: turning the native "Adaptive Sampling" toggle on
changes nothing on a GPU render; the flat uniform work pool runs regardless.

pkg262's A/B (.astroray_plan/docs/pkg262-default-flip-ab-2026-09.md) tried the
ENGINE-DEFAULT fix first (`include/raytracer.h` `useProgressiveSampler = true`,
fork (a)) and measured a real regression: the wavefront perf ceiling and the
CPU/GPU snapshot-parity gate both broke, because flipping the default makes
EVERY GPU render pay the Sobol'+Owen-scramble cost and diverge from the CPU's
PCG32 reference, not just adaptive ones. The fix instead lives in the addon
(fork (b), the spec's documented fallback): `blender_addon/__init__.py`
`render()` and `blender_addon/exporter.py` `sync_viewport_scene()` now call
`renderer.set_use_progressive_sampler(active_device == "gpu" and
settings.use_adaptive_sampling)` right after the device is resolved. The
engine default stays `false`.

`_render_addon_style` below therefore mirrors that exact addon expression
(not just `set_adaptive_sampling` alone) so this test exercises the real fix
rather than a fork the code no longer takes.

Gates:
  * test_adaptive_toggle_changes_gpu_output_759 — PRIMARY gate. At equal max
    spp, addon-style ON vs OFF must produce different images. Today (main,
    #759) they are byte-identical, because the toggle is gated dead; the fix
    makes the round loop actually engage. This is the literal RED-on-main /
    GREEN-after-fix reproduction for #759.
  * test_adaptive_flat_region_noise_bounded — secondary sanity: reads
    "flat-region variance falls" (spec acceptance criterion) as "stays low /
    converges", not as a directional ON-vs-OFF comparison. Statistically ON
    can never have LOWER flat-region noise than OFF at equal max spp (ON uses
    <= samples in an already-converged region — stopping early cannot reduce
    an estimator's variance below the same estimator run longer). What proves
    the round loop behaves correctly instead is that its OWN flat-region noise
    stays bounded / low (it does not leave the easy region under-converged or
    numerically corrupted after early retirement) and its mean stays close to
    a well-converged high-spp reference.

Skips without a CUDA device — this is an RTX-box gate (`ci_has_no_gpu_runtime_
blindspot`: CI has no GPU, this never runs there).
"""

import astroray
import numpy as np
import pytest
from base_helpers import create_renderer, render_image, setup_camera


def _has_cuda_gpu(renderer):
    return bool(astroray.__features__.get("cuda", False)) and \
        bool(getattr(renderer, "gpu_available", False))


def _build_scene(renderer):
    """A flat, uniformly-lit diffuse quad — matches the pkg131/pkg224 GPU test
    scenes so the central patch is a reference-free flat-noise proxy."""
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


def _render_addon_style(adaptive, samples, seed=1234):
    """Render exactly the way `blender_addon/__init__.py::render()` (and
    `exporter.py::sync_viewport_scene()`) do post-pkg262: `set_adaptive_sampling`
    plus `set_use_progressive_sampler(active_device == "gpu" and adaptive)` —
    the addon-side fork (b) enable, not a bare `set_adaptive_sampling` call."""
    r = create_renderer()
    if not _has_cuda_gpu(r):
        pytest.skip("No CUDA GPU — pkg262 GPU adaptive-effect gate runs on the RTX box.")
    r.set_use_gpu(True)
    r.set_adaptive_sampling(adaptive)
    if hasattr(r, "set_use_progressive_sampler"):
        r.set_use_progressive_sampler(bool(adaptive))  # active_device == "gpu" always here
    _build_scene(r)
    try:
        r.set_seed(seed)
    except AttributeError:
        pass
    return render_image(r, samples=samples, max_depth=3, apply_gamma=False)


def _flat_patch(img):
    h, w = img.shape[:2]
    cy, cx = h // 2, w // 2
    return img[cy - 8:cy + 8, cx - 8:cx + 8]


def _flat_patch_noise(img):
    """Per-pixel spatial std in the central 16x16 patch (a flat, uniformly-lit
    region -> its variation is Monte-Carlo noise, not signal). Mirrors
    `tests/test_pkg224_progressive_sobol_gpu.py::_flat_patch_noise`."""
    patch = _flat_patch(img)
    return float(patch.reshape(-1, patch.shape[-1]).std(axis=0).mean())


def test_adaptive_toggle_changes_gpu_output_759():
    """The addon-realistic invocation of the native Adaptive Sampling toggle
    must change the GPU output at equal max spp (#759: today it does not).

    NOTE on tolerance: two GPU wavefront renders of the IDENTICAL config are
    never bit-identical — atomicAdd accumulation order is nondeterministic
    across launches, giving a measured noise floor of max|diff| ~5e-7 /
    mean|diff| ~7e-10 for a rerun of the same code path (48x48, 128 spp,
    RTX 5070 Ti, 2026-09-09). A bare `np.array_equal` is USELESS here: it is
    False for every pair of GPU renders regardless of whether the adaptive
    round loop engaged, so it cannot distinguish the real #759 bug from
    ordinary float-atomic jitter. The threshold below (1e-3) is ~2000x that
    empirical floor: only a real change of code path (the round loop actually
    running and dividing by a different per-pixel sample count) can cross it.
    """
    on = _render_addon_style(adaptive=True, samples=128, seed=42)
    off = _render_addon_style(adaptive=False, samples=128, seed=42)
    assert on.shape == off.shape
    assert 0.05 < on.mean() and 0.05 < off.mean(), "render came out black"
    max_diff = float(np.abs(on - off).max())
    assert max_diff > 1e-3, (
        "GPU render is unchanged (within GPU atomic-noise floor) whether the "
        "native Adaptive Sampling toggle is on or off (issue #759) — the "
        "addon never enables the pkg224 progressive sampler the GPU round "
        "loop requires, so adaptiveOn in gpu_wavefront_snapshot.cu stays "
        f"false and the flat work pool runs regardless (max|diff|={max_diff:.2e}, "
        "empirical same-config noise floor is ~5e-7)")


def test_adaptive_flat_region_noise_bounded():
    """Once the round loop actually engages (post-fix), the flat/easy region
    must still converge to a low, bounded noise level and an unbiased mean
    relative to a well-converged high-spp reference — proving early retirement
    did not leave the region under-sampled or corrupt the estimate."""
    ref = _render_addon_style(adaptive=False, samples=512, seed=7)
    on = _render_addon_style(adaptive=True, samples=128, seed=7)
    noise_on = _flat_patch_noise(on)
    assert noise_on < 0.05, (
        f"flat-region noise {noise_on:.4e} did not fall to a converged level "
        "under the addon-realistic adaptive-ON path")
    residual = float(np.abs(_flat_patch(on) - _flat_patch(ref)).mean())
    assert residual < 0.05, (
        f"flat-region mean residual vs a 512-spp reference is {residual:.4e} "
        "— adaptive-ON retired the flat region before it actually converged")

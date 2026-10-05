#!/usr/bin/env python
"""pkg224 — GPU progressive (hash-Owen Sobol') sampler: wiring + convergence.

The sampler is opt-in via renderer.set_use_progressive_sampler(True); it is
published into the __constant__ c_wfSamplerMode and consumed by
WavefrontRNG::Uniform() on the device. With it OFF (the default) the GPU render
is unchanged (the byte-identical-default codegen is separately pinned by the
cuobjdump register probe in the pkg224 PR; here we pin the runtime determinism).

pkg262 (2026-09) tried flipping the engine default to true (issue #759 — GPU
adaptive sampling requires this sampler, and the addon never enabled it) and
MEASURED A REGRESSION: the wavefront perf ceiling and the CPU/GPU
snapshot-parity gate both broke because every GPU render started paying the
Sobol'+Owen-scramble cost and diverging from the CPU's PCG32 reference (see
.astroray_plan/docs/pkg262-default-flip-ab-2026-09.md). The fix instead lives
in blender_addon/__init__.py + exporter.py: the addon enables this flag only
when GPU adaptive sampling is actually requested. The engine default stays
false, so this file's original "untouched default == explicit off" contract
is unchanged.

Gates:
  * test_default_off_matches_untouched — the sampler explicitly OFF renders the
    same (within GPU float-atomic tolerance) as never touching the flag: the
    unchanged PCG32 path. (Bitwise codegen identity of the OFF path is pinned
    separately by the cuobjdump register probe in the PR; the GPU renderer's
    per-pixel accumulation is ~1 ULP non-deterministic run-to-run regardless.)
  * test_progressive_changes_output — ON vs OFF differ well beyond atomic
    jitter, proving the flag reaches the device draw sites.
  * test_progressive_lowers_noise — at matched low spp, the progressive render
    has lower RMSE against a converged reference than the PCG32 white-noise
    render (the convergence benefit that unblocks pkg131 adaptive sampling).
    #1015: the scene puts its variance in the light/BSDF dimensions.

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
    """A diffuse quad filling the frame, lit by an off-frame sphere light over a
    black world. The variance sits in the light/BSDF dimensions (dims >= 4) that
    the sampler toggle drives. #1015: the old uniform-world scene had none there
    (only the camera group, always Sobol since pkg305), so ON/OFF tied to 1 ulp."""
    renderer.set_background_color([0.0, 0.0, 0.0])
    mat = renderer.create_material("lambertian", [0.6, 0.6, 0.6], {})
    A, B = [-4, -4, 0], [4, -4, 0]
    C, D = [4, 4, 0], [-4, 4, 0]
    n = [0, 0, 1]
    renderer.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]},
                                 n, n, n)
    renderer.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]},
                                 n, n, n)
    light = renderer.create_material("light", [1.0, 1.0, 1.0], {"intensity": 40.0})
    renderer.add_sphere([1.5, 0.9, 0.6], 0.4, light)
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
    # Well above the ~1e-6 float-atomic jitter (measured 0.78 max on this scene).
    assert np.abs(off - on).max() > 1e-2, (
        "progressive ON matches OFF to within atomic jitter — the flag is not "
        "reaching WavefrontRNG::Uniform() on the device")
    # Both must be sane, non-black renders of the same scene.
    assert 0.05 < off.mean() and 0.05 < on.mean()
    # Same scene, same converged expectation — means stay close.
    assert abs(off.mean() - on.mean()) < 0.05


def test_progressive_lowers_noise():
    """At matched low spp the progressive render is closer to a converged
    reference than the PCG32 white-noise render (Sobol'-class convergence).
    RMSE vs reference, averaged over seeds; measured ratio 0.63 at 16 spp."""
    n = 16
    ref = _render(progressive=False, samples=1024, seed=99)
    seeds = (1, 2, 3, 4)
    rmse = lambda img: float(np.sqrt(((img - ref) ** 2).mean()))  # noqa: E731
    err_prog = np.mean([rmse(_render(progressive=True, samples=n, seed=s)) for s in seeds])
    err_white = np.mean([rmse(_render(progressive=False, samples=n, seed=s)) for s in seeds])
    assert err_prog < 0.85 * err_white, (
        f"progressive RMSE {err_prog:.4e} not below 0.85x white-noise "
        f"{err_white:.4e} at {n} spp — no convergence benefit observed")

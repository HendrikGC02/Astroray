"""pkg191 — GPU viewport progressive refinement regression.

Root cause: the Blender viewport accumulator is a Python running-mean of
independent per-chunk renders (blender_addon/exporter.py:585-597). It only
denoises if each chunk is a DISTINCT noise realization. The viewport renderer
runs at the default renderSeed==0. The CPU render loop special-cases
renderSeed==0 -> a fresh std::random_device seed PER CALL
(include/raytracer.h:3028-3030), so chunks are independent and the mean
converges. The GPU dispatch previously passed renderer.getSeed() (==0) verbatim
to cuda_wavefront_render, and the wavefront RNG is
WavefrontRNG(pixel, sample_idx, seed) (src/gpu/wavefront/stage_init.cu:189) ->
every seed-0 chunk reproduced IDENTICAL noise, so the running-mean averaged
duplicates and the viewport stayed stuck at the 1-sample noise. The fix
(module/blender_module.cpp) makes the GPU dispatch honour the same documented
"0 == non-deterministic" contract (include/raytracer.h:2102) as the CPU loop.

These tests assert the seed contract at the renderer level (the actual bug) plus
an end-to-end denoise proof on GPU. GPU-gated; CPU controls guard no-regression.
"""
import numpy as np
import pytest
from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")

_GPU = AVAILABLE and astroray.__features__.get("cuda", False)
gpu_only = pytest.mark.skipif(not _GPU, reason="needs CUDA build on the RTX box")


def _scene(use_gpu):
    r = astroray.Renderer()
    r.setup_camera(look_from=[0, 0, 5], look_at=[0, 0, 0], vup=[0, 1, 0],
                   vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.0,
                   width=96, height=96)
    r.set_background_color([0.05, 0.05, 0.08])
    r.set_integrator("path_tracer")
    mid = r.create_material("lambertian", [0.8, 0.3, 0.3], {})
    r.add_sphere([0, 0, 0], 1.2, mid)
    r.add_point_light(position=[3, 3, 3],
                      emission={'mode': 'rgb', 'color': [1.0, 1.0, 1.0]},
                      intensity=60.0)
    r.set_use_gpu(use_gpu)
    return r


def _render(r, samples=1):
    return np.array(r.render(samples, 4, None, False), dtype=np.float32)  # linear


# ---------------------------------------------------------------------------
# The core seed contract: seed 0 == non-deterministic (independent chunks).
# ---------------------------------------------------------------------------

@gpu_only
def test_gpu_seed0_chunks_are_independent():
    """Two seed-0 (default) GPU renders of the same scene must differ — this is
    what lets the viewport running-mean denoise. Regression for the stuck-at-
    1-sample bug."""
    r = _scene(use_gpu=True)
    a, b = _render(r), _render(r)
    max_diff = float(np.max(np.abs(a - b)))
    assert np.isfinite(a).all() and np.isfinite(b).all()
    assert max_diff > 0.0, (
        "GPU seed-0 chunks are byte-identical -> viewport cannot denoise "
        f"(max_abs_diff={max_diff})")


@gpu_only
def test_gpu_nonzero_seed_is_deterministic():
    """A pinned (non-zero) seed must stay reproducible on GPU — final-render and
    parity tests rely on this."""
    r = _scene(use_gpu=True)
    r.set_seed(1234567)
    a = _render(r)
    r.set_seed(1234567)
    b = _render(r)
    assert float(np.max(np.abs(a - b))) == 0.0, "pinned GPU seed must be deterministic"


def test_cpu_seed0_chunks_are_independent():
    """CPU control: seed 0 already yields independent chunks (guards that the
    documented contract still holds after the fix)."""
    r = _scene(use_gpu=False)
    a, b = _render(r), _render(r)
    assert float(np.max(np.abs(a - b))) > 0.0


@gpu_only
def test_gpu_progressive_accumulator_denoises():
    """End-to-end: emulate exporter.py's running-mean over 1-spp GPU chunks and
    prove the accumulated image converges toward a high-spp reference (MSE drops
    monotonically). Metrics-on-garbage guard: also assert the reference is a
    non-trivial image."""
    ref_r = _scene(use_gpu=True)
    ref_r.set_seed(987654321)  # pinned reference; independent of the chunk stream
    ref = _render(ref_r, samples=256)
    assert float(np.var(ref)) > 1e-5, "reference image is flat; scene has no signal"

    r = _scene(use_gpu=True)  # default seed 0 -> independent chunks (post-fix)
    accum = None
    cur = 0
    mse = {}
    for i in range(1, 65):
        chunk = _render(r, samples=1)
        if accum is None:
            accum, cur = chunk.copy(), 1
        else:
            new = cur + 1
            accum = (accum * cur + chunk) / float(new)
            cur = new
        if i in (1, 16, 64):
            mse[i] = float(np.mean((accum - ref) ** 2))
    print(f"\n[pkg191 GPU denoise] MSE-to-256spp @ {{1,16,64}} = "
          f"{{1: {mse[1]:.6e}, 16: {mse[16]:.6e}, 64: {mse[64]:.6e}}}")
    assert mse[16] < mse[1], f"noise did not drop 1->16 spp ({mse[1]} -> {mse[16]})"
    assert mse[64] < mse[16], f"noise did not drop 16->64 spp ({mse[16]} -> {mse[64]})"

"""pkg131 — CPU render-level: zero-knob adaptive sampling wiring + quality.

The CPU per-pixel sample loop (Renderer::render, include/raytracer.h) now stops
each pixel via the cited Cycles Dammertz metric + auto-threshold
(include/astroray/sampling/adaptive_sampling.h) instead of the old hand-rolled
coefficient-of-variation early-out. These render-level gates pin that:

  * at a LOW sample budget the auto-derived minimum-sample floor is >= the budget,
    so no pixel can converge early — adaptive ON is then bit-for-bit identical to
    adaptive OFF (the early-out is a strict no-op, never perturbs a render); and
  * at a HIGH budget the adaptive image is unbiased (means track the fully-sampled
    render) and its per-pixel deviation stays bounded by the stopping threshold —
    early stopping trades a little bounded noise for samples, it does not corrupt
    the image.

CPU-only (set_use_gpu False); the sampler is a CPU-loop feature.
"""

import numpy as np
from base_helpers import create_renderer, render_image, setup_camera


def _smooth_lit_quad(r):
    """A diffuse quad under a bright uniform world — smooth integrand, mild MC
    noise that an adaptive stopper handles well."""
    r.set_use_gpu(False)
    r.set_background_color([0.8, 0.8, 0.8])
    mat = r.create_material("lambertian", [0.6, 0.6, 0.6], {})
    A, B, C, D = [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]
    n = [0, 0, 1]
    r.add_triangle_layers(A, B, C, mat, {"UVMap": [[0, 0], [1, 0], [1, 1]]}, n, n, n)
    r.add_triangle_layers(A, C, D, mat, {"UVMap": [[0, 0], [1, 1], [0, 1]]}, n, n, n)
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vup=[0, 1, 0],
                 vfov=45, width=32, height=32)


def _render(adaptive, samples, seed=1234):
    r = create_renderer()
    _smooth_lit_quad(r)
    r.set_seed(seed)
    r.set_adaptive_sampling(adaptive)
    return render_image(r, samples=samples, max_depth=3, apply_gamma=False)


def test_adaptive_lowbudget_is_bit_identical_noop():
    """At budget 16 the auto min-sample floor clamps to the budget, so the
    convergence check never fires and adaptive ON == OFF bit-for-bit."""
    on = _render(adaptive=True, samples=16)
    off = _render(adaptive=False, samples=16)
    assert np.array_equal(on, off), (
        "adaptive perturbed a render whose budget is below the auto min-sample "
        f"floor (max|diff|={np.abs(on - off).max():.2e}) — the early-out must be a "
        "strict no-op there")


def test_adaptive_highbudget_unbiased_and_bounded():
    """At budget 256 adaptive stops easy pixels early. Same seed => the two runs
    share their sample prefix, so the difference is exactly the tail-noise the
    stopping threshold deemed acceptable: mean is unbiased, per-pixel deviation
    is small and bounded."""
    on = _render(adaptive=True, samples=256)
    off = _render(adaptive=False, samples=256)
    assert on.shape == off.shape
    assert 0.05 < on.mean(), "render came out black — scene/materials broke"
    # Unbiased: the early-out does not shift the image mean.
    assert abs(float(on.mean()) - float(off.mean())) < 0.01
    # Bounded: residual per-pixel noise stays within the threshold-level tolerance
    # (the auto threshold at budget 256 is ~0.02 brightness-relative).
    assert float(np.abs(on - off).mean()) < 0.05

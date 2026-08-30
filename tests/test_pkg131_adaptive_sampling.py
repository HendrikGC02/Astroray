"""pkg131 — zero-knob adaptive sampling core (Cycles adaptive_sampling.h).

The metric, the zero-knob auto-threshold derivation, the check cadence and the
mask dilation are pure __host__ __device__ free functions
(include/astroray/sampling/adaptive_sampling.h), so the host build exercised here
is byte-identical to the GPU device build. Pinning the host output validates the
device math directly.

Sources verified 2026-08-30 against Cycles main:
  * scene/integrator.cpp get_adaptive_sampling — auto-threshold + min-samples
  * integrator/adaptive_sampling.cpp need_filter — cadence
  * kernel/film/adaptive_sampling.h convergence_check + filter_x/_y — metric + dilation
Research note: .astroray_plan/docs/pkg131-adaptive-sampling-autothreshold-research.md
"""

import pytest

th = pytest.importorskip("astroray_test_helpers")


def test_auto_threshold_matches_cycles():
    """The zero-knob derivation reproduces Cycles' exact values (hand-verified)."""
    # budget=64: thr_pre=1/64=0.015625; min=ceil(16/0.015625**0.3)=56; thr*=5.
    thr, mn, step, cap, use = th.adaptive_derive(64, 0.0, 0)
    assert use and step == 16 and cap == 64
    assert mn == 56
    assert thr == pytest.approx(0.078125, abs=1e-6)
    # budget=256 -> thr 0.0195, min 85 ; budget=1024 -> thr 0.005 (clamped), min 128.
    thr256, mn256, *_ = th.adaptive_derive(256, 0.0, 0)
    assert mn256 == 85 and thr256 == pytest.approx(0.0195312, abs=1e-6)
    thr1k, mn1k, *_ = th.adaptive_derive(1024, 0.0, 0)
    assert mn1k == 128 and thr1k == pytest.approx(0.005, abs=1e-6)
    # The 0.001 threshold floor: a huge budget can't drive the threshold below 0.005.
    thr4k, mn4k, *_ = th.adaptive_derive(4096, 0.0, 0)
    assert thr4k == pytest.approx(0.005, abs=1e-6) and mn4k == 128


def test_threshold_and_floor_monotone():
    """Bigger sample budget => tighter threshold and a higher minimum-sample floor."""
    lo = th.adaptive_derive(64, 0.0, 0)
    hi = th.adaptive_derive(1024, 0.0, 0)
    assert hi[0] < lo[0]      # threshold
    assert hi[1] > lo[1]      # min_samples
    # Floor never exceeds the cap.
    for budget in (8, 32, 64, 256, 1024):
        _thr, mn, _step, cap, _use = th.adaptive_derive(budget, 0.0, 0)
        assert 4 <= mn <= cap


def test_manual_override():
    """Positive user threshold / min_samples bypass the auto derivation."""
    thr, mn, _step, _cap, _use = th.adaptive_derive(512, 0.01, 32)
    assert mn == 32
    assert thr == pytest.approx(0.05, abs=1e-6)  # 0.01 * 5 arbitrary factor


def test_cadence():
    """needConvergenceCheck: only past the floor, only on 16-aligned counts."""
    thr, mn, *_ = th.adaptive_derive(64, 0.0, 0)  # min_samples 56
    assert not th.adaptive_need_check(thr, mn, 16)   # below floor
    assert not th.adaptive_need_check(thr, mn, 56)   # at floor
    assert not th.adaptive_need_check(thr, mn, 63)   # not 16-aligned
    assert th.adaptive_need_check(thr, mn, 64)        # first real check
    assert not th.adaptive_need_check(thr, mn, 72)
    assert th.adaptive_need_check(thr, mn, 80)


def test_pixel_converged_metric():
    """Brightness-relative Dammertz metric: flat converges, noisy doesn't."""
    thr = 0.05
    # Noise-free: full mean (100/100=1.0) == half mean (50/50=1.0) -> error 0.
    assert th.adaptive_pixel_converged(100.0, 50.0, 100, thr, 1.0)
    # Noisy: half mean (10/50=0.2) far from full mean (1.0) -> big error.
    assert not th.adaptive_pixel_converged(100.0, 10.0, 100, thr, 1.0)
    # Dark pixel uses sqrt(intensity) normalization (brightness-relative): a small
    # absolute diff on a dim pixel is still relatively noisy.
    #   full mean 0.01, half mean 0.02 -> diff 0.01, intensity 0.01, norm 0.1,
    #   error = 0.01/(0.0001+0.1) = 0.0999 -> not converged at thr 0.05.
    assert not th.adaptive_pixel_converged(1.0, 1.0, 100, thr, 1.0)


def test_dilation_3x3_and_boundary():
    """A single unconverged pixel dilates to its 3x3 neighborhood; no wrap at edges."""
    W = H = 5
    mask = [1] * (W * H)
    mask[2 * W + 2] = 0  # center unconverged
    out = th.adaptive_dilate(mask, W, H)
    unconv = [i for i, v in enumerate(out) if v == 0]
    expected = {y * W + x for y in (1, 2, 3) for x in (1, 2, 3)}
    assert set(unconv) == expected

    # Corner pixel must not wrap to the opposite edge.
    mask = [1] * (W * H)
    mask[0] = 0
    out = th.adaptive_dilate(mask, W, H)
    assert out[0] == 0 and out[1] == 0 and out[W] == 0 and out[W + 1] == 0
    assert out[W - 1] == 1 and out[(H - 1) * W] == 1

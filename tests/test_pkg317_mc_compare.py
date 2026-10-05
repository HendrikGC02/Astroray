"""pkg317: synthetic fixtures for the gate-(c) noise-aware comparison candidates.

Independent noisy renders of the same image must pass; a 2 % ROI bias, a global
x0.98 and a missing feature must fail; the null false-positive rate must sit at
alpha +- 2 sigma.  CPU only, no Blender.
"""
from __future__ import annotations

import numpy as np
import pytest

from benchmarks.blender_parity import mc_compare as M

H, W, N = 64, 96, 8
ALPHA = 0.05
ROIS = {"roi": [0.25, 0.25, 0.75, 0.75]}


def base_image():
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    img = 0.3 + 0.2 * (x / W) + 0.1 * (y / H)
    img[20:44, 30:60] += 0.25  # a feature
    return np.repeat(img[..., None], 3, axis=-1) * np.array([1.0, 0.8, 0.6], np.float32)


def renders(rng, base=None, n=N, cv=0.05):
    """n independent MC-like renders: per-pixel Gamma noise with unit mean and the given cv."""
    base = base_image() if base is None else base
    k = 1.0 / cv ** 2
    return (base[None] * rng.gamma(k, 1.0 / k, size=(n, *base.shape))).astype(np.float32)


def test_identical_mean_noisy_pair_passes_welch():
    rng = np.random.default_rng(1)
    v = M.welch_verdict(renders(rng), renders(rng))
    assert v["pass"], v


def test_two_percent_roi_bias_fails_welch():
    rng = np.random.default_rng(2)
    x = renders(rng)
    y = M.inject_roi_shift(renders(rng), ROIS["roi"], 0.02)
    v = M.welch_verdict(x, y)
    assert not v["pass"] and v["n_reject_holm"] > 0
    assert 0.01 < v["max_rel_bias_rejected"] < 0.03


def test_global_gain_and_missing_feature_fail_welch():
    rng = np.random.default_rng(3)
    x = renders(rng)
    assert not M.welch_verdict(x, M.inject_gain(renders(rng), 0.98))["pass"]
    no_feature = base_image()
    no_feature[20:44, 30:60] -= 0.25
    assert not M.welch_verdict(x, renders(rng, no_feature))["pass"]


def test_margin_variant_ignores_one_percent_but_catches_three():
    rng = np.random.default_rng(4)
    x = renders(rng, cv=0.03)
    assert M.welch_verdict(x, M.inject_gain(renders(rng, cv=0.03), 0.995), delta_rel=0.02)["pass"]
    assert not M.welch_verdict(x, M.inject_gain(renders(rng, cv=0.03), 0.95), delta_rel=0.02)["pass"]


def test_null_false_positive_rate_holds_at_alpha():
    """200 independent null pairs: per-test rate ~ alpha, Holm per-pair FWER <= alpha + 2 sigma."""
    rng = np.random.default_rng(5)
    per_test, fwer = [], []
    for _ in range(200):
        r = M.welch_tiles(renders(rng, n=N), renders(rng, n=N))
        per_test.append((r["p"] < ALPHA).mean())
        fwer.append(M.holm(r["p"], ALPHA).any())
    n_tests = r["p"].size
    sigma_t = np.sqrt(ALPHA * (1 - ALPHA) / (200 * n_tests))
    assert abs(np.mean(per_test) - ALPHA) < 2 * sigma_t + 2e-3  # cv 0.05 tile means: near-normal
    sigma = np.sqrt(ALPHA * (1 - ALPHA) / 200)
    assert np.mean(fwer) <= ALPHA + 2 * sigma


def test_pvalues_are_uniform_under_null_and_not_under_bias():
    rng = np.random.default_rng(6)
    null = M.welch_verdict(renders(rng), renders(rng))
    biased = M.welch_verdict(renders(rng), M.inject_gain(renders(rng), 0.98))
    assert null["ks_p"] > 0.001 and biased["ks_p"] < 1e-6


def test_degenerate_deterministic_tiles_do_not_count():
    z = np.zeros((N, 16, 16, 3), np.float32)
    v = M.welch_verdict(z, z.copy())
    assert v["pass"] and v["n_tests"] == 0
    r = M.welch_tiles(z, z + 1.0)  # deterministic but unequal: p = 0 (not degenerate-equal)
    assert (r["p"] == 0).all()


def test_holm_and_bh_known_values():
    p = np.array([0.001, 0.02, 0.035, 0.5])
    assert M.holm(p, 0.05).tolist() == [True, False, False, False]  # 0.001<=.0125, 0.02>.0167
    assert M.benjamini_hochberg(p, 0.05).tolist() == [True, True, True, False]  # 0.035 <= .05*3/4


def test_ssim_noise_ceiling_passes_same_backend_and_catches_blur():
    rng = np.random.default_rng(7)
    x, y = renders(rng, cv=0.3), renders(rng, cv=0.3)
    assert M.ssim_gate_verdict(x, y, ROIS)["stat"] < M.SSIM_MIN  # the failure mode: noise-bound SSIM
    assert M.ssim_ceiling_verdict(x, y, ROIS)["pass"]
    assert not M.ssim_ceiling_verdict(x, M.inject_shift_px(y, 3), ROIS)["pass"]
    assert M.ssim_mean_verdict(x, y, ROIS)["stat"] > M.ssim_gate_verdict(x, y, ROIS)["stat"]


def test_roi_ratio_misses_a_three_percent_shift_but_flags_ten():
    rng = np.random.default_rng(8)
    x = renders(rng)
    shifted = lambda f: M.inject_roi_shift(renders(rng), ROIS["roi"], f)
    assert M.roi_ratio_verdict(x, shifted(0.03), ROIS)["pass"]      # inside the gate's +-5 %
    assert not M.roi_ratio_verdict(x, shifted(0.10), ROIS)["pass"]


def test_injected_controls_change_the_stack():
    rng = np.random.default_rng(9)
    g = renders(rng)
    for name, ctl in M.injected_controls(g, ROIS).items():
        assert ctl.shape == g.shape and not np.allclose(ctl, g), name
    assert len(list(M.half_splits(8))) == 35
    assert M.tile_means(g, 8).shape == (N, H // 8, W // 8, 3)


@pytest.mark.parametrize("k", [2, 4])
def test_box_down_shape_and_mean(k):
    img = np.arange(16 * 16 * 3, dtype=np.float32).reshape(16, 16, 3)
    d = M.box_down(img, k)
    assert d.shape == (16 // k, 16 // k, 3) and np.isclose(d.mean(), img.mean())

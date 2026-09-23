import numpy as np

from benchmarks.blender_parity import harness as H


def test_checker_counterfactual_rejects_high_variance_outside_named_card_mask():
    baseline = np.full((12, 12, 3), .5, np.float32)
    control = baseline.copy()
    baseline[:, :3] = 0.0  # unrelated black edge/background variance
    baseline[3:9, 4:10] = .5
    mask = np.zeros((12, 12), np.uint8); mask[3:9, 4:10] = 1
    result = H._gate_c_paired_probe(baseline, control, mask, {"kind": "checker", "min_delta": .05, "min_coverage": .02})
    assert not result["ok"]


def test_hair_counterfactual_rejects_bright_scalp_when_hair_off_is_identical():
    baseline = np.full((12, 12, 3), .2, np.float32)
    control = baseline.copy()
    baseline[4:8, 4:8] = 1.0  # bright scalp is present in both legs
    control[4:8, 4:8] = 1.0
    mask = np.zeros((12, 12), np.uint8); mask[1:4, 1:11] = 1
    result = H._gate_c_paired_probe(baseline, control, mask, {"kind": "hair", "min_delta": .05, "min_coverage": .02})
    assert not result["ok"]


def test_paired_feature_delta_requires_supported_masked_change():
    baseline = np.full((10, 10, 3), .2, np.float32); control = baseline.copy()
    baseline[2:6, 3:7] = .7
    mask = np.zeros((10, 10), np.uint8); mask[2:6, 3:7] = 1
    result = H._gate_c_paired_probe(baseline, control, mask, {"kind": "checker", "min_delta": .05, "min_coverage": .5})
    assert result["ok"] and result["coverage"] == 1.0

# -*- coding: utf-8 -*-
"""pkg129 (narrowed) — unit tests for the live-Cycles rough-metal A/B harness.

The pure parts (sweep construction, per-channel ratio, band logic, metric wiring,
report writing) are tested here with synthetic arrays — no Blender, no GPU. The
full three-leg Cycles-vs-Astroray run is the LEAD's on-hardware gate; it needs
Blender + a built addon .pyd + the RTX box (none present in CI), and there is no
verdict here by design.

    pytest tests/test_pkg129_metal_ab_harness.py -v
"""
from __future__ import annotations

import json
import math
import sys
import importlib.util
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_METAL_AB = REPO_ROOT / "benchmarks" / "cycles-parity" / "metal_ab"
# REPO_ROOT stays on sys.path so metal_ab/harness can resolve its
# `benchmarks.reference_bank.metrics` import (fully-qualified, no collision).
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_unique(mod_name, path):
    """Load a module from an explicit file path under a UNIQUE name.

    A bare ``import scenes`` / ``import harness`` collides in the full CI suite:
    other benchmarks dirs ship same-named modules (``benchmarks/blender_parity/
    harness.py``, several ``scenes`` packages), so whichever test imports first
    wins ``sys.modules`` and this test gets the wrong cached module
    (AttributeError: module 'scenes' has no attribute 'metal_sweep'). Loading by
    file path under a pkg129-unique name sidesteps the cache entirely.
    """
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec: @dataclass in the loaded module resolves its own
    # __module__ via sys.modules, which fails if the module isn't registered.
    # The unique name means no collision with other benchmarks modules.
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


S = _load_unique("pkg129_metal_ab_scenes", _METAL_AB / "scenes.py")  # noqa: E402
H = _load_unique("pkg129_metal_ab_harness", _METAL_AB / "harness.py")  # noqa: E402


# --------------------------------------------------------------------------- #
# Sweep construction (pure)
# --------------------------------------------------------------------------- #

def test_metal_sweep_is_3_roughness_x_2_albedo_metallic_one():
    sweep = S.metal_sweep()
    assert len(sweep) == 6
    rough = sorted({c.roughness for c in sweep})
    assert rough == [0.3, 0.6, 0.9]
    albedos = {c.albedo for c in sweep}
    assert albedos == {S.CHROMATIC, S.NEUTRAL}
    # names unique and self-describing
    assert len({c.name for c in sweep}) == 6
    assert "metal_chromatic_r030" in {c.name for c in sweep}
    assert "metal_neutral_r090" in {c.name for c in sweep}


def test_config_by_name_roundtrip_and_unknown():
    cfg = S.config_by_name("metal_neutral_r060")
    assert cfg.roughness == 0.6
    assert cfg.albedo == S.NEUTRAL
    with pytest.raises(ValueError):
        S.config_by_name("no_such_config")


# --------------------------------------------------------------------------- #
# Per-channel ratio + band logic (pure)
# --------------------------------------------------------------------------- #

def test_per_channel_ratio_identity_and_scaled():
    ref = np.full((8, 8, 3), 0.5, dtype=np.float32)
    assert H.per_channel_ratio(ref, ref) == pytest.approx((1.0, 1.0, 1.0))

    actual = ref.copy()
    actual[..., 0] *= 1.10   # R 10% brighter
    actual[..., 2] *= 0.80   # B 20% darker
    r, g, b = H.per_channel_ratio(actual, ref)
    assert r == pytest.approx(1.10, abs=1e-5)
    assert g == pytest.approx(1.00, abs=1e-5)
    assert b == pytest.approx(0.80, abs=1e-5)


def test_per_channel_ratio_zero_reference_is_nan():
    ref = np.zeros((4, 4, 3), dtype=np.float32)
    actual = np.full((4, 4, 3), 0.2, dtype=np.float32)
    ratio = H.per_channel_ratio(actual, ref)
    assert all(np.isnan(v) for v in ratio)


def test_in_band_asserts_both_floor_and_ceiling():
    band = H.Band(0.85, 1.15)
    assert H.in_band((1.0, 1.0, 1.0), band)
    assert H.in_band((0.85, 1.15, 1.0), band)         # exactly on bounds
    # ceiling is load-bearing: an energy GAIN must fail, not just a loss
    assert not H.in_band((1.20, 1.0, 1.0), band)      # over ceiling
    assert not H.in_band((0.80, 1.0, 1.0), band)      # under floor
    assert not H.in_band((float("nan"), 1.0, 1.0), band)  # missing signal fails


# --------------------------------------------------------------------------- #
# Metric wiring + report (uses pkg104 reference_bank; still no Blender/GPU)
# --------------------------------------------------------------------------- #

def _synthetic_pair(scale=1.0, seed=0):
    rng = np.random.default_rng(seed)
    ref = rng.uniform(0.2, 0.6, size=(24, 24, 3)).astype(np.float32)
    actual = (ref * scale).astype(np.float32)
    return actual, ref


def test_compare_leg_passes_on_identity_fails_on_out_of_band():
    band = H.Band(0.85, 1.15)
    actual, ref = _synthetic_pair(scale=1.0, seed=1)
    lc = H.compare_leg("cpu", actual, ref, band)
    assert lc.status == "pass"
    assert lc.ratio == pytest.approx((1.0, 1.0, 1.0), abs=1e-4)
    assert lc.ssim == pytest.approx(1.0, abs=1e-3)  # identical image
    assert lc.delta_e is not None

    actual2, ref2 = _synthetic_pair(scale=1.30, seed=2)  # 30% brighter -> fail ceiling
    lc2 = H.compare_leg("gpu", actual2, ref2, band)
    assert lc2.status == "fail"
    assert lc2.ratio[0] > band.high


def test_write_reports_emits_json_and_md(tmp_path):
    band = H.Band(0.85, 1.15)
    cfg = S.metal_sweep()[0]
    legs = [
        H.LegCompare("cpu", "pass", ratio=(1.01, 0.99, 1.00), ssim=0.99, delta_e=0.5),
        H.LegCompare("gpu", "fail", ratio=(1.20, 1.00, 1.00), ssim=0.9, delta_e=3.0),
    ]
    results = [H.ConfigResult(cfg.name, cfg.roughness, cfg.albedo, legs)]
    H.write_reports(results, tmp_path, band)

    js = (tmp_path / "metal_ab_report.json")
    md = (tmp_path / "metal_ab_report.md")
    assert js.exists() and md.exists()
    import json
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["band"] == {"low": 0.85, "high": 1.15}
    assert payload["configs"][0]["name"] == cfg.name
    text = md.read_text(encoding="utf-8")
    assert "VERDICT: DEFERRED" in text
    assert cfg.name in text


# --------------------------------------------------------------------------- #
# pkg263 — rough-glass preset (sweep, ROI geometry, ROI metrics, report)
# --------------------------------------------------------------------------- #

def test_glass_sweep_is_4_roughness_ior_145():
    sweep = S.glass_sweep()
    assert len(sweep) == 4
    rough = sorted(c.roughness for c in sweep)
    assert rough == [0.0, 0.2, 0.5, 0.85]
    assert all(c.ior == pytest.approx(1.45) for c in sweep)
    assert len({c.name for c in sweep}) == 4
    assert "glass_r000" in {c.name for c in sweep}
    assert "glass_r085" in {c.name for c in sweep}


def test_glass_config_by_name_roundtrip_and_unknown():
    cfg = S.glass_config_by_name("glass_r050")
    assert cfg.roughness == 0.5
    assert cfg.ior == pytest.approx(1.45)
    with pytest.raises(ValueError):
        S.glass_config_by_name("no_such_glass_config")


def test_sphere_projected_radius_px_matches_hand_calc():
    import math
    # r=0.6, d=2.4 -> alpha=asin(0.25); half_fov=25deg; res=256
    r_px = S.sphere_projected_radius_px(0.6, 2.4, math.radians(25.0), 256)
    alpha = math.asin(0.25)
    expected = (math.tan(alpha) / math.tan(math.radians(25.0))) * 128.0
    assert r_px == pytest.approx(expected, rel=1e-9)
    # scales linearly with resolution at fixed geometry
    r_px_2x = S.sphere_projected_radius_px(0.6, 2.4, math.radians(25.0), 512)
    assert r_px_2x == pytest.approx(r_px * 2.0, rel=1e-9)


def test_roi_masks_disjoint_centered_and_within_frame():
    res = 128
    masks, r_px, (cx, cy) = H._roi_masks(res)
    assert cx == cy == res / 2.0
    assert r_px > 0
    # centre disc and limb annulus never overlap (there's a gap 0.35R..0.8R)
    assert not (masks["centre"] & masks["limb"]).any()
    # background patch touches neither the centre disc nor the limb annulus
    assert not (masks["background"] & masks["centre"]).any()
    assert not (masks["background"] & masks["limb"]).any()
    for m in masks.values():
        assert m.any()  # every ROI has at least one pixel at this resolution
    # background patch sits strictly above the sphere's top edge (smaller row
    # index == top, memory blender-pixels-bottom-up-roi-flip)
    import numpy as np
    bg_rows = np.nonzero(masks["background"])[0]
    assert bg_rows.max() < cy - r_px


def test_roi_mean_rgb_and_elementwise_ratio():
    img = np.zeros((8, 8, 3), dtype=np.float32)
    img[:4, :, :] = (0.2, 0.4, 0.8)
    mask_top = np.zeros((8, 8), dtype=bool)
    mask_top[:4, :] = True
    mean = H.roi_mean_rgb(img, mask_top)
    assert mean == pytest.approx((0.2, 0.4, 0.8), abs=1e-6)

    empty_mask = np.zeros((8, 8), dtype=bool)
    assert all(np.isnan(v) for v in H.roi_mean_rgb(img, empty_mask))

    ratio = H._elementwise_ratio((0.4, 0.4, 0.0), (0.2, 0.0, 0.0))
    assert ratio[0] == pytest.approx(2.0)
    assert math.isnan(ratio[1])  # zero denominator -> nan, not a silent pass
    assert math.isnan(ratio[2])


def test_write_glass_reports_emits_json_and_md(tmp_path):
    cfg = S.glass_sweep()[1]
    rois = [
        H.GlassRoiResult("centre", (0.50, 0.50, 0.50), (0.49, 0.51, 0.50), (0.98, 1.02, 1.00)),
        H.GlassRoiResult("limb", (0.45, 0.45, 0.45), (0.30, 0.31, 0.30), (0.67, 0.69, 0.67)),
        H.GlassRoiResult("background", (0.30, 0.30, 0.30), (0.30, 0.30, 0.30), (1.00, 1.00, 1.00)),
    ]
    result = H.GlassConfigResult(
        cfg.name, cfg.roughness, "ok", rois,
        limb_over_centre_cycles=(0.90, 0.90, 0.90),
        limb_over_centre_astroray=(0.61, 0.61, 0.60),
    )
    H.write_glass_reports([result], tmp_path)

    js = tmp_path / "glass_ab_report.json"
    md = tmp_path / "glass_ab_report.md"
    assert js.exists() and md.exists()
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert payload["configs"][0]["name"] == cfg.name
    assert payload["configs"][0]["rois"][1]["roi"] == "limb"
    text = md.read_text(encoding="utf-8")
    assert cfg.name in text
    assert "limb/centre" in text
    assert "Diagnostic only (pkg263)" in text

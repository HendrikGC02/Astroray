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

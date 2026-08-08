# -*- coding: utf-8 -*-
"""pkg119 Phase B - unit tests for the differential-parity harness.

The metric/threshold/triage/selection/report logic is pure Python (no bpy, no
GPU) and is tested here directly with synthetic arrays - this is the real
regression coverage. The full Cycles-vs-Astroray differential run is a
local-host gate that SKIPS CLEANLY when Blender / a built addon / the GPU is
absent (CI has none), mirroring tests/test_dev_loop_smoke.py.

    pytest tests/test_blender_parity_harness.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.blender_parity import harness as H  # noqa: E402
from benchmarks.blender_parity import triage as T  # noqa: E402

BLENDER = Path("C:/Program Files/Blender Foundation/Blender 5.1/blender.exe")


# --------------------------------------------------------------------------- #
# Feature selection
# --------------------------------------------------------------------------- #

def _rows():
    return [
        {"category": "shader_node", "feature": "TEX_NOISE",
         "bl_idname": "ShaderNodeTexNoise", "classification": "SUPPORTED"},
        {"category": "shader_node", "feature": "TEX_NOISE",
         "bl_idname": "ShaderNodeTexNoise", "classification": "DROPPED-SILENT"},
        {"category": "shader_node", "feature": "BSDF_DIFFUSE",
         "bl_idname": "ShaderNodeBsdfDiffuse", "classification": "APPROXIMATED"},
        {"category": "shader_node", "feature": "BSDF_DIFFUSE",
         "bl_idname": "ShaderNodeBsdfDiffuse", "classification": "SUPPORTED"},
        {"category": "light", "feature": "AREA", "bl_idname": "",
         "classification": "SUPPORTED"},
        {"category": "shader_node", "feature": "AMBIENT_OCCLUSION",
         "bl_idname": "ShaderNodeAmbientOcclusion", "classification": "DROPPED-SILENT"},
    ]


def test_select_features_dedups_and_takes_worst_bucket():
    feats = H.select_features(_rows())
    keys = {f.key for f in feats}
    # DROPPED-SILENT-only feature excluded; three unique SUPPORTED/APPROX features.
    assert keys == {"shader_node:TEX_NOISE", "shader_node:BSDF_DIFFUSE", "light:AREA"}
    by_feature = {f.feature: f for f in feats}
    # BSDF_DIFFUSE has both APPROXIMATED and SUPPORTED rows -> worst case wins.
    assert by_feature["BSDF_DIFFUSE"].phase_a_bucket == "APPROXIMATED"
    assert by_feature["TEX_NOISE"].phase_a_bucket == "SUPPORTED"
    assert by_feature["TEX_NOISE"].bl_idname == "ShaderNodeTexNoise"


def test_select_features_on_real_matrix():
    matrix = json.loads(
        (REPO_ROOT / "docs" / "blender_parity" / "coverage_matrix.json").read_text())
    feats = H.select_features(matrix)
    # Phase-A run reported 131 SUPPORTED / 23 APPROXIMATED features; dedup to the
    # unique renderable+meta population. Sanity: non-empty and no DROPPED-SILENT.
    assert len(feats) > 20
    assert all(f.phase_a_bucket in ("SUPPORTED", "APPROXIMATED") for f in feats)
    # every shader feature that made the cut carries a bl_idname
    assert all(f.bl_idname for f in feats if f.category == "shader_node")


# --------------------------------------------------------------------------- #
# Gate
# --------------------------------------------------------------------------- #

def test_gate_pass_when_within_thresholds():
    gr = T.gate(0.97, 2.0, (1.0, 1.0, 1.0))
    assert gr.passed


def test_gate_fails_on_low_ssim():
    gr = T.gate(0.5, 1.0, (1.0, 1.0, 1.0))
    assert not gr.passed and "SSIM" in gr.reason


def test_gate_fails_on_high_delta_e():
    gr = T.gate(0.99, 25.0, (1.0, 1.0, 1.0))
    assert not gr.passed and "dE2000" in gr.reason


# --------------------------------------------------------------------------- #
# Triage - every FAIL lands in exactly one bucket
# --------------------------------------------------------------------------- #

def test_triage_known_intentional_spectral():
    gr = T.gate(0.4, 20.0, (1.0, 1.0, 1.0))
    bucket, reason = T.triage("WAVELENGTH", "SUPPORTED", gr)
    assert bucket == T.INTENTIONAL_DIVERGENCE and "spectral" in reason


def test_triage_pkg89_light_energy():
    gr = T.gate(0.6, 30.0, (3.0, 3.0, 3.0))
    bucket, reason = T.triage("AREA", "SUPPORTED", gr)
    assert bucket == T.INTENTIONAL_DIVERGENCE and "pkg89" in reason


def test_triage_approximated_is_intentional():
    gr = T.gate(0.7, 12.0, (1.05, 0.95, 1.1))
    bucket, _ = T.triage("BSDF_SHEEN", "APPROXIMATED", gr)
    assert bucket == T.INTENTIONAL_DIVERGENCE


def test_triage_uniform_energy_scale_is_intentional():
    gr = T.gate(0.95, 12.0, (1.4, 1.5, 1.45))  # all high, structurally fine
    bucket, reason = T.triage("SomeNode", "SUPPORTED", gr)
    assert bucket == T.INTENTIONAL_DIVERGENCE and "energy-scale" in reason


def test_triage_default_is_translation_bug():
    gr = T.gate(0.6, 15.0, (1.05, 0.7, 1.3))  # channels move differently -> hue bug
    bucket, _reason = T.triage("MIX_RGB", "SUPPORTED", gr)
    assert bucket == T.TRANSLATION_BUG


def test_triage_known_not_implemented_table():
    gr = T.gate(0.99, 0.1, (1.0, 1.0, 1.0))
    bucket, reason = T.triage(
        "Foo", "SUPPORTED", gr,
        known_not_implemented={"Foo": "engine has no lobe for this"})
    assert bucket == T.NOT_IMPLEMENTED


def test_ratio_is_energy_scale_direction_sensitive():
    assert T.ratio_is_energy_scale((1.4, 1.5, 1.45)) is True
    assert T.ratio_is_energy_scale((0.5, 0.6, 0.55)) is True
    # mixed direction is a hue/structure bug, not a uniform scale
    assert T.ratio_is_energy_scale((1.4, 0.6, 1.0)) is False


# --------------------------------------------------------------------------- #
# SPP-escalation discriminator (NOISE-LIMITED vs TRANSLATION-BUG)
# --------------------------------------------------------------------------- #

_INBAND = (1.02, 0.98, 1.03)


def test_ratio_in_band():
    assert T.ratio_in_band(_INBAND) is True
    assert T.ratio_in_band((0.85, 1.18, 1.0)) is True   # edges inclusive
    assert T.ratio_in_band((1.4, 1.0, 1.0)) is False
    assert T.ratio_in_band((0.5, 1.0, 1.0)) is False


def test_is_noise_suspect_requires_inband_and_small_de():
    assert T.is_noise_suspect(_INBAND, 3.0) is True          # dE < 4.0 (=8/2)
    assert T.is_noise_suspect(_INBAND, 5.0) is False         # dE over half-gate
    assert T.is_noise_suspect((1.5, 1.0, 1.0), 1.0) is False  # out-of-band ratio


def test_classify_climb_crossing_threshold_is_noise():
    # SSIM crosses SSIM_MIN on 4x samples -> pure convergence -> noise.
    assert T.classify_noise_vs_bug(0.72, 0.92, 16, 64, _INBAND, 2.0) is True


def test_classify_meaningful_climb_shrinking_gap_is_noise():
    # 0.60 -> 0.75 with SSIM_MIN 0.90: climb 0.15 (>=0.03); gap 0.30 -> 0.15,
    # shrink 50% (>=40%). Still below threshold but clearly converging.
    assert T.classify_noise_vs_bug(0.60, 0.75, 16, 64, _INBAND, 2.0) is True


def test_classify_plateau_is_bug():
    # A structural bug: SSIM barely moves with 4x samples, gap stays wide.
    assert T.classify_noise_vs_bug(0.60, 0.615, 16, 64, _INBAND, 2.0) is False


def test_classify_out_of_band_ratio_is_never_noise():
    # Even if SSIM climbs, an energy/hue bias is a real divergence, not noise.
    assert T.classify_noise_vs_bug(0.60, 0.85, 16, 64, (1.5, 1.5, 1.5), 2.0) is False


def test_classify_large_de_is_never_noise():
    assert T.classify_noise_vs_bug(0.60, 0.85, 16, 64, _INBAND, 6.0) is False


def test_classify_no_escalation_is_not_noise():
    # spp_high must exceed spp_low or there is no sweep evidence.
    assert T.classify_noise_vs_bug(0.60, 0.75, 64, 64, _INBAND, 2.0) is False


def _esc(ssim_low, ssim_high, ratio=_INBAND, de=2.0, spp_low=16, spp_high=64):
    return T.Escalation(ssim_low=ssim_low, ssim_high=ssim_high,
                        spp_low=spp_low, spp_high=spp_high,
                        ratio_high=ratio, delta_e_high=de)


def test_triage_escalation_climbing_ssim_is_noise_limited():
    # (a) climbing SSIM, in-band ratios, small dE -> NOISE-LIMITED, NOT a bug.
    gr = T.gate(0.60, 3.0, _INBAND)
    bucket, reason = T.triage("BSDF_TRANSPARENT", "SUPPORTED", gr,
                              escalation=_esc(0.60, 0.78))
    assert bucket == T.NOISE_LIMITED
    assert "noise" in reason.lower()


def test_triage_escalation_plateau_stays_translation_bug():
    # (b) plateaued SSIM -> a real structural bug is NOT masked.
    gr = T.gate(0.60, 3.0, _INBAND)
    bucket, _reason = T.triage("SOME_NODE", "SUPPORTED", gr,
                               escalation=_esc(0.60, 0.615))
    assert bucket == T.TRANSLATION_BUG


def test_triage_escalation_out_of_band_routes_to_existing_rules():
    # (c) out-of-band uniform ratio -> INTENTIONAL energy-scale even with an
    # escalation attached (energy-scale rule has precedence over the noise rule).
    gr = T.gate(0.60, 12.0, (1.5, 1.5, 1.5))
    bucket, reason = T.triage("SOME_NODE", "SUPPORTED", gr,
                              escalation=_esc(0.60, 0.85, ratio=(1.5, 1.5, 1.5)))
    assert bucket == T.INTENTIONAL_DIVERGENCE and "energy-scale" in reason


def test_triage_escalation_does_not_override_precedence():
    # (d) known-intentional + APPROXIMATED still win over a supplied escalation.
    gr = T.gate(0.40, 20.0, _INBAND)
    bucket, _ = T.triage("WAVELENGTH", "SUPPORTED", gr, escalation=_esc(0.40, 0.95))
    assert bucket == T.INTENTIONAL_DIVERGENCE
    bucket, _ = T.triage("BSDF_SHEEN", "APPROXIMATED", gr, escalation=_esc(0.40, 0.95))
    assert bucket == T.INTENTIONAL_DIVERGENCE


def test_triage_without_escalation_defaults_to_translation_bug():
    # No sweep supplied -> the noise rule is skipped, default stands (a real bug
    # is never masked by a missing escalation).
    gr = T.gate(0.60, 3.0, _INBAND)
    bucket, _ = T.triage("SOME_NODE", "SUPPORTED", gr)
    assert bucket == T.TRANSLATION_BUG


# --------------------------------------------------------------------------- #
# Metric comparison + triage integration (pure, synthetic arrays)
# --------------------------------------------------------------------------- #

def _img(seed, base):
    rng = np.random.default_rng(seed)
    return (base + rng.normal(0, 0.002, size=(48, 48, 3))).astype(np.float32).clip(0, None)


def test_compare_identical_passes():
    feat = H.Feature("shader_node", "TEX_CHECKER", "ShaderNodeTexChecker", "SUPPORTED")
    a = _img(1, 0.5)
    res = H.compare_and_triage(feat, a, a.copy())
    assert res.status == "pass" and res.triage_bucket is None
    assert res.ssim == pytest.approx(1.0, abs=1e-6)


def test_compare_black_material_triages_translation_bug():
    feat = H.Feature("shader_node", "MIX_RGB", "ShaderNodeMixRGB", "SUPPORTED")
    reference = _img(2, 0.6)              # oracle: lit surface
    actual = np.zeros_like(reference)    # addon: black (feature dropped/mis-wired)
    res = H.compare_and_triage(feat, actual, reference)
    assert res.status == "fail"
    assert res.triage_bucket in (T.TRANSLATION_BUG, T.INTENTIONAL_DIVERGENCE)


def test_per_channel_ratio():
    a = np.full((4, 4, 3), 0.6, np.float32)
    r = np.full((4, 4, 3), 0.3, np.float32)
    assert H.per_channel_ratio(a, r) == pytest.approx((2.0, 2.0, 2.0))


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #

def test_write_reports_and_followups(tmp_path):
    results = [
        H.FeatureResult("shader_node", "TEX_NOISE", "SUPPORTED", "pass",
                        ssim=0.98, delta_e=1.0, ratio=(1.0, 1.0, 1.0)),
        H.FeatureResult("shader_node", "MIX_RGB", "SUPPORTED", "fail",
                        ssim=0.6, delta_e=15.0, ratio=(1.0, 0.7, 1.3),
                        triage_bucket=T.TRANSLATION_BUG, triage_reason="diverges"),
        H.FeatureResult("light", "AREA", "SUPPORTED", "fail",
                        ssim=0.6, delta_e=30.0, ratio=(3.0, 3.0, 3.0),
                        triage_bucket=T.INTENTIONAL_DIVERGENCE, triage_reason="pkg89"),
        H.FeatureResult("render_settings", "RenderSettings", "SUPPORTED", "skip",
                        skip_reason="no differential scene"),
        H.FeatureResult("shader_node", "TEX_MAGIC", "SUPPORTED", "crash",
                        notes="CYCLES leg did not PASS"),
    ]
    H.write_reports(results, tmp_path)
    payload = json.loads((tmp_path / "triage_report.json").read_text())
    assert payload["summary"]["total"] == 5
    assert payload["summary"]["status"]["crash"] == 1
    # only the TRANSLATION-BUG feature is a follow-up candidate (INTENTIONAL isn't)
    fu = payload["summary"]["follow_up_candidates"]
    assert [c["feature"] for c in fu] == ["shader_node:MIX_RGB"]
    assert (tmp_path / "triage_report.md").exists()


def test_write_reports_noise_limited_is_not_followup_and_is_audited(tmp_path):
    results = [
        H.FeatureResult("shader_node", "BSDF_TRANSPARENT", "SUPPORTED", "fail",
                        ssim=0.60, delta_e=3.0, ratio=(1.0, 1.0, 1.0),
                        triage_bucket=T.NOISE_LIMITED, triage_reason="under-converged",
                        escalated=True, samples_low=64, samples_high=256,
                        ssim_high_spp=0.82, delta_e_high_spp=2.4),
    ]
    H.write_reports(results, tmp_path)
    payload = json.loads((tmp_path / "triage_report.json").read_text())
    # NOISE-LIMITED is not a bug -> not a roadmap follow-up candidate.
    assert payload["summary"]["follow_up_candidates"] == []
    assert payload["summary"]["triage"][T.NOISE_LIMITED] == 1
    md = (tmp_path / "triage_report.md").read_text()
    assert "SPP-escalation: 64->256 spp" in md


# --------------------------------------------------------------------------- #
# Local-host differential gate (skips cleanly without Blender / build / GPU)
# --------------------------------------------------------------------------- #

@pytest.mark.serial
@pytest.mark.gpu
def test_differential_run_local_host(tmp_path):
    if not BLENDER.exists():
        pytest.skip("Blender 5.1 not installed - local-host gate")
    if H._pyd_dir(REPO_ROOT) is None and H._pyd_dir(REPO_ROOT.parent / "Astroray") is None:
        pytest.skip("no built astroray .pyd - build the addon first")

    # One-feature matrix keeps the gate bounded; the full sweep is the parent's job.
    mini = tmp_path / "mini_matrix.json"
    mini.write_text(json.dumps([
        {"category": "shader_node", "feature": "EMISSION",
         "bl_idname": "ShaderNodeEmission", "classification": "SUPPORTED"},
    ]))
    rc = H.run(mini, tmp_path / "out", res=64, samples=16, timeout=300,
               include_composites=False)
    report = tmp_path / "out" / "triage_report.json"
    assert report.exists(), "harness did not write a triage report"
    payload = json.loads(report.read_text())
    assert payload["summary"]["total"] == 1
    # rc==0 means no crashed feature; a triaged FAIL is acceptable output.
    assert rc in (0, 1)

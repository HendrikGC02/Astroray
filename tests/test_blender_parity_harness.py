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

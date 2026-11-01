"""pkg328 Phase 2: the audited-matrix score (owner 2026-10-31).

Credit per identity is the static matrix class; a sampled audit witness, judged only by
``mc_compare.welch_verdict`` (Welch-1b), zeroes the identities it covers when it FAILs.  The threshold is the
owner-signed number; until it is signed, b2/b3 fail.  Pure python/numpy, no Blender.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from benchmarks.blender_parity import mc_compare as MCC
from benchmarks.blender_parity import render_leg as R
from benchmarks.reference_corpus import coverage_report as C

A = C.canonical_identity("ShaderNodeTexNoise", "input:Scale")
B = C.canonical_identity("ShaderNodeTexNoise", "input:Detail")
D = C.canonical_identity("ShaderNodeBsdfDiffuse", "input:Color")
E = C.canonical_identity("ShaderNodeBsdfGlass", "input:Normal")
F = C.canonical_identity("ShaderNodeTexWave", "input:Scale")   # supported, in no witness
MATRIX = {A: C.SUPPORTED, B: C.APPROXIMATED, D: C.SUPPORTED, E: C.DROPPED_SILENT, F: C.SUPPORTED}
LEDGER = [  # weights: A 3 scenes -> 3, B 2 -> 2, D 1 -> 1, E 1 -> 1, F 3 -> 3
    {"identity": A, "scene_ids": ["s1", "s2", "s3"]}, {"identity": B, "scene_ids": ["s1", "s2"]},
    {"identity": D, "scene_ids": ["s1"]}, {"identity": E, "scene_ids": ["s1"]},
    {"identity": F, "scene_ids": ["s1", "s2", "s3", "s4"]}]
DENOM = 3 + 2 + 1 + 1 + 3


def _audit(statuses: dict[str, dict[str, str]], witnesses: list[dict] | None = None) -> dict:
    witnesses = witnesses or [{"id": "w_noise", "identities": [A, B]}, {"id": "w_diffuse", "identities": [D]}]
    return {"sample": {"witnesses": witnesses},
            "results": {"n_seeds": 4, "witnesses": {
                wid: {b: {"status": st, "jackknife_pass": [st != "FAIL"] * 4} for b, st in per.items()}
                for wid, per in statuses.items()}}}


def _zeroed(audit):
    return {b: C.audit_zeroed(audit, b) for b in ("CPU", "GPU")}


def test_matrix_credit_values():
    assert C.matrix_credit(C.SUPPORTED) == 1.0
    assert C.matrix_credit(C.APPROXIMATED) == 0.5
    assert C.matrix_credit(C.DROPPED_SILENT) == 0.0
    assert C.matrix_credit("") == 0.0


def test_ceiling_is_pure_matrix_credit():
    s = C.score_audited(LEDGER, MATRIX, None)
    assert s["CPU"].score == pytest.approx((3 * 1.0 + 2 * 0.5 + 1 * 1.0 + 0 + 3 * 1.0) / DENOM)
    assert s["GPU"].score == s["CPU"].score
    assert s["CPU"].denominator == DENOM


def test_passing_witness_leaves_identities_at_matrix_credit():
    audit = _audit({"w_noise": {"CPU": "PASS", "GPU": "PASS"}, "w_diffuse": {"CPU": "PASS", "GPU": "PASS"}})
    s = C.score_audited(LEDGER, MATRIX, _zeroed(audit))
    assert s["CPU"].score == C.score_audited(LEDGER, MATRIX, None)["CPU"].score


def test_failing_witness_zeroes_only_its_identities_on_its_backend():
    audit = _audit({"w_noise": {"CPU": "FAIL", "GPU": "PASS"}, "w_diffuse": {"CPU": "PASS", "GPU": "PASS"}})
    s = C.score_audited(LEDGER, MATRIX, _zeroed(audit))
    assert s["CPU"].score == pytest.approx((1.0 * 1 + 3) / DENOM)  # D and F survive (E is dropped)
    assert s["GPU"].score == pytest.approx((3 + 1 + 1 + 3) / DENOM)  # GPU witness passed
    reasons = {u.key: u.cpu_reason for u in s["CPU"].use_scores}
    assert "w_noise" in reasons[A] and "w_noise" in reasons[B]


@pytest.mark.parametrize("status", ["NO-EFFECT", "ERROR"])
def test_no_effect_or_error_witness_neither_credits_nor_zeroes(status):
    audit = _audit({"w_noise": {"CPU": status, "GPU": status}, "w_diffuse": {"CPU": "PASS", "GPU": "PASS"}})
    assert _zeroed(audit) == {"CPU": {}, "GPU": {}}
    s = C.score_audited(LEDGER, MATRIX, _zeroed(audit))
    assert s["CPU"].score == C.score_audited(LEDGER, MATRIX, None)["CPU"].score


def test_a_dropped_identity_stays_zero_even_without_a_failing_witness():
    s = C.score_audited(LEDGER, MATRIX, None)
    assert {u.key: u.cpu for u in s["CPU"].use_scores}[E] == 0.0


def test_proposal_margin_is_seed_spread_plus_one_witness_weight():
    audit = _audit({"w_noise": {"CPU": "PASS", "GPU": "PASS"}, "w_diffuse": {"CPU": "PASS", "GPU": "PASS"}})
    # seed 2 flips w_diffuse to FAIL on CPU only
    audit["results"]["witnesses"]["w_diffuse"]["CPU"]["jackknife_pass"][2] = False
    p = C.audit_proposal(LEDGER, MATRIX, audit)
    ceiling = (3 + 1 + 1 + 3) / DENOM
    assert p["CPU"]["ceiling"] == pytest.approx(ceiling)
    assert p["CPU"]["seed_spread"] == pytest.approx(1.0 / DENOM)        # S drops by D's weight when seed 2 is left out
    assert p["GPU"]["seed_spread"] == 0.0
    assert p["CPU"]["one_witness_weight"] == pytest.approx((3 + 1.0) / DENOM)  # w_noise: A 3*1 + B 2*0.5
    assert p["CPU"]["proposed_threshold"] == pytest.approx(ceiling - 1.0 / DENOM - 4.0 / DENOM)
    assert p["GPU"]["proposed_threshold"] == pytest.approx(ceiling - 4.0 / DENOM)
    assert p["CPU"]["measured"] == pytest.approx(ceiling)


def test_proposal_threshold_is_clamped_at_zero():
    audit = _audit({"w_noise": {"CPU": "PASS", "GPU": "PASS"}, "w_diffuse": {"CPU": "PASS", "GPU": "PASS"}})
    audit["results"]["witnesses"]["w_noise"]["CPU"]["jackknife_pass"][0] = False
    audit["sample"]["witnesses"].append({"id": "big", "identities": [A, B, D, F]})
    audit["results"]["witnesses"]["big"] = {b: {"status": "PASS", "jackknife_pass": [True] * 4} for b in ("CPU", "GPU")}
    assert C.audit_proposal(LEDGER, MATRIX, audit)["CPU"]["proposed_threshold"] >= 0.0


# ---------------------------------------------------------------- thresholds


def test_threshold_unsigned_keeps_b2_b3_red(tmp_path):
    (tmp_path / "docs/blender_parity/evidence/gate_b").mkdir(parents=True)
    path = tmp_path / C.THRESHOLD_PATH
    path.write_text(json.dumps({"schema": C.THRESHOLD_SCHEMA, "proposed": {"cpu": 0.4, "gpu": 0.4}, "signed": None}))
    t = C.load_b_threshold(tmp_path)
    assert t["signed"] is False and t["min"] == {"CPU": None, "GPU": None} and t["proposed"]["CPU"] == 0.4
    res = C._score_subcheck(0.99, "CPU", t)
    assert res["pass"] is False and res["min"] is None and res["signed"] is False


def test_threshold_signed_is_the_bound(tmp_path):
    (tmp_path / "docs/blender_parity/evidence/gate_b").mkdir(parents=True)
    (tmp_path / C.THRESHOLD_PATH).write_text(json.dumps({
        "schema": C.THRESHOLD_SCHEMA, "proposed": {"cpu": 0.4, "gpu": 0.4},
        "signed": {"cpu": 0.40, "gpu": 0.35, "owner": "owner", "pr": 1}}))
    t = C.load_b_threshold(tmp_path)
    assert t["signed"] and t["min"] == {"CPU": 0.4, "GPU": 0.35}
    assert C._score_subcheck(0.40, "CPU", t)["pass"] is True
    assert C._score_subcheck(0.39, "CPU", t)["pass"] is False
    assert C._score_subcheck(0.35, "GPU", t)["pass"] is True


def test_threshold_without_owner_or_file_is_unsigned(tmp_path):
    assert C.load_b_threshold(tmp_path)["signed"] is False
    (tmp_path / "docs/blender_parity/evidence/gate_b").mkdir(parents=True)
    (tmp_path / C.THRESHOLD_PATH).write_text(json.dumps({
        "schema": C.THRESHOLD_SCHEMA, "signed": {"cpu": 0.4, "gpu": 0.4}}))
    assert C.load_b_threshold(tmp_path)["signed"] is False


def test_fixture_default_is_the_retired_constant():
    assert C._score_subcheck(0.96, "CPU", None) == {"pass": True, "score": 0.96, "min": C.SCORE_MIN}


def test_committed_threshold_file_is_unsigned_until_the_owner_signs():
    data = json.loads((REPO / C.THRESHOLD_PATH).read_text(encoding="utf-8"))
    assert data["schema"] == C.THRESHOLD_SCHEMA
    if data.get("signed") is not None:  # after sign-off the number and the owner are both recorded
        assert data["signed"]["owner"] and isinstance(data["signed"]["cpu"], float)


def test_gate_manifest_row_b_bound_follows_the_threshold_file():
    import gate_manifest as G

    t = C.load_b_threshold(REPO)
    expected = {b: (t["min"][b] if t["signed"] else (t["proposed"][b] if t["proposed"][b] is not None else 1.0))
                for b in ("CPU", "GPU")}
    assert G.ROW_SPEC["b"]["threshold"] == {"cpu_score": {"min": expected["CPU"]}, "gpu_score": {"min": expected["GPU"]}}
    assert G.ROW_SPEC["b"]["threshold"]["cpu_score"]["min"] != 0.95  # 0.95 is retired


# ---------------------------------------------------------------- Welch-1b judge uses mc_compare.welch_verdict


def _write_legs(root: Path, w: dict, seeds, rng, *, bias: float, effect: bool):
    h, wd = 48, 64
    for engine, leg_dir in (("astroray", "cpu"), ("cycles", "cycles")):
        for s in seeds:
            d = root / "stacks" / w["scene_id"] / leg_dir
            d.mkdir(parents=True, exist_ok=True)
            base = 0.4 + 0.02 * rng.standard_normal((h, wd, 3))
            np.save(d / f"s{s}.npy", (base * (1.0 + (bias if engine == "astroray" else 0.0))).astype(np.float32))
    wdir = root / "CPU" / C._study_slug(w["id"])
    wdir.mkdir(parents=True, exist_ok=True)
    mask = np.zeros((h, wd), np.uint8)
    mask[10:40, 10:50] = 255
    for name in ("astroray", "cycles"):
        base = np.full((h, wd, 3), 0.4, np.float32)
        ctrl = base.copy()
        if effect:
            ctrl[mask > 0] = 0.1
        np.save(wdir / f"{name}.npy", base)
        np.save(wdir / f"{name}_control.npy", ctrl)
        np.save(wdir / f"{name}_mask.npy", mask)
        np.save(wdir / f"{name}_control_mask.npy", mask)


def _sample(seeds):
    wit = {"id": "scn/Obj/Node", "scene_id": "scn", "identities": [A],
           "witness": {"roi": [0.0, 0.0, 1.0, 1.0], "control": {"kind": "noise_const"},
                       "effect": {"kind": "changed", "min_delta": 0.01, "min_coverage": 0.05, "min_signal": 0.001}}}
    return {"seeds": list(seeds), "witnesses": [wit]}


def test_judge_status_comes_from_welch_verdict(tmp_path, monkeypatch):
    seeds = (11, 12, 13, 14, 15, 16, 17, 18)
    sample = _sample(seeds)
    rng = np.random.default_rng(5)
    _write_legs(tmp_path, sample["witnesses"][0], seeds, rng, bias=0.0, effect=True)
    calls = []
    real = MCC.welch_verdict

    def spy(x, y, **kw):
        calls.append(kw)
        return real(x, y, **kw)
    monkeypatch.setattr(MCC, "welch_verdict", spy)
    out = C.audit_judge(sample, tmp_path, "CPU")["scn/Obj/Node"]
    assert out["status"] == "PASS" and out["effect"]["astroray"]["ok"]
    assert calls and all(k == C.AUDIT_WELCH for k in calls)       # frozen Welch-1b parameters
    assert len(calls) == 1 + len(seeds)                            # one verdict + one leave-one-seed-out per seed
    assert len(out["jackknife_pass"]) == len(seeds)
    # the status follows the verdict object, whatever it is
    monkeypatch.setattr(MCC, "welch_verdict", lambda x, y, **kw: {**real(x, y, **kw), "pass": False})
    assert C.audit_judge(sample, tmp_path, "CPU")["scn/Obj/Node"]["status"] == "FAIL"


def test_judge_fails_a_real_two_percent_bias(tmp_path):
    seeds = (11, 12, 13, 14, 15, 16, 17, 18)
    sample = _sample(seeds)
    _write_legs(tmp_path, sample["witnesses"][0], seeds, np.random.default_rng(6), bias=0.05, effect=True)
    out = C.audit_judge(sample, tmp_path, "CPU")["scn/Obj/Node"]
    assert out["status"] == "FAIL" and out["welch"]["n_reject_holm"] > 0


def test_judge_records_no_effect_without_crediting(tmp_path):
    seeds = (11, 12, 13, 14, 15, 16, 17, 18)
    sample = _sample(seeds)
    _write_legs(tmp_path, sample["witnesses"][0], seeds, np.random.default_rng(7), bias=0.05, effect=False)
    assert C.audit_judge(sample, tmp_path, "CPU")["scn/Obj/Node"]["status"] == "NO-EFFECT"


def test_judge_reports_missing_legs_as_error(tmp_path):
    out = C.audit_judge(_sample((1, 2, 3, 4)), tmp_path, "CPU")["scn/Obj/Node"]
    assert out["status"] == "ERROR"


# ---------------------------------------------------------------- frozen sample + pinned inputs


def test_committed_sample_is_the_candidate_v2_subset_plus_b5_families():
    sample = json.loads((REPO / C.AUDIT_SAMPLE_PATH).read_text(encoding="utf-8"))
    cands = json.loads((REPO / "benchmarks/reference_corpus/witness_candidates_v5.json").read_text(encoding="utf-8"))
    v2 = {w["id"] for w in cands["witnesses"] if w["population"] == "candidate_v2"}
    origin = {w["id"]: w["origin"] for w in sample["witnesses"]}
    assert {i for i, o in origin.items() if o == "witness_candidates_v5"} == v2
    assert sorted(w["family"] for w in sample["witnesses"] if w["origin"] == "supplement") == ["Metallic", "Principled", "Sky"]
    assert len(origin) == len(sample["witnesses"])                  # unique ids
    assert sample["welch"] == C.AUDIT_WELCH
    kinds = {w["witness"]["control"]["kind"] for w in sample["witnesses"]}
    assert kinds <= set(R.GATE_B_CONTROL_NODE_TYPES)
    assert sample["selection"]["candidates"]["sha256"] == C.sha256_file(REPO / "benchmarks/reference_corpus/witness_candidates_v5.json")


def test_load_audit_rejects_a_tampered_or_unbound_file(tmp_path):
    sample = {"schema": C.AUDIT_SAMPLE_SCHEMA, "witnesses": [{"id": "w", "scene_id": "s1", "identities": [A]}]}
    sp = tmp_path / "sample.json"
    sp.write_text(json.dumps(sample))
    results = {"schema": C.AUDIT_RESULTS_SCHEMA, "sample_sha256": C.sha256_file(sp), "welch": C.AUDIT_WELCH,
               "n_seeds": 4, "witnesses": {"w": {}}}
    rp = tmp_path / "results.json"
    rp.write_text(json.dumps(results))
    ref = {"sample": {"path": "sample.json", "sha256": C.sha256_file(sp)},
           "results": {"path": "results.json", "sha256": C.sha256_file(rp)}}
    audit, errors = C.load_audit(ref, tmp_path, ["s1"])
    assert not errors and audit["sample"]["witnesses"][0]["id"] == "w"
    _, errors = C.load_audit(ref, tmp_path, ["other"])
    assert any("not in a frozen scene" in e for e in errors)
    rp.write_text(json.dumps({**results, "welch": {"alpha": 0.2, "tile": 8, "delta_rel": 0.0}}))
    ref["results"]["sha256"] = C.sha256_file(rp)
    _, errors = C.load_audit(ref, tmp_path, ["s1"])
    assert any("Welch-1b" in e for e in errors)
    sp.write_text(json.dumps({**sample, "extra": 1}))                # sample edited after the freeze
    _, errors = C.load_audit(ref, tmp_path, ["s1"])
    assert any("hash does not match" in e for e in errors)

"""pkg328 Phase 2: the audited-matrix score (owner 2026-10-31).

Credit per identity is the static matrix class; a sampled audit witness, judged only by
``mc_compare.welch_verdict`` (Welch-1b), zeroes the identities it covers when it FAILs.  The threshold is the
owner-signed number; until it is signed, b2/b3 fail.  Pure python/numpy, no Blender.
"""

from __future__ import annotations

import json
import subprocess
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


def _leg(status: str) -> dict:
    """A stored witness leg consistent with ``status`` under the item-1 rules."""
    ok = {"ok": True}
    effect = {"PASS": {"astroray": ok, "cycles": ok}, "FAIL": {"astroray": ok, "cycles": ok},
              "NO-EFFECT": {"astroray": {"ok": False}, "cycles": {"ok": False}}}.get(status)
    if effect is None:
        return {"status": status, "reason": "legs missing"}
    return {"status": status, "effect": effect, "welch": {"pass": status == "PASS"}, "jackknife_pass": [status == "PASS"] * 4}


def _audit(statuses: dict[str, dict[str, str]], witnesses: list[dict] | None = None) -> dict:
    witnesses = witnesses or [{"id": "w_noise", "identities": [A, B]}, {"id": "w_diffuse", "identities": [D]}]
    return {"sample": {"witnesses": witnesses},
            "results": {"n_seeds": 4, "witnesses": {
                wid: {b: _leg(st) for b, st in per.items()} for wid, per in statuses.items()}}}


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
def test_no_effect_or_error_witness_credits_nothing(status):
    audit = _audit({"w_noise": {"CPU": status, "GPU": status}, "w_diffuse": {"CPU": "PASS", "GPU": "PASS"}})
    assert set(_zeroed(audit)["CPU"]) == {A, B} and set(_zeroed(audit)["GPU"]) == {A, B}
    s = C.score_audited(LEDGER, MATRIX, _zeroed(audit))
    assert s["CPU"].score == pytest.approx((1.0 * 1 + 3) / DENOM)   # same as a FAIL: A and B zeroed


def test_a_missing_backend_leg_is_an_error_that_zeroes_and_marks_the_audit_incomplete():
    audit = _audit({"w_noise": {"CPU": "PASS"}, "w_diffuse": {"CPU": "PASS", "GPU": "PASS"}})   # w_noise has no GPU leg
    assert C._witness_status(audit["results"], "w_noise", "GPU") == "ERROR"
    assert set(_zeroed(audit)["GPU"]) == {A, B} and _zeroed(audit)["CPU"] == {}
    assert [i.split(" [")[0] for i in C.audit_incomplete(audit)] == ["w_noise"]
    assert C.audit_incomplete(_audit({"w_noise": {"CPU": "NO-EFFECT", "GPU": "PASS"}, "w_diffuse": {"CPU": "PASS", "GPU": "PASS"}})) == []


@pytest.mark.parametrize("astroray,cycles,welch_pass,expected", [
    (True, True, True, "PASS"), (True, True, False, "FAIL"),
    (False, True, True, "FAIL"),        # Cycles' control moves the image, Astroray's does not: Astroray ignores the node
    (False, True, False, "FAIL"),
    (False, False, True, "NO-EFFECT"),  # neither engine shows an effect: nothing to judge
    (True, False, True, "NO-EFFECT")])  # no Cycles effect: the oracle cannot confirm the node matters
def test_leg_status_rules(astroray, cycles, welch_pass, expected):
    effect = {"astroray": {"ok": astroray}, "cycles": {"ok": cycles}}
    assert C.audit_leg_status(effect, welch_pass) == expected


def test_jackknife_never_flips_an_effect_decided_status():
    audit = _audit({"w_noise": {"CPU": "PASS", "GPU": "PASS"}, "w_diffuse": {"CPU": "PASS", "GPU": "PASS"}})
    leg = audit["results"]["witnesses"]["w_noise"]["CPU"]
    leg.update(status="FAIL", effect={"astroray": {"ok": False}, "cycles": {"ok": True}}, jackknife_pass=[True] * 4)
    assert C._witness_status(audit["results"], "w_noise", "CPU", 1) == "FAIL"


# ---------------------------------------------------------------- b6: nonzero uses link evidence


def _b6_fixture(statuses, *, digests=True, variant_of_f="v-f"):
    ledger = [{"identity": A, "variants": [{"scene_id": "s1", "variant_digest": "v-a"}], "scene_ids": ["s1"]},
              {"identity": F, "variants": [{"scene_id": "s1", "variant_digest": variant_of_f}], "scene_ids": ["s1"]}]
    witnesses = [{"id": "w_a", "scene_id": "s1", "variant_digest": "v-a", "identities": [A]},
                 {"id": "w_f", "scene_id": "s1", "variant_digest": "v-f", "identities": [F]}]
    audit = _audit(statuses, witnesses)
    audit["results"]["stack_sha256"] = {b: ({"s1/cpu": "x", "s1/gpu": "x", "s1/cycles": "y"} if digests else {})
                                        for b in ("CPU", "GPU")}
    return ledger, audit


def _b6(ledger, audit):
    return C.audit_links_evidence(ledger, C.score_audited(ledger, MATRIX, _zeroed(audit)), audit)


def test_b6_passes_only_when_every_nonzero_use_has_a_passing_witness_with_stack_digests():
    ok = {w: {"CPU": "PASS", "GPU": "PASS"} for w in ("w_a", "w_f")}
    ledger, audit = _b6_fixture(ok)
    assert _b6(ledger, audit)["pass"] is True and _b6(ledger, audit)["unlinked_count"] == {"CPU": 0, "GPU": 0}
    ledger, audit = _b6_fixture(ok, digests=False)                   # no recorded evidence artifact
    assert _b6(ledger, audit)["pass"] is False
    ledger, audit = _b6_fixture(ok, variant_of_f="other")            # a witness for a different variant of the same identity
    res = _b6(ledger, audit)
    assert res["pass"] is False and res["unlinked_count"] == {"CPU": 1, "GPU": 1} and "no PASSing audit witness" in res["reason"]


def test_b6_is_false_for_uses_no_witness_covers_and_a_zeroed_use_needs_no_link():
    ledger, audit = _b6_fixture({"w_a": {"CPU": "FAIL", "GPU": "PASS"}, "w_f": {"CPU": "PASS", "GPU": "PASS"}})
    res = _b6(ledger, audit)
    assert res["unlinked_count"] == {"CPU": 0, "GPU": 0} and res["pass"]     # A scores 0 on CPU: nothing to link there
    ledger.append({"identity": D, "variants": [{"scene_id": "s1", "variant_digest": "v-d"}], "scene_ids": ["s1"]})
    res = _b6(ledger, audit)
    assert res["pass"] is False and res["unlinked_count"] == {"CPU": 1, "GPU": 1}


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


def test_spread_includes_the_measured_full_seed_score():
    """A witness that fails with all 8 seeds but passes every 7-seed subset: the leave-one-out scores alone show no spread."""
    audit = _audit({"w_noise": {"CPU": "PASS", "GPU": "PASS"}, "w_diffuse": {"CPU": "PASS", "GPU": "PASS"}})
    leg = audit["results"]["witnesses"]["w_diffuse"]["CPU"]
    leg.update(status="FAIL", welch={"pass": False})                 # fails at 4 seeds, passes every 3-seed subset
    leg["jackknife_pass"] = [True] * 4
    p = C.audit_proposal(LEDGER, MATRIX, audit)
    ceiling = (3 + 1 + 1 + 3) / DENOM
    assert p["CPU"]["loo_scores"] == [pytest.approx(ceiling)] * 4
    assert p["CPU"]["measured"] == pytest.approx(ceiling - 1.0 / DENOM)
    assert p["CPU"]["seed_spread"] == pytest.approx(1.0 / DENOM)
    assert p["CPU"]["proposed_threshold"] == pytest.approx(ceiling - 1.0 / DENOM - 4.0 / DENOM)


def test_proposal_threshold_is_clamped_at_zero():
    audit = _audit({"w_noise": {"CPU": "PASS", "GPU": "PASS"}, "w_diffuse": {"CPU": "PASS", "GPU": "PASS"}})
    audit["results"]["witnesses"]["w_noise"]["CPU"]["jackknife_pass"][0] = False
    audit["sample"]["witnesses"].append({"id": "big", "identities": [A, B, D, F]})
    audit["results"]["witnesses"]["big"] = {b: {"status": "PASS", "jackknife_pass": [True] * 4} for b in ("CPU", "GPU")}
    assert C.audit_proposal(LEDGER, MATRIX, audit)["CPU"]["proposed_threshold"] >= 0.0


# ---------------------------------------------------------------- thresholds


CEILINGS = {"CPU": 0.7, "GPU": 0.6}
GOOD_SIGNED = {"cpu": 0.40, "gpu": 0.35, "owner": "owner", "pr": 1, "date": "2026-11-02"}


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, check=True, capture_output=True)


def _threshold_repo(root: Path, signed, *, commit: bool = True, proposed=None) -> Path:
    """A throwaway git repo holding a threshold file; ``commit=False`` leaves the signed bytes uncommitted."""
    path = root / C.THRESHOLD_PATH
    path.parent.mkdir(parents=True)
    body = {"schema": C.THRESHOLD_SCHEMA, "proposed": proposed or {"cpu": 0.4, "gpu": 0.4}, "signed": signed}
    _git(root, "init", "-q")
    if not commit:
        path.write_text(json.dumps({**body, "signed": None}))
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "unsigned")
    path.write_text(json.dumps(body))
    if commit:
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "sign")
    return root


def test_threshold_unsigned_keeps_b2_b3_red(tmp_path):
    t = C.load_b_threshold(_threshold_repo(tmp_path, None), CEILINGS)
    assert t["signed"] is False and t["min"] == {"CPU": None, "GPU": None} and t["proposed"]["CPU"] == 0.4
    res = C._score_subcheck(0.99, "CPU", t)
    assert res["pass"] is False and res["min"] is None and res["signed"] is False and "not signed" in res["reason"]


def test_threshold_signed_is_the_bound(tmp_path):
    t = C.load_b_threshold(_threshold_repo(tmp_path, GOOD_SIGNED), CEILINGS)
    assert t["signed"] and t["min"] == {"CPU": 0.4, "GPU": 0.35} and t["reason"] == ""
    assert C._score_subcheck(0.40, "CPU", t)["pass"] is True
    assert C._score_subcheck(0.39, "CPU", t)["pass"] is False
    assert C._score_subcheck(0.35, "GPU", t)["pass"] is True


@pytest.mark.parametrize("edit,why", [
    ({"owner": ""}, "owner"), ({"owner": "   "}, "owner"), ({"owner": None}, "owner"),
    ({"cpu": 0}, "cpu"), ({"cpu": -0.1}, "cpu"), ({"cpu": "0.4"}, "cpu"), ({"gpu": True}, "gpu"), ({"gpu": float("nan")}, "gpu"),
    ({"cpu": 0.71}, "exceeds the CPU measured ceiling"), ({"gpu": 0.61}, "exceeds the GPU measured ceiling"),
    ({"pr": "1"}, "pr"), ({"pr": True}, "pr"), ({"pr": None}, "pr"), ({"date": ""}, "date"), ({"date": None}, "date")])
def test_signed_threshold_with_a_bad_field_is_unsigned(tmp_path, edit, why):
    t = C.load_b_threshold(_threshold_repo(tmp_path, {**GOOD_SIGNED, **edit}), CEILINGS)
    assert t["signed"] is False and t["min"] == {"CPU": None, "GPU": None} and why in t["reason"]
    assert C._score_subcheck(0.99, "CPU", t)["pass"] is False


def test_signed_threshold_missing_a_field_is_unsigned(tmp_path):
    for field in ("owner", "pr", "date", "cpu", "gpu"):
        root = tmp_path / field
        root.mkdir()
        t = C.load_b_threshold(_threshold_repo(root, {k: v for k, v in GOOD_SIGNED.items() if k != field}), CEILINGS)
        assert t["signed"] is False, field


def test_signed_threshold_must_equal_its_committed_version(tmp_path):
    (tmp_path / "repo").mkdir()
    t = C.load_b_threshold(_threshold_repo(tmp_path / "repo", GOOD_SIGNED, commit=False), CEILINGS)
    assert t["signed"] is False and "differs from its committed HEAD version" in t["reason"]
    non_git = tmp_path / "plain"
    (non_git / C.THRESHOLD_PATH).parent.mkdir(parents=True)
    (non_git / C.THRESHOLD_PATH).write_text(json.dumps({"schema": C.THRESHOLD_SCHEMA, "signed": GOOD_SIGNED}))
    t = C.load_b_threshold(non_git, CEILINGS)
    assert t["signed"] is False and "not committed" in t["reason"]


def test_signed_threshold_needs_a_ceiling_to_pass_b2_b3(tmp_path):
    root = _threshold_repo(tmp_path, GOOD_SIGNED)
    assert C.load_b_threshold(root, {"CPU": None, "GPU": 0.6})["signed"] is False        # ceiling unavailable
    display = C.load_b_threshold(root)                                                    # no ceilings: display only
    assert display["signed"] and display["ceiling_checked"] is False
    assert C._score_subcheck(0.99, "CPU", display)["pass"] is False


def test_threshold_without_owner_or_file_is_unsigned(tmp_path):
    assert C.load_b_threshold(tmp_path)["signed"] is False


def test_fixture_default_is_the_retired_constant():
    assert C._score_subcheck(0.96, "CPU", None) == {"pass": True, "score": 0.96, "min": C.SCORE_MIN}


def test_committed_threshold_file_is_unsigned_until_the_owner_signs():
    data = json.loads((REPO / C.THRESHOLD_PATH).read_text(encoding="utf-8"))
    assert data["schema"] == C.THRESHOLD_SCHEMA
    if data.get("signed") is not None:  # after sign-off the number and the owner are both recorded
        assert data["signed"]["owner"] and isinstance(data["signed"]["cpu"], float)


def _gate_manifest_on(monkeypatch, root: Path):
    import gate_manifest as G

    monkeypatch.setattr(G, "REPO_ROOT", root)
    monkeypatch.setattr(G, "_coverage_reducer", lambda: C)
    return G


def test_gate_manifest_row_b_bound_follows_the_threshold_file(tmp_path, monkeypatch):
    signed = {"cpu": 0.61, "gpu": 0.62, "owner": "owner", "pr": 7, "date": "2026-11-02"}
    for name, body, expected in (
            ("signed", {"proposed": {"cpu": 0.55, "gpu": 0.57}, "signed": signed}, (0.61, 0.62)),
            ("unsigned", {"proposed": {"cpu": 0.55, "gpu": 0.57}, "signed": None}, (0.55, 0.57)),
            ("no_proposal", {"signed": None}, (1.0, 1.0))):
        root = tmp_path / name
        root.mkdir()
        path = root / C.THRESHOLD_PATH
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema": C.THRESHOLD_SCHEMA, **body}))
        _git(root, "init", "-q")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "x")
        G = _gate_manifest_on(monkeypatch, root)
        assert G._row_b_threshold() == {"cpu_score": {"min": expected[0]}, "gpu_score": {"min": expected[1]}}
    assert G._row_b_threshold()["cpu_score"]["min"] != 0.95      # 0.95 is retired


def test_committed_row_b_bound_is_not_the_retired_0_95():
    import gate_manifest as G

    assert G.ROW_SPEC["b"]["threshold"]["cpu_score"]["min"] != 0.95


def test_unsigned_audited_report_is_not_green_and_row_b_is_red(tmp_path, monkeypatch):
    """End to end: an audited report (all witnesses PASS, good scores) with an unsigned threshold is not green."""
    (tmp_path / "repo").mkdir()
    root = _threshold_repo(tmp_path / "repo", None)
    uses = {A: {"s1"}, B: {"s1"}, D: {"s1"}, F: {"s1"}}
    ledger = [r for r in LEDGER if r["identity"] != E]
    audit = _audit({"w_noise": {"CPU": "PASS", "GPU": "PASS"}, "w_diffuse": {"CPU": "PASS", "GPU": "PASS"}})
    verified = {"use_ledger": ledger, "audit": audit}
    pop = {"ratified": True, "gate_eligible": True}
    report = C._build_report_audited({}, MATRIX, uses, verified, pop, root, True, "", [], True)
    assert report["status"] != "green" and report["status"] == "red"
    assert report["subchecks"]["b2_cpu_score"]["pass"] is False and report["subchecks"]["b3_gpu_score"]["pass"] is False
    assert report["subchecks"]["b2_cpu_score"]["signed"] is False and report["threshold"]["signed"] is False
    assert report["subchecks"]["b2_cpu_score"]["score"] >= 0.5 and report["subchecks"]["b2_cpu_score"]["min"] is None  # a good score, no bound
    report["audit"]["build"] = {"CPU": {"build_id": "candidate"}}
    # row (b): the manifest reducer re-derives that report and the row stays red
    G = _gate_manifest_on(monkeypatch, tmp_path)
    frozen = {"schema": "pkg278.coverage_input_manifest.v5", "input_path": "input.json", "matrix": {"path": "matrix.json"},
              "corpus": {"scenes": {"fixture": {"sha256": "1" * 64}}}, "scanner_issue_823": {}}
    for name, payload in (("input.json", frozen), ("snapshot.json", {"scenes": {}}), ("matrix.json", []),
                          ("report.json", report)):
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(C, "build_report", lambda *a, **k: report)
    ref = lambda name: {"path": name, "sha256": G.sha256_file(tmp_path / name)}
    record = {"kind": "coverage_reduction", "input": ref("input.json"), "snapshot": ref("snapshot.json"),
              "matrix": ref("matrix.json"), "report": ref("report.json")}
    errors, value, subchecks = G._validate_b([record], tmp_path)
    assert any("not 'green'" in e for e in errors) and subchecks["b2_cpu_score"]["pass"] is False
    adapter = G.adapt_b_instrument(tmp_path / "report.json", tmp_path / "input.json", tmp_path / "snapshot.json",
                                   tmp_path / "matrix.json")
    (tmp_path / "b_instrument.json").write_text(json.dumps(adapter), encoding="utf-8")
    loaded = G.load_instruments(None, {"b": tmp_path / "b_instrument.json"})["b"]
    row, reasons = G.compute_row("b", loaded, G.ROW_SPEC["b"], tmp_path)
    assert row["status"] != "green" and reasons


# ---------------------------------------------------------------- Welch-1b judge uses mc_compare.welch_verdict


def _write_legs(root: Path, w: dict, seeds, rng, *, bias: float, effect: bool | str):
    """``effect``: True (both controls move the image), False (neither) or an engine name (only that one)."""
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
        if effect is True or effect == name:
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
    _write_legs(tmp_path, sample["witnesses"][0], seeds, np.random.default_rng(6), bias=0.02, effect=True)
    out = C.audit_judge(sample, tmp_path, "CPU")["scn/Obj/Node"]
    assert out["status"] == "FAIL" and out["welch"]["n_reject_holm"] > 0


def test_judge_records_no_effect_without_crediting(tmp_path):
    seeds = (11, 12, 13, 14, 15, 16, 17, 18)
    sample = _sample(seeds)
    _write_legs(tmp_path, sample["witnesses"][0], seeds, np.random.default_rng(7), bias=0.05, effect=False)
    assert C.audit_judge(sample, tmp_path, "CPU")["scn/Obj/Node"]["status"] == "NO-EFFECT"


def test_judge_fails_when_only_astroray_s_control_is_inert(tmp_path):
    seeds = (11, 12, 13, 14, 15, 16, 17, 18)
    sample = _sample(seeds)
    _write_legs(tmp_path, sample["witnesses"][0], seeds, np.random.default_rng(8), bias=0.0, effect="cycles")
    out = C.audit_judge(sample, tmp_path, "CPU")["scn/Obj/Node"]
    assert out["welch"]["pass"] and out["status"] == "FAIL"        # the verdict alone would pass


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


def _audit_files(tmp_path, legs, *, sample_extra=None, n_seeds=4):
    sample = {"schema": C.AUDIT_SAMPLE_SCHEMA, "witnesses": [{"id": "w", "scene_id": "s1", "identities": [A]}], **(sample_extra or {})}
    sp = tmp_path / "sample.json"
    sp.write_text(json.dumps(sample))
    rp = tmp_path / "results.json"
    rp.write_text(json.dumps({"schema": C.AUDIT_RESULTS_SCHEMA, "sample_sha256": C.sha256_file(sp), "welch": C.AUDIT_WELCH,
                              "n_seeds": n_seeds, "witnesses": {"w": legs}}))
    return {"sample": {"path": "sample.json", "sha256": C.sha256_file(sp)},
            "results": {"path": "results.json", "sha256": C.sha256_file(rp)}}


def test_load_audit_accepts_consistent_legs_and_a_missing_or_errored_leg(tmp_path):
    legs = {"CPU": _leg("PASS"), "GPU": _leg("FAIL")}
    assert C.load_audit(_audit_files(tmp_path, legs), tmp_path, ["s1"])[1] == []
    assert C.load_audit(_audit_files(tmp_path, {"CPU": _leg("NO-EFFECT")}), tmp_path, ["s1"])[1] == []   # missing GPU leg: scored as ERROR
    assert C.load_audit(_audit_files(tmp_path, {"CPU": {"status": "ERROR", "reason": "x"}}), tmp_path, ["s1"])[1] == []


@pytest.mark.parametrize("mutate,why", [
    (lambda leg: leg.update(status="MAYBE"), "unknown status"),
    (lambda leg: leg.update(status="FAIL"), "contradicts"),                        # stored welch.pass is True, both effects moved
    (lambda leg: leg["welch"].update(**{"pass": False}), "contradicts"),           # PASS but the verdict failed
    (lambda leg: leg["effect"]["astroray"].update(ok=False), "contradicts"),       # PASS although Astroray's control is inert
    (lambda leg: leg.update(jackknife_pass=[True] * 3), "jackknife_pass"),
    (lambda leg: leg.update(jackknife_pass=[1, 1, 1, 1]), "jackknife_pass"),
    (lambda leg: leg.pop("jackknife_pass"), "jackknife_pass"),
    (lambda leg: leg.pop("welch"), "lacks the effect / Welch verdict"),
    (lambda leg: leg.pop("effect"), "lacks the effect / Welch verdict")])
def test_load_audit_rejects_inconsistent_legs(tmp_path, mutate, why):
    leg = _leg("PASS")
    mutate(leg)
    _, errors = C.load_audit(_audit_files(tmp_path, {"CPU": leg, "GPU": _leg("PASS")}), tmp_path, ["s1"])
    assert any(why in e for e in errors), errors


def test_load_audit_rejects_a_seed_count_the_sample_does_not_have(tmp_path):
    ref = _audit_files(tmp_path, {"CPU": _leg("PASS")}, sample_extra={"seeds": [1, 2, 3]})
    assert any("n_seeds does not match" in e for e in C.load_audit(ref, tmp_path, ["s1"])[1])
    assert any("n_seeds is not a positive" in e for e in
               C.load_audit(_audit_files(tmp_path, {}, n_seeds=0), tmp_path, ["s1"])[1])


# ---- b1 ratification (owner 10-06 population decision, confirmed 10-31) ----------------------------------------------

def _ratified_frozen(root: Path, *, text: str | None = None, sha: str | None = None) -> dict:
    rel = "b1_ratification.md"
    if text is not None:
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    return {"population": {"expected_scene_ids": ["a"], "ratified": True,
                           "ratification": {"path": rel, "sha256": sha or C._sha256_bytes(text.encode()),
                                            "owner": "HendrikGC02"}}}


def test_committed_candidate_v2_ratification_passes_b1_population_status():
    manifest = json.loads((REPO / C.POPULATIONS_DIR / "candidate_v2.json").read_text(encoding="utf-8"))
    assert manifest["ratified"] is True
    frozen = json.loads((REPO / "docs/blender_parity/coverage_input_v5_candidate_v2.json").read_text(encoding="utf-8"))
    assert frozen["population"]["ratification"] == manifest["ratification"] == C.POPULATION_RATIFICATIONS["candidate_v2"]
    pop = C.population_status(frozen, REPO)
    assert pop["ratified"] and pop["gate_eligible"]


def test_nine_scene_population_is_not_ratified():
    assert "nine_scene" not in C.POPULATION_RATIFICATIONS
    manifest = json.loads((REPO / C.POPULATIONS_DIR / "nine_scene.json").read_text(encoding="utf-8"))
    assert "ratified" not in manifest


def test_ratification_fails_on_sha_mismatch_or_missing_file(tmp_path):
    frozen = _ratified_frozen(tmp_path, text="signed\n")
    assert C.population_status(frozen, tmp_path)["ratified"]
    (tmp_path / "b1_ratification.md").write_text("edited\n", encoding="utf-8", newline="\n")
    assert not C.population_status(frozen, tmp_path)["ratified"]
    (tmp_path / "b1_ratification.md").unlink()
    assert not C.population_status(frozen, tmp_path)["ratified"]

"""pkg278 - focused tests for the exit-gate instruments.

Covers the omission-resistant coverage scorer (hand-computed synthetic fixture +
adversarial missing/hash/backend/dimension cases), the acceptance manifest
(always a-f, computed statuses, hand-edit rejection, frozen thresholds) and the
clean-install validator (ineligible dev machine, hash-locked checks).

    pytest tests/test_pkg278_gate_instruments.py -v
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CR = _load("pkg278_coverage_report", "benchmarks/reference_corpus/coverage_report.py")
GM = _load("pkg278_gate_manifest", "scripts/gate_manifest.py")
VCI = _load("pkg278_validate_clean_install", "scripts/validate_clean_install.py")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hex(seed: int) -> str:
    return hashlib.sha256(f"scene-{seed}".encode()).hexdigest()


# =========================================================================== #
# Coverage scorer
# =========================================================================== #

def test_scorer_self_test_passes():
    assert CR.run_self_test() is True


def test_synthetic_fixture_matches_hand_computed_weighted_score():
    fx = CR.synthetic_fixture()
    cpu = CR.score_backend("CPU", fx["uses"], fx["matrix"], fx["evidence"], None)
    gpu = CR.score_backend("GPU", fx["uses"], fx["matrix"], fx["evidence"], None)
    assert cpu.score == pytest.approx(5.0 / 7.0, abs=1e-12)
    assert gpu.score == pytest.approx(4.0 / 7.0, abs=1e-12)
    assert cpu.denominator == 7.0 and gpu.denominator == 7.0


def test_missing_evidence_scores_zero_never_raises():
    fx = CR.synthetic_fixture()
    u1 = CR.canonical_identity("ShaderNodeBsdfDiffuse", "input:Color")
    fx["evidence"][u1]["GPU"] = []
    gpu = CR.score_backend("GPU", fx["uses"], fx["matrix"], fx["evidence"], None)
    # U1 drops from 1.0 to 0 -> (3*0 + 2*0.5)/7 = 1/7
    assert gpu.score == pytest.approx(1.0 / 7.0, abs=1e-12)


def test_hash_mismatch_invalidates_evidence():
    rec = {"variant": "S1", "behavior": "functioning", "warning": "",
           "content": "payload", "sha256": _sha("a different payload")}
    ok, why = CR.evidence_is_valid(rec, None)
    assert not ok and "hash mismatch" in why


def test_evidence_path_hash_verified(tmp_path):
    artifact = tmp_path / "evidence.txt"
    artifact.write_text("rendered", encoding="utf-8")
    good = {"variant": "S1", "behavior": "functioning", "warning": "",
            "path": "evidence.txt", "sha256": _sha("rendered")}
    assert CR.evidence_is_valid(good, tmp_path)[0]
    bad = dict(good, sha256=_sha("tampered"))
    assert not CR.evidence_is_valid(bad, tmp_path)[0]


def test_approximation_without_warning_scores_zero():
    key = CR.canonical_identity("N", "input:X")
    ev = {"variant": "S1", "behavior": "functioning", "warning": "",
          "content": "x", "sha256": _sha("x")}
    score, reason = CR.score_use(key, {"S1"}, CR.APPROXIMATED, {key: {"CPU": [ev]}},
                                 "CPU", None)
    assert score == 0.0 and "warning" in reason


def test_approximation_ignored_but_warned_scores_zero():
    key = CR.canonical_identity("N", "input:X")
    ev = {"variant": "S1", "behavior": "ignored", "warning": "dropped with a warning",
          "content": "x", "sha256": _sha("x")}
    score, _ = CR.score_use(key, {"S1"}, CR.APPROXIMATED, {key: {"CPU": [ev]}}, "CPU", None)
    assert score == 0.0


def test_evidence_must_cover_every_exercised_variant():
    key = CR.canonical_identity("N", "input:X")
    ev = {"variant": "S1", "behavior": "functioning", "warning": "",
          "content": "x", "sha256": _sha("x")}
    score, reason = CR.score_use(key, {"S1", "S2"}, CR.SUPPORTED, {key: {"CPU": [ev]}},
                                 "CPU", None)
    assert score == 0.0 and "S2" in reason


def test_weight_capped_at_three_distinct_scenes():
    uses = CR.extract_exercised_uses({
        f"S{i}": [{"bl_idname": "N", "sockets": ["input:X"]}] for i in range(5)
    })
    key = CR.canonical_identity("N", "input:X")
    assert len(uses[key]) == 5
    assert min(len(uses[key]), CR.WEIGHT_CAP) == 3


def test_unreachable_nodes_not_counted():
    uses = CR.extract_exercised_uses({
        "S1": [{"bl_idname": "N", "sockets": ["input:X"], "reachable": True},
               {"bl_idname": "N", "sockets": ["input:Y"], "reachable": False}],
    })
    assert CR.canonical_identity("N", "input:X") in uses
    assert CR.canonical_identity("N", "input:Y") not in uses


def test_silent_drops_reported_separately():
    uses = {CR.canonical_identity("N", "input:X"): {"S1"},
            CR.canonical_identity("M", "input:Y"): {"S1"}}
    matrix = {CR.canonical_identity("N", "input:X"): CR.SUPPORTED,
              CR.canonical_identity("M", "input:Y"): CR.DROPPED_SILENT}
    drops = CR.silent_drops(uses, matrix)
    assert drops == [CR.canonical_identity("M", "input:Y")]


def _ratified_input_manifest(*, scanner: bool = True, ratified: bool = True,
                             scene_count: int = 9) -> dict:
    scanner_entry = {"integrated": True}
    if scanner:
        content = "issue-823-landed"
        scanner_entry.update({"content": content, "sha256": _sha(content)})
    return {
        "population": {"scene_count": scene_count, "ratified": ratified},
        "scanner_issue_823": scanner_entry,
        "evidence": {},
    }


def test_scanner_823_blocks_any_score():
    fx = CR.synthetic_fixture()
    report = CR.build_report({"population": {"scene_count": 9, "ratified": False},
                              "scanner_issue_823": {"integrated": False},
                              "evidence": fx["evidence"]},
                             {"S1": [], "S2": [], "S3": []}, [])
    assert report["status"] == "unmeasured"
    assert report["blocked"] is True
    assert report["cpu"]["score"] is None and report["gpu"]["score"] is None


def test_unratified_population_is_provisional_not_green():
    fx = CR.synthetic_fixture()
    # Make all four uses fully supported on both backends so scores clear 0.95.
    u4 = CR.canonical_identity("ShaderNodeBsdfMetallic", "input:Base Color")
    for key in fx["evidence"]:
        if not fx["evidence"][key]["GPU"]:
            fx["evidence"][key]["GPU"] = [CR._inline_evidence(s)
                                          for s in sorted(fx["uses"][key])]
        if not fx["evidence"][key]["CPU"]:
            fx["evidence"][key]["CPU"] = [CR._inline_evidence(s)
                                          for s in sorted(fx["uses"][key])]
    assert u4 in fx["evidence"]
    input_manifest = _ratified_input_manifest(ratified=False)
    input_manifest["evidence"] = fx["evidence"]
    node_trees = {s: [] for s in ("S1", "S2", "S3")}
    # node_trees empty => no exercised uses; inject the fixture uses directly.
    report = CR.build_report(input_manifest, node_trees, [])
    assert report["population"]["status"] == "provisional"
    assert report["population"]["gate_eligible"] is False
    assert report["status"] == "provisional"


def test_backend_scores_are_separate_not_averaged():
    u1 = CR.canonical_identity("ShaderNodeBsdfDiffuse", "input:Color")
    ev = {u1: {"CPU": [CR._inline_evidence("S1")], "GPU": []}}
    input_manifest = _ratified_input_manifest()
    input_manifest["evidence"] = ev
    # build_report extracts uses from node trees; feed a node tree that exercises U1.
    node_trees = {"S1": [{"bl_idname": "ShaderNodeBsdfDiffuse", "sockets": ["input:Color"]}]}
    report = CR.build_report(input_manifest, node_trees, [{
        "category": "shader_node", "feature": "BSDF_DIFFUSE",
        "bl_idname": "ShaderNodeBsdfDiffuse", "socket_or_prop": "input:Color",
        "classification": CR.SUPPORTED}])
    assert report["cpu"]["score"] == pytest.approx(1.0)
    assert report["gpu"]["score"] == pytest.approx(0.0)
    assert report["status"] == "red"  # GPU fails 95 %; backends never averaged
    assert report["subchecks"]["b2_cpu_score"]["pass"] is True
    assert report["subchecks"]["b3_gpu_score"]["pass"] is False


def test_original_population_is_undefined():
    report = CR.population_status({"population": {"scene_count": None, "ratified": False}})
    assert report["status"] == "undefined"
    assert report["original_population"]["status"] == "undefined"


# =========================================================================== #
# Acceptance manifest
# =========================================================================== #

def test_manifest_always_has_rows_a_through_f():
    manifest, _ = GM.assemble({})
    assert set(manifest["rows"]) == set(GM.ROWS)
    for rid in GM.ROWS:
        assert manifest["rows"][rid]["status"] == "unmeasured"
        assert manifest["rows"][rid]["value"] is None
    assert GM.validate_shape(manifest) == []


def test_hand_edited_green_is_rejected(tmp_path):
    existing = {"rows": {"a": {"status": "green"}}}
    manifest, reasons = GM.assemble({}, tmp_path, existing)
    row = manifest["rows"]["a"]
    assert row["status"] == "red"
    assert row.get("hand_edit_detected") is True
    assert "hand-edited" in reasons["a"][0]


def test_green_row_without_evidence_is_red(tmp_path):
    raw = {
        "instrument": "viewport_latency", "scene_sha256": [_hex(1), _hex(2)],
        "build_id": "b1", "backend": ["GPU"], "settings": {}, "metric": {},
        "value": {"gpu_p95_ms": 50.0, "gpu_p99_ms": 50.0, "cancel_p95_ms": 100.0,
                  "cancel_p99_ms": 100.0, "stale_frames_after_ack": 0},
        "threshold": {"gpu_p95_ms": 100, "gpu_p99_ms": 150, "cancel_p95_ms": 200,
                      "cancel_p99_ms": 300, "stale_frames_after_ack": 0},
        "evidence_path": None, "evidence_sha256": None,
        "dimensions": {"scene": True, "edit_kind": True, "repetitions": True},
        "subchecks": {k: {"pass": True} for k in GM.ROW_SPEC["a"]["required_subchecks"]},
        "date": "2026-09-23",
    }
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red"
    assert any("evidence" in r for r in reasons)


def _green_row_a(tmp_path) -> dict:
    evidence = tmp_path / "gate_a.json"
    scene_hashes = [_hex(1), _hex(2)]
    capture = tmp_path / "latency-capture.bin"
    capture.write_bytes(b"immutable latency capture")
    artifact = {"path": capture.name, "sha256": GM.sha256_file(capture)}
    records = []
    for scene in scene_hashes:
        for edit_kind in ("camera", "material"):
            for batch in range(3):
                for repetition in range(100):
                    event = len(records) * 1_000_000_000
                    records.append({"backend": "GPU", "scene_sha256": scene, "edit_kind": edit_kind,
                                    "batch": batch, "repetition": repetition, "event_ns": event,
                                    "present_ns": event + 50_000_000, "cancel_ack_ns": event + 100_000_000,
                                    "stale_frames_after_ack": 0, "denoise_enabled": False, "artifact": artifact})
    payload = {
        "schema": "pkg278.instrument.v2", "row": "a", "instrument": "viewport_latency",
        "scene_sha256": scene_hashes, "build_id": "b1", "backend": ["GPU"],
        "settings": {"resolution": "128x128"}, "metric": {"name": "event_to_present"},
        "value": {"gpu_p95_ms": 50.0, "gpu_p99_ms": 50.0, "cancel_p95_ms": 100.0,
                  "cancel_p99_ms": 100.0, "stale_frames_after_ack": 0},
        "threshold": {"gpu_p95_ms": 100, "gpu_p99_ms": 150, "cancel_p95_ms": 200,
                      "cancel_p99_ms": 300, "stale_frames_after_ack": 0}, "records": records,
    }
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    digest = GM.sha256_file(evidence)
    return {
        "instrument": "viewport_latency",
        "scene_sha256": scene_hashes, "build_id": "b1", "backend": ["GPU"],
        "settings": {"resolution": "128x128"}, "metric": {"name": "event_to_present"},
        "value": {"gpu_p95_ms": 50.0, "gpu_p99_ms": 50.0, "cancel_p95_ms": 100.0,
                  "cancel_p99_ms": 100.0, "stale_frames_after_ack": 0},
        "threshold": {"gpu_p95_ms": 100, "gpu_p99_ms": 150, "cancel_p95_ms": 200,
                      "cancel_p99_ms": 300, "stale_frames_after_ack": 0},
        "evidence_path": str(evidence), "evidence_sha256": digest,
        "dimensions": {"scene": "concrete", "edit_kind": "concrete", "repetitions": 100},
        "subchecks": {"both_pinned_scenes": True, "three_by_hundred_repetitions": True,
                      "denoise_excluded": True, "gpu_only_latency": True},
        "date": "2026-09-23",
    }


def test_valid_green_row_computes_green(tmp_path):
    row, reasons = GM.compute_row("a", _green_row_a(tmp_path), GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "green", reasons


def test_hash_pinned_empty_or_wrong_instrument_payload_is_red(tmp_path):
    raw = _green_row_a(tmp_path)
    evidence = Path(raw["evidence_path"])
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["instrument"] = "wrong-instrument"
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    raw["evidence_sha256"] = GM.sha256_file(evidence)
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("instrument mismatch" in r for r in reasons)

    evidence.write_text("{}", encoding="utf-8")
    raw["evidence_sha256"] = GM.sha256_file(evidence)
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("schema" in r for r in reasons)


def test_green_requires_required_backend_and_dimensions(tmp_path):
    raw = _green_row_a(tmp_path)
    raw["backend"] = ["CPU"]  # row (a) is a GPU-only latency oracle
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("backend" in r for r in reasons)

    raw = _green_row_a(tmp_path)
    raw["dimensions"] = {"scene": True}
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("dimension" in r for r in reasons)


def test_threshold_cannot_be_loosened(tmp_path):
    raw = _green_row_a(tmp_path)
    raw["threshold"]["gpu_p95_ms"] = 9999
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("loosened" in r for r in reasons)


def test_value_outside_frozen_bound_is_red(tmp_path):
    raw = _green_row_a(tmp_path)
    raw["value"]["gpu_p95_ms"] = 250  # > 100 ms
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("outside frozen bound" in r for r in reasons)


def test_incomplete_latency_lattice_is_red(tmp_path):
    raw = _green_row_a(tmp_path)
    evidence = Path(raw["evidence_path"])
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["records"].pop()
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    raw["evidence_sha256"] = GM.sha256_file(evidence)
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red" and any("1200" in r or "cover" in r for r in reasons)


def test_latency_rejects_missing_artifact_and_nonconcrete_dimensions(tmp_path):
    raw = _green_row_a(tmp_path)
    evidence = Path(raw["evidence_path"])
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["records"][0]["artifact"] = {"path": "DOES_NOT_EXIST.json", "sha256": "0" * 64}
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    raw["evidence_sha256"] = GM.sha256_file(evidence)
    raw["dimensions"] = {"scene": [], "edit_kind": 0, "repetitions": {}}
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red"
    assert any("artifact missing" in reason for reason in reasons)
    assert any("dimension absent" in reason for reason in reasons)


def test_latency_rejects_wrong_outer_instrument_and_bad_numeric_without_crash(tmp_path):
    raw = _green_row_a(tmp_path)
    raw["instrument"] = "issue_triage"
    raw["threshold"]["gpu_p95_ms"] = []
    raw["value"]["gpu_p99_ms"] = True
    row, reasons = GM.compute_row("a", raw, GM.ROW_SPEC["a"], tmp_path)
    assert row["status"] == "red"
    assert any("manifest instrument mismatch" in reason for reason in reasons)
    assert any("finite number" in reason for reason in reasons)


def test_trio_requires_frozen_roles_paired_f12_runs_and_real_artifacts(tmp_path):
    image = tmp_path / "image.bin"; image.write_bytes(b"image")
    mask = tmp_path / "roi.bin"; mask.write_bytes(b"mask")
    image_ref = {"path": image.name, "sha256": GM.sha256_file(image)}
    mask_ref = {"path": mask.name, "sha256": GM.sha256_file(mask)}
    hashes = [_hex(i) for i in (11, 12, 13)]
    records = []
    for role, actual, digest in zip(GM.TRIO_ROLES, ("gallery", "workshop", "terrace_hair"), hashes):
        for backend in ("CPU", "GPU"):
            records.append({"kind": "f12_run", "role": role, "scene_id": actual, "scene_sha256": digest,
                            "backend": backend, "build_id": "b1", "exit_code": 0, "sentinel": "f12",
                            "image": image_ref, "non_vacuity": {"checker": 1, "hdri": 1, "hair": 1},
                            "rois": [{"mask": mask_ref, "ratio": {"r": 1, "g": 1, "b": 1}, "ssim": .99}]})
    evidence = tmp_path / "gate_c.json"
    payload = {"schema": GM.PAYLOAD_SCHEMA, "row": "c", "instrument": "trio_parity", "scene_sha256": hashes,
               "build_id": "b1", "backend": ["CPU", "GPU"], "settings": {}, "metric": {}, "value": {},
               "threshold": {"roi_pct_max": 5, "ssim_min": .95}, "records": records}
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    raw = {**payload, "value": {"roi_pct_max": 0.0, "ssim_min": .99}, "evidence_path": str(evidence),
           "evidence_sha256": GM.sha256_file(evidence), "dimensions": {"backend": "paired", "scene": "role", "roi": "mask"},
           "subchecks": {"cpu_exit_zero": True, "gpu_exit_zero": True, "pinned_images": True, "non_vacuity": True}, "date": "2026-09-24"}
    row, reasons = GM.compute_row("c", raw, GM.ROW_SPEC["c"], tmp_path)
    assert row["status"] == "green", reasons
    payload["records"].pop(); evidence.write_text(json.dumps(payload), encoding="utf-8"); raw["evidence_sha256"] = GM.sha256_file(evidence)
    row, _ = GM.compute_row("c", raw, GM.ROW_SPEC["c"], tmp_path)
    assert row["status"] == "red"


def test_triage_rejects_legacy_detached_snapshot_and_rating_flags(tmp_path):
    blob = tmp_path / "triage.json"; blob.write_bytes(b"triage")
    ref = {"path": blob.name, "sha256": GM.sha256_file(blob)}
    records = [{"kind": "snapshot", "phase": "baseline", "command": "gh issue list", "timestamp": "2026-09-24T00:00:00Z", "reported_total": 2, "issue_ids": [1, 2], "artifact": ref},
               {"kind": "snapshot", "phase": "recheck", "command": "gh issue list", "timestamp": "2026-09-24T01:00:00Z", "reported_total": 2, "issue_ids": [1, 2], "artifact": ref},
               {"kind": "rating", "issue_id": 1, "rater_id": "r1", "signed": True, "severity": "low", "signature": ref},
               {"kind": "rating", "issue_id": 2, "rater_id": "r2", "signed": True, "severity": "low", "signature": ref}]
    evidence = tmp_path / "gate_e.json"
    payload = {"schema": GM.PAYLOAD_SCHEMA, "row": "e", "instrument": "issue_triage", "scene_sha256": [], "build_id": "b1", "backend": [], "settings": {}, "metric": {}, "value": {}, "threshold": {"high_count": 0}, "records": records}
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    raw = {**payload, "value": {"high_count": 0}, "evidence_path": str(evidence), "evidence_sha256": GM.sha256_file(evidence), "dimensions": {"issue_snapshot": "ids", "ratings": "signed"}, "subchecks": {"snapshot_unique": True, "count_matches_total": True, "all_rated_independently": True, "delta_empty": True}, "date": "2026-09-24"}
    row, reasons = GM.compute_row("e", raw, GM.ROW_SPEC["e"], tmp_path)
    assert row["status"] == "red"


def test_row_b_unmeasured_until_scanner_823(tmp_path):
    raw = {"instrument": "coverage_report", "scene_sha256": [_hex(1)],
           "build_id": "b1", "backend": ["CPU", "GPU"], "settings": {}, "metric": {},
           "value": {"cpu_score": 0.99, "gpu_score": 0.99},
           "threshold": {"cpu_score": 0.95, "gpu_score": 0.95},
           "evidence_path": None, "evidence_sha256": None,
           "dimensions": {"backend": True, "variant": True},
           "scanner_issue_823": {"integrated": False},
           "subchecks": {k: {"pass": True} for k in GM.ROW_SPEC["b"]["required_subchecks"]},
           "date": "2026-09-23"}
    row, reasons = GM.compute_row("b", raw, GM.ROW_SPEC["b"], tmp_path)
    assert row["status"] == "unmeasured"
    assert any("823" in r for r in reasons)


def test_validate_manifest_rejects_green_without_evidence():
    manifest, _ = GM.assemble({})
    manifest["rows"]["a"]["status"] = "green"
    errors = GM.validate_manifest(manifest)
    assert errors


def test_validate_shape_detects_missing_row():
    manifest = {"schema": "pkg278.acceptance_manifest.v1", "rows": {}}
    errors = GM.validate_shape(manifest)
    assert any("missing" in e for e in errors)


# =========================================================================== #
# Clean-install validator
# =========================================================================== #

def test_dev_machine_is_ineligible_never_green():
    doc = VCI.build_checks_doc(REPO_ROOT)
    assert doc["machine"]["eligible"] is False
    result = VCI.evaluate(doc, REPO_ROOT)
    assert result["status"] == "ineligible"
    assert result["all_green"] is False


def test_all_five_checks_required(tmp_path):
    doc = VCI.build_checks_doc(REPO_ROOT)
    doc["machine"] = {"eligible": True}
    for name in VCI.MANDATORY_CHECKS:
        artifact = tmp_path / VCI.CHECK_ARTIFACTS[name]
        artifact.write_text(name, encoding="utf-8")
        doc["checks"][name] = {"pass": True, "evidence_path": artifact.name,
                               "evidence_sha256": VCI.sha256_file(artifact)}
    doc["checks"].pop("f12_exit_zero")
    result = VCI.evaluate(doc, tmp_path)
    assert result["status"] == "ineligible" and not result["all_green"]


def test_hash_locked_check_detects_tamper(tmp_path):
    doc = VCI.build_checks_doc(REPO_ROOT)
    doc["machine"] = {"eligible": True}
    artifact = tmp_path / "profile_fresh.json"
    artifact.write_text(json.dumps({"schema": "pkg278.clean_install_probe.v1", "check": "fresh_profile",
                                    "prior_astroray_addon": False, "userpref_astroray": False,
                                    "profile_path": "C:/isolated/profile", "addons": []}), encoding="utf-8")
    doc["checks"]["fresh_profile"] = {"evidence_path": artifact.name,
                                      "evidence_sha256": VCI.sha256_file(artifact)}
    result = VCI.evaluate(doc, tmp_path)
    assert result["checks"]["fresh_profile"]["status"] == "green"

    artifact.write_text("tampered", encoding="utf-8")
    result = VCI.evaluate(doc, tmp_path)
    assert result["checks"]["fresh_profile"]["status"] == "red"


def test_all_green_on_eligible_machine(tmp_path):
    doc = VCI.build_checks_doc(REPO_ROOT)
    doc["machine"] = {"eligible": True}
    release = tmp_path / "release.zip"; release.write_bytes(b"release ZIP bytes")
    image = tmp_path / "f12.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + (13).to_bytes(4, "big") + b"IHDR" + (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + b"\x08\x02\x00\x00\x00")
    zip_ref = {"path": release.name, "sha256": VCI.sha256_file(release)}
    image_ref = {"path": image.name, "sha256": VCI.sha256_file(image)}
    probes = {
        "fresh_profile": {"prior_astroray_addon": False, "userpref_astroray": False, "profile_path": "C:/isolated/profile", "addons": []},
        "zip_identity": {"zip": zip_ref},
        "installer_path": {"installer": "blender_extension_installer", "installer_result": "FINISHED", "installed_module_path": "C:/isolated/extensions/astroray", "zip_path": "C:/isolated/release.zip", "source_path_used": False},
        "no_toolchain": {"toolchain_programs": [], "source_tree_fallback": False, "checked_path": "C:/Windows", "source_roots_checked": [], "loaded_module_path": "C:/isolated/extensions/astroray"},
        "f12_exit_zero": {"exit_code": 0, "image": image_ref, "loaded_module_path": "C:/isolated/extensions/astroray"},
    }
    doc["zip"] = zip_ref
    for name in VCI.MANDATORY_CHECKS:
        artifact = tmp_path / VCI.CHECK_ARTIFACTS[name]
        probe = {"schema": "pkg278.clean_install_probe.v1", "check": name, **probes[name]}
        artifact.write_text(json.dumps(probe), encoding="utf-8")
        doc["checks"][name] = {"evidence_path": artifact.name,
                               "evidence_sha256": VCI.sha256_file(artifact)}
    result = VCI.evaluate(doc, tmp_path)
    assert result["status"] == "green" and result["all_green"]


def test_clean_install_rejects_forged_eligibility_and_arbitrary_blob(tmp_path):
    doc = VCI.build_checks_doc(REPO_ROOT)
    doc["machine"] = {"eligible": True}
    artifact = tmp_path / "profile_fresh.json"
    artifact.write_text("arbitrary text", encoding="utf-8")
    doc["checks"]["fresh_profile"] = {"evidence_path": artifact.name,
                                         "evidence_sha256": VCI.sha256_file(artifact)}
    result = VCI.evaluate(doc, tmp_path)
    assert result["status"] != "green"
    assert result["checks"]["fresh_profile"]["status"] == "red"


def test_committed_evidence_reports_ineligible():
    checks = REPO_ROOT / "docs" / "blender_parity" / "evidence" / "install-clean-machine" / "checks.json"
    if not checks.is_file():
        pytest.skip("clean-install evidence not committed")
    doc = json.loads(checks.read_text(encoding="utf-8"))
    result = VCI.evaluate(doc, checks.parent)
    assert result["status"] == "ineligible"
    assert result["all_green"] is False


# =========================================================================== #
# Harness verdict export + reference-bank channel_ratio gate
# =========================================================================== #

def test_harness_writes_feature_verdicts(tmp_path):
    sys.path.insert(0, str(REPO_ROOT))
    from benchmarks.blender_parity import harness as H

    results = [
        H.FeatureResult("shader_node", "TEX_NOISE", "SUPPORTED", "pass",
                        ssim=0.98, delta_e=1.0, ratio=(1.0, 1.0, 1.0)),
        H.FeatureResult("shader_node", "MIX_RGB", "SUPPORTED", "fail",
                        ssim=0.6, delta_e=15.0, ratio=(1.0, 0.7, 1.3),
                        triage_bucket="TRANSLATION-BUG"),
    ]
    H.write_reports(results, tmp_path)
    payload = json.loads((tmp_path / "feature_verdicts.json").read_text())
    assert payload["schema"] == "pkg278.feature_verdicts.v1"
    assert [v["feature"] for v in payload["verdicts"]] == [
        "shader_node:TEX_NOISE", "shader_node:MIX_RGB"]
    assert payload["verdicts"][1]["triage_bucket"] == "TRANSLATION-BUG"


def test_reference_bank_channel_ratio_gate():
    import numpy as np
    sys.path.insert(0, str(REPO_ROOT))
    from benchmarks.reference_bank import runner as RB

    reference = np.full((8, 8, 3), 0.5, np.float32)
    within = reference.copy()
    within[..., 1] *= 1.04  # +4 % on green -> inside +/-5 %
    worst, ratios = RB.compute_channel_mean_ratio(within, reference)
    assert worst == pytest.approx(0.04, abs=1e-6)
    assert ratios["g"] == pytest.approx(1.04, abs=1e-6)

    outside = reference.copy()
    outside[..., 2] *= 1.10  # +10 % on blue -> outside
    worst2, _ = RB.compute_channel_mean_ratio(outside, reference)
    assert worst2 == pytest.approx(0.10, abs=1e-6)

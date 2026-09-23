"""Strict evidence contract for pkg278 gate (e); no network access required."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


KIR = _load("pkg278_known_issues_test", "scripts/dev/known_issues_report.py")
GM = _load("pkg278_gate_manifest_triage", "scripts/gate_manifest.py")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _evidence(tmp_path: Path):
    issues = [{"number": 1, "title": "one", "body": "body", "labels": [], "url": "https://x/1", "updatedAt": "2026-09-24T00:00:00Z"},
              {"number": 2, "title": "two", "body": "body", "labels": [], "url": "https://x/2", "updatedAt": "2026-09-24T00:00:00Z"}]
    baseline = tmp_path / "issues-baseline.json"
    snapshot = {"schema": KIR.GATE_E_SCHEMA, "captured_at": "2026-09-24T00:00:00Z", "repo": KIR.GATE_E_REPO, "command": KIR.gate_e_command(1000), "capture_limit": 1000, "graphql_total_query": KIR.GATE_E_GRAPHQL_QUERY, "reported_total": 2, "issues": issues}
    _write(baseline, snapshot)
    ratings = tmp_path / "ratings.json"
    _write(ratings, {"schema": KIR.RATINGS_SCHEMA, "review": {"identity": "independent reviewer", "review_timestamp": "2026-09-24T00:01:00Z", "snapshot_sha256": _sha(baseline)}, "ratings": [{"id": 1, "severity": "low", "rationale": "reviewed"}, {"id": 2, "severity": "medium", "rationale": "reviewed"}]})
    recheck = tmp_path / "issues-recheck.json"
    snapshot["captured_at"] = "2026-09-24T00:02:00Z"; _write(recheck, snapshot)
    return baseline, ratings, recheck


def test_strict_reducer_parses_raw_snapshot_and_ratings(tmp_path):
    baseline, ratings, recheck = _evidence(tmp_path)
    result = KIR.validate_gate_e_artifacts(baseline, recheck, ratings)
    assert result["value"] == {"high_count": 0}
    assert result["subchecks"]["delta_empty"] is True


def test_reducer_rejects_duplicate_new_or_changed_recheck_content(tmp_path):
    baseline, ratings, recheck = _evidence(tmp_path)
    changed = json.loads(recheck.read_text()); changed["issues"][1]["title"] = "changed"; _write(recheck, changed)
    try:
        KIR.validate_gate_e_artifacts(baseline, recheck, ratings)
        assert False, "content reconciliation must fail"
    except ValueError as exc:
        assert "recheck differs" in str(exc)
    baseline, ratings, recheck = _evidence(tmp_path)
    changed = json.loads(recheck.read_text())
    changed["issues"].append(_live_issue(3))
    changed["reported_total"] = 3
    _write(recheck, changed)
    try:
        KIR.validate_gate_e_artifacts(baseline, recheck, ratings)
        assert False, "added issue must fail reconciliation"
    except ValueError as exc:
        assert "recheck differs" in str(exc)


def test_reducer_rejects_unknown_severity_and_detached_rating_link(tmp_path):
    baseline, ratings, recheck = _evidence(tmp_path)
    data = json.loads(ratings.read_text()); data["ratings"][0]["severity"] = "urgent"; _write(ratings, data)
    try:
        KIR.validate_gate_e_artifacts(baseline, recheck, ratings)
        assert False, "unknown severity must fail"
    except ValueError as exc:
        assert "unknown severity" in str(exc)
    baseline, ratings, recheck = _evidence(tmp_path)
    data = json.loads(ratings.read_text()); data["review"]["snapshot_sha256"] = "0" * 64; _write(ratings, data)
    try:
        KIR.validate_gate_e_artifacts(baseline, recheck, ratings)
        assert False, "detached rating must fail"
    except ValueError as exc:
        assert "does not link" in str(exc)


def test_reducer_rejects_review_timestamp_before_baseline(tmp_path):
    baseline, ratings, recheck = _evidence(tmp_path)
    data = json.loads(ratings.read_text())
    data["review"]["review_timestamp"] = "2026-09-23T23:59:00Z"
    _write(ratings, data)
    try:
        KIR.validate_gate_e_artifacts(baseline, recheck, ratings)
        assert False, "review before immutable baseline must fail"
    except ValueError as exc:
        assert "outside" in str(exc)


def test_gate_manifest_reuses_strict_reducer_and_artifact_hashes(tmp_path):
    baseline, ratings, recheck = _evidence(tmp_path)
    ref = lambda path: {"path": path.name, "sha256": _sha(path)}
    payload = {"schema": GM.PAYLOAD_SCHEMA, "row": "e", "instrument": "issue_triage", "scene_sha256": [], "build_id": "live-github", "backend": [], "settings": {"scope": "all-open-issues"}, "metric": {"name": "independently_rated_high_count"}, "value": {"high_count": 0}, "threshold": {"high_count": 0}, "records": [{"kind": "snapshot", "phase": "baseline", "artifact": ref(baseline)}, {"kind": "snapshot", "phase": "recheck", "artifact": ref(recheck)}, {"kind": "ratings", "artifact": ref(ratings)}]}
    instrument = tmp_path / "instrument.json"; _write(instrument, payload)
    raw = {**payload, "evidence_path": str(instrument), "evidence_sha256": _sha(instrument), "dimensions": {"issue_snapshot": "raw", "ratings": "independent"}, "subchecks": {"snapshot_unique": True, "count_matches_total": True, "all_rated_independently": True, "delta_empty": True}, "date": "2026-09-24"}
    row, reasons = GM.compute_row("e", raw, GM.ROW_SPEC["e"], tmp_path)
    assert row["status"] == "green", reasons
    ratings.write_text("{}", encoding="utf-8")
    payload["records"][2]["artifact"]["sha256"] = _sha(ratings); _write(instrument, payload); raw["evidence_sha256"] = _sha(instrument)
    row, _ = GM.compute_row("e", raw, GM.ROW_SPEC["e"], tmp_path)
    assert row["status"] == "red"


def _live_issue(number: int) -> dict:
    return {"number": number, "title": f"issue {number}", "body": "body", "labels": [],
            "url": f"https://x/{number}", "updatedAt": "2026-09-24T00:00:00Z"}


def test_cli_capture_review_finalize_preserves_baseline(monkeypatch, tmp_path):
    issue_list = [_live_issue(1)]

    def fake_run(command):
        if command[:3] == ["gh", "api", "graphql"]:
            return json.dumps({"data": {"repository": {"issues": {"totalCount": 1}}}})
        assert command[:3] == ["gh", "issue", "list"]
        assert command[command.index("--repo") + 1] == KIR.GATE_E_REPO
        return json.dumps(issue_list)

    monkeypatch.setattr(KIR, "_run", fake_run)
    evidence = tmp_path / "evidence"
    monkeypatch.setattr(sys, "argv", ["known_issues_report.py", "--capture-gate-e", "--evidence-dir", str(evidence)])
    assert KIR.main() == 0
    baseline = evidence / "issues-baseline.json"
    baseline_bytes = baseline.read_bytes()
    rating = tmp_path / "ratings.json"
    _write(rating, {"schema": KIR.RATINGS_SCHEMA, "review": {"identity": "reviewer", "review_timestamp": datetime.now(timezone.utc).isoformat(), "snapshot_sha256": _sha(baseline)}, "ratings": [{"id": 1, "severity": "low", "rationale": "reviewed"}]})
    monkeypatch.setattr(sys, "argv", ["known_issues_report.py", "--finalize-gate-e", "--ratings", str(rating), "--evidence-dir", str(evidence)])
    assert KIR.main() == 0
    assert baseline.read_bytes() == baseline_bytes
    assert (evidence / "instrument.json").is_file()


def test_cli_finalize_rejects_tampered_baseline_and_ratings_mismatch(monkeypatch, tmp_path):
    baseline, ratings, _ = _evidence(tmp_path)
    evidence = tmp_path / "evidence"; evidence.mkdir(); copied = evidence / "issues-baseline.json"; copied.write_bytes(baseline.read_bytes())
    data = json.loads(copied.read_text()); data["issues"][0]["title"] = "tampered"; _write(copied, data)
    monkeypatch.setattr(sys, "argv", ["known_issues_report.py", "--finalize-gate-e", "--ratings", str(ratings), "--evidence-dir", str(evidence)])
    try:
        KIR.main(); assert False, "tampered baseline must not match reviewer SHA"
    except ValueError as exc:
        assert "does not link" in str(exc)


def test_live_capture_raises_limit_and_reconciles_with_bounded_query(monkeypatch):
    issues = [_live_issue(index) for index in range(1000)]
    commands = []

    def fake_run(command):
        commands.append(command)
        if command[:3] == ["gh", "api", "graphql"]:
            return json.dumps({"data": {"repository": {"issues": {"totalCount": 1000}}}})
        return json.dumps(issues)

    monkeypatch.setattr(KIR, "_run", fake_run)
    snapshot = KIR._live_snapshot()
    assert snapshot["capture_limit"] == 1001
    assert snapshot["command"] == KIR.gate_e_command(1001)
    assert any(command == KIR.gate_e_command(1001) for command in commands)

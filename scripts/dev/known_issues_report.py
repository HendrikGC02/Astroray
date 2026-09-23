#!/usr/bin/env python
"""Regenerate .astroray_plan/docs/KNOWN_ISSUES.md from GitHub issues.

Source of truth is GitHub: issues labelled ``addon-bug`` (defects) or
``addon-gap`` (native Blender controls not yet honoured), severity from the
``P0-critical`` … ``P3-low`` labels. Run after filing/closing issues:

    python scripts/dev/known_issues_report.py            # writes the doc
    python scripts/dev/known_issues_report.py --check    # exit 1 if the doc is stale

Requires the ``gh`` CLI (authenticated). Never edits issues.
"""
import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / ".astroray_plan" / "docs" / "KNOWN_ISSUES.md"
SEVERITY = ["P0-critical", "P1-high", "P2-medium", "P3-low"]

# pkg278 gate (e): the published severity rubric. High = wrong image, crash, or
# a native setting silently ignored; medium = degraded but flagged; low =
# cosmetic. Every open issue is rated under this rubric by an independent pass,
# not by label, so the gate cannot be met by relabeling.
SEVERITY_RUBRIC = (
    "## Severity rubric (gate (e), owner-ratified 2026-09-07)\n\n"
    "- **high** — wrong image, crash, or a native setting silently ignored.\n"
    "- **medium** — degraded but flagged (a visible degradation with a warning).\n"
    "- **low** — cosmetic.\n\n"
    "Every open issue is rated independently under this rubric, not by label; "
    "gate (e) is green only when the live snapshot is fully reconciled and "
    "`high_count == 0`.\n"
)

# This command remains a label-based *legacy diagnostic*.  Gate (e) uses the
# typed capture below, where every open issue is independently rated.
GATE_E_SCHEMA = "pkg278.issue_snapshot.v2"
RATINGS_SCHEMA = "pkg278.issue_ratings.v2"
GATE_E_COMMAND = ["gh", "issue", "list", "--state", "open", "--limit", "1000",
                  "--json", "number,title,body,labels,url,updatedAt"]
GATE_E_GRAPHQL_QUERY = "repository.issues(states:OPEN).totalCount"
GATE_E_SEVERITIES = {"high", "medium", "low", "not-applicable"}


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp missing")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _issue_ids(issues: Any) -> list[int]:
    if not isinstance(issues, list):
        raise ValueError("issues must be a list")
    ids = []
    for issue in issues:
        if not isinstance(issue, dict) or isinstance(issue.get("number"), bool) or not isinstance(issue.get("number"), int):
            raise ValueError("issue record lacks numeric number")
        if not all(isinstance(issue.get(key), str) for key in ("title", "body", "url", "updatedAt")):
            raise ValueError(f"issue #{issue.get('number')} lacks full content fields")
        if not isinstance(issue.get("labels"), list):
            raise ValueError(f"issue #{issue.get('number')} labels malformed")
        _timestamp(issue["updatedAt"]); ids.append(issue["number"])
    if len(ids) != len(set(ids)):
        raise ValueError("snapshot contains duplicate issue IDs")
    return ids


def parse_snapshot(path: pathlib.Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != GATE_E_SCHEMA:
        raise ValueError("unsupported gate-e snapshot schema")
    if data.get("command") != GATE_E_COMMAND or data.get("graphql_total_query") != GATE_E_GRAPHQL_QUERY or data.get("reported_total") != len(data.get("issues", [])):
        raise ValueError("snapshot command or reported total is not canonical")
    ids = _issue_ids(data["issues"])
    if data["reported_total"] >= 1000:
        raise ValueError("snapshot hit the 1000-issue capture limit")
    _timestamp(data.get("captured_at"))
    return {"ids": ids, "content": data["issues"], "captured_at": data["captured_at"], "reported_total": data["reported_total"]}


def parse_ratings(path: pathlib.Path, snapshot_sha256: str, ids: list[int]) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    review = data.get("review") if isinstance(data, dict) else None
    ratings = data.get("ratings") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("schema") != RATINGS_SCHEMA or not isinstance(review, dict) or not isinstance(ratings, list):
        raise ValueError("ratings require review metadata and ratings list")
    identity = review.get("identity") or review.get("reviewer")
    if not isinstance(identity, str) or not identity.strip() or not isinstance(review.get("review_timestamp"), str):
        raise ValueError("ratings require independent reviewer identity and timestamp")
    _timestamp(review["review_timestamp"])
    linked = str(review.get("snapshot_sha256") or "").lower()
    if linked != snapshot_sha256:
        raise ValueError("ratings snapshot SHA does not link to baseline snapshot")
    rated: dict[int, str] = {}
    for item in ratings:
        if not isinstance(item, dict) or isinstance(item.get("id"), bool) or not isinstance(item.get("id"), int):
            raise ValueError("rating lacks numeric issue ID")
        if item["id"] in rated or item.get("severity") not in GATE_E_SEVERITIES or not isinstance(item.get("rationale"), str) or not item["rationale"].strip():
            raise ValueError("rating has duplicate ID, unknown severity, or empty rationale")
        rated[item["id"]] = item["severity"]
    if set(rated) != set(ids):
        raise ValueError("ratings IDs do not exactly match baseline snapshot")
    return {"ratings": rated, "identity": identity, "review_timestamp": review["review_timestamp"]}


def validate_gate_e_artifacts(baseline: pathlib.Path, recheck: pathlib.Path,
                              ratings: pathlib.Path) -> dict[str, Any]:
    """Strict pure reducer used by both collector and acceptance aggregator."""
    first = parse_snapshot(baseline); second = parse_snapshot(recheck)
    if _timestamp(second["captured_at"]) <= _timestamp(first["captured_at"]):
        raise ValueError("recheck snapshot is not newer than baseline")
    if first["ids"] != second["ids"] or first["content"] != second["content"]:
        raise ValueError("recheck differs in issue IDs or issue content")
    parsed_ratings = parse_ratings(ratings, sha256_file(baseline), first["ids"])
    if not (_timestamp(first["captured_at"]) <= _timestamp(parsed_ratings["review_timestamp"]) <= _timestamp(second["captured_at"])):
        raise ValueError("independent rating timestamp is outside the two live snapshots")
    high = sum(severity == "high" for severity in parsed_ratings["ratings"].values())
    return {"value": {"high_count": high}, "subchecks": {"snapshot_unique": True,
            "count_matches_total": True, "all_rated_independently": True, "delta_empty": True},
            "ids": first["ids"], "rating_identity": parsed_ratings["identity"]}


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=ROOT).stdout


def _live_snapshot() -> dict[str, Any]:
    issues = json.loads(_run(GATE_E_COMMAND) or "[]")
    repo = json.loads(_run(["gh", "repo", "view", "--json", "nameWithOwner"]))["nameWithOwner"].split("/", 1)
    query = "query($owner:String!,$name:String!){repository(owner:$owner,name:$name){issues(states:OPEN,first:1){totalCount}}}"
    total = json.loads(_run(["gh", "api", "graphql", "-f", f"query={query}", "-F", f"owner={repo[0]}", "-F", f"name={repo[1]}"]))["data"]["repository"]["issues"]["totalCount"]
    if total >= 1000:
        raise RuntimeError("gate-e capture refuses a 1000-issue-truncated snapshot")
    if total != len(issues):
        raise RuntimeError(f"GraphQL total {total} disagrees with issue-list count {len(issues)}")
    return {"schema": GATE_E_SCHEMA, "captured_at": datetime.now(timezone.utc).isoformat(),
            "command": GATE_E_COMMAND, "graphql_total_query": GATE_E_GRAPHQL_QUERY,
            "reported_total": total, "issues": issues}


def fetch(label: str, state: str) -> list[dict]:
    cmd = ["gh", "issue", "list", "--label", label, "--state", state, "--limit", "200",
           "--json", "number,title,labels,url,updatedAt"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=ROOT).stdout
    return json.loads(out or "[]")


def severity(issue: dict) -> str:
    names = {l["name"] for l in issue.get("labels", [])}
    for s in SEVERITY:
        if s in names:
            return s
    return "unranked"


def table(rows: list[dict]) -> str:
    if not rows:
        return "_none_\n"
    rows = sorted(rows, key=lambda r: (SEVERITY.index(severity(r)) if severity(r) in SEVERITY else 9, r["number"]))
    lines = ["| # | Severity | Title | Updated |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| [{r['number']}]({r['url']}) | {severity(r)} | {r['title']} | {r['updatedAt'][:10]} |")
    return "\n".join(lines) + "\n"


def render() -> str:
    bugs = fetch("addon-bug", "open")
    gaps = fetch("addon-gap", "open")
    closed = fetch("addon-bug", "closed") + fetch("addon-gap", "closed")
    seen = set()
    closed = [c for c in closed if not (c["number"] in seen or seen.add(c["number"]))]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    high_open = sum(1 for b in bugs if severity(b) in ("P0-critical", "P1-high"))
    return (
        "# Known issues — Blender addon\n\n"
        f"Generated {stamp} by `scripts/dev/known_issues_report.py` from GitHub issues "
        "labelled `addon-bug` / `addon-gap`. This is a legacy label diagnostic, not gate-(e) evidence. Do not edit by hand; file or close issues instead.\n\n"
        f"Pillar-4 exit-gate (e): open `addon-bug` at P0/P1 = **{high_open}** (target 0).\n\n"
        + SEVERITY_RUBRIC +
        "\n## Open defects (`addon-bug`)\n\n" + table(bugs) +
        "\n## Open gaps (`addon-gap`)\n\n" + table(gaps) +
        "\n## Recently closed\n\n" + table(closed[:30])
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if KNOWN_ISSUES.md differs (ignoring the timestamp line)")
    ap.add_argument("--capture-gate-e", action="store_true", help="capture typed live gate-(e) evidence; read-only GitHub access")
    ap.add_argument("--ratings", type=pathlib.Path, help="independent pkg278.issue_ratings.v2 JSON linked to the baseline SHA")
    ap.add_argument("--evidence-dir", type=pathlib.Path, default=ROOT / "docs" / "blender_parity" / "evidence" / "e")
    args = ap.parse_args()
    if args.capture_gate_e:
        if args.check or args.ratings is None:
            ap.error("--capture-gate-e requires --ratings and cannot be combined with --check")
        out = args.evidence_dir; out.mkdir(parents=True, exist_ok=True)
        baseline = out / "issues-baseline.json"; baseline.write_text(json.dumps(_live_snapshot(), indent=2), encoding="utf-8")
        ratings = out / "issue-ratings.json"; ratings.write_bytes(args.ratings.read_bytes())
        # Validate before the fresh query so malformed independent input cannot
        # produce a partially assembled instrument.
        parse_ratings(ratings, sha256_file(baseline), parse_snapshot(baseline)["ids"])
        recheck = out / "issues-recheck.json"; recheck.write_text(json.dumps(_live_snapshot(), indent=2), encoding="utf-8")
        reduced = validate_gate_e_artifacts(baseline, recheck, ratings)
        ref = lambda p: {"path": p.name, "sha256": sha256_file(p)}
        payload = {"schema": "pkg278.instrument.v2", "row": "e", "instrument": "issue_triage",
                   "scene_sha256": [], "build_id": "live-github", "backend": [], "settings": {"scope": "all-open-issues"},
                   "metric": {"name": "independently_rated_high_count"}, "value": reduced["value"],
                   "threshold": {"high_count": 0}, "records": [{"kind": "snapshot", "phase": "baseline", "artifact": ref(baseline)},
                   {"kind": "snapshot", "phase": "recheck", "artifact": ref(recheck)}, {"kind": "ratings", "artifact": ref(ratings)}]}
        instrument = out / "instrument.json"; instrument.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(instrument)
        return 0
    text = render()
    if args.check:
        old = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        strip = lambda s: "\n".join(l for l in s.splitlines() if not l.startswith("Generated "))
        if strip(old) != strip(text):
            print("KNOWN_ISSUES.md is stale; rerun without --check", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

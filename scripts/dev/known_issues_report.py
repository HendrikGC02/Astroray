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
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / ".astroray_plan" / "docs" / "KNOWN_ISSUES.md"
SEVERITY = ["P0-critical", "P1-high", "P2-medium", "P3-low"]


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
        "labelled `addon-bug` / `addon-gap`. Do not edit by hand; file or close issues instead.\n\n"
        f"Pillar-4 exit-gate (e): open `addon-bug` at P0/P1 = **{high_open}** (target 0).\n\n"
        "## Open defects (`addon-bug`)\n\n" + table(bugs) +
        "\n## Open gaps (`addon-gap`)\n\n" + table(gaps) +
        "\n## Recently closed\n\n" + table(closed[:30])
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if KNOWN_ISSUES.md differs (ignoring the timestamp line)")
    args = ap.parse_args()
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

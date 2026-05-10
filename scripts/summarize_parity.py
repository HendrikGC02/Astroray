#!/usr/bin/env python3
"""Summarize a pkg71 Cycles parity CSV as Markdown."""

from __future__ import annotations

import argparse
import csv
import tomllib
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCH_ROOT = ROOT / "benchmarks" / "cycles-parity"
MANIFEST = BENCH_ROOT / "scenes" / "manifest.toml"
ENGINES = ("cycles-cpu", "cycles-cuda", "astroray-cpu", "astroray-gpu")


def _load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _pivot(rows: list[dict[str, str]], field: str) -> str:
    by_scene: dict[str, dict[str, str]] = defaultdict(dict)
    for row in rows:
        value = row.get(field, "")
        if not value and row.get("skip_reason"):
            value = f"skip: {row['skip_reason'].splitlines()[0]}"
        by_scene[row["scene"]][row["engine"]] = value

    lines = ["| Scene | " + " | ".join(ENGINES) + " |", "|" + "---|" * (len(ENGINES) + 1)]
    for scene in sorted(by_scene):
        cells = [scene]
        for engine in ENGINES:
            value = by_scene[scene].get(engine, "")
            if field == "ssim_to_cycles" and value:
                try:
                    numeric = float(value)
                    if numeric < 0.95:
                        value = f"**{value}**"
                except ValueError:
                    pass
            cells.append(value)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _attributions(rows: list[dict[str, str]]) -> list[str]:
    if not MANIFEST.exists():
        return []
    rendered = {row["scene"] for row in rows if not row.get("skip_reason")}
    with MANIFEST.open("rb") as fh:
        scenes = tomllib.load(fh).get("scene", [])
    lines = []
    for scene in scenes:
        if scene["id"] in rendered and str(scene.get("license", "")).upper().startswith("CC-BY"):
            lines.append(f"- {scene['attribution']}")
    return lines


def summarize(csv_path: Path) -> str:
    rows = _load_rows(csv_path)
    lines = [
        f"# Cycles Parity Summary: `{csv_path.name}`",
        "",
        "## Time to Samples (ms)",
        "",
        _pivot(rows, "time_ms"),
        "",
        "## Peak Resident Memory (MB)",
        "",
        _pivot(rows, "peak_mem_mb"),
        "",
        "## SSIM to Cycles CPU Reference",
        "",
        _pivot(rows, "ssim_to_cycles"),
    ]
    attributions = _attributions(rows)
    if attributions:
        lines.extend(["", "## Scene Attribution", "", *attributions])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    markdown = summarize(args.csv)
    if args.output:
        args.output.write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

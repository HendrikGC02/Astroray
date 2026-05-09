#!/usr/bin/env python
"""Summarize render PNGs for quick visual-test triage.

This is intentionally diagnostic, not a CI gate. It helps agents spot
all-black images, tiny binary masks, and unexpectedly saturated renders before
turning any one observation into a real pytest assertion.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def analyze_png(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        arr = np.asarray(rgb, dtype=np.float32) / 255.0

    mean = float(arr.mean())
    min_value = float(arr.min())
    max_value = float(arr.max())
    saturated_fraction = float((arr >= 0.999).mean())
    black_fraction = float((arr <= 0.001).mean())
    unique_values = int(np.unique((arr * 255.0).astype(np.uint8).reshape(-1, 3), axis=0).shape[0])

    flags: list[str] = []
    if max_value <= 0.001:
        flags.append("all-black")
    elif mean < 0.01:
        flags.append("very-dark")
    if saturated_fraction > 0.25:
        flags.append("saturated")
    if unique_values <= 8:
        flags.append("low-color-count")
    if path.stat().st_size < 1024:
        flags.append("tiny-file")

    return {
        "path": str(path),
        "width": rgb.width,
        "height": rgb.height,
        "bytes": path.stat().st_size,
        "mean": mean,
        "min": min_value,
        "max": max_value,
        "black_fraction": black_fraction,
        "saturated_fraction": saturated_fraction,
        "unique_rgb": unique_values,
        "flags": flags,
    }


def format_table(rows: list[dict[str, Any]], flagged_only: bool) -> str:
    if flagged_only:
        rows = [row for row in rows if row["flags"]]

    lines = [
        "| file | size | bytes | mean | min | max | unique | flags |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        name = Path(row["path"]).name
        flags = ", ".join(row["flags"]) if row["flags"] else "-"
        lines.append(
            f"| {name} | {row['width']}x{row['height']} | {row['bytes']} | "
            f"{row['mean']:.4f} | {row['min']:.4f} | {row['max']:.4f} | "
            f"{row['unique_rgb']} | {flags} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory",
        nargs="?",
        default="test_results",
        help="Directory containing PNG render outputs.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a Markdown table.")
    parser.add_argument(
        "--flagged-only",
        action="store_true",
        help="Show only outputs with triage flags.",
    )
    args = parser.parse_args()

    directory = Path(args.directory)
    paths = sorted(directory.glob("*.png"))
    rows = [analyze_png(path) for path in paths]

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(format_table(rows, args.flagged_only))
        print(f"\nAnalyzed {len(rows)} PNG files under {directory}.")
        if args.flagged_only:
            print("Flags are hints for review, not automatic failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

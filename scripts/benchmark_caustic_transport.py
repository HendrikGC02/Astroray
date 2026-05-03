#!/usr/bin/env python
"""Render pkg29a caustic validation scenes and write image/stat diagnostics."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()

import astroray  # noqa: E402
from base_helpers import save_image  # noqa: E402
from scenes.caustic_validation import SCENES, image_metrics, render_scene  # noqa: E402


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    keys = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--max-depth", type=int, default=12)
    parser.add_argument("--seed", type=int, default=145)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "test_results" / "pkg29a_caustics")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for scene_name in sorted(SCENES):
        for integrator in ("path_tracer", "caustic_path_tracer"):
            print(f"Rendering {scene_name} / {integrator} ...", flush=True)
            record = render_scene(
                astroray, scene_name, integrator,
                samples=args.samples, max_depth=args.max_depth, seed=args.seed)
            image_path = args.output_dir / f"{scene_name}_{integrator}.png"
            save_image(record.pixels, str(image_path))
            row = {
                "scene": scene_name,
                "integrator": integrator,
                "seconds": f"{record.seconds:.4f}",
                **{k: f"{v:.6f}" for k, v in image_metrics(record.pixels, scene_name).items()},
                **{k: f"{v:.6f}" for k, v in record.stats.items()},
            }
            rows.append(row)
            print(f"  -> {record.seconds:.2f}s, max={row['max_luminance']}")

    json_path = args.output_dir / "caustic_transport_stats.json"
    csv_path = args.output_dir / "caustic_transport_stats.csv"
    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    write_csv(rows, csv_path)
    print(f"\nWrote {json_path}")
    print(f"Wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

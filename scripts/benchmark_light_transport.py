#!/usr/bin/env python
"""Compare Astroray light-transport integrator configurations.

Writes CSV/JSON stats plus PNG charts. Use ASTRORAY_BUILD_DIR to point at a
specific build, for example a tiny-cuda-nn opt-in build.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()

import astroray  # noqa: E402
from scenes.neural_cache_indirect import (  # noqa: E402
    add_indirect_scene,
    make_renderer,
    mean_luminance,
    mse_luminance,
)


def _render_config(config, width, height, samples, max_depth, frames, seed, warmup_renders=1):
    r = make_renderer(astroray, width, height)
    add_indirect_scene(r)
    r.set_seed(seed)
    r.set_integrator_param("max_depth", int(max_depth))
    for key, value in config.get("params", {}).items():
        r.set_integrator_param(key, int(value))
    integrator = config.get("integrator")
    if integrator:
        r.set_integrator(integrator)

    pixels = None
    for warmup in range(max(0, warmup_renders)):
        r.set_seed(seed - 1000 - warmup)
        pixels = np.asarray(r.render(samples, max_depth, None, False), dtype=np.float32)

    start = time.perf_counter()
    for frame in range(frames):
        r.set_seed(seed + frame)
        pixels = np.asarray(r.render(samples, max_depth, None, False), dtype=np.float32)
    elapsed = time.perf_counter() - start
    stats = dict(r.get_integrator_stats())
    return pixels, elapsed, stats


def _write_csv(path: Path, rows: list[dict]) -> None:
    keys = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _plot_outputs(output_dir: Path, rows: list[dict]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = [row["config"] for row in rows]

    def bar_chart(filename, key, title, ylabel):
        fig, ax = plt.subplots(figsize=(8, 4.5))
        values = [float(row.get(key, 0.0)) for row in rows]
        ax.bar(labels, values, color=["#3b82f6", "#14b8a6", "#f59e0b", "#8b5cf6"][: len(rows)])
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", rotation=18)
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        fig.savefig(output_dir / filename, dpi=140)
        plt.close(fig)

    bar_chart("light_transport_time.png", "seconds_per_frame", "Render Time", "seconds / frame")
    bar_chart("light_transport_mse.png", "mse_vs_reference", "Error vs Reference", "luminance MSE")
    bar_chart("light_transport_speedup.png", "speedup_vs_path_tracer", "Speedup vs Path Tracer", "x")

    fig, ax = plt.subplots(figsize=(8, 4.5))
    queued = [float(row.get("stat_last_queued_samples", 0.0)) for row in rows]
    trained = [float(row.get("stat_last_trained_samples", 0.0)) for row in rows]
    x = np.arange(len(labels))
    ax.bar(x - 0.18, queued, width=0.36, label="queued")
    ax.bar(x + 0.18, trained, width=0.36, label="trained")
    ax.set_title("NRC Training Activity")
    ax.set_ylabel("samples")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=18, ha="right")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "light_transport_nrc_training.png", dpi=140)
    plt.close(fig)


def run_benchmark(
    output_dir: Path,
    width: int = 32,
    height: int = 32,
    samples: int = 4,
    reference_samples: int = 32,
    max_depth: int = 6,
    frames: int = 2,
    warmup_renders: int = 1,
    make_plots: bool = True,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)

    reference_config = {"config": "reference_path_tracer", "integrator": "path_tracer"}
    reference, _, _ = _render_config(
        reference_config, width, height, reference_samples, max_depth, 1, 1000, 0)

    configs = [
        {"config": "path_tracer", "integrator": "path_tracer"},
        {"config": "auto_default", "integrator": None},
        {
            "config": "neural_cache_fallback",
            "integrator": "neural-cache",
            "params": {"force_fallback": 1},
        },
        {
            "config": "neural_cache_backend",
            "integrator": "neural-cache",
            "params": {
                "warmup_frames": max(frames, 1),
                "training_pct": 100,
                "min_train_batch": 1,
                "max_train_samples": 512,
            },
        },
    ]

    rows: list[dict] = []
    for idx, config in enumerate(configs):
        pixels, elapsed, stats = _render_config(
            config, width, height, samples, max_depth, frames, 2000, warmup_renders)
        row = {
            "config": config["config"],
            "requested_integrator": config.get("integrator") or "auto",
            "width": width,
            "height": height,
            "samples": samples,
            "frames": frames,
            "warmup_renders": warmup_renders,
            "total_seconds": elapsed,
            "seconds_per_frame": elapsed / max(frames, 1),
            "mean_luminance": mean_luminance(pixels),
            "mse_vs_reference": mse_luminance(pixels, reference),
            "max_value": float(np.max(pixels)),
            "finite": bool(np.isfinite(pixels).all()),
        }
        for key, value in stats.items():
            row[f"stat_{key}"] = float(value)
        rows.append(row)

    baseline = next(row for row in rows if row["config"] == "path_tracer")
    baseline_seconds = max(float(baseline["seconds_per_frame"]), 1e-9)
    for row in rows:
        seconds = max(float(row["seconds_per_frame"]), 1e-9)
        row["speedup_vs_path_tracer"] = baseline_seconds / seconds
        if not math.isfinite(float(row["mse_vs_reference"])):
            row["mse_vs_reference"] = 0.0

    json_path = output_dir / "light_transport_stats.json"
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    _write_csv(output_dir / "light_transport_stats.csv", rows)
    if make_plots:
        _plot_outputs(output_dir, rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "test_results" / "light_transport_benchmark")
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--height", type=int, default=32)
    parser.add_argument("--samples", type=int, default=4)
    parser.add_argument("--reference-samples", type=int, default=32)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--frames", type=int, default=2)
    parser.add_argument("--warmup-renders", type=int, default=1)
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()

    rows = run_benchmark(
        output_dir=args.output_dir,
        width=args.width,
        height=args.height,
        samples=args.samples,
        reference_samples=args.reference_samples,
        max_depth=args.max_depth,
        frames=args.frames,
        warmup_renders=args.warmup_renders,
        make_plots=not args.no_plots,
    )
    print(f"Wrote {len(rows)} configurations to {args.output_dir}")
    for row in rows:
        print(
            f"{row['config']}: {row['seconds_per_frame']:.4f}s/frame, "
            f"speedup {row['speedup_vs_path_tracer']:.2f}x, "
            f"MSE {row['mse_vs_reference']:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

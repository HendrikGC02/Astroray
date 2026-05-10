#!/usr/bin/env python
"""pkg74 — engine benchmark + visual showcase runner.

Spec:     .astroray_plan/packages/pkg74-engine-benchmark-showcase.md
Research: .astroray_plan/docs/engine-benchmark-research.md

Reference patterns (cite, do not mirror verbatim):
- mmp/pbrt-v4 src/pbrt/util/stats.h — stats categories
- mitsuba-renderer/mitsuba3 include/mitsuba/core/profiler.h — phase enum
- blender/cycles src/util/stats.h, src/scene/stats.h — RenderStats schema

Phase 1 deliverables:
  --quick produces material_zoo_contact_sheet.png,
  convergence_grid_contact_sheet.png, convergence_curve.png,
  stats_summary.csv, index.html in
  benchmarks/showcase/output/<YYYY-MM-DD-HHMMSS>-<machine-id>/

Phase 2 additions (this round):
  - `benchmarks/showcase/stats.py` collects geometry, memory, timing,
    sampling, quality, spectral, gpu, integrator-specific categories.
    Per spec design decision #7, no engine bindings are added — stats
    that need a future C++ binding are probed via hasattr and report
    empty cells.
  - New scene `integrator_compare` runs every safe registered
    integrator on a Cornell-with-glass and produces:
      * integrator_compare_contact_sheet.png
      * integrator_compare_timing.png
  - Paired-seed variance render for the convergence reference SPP →
    `qual_variance_*` columns + `qual_convergence_rate_slope`.
  - `--gpu` flag appends a second render per scene with
    `set_use_gpu(True)`, tagged `device=gpu`. Cleanly skipped when
    CUDA is absent.
  - HTML index groups columns by category in collapsible <details>
    sections.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import os
import platform
import re
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np


# Bootstrap so `import astroray` resolves the same way the test suite does.
_ROOT = Path(__file__).resolve().parents[2]
_TESTS = _ROOT / "tests"
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()

import astroray  # noqa: E402

from . import config, stats  # noqa: E402
from .contact_sheets import save_contact_sheet, save_strip  # noqa: E402
from .graphs import (  # noqa: E402
    rmse,
    save_convergence_curve,
    save_integrator_timing_bar,
)
from .html_index import write_index  # noqa: E402
from .scenes import convergence_grid, integrator_compare, material_zoo  # noqa: E402


# ---------------------------------------------------------------------------
# Run metadata
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower() or "unknown"


def _machine_id() -> str:
    host = _slug(socket.gethostname() or "host")
    cpu = _slug((platform.processor() or platform.machine() or "cpu").split()[0]
                if (platform.processor() or platform.machine()) else "cpu")
    return f"{host}-{cpu}"[:64]


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", str(_ROOT), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True, timeout=5)
        return out.strip() or "unknown"
    except Exception:
        return "unknown"


def _peak_rss_mb() -> float:
    try:
        import psutil  # type: ignore
        return float(psutil.Process(os.getpid()).memory_info().rss) / (1024 * 1024)
    except Exception:
        return float("nan")


# ---------------------------------------------------------------------------
# Render execution + per-row build
# ---------------------------------------------------------------------------

def _render(renderer, samples: int, max_depth: int) -> np.ndarray:
    return np.asarray(
        renderer.render(samples, max_depth, None, False),
        dtype=np.float32,
    )


def _try_set_gpu(renderer, device: str) -> tuple[str, str]:
    """Returns (effective_device, gpu_skip_reason). Phase-2 GPU rows."""
    if device != "gpu":
        return "cpu", ""
    if not bool(getattr(renderer, "gpu_available", False)):
        return "cpu", "gpu unavailable"
    try:
        renderer.set_use_gpu(True)
        return "gpu", ""
    except Exception as exc:
        return "cpu", f"set_use_gpu failed: {type(exc).__name__}: {exc}"


def _row_with_phase1_compat(scene: str, integrator: str, device: str,
                            samples: int, width: int, height: int,
                            max_depth: int, render_seconds: float,
                            skip_reason: str = "") -> dict[str, object]:
    """The Phase 1 column shape — preserved verbatim so the Phase 1
    pytest gate keeps passing.
    """
    return {
        "scene": scene,
        "integrator": integrator,
        "device": device,
        "samples": samples,
        "width": width,
        "height": height,
        "max_depth": max_depth,
        "render_seconds": f"{render_seconds:.4f}" if render_seconds >= 0 else "",
        "peak_rss_mb": f"{_peak_rss_mb():.2f}",
        "skip_reason": skip_reason,
    }


# ---------------------------------------------------------------------------
# Material zoo — one row + one tile per registered material
# ---------------------------------------------------------------------------

def render_material_zoo(out_dir: Path,
                        resolution: int,
                        samples: int,
                        max_depth: int,
                        seed: int,
                        run_meta: dict[str, object],
                        device: str = "cpu") -> tuple[Path, list[dict[str, object]]]:
    tiles: list[tuple[str, np.ndarray | None]] = []
    rows: list[dict[str, object]] = []

    for display_name, mat_type, color, params in material_zoo.material_entries(astroray):
        scene_label = f"material_zoo[{display_name}]"
        try:
            r = astroray.Renderer()
            if hasattr(r, "set_seed"):
                r.set_seed(seed)
            mat_id = r.create_material(mat_type, color, params)

            t_build = time.perf_counter()
            scene_meta = material_zoo.build_material_preview_scene(
                r, mat_id, resolution)
            scene_build_ms = (time.perf_counter() - t_build) * 1000.0

            effective_device, gpu_reason = _try_set_gpu(r, device)

            t_render = time.perf_counter()
            pixels = _render(r, samples, max_depth)
            render_ms = (time.perf_counter() - t_render) * 1000.0
            elapsed_s = render_ms / 1000.0

            tiles.append((display_name, pixels))
            row: dict[str, object] = {
                **run_meta,
                **_row_with_phase1_compat(
                    scene_label, "path_tracer", effective_device,
                    samples, resolution, resolution, max_depth, elapsed_s,
                    skip_reason=gpu_reason),
                **stats.collect(
                    renderer=r, astroray_module=astroray,
                    scene_meta=scene_meta,
                    samples=samples, width=resolution, height=resolution,
                    max_depth=max_depth,
                    scene_build_ms=scene_build_ms, render_ms=render_ms,
                    pixels=pixels, device=effective_device),
            }
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            tiles.append((display_name, None))
            rows.append({
                **run_meta,
                **_row_with_phase1_compat(
                    scene_label, "path_tracer", device,
                    samples, resolution, resolution, max_depth, -1.0,
                    skip_reason=f"{type(exc).__name__}: {exc}".replace("\n", " ")[:240]),
            })
            print(f"  [skip] {display_name}: {type(exc).__name__}: {exc}",
                  file=sys.stderr)

    suffix = f"_{device}" if device != "cpu" else ""
    sheet_path = out_dir / f"material_zoo_contact_sheet{suffix}.png"
    save_contact_sheet(tiles, sheet_path, columns=4,
                       title=f"Material zoo (registry-driven, device={device})")
    return sheet_path, rows


# ---------------------------------------------------------------------------
# Convergence grid + curve + paired-seed variance render
# ---------------------------------------------------------------------------

def render_convergence(out_dir: Path,
                       resolution: int,
                       spp_series: list[int],
                       max_depth: int,
                       seed: int,
                       run_meta: dict[str, object],
                       device: str = "cpu") -> tuple[Path, Path, list[dict[str, object]]]:
    tiles: list[tuple[str, np.ndarray]] = []
    rows: list[dict[str, object]] = []
    pixels_by_spp: dict[int, np.ndarray] = {}
    scene_build_ms_by_spp: dict[int, float] = {}
    render_ms_by_spp: dict[int, float] = {}
    scene_meta: dict[str, int] = {}

    for spp in spp_series:
        r = astroray.Renderer()
        if hasattr(r, "set_seed"):
            r.set_seed(seed)
        t_build = time.perf_counter()
        scene_meta = convergence_grid.build_cornell(r, resolution, resolution)
        scene_build_ms = (time.perf_counter() - t_build) * 1000.0

        _try_set_gpu(r, device)  # graceful no-op for CPU device
        t_render = time.perf_counter()
        pixels = _render(r, spp, max_depth)
        render_ms = (time.perf_counter() - t_render) * 1000.0

        pixels_by_spp[spp] = pixels
        scene_build_ms_by_spp[spp] = scene_build_ms
        render_ms_by_spp[spp] = render_ms
        tiles.append((f"{spp} spp", pixels))

    # Paired-seed variance render at the highest SPP. One extra render
    # is the smallest representative cost; bigger statistics need more
    # paired draws but the doubling overhead grows fast.
    spp_sorted = sorted(pixels_by_spp.keys())
    top_spp = spp_sorted[-1]
    second_seed_pixels: np.ndarray | None = None
    try:
        r2 = astroray.Renderer()
        if hasattr(r2, "set_seed"):
            r2.set_seed(seed + 1)
        convergence_grid.build_cornell(r2, resolution, resolution)
        _try_set_gpu(r2, device)
        second_seed_pixels = _render(r2, top_spp, max_depth)
    except Exception as exc:  # noqa: BLE001
        print(f"  [skip] paired-seed variance render failed: {exc}",
              file=sys.stderr)

    # Convergence curve: highest-SPP entry is the in-run reference.
    # Plot excludes the reference point (self-vs-self == 0) but keeps
    # it in the CSV.
    reference = pixels_by_spp[top_spp]
    rmse_values = [rmse(pixels_by_spp[s], reference) for s in spp_sorted]
    slope = stats.convergence_rate_slope(spp_sorted[:-1], rmse_values[:-1])

    curve_path = out_dir / "convergence_curve.png"
    if len(spp_sorted) >= 2:
        save_convergence_curve(spp_sorted[:-1], rmse_values[:-1], curve_path,
                               scene_name=f"Cornell box (ref = {top_spp} spp)",
                               slope=slope)
    else:
        save_convergence_curve(spp_sorted, rmse_values, curve_path,
                               scene_name="Cornell box", slope=None)

    # Build rows after we know the slope + variance pixels — every
    # convergence row carries the same slope; only the top-SPP row
    # carries variance numbers (since that's the only one we paired).
    for spp, value in zip(spp_sorted, rmse_values):
        r_disposable = astroray.Renderer()
        if hasattr(r_disposable, "set_seed"):
            r_disposable.set_seed(seed)
        # Rebuild scene so stat collectors see the geometry counts; the
        # render itself already happened.
        convergence_grid.build_cornell(r_disposable, resolution, resolution)
        pixels = pixels_by_spp[spp]
        paired = second_seed_pixels if spp == top_spp else None

        elapsed_s = render_ms_by_spp[spp] / 1000.0
        row: dict[str, object] = {
            **run_meta,
            **_row_with_phase1_compat(
                "convergence_grid_cornell", "path_tracer", device,
                spp, resolution, resolution, max_depth, elapsed_s),
            **stats.collect(
                renderer=r_disposable, astroray_module=astroray,
                scene_meta=scene_meta,
                samples=spp, width=resolution, height=resolution,
                max_depth=max_depth,
                scene_build_ms=scene_build_ms_by_spp[spp],
                render_ms=render_ms_by_spp[spp],
                pixels=pixels, pixels_second_seed=paired,
                reference=reference if spp != top_spp else None,
                device=device),
            "rmse_vs_in_run_reference": f"{value:.6f}",
            "qual_convergence_rate_slope":
                round(slope, 6) if slope == slope else "",  # NaN guard
        }
        rows.append(row)

    sheet_path = out_dir / "convergence_grid_contact_sheet.png"
    save_strip(tiles, sheet_path, title="Cornell — convergence grid")

    return sheet_path, curve_path, rows


# ---------------------------------------------------------------------------
# Integrator-compare scene (Phase 2)
# ---------------------------------------------------------------------------

def render_integrator_compare(out_dir: Path,
                              resolution: int,
                              samples: int,
                              max_depth: int,
                              seed: int,
                              run_meta: dict[str, object],
                              device: str = "cpu") -> tuple[Path, Path, list[dict[str, object]]]:
    tiles: list[tuple[str, np.ndarray | None]] = []
    rows: list[dict[str, object]] = []
    timing: dict[str, float] = {}

    for integrator in integrator_compare.integrator_entries(astroray):
        scene_label = "integrator_compare_cornell_glass"
        try:
            r = astroray.Renderer()
            if hasattr(r, "set_seed"):
                r.set_seed(seed)
            t_build = time.perf_counter()
            scene_meta = integrator_compare.build_cornell_with_glass(
                r, resolution, resolution, integrator=integrator)
            scene_build_ms = (time.perf_counter() - t_build) * 1000.0

            effective_device, gpu_reason = _try_set_gpu(r, device)

            t_render = time.perf_counter()
            pixels = _render(r, samples, max_depth)
            render_ms = (time.perf_counter() - t_render) * 1000.0
            elapsed_s = render_ms / 1000.0

            tiles.append((integrator, pixels))
            timing[integrator] = render_ms

            row: dict[str, object] = {
                **run_meta,
                **_row_with_phase1_compat(
                    scene_label, integrator, effective_device,
                    samples, resolution, resolution, max_depth, elapsed_s,
                    skip_reason=gpu_reason),
                **stats.collect(
                    renderer=r, astroray_module=astroray,
                    scene_meta=scene_meta,
                    samples=samples, width=resolution, height=resolution,
                    max_depth=max_depth,
                    scene_build_ms=scene_build_ms, render_ms=render_ms,
                    pixels=pixels, device=effective_device),
            }
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            tiles.append((integrator, None))
            timing[integrator] = -1.0  # marks FAIL on the bar chart
            rows.append({
                **run_meta,
                **_row_with_phase1_compat(
                    scene_label, integrator, device,
                    samples, resolution, resolution, max_depth, -1.0,
                    skip_reason=f"{type(exc).__name__}: {exc}".replace("\n", " ")[:240]),
            })
            print(f"  [skip] integrator {integrator}: {type(exc).__name__}: {exc}",
                  file=sys.stderr)

    sheet_path = out_dir / "integrator_compare_contact_sheet.png"
    save_contact_sheet(tiles, sheet_path, columns=4,
                       title="Integrator comparison (Cornell + glass)")

    timing_path = out_dir / "integrator_compare_timing.png"
    save_integrator_timing_bar(timing, timing_path,
                               scene_name=f"Cornell + glass, {samples} spp")

    return sheet_path, timing_path, rows


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

def write_stats_csv(rows: list[dict[str, object]], out_dir: Path) -> Path:
    """Write `stats_summary.csv` using the union of keys from all rows."""
    union: list[str] = []
    seen: set[str] = set()
    # Stable header order: meta first, then by category.
    preferred = [
        "run_date", "git_sha", "machine_id", "seed",
        "scene", "integrator", "device",
        "samples", "width", "height", "max_depth",
        "render_seconds", "peak_rss_mb",
        "rmse_vs_in_run_reference", "skip_reason",
    ]
    for k in preferred:
        if k not in seen:
            union.append(k); seen.add(k)
    # Group remaining keys by category (geom_, mem_, time_, samp_, qual_,
    # spec_, gpu_, intstat_, integrator_stats_, then leftovers).
    category_order = ["geom", "mem", "time", "samp", "qual", "spec",
                      "gpu", "intstat", "integrator", "meta"]
    by_cat: dict[str, list[str]] = {c: [] for c in category_order}
    for row in rows:
        for k in row.keys():
            if k in seen:
                continue
            cat = stats.column_category(k)
            by_cat.setdefault(cat, []).append(k)
            seen.add(k)
    for cat in category_order:
        union.extend(by_cat.get(cat, []))
    # Anything we didn't account for goes at the end.
    for k in by_cat:
        if k not in category_order:
            union.extend(by_cat[k])

    out = out_dir / "stats_summary.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=union, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in union})
    return out


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------

def run(quick: bool = True,
        output_root: Path | None = None,
        resolution: int | None = None,
        samples: int | None = None,
        spp_series: list[int] | None = None,
        max_depth: int | None = None,
        seed: int | None = None,
        gpu: bool = False,
        skip_integrator_compare: bool = False) -> Path:
    """Execute the showcase. Returns the dated output directory."""
    if quick:
        resolution = resolution or config.QUICK_RESOLUTION
        samples = samples or config.QUICK_SPP
        spp_series = spp_series or list(config.QUICK_SPP_SERIES)
        max_depth = max_depth or config.QUICK_MAX_DEPTH
        seed = seed if seed is not None else config.QUICK_SEED
    else:
        resolution = resolution or config.FULL_RESOLUTION
        samples = samples or config.FULL_SPP
        spp_series = spp_series or list(config.FULL_SPP_SERIES)
        max_depth = max_depth or config.FULL_MAX_DEPTH
        seed = seed if seed is not None else config.QUICK_SEED

    output_root = output_root or config.OUTPUT_DIR
    timestamp = _dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    machine = _machine_id()
    sha = _git_sha()
    out_dir = output_root / f"{timestamp}-{machine}"
    out_dir.mkdir(parents=True, exist_ok=True)

    run_meta = {
        "run_date": timestamp,
        "git_sha": sha,
        "machine_id": machine,
        "seed": seed,
    }

    devices = ["cpu"]
    if gpu:
        # We always also include the CPU pass for parity comparison.
        devices.append("gpu")

    print(f"[pkg74] showcase output: {out_dir}", flush=True)
    print(f"[pkg74] mode={'quick' if quick else 'full'} "
          f"resolution={resolution} spp={samples} "
          f"spp_series={spp_series} max_depth={max_depth} "
          f"devices={devices}", flush=True)

    all_rows: list[dict[str, object]] = []
    artefacts: dict[str, str] = {}

    for device in devices:
        suffix = f"_{device}" if device != "cpu" else ""
        print(f"[pkg74] rendering material zoo (device={device})...", flush=True)
        try:
            sheet, zoo_rows = render_material_zoo(
                out_dir, resolution, samples, max_depth, seed, run_meta,
                device=device)
            all_rows.extend(zoo_rows)
            artefacts[f"Material zoo ({device})"] = sheet.name
        except Exception:
            traceback.print_exc()
            placeholder = out_dir / f"material_zoo_contact_sheet{suffix}.png"
            save_contact_sheet([("zoo failed", None)], placeholder,
                               columns=1, title="Material zoo — failed")
            artefacts[f"Material zoo ({device})"] = placeholder.name

    print("[pkg74] rendering convergence grid...", flush=True)
    try:
        sheet, curve, conv_rows = render_convergence(
            out_dir, resolution, spp_series, max_depth, seed, run_meta,
            device="cpu")
        all_rows.extend(conv_rows)
        artefacts["Convergence grid (Cornell)"] = sheet.name
        artefacts["Convergence curve (RMSE vs SPP)"] = curve.name
    except Exception:
        traceback.print_exc()
        save_strip([("convergence failed", np.zeros((4, 4, 3), dtype=np.float32))],
                   out_dir / "convergence_grid_contact_sheet.png",
                   title="Convergence grid — failed")
        save_convergence_curve([1], [1.0],
                               out_dir / "convergence_curve.png",
                               scene_name="Convergence — failed")
        artefacts["Convergence grid (Cornell)"] = "convergence_grid_contact_sheet.png"
        artefacts["Convergence curve (RMSE vs SPP)"] = "convergence_curve.png"

    if not skip_integrator_compare:
        print("[pkg74] rendering integrator comparison...", flush=True)
        try:
            sheet, timing, ic_rows = render_integrator_compare(
                out_dir, resolution, samples, max_depth, seed, run_meta,
                device="cpu")
            all_rows.extend(ic_rows)
            artefacts["Integrator comparison (Cornell + glass)"] = sheet.name
            artefacts["Integrator comparison — total render time"] = timing.name
        except Exception:
            traceback.print_exc()

    write_stats_csv(all_rows, out_dir)

    write_index(
        out_dir,
        machine_id=machine,
        git_sha=sha,
        run_timestamp=timestamp,
        artefacts=artefacts,
    )

    print(f"[pkg74] done. {len(all_rows)} rows written.", flush=True)
    return out_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", default=True,
                        help="Quick mode: low SPP, small resolution (default).")
    parser.add_argument("--full", action="store_true",
                        help="Full mode: production SPP and resolution.")
    parser.add_argument("--gpu", action="store_true",
                        help="Also render with set_use_gpu(True) and append rows tagged device=gpu. Cleanly skipped when CUDA absent.")
    parser.add_argument("--skip-integrator-compare", action="store_true",
                        help="Skip the integrator_compare scene. Useful when you only want the material zoo + convergence artefacts.")
    parser.add_argument("--output-dir", type=Path, default=None,
                        help="Override output root (default: benchmarks/showcase/output/).")
    parser.add_argument("--resolution", type=int, default=None)
    parser.add_argument("--samples", type=int, default=None,
                        help="SPP for the material zoo + integrator compare (convergence grid uses --spp-series).")
    parser.add_argument("--spp-series", type=int, nargs="+", default=None)
    parser.add_argument("--max-depth", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)

    quick = not args.full
    out = run(
        quick=quick,
        output_root=args.output_dir,
        resolution=args.resolution,
        samples=args.samples,
        spp_series=args.spp_series,
        max_depth=args.max_depth,
        seed=args.seed,
        gpu=args.gpu,
        skip_integrator_compare=args.skip_integrator_compare,
    )
    print(f"\nIndex: {out / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

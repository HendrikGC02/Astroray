"""Visual reference bank runner — pkg104 Phase 1 skeleton.

Renders a list of named scenes, compares against pinned references, and
writes per-scene Markdown reports + a top-level CSV history row.

CLI:
    python -m benchmarks.reference_bank.runner --scenes cornell-mini
    python -m benchmarks.reference_bank.runner --mode smoke
    python -m benchmarks.reference_bank.runner --scenes prism --bless

Scene contract:
    scenes/<name>/scene.py must expose:
        NAME: str
        WIDTH: int
        HEIGHT: int
        SAMPLES: int
        MAX_DEPTH: int
        SEED: int
        make_scene(astroray) -> astroray.Renderer

    scenes/<name>/gates.toml declares the per-scene gates:
        [scene]
        description = "..."
        [[gate]]
        type = "ssim" | "delta_e_2000" | "phash" | "hue_spread" |
               "bright_coverage" | "dark_disk"
        threshold = <float>
        direction = "ge" | "le"        # ge: measured >= threshold passes;
                                       # le: measured <= threshold passes
        roi = [y0, y1, x0, x1]         # optional, where the metric supports it
        luminance_threshold = <float>  # optional, hue_spread/bright/dark
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

# Ensure tests/ runtime_setup is on sys.path so we can import astroray the same
# way pytest does (handles cross-build-dir cases).
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "tests"))
sys.path.append(str(_REPO_ROOT))

# Lazy import to avoid hard dep at module-import time (lets `--help` work without a build).
_astroray = None


def _load_astroray():
    global _astroray
    if _astroray is None:
        from runtime_setup import configure_test_imports  # type: ignore
        configure_test_imports()
        import astroray  # type: ignore
        _astroray = astroray
    return _astroray


_BANK_ROOT = Path(__file__).resolve().parent
_SCENES_ROOT = _BANK_ROOT / "scenes"
_REFS_ROOT = _BANK_ROOT / "refs"
_RESULTS_ROOT = _BANK_ROOT / "results"


@dataclass
class GateSpec:
    type: str
    threshold: float
    direction: str  # "ge" or "le"
    roi: tuple[int, int, int, int] | None = None
    luminance_threshold: float | None = None
    saturation_floor: float | None = None
    description: str | None = None


@dataclass
class GateResult:
    spec: GateSpec
    measured: float
    passed: bool
    notes: str = ""


@dataclass
class SceneResult:
    name: str
    samples: int
    width: int
    height: int
    render_walltime_s: float
    gates: list[GateResult] = field(default_factory=list)
    passed: bool = True


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_REPO_ROOT), check=False, capture_output=True, text=True,
        )
        return out.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def _load_scene_module(scene_dir: Path):
    scene_py = scene_dir / "scene.py"
    if not scene_py.exists():
        raise FileNotFoundError(f"scene.py not found at {scene_py}")
    spec = importlib.util.spec_from_file_location(f"_rb_scene_{scene_dir.name}", scene_py)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {scene_py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for attr in ("NAME", "WIDTH", "HEIGHT", "SAMPLES", "MAX_DEPTH", "SEED", "make_scene"):
        if not hasattr(module, attr):
            raise AttributeError(f"{scene_py} missing required attribute: {attr}")
    return module


def _load_gates(scene_dir: Path) -> tuple[str, list[GateSpec]]:
    gates_toml = scene_dir / "gates.toml"
    if not gates_toml.exists():
        return ("(no description)", [])
    with gates_toml.open("rb") as f:
        data = tomllib.load(f)
    description = data.get("scene", {}).get("description", "(no description)")
    gates: list[GateSpec] = []
    for g in data.get("gate", []):
        gates.append(GateSpec(
            type=g["type"],
            threshold=float(g["threshold"]),
            direction=g.get("direction", "ge"),
            roi=tuple(g["roi"]) if "roi" in g else None,  # type: ignore
            luminance_threshold=g.get("luminance_threshold"),
            saturation_floor=g.get("saturation_floor"),
            description=g.get("description"),
        ))
    return description, gates


def _render_scene(module) -> tuple[np.ndarray, float]:
    astroray = _load_astroray()
    r = module.make_scene(astroray)
    r.set_seed(module.SEED)
    t0 = time.time()
    pixels = r.render(module.SAMPLES, module.MAX_DEPTH, None, True)
    dt = time.time() - t0
    return np.asarray(pixels, dtype=np.float32), dt


def _save_png(arr: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(arr, 0.0, 1.0)
    img = (clipped * 255.0 + 0.5).astype(np.uint8)
    Image.fromarray(img).save(path)


def _load_reference(scene_dir: Path) -> np.ndarray | None:
    # Prefer scene-local reference.png (display-referred, sRGB-encoded uint8).
    local_png = scene_dir / "reference.png"
    if local_png.exists():
        ref = np.asarray(Image.open(local_png).convert("RGB"), dtype=np.float32) / 255.0
        return ref
    # Future: EXR support via OpenImageIO; not strictly required for Phase 1.
    return None


def _save_reference(arr: np.ndarray, scene_dir: Path) -> Path:
    p = scene_dir / "reference.png"
    _save_png(arr, p)
    return p


def _evaluate_gate(spec: GateSpec, actual: np.ndarray, reference: np.ndarray | None) -> GateResult:
    """Dispatch to the metric for spec.type, compute pass/fail."""
    from .metrics import (
        compute_ssim,
        compute_delta_e_2000,
        compute_phash_distance,
        compute_hue_spread,
        compute_bright_coverage,
        compute_dark_disk_fraction,
    )

    notes = ""
    if spec.type in ("ssim", "delta_e_2000", "phash") and reference is None:
        return GateResult(spec=spec, measured=float("nan"), passed=False,
                          notes=f"gate {spec.type} requires a reference; none found")

    if spec.type == "ssim":
        measured, _ = compute_ssim(actual, reference)  # type: ignore[arg-type]
    elif spec.type == "delta_e_2000":
        mask = None
        if spec.roi is not None:
            mask = np.zeros(actual.shape[:2], dtype=bool)
            y0, y1, x0, x1 = spec.roi
            mask[y0:y1, x0:x1] = True
        measured, _ = compute_delta_e_2000(actual, reference, mask=mask)  # type: ignore[arg-type]
    elif spec.type == "phash":
        d, _ = compute_phash_distance(actual, reference)  # type: ignore[arg-type]
        measured = float(d)
    elif spec.type == "hue_spread":
        measured, _ = compute_hue_spread(
            actual,
            luminance_threshold=spec.luminance_threshold or 0.05,
            roi=spec.roi,
            saturation_floor=spec.saturation_floor or 0.05,
        )
    elif spec.type == "bright_coverage":
        measured, _ = compute_bright_coverage(
            actual,
            luminance_threshold=spec.luminance_threshold or 0.5,
            roi=spec.roi,
        )
    elif spec.type == "dark_disk":
        measured, _ = compute_dark_disk_fraction(
            actual,
            luminance_threshold=spec.luminance_threshold or 0.02,
            roi=spec.roi,
        )
    else:
        return GateResult(spec=spec, measured=float("nan"), passed=False,
                          notes=f"unknown gate type: {spec.type}")

    if spec.direction == "ge":
        passed = measured >= spec.threshold
    elif spec.direction == "le":
        passed = measured <= spec.threshold
    else:
        return GateResult(spec=spec, measured=measured, passed=False,
                          notes=f"unknown direction: {spec.direction}")
    return GateResult(spec=spec, measured=float(measured), passed=bool(passed), notes=notes)


def _write_report(
    scene_name: str,
    description: str,
    result: SceneResult,
    actual: np.ndarray,
    reference: np.ndarray | None,
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _save_png(actual, out_dir / "actual.png")
    if reference is not None:
        _save_png(reference, out_dir / "reference.png")
        diff = np.abs(actual - reference)
        _save_png(diff / max(diff.max(), 1e-6), out_dir / "diff.png")

    lines = [
        f"# {scene_name}",
        "",
        f"{description}",
        "",
        f"- Resolution: {result.width}×{result.height}",
        f"- Samples: {result.samples}",
        f"- Render walltime: {result.render_walltime_s:.3f}s",
        f"- Overall: **{'PASS' if result.passed else 'FAIL'}**",
        "",
        "## Gates",
        "",
        "| Type | Threshold | Direction | Measured | Pass |",
        "|------|-----------|-----------|----------|------|",
    ]
    for gr in result.gates:
        lines.append(
            f"| {gr.spec.type} | {gr.spec.threshold} | {gr.spec.direction} | "
            f"{gr.measured:.4f} | {'YES' if gr.passed else 'NO'} |"
        )
        if gr.notes:
            lines.append(f"  - note: {gr.notes}")
    lines.append("")
    if reference is None:
        lines.append("_No reference pinned yet — run with `--bless` to capture the current render as the reference._")
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def _enumerate_scenes(filter_names: list[str] | None, mode: str) -> list[Path]:
    if not _SCENES_ROOT.exists():
        return []
    dirs = [p for p in sorted(_SCENES_ROOT.iterdir()) if p.is_dir() and (p / "scene.py").exists()]
    if filter_names:
        wanted = set(filter_names)
        dirs = [p for p in dirs if p.name in wanted]
    if mode == "smoke":
        smoke_scenes = {"cornell-mini"}  # extend as the bank grows
        dirs = [p for p in dirs if p.name in smoke_scenes]
    return dirs


def run(scene_names: list[str] | None, mode: str, bless: bool) -> int:
    scene_dirs = _enumerate_scenes(scene_names, mode)
    if not scene_dirs:
        print("No scenes found. Add a scene under benchmarks/reference_bank/scenes/<name>/", file=sys.stderr)
        return 0  # not an error — empty bank is the Phase 1 expected state

    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H%M%S")
    sha = _git_sha()
    run_id = f"{timestamp}-{sha}"
    run_dir = _RESULTS_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    csv_rows: list[dict[str, Any]] = []
    overall_pass = True

    for scene_dir in scene_dirs:
        scene_name = scene_dir.name
        print(f"[reference_bank] {scene_name} ... ", end="", flush=True)
        module = _load_scene_module(scene_dir)
        description, gate_specs = _load_gates(scene_dir)

        try:
            actual, dt = _render_scene(module)
        except Exception as e:
            print(f"RENDER-ERROR: {e}")
            overall_pass = False
            csv_rows.append({"scene": scene_name, "status": "render_error", "error": str(e)})
            continue

        if bless:
            ref_path = _save_reference(actual, scene_dir)
            print(f"BLESSED -> {ref_path.relative_to(_REPO_ROOT)}")
            csv_rows.append({
                "scene": scene_name, "status": "blessed",
                "samples": module.SAMPLES, "walltime_s": round(dt, 3),
            })
            continue

        reference = _load_reference(scene_dir)
        result = SceneResult(
            name=scene_name, samples=module.SAMPLES, width=module.WIDTH,
            height=module.HEIGHT, render_walltime_s=dt,
        )
        for gs in gate_specs:
            result.gates.append(_evaluate_gate(gs, actual, reference))
        result.passed = all(gr.passed for gr in result.gates) and (
            reference is not None or not any(
                gr.spec.type in ("ssim", "delta_e_2000", "phash") for gr in result.gates
            )
        )

        scene_out = run_dir / scene_name
        _write_report(scene_name, description, result, actual, reference, scene_out)

        passed_count = sum(1 for gr in result.gates if gr.passed)
        total = len(result.gates)
        status = "PASS" if result.passed else "FAIL"
        print(f"{status} ({passed_count}/{total} gates, {dt:.2f}s)")
        if not result.passed:
            overall_pass = False
        csv_rows.append({
            "scene": scene_name, "status": status.lower(),
            "samples": module.SAMPLES, "walltime_s": round(dt, 3),
            "gates_passed": passed_count, "gates_total": total,
        })

    # Compact CSV history row.
    if csv_rows:
        csv_path = _BANK_ROOT / "history.csv"
        keys = sorted({k for row in csv_rows for k in row.keys()} | {"timestamp", "sha"})
        write_header = not csv_path.exists()
        with csv_path.open("a", encoding="utf-8") as f:
            if write_header:
                f.write(",".join(keys) + "\n")
            for row in csv_rows:
                row = dict(row)
                row["timestamp"] = timestamp
                row["sha"] = sha
                f.write(",".join(str(row.get(k, "")) for k in keys) + "\n")

    print(f"[reference_bank] run {run_id}: {'PASS' if overall_pass else 'FAIL'}")
    return 0 if overall_pass else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Visual reference bank runner (pkg104).")
    p.add_argument("--scenes", default=None, help="comma-separated scene names; default = all")
    p.add_argument("--mode", choices=("smoke", "full", "manual"), default="manual")
    p.add_argument("--bless", action="store_true",
                   help="Save current render as the pinned reference (owner-bless workflow).")
    args = p.parse_args(argv)
    names = args.scenes.split(",") if args.scenes else None
    return run(names, args.mode, args.bless)


if __name__ == "__main__":
    sys.exit(main())

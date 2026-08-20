# -*- coding: utf-8 -*-
"""pkg178 Stage-4 acceptance — thin-film iridescence A/B driver (Cycles-5.2 oracle).

For each thin-film config it spawns TWO subprocess-isolated headless-Blender legs
— CYCLES (oracle, CPU for determinism) and Astroray CUSTOM_RAYTRACER (GPU; the
thin-film GPU path shipped in PR #579) — rendering the SAME translated Blender
scene (``scenes.build_thinfilm_scene``), then compares them in LINEAR:

  * per-channel Astroray/Cycles mean-radiance ratio over the sphere ROI, gated on
    a band asserting BOTH bounds (pkg166; an iridescence energy GAIN fails the
    ceiling just as a loss fails the floor);
  * circular-mean hue angle per leg + the Astroray-vs-Cycles hue delta — the
    "hue-trajectory" the task asks for (how the iridescent tint tracks Cycles as
    thickness sweeps).

This IS the pkg178 "feature-matrix parity vs Cycles" acceptance gate for thin
film, run through the real addon Principled->native translation. The dielectric
kind is the analytically-exact Fresnel case (expected tight match); the conductor
kind is Astroray's RGB-upsample approximation (a residual hue gap is EXPECTED and
quantified here to size the per-lambda-conductor follow-up).

The metric/band layer is pure (tests/test_thin_film_ab_harness.py). Only ``run()``
needs Blender 5.2 + a built OpenMP-OFF addon .pyd (pkg119b runbook).

One command (run by the lead on hardware):
    python benchmarks/cycles-parity/thin_film/harness.py \
        --out test_results/pkg178_thinfilm_ab --res 128 --samples 256
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# repo root = .../Astroray ; this file is at benchmarks/cycles-parity/thin_film
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))  # for `benchmarks.reference_bank`
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for sibling `scenes`

import scenes as _scenes  # noqa: E402

SENTINEL = "PKG178TF_LEG"
_RENDER_LEG = Path(__file__).resolve().parent / "render_leg.py"

# Cross-engine per-channel ratio band. Same 0.85/1.15 default as pkg129 metal_ab
# (independent-RNG cross-ENGINE comparison carries translation + sampler
# differences on top of the internal GPU/CPU band). The lead tunes per-kind on the
# hardware run; both bounds always asserted.
DEFAULT_RATIO_LOW = 0.85
DEFAULT_RATIO_HIGH = 1.15


# --------------------------------------------------------------------------- #
# Pure metric layer (unit-tested without Blender/GPU)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Band:
    low: float
    high: float


def in_band(ratio: tuple[float, float, float], band: Band) -> bool:
    for v in ratio:
        if math.isnan(v) or v < band.low or v > band.high:
            return False
    return True


def per_channel_ratio(actual, reference) -> tuple[float, float, float]:
    """Mean Astroray/Cycles ratio per RGB channel (trivial — not a new metric)."""
    a = actual.reshape(-1, 3).mean(axis=0)
    r = reference.reshape(-1, 3).mean(axis=0)
    out = []
    for i in range(3):
        out.append(float(a[i] / r[i]) if r[i] > 1e-9 else float("nan"))
    return (out[0], out[1], out[2])


def sphere_roi(img):
    """ROI covering the sphere. The 0.9-radius sphere at dist 1.35 / 60deg fov has
    angular radius ~34deg > the 30deg half-fov, so it OVERFILLS the frame — the
    whole frame is sphere, no world background in view (verified: corner pixels are
    grazing-incidence sphere reflection, not the 0.6 world). Use the full disc
    (thin antialiased border trimmed). A central box would over-weight the dim
    near-normal-incidence cap, which for a dim dielectric makes the red-channel
    ratio a tiny-denominator artifact (pkg178 thin-film calibration note)."""
    h, w, _ = img.shape
    m = max(1, int(round(min(h, w) * 0.04)))
    return img[m:h - m, m:w - m]


def hue_angle_deg(roi) -> float:
    """Circular-mean hue angle (deg) over the ROI, magnitude-normalised.

    Reuses the pkg104 reference-bank RGB->hue (NOT a new metric); mirrors
    conductor_hue_sweep so the standalone Astroray reference and this oracle gate
    read hue the same way.
    """
    import numpy as np
    from benchmarks.reference_bank.metrics.hue_spread import _rgb_to_hue
    mx = roi.max()
    rgb_n = roi / mx if mx > 0 else roi
    hue = _rgb_to_hue(rgb_n)
    h = hue[~np.isnan(hue)]
    if h.size < 4:
        return float("nan")
    z = np.exp(1j * h)
    return float((np.angle(z.mean()) % (2 * np.pi)) * 180.0 / np.pi)


def _hue_delta_deg(a: float, b: float) -> float:
    """Smallest signed circular distance |a-b| in [0,180]."""
    if math.isnan(a) or math.isnan(b):
        return float("nan")
    d = abs(a - b) % 360.0
    return d if d <= 180.0 else 360.0 - d


@dataclass
class CellResult:
    name: str
    kind: str
    thickness_nm: float
    film_ior: float
    status: str  # "pass" | "fail" | "crash"
    ratio: tuple[float, float, float] | None = None
    astroray_rgb: tuple[float, float, float] | None = None
    cycles_rgb: tuple[float, float, float] | None = None
    astroray_hue: float | None = None
    cycles_hue: float | None = None
    hue_delta_deg: float | None = None
    ssim: float | None = None
    delta_e: float | None = None
    notes: str = ""


def compare_cell(cfg, astroray_img, cycles_img, band: Band) -> CellResult:
    """Per-channel ratio + hue metrics + gate for one thin-film cell."""
    from benchmarks.reference_bank.metrics import compute_ssim, compute_delta_e_2000
    a_roi, c_roi = sphere_roi(astroray_img), sphere_roi(cycles_img)
    ratio = per_channel_ratio(a_roi, c_roi)
    a_hue, c_hue = hue_angle_deg(a_roi), hue_angle_deg(c_roi)
    ssim, _ = compute_ssim(astroray_img, cycles_img)
    de, _ = compute_delta_e_2000(astroray_img, cycles_img)
    a_mean = a_roi.reshape(-1, 3).mean(axis=0)
    c_mean = c_roi.reshape(-1, 3).mean(axis=0)
    return CellResult(
        name=cfg.name, kind=cfg.kind, thickness_nm=cfg.thickness_nm,
        film_ior=cfg.film_ior,
        status="pass" if in_band(ratio, band) else "fail",
        ratio=ratio,
        astroray_rgb=(float(a_mean[0]), float(a_mean[1]), float(a_mean[2])),
        cycles_rgb=(float(c_mean[0]), float(c_mean[1]), float(c_mean[2])),
        astroray_hue=a_hue, cycles_hue=c_hue,
        hue_delta_deg=_hue_delta_deg(a_hue, c_hue),
        ssim=float(ssim), delta_e=float(de))


# --------------------------------------------------------------------------- #
# Blender / .pyd discovery
# --------------------------------------------------------------------------- #

def _find_blender() -> Path | None:
    env = os.environ.get("BLENDER_EXE", "")
    if env and Path(env).is_file():
        return Path(env)
    # pkg178-D1: Blender 5.2 LTS is the parity oracle. Prefer it explicitly.
    for c in (r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
              r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"):
        if Path(c).is_file():
            return Path(c)
    on_path = shutil.which("blender")
    return Path(on_path) if on_path else None


def _pyd_dir(root: Path) -> Path | None:
    for cand in (root / "build_blender_addon_cuda", root / "build_blender_addon_tcnn",
                 root / "build_blender_addon", root / "build_cuda"):
        if list(cand.glob("astroray*.pyd")):
            return cand
    return None


def _run_leg(blender: Path, cfg, engine: str, device: str, out_stem: Path,
             res: int, samples: int, timeout: int, env: dict) -> tuple[bool, str]:
    cmd = [
        str(blender), "--background", "--factory-startup",
        "--python", str(_RENDER_LEG), "--",
        "--config", cfg.name, "--engine", engine, "--device", device,
        "--out", str(out_stem), "--res", str(res), "--samples", str(samples),
    ]
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT after {timeout}s"
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    ok = f"{SENTINEL} FAIL" not in combined and f"{SENTINEL} PASS" in combined
    ok = ok and out_stem.with_suffix(".npy").exists()
    return ok, combined[-1500:]


def run(out_dir: Path, *, res: int = 128, samples: int = 256, timeout: int = 900,
        band: Band | None = None) -> int:
    import numpy as np

    band = band or Band(DEFAULT_RATIO_LOW, DEFAULT_RATIO_HIGH)
    blender = _find_blender()
    if blender is None:
        print("[pkg178tf] Blender not found (set BLENDER_EXE) — cannot run legs.",
              file=sys.stderr)
        return 2
    build_dir = _pyd_dir(_REPO_ROOT) or _pyd_dir(_REPO_ROOT.parent / "Astroray")
    if build_dir is None:
        print("[pkg178tf] no astroray*.pyd found — build the addon first.",
              file=sys.stderr)
        return 2
    print(f"[pkg178tf] Blender: {blender}", flush=True)
    print(f"[pkg178tf] addon .pyd dir: {build_dir}", flush=True)

    env = os.environ.copy()
    env["ASTRORAY_PYD_DIR"] = str(build_dir)
    env["ASTRORAY_BUILD_DIR"] = str(_REPO_ROOT / "build_cuda")

    out_dir = out_dir.resolve()
    renders_dir = out_dir / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)

    results: list[CellResult] = []
    for cfg in _scenes.thinfilm_sweep():
        print(f"[pkg178tf] {cfg.name} ...", flush=True)
        arrays: dict[str, Any] = {}
        crash = None
        for engine, device in (("CYCLES", "cpu"), ("CUSTOM_RAYTRACER", "gpu")):
            tag = "cycles" if engine == "CYCLES" else "astroray_gpu"
            stem = renders_dir / f"{cfg.name}__{tag}"
            ok, log_tail = _run_leg(blender, cfg, engine, device, stem, res,
                                    samples, timeout, env)
            if not ok:
                crash = f"{tag} leg did not PASS. log tail:\n{log_tail}"
                break
            arrays[tag] = np.load(stem.with_suffix(".npy"))
        if crash is not None:
            results.append(CellResult(cfg.name, cfg.kind, cfg.thickness_nm,
                                      cfg.film_ior, "crash", notes=crash))
            print(f"    CRASH: {crash.splitlines()[0]}", flush=True)
            continue

        r = compare_cell(cfg, arrays["astroray_gpu"], arrays["cycles"], band)
        results.append(r)
        print(f"    {r.status.upper()} ratio={tuple(round(x, 3) for x in r.ratio)} "
              f"hue A/C={r.astroray_hue:.0f}/{r.cycles_hue:.0f} "
              f"dHue={r.hue_delta_deg:.0f} dE={r.delta_e:.2f}", flush=True)

    write_reports(results, out_dir, band)
    failed = [r for r in results if r.status in ("fail", "crash")]
    return 1 if failed else 0


# --------------------------------------------------------------------------- #
# Reports (pure)
# --------------------------------------------------------------------------- #

def _kind_summary(results: list[CellResult], kind: str) -> dict[str, Any]:
    rows = [r for r in results if r.kind == kind and r.ratio is not None]
    if not rows:
        return {"n": 0}
    max_ratio_dev = max(max(abs(x - 1.0) for x in r.ratio) for r in rows)
    hue_deltas = [r.hue_delta_deg for r in rows if not math.isnan(r.hue_delta_deg)]
    return {
        "n": len(rows),
        "passed": sum(1 for r in rows if r.status == "pass"),
        "max_abs_ratio_dev": round(max_ratio_dev, 4),
        "max_hue_delta_deg": round(max(hue_deltas), 2) if hue_deltas else None,
        "mean_hue_delta_deg": round(sum(hue_deltas) / len(hue_deltas), 2) if hue_deltas else None,
    }


def write_reports(results: list[CellResult], out_dir: Path, band: Band) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {k: _kind_summary(results, k) for k in ("dielectric", "conductor")}
    payload = {
        "band": {"low": band.low, "high": band.high},
        "summary": summary,
        "cells": [asdict(r) for r in results],
    }
    (out_dir / "thinfilm_ab_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# pkg178 thin-film A/B — Cycles-5.2 oracle vs Astroray GPU",
        "",
        (f"Per-channel Astroray/Cycles linear mean-ratio band "
         f"[{band.low}, {band.high}] (both bounds; pkg166). Hue = circular-mean "
         "iridescence angle over the sphere ROI."),
        "",
        "## Verdict",
        "",
        f"- **dielectric** (analytically-exact Fresnel): {summary['dielectric']}",
        f"- **conductor** (RGB-upsample approx): {summary['conductor']}",
        "",
        "## Per-cell",
        "",
        "| Config | kind | d(nm) | filmIOR | Status | R/G/B ratio | hue A/C (deg) | dHue | dE2000 |",
        "|--------|------|-------|---------|--------|-------------|---------------|------|--------|",
    ]
    for r in results:
        if r.ratio is None:
            lines.append(f"| {r.name} | {r.kind} | {r.thickness_nm:.0f} | "
                         f"{r.film_ior:.1f} | {r.status} | - | - | - | - |")
            continue
        ratio = "/".join(f"{x:.3f}" for x in r.ratio)
        lines.append(
            f"| {r.name} | {r.kind} | {r.thickness_nm:.0f} | {r.film_ior:.1f} | "
            f"{r.status} | {ratio} | {r.astroray_hue:.0f}/{r.cycles_hue:.0f} | "
            f"{r.hue_delta_deg:.0f} | {r.delta_e:.2f} |")
    (out_dir / "thinfilm_ab_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[pkg178tf] wrote {out_dir / 'thinfilm_ab_report.json'} and .md", flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="pkg178 thin-film A/B (Cycles-5.2 oracle).")
    p.add_argument("--out", type=Path,
                   default=_REPO_ROOT / "test_results" / "pkg178_thinfilm_ab")
    p.add_argument("--res", type=int, default=128)
    p.add_argument("--samples", type=int, default=256)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--ratio-low", type=float, default=DEFAULT_RATIO_LOW)
    p.add_argument("--ratio-high", type=float, default=DEFAULT_RATIO_HIGH)
    args = p.parse_args(argv)
    return run(args.out, res=args.res, samples=args.samples, timeout=args.timeout,
               band=Band(args.ratio_low, args.ratio_high))


if __name__ == "__main__":
    sys.exit(main())

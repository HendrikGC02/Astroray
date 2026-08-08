# -*- coding: utf-8 -*-
"""pkg119 Phase B - differential parity harness driver (pure Python, no bpy).

Reads the Phase-A coverage matrix, selects the SUPPORTED/APPROXIMATED cells as
the differential test population, and for each feature (plus a curated set of
COMPOSITE scenes) spawns two subprocess-isolated headless-Blender render legs -
one CYCLES oracle, one CUSTOM_RAYTRACER (per pkg71 discipline). It then compares
the two linear renders with the pkg104 reference-bank metrics (compute_ssim +
compute_delta_e_2000 + a trivial per-channel mean ratio - NOT a new metric
stack), gates each feature, and triages every failure into exactly one of
NOT-IMPLEMENTED / TRANSLATION-BUG / INTENTIONAL-DIVERGENCE (triage.py).

Crash isolation (spec Phase-B acceptance): any leg that crashes, times out, or
fails to print its ``PKG119B_LEG PASS`` sentinel is recorded as a crashed
feature and the run CONTINUES. A crashed feature also back-propagates a note to
close its Phase-A UNKNOWN cell.

One command:
    python -m benchmarks.blender_parity.harness \
        --matrix docs/blender_parity/coverage_matrix.json \
        --out test_results/blender_parity_diff

The metric/triage/report layer is import-safe and unit-tested without Blender or
a GPU (tests/test_blender_parity_harness.py). Only ``run()`` needs Blender.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
# reference_bank is a sibling package under benchmarks/; make it importable.
sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.blender_parity import triage as T  # noqa: E402

SENTINEL = "PKG119B_LEG"
DEFAULT_MATRIX = _REPO_ROOT / "docs" / "blender_parity" / "coverage_matrix.json"
_RENDER_LEG = Path(__file__).resolve().parent / "render_leg.py"


# --------------------------------------------------------------------------- #
# Feature selection (pure)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Feature:
    category: str
    feature: str
    bl_idname: str
    phase_a_bucket: str  # SUPPORTED or APPROXIMATED (worst-case across sockets)

    @property
    def key(self) -> str:
        return f"{self.category}:{self.feature}"


# Categories that have a differential visual scene generator. Others (e.g.
# render_settings sampling knobs) have no meaningful oracle diff and are recorded
# with a skip_reason per pkg71 discipline rather than silently dropped.
RENDERABLE_CATEGORIES = {"shader_node", "light", "camera", "world"}


def select_features(matrix_rows: list[dict[str, Any]]) -> list[Feature]:
    """Dedup the SUPPORTED/APPROXIMATED matrix rows to unique features.

    A feature is APPROXIMATED if ANY of its rows is APPROXIMATED (worst case),
    else SUPPORTED. bl_idname is taken from the first row that carries one.
    """
    buckets: dict[tuple[str, str], set[str]] = defaultdict(set)
    idnames: dict[tuple[str, str], str] = {}
    for r in matrix_rows:
        cls = r.get("classification")
        if cls not in ("SUPPORTED", "APPROXIMATED"):
            continue
        k = (r["category"], r["feature"])
        buckets[k].add(cls)
        if not idnames.get(k) and r.get("bl_idname"):
            idnames[k] = r["bl_idname"]
    feats: list[Feature] = []
    for (cat, feat), cls_set in sorted(buckets.items()):
        bucket = "APPROXIMATED" if "APPROXIMATED" in cls_set else "SUPPORTED"
        feats.append(Feature(cat, feat, idnames.get((cat, feat), ""), bucket))
    return feats


# --------------------------------------------------------------------------- #
# Per-feature result (pure data)
# --------------------------------------------------------------------------- #

@dataclass
class FeatureResult:
    category: str
    feature: str
    phase_a_bucket: str
    status: str  # "pass" | "fail" | "crash" | "skip"
    ssim: float | None = None
    delta_e: float | None = None
    ratio: tuple[float, float, float] | None = None
    triage_bucket: str | None = None
    triage_reason: str | None = None
    skip_reason: str | None = None
    notes: str = ""


# --------------------------------------------------------------------------- #
# Metric comparison (reuses pkg104 reference_bank; NO new metric stack)
# --------------------------------------------------------------------------- #

def per_channel_ratio(actual, reference) -> tuple[float, float, float]:
    """Mean Astroray/Cycles ratio per RGB channel (trivial - not a new metric)."""
    import numpy as np
    a = actual.reshape(-1, 3).mean(axis=0)
    r = reference.reshape(-1, 3).mean(axis=0)
    out = []
    for i in range(3):
        out.append(float(a[i] / r[i]) if r[i] > 1e-9 else float("nan"))
    return (out[0], out[1], out[2])


def compare_and_triage(feat: Feature, actual, reference) -> FeatureResult:
    """Run the reference-bank metrics, gate, and triage a single feature."""
    from benchmarks.reference_bank.metrics import compute_ssim, compute_delta_e_2000

    ssim, _ = compute_ssim(actual, reference)
    delta_e, _ = compute_delta_e_2000(actual, reference)
    ratio = per_channel_ratio(actual, reference)

    gr = T.gate(ssim, delta_e, ratio)
    res = FeatureResult(
        category=feat.category, feature=feat.feature,
        phase_a_bucket=feat.phase_a_bucket,
        status="pass" if gr.passed else "fail",
        ssim=ssim, delta_e=delta_e, ratio=ratio,
    )
    if not gr.passed:
        bucket, reason = T.triage(feat.feature, feat.phase_a_bucket, gr)
        res.triage_bucket = bucket
        res.triage_reason = reason
    return res


# --------------------------------------------------------------------------- #
# Render-leg orchestration (needs Blender)
# --------------------------------------------------------------------------- #

def _find_blender() -> Path | None:
    env = os.environ.get("BLENDER_EXE", "")
    if env and Path(env).is_file():
        return Path(env)
    on_path = shutil.which("blender")
    if on_path:
        return Path(on_path)
    for c in (r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
              r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"):
        if Path(c).is_file():
            return Path(c)
    return None


def _pyd_dir(root: Path) -> Path | None:
    # The Astroray leg imports astroray INSIDE Blender's Python (render_leg),
    # so it MUST be an OpenMP-OFF build or MinGW libgomp deadlocks in Blender
    # (memory mingw_openmp_blender_deadlock). Prefer the addon build dirs
    # (build_blender_addon.py forces -DASTRORAY_DISABLE_OPENMP=ON) over the
    # plain build_cuda (OpenMP ON — deadlocks headless-Blender renders).
    for cand in (root / "build_blender_addon_cuda", root / "build_blender_addon_tcnn",
                 root / "build_blender_addon", root / "build_cuda",
                 root / "build_cuda" / "Release"):
        if list(cand.glob("astroray*.pyd")):
            return cand
    return None


def _run_leg(blender: Path, feat: Feature, engine: str, out_stem: Path,
             res: int, samples: int, timeout: int, env: dict) -> tuple[bool, str]:
    """Spawn one headless-Blender leg. Returns (ok, log_tail)."""
    cmd = [
        str(blender), "--background", "--factory-startup",
        "--python", str(_RENDER_LEG), "--",
        "--category", feat.category, "--feature", feat.feature,
        "--bl-idname", feat.bl_idname, "--engine", engine,
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


def run(matrix_path: Path, out_dir: Path, *, res: int = 128, samples: int = 64,
        timeout: int = 300, include_composites: bool = True) -> int:
    import numpy as np

    blender = _find_blender()
    if blender is None:
        print("[pkg119b] Blender not found (set BLENDER_EXE) - cannot run legs.",
              file=sys.stderr)
        return 2
    build_dir = _pyd_dir(_REPO_ROOT) or _pyd_dir(_REPO_ROOT.parent / "Astroray")
    if build_dir is None:
        print("[pkg119b] no astroray*.pyd found - build the addon first.",
              file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["ASTRORAY_PYD_DIR"] = str(build_dir)
    env["ASTRORAY_BUILD_DIR"] = str(_REPO_ROOT / "build_cuda")

    matrix_rows = json.loads(Path(matrix_path).read_text(encoding="utf-8"))
    features = select_features(matrix_rows)
    if include_composites:
        from benchmarks.blender_parity import scene_library
        for name in scene_library.COMPOSITE_SCENES:
            features.append(Feature("composite", name, "", "SUPPORTED"))

    # Resolve to ABSOLUTE: render_leg runs inside Blender whose CWD is NOT the
    # harness CWD, so a relative out-stem makes Blender save the .exr under a
    # different root (observed: C:\test_results\...) than render_leg then looks
    # for -> "no render output". Absolute stems make both legs agree.
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    renders_dir = out_dir / "renders"
    renders_dir.mkdir(exist_ok=True)

    results: list[FeatureResult] = []
    for feat in features:
        print(f"[pkg119b] {feat.key} ...", flush=True)
        if feat.category not in RENDERABLE_CATEGORIES and feat.category != "composite":
            results.append(FeatureResult(
                feat.category, feat.feature, feat.phase_a_bucket, "skip",
                skip_reason=f"no differential scene for category {feat.category} "
                            "(sampling/meta feature - no oracle visual diff)"))
            continue

        legs_ok = True
        arrays = {}
        for engine in ("CYCLES", "CUSTOM_RAYTRACER"):
            stem = renders_dir / f"{feat.category}__{feat.feature}__{engine.lower()}"
            ok, log_tail = _run_leg(blender, feat, engine, stem, res, samples,
                                    timeout, env)
            if not ok:
                results.append(FeatureResult(
                    feat.category, feat.feature, feat.phase_a_bucket, "crash",
                    notes=f"{engine} leg did not PASS; back-propagates to close "
                          f"Phase-A UNKNOWN cell. log tail:\n{log_tail}"))
                legs_ok = False
                break
            arrays[engine] = np.load(stem.with_suffix(".npy"))
        if not legs_ok:
            continue

        try:
            res_ft = compare_and_triage(feat, arrays["CUSTOM_RAYTRACER"], arrays["CYCLES"])
        except Exception as exc:  # noqa: BLE001
            results.append(FeatureResult(
                feat.category, feat.feature, feat.phase_a_bucket, "crash",
                notes=f"metric comparison raised {type(exc).__name__}: {exc}"))
            continue
        results.append(res_ft)
        print(f"    {res_ft.status.upper()} ssim={res_ft.ssim:.4f} "
              f"dE={res_ft.delta_e:.3f}"
              + (f" -> {res_ft.triage_bucket}" if res_ft.triage_bucket else ""),
              flush=True)

    write_reports(results, out_dir)
    # A crashed feature is a hard failure of "no crash on any feature"; a
    # triaged FAIL is expected output, not a harness failure.
    crashes = [r for r in results if r.status == "crash"]
    return 1 if crashes else 0


# --------------------------------------------------------------------------- #
# Reports (pure)
# --------------------------------------------------------------------------- #

def summarize(results: list[FeatureResult]) -> dict[str, Any]:
    status = Counter(r.status for r in results)
    triage = Counter(r.triage_bucket for r in results if r.triage_bucket)
    return {
        "total": len(results),
        "status": dict(status),
        "triage": dict(triage),
        "follow_up_candidates": [
            {"feature": f"{r.category}:{r.feature}", "bucket": r.triage_bucket,
             "reason": r.triage_reason}
            for r in results
            if r.triage_bucket in (T.NOT_IMPLEMENTED, T.TRANSLATION_BUG)
        ],
    }


def write_reports(results: list[FeatureResult], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(results)
    payload = {"summary": summary, "features": [asdict(r) for r in results]}
    (out_dir / "triage_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Blender Differential Parity - Triage Report (pkg119 Phase B)",
        "",
        "Cycles (oracle) vs CUSTOM_RAYTRACER, gated on reference-bank SSIM/dE2000.",
        "",
        "## Summary",
        "",
        f"- Total features: {summary['total']}",
        f"- Status: {summary['status']}",
        f"- Triage: {summary['triage']}",
        "",
        "## Follow-up-package candidates (NOT-IMPLEMENTED / TRANSLATION-BUG)",
        "",
    ]
    if summary["follow_up_candidates"]:
        for c in summary["follow_up_candidates"]:
            lines.append(f"- **{c['feature']}** [{c['bucket']}] - {c['reason']}")
    else:
        lines.append("_none_")
    lines += ["", "## Per-feature results", "",
              "| Feature | Phase-A | Status | SSIM | dE2000 | Triage |",
              "|---------|---------|--------|------|--------|--------|"]
    for r in results:
        ssim = f"{r.ssim:.4f}" if r.ssim is not None else "-"
        de = f"{r.delta_e:.3f}" if r.delta_e is not None else "-"
        tri = r.triage_bucket or (r.skip_reason or "") if r.status != "pass" else ""
        lines.append(f"| {r.category}:{r.feature} | {r.phase_a_bucket} | "
                     f"{r.status} | {ssim} | {de} | {tri} |")
        if r.status == "crash" and r.notes:
            lines.append(f"  - crash: {r.notes.splitlines()[0]}")
    (out_dir / "triage_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[pkg119b] wrote {out_dir / 'triage_report.json'} and .md", flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Blender differential parity harness (pkg119 Phase B).")
    p.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    p.add_argument("--out", type=Path, default=_REPO_ROOT / "test_results" / "blender_parity_diff")
    p.add_argument("--res", type=int, default=128)
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--no-composites", action="store_true")
    args = p.parse_args(argv)
    return run(args.matrix, args.out, res=args.res, samples=args.samples,
               timeout=args.timeout, include_composites=not args.no_composites)


if __name__ == "__main__":
    sys.exit(main())

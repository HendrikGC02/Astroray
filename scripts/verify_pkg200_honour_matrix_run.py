# -*- coding: utf-8 -*-
"""pkg200 — native-settings F12 pixel-honour matrix: A/B render driver (outer).

The ONE reusable A/B honour driver (scripts/README.md). Pure orchestration, no
bpy: for each (Blender version, matrix row) it spawns the in-Blender leg
(``verify_pkg200_honour_matrix.py``) which renders variant A and B as 32-bit
LINEAR EXRs through the real F12 path, then reads those EXRs with cv2
(IMREAD_UNCHANGED — memory ``gamma-furnace-cannot-detect-energy-gain``; imageio
silently corrupts float EXR), computes per-channel LINEAR statistics, and runs
the row's predicate (PASS / HONEST-FAIL / NEEDS-VISUAL / LIMITATION).

Gate discipline: a leg is trusted only if it prints ``PKG200_LEG PASS`` (never
the Blender exit code — pkg175 rule). Metric is per-channel mean/max/variance,
NEVER SSIM (memory ``ssim-wrong-gate-for-independent-rng``). Seeds are pinned
nonzero per row.

One command (holds the GPU lock for the whole sweep — batch it):
    python scripts/verify_pkg200_honour_matrix_run.py \
        --addon-dir dist/astroray \
        --blender "C:/Program Files/Blender Foundation/Blender 5.1/blender.exe" \
        --blender "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" \
        --out test_results/pkg200_honour

Subset / smoke:
    ... --rows film_exposure,max_bounces
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))

import pkg200_honour_matrix as M  # noqa: E402

_LEG = _REPO / "scripts" / "verify_pkg200_honour_matrix.py"
SENTINEL = "PKG200_LEG"


# --------------------------------------------------------------------------- #
# EXR read + statistics (cv2, per-channel LINEAR — NOT imageio, NOT SSIM)
# --------------------------------------------------------------------------- #
def _read_exr(path: Path):
    """(rgb HxWx3 float64, alpha HxW float64 or None). BGR(A) -> RGB."""
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None, None
    img = np.asarray(img, dtype="float64")
    if img.ndim != 3 or img.shape[2] < 3:
        return None, None
    rgb = img[..., 2::-1]  # BGR -> RGB
    alpha = img[..., 3] if img.shape[2] >= 4 else None
    return rgb, alpha


def _lum(rgb):
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def _stats(path: Path) -> "M.LegStats | None":
    import numpy as np  # type: ignore
    rgb, alpha = _read_exr(path)
    if rgb is None:
        return None
    rgb = np.nan_to_num(rgb, nan=0.0, posinf=0.0, neginf=0.0)
    flat = rgb.reshape(-1, 3)
    mean = tuple(float(x) for x in flat.mean(axis=0))
    maxv = tuple(float(x) for x in flat.max(axis=0))
    var = tuple(float(x) for x in flat.var(axis=0))
    lum = _lum(rgb)
    gy, gx = np.gradient(lum)
    grad_mean = float(np.hypot(gx, gy).mean())
    hi_pct = float(np.percentile(lum, 99.5))
    alpha_mean = float(np.nan_to_num(alpha).mean()) if alpha is not None else 1.0
    return M.LegStats(mean, maxv, var, float(lum.mean()), float(lum.max()),
                      float(lum.var()), alpha_mean, grad_mean, hi_pct,
                      (rgb.shape[0], rgb.shape[1]))


def _cross(a_path: Path, b_path: Path) -> "M.Cross | None":
    import numpy as np  # type: ignore
    ra, _ = _read_exr(a_path)
    rb, _ = _read_exr(b_path)
    if ra is None or rb is None or ra.shape != rb.shape:
        return None
    la = np.nan_to_num(_lum(ra))
    lb = np.nan_to_num(_lum(rb))
    d = np.abs(la - lb)
    return M.Cross(float(d.mean()), float(d.max()), bool(d.max() <= 1e-5))


def _write_png(exr: Path, png: Path):
    """sRGB tonemap for the multimodal visual-inspection rows."""
    try:
        os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
        import cv2  # type: ignore
        import numpy as np  # type: ignore
        rgb, _ = _read_exr(exr)
        if rgb is None:
            return
        rgb = np.nan_to_num(np.clip(rgb, 0, None))
        srgb = np.where(rgb <= 0.0031308, rgb * 12.92,
                        1.055 * rgb ** (1 / 2.4) - 0.055)
        bgr = np.clip(srgb[..., ::-1], 0, 1) * 255
        cv2.imwrite(str(png), bgr.astype("uint8"))
    except Exception:  # noqa: BLE001 — PNG is cosmetic
        pass


# --------------------------------------------------------------------------- #
# Leg orchestration
# --------------------------------------------------------------------------- #
@dataclass
class RowResult:
    row: str
    stage: str
    kind: str
    blender: str
    scene: str
    verdict: str
    detail: str
    a: dict | None = None
    b: dict | None = None
    note: str = ""


def _run_leg(blender: Path, row: M.Row, out_dir: Path, env: dict, timeout: int):
    a = (out_dir / f"{row.name}__A.exr").resolve()
    b = (out_dir / f"{row.name}__B.exr").resolve()
    for f in (a, b):
        if f.exists():
            f.unlink()
    cmd = [str(blender), "--background", "--factory-startup",
           "--python", str(_LEG), "--",
           "--row", row.name, "--out-a", str(a), "--out-b", str(b)]
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return None, None, f"TIMEOUT after {timeout}s"
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if f"{SENTINEL} FAIL" in out or f"{SENTINEL} PASS" not in out:
        tail = "\n".join(out.strip().splitlines()[-12:])
        return None, None, f"leg did not PASS:\n{tail}"
    return a, b, ""


def _sib(path: Path, tag: str) -> Path:
    return path.with_name(path.stem + tag + path.suffix)


def _evaluate(row: M.Row, a_path: Path, b_path: Path) -> tuple[str, str, dict, dict]:
    sa = _stats(a_path)
    sb = _stats(b_path)
    if sa is None or sb is None:
        return M.ERROR, "EXR unreadable via cv2", {}, {}

    if row.noise_pair:
        # MC noise = per-pixel |seedA - seedB| mean at each spp. Must fall ~1/2
        # for a 4x spp step (1/sqrt(N)); mean stays stable.
        n_lo = _cross(a_path, _sib(a_path, "2"))
        n_hi = _cross(b_path, _sib(b_path, "2"))
        if n_lo is None or n_hi is None or n_lo.lum_abs_diff_mean <= 1e-9:
            return M.ERROR, "noise-pair frames unreadable", asdict(sa), asdict(sb)
        noise_ratio = n_hi.lum_abs_diff_mean / n_lo.lum_abs_diff_mean
        mean_ratio = sb.lum_mean / sa.lum_mean if sa.lum_mean > 1e-9 else float("nan")
        detail = (f"MC-noise({row.samples}spp)={n_lo.lum_abs_diff_mean:.4g} "
                  f"({row.samples_hi}spp)={n_hi.lum_abs_diff_mean:.4g} "
                  f"ratio={noise_ratio:.3f}; mean ratio={mean_ratio:.3f}")
        if 0.9 <= mean_ratio <= 1.1 and noise_ratio < 0.65:
            return M.PASS, detail + " (noise falls ~1/sqrt(N))", asdict(sa), asdict(sb)
        return M.HONEST_FAIL, detail + " (noise did not fall ~1/sqrt(N))", asdict(sa), asdict(sb)

    cross = _cross(a_path, b_path)
    verdict, detail = row.predicate(sa, sb, cross)
    return verdict, detail, asdict(sa), asdict(sb)


def run(blenders: list[Path], addon_dir: Path, out_dir: Path, rows: list[M.Row],
        timeout: int) -> list[RowResult]:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[RowResult] = []

    for blender in blenders:
        tag = blender.parent.name.replace("Blender ", "bl") or blender.stem
        env = os.environ.copy()
        env["ASTRORAY_SMOKE_ADDON_DIR"] = str(addon_dir.resolve())
        env["OPENCV_IO_ENABLE_OPENEXR"] = "1"
        renders = out_dir / tag
        renders.mkdir(parents=True, exist_ok=True)

        for row in rows:
            if row.kind == "limitation":
                results.append(RowResult(
                    row.name, row.stage, row.kind, tag, row.scene,
                    M.LIMITATION,
                    "viewport-only control — not exercisable via headless F12",
                    note=row.note))
                print(f"[{tag}] {row.name:24s} LIMITATION (viewport-only)", flush=True)
                continue

            t0 = time.time()
            a_path, b_path, err = _run_leg(blender, row, renders, env, timeout)
            if err:
                results.append(RowResult(row.name, row.stage, row.kind, tag,
                                         row.scene, M.ERROR, err, note=row.note))
                print(f"[{tag}] {row.name:24s} ERROR ({err.splitlines()[0]})", flush=True)
                continue

            verdict, detail, sa, sb = _evaluate(row, a_path, b_path)
            if row.kind == "visual":
                _write_png(a_path, renders / f"{row.name}__A.png")
                _write_png(b_path, renders / f"{row.name}__B.png")
            results.append(RowResult(row.name, row.stage, row.kind, tag, row.scene,
                                     verdict, detail, sa, sb, note=row.note))
            print(f"[{tag}] {row.name:24s} {verdict}  {detail}  ({time.time()-t0:.1f}s)",
                  flush=True)

    _write_reports(results, out_dir)
    return results


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #
def _write_reports(results: list[RowResult], out_dir: Path):
    (out_dir / "results.json").write_text(
        json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")

    lines = ["# pkg200 — Native-settings F12 pixel-honour matrix — results", "",
             f"Rows: {len(results)}  (per Blender version)", "",
             "| Stage | Row | Scene | Blender | Kind | Verdict | Measured |",
             "|-------|-----|-------|---------|------|---------|----------|"]
    for r in sorted(results, key=lambda x: (x.stage, x.row, x.blender)):
        lines.append(f"| {r.stage} | {r.row} | {r.scene} | {r.blender} | "
                     f"{r.kind} | {r.verdict} | {r.detail} |")
    verdicts = {}
    for r in results:
        verdicts[r.verdict] = verdicts.get(r.verdict, 0) + 1
    lines += ["", "## Verdict tally", "", f"`{verdicts}`", "",
              "## Known gaps (recorded, not fixed here)", ""]
    for k, v in M.KNOWN_GAPS.items():
        lines.append(f"- **{k}** — {v}")
    (out_dir / "results.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[pkg200] wrote {out_dir / 'results.md'} and results.json", flush=True)


def _find_blenders(explicit: list[str]) -> list[Path]:
    if explicit:
        return [Path(b) for b in explicit]
    found = []
    for c in (r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
              r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"):
        if Path(c).is_file():
            found.append(Path(c))
    return found


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="pkg200 honour-matrix A/B driver.")
    p.add_argument("--addon-dir", required=True, type=Path,
                   help="staged/installed addon dir (astroray*.pyd + __init__.py)")
    p.add_argument("--blender", action="append", default=[],
                   help="blender.exe (repeatable); default = 5.1 + 5.2 if present")
    p.add_argument("--out", type=Path, default=_REPO / "test_results" / "pkg200_honour")
    p.add_argument("--rows", default="", help="comma list of row names (default: all)")
    p.add_argument("--timeout", type=int, default=600)
    args = p.parse_args(argv)

    M.check_completeness()  # Stage-0 gate before any render

    blenders = _find_blenders(args.blender)
    if not blenders:
        print("[pkg200] no Blender found (pass --blender)", file=sys.stderr)
        return 2
    if not args.addon_dir.exists():
        print(f"[pkg200] addon dir not found: {args.addon_dir}", file=sys.stderr)
        return 2

    if args.rows:
        want = [s.strip() for s in args.rows.split(",") if s.strip()]
        rows = [M.get_row(n) for n in want]
    else:
        rows = list(M.MATRIX)

    results = run(blenders, args.addon_dir, args.out, rows, args.timeout)
    errs = [r for r in results if r.verdict == M.ERROR]
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())

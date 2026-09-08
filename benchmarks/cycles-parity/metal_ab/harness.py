# -*- coding: utf-8 -*-
"""pkg129 (narrowed) — live-Cycles rough-metal A/B driver.

For each rough-metal config it spawns THREE subprocess-isolated headless-Blender
legs — CYCLES (oracle), Astroray CPU, Astroray GPU — then compares each Astroray
leg against the Cycles oracle in LINEAR with the pkg104 reference-bank metrics
(``compute_ssim`` + ``compute_delta_e_2000``, informational) plus a per-channel
mean-radiance ratio gated on a band that asserts BOTH floor and ceiling (pkg166
rules; memory gamma-furnace-cannot-detect-energy-gain — the ceiling is
load-bearing, an energy GAIN is as much a failure as a loss).

The metric/band layer is pure and unit-tested without Blender or a GPU
(tests/test_pkg129_metal_ab_harness.py). Only ``run()`` needs Blender + a built
addon .pyd. This is NOT a verdict tool: the on-hardware verdict (and any
conviction-path decision) is the LEAD's to record after running on the RTX box.

One command (run by the lead on hardware):
    python benchmarks/cycles-parity/metal_ab/harness.py \
        --out test_results/pkg129_metal_ab --res 128 --samples 256

The subprocess-per-engine shape follows the Apache-2.0 Blender/Cycles benchmark
precedents (benchmarks/cycles-parity/README.md) and blender_parity's pkg119b
driver; the reference-bank metrics are pkg104's, reused, not re-derived.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# repo root = .../Astroray ; metal_ab is at benchmarks/cycles-parity/metal_ab
_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT))  # for `benchmarks.reference_bank`
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for sibling `scenes`

import scenes as _scenes  # noqa: E402

SENTINEL = "PKG129_LEG"
_RENDER_LEG = Path(__file__).resolve().parent / "render_leg.py"

# Default cross-engine parity band (per-channel Astroray/Cycles linear mean
# ratio). WIDER than the internal GPU/CPU 0.95/1.05 band (pkg163) because an
# independent-RNG cross-ENGINE comparison also carries scene-translation and
# sampler differences. Both bounds always asserted (an energy gain fails the
# ceiling just as a loss fails the floor).
#
# 2026-08-11 re-baseline (toward-Cycles, settled engine post pkg181 + height-
# correlated Smith G2 #573 + pkg172(A) guarded-pdf + ggxReflect eval-D fix #582).
# On the Blender-5.2 metal furnace A/B every channel of all 6 configs x CPU/GPU
# lands in [0.857, 1.016]:
#   * CEILING 1.15 -> 1.05. The settled engine never gains energy (max ratio
#     1.016); the old 1.15 predates #582 (which fixed low-roughness metal going
#     near-black). 1.05 keeps ~3% headroom and turns the ceiling into a real
#     energy-GAIN guard instead of a no-op.
#   * FLOOR held at 0.85 (NOT tightened). The binding cell is chromatic r=0.9 blue
#     at 0.857 — the known high-roughness multiscatter energy-compensation
#     residual (a tracked follow-up, not a regression); tightening would fail a
#     legitimate cell. The metal is systematically ~dim in blue at high roughness,
#     so the band is deliberately asymmetric.
DEFAULT_RATIO_LOW = 0.85
DEFAULT_RATIO_HIGH = 1.05


# --------------------------------------------------------------------------- #
# Pure metric + band logic (unit-tested without Blender/GPU)
# --------------------------------------------------------------------------- #

def per_channel_ratio(actual, reference) -> tuple[float, float, float]:
    """Mean Astroray/Cycles ratio per RGB channel (trivial — not a new metric).

    Matches benchmarks/blender_parity/harness.per_channel_ratio.
    """
    a = actual.reshape(-1, 3).mean(axis=0)
    r = reference.reshape(-1, 3).mean(axis=0)
    out = []
    for i in range(3):
        out.append(float(a[i] / r[i]) if r[i] > 1e-9 else float("nan"))
    return (out[0], out[1], out[2])


@dataclass(frozen=True)
class Band:
    low: float
    high: float


def in_band(ratio: tuple[float, float, float], band: Band) -> bool:
    """True iff every channel ratio is within [low, high] (BOTH bounds).

    NaN (reference channel ~0) is treated as out of band — a missing signal is a
    failure, never a silent pass.
    """
    import math
    for v in ratio:
        if math.isnan(v) or v < band.low or v > band.high:
            return False
    return True


# --------------------------------------------------------------------------- #
# Per-config result (pure data)
# --------------------------------------------------------------------------- #

@dataclass
class LegCompare:
    device: str                     # "cpu" | "gpu"
    status: str                     # "pass" | "fail" | "crash"
    ratio: tuple[float, float, float] | None = None
    ssim: float | None = None
    delta_e: float | None = None
    notes: str = ""


@dataclass
class ConfigResult:
    name: str
    roughness: float
    albedo: tuple[float, float, float]
    legs: list[LegCompare]


def compare_leg(device: str, actual, reference, band: Band) -> LegCompare:
    """Reference-bank metrics + band gate for one Astroray leg vs the oracle."""
    from benchmarks.reference_bank.metrics import compute_ssim, compute_delta_e_2000

    ratio = per_channel_ratio(actual, reference)
    ssim, _ = compute_ssim(actual, reference)
    delta_e, _ = compute_delta_e_2000(actual, reference)
    return LegCompare(
        device=device,
        status="pass" if in_band(ratio, band) else "fail",
        ratio=ratio, ssim=ssim, delta_e=delta_e,
    )


# --------------------------------------------------------------------------- #
# Blender / .pyd discovery (mirrors blender_parity conventions — no hardcoding)
# --------------------------------------------------------------------------- #

def _find_blender() -> Path | None:
    env = os.environ.get("BLENDER_EXE", "")
    if env and Path(env).is_file():
        return Path(env)
    on_path = shutil.which("blender")
    if on_path:
        return Path(on_path)
    # pkg178-D1: Blender 5.2 LTS is the parity oracle (installed alongside 5.1);
    # prefer it, falling back to 5.1/5.0 only if 5.2 is absent.
    for c in (r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
              r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
              r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"):
        if Path(c).is_file():
            return Path(c)
    return None


def _pyd_dir(root: Path) -> Path | None:
    # Imported inside Blender -> MUST be an OpenMP-OFF addon build or MinGW
    # libgomp deadlocks (memory mingw_openmp_blender_deadlock). Prefer the addon
    # build dirs over the OpenMP-ON build_cuda.
    for cand in (root / "build_blender_addon_cuda", root / "build_blender_addon_tcnn",
                 root / "build_blender_addon", root / "build_cuda",
                 root / "build_cuda" / "Release"):
        if list(cand.glob("astroray*.pyd")):
            return cand
    return None


def _run_leg(blender: Path, cfg, engine: str, device: str, out_stem: Path,
             res: int, samples: int, timeout: int, env: dict,
             material: str = "metal") -> tuple[bool, str]:
    cmd = [
        str(blender), "--background", "--factory-startup",
        "--python", str(_RENDER_LEG), "--",
        "--config", cfg.name, "--material", material,
        "--engine", engine, "--device", device,
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
        print("[pkg129] Blender not found (set BLENDER_EXE) — cannot run legs.",
              file=sys.stderr)
        return 2
    build_dir = _pyd_dir(_REPO_ROOT) or _pyd_dir(_REPO_ROOT.parent / "Astroray")
    if build_dir is None:
        print("[pkg129] no astroray*.pyd found — build the addon first.",
              file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["ASTRORAY_PYD_DIR"] = str(build_dir)
    env["ASTRORAY_BUILD_DIR"] = str(_REPO_ROOT / "build_cuda")

    out_dir = out_dir.resolve()
    renders_dir = out_dir / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)

    results: list[ConfigResult] = []
    for cfg in _scenes.metal_sweep():
        print(f"[pkg129] {cfg.name} (r={cfg.roughness}) ...", flush=True)
        arrays: dict[str, Any] = {}
        crash = None
        for engine, device in (("CYCLES", "cpu"), ("CUSTOM_RAYTRACER", "cpu"),
                               ("CUSTOM_RAYTRACER", "gpu")):
            tag = "cycles" if engine == "CYCLES" else f"astroray_{device}"
            stem = renders_dir / f"{cfg.name}__{tag}"
            ok, log_tail = _run_leg(blender, cfg, engine, device, stem, res,
                                    samples, timeout, env)
            if not ok:
                crash = f"{tag} leg did not PASS. log tail:\n{log_tail}"
                break
            arrays[tag] = np.load(stem.with_suffix(".npy"))
        if crash is not None:
            results.append(ConfigResult(
                cfg.name, cfg.roughness, cfg.albedo,
                [LegCompare("(leg)", "crash", notes=crash)]))
            print(f"    CRASH: {crash.splitlines()[0]}", flush=True)
            continue

        ref = arrays["cycles"]
        legs = [compare_leg("cpu", arrays["astroray_cpu"], ref, band),
                compare_leg("gpu", arrays["astroray_gpu"], ref, band)]
        results.append(ConfigResult(cfg.name, cfg.roughness, cfg.albedo, legs))
        for lc in legs:
            print(f"    {lc.device.upper()} {lc.status.upper()} "
                  f"ratio={tuple(round(x, 4) for x in lc.ratio)} "
                  f"ssim={lc.ssim:.4f} dE={lc.delta_e:.3f}", flush=True)

    write_reports(results, out_dir, band)
    failed = [r for r in results
              if any(l.status in ("fail", "crash") for l in r.legs)]
    return 1 if failed else 0


# --------------------------------------------------------------------------- #
# Reports (pure)
# --------------------------------------------------------------------------- #

def write_reports(results: list[ConfigResult], out_dir: Path, band: Band) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "band": {"low": band.low, "high": band.high},
        "configs": [asdict(r) for r in results],
    }
    (out_dir / "metal_ab_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# pkg129 — live-Cycles rough-metal A/B (Cycles oracle vs Astroray CPU/GPU)",
        "",
        (f"Per-channel Astroray/Cycles linear mean-ratio band "
         f"[{band.low}, {band.high}] (both bounds asserted; pkg166 rules)."),
        "",
        "| Config | r | Leg | Status | R/G/B ratio | SSIM | dE2000 |",
        "|--------|---|-----|--------|-------------|------|--------|",
    ]
    for r in results:
        for lc in r.legs:
            ratio = ("/".join(f"{x:.4f}" for x in lc.ratio)
                     if lc.ratio else "-")
            ssim = f"{lc.ssim:.4f}" if lc.ssim is not None else "-"
            de = f"{lc.delta_e:.3f}" if lc.delta_e is not None else "-"
            lines.append(f"| {r.name} | {r.roughness} | {lc.device} | "
                         f"{lc.status} | {ratio} | {ssim} | {de} |")
    lines += ["", ("> VERDICT: DEFERRED to the lead's on-hardware run. This table "
                   "is measurement, not adjudication; the conviction-path LUT "
                   "port fires only on a real, scene-controlled divergence with "
                   "architect sign-off.")]
    (out_dir / "metal_ab_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[pkg129] wrote {out_dir / 'metal_ab_report.json'} and .md", flush=True)


# --------------------------------------------------------------------------- #
# pkg263 — rough-glass preset (owner "limb darkening" report). Positional ROIs
# (centre disc / limb annulus / background patch), unlike the metal furnace's
# whole-frame mean, so this section adds its own pure ROI/report layer instead
# of reusing ConfigResult/LegCompare/write_reports (those are shaped around a
# pass/fail band on a single whole-image ratio, not per-ROI measurement).
# CPU only (GPU leg optional per the spec; not run here to avoid the lock).
# --------------------------------------------------------------------------- #

def _roi_masks(res: int):
    """Centre disc (r < 0.35 R) / limb annulus (0.8 R < r < 0.98 R) /
    background patch (a clear-sky strip above the sphere) boolean masks, in
    the SAME frame ``scenes.build_glass_scene`` renders — the camera axis
    passes through the sphere centre, so the silhouette is a circle centred
    in the square frame at radius R (``scenes.sphere_projected_radius_px``).
    Returns (masks_dict, R_px, (cx, cy))."""
    import numpy as np

    half_fov = math.radians(_scenes.GLASS_CAM_FOV_DEG / 2.0)
    r_px = _scenes.sphere_projected_radius_px(
        _scenes.GLASS_SPHERE_RADIUS, _scenes.GLASS_CAM_DISTANCE, half_fov, res)
    cx = cy = res / 2.0
    yy, xx = np.mgrid[0:res, 0:res].astype(np.float64)
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    centre = d < 0.35 * r_px
    limb = (d >= 0.8 * r_px) & (d < 0.98 * r_px)

    top_clear = cy - r_px  # rows strictly above the sphere's top edge
    margin = top_clear * 0.15
    row0, row1 = margin, top_clear - margin
    half = max(1.0, (row1 - row0) / 2.0)
    col0, col1 = cx - half, cx + half
    background = np.zeros((res, res), dtype=bool)
    background[int(round(row0)):int(round(row1)),
               int(round(col0)):int(round(col1))] = True

    return {"centre": centre, "limb": limb, "background": background}, r_px, (cx, cy)


def roi_mean_rgb(img, mask) -> tuple[float, float, float]:
    """Per-channel mean over a boolean ROI mask (trivial — not a new metric)."""
    sel = img[mask]
    if sel.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    m = sel.reshape(-1, 3).mean(axis=0)
    return (float(m[0]), float(m[1]), float(m[2]))


def _elementwise_ratio(num: tuple[float, float, float],
                       den: tuple[float, float, float]) -> tuple[float, float, float]:
    out = []
    for n, d in zip(num, den):
        out.append(float(n / d) if d and abs(d) > 1e-9 and not math.isnan(d) else float("nan"))
    return (out[0], out[1], out[2])


@dataclass
class GlassRoiResult:
    roi: str                                    # "centre" | "limb" | "background"
    cycles_rgb: tuple[float, float, float]
    astroray_rgb: tuple[float, float, float]
    ratio: tuple[float, float, float]            # astroray / cycles


@dataclass
class GlassConfigResult:
    name: str
    roughness: float
    status: str                                  # "ok" | "crash"
    rois: list[GlassRoiResult]
    limb_over_centre_cycles: tuple[float, float, float] | None = None
    limb_over_centre_astroray: tuple[float, float, float] | None = None
    notes: str = ""


def _linear_to_srgb_u8(px):
    """Linear float [0,1]-ish -> sRGB uint8 (matches render_leg._render_to_npy's
    formula). Done on the HARNESS side, not inside Blender: Blender's bundled
    Python has no PIL (verified: `import PIL` there raises ModuleNotFoundError),
    so render_leg's own PNG write is silently skipped (wrapped in a
    try/except — cosmetic by design) and this is the only place a display
    image actually gets made for the glass sweep."""
    import numpy as np
    srgb = np.where(px <= 0.0031308, px * 12.92,
                    1.055 * np.clip(px, 0, None) ** (1 / 2.4) - 0.055)
    return (np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8)


def _annotate_and_contact_sheet(renders_dir: Path, cfg_name: str, roi_masks,
                                r_px: float, center: tuple[float, float],
                                cyc_linear, ast_linear) -> None:
    """Builds each engine's sRGB display image from its LINEAR array, draws
    the three ROIs on each, and writes a Cycles | Astroray | abs-diff contact
    sheet (memory blender-pixels-bottom-up-roi-flip: LOOK at the drawn ROI,
    don't just trust the number)."""
    import numpy as np
    from PIL import Image, ImageDraw

    cx, cy = center
    cyc_png = Image.fromarray(_linear_to_srgb_u8(cyc_linear), "RGB")
    ast_png = Image.fromarray(_linear_to_srgb_u8(ast_linear), "RGB")

    def _draw(img):
        im = img.copy()
        d = ImageDraw.Draw(im)
        d.ellipse([cx - 0.35 * r_px, cy - 0.35 * r_px,
                   cx + 0.35 * r_px, cy + 0.35 * r_px], outline=(255, 40, 40), width=2)
        d.ellipse([cx - 0.8 * r_px, cy - 0.8 * r_px,
                   cx + 0.8 * r_px, cy + 0.8 * r_px], outline=(40, 220, 40), width=2)
        d.ellipse([cx - 0.98 * r_px, cy - 0.98 * r_px,
                   cx + 0.98 * r_px, cy + 0.98 * r_px], outline=(40, 220, 40), width=2)
        ys, xs = np.nonzero(roi_masks["background"])
        if ys.size:
            d.rectangle([int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
                        outline=(60, 160, 255), width=2)
        return im

    _draw(cyc_png).save(renders_dir / f"{cfg_name}__cycles_roi.png")
    _draw(ast_png).save(renders_dir / f"{cfg_name}__astroray_roi.png")

    w, h = cyc_png.size
    cyc_arr = np.asarray(cyc_png, dtype=np.float32)
    ast_arr = np.asarray(ast_png, dtype=np.float32)
    diff = np.clip(np.abs(cyc_arr - ast_arr) * 3.0, 0, 255).astype(np.uint8)
    sheet = Image.new("RGB", (w * 3 + 20, h), (32, 32, 32))
    sheet.paste(cyc_png, (0, 0))
    sheet.paste(ast_png, (w + 10, 0))
    sheet.paste(Image.fromarray(diff), (2 * (w + 10), 0))
    sheet.save(renders_dir / f"{cfg_name}__contact_sheet.png")


def run_glass(out_dir: Path, *, res: int = 256, samples: int = 128,
             astroray_samples: int | None = None, timeout: int = 900) -> int:
    import numpy as np

    blender = _find_blender()
    if blender is None:
        print("[pkg263] Blender not found (set BLENDER_EXE) — cannot run legs.",
              file=sys.stderr)
        return 2
    # A pre-set ASTRORAY_PYD_DIR (e.g. the staged CPU addon build under the
    # main checkout's dist/astroray/, which _pyd_dir's build_cuda*/
    # build_blender_addon* candidates don't cover) wins over auto-discovery.
    env_override = os.environ.get("ASTRORAY_PYD_DIR", "")
    if env_override and list(Path(env_override).glob("astroray*.pyd")):
        build_dir = Path(env_override)
    else:
        build_dir = _pyd_dir(_REPO_ROOT) or _pyd_dir(_REPO_ROOT.parent / "Astroray")
    if build_dir is None:
        print("[pkg263] no astroray*.pyd found — build the addon first.",
              file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["ASTRORAY_PYD_DIR"] = str(build_dir)
    env["ASTRORAY_BUILD_DIR"] = str(_REPO_ROOT / "build_cuda")

    out_dir = out_dir.resolve()
    renders_dir = out_dir / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)

    astroray_samples = astroray_samples or samples
    roi_masks, r_px, center = _roi_masks(res)

    results: list[GlassConfigResult] = []
    for cfg in _scenes.glass_sweep():
        print(f"[pkg263] {cfg.name} (r={cfg.roughness}) ...", flush=True)
        arrays: dict[str, Any] = {}
        crash = None
        for engine, device, spp in (("CYCLES", "cpu", samples),
                                    ("CUSTOM_RAYTRACER", "cpu", astroray_samples)):
            tag = "cycles" if engine == "CYCLES" else "astroray_cpu"
            stem = renders_dir / f"{cfg.name}__{tag}"
            ok, log_tail = _run_leg(blender, cfg, engine, device, stem, res, spp,
                                    timeout, env, material="glass")
            if not ok:
                crash = f"{tag} leg did not PASS. log tail:\n{log_tail}"
                break
            arrays[tag] = np.load(stem.with_suffix(".npy"))
        if crash is not None:
            results.append(GlassConfigResult(cfg.name, cfg.roughness, "crash", [],
                                             notes=crash))
            print(f"    CRASH: {crash.splitlines()[0]}", flush=True)
            continue

        cyc, ast = arrays["cycles"], arrays["astroray_cpu"]
        roi_results, means = [], {}
        for roi_name, mask in roi_masks.items():
            c_mean = roi_mean_rgb(cyc, mask)
            a_mean = roi_mean_rgb(ast, mask)
            ratio = per_channel_ratio(ast[mask], cyc[mask])
            roi_results.append(GlassRoiResult(roi_name, c_mean, a_mean, ratio))
            means[roi_name] = (c_mean, a_mean)
        limb_c, limb_a = means["limb"]
        centre_c, centre_a = means["centre"]
        loc_c = _elementwise_ratio(limb_c, centre_c)
        loc_a = _elementwise_ratio(limb_a, centre_a)
        results.append(GlassConfigResult(cfg.name, cfg.roughness, "ok", roi_results,
                                         limb_over_centre_cycles=loc_c,
                                         limb_over_centre_astroray=loc_a))
        _annotate_and_contact_sheet(renders_dir, cfg.name, roi_masks, r_px, center,
                                    cyc, ast)
        for r in roi_results:
            print(f"    {r.roi:10s} astroray/cycles ratio="
                  f"{tuple(round(x, 4) for x in r.ratio)}", flush=True)
        print(f"    limb/centre  cycles={tuple(round(x, 4) for x in loc_c)} "
              f"astroray={tuple(round(x, 4) for x in loc_a)}", flush=True)

    write_glass_reports(results, out_dir)
    return 0 if all(r.status == "ok" for r in results) else 1


def write_glass_reports(results: list[GlassConfigResult], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"configs": [asdict(r) for r in results]}
    (out_dir / "glass_ab_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# pkg263 — live-Cycles rough-glass A/B (Cycles oracle vs Astroray CPU)",
        "",
        "Per-ROI Astroray/Cycles linear per-channel mean ratio; limb/centre ratio per engine.",
        "",
        "| Config | r | ROI | Cycles R/G/B | Astroray R/G/B | Astroray/Cycles ratio |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        if r.status != "ok":
            lines.append(f"| {r.name} | {r.roughness} | (crash) | - | - | - |")
            continue
        for roi in r.rois:
            c = "/".join(f"{x:.4f}" for x in roi.cycles_rgb)
            a = "/".join(f"{x:.4f}" for x in roi.astroray_rgb)
            ra = "/".join(f"{x:.4f}" for x in roi.ratio)
            lines.append(f"| {r.name} | {r.roughness} | {roi.roi} | {c} | {a} | {ra} |")
    lines += ["", "| Config | r | limb/centre Cycles | limb/centre Astroray |",
              "|---|---|---|---|"]
    for r in results:
        if r.status != "ok":
            continue
        lc = "/".join(f"{x:.4f}" for x in r.limb_over_centre_cycles)
        la = "/".join(f"{x:.4f}" for x in r.limb_over_centre_astroray)
        lines.append(f"| {r.name} | {r.roughness} | {lc} | {la} |")
    lines += ["", ("> Diagnostic only (pkg263): no engine change here; findings route "
                   "to pkg124 (VNDF reflection lobe) / pkg179 Phase 2.")]
    (out_dir / "glass_ab_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[pkg263] wrote {out_dir / 'glass_ab_report.json'} and .md", flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="pkg129 live-Cycles rough-metal/glass A/B harness.")
    p.add_argument("--material", choices=("metal", "glass"), default="metal")
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--res", type=int, default=None)
    p.add_argument("--samples", type=int, default=None)
    p.add_argument("--astroray-samples", type=int, default=None,
                   help="glass only: Astroray sample count if it must differ from --samples")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--ratio-low", type=float, default=DEFAULT_RATIO_LOW)
    p.add_argument("--ratio-high", type=float, default=DEFAULT_RATIO_HIGH)
    args = p.parse_args(argv)

    if args.material == "glass":
        out = args.out or (_REPO_ROOT / "test_results" / "pkg263_rough_glass_ab")
        return run_glass(out, res=args.res or 256, samples=args.samples or 128,
                         astroray_samples=args.astroray_samples, timeout=args.timeout)

    out = args.out or (_REPO_ROOT / "test_results" / "pkg129_metal_ab")
    return run(out, res=args.res or 128, samples=args.samples or 256,
               timeout=args.timeout, band=Band(args.ratio_low, args.ratio_high))


if __name__ == "__main__":
    sys.exit(main())

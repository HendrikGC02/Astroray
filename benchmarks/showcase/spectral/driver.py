# -*- coding: utf-8 -*-
"""pkg324 - spectral showcase driver behind ``runner.py --preset spectral``.

Renders every manifest scene (and its variants) on the requested legs, writes
three-way contact sheets, runs the analytic checks and stamps seed/spp/size/time on
every panel. Reuses (CLAUDE.md 5b): ``benchmarks/blender_parity/render_leg.py`` for
the per-leg Blender process (one engine per process), ``report_tools`` for the sheet
labels and ``harness._npy_to_png`` for the sRGB encode, ``checks.py`` for the numbers.

    python -m benchmarks.showcase.runner --preset spectral --legs cpu cycles \
        --pyd-dir <staged addon dir or CPU build dir> --output-dir <dir>
    python scripts/build/gpu_locked_run.py <lane> -- python -m benchmarks.showcase.runner \
        --preset spectral --legs gpu cycles_gpu --pyd-dir dist/astroray --output-dir <dir>

Legs: ``cpu`` / ``gpu`` (Astroray device), ``cycles`` (Cycles CPU), ``cycles_gpu`` (Cycles OptiX).
Outputs under ``<out>/``: ``npy/<scene>__<variant>__<leg>.npy`` (linear), ``logs/``,
``sheets/<scene>.png``, ``results.json`` (render times + check numbers), ``summary.md``.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from benchmarks.showcase.spectral import checks  # noqa: E402

BLENDER_EXE = os.environ.get("BLENDER_EXE", r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
RENDER_LEG = REPO / "benchmarks" / "blender_parity" / "render_leg.py"
MANIFEST = HERE / "manifest.json"
LEGS = {
    "cpu": {"engine": "CUSTOM_RAYTRACER", "device": "cpu", "label": "Astroray CPU"},
    "gpu": {"engine": "CUSTOM_RAYTRACER", "device": "gpu", "label": "Astroray GPU"},
    "cycles": {"engine": "CYCLES", "device": "cpu", "label": "Cycles CPU"},
    "cycles_gpu": {"engine": "CYCLES", "device": "gpu", "label": "Cycles OptiX"},
}
SHEET_LEGS = ("cpu", "gpu", "cycles")  # three-way sheet columns (cycles_gpu replaces cycles when only it exists)
PANEL_W = 400


def load_manifest(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def scene_variants(entry: dict) -> list[dict]:
    return entry.get("variants") or [{"id": "default"}]


def _stem(out: Path, scene: str, variant: str, leg: str) -> Path:
    return out / "npy" / f"{scene}__{variant}__{leg}"


def render_leg(scene_id: str, entry: dict, variant: dict, leg: str, out: Path, pyd_dir: str,
               spp: int | None, res_scale: float, threads: int, force: bool) -> dict:
    """One Blender process = one (scene, variant, leg). Returns {"ok", "render_s", "log"}."""
    spec = LEGS[leg]
    stem = _stem(out, scene_id, variant["id"], leg)
    log = out / "logs" / f"{scene_id}__{variant['id']}__{leg}.log"
    if stem.with_suffix(".npy").is_file() and not force:
        return {"ok": True, "render_s": None, "skipped": True, "log": str(log)}
    blend = (REPO / entry["blend_path"]).resolve()
    if not blend.is_file():
        return {"ok": False, "error": f"missing {blend}", "log": str(log)}
    rx, ry = entry["res"]
    rx, ry = max(16, int(round(rx * res_scale))), max(16, int(round(ry * res_scale)))
    cmd = [BLENDER_EXE, "-b", "--factory-startup", "--python", str(RENDER_LEG), "--",
           "--engine", spec["engine"], "--load-blend", str(blend), "--res", str(rx), "--res-y", str(ry),
           "--samples", str(spp or entry["spp"]), "--seed", str(entry.get("seed", 324)), "--out", str(stem)]
    if spec["engine"] == "CUSTOM_RAYTRACER":
        cmd += ["--device", spec["device"]]
    else:
        cmd += ["--cycles-leg-device", spec["device"]]
    if "max_bounces" in variant:
        cmd += ["--max-bounces", str(variant["max_bounces"])]
    if "camera" in variant:
        cmd += ["--camera", variant["camera"]]
    env = dict(os.environ, OMP_NUM_THREADS=str(threads), ASTRORAY_LEG_THREADS=str(threads))
    if pyd_dir:
        env["ASTRORAY_PYD_DIR"] = pyd_dir
    stem.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, errors="replace", cwd=str(REPO))
    log.write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr, encoding="utf-8")
    ok = "PKG119B_LEG PASS" in proc.stdout and stem.with_suffix(".npy").is_file()
    info = {}
    for line in proc.stdout.splitlines():
        if line.startswith("PKG307_INFO "):
            info = json.loads(line[len("PKG307_INFO "):])
    return {"ok": ok, "render_s": info.get("render_s"), "wall_s": round(time.perf_counter() - t0, 1),
            "device": info.get("device"), "log": str(log)}


def _load(out: Path, scene: str, variant: str, leg: str):
    f = _stem(out, scene, variant, leg).with_suffix(".npy")
    return np.load(f) if f.is_file() else None


def _panel(img: np.ndarray, label: str, width: int):
    from PIL import Image
    srgb = np.where(img <= 0.0031308, img * 12.92, 1.055 * np.clip(img, 0, None) ** (1 / 2.4) - 0.055)
    im = Image.fromarray((np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8))
    im = im.resize((width, max(1, round(im.height * width / im.width))), Image.LANCZOS)
    return label, im


def build_sheet(scene_id: str, entry: dict, out: Path, results: dict) -> Path | None:
    """Columns = legs present, rows = variants. Every panel label carries leg, spp, seed, size and time;
    a leg that cannot do the effect says so in its label."""
    from PIL import Image
    from benchmarks.reference_corpus import report_tools as rt
    legs = [l for l in ("cpu", "gpu", "cycles", "cycles_gpu") if any(
        _load(out, scene_id, v["id"], l) is not None for v in scene_variants(entry))]
    if not legs:
        return None
    seed, spp = entry.get("seed", 324), entry["spp"]
    rows = []
    for v in scene_variants(entry):
        row = []
        for leg in legs:
            img = _load(out, scene_id, v["id"], leg)
            if img is None:
                continue
            res = results.get(scene_id, {}).get(v["id"], {}).get(leg, {})
            t = res.get("render_s")
            lab = f"{LEGS[leg]['label']}"
            if v["id"] != "default":
                lab += f" [{v['id']}]"
            lab += f" | {spp} spp seed {seed} {img.shape[1]}x{img.shape[0]}"
            if t:
                lab += f" | {t:.1f}s"
            if leg.startswith("cycles") and entry.get("cycles") == "no_dispersion":
                lab += " | no dispersion in Blender 5.2"
            row.append(_panel(img, lab, PANEL_W))
        rows.append(row)
    gap = rt.GAP
    col_w = PANEL_W
    ph = max(im.height for row in rows for _, im in row)
    sheet = Image.new("RGB", (len(legs) * col_w + gap * (len(legs) - 1), len(rows) * (rt.LABEL_BAR_H + ph + gap)),
                      rt.SHEET_BG)
    y = 0
    for row in rows:
        x = 0
        for lab, im in row:
            sheet.paste(_fit_label(rt, col_w, lab), (x, y))
            sheet.paste(im, (x, y + rt.LABEL_BAR_H))
            x += col_w + gap
        y += rt.LABEL_BAR_H + ph + gap
    path = out / "sheets" / f"{scene_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, optimize=True)
    return path


def _fit_label(rt, width, text):
    """report_tools' label bar (same colours / height) with the text clipped to the panel width."""
    from PIL import Image, ImageDraw
    bar = Image.new("RGB", (width, rt.LABEL_BAR_H), rt.LABEL_BG)
    d = ImageDraw.Draw(bar)
    d.text((4, rt.LABEL_BAR_H // 2), text[: width // 6], fill=rt.LABEL_FG, anchor="lm")  # ~6 px per glyph
    return bar


def run_checks(manifest: dict, out: Path, legs: list[str]) -> dict:
    res = {}
    for sid, entry in manifest["scenes"].items():
        if not entry.get("check") or entry["check"].get("kind") in (None, "none", "see_check_scene"):
            continue
        for leg in legs:
            imgs = {v["id"]: _load(out, sid, v["id"], leg) for v in scene_variants(entry)}
            if any(i is None for i in imgs.values()):
                continue
            try:
                r = checks.run_check(entry, imgs)
            except Exception as exc:  # noqa: BLE001 - report, never hide
                r = {"error": f"{type(exc).__name__}: {exc}"}
            if r is not None:
                res.setdefault(sid, {})[leg] = r
    return res


def write_summary(out: Path, manifest: dict, results: dict, check_results: dict):
    lines = ["# Spectral showcase run", "", f"seed {manifest.get('seed')}, Blender {manifest.get('blender', '5.2')}", ""]
    lines += ["| scene | variant | leg | render s |", "|---|---|---|---|"]
    for sid, per_v in results.items():
        for vid, per_leg in per_v.items():
            for leg, r in per_leg.items():
                lines.append(f"| {sid} | {vid} | {leg} | {r.get('render_s') if r.get('ok') else 'FAILED'} |")
    lines += ["", "## Checks", "", "```json", json.dumps(check_results, indent=1), "```", ""]
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--legs", nargs="+", choices=list(LEGS), default=["cpu", "cycles"])
    p.add_argument("--scenes", nargs="+", default=None, help="manifest scene ids (default: all that exist)")
    p.add_argument("--output-dir", type=Path, default=None)
    p.add_argument("--pyd-dir", default=os.environ.get("ASTRORAY_PYD_DIR", ""),
                   help="staged addon dir / build dir holding astroray*.pyd (ASTRORAY_PYD_DIR)")
    p.add_argument("--samples", type=int, default=None, help="override the manifest spp (smoke runs only)")
    p.add_argument("--res-scale", type=float, default=1.0)
    p.add_argument("--threads", type=int, default=8, help="OMP / Blender threads per leg (lane rule 12: 8)")
    p.add_argument("--force", action="store_true", help="re-render legs whose .npy already exists")
    p.add_argument("--sheets-only", action="store_true", help="no rendering: rebuild sheets/checks from existing .npy")
    args = p.parse_args(argv)

    manifest = load_manifest()
    out = (args.output_dir or (REPO / "benchmarks" / "showcase" / "output" / ("spectral-" + time.strftime("%Y%m%d-%H%M%S")))).resolve()
    out.mkdir(parents=True, exist_ok=True)
    rj = out / "results.json"
    results = json.loads(rj.read_text(encoding="utf-8")).get("renders", {}) if rj.is_file() else {}
    ids = args.scenes or list(manifest["scenes"])
    for sid in ids:
        entry = manifest["scenes"][sid]
        if entry.get("status") == "needs_download" or not (REPO / entry["blend_path"]).is_file():
            print(f"[pkg324] {sid}: blend not present, skipped", flush=True)
            continue
        for v in scene_variants(entry):
            for leg in args.legs:
                if args.sheets_only:
                    continue
                r = render_leg(sid, entry, v, leg, out, args.pyd_dir, args.samples, args.res_scale, args.threads, args.force)
                if r.get("skipped"):
                    r = results.get(sid, {}).get(v["id"], {}).get(leg, {"ok": True})
                results.setdefault(sid, {}).setdefault(v["id"], {})[leg] = r
                print(f"[pkg324] {sid} [{v['id']}] {leg}: {'ok' if r.get('ok') else 'FAILED'} "
                      f"{r.get('render_s') or ''}", flush=True)
    present = [l for l in LEGS if any(_stem(out, s, v["id"], l).with_suffix(".npy").is_file()
                                      for s in ids for v in scene_variants(manifest["scenes"][s]))]
    sheets = {}
    for sid in ids:
        entry = manifest["scenes"][sid]
        if entry.get("gallery", True) and entry.get("status") != "needs_download":
            sp = build_sheet(sid, entry, out, results)
            if sp:
                sheets[sid] = str(sp)
    check_results = run_checks({"scenes": {s: manifest["scenes"][s] for s in ids}}, out, present)
    rj.write_text(json.dumps({"seed": manifest.get("seed"), "renders": results, "checks": check_results,
                              "sheets": sheets}, indent=1), encoding="utf-8")
    write_summary(out, manifest, results, check_results)
    print(f"[pkg324] results: {rj}", flush=True)
    failed = [(s, v, l) for s, pv in results.items() for v, pl in pv.items() for l, r in pl.items() if not r.get("ok")]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

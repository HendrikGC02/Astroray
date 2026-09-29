"""pkg284 -- Monte-Carlo tolerance bands for the Cycles-parity corpus v2.

Renders each ``v2_*`` scene in Cycles CPU (via ``blender_parity/render_leg.py``)
at ``spp_gate`` with N fixed seeds, measures the per-ROI per-channel mean of every
render, and derives the gate band from the seed-to-seed scatter:

    tolerance = max(0.02, 3 * sigma_rel * sqrt(2))

(sigma_rel = std of the N ROI means / their mean; sqrt(2) because the gate compares
two independent renders; 2 % floor covers Cycles' own residual seed noise, spec
pkg284 "Key design decisions"). Also renders the ``spp_reference`` Cycles reference
(seed 278) and writes it as a linear EXR. Output: ``gates_v2.toml``.

Run in the repo's normal Python env (NOT inside Blender):

    python benchmarks/reference_corpus/mc_tolerance.py --scenes v2_light_tree ... \
        --seeds 278 279 280 --work-dir <dir> [--skip-reference]

Phase 1 (this state) measures the Cycles leg only; the Astroray CPU/GPU legs and
the parity test are Phase 2.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "benchmarks" / "reference_corpus"
MANIFEST = CORPUS / "scenes" / "manifest.json"
REFS = CORPUS / "refs_v2"
GATES = CORPUS / "gates_v2.toml"
RENDER_LEG = REPO / "benchmarks" / "blender_parity" / "render_leg.py"
BLENDER = Path(os.environ.get("ASTRORAY_BLENDER",
                              r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"))
BAND_FLOOR, BAND_CEIL, DARK = 0.02, 0.15, 0.01
GATE_C = ("v2_light_tree", "v2_textures_opvm", "v2_camera_geometry")  # owner 2026-09-29


def render_cycles(scene_id: str, seed: int, spp: int, stem: Path, threads: int = 8) -> np.ndarray:
    """One Cycles CPU render through render_leg.py; returns linear HxWx3 (row 0 = top)."""
    cmd = [str(BLENDER), "-b", "--factory-startup", "--threads", str(threads),
           "--python", str(RENDER_LEG), "--", "--engine", "CYCLES", "--device", "cpu",
           "--corpus-manifest", str(MANIFEST), "--corpus-scene", scene_id,
           "--out", str(stem), "--seed", str(seed), "--spp-override", str(spp)]
    stem.parent.mkdir(parents=True, exist_ok=True)
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=1500, check=False)
    if "PKG119B_LEG PASS" not in out.stdout:
        raise RuntimeError(f"{scene_id} seed={seed}: render leg failed\n{out.stdout[-1500:]}\n{out.stderr[-500:]}")
    return np.load(stem.with_suffix(".npy"))


def roi_means(img: np.ndarray, rect) -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = rect
    box = img[round(y0 * h):round(y1 * h), round(x0 * w):round(x1 * w)]
    return box.reshape(-1, 3).mean(axis=0)


def write_exr(path: Path, img: np.ndarray) -> None:
    os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), np.ascontiguousarray(img[:, :, ::-1].astype(np.float32))):
        raise RuntimeError(f"cannot write {path}")


def band(sigma_rel: float) -> tuple[float, str]:
    raw = 3.0 * sigma_rel * math.sqrt(2.0)
    if raw > BAND_CEIL:
        return raw, f"raw 3*sigma*sqrt2 = {raw:.3f} exceeds {BAND_CEIL:.2f}: low-count/high-variance ROI, kept unclipped"
    return max(BAND_FLOOR, raw), ""


def measure(scene_id: str, entry: dict, seeds, work: Path, do_reference: bool) -> dict:
    v2 = entry["v2"]
    spp_g, spp_r = v2["spp_gate"], v2["spp_reference"]
    if do_reference:
        ref = render_cycles(scene_id, seeds[0], spp_r, work / f"{scene_id}_cycles_ref")
        write_exr(REFS / f"{scene_id}_cycles.exr", ref)
        np.save(work / f"{scene_id}_cycles_ref.npy", ref)
    else:
        ref = np.load(work / f"{scene_id}_cycles_ref.npy")
    per_seed = []
    for s in seeds:
        img = render_cycles(scene_id, s, spp_g, work / f"{scene_id}_s{s}")
        per_seed.append({n: roi_means(img, r) for n, r in entry["crops"].items()})
    rois = []
    for name, rect in entry["crops"].items():
        m = np.stack([p[name] for p in per_seed])            # seeds x 3
        ref_m = roi_means(ref, rect)
        sig = m.std(axis=0, ddof=1) / np.maximum(m.mean(axis=0), 1e-12)
        bands, notes = [], []
        for c, ch in enumerate("rgb"):
            if ref_m[c] < DARK:
                bands.append(0.0)
                notes.append(f"{ch}: excluded (Cycles mean {ref_m[c]:.4f} < {DARK})")
                continue
            t, why = band(float(sig[c]))
            bands.append(t)
            if why:
                notes.append(f"{ch}: {why}")
        rois.append({"name": name, "rect": rect, "ref_mean": ref_m.tolist(),
                     "seed_mean": m.mean(axis=0).tolist(), "sigma_rel": sig.tolist(),
                     "tol": bands, "excluded": [bool(ref_m[c] < DARK) for c in range(3)],
                     "note": "; ".join(notes)})
    return {"rois": rois}


def _arr(v, fmt="{:.6g}"):
    return "[" + ", ".join(fmt.format(x) for x in v) + "]"


def write_toml(results: dict, manifest: dict, seeds, blender_version: str, base: str) -> None:
    L = ["# pkg284 corpus v2 gates -- generated by mc_tolerance.py; bands are measured, never hand-typed.",
         "# Gate: per-ROI per-channel linear mean ratio Astroray/Cycles; fixed seed, adaptive OFF, denoise OFF.",
         "# tol = max(0.02, 3*sigma_rel*sqrt(2)); sigma_rel from the Cycles seed-to-seed scatter at spp_gate.",
         "# Channels with Cycles mean < 0.01 are excluded (tol = 0). Re-bless rule: README.md.", "",
         "[meta]", f'blender = "{blender_version}"', f"seed = {seeds[0]}", f"mc_seeds = {seeds}",
         "adaptive_sampling = false", "denoise = false", f"band_floor = {BAND_FLOOR}",
         f'blessed_on = "Cycles references: Blender {blender_version}, base commit {base}, pkg284 Phase 1"', ""]
    for sid in sorted(manifest["scenes"]):
        e = manifest["scenes"][sid]
        if "v2" not in e:
            continue
        v2 = e["v2"]
        L += [f"[scenes.{sid}]", f'blend = "{e["blend_path"]}"', f"seed = {v2['seed']}",
              f"spp_gate = {v2['spp_gate']}", f"spp_reference = {v2['spp_reference']}",
              f"res = [{e['settings']['res_x']}, {e['settings']['res_y']}]",
              f"render_gate = {str(v2['render_gate']).lower()}",
              f"gate_c = {str(sid in GATE_C).lower()}"]
        if sid in results:
            L.append(f'reference = "benchmarks/reference_corpus/refs_v2/{sid}_cycles.exr"')
        L.append("")
        for roi in results.get(sid, {}).get("rois", []):
            L += [f"[[scenes.{sid}.roi]]", f'name = "{roi["name"]}"', f"rect = {_arr(roi['rect'], '{:.4f}')}",
                  f"cycles_mean = {_arr(roi['ref_mean'])}", f"sigma_rel = {_arr(roi['sigma_rel'], '{:.4f}')}",
                  f"tol = {_arr(roi['tol'], '{:.4f}')}", "provisional = false"]
            if roi["note"]:
                L.append(f'note = "{roi["note"]}"')
            div = v2.get("divergence", {}).get(roi["name"])
            if div:
                L.append(f'expected_divergence = "{div}"')
            L.append("")
    text = "\n".join(L)
    tomllib.loads(text)  # must parse
    GATES.write_text(text, encoding="utf-8", newline="\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenes", nargs="+", help="v2 scene ids (default: every render-gated v2 scene)")
    ap.add_argument("--seeds", nargs="+", type=int, default=[278, 279, 280])
    ap.add_argument("--work-dir", required=True, help="scratch dir for .npy/.png renders")
    ap.add_argument("--skip-reference", action="store_true", help="reuse <work>/<scene>_cycles_ref.npy")
    ap.add_argument("--table-only", action="store_true",
                    help="rewrite gates_v2.toml from <work>/results.json without rendering")
    a = ap.parse_args()
    if any(s <= 0 for s in a.seeds):
        sys.exit("seeds must be non-zero (0 is the random sentinel)")
    work = Path(a.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    gated = [s for s, e in manifest["scenes"].items() if "v2" in e and e["v2"]["render_gate"]]
    scenes = a.scenes or sorted(gated)
    res_path = work / "results.json"
    results = json.loads(res_path.read_text()) if res_path.is_file() else {}
    if not a.table_only:
        for sid in scenes:
            print(f"[mc_tolerance] {sid}", flush=True)
            results[sid] = measure(sid, manifest["scenes"][sid], a.seeds, work, not a.skip_reference)
            res_path.write_text(json.dumps(results, indent=1))
    version = next(e["v2"]["blender_version"] for e in manifest["scenes"].values() if "v2" in e)
    base = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True, check=False).stdout.strip()
    write_toml(results, manifest, a.seeds, version, base)
    print(f"[mc_tolerance] wrote {GATES}")


if __name__ == "__main__":
    main()

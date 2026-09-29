"""pkg284 -- Monte-Carlo tolerance bands for the Cycles-parity corpus v2.

Renders each ``v2_*`` scene through ``blender_parity/render_leg.py`` at ``spp_gate`` with N
fixed seeds on up to three legs (Cycles CPU, Astroray CPU, Astroray GPU), measures the
per-ROI mean of every render (per channel and Rec.709 luminance) and derives the gate bands
from the seed-to-seed scatter of BOTH engines:

    parity tol  = max(0.02, 3 * sqrt(sigma_cycles^2 + sigma_astroray^2))    (per channel + luminance)
    GPU/CPU tol = max(0.05, 3 * sqrt(sigma_cpu^2 + sigma_gpu^2))            (pkg271 +-5 % floor)
    pin tol     = max(0.02, 3 * sigma_astroray * sqrt(1.2))                 (documented-divergence rows:
                                                                             one render vs the N-seed mean)

sigma = std of the N ROI means / their mean. The 2 % floor covers residual seed noise (spec
pkg284 "Key design decisions"). Channels/luminance with Cycles mean < 0.01 are excluded.
Astroray's spectral R/B chroma noise floor (~0.002 relVar at 64 spp) is inside sigma_astroray
because it is measured, not assumed; there are no per-channel variance gates, only mean gates.

``results.json`` in --work-dir accumulates legs, so the GPU leg can be added later
(``--legs gpu``). ``gates_v2.toml`` is regenerated from it; the hand-maintained
``provisional_v2.toml`` (assertion-level xfail rows, each tied to an issue) is never touched.

Run in the repo's normal Python env (NOT inside Blender). The Astroray legs need an
OpenMP-OFF staged addon build: ``ASTRORAY_PYD_DIR=<dist/astroray>``. GPU legs only through
``scripts/build/gpu_locked_run.py <lane> -- python ...mc_tolerance.py --legs gpu``:

    python benchmarks/reference_corpus/mc_tolerance.py --scenes v2_light_tree ... \\
        --seeds 278 279 280 281 282 --legs cycles cpu --work-dir <dir> [--reference]

Variant scenes ``<scene>@<variant>`` (VARIANTS below) reuse a scene's .blend with another
camera; today only ``v2_camera_geometry@ortho`` (the named ortho camera, #845).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import tomllib

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "benchmarks" / "reference_corpus"
MANIFEST = CORPUS / "scenes" / "manifest.json"
REFS = CORPUS / "refs_v2"
GATES = CORPUS / "gates_v2.toml"
KNOWN = CORPUS / "provisional_v2.toml"  # hand-maintained: provisional rows + extra documented divergences
RENDER_LEG = REPO / "benchmarks" / "blender_parity" / "render_leg.py"
BLENDER = Path(os.environ.get("ASTRORAY_BLENDER",
                              r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"))
BAND_FLOOR, BAND_CEIL, GPU_CPU_FLOOR, DARK = 0.02, 0.15, 0.05, 0.01
GATE_C = ("v2_light_tree", "v2_textures_opvm", "v2_camera_geometry")  # owner 2026-09-29
LUM = np.array([0.2126, 0.7152, 0.0722])
CH = ("r", "g", "b", "L")
LEGS = ("cycles", "cpu", "gpu")

# Ortho leg of v2_camera_geometry. World points mirror build_corpus._v2_camera_geometry;
# CamOrtho sits at the perspective camera position, ortho_scale 6 (sensor fit AUTO: applies
# to the larger image dimension), and is projected here analytically so the committed .blend
# (and its manifest sha) stays untouched. (name, world point, ROI half-width / image width)
_ORTHO_POINTS = (("instances", (-2.15, 0.0, 0.25), 0.04), ("hair_tuft", (-0.8, 0.0, 0.45), 0.04),
                 ("motion_vane", (0.4, 0.0, 0.55), 0.04), ("mesh_volume", (1.7, 0.0, 0.5), 0.04),
                 ("post_far_visible", (-2.6, 5.0, 0.75), 0.012),
                 ("post_far_clipped_region", (-0.9, 11.0, 0.75), 0.012),
                 ("near_clip_column", (0.0, -4.65, 1.5), 0.03))
VARIANTS = {"v2_camera_geometry@ortho": {
    "base": "v2_camera_geometry", "camera": "CamOrtho", "cam_pos": (0.0, -5.2, 1.3),
    "cam_target": (0.0, 0.0, 0.6), "ortho_scale": 6.0, "points": _ORTHO_POINTS}}


def ortho_crops(v: dict, res_xy) -> dict:
    """Normalised ROI rects (row 0 = top) for an ortho camera looking from cam_pos at cam_target."""
    pos, tgt = np.array(v["cam_pos"], float), np.array(v["cam_target"], float)
    f = (tgt - pos) / np.linalg.norm(tgt - pos)
    right = np.cross(f, [0.0, 0.0, 1.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, f)
    w, h = res_xy
    out = {}
    for name, pt, hw in v["points"]:
        d = np.array(pt, float) - pos
        u = 0.5 + d @ right / v["ortho_scale"]
        vv = 0.5 + d @ up / (v["ortho_scale"] * h / w)
        cx, cy, hh = u, 1.0 - vv, hw * w / h
        rect = [round(float(min(max(c, 0.0), 1.0)), 4) for c in (cx - hw, cy - hh, cx + hw, cy + hh)]
        if rect[2] - rect[0] < 0.005 or rect[3] - rect[1] < 0.005:
            raise SystemExit(f"[mc_tolerance] ortho ROI {name!r} off-frame: {rect}")
        out[name] = rect
    return out


def scene_entry(manifest: dict, sid: str) -> dict:
    """Manifest entry for a scene id, or a synthesised one for a variant (own crops + camera)."""
    if sid not in VARIANTS:
        e = json.loads(json.dumps(manifest["scenes"][sid]))
    else:
        v = VARIANTS[sid]
        e = json.loads(json.dumps(manifest["scenes"][v["base"]]))
        e["crops"] = ortho_crops(v, (e["settings"]["res_x"], e["settings"]["res_y"]))
        e["v2"]["divergence"] = {}
    if KNOWN.is_file():  # divergences found while pinning (owner 2026-09-29 rule), same form as the manifest's
        for d in tomllib.loads(KNOWN.read_text(encoding="utf-8")).get("divergence", []):
            if d["scene"] == sid:
                e["v2"]["divergence"][d["roi"]] = d["reason"]
    return e


def render(sid: str, leg: str, seed: int, spp: int, stem: Path, threads: int = 8,
           timeout: int = 600) -> np.ndarray:
    """One render through render_leg.py; returns linear HxWx3 (row 0 = top)."""
    base = VARIANTS[sid]["base"] if sid in VARIANTS else sid
    engine, device = {"cycles": ("CYCLES", "cpu"), "cpu": ("CUSTOM_RAYTRACER", "cpu"),
                      "gpu": ("CUSTOM_RAYTRACER", "gpu")}[leg]
    cmd = [str(BLENDER), "-b", "--factory-startup", "--threads", str(threads),
           "--python", str(RENDER_LEG), "--", "--engine", engine, "--device", device,
           "--corpus-manifest", str(MANIFEST), "--corpus-scene", base,
           "--out", str(stem), "--seed", str(seed), "--spp-override", str(spp)]
    if sid in VARIANTS:
        cmd += ["--camera", VARIANTS[sid]["camera"]]
    env = dict(os.environ, OMP_NUM_THREADS=str(threads))
    stem.parent.mkdir(parents=True, exist_ok=True)
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, env=env)
    if "PKG119B_LEG PASS" not in out.stdout:
        raise RuntimeError(f"{sid} {leg} seed={seed}: render leg failed\n{out.stdout[-1500:]}\n{out.stderr[-500:]}")
    return np.load(stem.with_suffix(".npy"))


def roi_means(img: np.ndarray, rect) -> np.ndarray:
    """ROI mean (r, g, b, luminance)."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = rect
    box = img[round(y0 * h):round(y1 * h), round(x0 * w):round(x1 * w)]
    m = box.reshape(-1, 3).mean(axis=0)
    return np.append(m, m @ LUM)


def write_exr(path: Path, img: np.ndarray) -> None:
    os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), np.ascontiguousarray(img[:, :, ::-1].astype(np.float32))):
        raise RuntimeError(f"cannot write {path}")


def read_exr(path: Path) -> np.ndarray:
    os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
    import cv2
    im = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if im is None:
        raise RuntimeError(f"cannot read {path}")
    return np.ascontiguousarray(im[:, :, :3][:, :, ::-1]).astype(np.float32)


def exr_path(sid: str) -> Path:
    return REFS / f"{sid.replace('@', '_')}_cycles.exr"


def reference(sid: str, manifest: dict, work: Path, render_it: bool, seed: int) -> np.ndarray:
    if render_it or not exr_path(sid).is_file():  # variants have no Phase 1 reference
        entry = scene_entry(manifest, sid)
        ref = render(sid, "cycles", seed, entry["v2"]["spp_reference"], work / f"{sid}_cycles_ref")
        write_exr(exr_path(sid), ref)
        return ref
    return read_exr(exr_path(sid))


def measure_leg(sid: str, entry: dict, leg: str, seeds, work: Path) -> dict:
    """Per-ROI seed means at spp_gate: {roi: [seeds x 4]}."""
    per_seed = []
    for s in seeds:
        img = render(sid, leg, s, entry["v2"]["spp_gate"], work / f"{sid}_{leg}_s{s}")
        per_seed.append({n: roi_means(img, r) for n, r in entry["crops"].items()})
    return {n: np.stack([p[n] for p in per_seed]).tolist() for n in entry["crops"]}


def sigma_rel(samples) -> np.ndarray:
    m = np.asarray(samples)
    return m.std(axis=0, ddof=1) / np.maximum(np.abs(m.mean(axis=0)), 1e-12)


def _arr(v, fmt="{:.6g}"):
    return "[" + ", ".join(fmt.format(x) for x in v) + "]"


def build_rois(entry: dict, res: dict) -> list[dict]:
    """Merge the accumulated legs into per-ROI means, sigmas and tolerances."""
    div = entry["v2"].get("divergence", {})
    rois = []
    for name, rect in entry["crops"].items():
        r = {"name": name, "rect": rect}
        legs = {}
        for leg in LEGS:
            samples = res.get("legs", {}).get(leg, {}).get(name)
            if samples is not None:
                legs[leg] = {"mean": np.mean(samples, axis=0), "sigma": sigma_rel(samples)}
        ref = res["ref"][name]
        r["cycles_mean"] = ref
        r["excluded"] = [bool(ref[c] < DARK) for c in range(4)]
        notes = []
        sc = legs["cycles"]["sigma"] if "cycles" in legs else np.zeros(4)
        if "cycles" in legs:
            r["cycles_sigma"] = sc.tolist()
        for leg in ("cpu", "gpu"):
            if leg not in legs:
                continue
            r[f"{leg}_mean"] = legs[leg]["mean"].tolist()
            r[f"{leg}_sigma"] = legs[leg]["sigma"].tolist()
            tol = []
            for c in range(4):
                if r["excluded"][c]:
                    tol.append(0.0)
                    continue
                raw = 3.0 * math.hypot(sc[c], legs[leg]["sigma"][c])
                if raw > BAND_CEIL:
                    notes.append(f"{leg} {CH[c]}: raw 3*sigma = {raw:.3f} > {BAND_CEIL:.2f}, kept unclipped (high-variance ROI)")
                tol.append(max(BAND_FLOOR, raw))
            r[f"{leg}_tol"] = tol
            r[f"{leg}_pin_tol"] = [max(BAND_FLOOR, 3.0 * legs[leg]["sigma"][c] * math.sqrt(1.2))
                                   for c in range(4)]
        if "cpu" in legs and "gpu" in legs:
            r["gpu_cpu_tol"] = [max(GPU_CPU_FLOOR, 3.0 * math.hypot(legs["cpu"]["sigma"][c], legs["gpu"]["sigma"][c]))
                                for c in range(4)]
        r["note"] = "; ".join(notes)
        if name in div:
            r["expected_divergence"] = div[name]
        rois.append(r)
    return rois


def write_toml(results: dict, manifest: dict, seeds, blender_version: str, base: str) -> None:
    L = ["# pkg284 corpus v2 gates -- generated by mc_tolerance.py; bands are measured, never hand-typed.",
         "# Gate: per-ROI per-channel + luminance linear mean ratio Astroray/Cycles; fixed seed, adaptive OFF, denoise OFF.",
         "# tol = max(0.02, 3*sqrt(sigma_cycles^2 + sigma_astroray^2)); GPU/CPU tol floor 0.05; sigmas from the",
         "# seed-to-seed scatter at spp_gate. Channels/luminance with Cycles mean < 0.01 are excluded (tol = 0).",
         "# Vectors are [r, g, b, luminance]. Provisional rows live in provisional_v2.toml. Re-bless rule: README.md.", "",
         "[meta]", f'blender = "{blender_version}"', f"seed = {seeds[0]}", f"mc_seeds = {seeds}",
         "adaptive_sampling = false", "denoise = false", f"band_floor = {BAND_FLOOR}",
         f'blessed_on = "Cycles references: Blender {blender_version}; bands: {len(seeds)} seeds, Cycles + Astroray CPU spread, base commit {base}, pkg284 Phase 2"', ""]
    for sid in sorted(results):
        e = scene_entry(manifest, sid)
        v2 = e["v2"]
        L += [f'[scenes."{sid}"]', f'blend = "{e["blend_path"]}"', f"seed = {v2['seed']}",
              f"spp_gate = {v2['spp_gate']}", f"spp_reference = {v2['spp_reference']}",
              f"res = [{e['settings']['res_x']}, {e['settings']['res_y']}]",
              f"render_gate = {str(v2['render_gate']).lower()}",
              f"gate_c = {str(sid in GATE_C).lower()}"]
        if sid in VARIANTS:
            L += [f'base = "{VARIANTS[sid]["base"]}"', f'camera = "{VARIANTS[sid]["camera"]}"']
        L += [f'reference = "benchmarks/reference_corpus/refs_v2/{exr_path(sid).name}"', ""]
        for r in build_rois(e, results[sid]):
            L += [f'[[scenes."{sid}".roi]]', f'name = "{r["name"]}"', f"rect = {_arr(r['rect'], '{:.4f}')}",
                  f"cycles_mean = {_arr(r['cycles_mean'])}",
                  f"excluded = [{', '.join(str(x).lower() for x in r['excluded'])}]"]
            for k in ("cycles_sigma", "cpu_sigma", "gpu_sigma", "cpu_tol", "cpu_pin_tol", "gpu_tol",
                      "gpu_pin_tol", "gpu_cpu_tol"):
                if k in r:
                    L.append(f"{k} = {_arr(r[k], '{:.4f}')}")
            for k in ("cpu_mean", "gpu_mean"):
                if k in r:
                    L.append(f"{k} = {_arr(r[k])}")
            if r["note"]:
                L.append(f'note = "{r["note"]}"')
            if "expected_divergence" in r:
                L.append(f'expected_divergence = "{r["expected_divergence"]}"')
            L.append("")
    text = "\n".join(L)
    tomllib.loads(text)  # must parse
    GATES.write_text(text, encoding="utf-8", newline="\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenes", nargs="+", help="v2 scene ids incl. variants (default: every render-gated v2 scene + variants)")
    ap.add_argument("--seeds", nargs="+", type=int, default=[278, 279, 280, 281, 282])
    ap.add_argument("--legs", nargs="+", choices=LEGS, default=["cycles", "cpu"],
                    help="legs to (re)measure this run; earlier legs stay in results.json")
    ap.add_argument("--reference", action="store_true",
                    help="re-render the 1024 spp Cycles reference EXR (default: reuse refs_v2/)")
    ap.add_argument("--work-dir", required=True, help="scratch dir for .npy/.png renders + results.json")
    ap.add_argument("--table-only", action="store_true",
                    help="rewrite gates_v2.toml from <work>/results.json without rendering")
    a = ap.parse_args()
    if any(s <= 0 for s in a.seeds):
        sys.exit("seeds must be non-zero (0 is the random sentinel)")
    work = Path(a.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    gated = [s for s, e in manifest["scenes"].items() if "v2" in e and e["v2"]["render_gate"]]
    scenes = a.scenes or sorted(gated) + sorted(VARIANTS)
    res_path = work / "results.json"
    results = json.loads(res_path.read_text()) if res_path.is_file() else {}
    if not a.table_only:
        for sid in scenes:
            print(f"[mc_tolerance] {sid} legs={a.legs}", flush=True)
            entry = scene_entry(manifest, sid)
            res = results.setdefault(sid, {"legs": {}})
            if a.reference or "ref" not in res:
                ref = reference(sid, manifest, work, a.reference, a.seeds[0])
                res["ref"] = {n: roi_means(ref, r).tolist() for n, r in entry["crops"].items()}
            for leg in a.legs:
                res["legs"][leg] = measure_leg(sid, entry, leg, a.seeds, work)
                res["seeds"] = a.seeds
                res_path.write_text(json.dumps(results, indent=1))
    version = next(e["v2"]["blender_version"] for e in manifest["scenes"].values() if "v2" in e)
    base = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True, check=False).stdout.strip()
    write_toml(results, manifest, a.seeds, version, base)
    print(f"[mc_tolerance] wrote {GATES}")


if __name__ == "__main__":
    main()

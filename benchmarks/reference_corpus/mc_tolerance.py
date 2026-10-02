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

``--suite production`` (pkg310) runs the same pipeline over the eight ``prod_*`` production node-tree
scenes: manifest ``production/manifest.json``, references ``production/refs/``, bands written to
``gates_production.toml``, provisional rows in ``provisional_production.toml`` (see SUITES).

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
PROD = CORPUS / "production"
# pkg310: alternative scene populations run through the identical pipeline (--suite NAME).
SUITES = {"production": {"manifest": PROD / "manifest.json", "refs": PROD / "refs",
                         "gates": CORPUS / "gates_production.toml",
                         "known": CORPUS / "provisional_production.toml", "label": "pkg310 production corpus", "bless": "pkg310",
                         # decorrelated (#986: adjacent CPU seeds share seed+tile streams); 278 stays the gate seed
                         "seeds": [278, 1301, 2711, 4177, 6113]}}
ARB = CORPUS / "arbitration"
# pkg307 Phase 2: the three spectral arbitration scenes. Their reference is a Mitsuba 3 spectral render (Cycles is RGB).
SUITES["arbitration"] = {"manifest": ARB / "manifest.json", "refs": ARB / "refs", "gates": ARB / "gates_arbitration.toml",
                         "known": ARB / "no_known_rows.toml", "label": "pkg307 arbitration", "bless": "pkg307",
                         "ref_leg": "mitsuba", "seeds": [278, 279, 280, 281, 282]}
MITSUBA_PY = Path(os.environ.get("ASTRORAY_MITSUBA_PY", r"C:\Users\hgcom\tools\venv-mitsuba\Scripts\python.exe"))
REF_LEG = "cycles"  # which engine renders the scene reference (the arbitration suite uses Mitsuba)
LABEL, BLESS = "pkg284 corpus v2", "pkg284 Phase 2"
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


def use_suite(name: str) -> None:
    """Point the module-level manifest/reference/gates/provisional paths at a SUITES entry (CLI only)."""
    global MANIFEST, REFS, GATES, KNOWN, GATE_C, LABEL, BLESS, REF_LEG
    s = SUITES[name]
    REF_LEG = s.get("ref_leg", "cycles")
    MANIFEST, REFS, GATES, KNOWN = s["manifest"], s["refs"], s["gates"], s["known"]
    LABEL, BLESS = s["label"], s["bless"]
    GATE_C = ()


def render(sid: str, leg: str, seed: int, spp: int, stem: Path, threads: int = 8,
           timeout: int = 600, manifest: Path | None = None, res_percent: int | None = None,
           info: dict | None = None, extra: tuple = ()) -> np.ndarray:
    """One render through render_leg.py; returns linear HxWx3 (row 0 = top). The Blender log is kept
    next to the array as ``<stem>.log`` (pkg310 silent_drop_audit reads the DegradationReport from it).
    ``manifest`` overrides the module manifest (pkg310 tests pass the production one explicitly).
    pkg307: leg ``cycles_gpu`` is Cycles OptiX; ``res_percent`` scales the frame (timing at >= 1280x720);
    a passed ``info`` dict receives the leg's ``PKG307_INFO`` line (render-only seconds, Cycles settings)."""
    base = VARIANTS[sid]["base"] if sid in VARIANTS else sid
    if leg == "mitsuba":  # pkg307 Phase 2: Mitsuba 3 spectral (its own venv), arbitration scenes only
        cmd = [str(MITSUBA_PY), str(ARB / "mitsuba_scenes.py"), "--scene", base, "--spp", str(spp), "--seed", str(seed),
               "--out", str(stem)] + (["--res-percent", str(res_percent)] if res_percent else []) + list(extra)
        stem.parent.mkdir(parents=True, exist_ok=True)
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        stem.with_suffix(".log").write_text(out.stdout + "\n" + out.stderr, encoding="utf-8", errors="replace")
        if "PKG119B_LEG PASS" not in out.stdout:
            raise RuntimeError(f"{sid} mitsuba seed={seed}: render failed\n{out.stdout[-1500:]}\n{out.stderr[-1500:]}")
        if info is not None:
            line = next((ln for ln in out.stdout.splitlines() if ln.startswith("PKG307_INFO ")), None)
            info.update(json.loads(line[len("PKG307_INFO "):]) if line else {})
        return np.load(stem.with_suffix(".npy"))
    engine, device = {"cycles": ("CYCLES", "cpu"), "cycles_gpu": ("CYCLES", "cpu"), "cpu": ("CUSTOM_RAYTRACER", "cpu"),
                      "gpu": ("CUSTOM_RAYTRACER", "gpu")}[leg]
    cmd = [str(BLENDER), "-b", "--factory-startup", "--threads", str(threads),
           "--python", str(RENDER_LEG), "--", "--engine", engine, "--device", device,
           "--corpus-manifest", str(manifest or MANIFEST), "--corpus-scene", base,
           "--out", str(stem), "--seed", str(seed), "--spp-override", str(spp)]
    if sid in VARIANTS:
        cmd += ["--camera", VARIANTS[sid]["camera"]]
    if leg == "cycles_gpu":
        cmd += ["--cycles-leg-device", "gpu"]
    if res_percent is not None:
        cmd += ["--res-percent", str(res_percent)]
    env = dict(os.environ, OMP_NUM_THREADS=str(threads))
    stem.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):  # Blender 5.2 rarely dies in BKE_image_render_write_exr (no sentinel printed): retry a crash
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, env=env)
        if "PKG119B_LEG PASS" in out.stdout or "PKG119B_LEG FAIL" in out.stdout:
            break
    stem.with_suffix(".log").write_text(out.stdout + "\n" + out.stderr, encoding="utf-8", errors="replace")
    if "PKG119B_LEG PASS" not in out.stdout:
        raise RuntimeError(f"{sid} {leg} seed={seed}: render leg failed\n{out.stdout[-1500:]}\n{out.stderr[-500:]}")
    if info is not None:
        line = next((ln for ln in out.stdout.splitlines() if ln.startswith("PKG307_INFO ")), None)
        info.update(json.loads(line[len("PKG307_INFO "):]) if line else {})
    return np.load(stem.with_suffix(".npy"))


def roi_means(img: np.ndarray, rect) -> np.ndarray:
    """ROI mean (r, g, b, luminance)."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = rect
    box = img[round(y0 * h):round(y1 * h), round(x0 * w):round(x1 * w)]
    m = box.reshape(-1, 3).mean(axis=0)
    return np.append(m, m @ LUM)


def score_material(scene_gates: dict, img: np.ndarray, leg: str) -> list[dict]:
    """pkg310: every non-excluded (ROI, channel) of one ``gates_*.toml`` scene against one render.

    ``scene_gates`` is ``tomllib`` output for ``[scenes.<id>]``; ``leg`` is ``cpu`` or ``gpu``. Rows the owner
    declared documented divergences (``expected_divergence``) pin Astroray against its own N-seed mean, the
    same rule as tests/test_corpus_v2_parity.py. Returns dicts with roi, channel, ratio, tol, ok."""
    rows = []
    for roi in scene_gates["roi"]:
        m = roi_means(img, roi["rect"])
        pinned = "expected_divergence" in roi
        den = roi[f"{leg}_mean"] if pinned else roi["cycles_mean"]
        tol = roi[f"{leg}_pin_tol"] if pinned else roi[f"{leg}_tol"]
        for c, ch in enumerate(CH):
            if roi["excluded"][c]:
                continue
            ratio = float(m[c] / den[c])
            rows.append({"roi": roi["name"], "channel": ch, "ratio": ratio, "tol": float(tol[c]),
                         "ok": abs(ratio - 1.0) <= tol[c], "pinned": pinned})
    return rows


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
    return REFS / f"{sid.replace('@', '_')}_{REF_LEG}.exr"


def reference(sid: str, manifest: dict, work: Path, render_it: bool, seed: int) -> np.ndarray:
    if render_it or not exr_path(sid).is_file():  # variants have no Phase 1 reference
        entry = scene_entry(manifest, sid)
        ref = render(sid, REF_LEG, seed, entry["v2"]["spp_reference"], work / f"{sid}_{REF_LEG}_ref", timeout=3600)
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
    L = [f"# {LABEL} gates -- generated by mc_tolerance.py; bands are measured, never hand-typed.",
         "# Gate: per-ROI per-channel + luminance linear mean ratio Astroray/Cycles; fixed seed, adaptive OFF, denoise OFF.",
         "# tol = max(0.02, 3*sqrt(sigma_cycles^2 + sigma_astroray^2)); GPU/CPU tol floor 0.05; sigmas from the",
         "# seed-to-seed scatter at spp_gate. Channels/luminance with Cycles mean < 0.01 are excluded (tol = 0).",
         f"# Vectors are [r, g, b, luminance]. Provisional rows live in {KNOWN.name}. Re-bless rule: README.md.", "",
         "[meta]", f'blender = "{blender_version}"', f"seed = {seeds[0]}", f"mc_seeds = {seeds}",
         "adaptive_sampling = false", "denoise = false", f"band_floor = {BAND_FLOOR}",
         f'blessed_on = "Cycles references: Blender {blender_version}; bands: {len(seeds)} seeds, Cycles + Astroray CPU spread, base commit {base}, {BLESS}"', ""]
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
        L += [f'reference = "{exr_path(sid).relative_to(REPO).as_posix()}"', ""]
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


# --------------------------------------------------------------------------------------------------
# pkg307 -- noise-per-time benchmark (--noise-bench). Metric definitions are pure numpy (unit-tested
# in tests/test_pkg307_noise_bench.py); the stages below drive render_leg.py exactly like the gate pipeline.
# --------------------------------------------------------------------------------------------------
NB_LEGS = ("cycles", "cycles_gpu", "cpu", "gpu", "mitsuba")
NB_LABEL = {"cycles": "Cycles CPU", "cycles_gpu": "Cycles OptiX", "cpu": "Astroray CPU",
            "gpu": "Astroray GPU", "mitsuba": "Mitsuba 3 spectral"}
NB_FRAME = (1280, 720)  # every time is normalised to one frame of this size
NB_GPU_LEGS = ("gpu", "cycles_gpu", "mitsuba")
# (small, large) spp of the differencing pair: both in the linear regime (Cycles OptiX has a ~2 s floor below ~64 spp)
NB_TIMING_SPP = {"gpu": (64, 320), "cycles_gpu": (64, 320), "cpu": (8, 72), "cycles": (8, 72),
                 "mitsuba": (64, 320)}
NB_SPP_MAX = 16384
NB_TAIL = 1e-3  # top 0.1 % of pixels
NB_IMAGE_FLOOR = 0.01  # the 'image' row keeps pixels with reference luminance above this


def floor_pow2(x: float) -> int | None:
    """Largest power of two <= x, None when x < 1."""
    return None if x < 1.0 else 1 << int(math.floor(math.log2(x)))


def equal_time_spp(budget_s: float, t_per_spp_s: float, cap: int = NB_SPP_MAX) -> int | None:
    """spp a leg affords within ``budget_s`` at ``t_per_spp_s`` (per-frame seconds), rounded down to a power of two."""
    n = floor_pow2(budget_s / t_per_spp_s)
    return None if n is None else min(n, cap)


def per_sample_time(t_small: float, t_large: float, n_small: int, n_large: int) -> float:
    """Render-only seconds per sample by spp differencing: (t(N2) - t(N1)) / (N2 - N1) removes start-up,
    scene sync and any other spp-independent cost."""
    return (t_large - t_small) / (n_large - n_small)


def noise_metrics(stack: np.ndarray, ref: np.ndarray, rect, floor: float | None = None,
                  dark: float = DARK, tail: float = NB_TAIL) -> dict:
    """Noise metrics of one ROI from ``stack`` (seeds x H x W x 3 linear) against the reference ``ref`` (H x W x 3).

    relvar_lum  mean over ROI pixels of the across-seed luminance variance / (reference ROI mean luminance)^2
    relvar_rgb  the same per channel (NaN where the reference channel mean < ``dark``)
    chroma      mean over pixels (seed-mean luminance > ``dark``) of sum_c var_seeds(c / max(L, 1e-3))
    bias2       squared offset of the ROI-mean luminance from the reference, relative, minus the seed noise of that
                mean (clipped at 0). ROI-mean level on purpose: a per-pixel bias^2 against a finite-spp reference is
                dominated by the reference's own noise at equal-time budgets.
    relmse      relvar_lum + bias2
    tail_share  share of the total luminance variance held by the top ``tail`` fraction of pixels (at least one)
    ``floor`` keeps only pixels with reference luminance above it (the whole-image row)."""
    s, h, w = stack.shape[:3]
    x0, y0, x1, y1 = rect
    sl = (slice(round(y0 * h), round(y1 * h)), slice(round(x0 * w), round(x1 * w)))
    x = stack[(slice(None),) + sl].astype(np.float64)
    r = ref[sl].astype(np.float64)
    keep = np.ones(r.shape[:2], bool) if floor is None else (r @ LUM) > floor
    xk, rk = x[:, keep], r[keep]
    n = int(keep.sum())
    rm = rk.mean(axis=0)
    r_lum = float(rm @ LUM)
    lum = xk @ LUM
    var_l = lum.var(axis=0, ddof=1)
    var_c = xk.var(axis=0, ddof=1).mean(axis=0)
    chrom = xk / np.maximum(lum, 1e-3)[..., None]
    good = lum.mean(axis=0) > dark
    chroma = float(chrom.var(axis=0, ddof=1).sum(axis=-1)[good].mean()) if good.any() else float("nan")
    m_lum = lum.mean(axis=1)  # per-seed ROI mean
    bias2 = max(0.0, (m_lum.mean() - r_lum) ** 2 - m_lum.var(ddof=1) / s) / r_lum ** 2
    relvar = float(var_l.mean() / r_lum ** 2)
    k = max(1, math.ceil(tail * n))
    tot = float(var_l.sum())
    return {"n_px": n, "ref_lum": r_lum, "relvar_lum": relvar,
            "relvar_rgb": [float(v / m ** 2) if m >= dark else float("nan") for v, m in zip(var_c, rm)],
            "chroma": chroma, "bias2": float(bias2), "relmse": relvar + float(bias2),
            "tail_share": float(np.sort(var_l)[-k:].sum() / tot) if tot > 0 else 0.0}


def nvar_slope(spps, relvars) -> float:
    """d log(N x relVar) / d log N: 0 = plain Monte Carlo (variance ~ 1/N), < 0 = faster than MC (stratified/QMC)."""
    n = np.asarray(spps, float)
    v = np.asarray(relvars, float)
    ok = np.isfinite(v) & (v > 0)
    if ok.sum() < 2:
        return float("nan")
    return float(np.polyfit(np.log(n[ok]), np.log((n * v)[ok]), 1)[0])


def efficiency(relmse: float, t_s: float) -> float:
    """1 / (relMSE x t): larger is better; only ratios between legs are meaningful."""
    return 1.0 / (relmse * t_s) if relmse > 0 and t_s > 0 else float("nan")


def _nb_paths(work: Path, tag: str = "") -> dict:
    """``tag`` separates repeat timing runs that share one (deterministic, cached) render directory."""
    return {"timing": work / f"timing{tag}.json", "renders": work / "renders", "results": work / f"nb_results{tag}.json"}


def _nb_render(sid, leg, spp, seed, work, threads=8, **kw):
    """Cached render of the benchmark frame (manifest resolution) -> linear HxWx3."""
    stem = _nb_paths(work)["renders"] / f"{sid.replace('@', '_')}_{leg}_spp{spp}_s{seed}"
    if stem.with_suffix(".npy").is_file():
        return np.load(stem.with_suffix(".npy"))
    return render(sid, leg, seed, spp, stem, threads=threads, timeout=3600, **kw)


def _gpu_note() -> str:
    q = subprocess.run(["nvidia-smi", "--query-gpu=clocks.sm,clocks.max.sm,temperature.gpu,power.draw",
                        "--format=csv,noheader"], capture_output=True, text=True, check=False)
    return q.stdout.strip() or "nvidia-smi unavailable"


def time_leg(sid: str, leg: str, work: Path, reps: int = 3, spps=None) -> dict:
    """Render-only seconds per sample of one leg, normalised to one 1280x720 frame.

    spp differencing (min-of-``reps`` per point, interleaved, after one discarded burn-in render so the GPU is at
    its working clock). GPU legs render at >= 1280 px wide (res_percent); CPU legs at the manifest resolution, then
    scale by pixel count (CPU cost is linear in pixels, small GPU frames under-fill the device)."""
    n_small, n_large = spps or NB_TIMING_SPP[leg]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = scene_entry(manifest, sid)
    pct = math.ceil(NB_FRAME[0] / entry["settings"]["res_x"] * 100) if leg in NB_GPU_LEGS else None
    tdir = work / "timing"
    best = {n_small: float("inf"), n_large: float("inf")}
    raw, res, gpu_notes, info = [], None, [_gpu_note()], {}
    for rep in range(reps + 1):  # rep 0 is the burn-in
        for n in (n_small, n_large):
            info = {}
            render(sid, leg, 278, n, tdir / f"{sid.replace('@', '_')}_{leg}_n{n}_r{rep}", res_percent=pct,
                   info=info, timeout=3600)
            res = info["res"]
            if rep:
                best[n] = min(best[n], info["render_s"])
                raw.append([rep, n, info["render_s"]])
    gpu_notes.append(_gpu_note())
    t_ps = per_sample_time(best[n_small], best[n_large], n_small, n_large)
    area = res[0] * res[1]
    return {"t_per_spp_frame_s": t_ps * NB_FRAME[0] * NB_FRAME[1] / area, "t_per_spp_at_res_s": t_ps,
            "timing_res": res, "n": [n_small, n_large], "min_s": [best[n_small], best[n_large]], "raw": raw,
            "gpu_clock_notes": gpu_notes, "settings": {k: info.get(k) for k in (
                "pattern", "blur_glossy", "clamp_direct", "clamp_indirect", "adaptive", "denoise",
                "filter_type", "filter_width", "blender")}}


def nb_spp_plan(t_frame: float, budgets, base_spps) -> dict:
    """{spp: [labels]} for one leg: the fixed equal-spp points plus each budget's equal-time spp."""
    plan: dict = {}
    for n in base_spps:
        plan.setdefault(n, []).append(f"spp{n}")
    for b in budgets:
        n = equal_time_spp(b, t_frame)
        if n is not None:
            plan.setdefault(n, []).append(f"{b:g}s")
    return plan


def nb_rows(sid, leg, plan, t_frame, entry, ref, work, seeds) -> list[dict]:
    """Metric rows (every ROI + the whole image) for one scene and leg at every planned spp."""
    rows = []
    rects = {"image": ([0.0, 0.0, 1.0, 1.0], NB_IMAGE_FLOOR), **{n: (r, None) for n, r in entry["crops"].items()}}
    for spp, labels in sorted(plan.items()):
        stack = np.stack([_nb_render(sid, leg, spp, s, work) for s in seeds])
        for name, (rect, floor) in rects.items():
            m = noise_metrics(stack, ref, rect, floor)
            t = spp * t_frame
            rows.append({"scene": sid, "leg": leg, "spp": spp, "labels": labels, "t_frame_s": t, "roi": name,
                         **m, "eff": efficiency(m["relmse"], t), "dark": m["ref_lum"] < DARK})
    return rows


def _git(*args, cwd=REPO) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=False).stdout.strip()


def nb_meta(seeds, budgets, base_spps, timing: dict) -> dict:
    import datetime
    pyd_dir = Path(os.environ.get("ASTRORAY_PYD_DIR", REPO / "build_cuda"))
    pyd = next(iter(pyd_dir.glob("astroray*.pyd")), None)
    first = next(iter(next(iter(timing.values())).values()), {}) if timing else {}
    return {"date": datetime.date.today().isoformat(), "seeds": seeds, "budgets_s": budgets,
            "base_spps": base_spps, "frame": list(NB_FRAME), "ref": "Cycles 1024 spp refs_v2",
            "harness_sha": _git("rev-parse", "--short", "HEAD"),
            "astroray_build": {"pyd": str(pyd), "pyd_mtime": pyd.stat().st_mtime if pyd else None,
                               "build_sha": _git("rev-parse", "--short", "HEAD", cwd=pyd_dir.parent) if pyd else ""},
            "blender": BLENDER.parent.name, "settings": first.get("settings", {}),
            "banner": ("Corpus scenes author blur_glossy = 0 and sample_clamp_indirect = 0 (not Blender's defaults); "
                       "adaptive sampling OFF, denoise OFF; pixel filter and sampling pattern as authored (settings); "
                       "equal-time budgets are per 1280x720 frame, noise is measured per pixel at the manifest "
                       "resolution; bias^2 is ROI-mean level.")}


def arb_calibrate(a, manifest, scenes) -> None:
    """--arb-calibrate: scale each arbitration scene's Mitsuba lamp so its anchor ROI matches the anchor leg.

    Lamp units differ per engine (Blender watts vs radiance) and light transport is linear in emitter power, so one scalar
    per scene fixes the units. The anchor is a ROI whose value does not depend on the effect under test: the
    directly sun/lamp-lit floor against Cycles (RGB-safe), the visible lamp face against Astroray CPU for the narrow-band
    lamp (Cycles cannot render it). Every other ROI is then an independent comparison. Writes calibration.json."""
    work = Path(a.work_dir)
    cal_path = ARB / "calibration.json"
    cal = json.loads(cal_path.read_text()) if cal_path.is_file() else {}
    for sid in scenes:
        entry = scene_entry(manifest, sid)
        anchor = entry["v2"]["anchor"]
        rect = entry["crops"][anchor["roi"]]
        tgt = np.mean([roi_means(render(sid, anchor["leg"], s, 256, work / f"{sid}_{anchor['leg']}_cal_s{s}", timeout=3600), rect)[3]
                       for s in a.seeds[:3]])
        unit = np.mean([roi_means(render(sid, "mitsuba", s, 256, work / f"{sid}_mitsuba_cal_s{s}", timeout=3600,
                                         extra=("--lamp-scale", "1.0")), rect)[3] for s in a.seeds[:3]])
        cal[sid] = {"lamp_scale": float(tgt / unit), "anchor": anchor, "anchor_leg_lum": float(tgt), "mitsuba_unit_scale_lum": float(unit)}
        print(f"[arb-calibrate] {sid}: anchor {anchor} target {tgt:.5g} mitsuba@1 {unit:.5g} -> lamp_scale {tgt / unit:.5g}", flush=True)
    cal_path.write_text(json.dumps(cal, indent=1) + "\n", encoding="utf-8", newline="\n")


def nb_run(a, manifest, scenes) -> None:
    """--noise-bench: stages ``time`` -> ``render`` -> ``report`` (each cached under --work-dir, resumable)."""
    work = Path(a.work_dir)
    paths = _nb_paths(work, a.nb_tag)
    timing = json.loads(paths["timing"].read_text()) if paths["timing"].is_file() else {}
    if "time" in a.nb_stages:
        for sid in scenes:
            for leg in a.nb_legs:
                if leg in timing.get(sid, {}) and not a.nb_retime:
                    continue
                print(f"[noise-bench] time {sid} {leg}", flush=True)
                timing.setdefault(sid, {})[leg] = time_leg(sid, leg, work)
                paths["timing"].write_text(json.dumps(timing, indent=1))
    rows: list[dict] = []
    plans: dict = {}
    for sid in scenes:
        entry = scene_entry(manifest, sid)
        ref = read_exr(exr_path(sid))
        for leg in a.nb_legs:
            t_frame = timing[sid][leg]["t_per_spp_frame_s"]
            plan = nb_spp_plan(t_frame, a.budgets, a.spps)
            plans.setdefault(sid, {})[leg] = {str(k): v for k, v in plan.items()}
            if "render" in a.nb_stages:
                for spp in sorted(plan):
                    for s in a.seeds:
                        print(f"[noise-bench] render {sid} {leg} spp={spp} seed={s}", flush=True)
                        _nb_render(sid, leg, spp, s, work)
            if "report" in a.nb_stages:
                rows += nb_rows(sid, leg, plan, t_frame, entry, ref, work, a.seeds)
    if "report" in a.nb_stages:
        out = {"meta": nb_meta(a.seeds, a.budgets, a.spps, timing), "timing": timing, "plans": plans, "rows": rows}
        paths["results"].write_text(json.dumps(out, indent=1))
        print(f"[noise-bench] wrote {paths['results']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scenes", nargs="+", help="v2 scene ids incl. variants (default: every render-gated v2 scene + variants)")
    ap.add_argument("--seeds", nargs="+", type=int, default=None,
                    help="MC seeds (default 278-282; the production suite defaults to decorrelated seeds, see SUITES)")
    ap.add_argument("--gates", type=Path, default=None,
                    help="write the generated bands here instead of the suite's gates file (default gates_v2.toml, "
                         "or gates_production.toml with --suite production)")
    ap.add_argument("--legs", nargs="+", choices=LEGS, default=["cycles", "cpu"],
                    help="legs to (re)measure this run; earlier legs stay in results.json")
    ap.add_argument("--reference", action="store_true",
                    help="re-render the 1024 spp Cycles reference EXR (default: reuse refs_v2/)")
    ap.add_argument("--work-dir", required=True, help="scratch dir for .npy/.png renders + results.json")
    ap.add_argument("--suite", choices=sorted(SUITES), default=None,
                    help="scene population (default: the pkg284 v2 corpus)")
    ap.add_argument("--noise-bench", action="store_true",
                    help="pkg307: noise-per-time benchmark (equal-spp and equal-time tables) instead of the gate bands")
    ap.add_argument("--arb-calibrate", action="store_true", help="pkg307: match the Mitsuba lamp scale to each scene's anchor ROI")
    ap.add_argument("--nb-legs", nargs="+", choices=NB_LEGS, default=["cycles", "cycles_gpu", "cpu", "gpu"])
    ap.add_argument("--nb-stages", nargs="+", choices=("time", "render", "report"), default=["time", "render", "report"])
    ap.add_argument("--nb-tag", default="", help="suffix for timing/results files (repeat-run reproducibility check)")
    ap.add_argument("--nb-retime", action="store_true", help="redo cached per-sample timings")
    ap.add_argument("--budgets", nargs="+", type=float, default=[2.0, 10.0, 60.0],
                    help="equal-time budgets in seconds per 1280x720 frame")
    ap.add_argument("--spps", nargs="+", type=int, default=[16, 64, 256], help="equal-spp points")
    ap.add_argument("--table-only", action="store_true",
                    help="rewrite gates_v2.toml from <work>/results.json without rendering")
    a = ap.parse_args()
    if a.suite:
        use_suite(a.suite)
    if a.gates:
        global GATES
        GATES = a.gates.resolve()
    a.seeds = a.seeds or (SUITES[a.suite]["seeds"] if a.suite else [278, 279, 280, 281, 282])
    if any(s <= 0 for s in a.seeds):
        sys.exit("seeds must be non-zero (0 is the random sentinel)")
    work = Path(a.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    gated = [s for s, e in manifest["scenes"].items() if "v2" in e and e["v2"]["render_gate"]]
    scenes = a.scenes or sorted(gated) + ([] if a.suite else sorted(VARIANTS))
    if a.arb_calibrate:
        arb_calibrate(a, manifest, a.scenes or sorted(gated))
        return
    if a.noise_bench:
        nb_run(a, manifest, a.scenes or sorted(gated) + sorted(VARIANTS))
        return
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

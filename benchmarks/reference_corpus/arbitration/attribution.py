"""pkg327 Phase A -- minor-channel chroma attribution driver (CPU only, evidence only, no gate).

Renders the production scenes (and the arbitration chroma proxies) through the existing legs and tabulates the
Astroray/Cycles ratio per ROI channel for each attribution variant. It adds no renderer of its own:

* Blender legs go through ``mc_tolerance.render`` -> ``render_leg.py`` with ``--attrib-spec`` (controls ``albedo_grey``,
  ``world_flat_white``, ``albedo_const``, ``lambertian``; each receipted, no-op guarded).
* Mitsuba legs go through ``mc_tolerance.render(leg="mitsuba")`` -> ``mitsuba_scenes.py --variant scalar_spectral|scalar_rgb``.

    ASTRORAY_PYD_DIR=<staged addon> python attribution.py blender --work-dir W [--scenes ...] [--variants ...] [--seeds ...]
    python attribution.py mitsuba --work-dir W [--scenes arb_chroma_bowl ...] [--seeds ...]
    python attribution.py smooth-hdri --out hdri_smoothsun.hdr; export ASTRORAY_ATTRIB_SMOOTH_HDRI=<that file>
    python attribution.py table   --work-dir W [--json out.json]
    python attribution.py proxy   --work-dir W [--json out.json]   # Astroray/Cycles vs Mitsuba spectral/rgb

Renders are cached in ``W`` (``<scene>__<variant>__<leg>_s<seed>.npy``); re-running skips finished ones. Run one driver
at a time (this PC hard-resets under combined CPU load).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path[:0] = [str(HERE.parent), str(HERE)]

import mc_tolerance as mt  # noqa: E402

SEEDS = [278, 1301, 2711, 4177]  # first four of the production suite's decorrelated seeds (#986); 278 = gate seed
PROD_MANIFEST = mt.PROD / "manifest.json"
HDRI_PROXIES = ("arb_chroma_warm_hdri", "arb_chroma_patches", "arb_chroma_bowl_stage", "arb_chroma_hero_wood", "arb_chroma_hero_car", "arb_chroma_hero_pbr")
SMOOTH_HDRI = os.environ.get("ASTRORAY_ATTRIB_SMOOTH_HDRI", "")  # evidence-local derived HDRI (see the attribution doc)
ARB_MANIFEST = mt.ARB / "manifest.json"
CALIBRATION = mt.ARB / "calibration.json"

# Scene -> Principled material the albedo controls act on, the equal-luminance grey (Rec.709 luminance of the
# material's mean linear albedo, read from its constants / ramp / image mean), the ROIs under attribution.
TARGETS = {
    "prod_curves_geometry": {"material": "CurvesGeometry", "grey": 0.34, "rois": ["inner_backface", "outer_front"]},
    "prod_wood": {"material": "Wood", "grey": 0.27, "rois": ["grain_center", "grain_left", "grain_right", "lower"]},
    "prod_car_paint": {"material": "CarPaint", "grey": 0.40, "rois": ["lit_front", "upper_flake", "lower_shadowed"]},
    "prod_pbr_group": {"material": "PbrGroup", "grey": 0.19, "rois": ["lower", "left", "centre"]},
    "prod_light_path": {"material": "RayLengthFloor", "grey": 0.33, "rois": ["floor_near", "floor_far"]},
}


def variant_specs(scene: str) -> dict[str, list]:
    t = TARGETS.get(scene)
    out = {"baseline": []}
    if t:
        grey = {"kind": "albedo_grey", "material": t["material"], "level": t["grey"]}
        flat = {"kind": "world_flat_white"}
        out.update({"albedo_grey": [grey], "world_flat_white": [flat], "grey_flat": [grey, flat]})
    if scene in HDRI_PROXIES and SMOOTH_HDRI:  # pkg327: the HDRI with its sun smoothed to a 2 degree blob, same energy
        out["hdri_smooth"] = [{"kind": "world_hdri", "path": SMOOTH_HDRI}]
    if scene == "prod_light_path":  # #1199 recipe: Lambertian floor, then an R-only albedo sweep (G, B = ramp value at floor_near)
        m = t["material"]
        out["lambertian"] = [{"kind": "lambertian", "material": m}]
        # the ramp (0.75, 0.25, 0.15) -> (0.15, 0.30, 0.75) at the floor_near camera ray (4.5 m x 0.12 = 0.54), as one constant colour
        out["ramp_const"] = [{"kind": "albedo_const", "material": m, "rgb": [0.426, 0.277, 0.474]}]
        for r in (0.15, 0.30, 0.48, 0.75):
            out[f"rsweep_r{round(r * 100):03d}"] = [{"kind": "albedo_const", "material": m, "rgb": [r, 0.38, 0.49]}]
        out["rsweep_lamb_r048"] = [{"kind": "lambertian", "material": m},
                                    {"kind": "albedo_const", "material": m, "rgb": [0.48, 0.38, 0.49]}]
    return out


def stem(work: Path, scene: str, variant: str, leg: str, seed: int) -> Path:
    return work / f"{scene}__{variant}__{leg}_s{seed}"


def blender_render(work, scene, variant, leg, seed, spp, spec, manifest):
    s = stem(work, scene, variant, leg, seed)
    if s.with_suffix(".npy").is_file():
        return np.load(s.with_suffix(".npy"))
    extra = ("--attrib-spec", json.dumps(spec)) if spec else ()
    img = mt.render(scene, leg, seed, spp, s, manifest=manifest, extra=extra)
    log = s.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
    if spec and "PKG327_ATTRIB" not in log:
        raise RuntimeError(f"{s.name}: no PKG327_ATTRIB receipt (control did not run)")
    if leg == "cpu" and '"effective_device": "gpu"' in log:
        raise RuntimeError(f"{s.name}: the CPU leg ran on the GPU")
    return img


def cmd_blender(a):
    work = Path(a.work_dir)
    mpath = PROD_MANIFEST if a.manifest == "prod" else ARB_MANIFEST
    for scene in a.scenes:
        specs = variant_specs(scene)
        for variant in (a.variants or list(specs)):
            if variant not in specs:  # e.g. hdri_smooth exists only for the HDRI proxies
                continue
            for seed in a.seeds:
                for leg in a.legs:  # Cycles then Astroray per seed: one render at a time
                    blender_render(work, scene, variant, leg, seed, a.spp, specs[variant], mpath)
                print(f"[attrib] {scene} {variant} seed {seed} done", flush=True)


def cmd_mitsuba(a):
    work = Path(a.work_dir)
    for scene in a.scenes:
        for variant in a.mi_variants:
            for seed in a.seeds:
                s = stem(work, scene, variant + a.tag, "mitsuba", seed)
                if not s.with_suffix(".npy").is_file():
                    mt.render(scene, "mitsuba", seed, a.spp, s, timeout=3600,
                              extra=("--variant", variant) + (("--hdri", a.hdri) if a.hdri else ()))
                print(f"[attrib] {scene} {variant} seed {seed} done", flush=True)


def _rois(scene: str) -> dict:
    man = ARB_MANIFEST if scene.startswith("arb_") else PROD_MANIFEST
    return json.loads(man.read_text(encoding="utf-8"))["scenes"][scene]["crops"]


def _means(work: Path, scene: str, variant: str, leg: str, roi: str) -> np.ndarray | None:
    """(seeds x 4) ROI means (r, g, b, L) from the cached renders."""
    rect = _rois(scene)[roi]
    rows = [mt.roi_means(np.load(p), rect) for p in sorted(work.glob(f"{scene}__{variant}__{leg}_s*.npy"))]
    return np.stack(rows) if rows else None


def _ratio(num: np.ndarray, den: np.ndarray):
    """Ratio of seed means and its delta-method standard error, per channel."""
    n, d = len(num), len(den)
    mn, md = num.mean(0), den.mean(0)
    se = np.sqrt((num.std(0, ddof=1) / np.sqrt(n) / mn) ** 2 + (den.std(0, ddof=1) / np.sqrt(d) / md) ** 2) if n > 1 and d > 1 else np.full(4, np.nan)
    return mn / md, np.abs(mn / md) * se


def cmd_table(a):
    work = Path(a.work_dir)
    out = {}
    for scene in sorted({p.name.split("__")[0] for p in work.glob("*__*__cpu_s*.npy")}):
        for variant in sorted({p.name.split("__")[1] for p in work.glob(f"{scene}__*__cpu_s*.npy")}):
            for roi in (TARGETS.get(scene, {}).get("rois") or list(_rois(scene))):
                num, den = _means(work, scene, variant, "cpu", roi), _means(work, scene, variant, "cycles", roi)
                if num is None or den is None:
                    continue
                r, se = _ratio(num, den)
                out.setdefault(scene, {}).setdefault(roi, {})[variant] = {
                    "n_astroray": len(num), "n_cycles": len(den), "ratio": r.round(4).tolist(), "se": se.round(4).tolist(),
                    "astroray_mean": num.mean(0).round(5).tolist(), "cycles_mean": den.mean(0).round(5).tolist()}
    for scene, rois in out.items():
        print(f"== {scene}  (Astroray CPU / Cycles CPU; r g b L; +-1 SE)")
        for roi, variants in rois.items():
            for v, d in variants.items():
                cells = "  ".join(f"{x:.3f}+-{e:.3f}" for x, e in zip(d["ratio"], d["se"]))
                print(f"  {roi:16s} {v:18s} n={d['n_astroray']}/{d['n_cycles']}  {cells}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")


def cmd_proxy(a):
    """Arbitration table: Astroray/Cycles vs Mitsuba scalar_spectral/scalar_rgb per proxy ROI channel."""
    work = Path(a.work_dir)
    out = {}
    for scene in mt_proxy_scenes():
        for roi in _rois(scene):
            hd = scene in HDRI_PROXIES
            bv = a.blender_variant if hd else "baseline"
            parts = {"astroray": _means(work, scene, bv, "cpu", roi), "cycles": _means(work, scene, bv, "cycles", roi),
                     "mi_spectral": _means(work, scene, "scalar_spectral" + (a.tag if hd else ""), "mitsuba", roi),
                     "mi_rgb": _means(work, scene, "scalar_rgb" + (a.tag if hd else ""), "mitsuba", roi)}
            if any(v is None for v in parts.values()):
                continue
            ac, ac_se = _ratio(parts["astroray"], parts["cycles"])
            ms, ms_se = _ratio(parts["mi_spectral"], parts["mi_rgb"])
            se = np.sqrt(ac_se ** 2 + ms_se ** 2)
            diff = ac - ms
            band = 2.0 * se + a.floor
            cyc_mi = _ratio(parts["cycles"], parts["mi_rgb"])[0]      # sanity: the RGB engines agree on the scene
            ast_mi = _ratio(parts["astroray"], parts["mi_spectral"])[0]  # sanity: the spectral engines agree
            out.setdefault(scene, {})[roi] = {
                "astroray_over_cycles": ac.round(4).tolist(), "astroray_over_cycles_se": ac_se.round(4).tolist(),
                "mi_spectral_over_rgb": ms.round(4).tolist(), "mi_spectral_over_rgb_se": ms_se.round(4).tolist(),
                "difference": diff.round(4).tolist(), "band": band.round(4).tolist(),
                "agree": [bool(abs(d) <= b) for d, b in zip(diff, band)],
                "shift_reproduced": [bool(abs(m - 1.0) > 2.0 * e and abs(x - 1.0) > 2.0 * f and (m - 1.0) * (x - 1.0) > 0 and abs(d) <= b)
                                     for m, e, x, f, d, b in zip(ms, ms_se, ac, ac_se, diff, band)],
                "cycles_over_mi_rgb": cyc_mi.round(4).tolist(), "astroray_over_mi_spectral": ast_mi.round(4).tolist(),
                "means": {k: v.mean(0).round(5).tolist() for k, v in parts.items()}, "seeds": {k: len(v) for k, v in parts.items()}}
    for scene, rois in out.items():
        print(f"== {scene}  (r g b L)")
        for roi, d in rois.items():
            f = lambda k: "  ".join(f"{x:.3f}" for x in d[k])  # noqa: E731
            print(f"  {roi:16s} A/C {f('astroray_over_cycles')} | Ms/Mr {f('mi_spectral_over_rgb')} | diff {f('difference')} "
                  f"| agree {''.join('Y' if x else 'n' for x in d['agree'])} repro {''.join('Y' if x else '-' for x in d['shift_reproduced'])}"
                  f" | C/Mr {f('cycles_over_mi_rgb')} | A/Ms {f('astroray_over_mi_spectral')}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")


def cmd_calibrate_stage(a):
    """Mitsuba scale of the stage area lamp, from the lamp alone: Cycles with only the area lamp on (``lights_only``) over Mitsuba
    scalar_rgb with only the lamp at scale 1, on the grey patch of arb_chroma_patches (the ratio is the same on every ROI; the sun and the
    HDRI are in physical units and are checked the same way, see the attribution doc)."""
    work = Path(a.work_dir)
    scene, roi = "arb_chroma_patches", "grey"
    vals = {"cycles": [], "mitsuba": []}
    for seed in SEEDS[:2]:
        sc = stem(work, scene, "calib_area", "cycles", seed)
        img = np.load(sc.with_suffix(".npy")) if sc.with_suffix(".npy").is_file() else mt.render(
            scene, "cycles", seed, 256, sc, manifest=ARB_MANIFEST, extra=("--attrib-spec", json.dumps([{"kind": "lights_only", "keep": ["area"]}])))
        vals["cycles"].append(mt.roi_means(img, _rois(scene)[roi])[3])
        sm = stem(work, scene, "calib_area", "mitsuba", seed)
        img = np.load(sm.with_suffix(".npy")) if sm.with_suffix(".npy").is_file() else mt.render(
            scene, "mitsuba", seed, a.spp, sm, timeout=3600, extra=("--variant", "scalar_rgb", "--lamp-scale", "1", "--keep", "area"))
        vals["mitsuba"].append(mt.roi_means(img, _rois(scene)[roi])[3])
    scale = float(np.mean(vals["cycles"]) / np.mean(vals["mitsuba"]))
    cal = json.loads(CALIBRATION.read_text(encoding="utf-8")) if CALIBRATION.is_file() else {}
    cal["arb_chroma_stage"] = {"lamp_scale": scale, "anchor": {"scene": scene, "roi": roi, "leg": "cycles", "part": "area lamp only"},
                               "cycles_area_only_lum": float(np.mean(vals["cycles"])), "mitsuba_rgb_area_only_lum_scale1": float(np.mean(vals["mitsuba"]))}
    CALIBRATION.write_text(json.dumps(cal, indent=1) + chr(10), encoding="utf-8", newline=chr(10))
    print(f"[attrib] stage lamp scale {scale:.4f} (area-only L: Cycles {np.mean(vals['cycles']):.5f}, Mitsuba rgb at scale 1 {np.mean(vals['mitsuba']):.5f})")


def cmd_smooth_hdri(a):
    """Derived attribution HDRI: the production HDRI with its sun (the 6 texels above 1 % of the peak luminance, 84 % of the energy)
    replaced by a Gaussian of the same solid-angle-integrated RGB energy (sigma 6 texels, about 2 degrees) over the local sky level.
    Mitsuba's spectral envmap is not texel-invariant for the 1.6e5 sun texels (grey patch G/B 0.983/0.970 under the raw HDRI), so it only
    arbitrates a HDRI without that peak; Astroray and Cycles are unchanged by the smoothing (see the attribution doc)."""
    import cv2

    src = REPO / "benchmarks" / "reference_corpus" / "assets" / "syferfontein_18d_clear_1k.hdr"
    rgb = cv2.imread(str(src), cv2.IMREAD_UNCHANGED).astype(np.float64)[:, :, ::-1].copy()
    h, w, _ = rgb.shape
    lum = rgb @ mt.LUM
    sun = lum > lum.max() * 0.01
    sa = np.sin((np.arange(h) + 0.5) / h * np.pi)[:, None] * np.ones((1, w))  # solid angle per equirect texel, up to a constant
    energy = (rgb * (sa * sun)[..., None]).sum((0, 1))
    ys, xs = np.nonzero(sun)
    cy, cx = ys.mean(), xs.mean()
    ring = np.zeros_like(sun)
    for dy in range(-6, 7):
        for dx in range(-6, 7):
            ring |= np.roll(np.roll(sun, dy, 0), dx, 1)
    out = rgb.copy()
    out[sun] = rgb[ring & ~sun].mean(0)
    yy, xx = np.mgrid[0:h, 0:w]
    g = np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 6.0 ** 2))
    out += (g / (g * sa).sum())[..., None] * energy
    dst = Path(a.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dst), out[:, :, ::-1].astype(np.float32))
    e0, e1 = (rgb * sa[..., None]).sum((0, 1)), (out * sa[..., None]).sum((0, 1))
    print(f"[attrib] wrote {dst} (sun at row {cy:.1f} col {cx:.1f}; peak {rgb.max():.0f} -> {out.max():.0f}; energy ratio {(e1 / e0).round(4).tolist()})")


def mt_proxy_scenes():
    return [s for s in json.loads(ARB_MANIFEST.read_text(encoding="utf-8"))["scenes"] if s.startswith("arb_chroma_")]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("blender")
    b.add_argument("--scenes", nargs="+", default=list(TARGETS))
    b.add_argument("--variants", nargs="+", default=None)
    b.add_argument("--legs", nargs="+", choices=("cycles", "cpu"), default=["cycles", "cpu"])
    b.add_argument("--manifest", choices=("prod", "arb"), default="prod")
    m = sub.add_parser("mitsuba")
    m.add_argument("--scenes", nargs="+", required=True)
    m.add_argument("--mi-variants", nargs="+", default=["scalar_spectral", "scalar_rgb"])
    m.add_argument("--hdri", default="", help="override the HDRI of arb_chroma_*_hdri scenes (use with --tag)")
    m.add_argument("--tag", default="", help="suffix appended to the Mitsuba variant name in the cache, e.g. -smooth")
    for p in (b, m):
        p.add_argument("--work-dir", required=True)
        p.add_argument("--seeds", nargs="+", type=int, default=SEEDS)
        p.add_argument("--spp", type=int, default=64)
    q = sub.add_parser("proxy")
    q.add_argument("--work-dir", required=True)
    q.add_argument("--json", default="")
    q.add_argument("--blender-variant", default="baseline", help="Blender-leg variant of the HDRI proxy (e.g. hdri_smooth)")
    q.add_argument("--tag", default="", help="Mitsuba variant suffix of the HDRI proxy (e.g. -smooth)")
    q.add_argument("--floor", type=float, default=0.01, help="agreement band = 2 x combined SE + this (engine-model differences)")
    h = sub.add_parser("smooth-hdri")
    h.add_argument("--out", required=True)
    c = sub.add_parser("calibrate-stage")
    c.add_argument("--work-dir", required=True)
    c.add_argument("--spp", type=int, default=1024)
    t = sub.add_parser("table")
    t.add_argument("--work-dir", required=True)
    t.add_argument("--json", default="")
    a = ap.parse_args(argv)
    {"blender": cmd_blender, "mitsuba": cmd_mitsuba, "table": cmd_table, "proxy": cmd_proxy, "calibrate-stage": cmd_calibrate_stage, "smooth-hdri": cmd_smooth_hdri}[a.cmd](a)


if __name__ == "__main__":
    main()

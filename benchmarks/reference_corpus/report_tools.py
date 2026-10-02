# -*- coding: utf-8 -*-
"""pkg259 Phase-1-polish -- reference-corpus report tooling.

Runs in the repo's normal Python environment, NOT inside Blender (Blender's
bundled Python has no PIL -- see ``benchmarks/blender_parity/harness.py``'s
``_npy_to_png``, reused here rather than re-derived, per CLAUDE.md Sec 5b).

Converts a ``render_leg.py`` linear ``.npy`` render to a display PNG, then
turns a scene's ``manifest.json`` ``crops`` entries (name -> normalised
``[x0, y0, x1, y1]``) into first-class per-crop PNGs cropped from that SAME
establishing render (never a separate re-render, per the design doc Sec 1.1)
plus two contact sheets: the full Cycles-vs-Astroray establishing shot, and
a per-crop grid. Both use the label-bar-plus-image stacking convention the
Phase-1 ``<family>_contact_sheet.png`` renders already established.

Registered: ``scripts/README.md``.

Usage (after rendering both engines with
``benchmarks/blender_parity/render_leg.py --load-blend``, which writes
``<out>.npy``)::

    python benchmarks/reference_corpus/report_tools.py \
        --family materials_hall \
        --cycles-npy <out>/materials_hall_cycles_cpu.npy \
        --astroray-npy <out>/materials_hall_astroray_cpu.npy \
        --manifest benchmarks/reference_corpus/scenes/manifest.json \
        --out-dir benchmarks/reference_corpus/refs
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.blender_parity.harness import _npy_to_png  # noqa: E402

DISPLAY_NAME = {"cycles_cpu": "Cycles", "astroray_cpu": "Astroray"}

LABEL_BAR_H = 22
NAME_HEADER_H = 18
GAP = 14
SHEET_BG = (20, 20, 24)
LABEL_BG = (20, 20, 24)
LABEL_FG = (230, 230, 230)


def _label_bar(width: int, text: str):
    from PIL import Image, ImageDraw
    bar = Image.new("RGB", (width, LABEL_BAR_H), LABEL_BG)
    ImageDraw.Draw(bar).text((8, LABEL_BAR_H // 2), text, fill=LABEL_FG, anchor="lm")
    return bar


def stack_labeled(panels):
    """Vertically stack ``(label, PIL.Image)`` panels with a label bar above
    each -- the convention the Phase-1 ``<family>_contact_sheet.png``
    renders already use for the Cycles-vs-Astroray comparison."""
    from PIL import Image
    width = max(im.width for _, im in panels)
    total_h = sum(LABEL_BAR_H + im.height for _, im in panels) + GAP * (len(panels) - 1)
    sheet = Image.new("RGB", (width, total_h), SHEET_BG)
    y = 0
    for label, im in panels:
        sheet.paste(_label_bar(width, label), (0, y))
        y += LABEL_BAR_H
        sheet.paste(im, ((width - im.width) // 2, y))
        y += im.height + GAP
    return sheet


def crop_image(im, rect):
    """Crop a PIL image to a normalised ``[x0, y0, x1, y1]`` rect (the
    ``manifest.json`` ``crops`` shape from ``scene_library._crop_rect``)."""
    w, h = im.size
    x0, y0, x1, y1 = rect
    box = (int(round(x0 * w)), int(round(y0 * h)), int(round(x1 * w)), int(round(y1 * h)))
    return im.crop(box)


def build_crop_grid(names, crops_by_engine, engines):
    """Horizontal strip of per-crop tiles; each tile stacks one row per
    engine (in ``engines`` order) under a name header, left-aligned so
    differently-sized crops (a wide alcove next to a narrow one) don't force
    a uniform grid cell size."""
    from PIL import Image, ImageDraw
    tiles = []
    for name in names:
        imgs = [(eng, crops_by_engine[eng][name]) for eng in engines if name in crops_by_engine[eng]]
        if not imgs:
            continue
        w = max(im.width for _, im in imgs)
        h = NAME_HEADER_H + sum(LABEL_BAR_H + im.height for _, im in imgs)
        tile = Image.new("RGB", (w, h), SHEET_BG)
        ImageDraw.Draw(tile).text((2, 2), name, fill=LABEL_FG)
        y = NAME_HEADER_H
        for eng, im in imgs:
            tile.paste(_label_bar(w, DISPLAY_NAME.get(eng, eng)), (0, y))
            y += LABEL_BAR_H
            tile.paste(im, (0, y))
            y += im.height
        tiles.append(tile)
    if not tiles:
        raise ValueError("no crops to grid")
    total_w = sum(t.width for t in tiles) + GAP * (len(tiles) - 1)
    total_h = max(t.height for t in tiles)
    sheet = Image.new("RGB", (total_w, total_h), SHEET_BG)
    x = 0
    for t in tiles:
        sheet.paste(t, (x, 0))
        x += t.width + GAP
    return sheet


def build_family_report(family: str, manifest_path: Path, out_dir: Path,
                         engine_npys: dict) -> dict:
    """Convert each engine's ``.npy`` to a PNG, crop every ``manifest.json``
    ``crops`` entry from it, and write the full-shot + crop-grid contact
    sheets. ``engine_npys``: ``{"cycles_cpu": Path|None, "astroray_cpu":
    Path|None}``. Returns the set of paths written."""
    from PIL import Image

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["scenes"][family]
    crops = entry.get("crops", {})

    out_dir.mkdir(parents=True, exist_ok=True)
    crops_dir = out_dir / f"{family}_crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    written = {"engine_pngs": {}, "crops": {}, "sheets": {}}

    engine_pngs = {}
    for label, npy in engine_npys.items():
        if not npy:
            continue
        npy = Path(npy)
        png_path = out_dir / f"{family}_{label}.png"
        _npy_to_png(npy, png_path)
        engine_pngs[label] = png_path
        written["engine_pngs"][label] = png_path

    if engine_pngs:
        panels = [(DISPLAY_NAME.get(label, label), Image.open(png))
                  for label, png in engine_pngs.items()]
        sheet_path = out_dir / f"{family}_contact_sheet.png"
        stack_labeled(panels).save(sheet_path)
        written["sheets"]["full"] = sheet_path

    if crops and engine_pngs:
        crops_by_engine = {}
        for label, png in engine_pngs.items():
            im = Image.open(png)
            crops_by_engine[label] = {}
            for name, rect in crops.items():
                crop_im = crop_image(im, rect)
                crop_path = crops_dir / f"{name}_{label}.png"
                crop_im.save(crop_path)
                crops_by_engine[label][name] = crop_im
                written["crops"][(name, label)] = crop_path

        engines_present = list(engine_pngs.keys())
        grid_path = out_dir / f"{family}_crops_contact_sheet.png"
        build_crop_grid(list(crops.keys()), crops_by_engine, engines_present).save(grid_path)
        written["sheets"]["crops"] = grid_path

    return written


def build_production_report(work: Path, out_dir: Path, seed: int = 278) -> dict:
    """pkg310: per-material Cycles | Astroray CPU | Astroray GPU contact sheets (ROIs drawn), a
    band-utilisation chart and ``production_summary.json`` (N/8 per backend) from the seed-``seed``
    renders that ``mc_tolerance.render`` / tests/test_production_corpus.py keep in ``work``.
    Band utilisation = worst |ratio - 1| / tol over the material's ROI channels (<= 1 is in band)."""
    import numpy as np
    import tomllib
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from results_layout import save_comparison_sheet, save_stat_chart

    from benchmarks.reference_corpus import mc_tolerance as MC

    gates = tomllib.loads((REPO_ROOT / "benchmarks" / "reference_corpus" / "gates_production.toml")
                          .read_text(encoding="utf-8"))["scenes"]
    manifest = json.loads((MC.SUITES["production"]["manifest"]).read_text(encoding="utf-8"))["scenes"]
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {"materials": {}, "seed": seed}
    util = {"cpu": [], "gpu": []}
    names = sorted(gates)
    for sid in names:
        g = gates[sid]
        h, w = g["res"][1], g["res"][0]
        ref = MC.read_exr(REPO_ROOT / g["reference"])
        tiles = [(f"Cycles {g['spp_reference']} spp", ref)]
        entry = summary["materials"][sid] = {}
        for leg, label in (("cpu", "Astroray CPU"), ("gpu", "Astroray GPU")):
            f = work / f"{sid}_{leg}_s{seed}.npy"
            if not f.is_file():  # fail closed: a missing leg must not read as "0 deviation"
                raise FileNotFoundError(f"missing {leg} render for {sid}: {f} (run the leg first)")
            img = np.load(f)
            tiles.append((f"{label} {g['spp_gate']} spp", img))
            rows = MC.score_material(g, img, leg)
            worst = max(abs(r["ratio"] - 1.0) / r["tol"] for r in rows)
            util[leg].append(round(worst, 3))
            entry[leg] = {"pass": all(r["ok"] for r in rows), "channels": len(rows),
                          "out_of_band": [r for r in rows if not r["ok"]], "worst_band_utilisation": round(worst, 3)}
        tiles = [(t, np.clip(px, 0.0, None) ** (1.0 / 2.2)) for t, px in tiles]
        rois = {r["name"]: (r["rect"][0] * w, r["rect"][1] * h, r["rect"][2] * w, r["rect"][3] * h) for r in g["roi"]}
        save_comparison_sheet(out_dir / f"{sid}_sheet.png", tiles, f"{sid} (display gamma 2.2, seed {seed})", rois)
        _ = manifest[sid]
    for leg in ("cpu", "gpu"):
        summary[leg] = {"pass": sum(1 for m in summary["materials"].values() if m.get(leg, {}).get("pass")),
                        "of": len(names)}
    save_stat_chart(out_dir / "band_utilisation_chart.png",
                    [{"label": "Astroray CPU", "x": names, "y": util["cpu"], "role": "cpu"},
                     {"label": "Astroray GPU", "x": names, "y": util["gpu"], "role": "gpu"}],
                    title="Production corpus: worst ROI-channel deviation / MC band",
                    xlabel="material", ylabel="|ratio - 1| / tol (<= 1 in band)", ref=(1.0, "band edge"),
                    meta={"suite": "production", "seed": seed, "summary": summary})
    (out_dir / "production_summary.json").write_text(json.dumps(summary, indent=1) + "\n",
                                                     encoding="utf-8", newline="\n")
    return summary


# --------------------------------------------------------------------------------------------------
# pkg307 -- noise-per-time report: tables, charts and equal-time contact sheets from mc_tolerance.py
# --noise-bench output (<work>/nb_results.json + renders/). Curated-tree rules: tests/results_layout.py.
# --------------------------------------------------------------------------------------------------
NB_ORDER = ("cycles", "cycles_gpu", "cpu", "gpu", "mitsuba")
NB_NAME = {"cycles": "Cycles CPU", "cycles_gpu": "Cycles OptiX", "cpu": "Astroray CPU", "gpu": "Astroray GPU",
           "mitsuba": "Mitsuba 3 spectral"}
# fixed colours per role (test-results-conventions section 4); OptiX is the lighter Cycles grey, Mitsuba the 'other' green
NB_COLOR = {"cycles": "#52514e", "cycles_gpu": "#9a9893", "cpu": "#2a78d6", "gpu": "#eb6834", "mitsuba": "#1baf7a"}
NB_SURFACE = "#fcfcfb"


def _nb_load(work: Path, tag: str = "") -> dict:
    return json.loads((Path(work) / f"nb_results{tag}.json").read_text(encoding="utf-8"))


def nb_index(res: dict) -> dict:
    """{(scene, leg, label, roi): row} where label is 'spp64' / '10s' ...; rows reached by several labels repeat."""
    idx = {}
    for r in res["rows"]:
        for lab in r["labels"]:
            idx[(r["scene"], r["leg"], lab, r["roi"])] = r
    return idx


def nb_headline(res: dict, label: str, roi: str = "image") -> list[dict]:
    """Per scene: each leg's relMSE / seconds / efficiency at ``label`` and the two Astroray/Cycles efficiency
    ratios (< 1: Astroray less efficient)."""
    idx = nb_index(res)
    out = []
    for sid in sorted({r["scene"] for r in res["rows"]}):
        row = {"scene": sid}
        for leg in NB_ORDER:
            r = idx.get((sid, leg, label, roi))
            if r:
                row[leg] = {"spp": r["spp"], "t": r["t_frame_s"], "relmse": r["relmse"], "relvar": r["relvar_lum"],
                            "bias2": r["bias2"], "eff": r["eff"], "chroma": r["chroma"], "tail": r["tail_share"]}
        for name, a, c in (("gpu_vs_optix", "gpu", "cycles_gpu"), ("cpu_vs_cycles", "cpu", "cycles")):
            if a in row and c in row:
                row[name] = row[a]["eff"] / row[c]["eff"]
        out.append(row)
    return out


def _nb_save(fig, path: Path, meta: dict, series: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=NB_SURFACE)
    path.with_suffix(".json").write_text(json.dumps({"meta": meta, "series": series}, indent=1, default=str) + "\n",
                                         encoding="utf-8", newline="\n")
    return path


def _nb_axes(fig_w=11.0, fig_h=4.6, **kw):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=110, facecolor=NB_SURFACE, **kw)
    for a in (ax.flat if hasattr(ax, "flat") else [ax]):
        a.set_facecolor(NB_SURFACE)
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
    return fig, ax


def nb_efficiency_chart(res: dict, out: Path) -> Path:
    """Efficiency of Astroray GPU relative to Cycles OptiX (and CPU vs CPU) per scene at each budget (log y)."""
    import numpy as np
    labels = [f"{b:g}s" for b in res["meta"]["budgets_s"]]
    fig, axes = _nb_axes(13.0, 4.6, ncols=2, sharey=True)
    series = {}
    for ax, (key, title) in zip(axes, (("gpu_vs_optix", "Astroray GPU vs Cycles OptiX"),
                                       ("cpu_vs_cycles", "Astroray CPU vs Cycles CPU"))):
        scenes = None
        for i, lab in enumerate(labels):
            hl = nb_headline(res, lab)
            scenes = [h["scene"].replace("v2_", "") for h in hl]
            vals = [h.get(key, float("nan")) for h in hl]
            x = np.arange(len(hl)) + (i - (len(labels) - 1) / 2) * 0.26
            ax.bar(x, vals, width=0.26, color=("#9a9893", "#2a78d6", "#eb6834")[i % 3],
                   label=f"{lab} per 1280x720 frame")
            series[f"{key}@{lab}"] = dict(zip(scenes, vals))
        ax.set_yscale("log")
        ax.axhline(1.0, color="#52514e", ls="--", lw=1.0, label="parity (efficiency ratio 1)")
        ax.set_xticks(range(len(scenes)))
        ax.set_xticklabels(scenes, rotation=30, ha="right", fontsize=8)
        ax.set_title(title + ": efficiency 1 / (relMSE x time), whole image", fontsize=10)
        ax.grid(axis="y", color="#e4e4e1", lw=0.6)
    axes[0].set_ylabel("efficiency ratio (< 1: Astroray less efficient)")
    axes[0].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    return _nb_save(fig, out / "efficiency_ratio_chart.png", res["meta"], series)


def nb_curves_chart(res: dict, out: Path) -> Path:
    """Whole-image relMSE against seconds per 1280x720 frame, one panel per scene, all legs (log-log)."""
    scenes = sorted({r["scene"] for r in res["rows"]})
    cols = 4
    nrows = math.ceil(len(scenes) / cols)
    fig, axes = _nb_axes(15.0, 3.2 * nrows, nrows=nrows, ncols=cols, squeeze=False)
    series = {}
    for ax, sid in zip(axes.flat, scenes):
        for leg in NB_ORDER:
            pts = sorted((r["t_frame_s"], r["relmse"]) for r in res["rows"]
                         if r["scene"] == sid and r["leg"] == leg and r["roi"] == "image")
            if pts:
                ax.plot(*zip(*pts), "-o", ms=3, lw=1.4, color=NB_COLOR[leg], label=NB_NAME[leg])
                series[f"{sid}/{leg}"] = pts
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(sid.replace("v2_", ""), fontsize=9)
        ax.grid(color="#e4e4e1", lw=0.5)
        ax.set_xlabel("seconds per 1280x720 frame", fontsize=8)
        ax.set_ylabel("relMSE (whole image)", fontsize=8)
    axes.flat[0].legend(frameon=False, fontsize=7)
    for ax in list(axes.flat)[len(scenes):]:
        ax.axis("off")
    fig.tight_layout()
    return _nb_save(fig, out / "relmse_vs_time_chart.png", res["meta"], series)


def nb_anatomy_chart(res: dict, out: Path, label: str = "spp64") -> Path:
    """Where the noise sits at equal spp: bias^2 share of relMSE, top-0.1 % tail share, chroma relVar."""
    import numpy as np
    hl = nb_headline(res, label)
    scenes = [h["scene"].replace("v2_", "") for h in hl]
    legs = [lg for lg in ("cycles_gpu", "gpu", "cycles", "cpu") if any(lg in h for h in hl)]
    fig, axes = _nb_axes(19.0, 4.4, ncols=4)
    series = {}
    slope = lambda h, leg: res.get("slopes", {}).get(h["scene"], {}).get(leg, {}).get("image", float("nan"))
    panels = (("bias2 share of relMSE", lambda d: d["bias2"] / d["relmse"], False),
              ("top 0.1 % pixels' share of variance", lambda d: d["tail"], False),
              ("chroma relVar (sum of channel variances of rgb/L)", lambda d: d["chroma"], True))
    panels += (("N x relVar slope (0 = plain MC, < 0 = stratified)", None, False),)
    for ax, (title, fn, log) in zip(axes, panels):
        for i, leg in enumerate(legs):
            vals = [slope(h, leg) if fn is None else (fn(h[leg]) if leg in h else float("nan")) for h in hl]
            ax.bar(np.arange(len(hl)) + (i - (len(legs) - 1) / 2) * 0.8 / len(legs), vals, width=0.8 / len(legs),
                   color=NB_COLOR[leg], label=NB_NAME[leg])
            series[f"{title}/{leg}"] = dict(zip(scenes, vals))
        if log:
            ax.set_yscale("log")
        ax.set_xticks(range(len(scenes)))
        ax.set_xticklabels(scenes, rotation=35, ha="right", fontsize=8)
        ax.set_title(title if fn is None else f"{title} at 64 spp", fontsize=9)
        ax.grid(axis="y", color="#e4e4e1", lw=0.6)
    axes[0].legend(frameon=False, fontsize=7)
    fig.tight_layout()
    return _nb_save(fig, out / "noise_anatomy_chart.png", res["meta"], series)


def nb_equal_time_sheets(res: dict, work: Path, out: Path, labels=None, seed: int = 278) -> list[Path]:
    """One sheet per scene: rows = equal-time budgets, columns = legs, every tile at the spp its leg affords
    in that budget per 1280x720 frame (seed ``seed``), ROIs drawn."""
    import numpy as np
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from results_layout import save_comparison_sheet
    labels = labels or [f"{b:g}s" for b in res["meta"]["budgets_s"]]
    idx = nb_index(res)
    paths = []
    for sid in sorted({r["scene"] for r in res["rows"]}):
        crops = res["meta"].get("crops", {}).get(sid, {})  # the run's own ROIs (suite- and variant-aware)
        rows = []
        for lab in labels:
            row = []
            for leg in NB_ORDER:
                r = idx.get((sid, leg, lab, "image"))
                if r is None and not any(x["scene"] == sid and x["leg"] == leg for x in res["rows"]):
                    continue
                if r is None:
                    row.append((f"{NB_NAME[leg]}: below 1 spp in {lab}", np.full((180, 320, 3), 0.15)))
                    continue
                f = Path(work) / "renders" / f"{sid.replace('@', '_')}_{leg}_spp{r['spp']}_s{seed}.npy"
                row.append((f"{NB_NAME[leg]} | {lab} | {r['spp']} spp", np.load(f)))
            rows.append(row)
        h, w = rows[0][0][1].shape[:2]
        rois = {n: (x0 * w, y0 * h, x1 * w, y1 * h) for n, (x0, y0, x1, y1) in crops.items()}
        name = f"equal_time_{sid.replace('v2_', '').replace('@', '_')}_sheet.png"
        paths.append(save_comparison_sheet(out / name, rows,
                                           f"{sid}: equal time per 1280x720 frame (rows: budget), seed {seed}", rois))
    return paths


def nb_write_csv(res: dict, out: Path) -> Path:
    cols = ("scene", "leg", "spp", "t_frame_s", "roi", "relvar_lum", "chroma", "bias2", "relmse", "tail_share", "eff")
    lines = [",".join(cols + ("labels",))]
    for r in res["rows"]:
        lines.append(",".join([f"{r[c]:.6g}" if isinstance(r[c], float) else str(r[c]) for c in cols]
                              + ["|".join(r["labels"])]))
    p = out / "efficiency_table.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return p


def nb_markdown(res: dict) -> str:
    """Headline equal-time table (whole image) as markdown, for the findings doc."""
    out = []
    for lab in [f"{b:g}s" for b in res["meta"]["budgets_s"]]:
        out += [f"### Equal time: {lab} per 1280x720 frame (whole image)", "",
                ("| scene | Cycles OptiX spp / relMSE | Astroray GPU spp / relMSE | **GPU eff. ratio** | "
                 "Cycles CPU spp / relMSE | Astroray CPU spp / relMSE | CPU eff. ratio |"), "|---|---|---|---|---|---|---|"]
        for h in nb_headline(res, lab):
            def cell(leg, h=h):
                d = h.get(leg)
                return f"{d['spp']} / {d['relmse']:.2e}" if d else "n/a"
            gr, cr = h.get("gpu_vs_optix"), h.get("cpu_vs_cycles")
            out.append(f"| {h['scene'].replace('v2_', '')} | {cell('cycles_gpu')} | {cell('gpu')} | "
                       f"**{f'{gr:.3f}' if gr else 'n/a'}** | {cell('cycles')} | {cell('cpu')} | "
                       f"{f'{cr:.3f}' if cr else 'n/a'} |")
        out.append("")
    return "\n".join(out)


def build_noise_bench_report(work: Path, out: Path, sheets: bool = True, tag: str = "") -> dict:
    res = _nb_load(work, tag)
    written = {"csv": nb_write_csv(res, out), "efficiency": nb_efficiency_chart(res, out),
               "curves": nb_curves_chart(res, out), "anatomy": nb_anatomy_chart(res, out)}
    if sheets:
        written["sheets"] = nb_equal_time_sheets(res, work, out)
    (out / "headline.md").write_text(nb_markdown(res), encoding="utf-8", newline="\n")
    return written


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["production"]:
        pp = argparse.ArgumentParser(prog="report_tools.py production")
        pp.add_argument("--work-dir", required=True)
        pp.add_argument("--out-dir", required=True)
        pa = pp.parse_args(argv[1:])
        s = build_production_report(Path(pa.work_dir), Path(pa.out_dir))
        print(f"[pkg310] CPU {s['cpu']['pass']}/{s['cpu']['of']}  GPU {s['gpu']['pass']}/{s['gpu']['of']}")
        return
    if argv[:1] == ["noise-bench"]:
        pp = argparse.ArgumentParser(prog="report_tools.py noise-bench")
        pp.add_argument("--work-dir", required=True)
        pp.add_argument("--out-dir", required=True)
        pp.add_argument("--no-sheets", action="store_true")
        pp.add_argument("--tag", default="", help="the --nb-tag of the run to report")
        pa = pp.parse_args(argv[1:])
        w = build_noise_bench_report(Path(pa.work_dir), Path(pa.out_dir), sheets=not pa.no_sheets, tag=pa.tag)
        print("[pkg307] wrote " + ", ".join(f"{k}={v}" if not isinstance(v, list) else f"{k}x{len(v)}" for k, v in w.items()))
        return
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--family", required=True)
    p.add_argument("--cycles-npy", default=None)
    p.add_argument("--astroray-npy", default=None)
    p.add_argument("--manifest", default=str(REPO_ROOT / "benchmarks" / "reference_corpus" / "scenes" / "manifest.json"))
    p.add_argument("--out-dir", default=str(REPO_ROOT / "benchmarks" / "reference_corpus" / "refs"))
    args = p.parse_args(argv)

    engine_npys = {"cycles_cpu": args.cycles_npy, "astroray_cpu": args.astroray_npy}
    written = build_family_report(args.family, Path(args.manifest), Path(args.out_dir), engine_npys)

    n_crops = len({name for name, _ in written["crops"]})
    print(f"[pkg259] {args.family}: {len(written['engine_pngs'])} engine PNG(s), "
          f"{n_crops} crop name(s), sheets={list(written['sheets'])}")


if __name__ == "__main__":
    main()

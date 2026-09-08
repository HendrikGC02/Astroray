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


def main(argv=None):
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

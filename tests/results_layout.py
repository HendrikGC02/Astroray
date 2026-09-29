"""test_results layout helpers (conventions: .astroray_plan/docs/test-results-conventions.md).

Astroray-free on purpose: tests, scripts and benchmarks all import this.
matplotlib is imported lazily. Code obtains output paths ONLY via
`results_path(area, feature, name)`, which always resolves under
`test_results/_runs/` (ignored). Curated evidence in `test_results/<area>/...`
is promoted by hand.

CLI:
    python tests/results_layout.py index [--runs]   # regenerate index.html
    python tests/results_layout.py clean            # empty _runs/
    python tests/results_layout.py clean --legacy   # move pre-convention entries to _legacy/
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "test_results"

AREAS = (
    "materials", "textures-nodes", "lights", "world", "volumes", "caustics",
    "spectral", "camera", "geometry", "passes", "integrator", "viewport",
    "perf", "parity", "addon", "astro",
)

FEATURE_RE = re.compile(r"^[a-z0-9-]{3,40}$")
NAME_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9]+$")
_BANNED_TOKEN_RE = re.compile(
    r"^(batch\w*|lanes?\d*|lead|hotfix\w*|storm\d*|rounds?\d*|sessions?\d*"
    r"|pkg\d+\w*|issue\d+\w*|\d{8}|20\d\d|opus|sonnet|haiku|claude|codex|astra"
    r"|terra|luna|deepseek)$")

# Curated-tree rules (guard + index).
CURATED_EXTS = {".png", ".svg", ".json", ".csv", ".blend"}
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_WIDTH = 1600
MAX_BLEND_BYTES = 1024 * 1024
SCRATCH = {"tmp", ".pytest_cache", "_runs", "_legacy"}

ROLE_COLORS = {"cycles": "#52514e", "cpu": "#2a78d6", "gpu": "#eb6834",
               "other": "#1baf7a"}
_EXTRA_COLORS = ("#8a5cf6", "#d4a017", "#0e8fa3")  # fixed order, never cycled
SURFACE = "#fcfcfb"


def banned_token(text: str) -> str | None:
    """Return the first banned token in a path component, else None."""
    for tok in re.split(r"[-_.]", text.lower()):
        if _BANNED_TOKEN_RE.match(tok):
            return tok
    return None


def _check(area: str, feature: str, name: str | None = None) -> None:
    if area not in AREAS:
        raise ValueError(f"unknown area {area!r}; expected one of {AREAS}")
    if not FEATURE_RE.match(feature):
        raise ValueError(f"feature {feature!r} must match {FEATURE_RE.pattern}")
    for label, val in (("feature", feature), ("name", name)):
        if val is None:
            continue
        bad = banned_token(val)
        if bad:
            raise ValueError(f"{label} {val!r} contains banned token {bad!r} "
                             "(batch/lane/lead/hotfix/storm/round/session/date/pkgNNN/issueNNN)")
    if name is not None and not NAME_RE.match(name):
        raise ValueError(f"name {name!r} must match {NAME_RE.pattern}")


def slug(text) -> str:
    """Lowercase `text` with runs of non-alphanumerics folded to `_`, for
    building artifact names from dynamic parts (e.g. a preset or roughness)."""
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def results_dir(area: str, feature: str, create: bool = True) -> Path:
    """`test_results/_runs/<area>/<feature>` (created unless `create=False`,
    e.g. for argparse defaults)."""
    _check(area, feature)
    d = RESULTS / "_runs" / area / feature
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def results_path(area: str, feature: str, name: str) -> Path:
    """`test_results/_runs/<area>/<feature>/<name>`; parents created."""
    _check(area, feature, name)
    return results_dir(area, feature) / name


def _contact_sheets():
    p = ROOT / "benchmarks" / "showcase" / "contact_sheets.py"
    spec = importlib.util.spec_from_file_location("_astroray_contact_sheets", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def save_comparison_sheet(path, tiles, title, rois=None) -> Path:
    """Labelled sheet: `tiles` = [(label, HxWx3 float), ...] in column order
    Cycles | CPU | GPU (or before | after). A list of such lists gives rows.
    `rois` = {name: (x0, y0, x1, y1)} pixel rectangles drawn on every tile."""
    rows = tiles if tiles and isinstance(tiles[0], list) else [tiles]
    columns = max(len(r) for r in rows)
    flat = []
    for r in rows:
        flat.extend(r + [("", None)] * (columns - len(r)))
    aspect = max((px.shape[0] / px.shape[1] for _, px in flat if px is not None),
                 default=1.0)
    width_in = 15.0 / columns  # 15 in x 100 dpi = 1500 px, under the 1600 px cap
    return _contact_sheets().save_contact_sheet(
        flat, Path(path), columns=columns, title=title, rois=rois,
        tile_size=(width_in, width_in * aspect + 0.4), dpi=100)


def _series_color(s: dict, other_idx: list) -> str:
    role = s.get("role")
    if role is None:
        low = str(s.get("label", "")).lower()
        role = next((r for r in ("cycles", "cpu", "gpu") if r in low), "other")
    if role != "other":
        return ROLE_COLORS[role]
    i = other_idx[0]
    other_idx[0] += 1
    cols = (ROLE_COLORS["other"],) + _EXTRA_COLORS
    if i >= len(cols):
        raise ValueError("more than 4 'other' series; split the chart")
    return cols[i]


def save_stat_chart(path, series, *, title, xlabel, ylabel, kind="bar",
                    band=None, ref=None, meta=None) -> Path:
    """PNG chart + same-stem `.json` sidecar.

    series: [{"label": str, "x": [...], "y": [...], "role": optional
    "cycles"|"cpu"|"gpu"|"other"}]. band=(lo, hi) shades the tolerance range;
    ref=value or (value, label) draws a reference line; meta = provenance."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=110, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    other = [0]
    n = len(series)
    for i, s in enumerate(series):
        col = _series_color(s, other)
        x, y = list(s["x"]), list(s["y"])
        if kind == "bar":
            pos = list(range(len(x)))
            w = 0.8 / n
            ax.bar([p - 0.4 + w * (i + 0.5) for p in pos], y, width=w,
                   color=col, label=s.get("label"))
            ax.set_xticks(pos)
            ax.set_xticklabels([str(v) for v in x], rotation=30 if len(x) > 5 else 0,
                               ha="right" if len(x) > 5 else "center", fontsize=8)
        else:
            ax.plot(x, y, color=col, marker="o", ms=3.5, lw=1.6,
                    label=s.get("label"))
    if band is not None:
        ax.axhspan(band[0], band[1], color="#d9d9d6", alpha=0.6, zorder=0,
                   label="tolerance")
    if ref is not None:
        val, lab = (ref if isinstance(ref, (tuple, list)) else (ref, "reference"))
        ax.axhline(val, color="#52514e", ls="--", lw=1.0, label=lab)
    ax.set_title(title, fontsize=11)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", color="#e4e4e1", lw=0.6)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if n >= 2 or band is not None or ref is not None:
        ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)
    path.with_suffix(".json").write_text(json.dumps({
        "title": title, "xlabel": xlabel, "ylabel": ylabel, "kind": kind,
        "series": [{k: v for k, v in s.items()} for s in series],
        "band": band, "ref": ref, "meta": meta or {},
    }, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    return path


# --- index ---------------------------------------------------------------

_CSS = """:root{--bg:#fcfcfb;--fg:#1c1c1a;--mut:#6b6a66;--card:#fff;--bd:#e4e4e1;--ac:#2a78d6}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe8;--mut:#a3a29d;--card:#1f1f1e;--bd:#33332f;--ac:#6aa8f0}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
h1{font-size:20px}h2{font-size:16px;margin:24px 0 8px;border-bottom:1px solid var(--bd)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:6px;padding:10px}
.card h3{margin:0 0 4px;font-size:14px}.card p{margin:4px 0;color:var(--mut);font-size:12px}
.card img{width:100%;height:auto;border:1px solid var(--bd);margin-top:6px}
a{color:var(--ac)}"""


def _readme_lines(readme: Path) -> str:
    if not readme.is_file():
        return ""
    lines = [l.strip() for l in readme.read_text(encoding="utf-8").splitlines()]
    lines = [l for l in lines if l and not l.startswith("#")]
    return " ".join(lines[:3])


def render_index(root: Path) -> str:
    """Deterministic index HTML for the tree at `root` (relative links)."""
    out = ["<!doctype html>", '<html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1">',
           f"<title>Astroray test results</title><style>{_CSS}</style></head><body>",
           "<h1>Astroray test results</h1>"]
    for area in AREAS:
        adir = root / area
        feats = sorted(p for p in adir.iterdir() if p.is_dir()) if adir.is_dir() else []
        if not feats:
            continue
        out.append(f"<h2>{html.escape(area)}</h2><div class=\"grid\">")
        for f in feats:
            out.append(f'<div class="card"><h3>{html.escape(f.name)}</h3>')
            blurb = _readme_lines(f / "README.md")
            if blurb:
                out.append(f"<p>{html.escape(blurb)}</p>")
            files = sorted(p for p in f.iterdir() if p.is_file())
            links = [p for p in files if p.suffix.lower() in (".json", ".csv", ".blend")]
            if links:
                out.append("<p>" + " &middot; ".join(
                    f'<a href="{area}/{f.name}/{p.name}">{html.escape(p.name)}</a>'
                    for p in links) + "</p>")
            for p in files:
                if p.suffix.lower() in (".png", ".svg"):
                    out.append(f'<a href="{area}/{f.name}/{p.name}"><img loading="lazy" '
                               f'src="{area}/{f.name}/{p.name}" alt="{html.escape(p.name)}"></a>')
            out.append("</div>")
        out.append("</div>")
    out.append("</body></html>")
    return "\n".join(out) + "\n"


def write_index(runs: bool = False) -> Path:
    root = RESULTS / "_runs" if runs else RESULTS
    if not root.is_dir():
        raise SystemExit(f"{root} does not exist")
    dst = root / "index.html"
    dst.write_text(render_index(root), encoding="utf-8", newline="\n")
    return dst


def clean(legacy: bool = False) -> list:
    moved = []
    if not legacy:
        runs = RESULTS / "_runs"
        if runs.is_dir():
            for c in runs.iterdir():
                shutil.rmtree(c) if c.is_dir() else c.unlink()
                moved.append(c.name)
        return moved
    keep = set(AREAS) | SCRATCH | {"index.html", "README.md"}
    dst = RESULTS / "_legacy"
    for c in sorted(RESULTS.iterdir()) if RESULTS.is_dir() else []:
        if c.name in keep:
            continue
        dst.mkdir(exist_ok=True)
        target = dst / c.name
        if target.exists():  # never overwrite/delete: disambiguate
            i = 1
            while (dst / f"{c.name}.{i}").exists():
                i += 1
            target = dst / f"{c.name}.{i}"
        shutil.move(str(c), str(target))
        moved.append(c.name)
    return moved


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("index")
    pi.add_argument("--runs", action="store_true")
    pc = sub.add_parser("clean")
    pc.add_argument("--legacy", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "index":
        print(write_index(a.runs))
    else:
        moved = clean(a.legacy)
        print(f"{'moved to _legacy' if a.legacy else 'removed from _runs'}: {len(moved)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())

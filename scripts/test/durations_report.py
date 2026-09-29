#!/usr/bin/env python
"""Test-suite durations report from pytest --junitxml (bar charts + JSON + text table).

  python scripts/test/durations_report.py --junit before.xml [--junit after.xml] [--out DIR]
With two --junit files the charts group before (first) vs after (second).
"""
import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Ordered: first keyword hit on the file name wins.
AREA_KEYWORDS = {
    "addon": ["blender", "addon", "headless", "panel", "install", "binding", "standalone", "settings", "nav_resolution", "exporter", "importer", "blend_import", "fits", "grid_import"],
    "viewport": ["viewport", "worker", "dirty_domain", "orbit", "present", "cancellation", "ui_latency", "scene_switch", "buffer_identity", "progressive"],
    "volumes": ["volume", "smoke", "fire", "medium", "media", "heterogeneous", "scattering", "subsurface"],
    "caustics": ["caustic", "photon", "sms", "raindrop"],
    "spectral": ["spectral", "dispersion", "sellmeier", "prism", "upsampl"],
    "lights": ["light", "lamp", "ies", "sun", "emiss"],
    "world": ["sky", "world", "hdri", "env"],
    "parity": ["parity", "corpus", "cycles"],
    "astro": ["kerr", "gr_", "astro", "nebula", "blackbody", "redshift", "blackhole", "schwarzschild", "adaf", "slim_disk", "synchrotron", "momentum", "observer", "physics_emitters"],
    "perf": ["perf", "timing", "bench"],
    "passes": ["aov", "pass", "crypto", "denois"],
    "camera": ["camera", "dof", "ortho", "lens", "motion_blur", "screen_to_pixel", "render_region"],
    "geometry": ["mesh", "curve", "instanc", "holdout", "geometry", "heightfield", "displacement", "tlas", "shape", "thin_wall", "hair", "normal_map", "normal_buffer", "texspace", "object_space", "sphere_chain"],
    "textures-nodes": ["texture", "node", "opvm", "op_vm", "shader_graph", "mapping", "coordinate", "procedural", "voronoi", "generated", "grid_cache"],
    "materials": ["material", "bsdf", "glass", "metal", "dielectric", "principled",
                  "thinfilm", "thin_film", "alpha", "furnace", "poly", "disney", "lobe", "energy", "aniso", "diffuse", "lambertian", "specular", "spectrum", "registry"],
    "integrator": ["converg", "adaptive", "guiding", "nee", "mis", "integrator", "sampler", "oracle", "reference_pt", "restir", "dtree", "rng", "sobol", "wavefront", "bounces", "hero", "solid_angle", "practrand", "neural", "gpu_", "cuda", "tolerance", "statistical", "gate", "reservoir", "bit_identity", "regression"],
    # chart-only bucket: not part of the test-results area taxonomy.
    "tooling": ["orchestrator", "hooks", "index", "delegate", "scripts", "build_integrity", "html", "durations", "roadmap", "claude", "linear_render_guard", "prewarm", "process_tree", "worktree", "issue_triage", "hygiene"],
}
BG, C_SINGLE, C_BEFORE, C_AFTER = "#fcfcfb", "#2a78d6", "#52514e", "#2a78d6"


def area_of(fname):
    stem = Path(fname).stem.lower()
    for area, kws in AREA_KEYWORDS.items():
        if any(k in stem for k in kws):
            return area
    return "other"


def file_of(classname):
    parts = classname.split(".")
    for i, part in enumerate(parts):
        if part.startswith("test_"):
            d = parts[:i] if parts[:1] == ["tests"] else ["tests"] + parts[:i]
            return "/".join(d + [part]) + ".py"
    return classname.replace(".", "/") or "unknown"


def load(path):
    """Return (tests, counts): tests = [(file, name, seconds)]."""
    tests, counts = [], defaultdict(int)
    for tc in ET.parse(path).getroot().iter("testcase"):
        tests.append((file_of(tc.get("classname") or tc.get("name", "")), tc.get("name", ""), float(tc.get("time", 0))))
        if tc.find("skipped") is not None:
            counts["skipped"] += 1
        elif tc.find("failure") is not None or tc.find("error") is not None:
            counts["failed"] += 1
        else:
            counts["passed"] += 1
    return tests, dict(counts)


def aggregate(tests):
    by_file, by_area, n_area = defaultdict(float), defaultdict(float), defaultdict(int)
    for f, _, t in tests:
        by_file[f] += t
        by_area[area_of(f)] += t
        n_area[area_of(f)] += 1
    top = {f"{f}::{n}": t for f, n, t in sorted(tests, key=lambda x: -x[2])}
    return {"area": dict(by_area), "file": dict(by_file), "test": top, "n_area": dict(n_area)}


def git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def chart(name, rows, series, out, meta, title, limit=None):
    """rows: [(label, {series: seconds})] sorted by first series; series: [(label, colour)]."""
    rows = rows[:limit] if limit else rows
    shown = rows[::-1]  # largest at top
    h = max(3, 0.28 * len(shown) * len(series) + 1.4)
    fig, ax = plt.subplots(figsize=(16, h), dpi=100, facecolor=BG)
    ax.set_facecolor(BG)
    bh = 0.8 / len(series)
    for si, (s, colour) in enumerate(series):
        ys = [i + (si - (len(series) - 1) / 2) * bh for i in range(len(shown))]
        vals = [r[1].get(s, 0.0) for r in shown]
        ax.barh(ys, vals, height=bh * 0.9, color=colour, label=s if len(series) > 1 else None)
        for y, v in zip(ys, vals):
            ax.text(v, y, f" {v:.1f}", va="center", fontsize=8)
    ax.set_yticks(range(len(shown)))
    ax.set_yticklabels([r[0] for r in shown], fontsize=8)
    ax.set_xlabel("seconds (s)")
    ax.set_title(title, fontsize=11, loc="left")
    ax.spines[["top", "right"]].set_visible(False)
    if len(series) > 1:
        ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out / f"{name}.png", facecolor=BG)
    plt.close(fig)
    (out / f"{name}.json").write_text(json.dumps(
        {**meta, "rows": [{"label": r[0], **r[1]} for r in rows]}, indent=2), encoding="utf-8")


def text_table(title, rows, total, n):
    print(f"\n{title}")
    for label, secs in rows[:n]:
        print(f"  {secs:8.1f}s {100 * secs / total if total else 0:5.1f}%  {label}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--junit", action="append", required=True, help="junit xml (1 or 2 times)")
    ap.add_argument("--label", action="append", help="series labels (default before/after)")
    ap.add_argument("--merge", action="store_true", help="merge all --junit files into one series")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if len(a.junit) > 2 and not a.merge:
        ap.error("at most two --junit files")
    labels = (a.label or []) + ["before", "after"][len(a.label or []):]
    # TODO: switch to results_path("perf", "test-suite-durations", ...) once tests/results_layout.py lands.
    out = Path(a.out or "test_results/_runs/perf/test-suite-durations")
    out.mkdir(parents=True, exist_ok=True)

    loaded = [load(p) for p in a.junit]
    if a.merge:
        merged = defaultdict(int)
        for _, c in loaded:
            for k, v in c.items():
                merged[k] += v
        loaded = [(sum((t for t, _ in loaded), []), dict(merged))]
    aggs = [aggregate(t) for t, _ in loaded]
    totals = [sum(x[2] for x in t) for t, _ in loaded]
    if len(loaded) == 1:
        series = [(labels[0], C_SINGLE)]
    else:
        series = [(labels[0], C_BEFORE), (labels[1], C_AFTER)]
    names = [s for s, _ in series]
    tot_txt = " | ".join(f"{n}: {t:.0f}s" for n, t in zip(names, totals))
    meta = {"junit": a.junit, "git_sha": git_sha(),
            "total_seconds": dict(zip(names, totals)),
            "test_count": {n: len(t) for n, (t, _) in zip(names, loaded)},
            "outcomes": {n: c for n, (_, c) in zip(names, loaded)}}

    def rows_for(kind):
        keys = set().union(*[x[kind].keys() for x in aggs])
        rows = [(k, {n: x[kind].get(k, 0.0) for n, x in zip(names, aggs)}) for k in keys]
        return sorted(rows, key=lambda r: -r[1][names[0]])

    n0 = aggs[0]["n_area"]
    area_rows = [(f"{k} ({n0.get(k, 0)} tests)", v) for k, v in rows_for("area")]
    chart("durations_by_area_chart", area_rows, series, out, meta, f"Test time by area - {tot_txt}")
    chart("durations_by_file_chart", rows_for("file"), series, out, meta,
          f"Top 30 test files - {tot_txt}", 30)
    test_rows = [(k if len(k) <= 70 else "..." + k[-67:], v) for k, v in rows_for("test")]
    chart("durations_top_tests_chart", test_rows, series, out, meta,
          f"Top 30 tests - {tot_txt}", 30)

    t0 = totals[0]
    text_table("Top 15 files", sorted(aggs[0]["file"].items(), key=lambda x: -x[1]), t0, 15)
    text_table("Top 30 tests", list(aggs[0]["test"].items()), t0, 30)
    other = sorted(f for f in aggs[0]["file"] if area_of(f) == "other")
    print(f"\nFiles in 'other' ({len(other)}): {', '.join(other) or '-'}")
    print(f"Wrote charts + JSON to {out}")


if __name__ == "__main__":
    sys.exit(main())

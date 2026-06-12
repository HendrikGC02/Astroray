"""Build the 2026-06 self-contained HTML feature showcase report.

Reads this session's measured data:
  - test_results/showcase_2026-06/render_timings.json   (Part D timing log)
  - benchmarks/viewport_parity/results_2026-06-12/*.json (in-Blender legs)
plus clearly-labeled historical series (pkg55 optimization arc, PR #463
viewport gate), renders matplotlib graphs to in-memory PNGs, base64-embeds
every image, and writes docs/reports/2026-06-feature-showcase.html.

Usage: python scripts/diagnostics/build_feature_report_2026_06.py
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
SHOW = REPO / "test_results" / "showcase_2026-06"
VP = REPO / "benchmarks" / "viewport_parity" / "results_2026-06-12"
OUT = REPO / "docs" / "reports" / "2026-06-feature-showcase.html"

DARK = "#0d1117"
PANEL = "#161b22"
FG = "#e6edf3"
ACCENT = "#4fc3f7"
ACCENT2 = "#f78c6c"
ACCENT3 = "#c3e88d"


# --------------------------------------------------------------------------- #
# encoding helpers
# --------------------------------------------------------------------------- #
def b64_image(path: Path, max_w: int = 1400, quality: int = 88) -> str:
    """JPEG-encode a render (PNG for images with hard edges stays larger but
    crisper — charts use b64_fig instead)."""
    img = Image.open(path).convert("RGB")
    if img.size[0] > max_w:
        h = int(img.size[1] * max_w / img.size[0])
        img = img.resize((max_w, h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def b64_fig(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), dpi=110,
                bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def style_ax(ax):
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_color("#30363d")
    ax.tick_params(colors=FG, labelsize=9)
    ax.xaxis.label.set_color(FG)
    ax.yaxis.label.set_color(FG)
    ax.title.set_color(FG)
    ax.grid(True, alpha=0.15, color="#8b949e")


def new_fig(w=10.5, h=4.2):
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor(PANEL)
    style_ax(ax)
    return fig, ax


# --------------------------------------------------------------------------- #
# graph a — per-scene render-time comparison from the session timing log
# --------------------------------------------------------------------------- #
def graph_render_times() -> str:
    records = json.loads((SHOW / "render_timings.json").read_text())
    # keep the highest-spp record per (scene, device) so the bars compare
    # like-for-like full-quality renders
    best: dict[tuple, dict] = {}
    for r in records:
        key = (r["scene"], r["device"], r["resolution"])
        if key not in best or r["spp"] > best[key]["spp"]:
            best[key] = r
    scenes = sorted({(r["scene"], r["resolution"], r["spp"]) for r in best.values()
                     if r["spp"] >= 512})
    device_order = ["cpu", "gpu-megakernel", "gpu-wavefront"]
    colors = {"cpu": "#8b949e", "gpu-megakernel": ACCENT2, "gpu-wavefront": ACCENT}
    fig, ax = new_fig(11, 4.6)
    width = 0.26
    xs = np.arange(len(scenes))
    for di, dev in enumerate(device_order):
        vals, labels = [], []
        for (scene, res, spp) in scenes:
            rec = best.get((scene, dev, res))
            vals.append(rec["wall_s"] if rec and rec["spp"] == spp else np.nan)
        bars = ax.bar(xs + (di - 1) * width, vals, width,
                      label=dev, color=colors[dev])
        for b, v in zip(bars, vals):
            if np.isfinite(v):
                ax.text(b.get_x() + b.get_width() / 2, v * 1.05, f"{v:.1f}s",
                        ha="center", va="bottom", color=FG, fontsize=8)
    ax.set_yscale("log")
    ax.set_xticks(xs)
    ax.set_xticklabels([f"{s}\n{res} @ {spp}spp" for s, res, spp in scenes],
                       fontsize=8, color=FG)
    ax.set_ylabel("wall-clock seconds (log)")
    ax.set_title("Render time by device/integrator — measured this session (RTX 5070 Ti)")
    leg = ax.legend(facecolor=PANEL, labelcolor=FG, edgecolor="#30363d")
    return b64_fig(fig)


# --------------------------------------------------------------------------- #
# graph b — the pkg55 wavefront optimization arc (historical, labeled)
# --------------------------------------------------------------------------- #
def graph_pkg55_arc(fresh_ratio: float = 1.50) -> str:
    # speed of wavefront relative to megakernel (>1 = faster), from the pkg55
    # spec + PR history (contact-sheet gate scene unless noted)
    arc = [
        ("N+6\n#443", 1 / 4.0, "first end-to-end image"),
        ("N+7p1\n#447", 1 / 1.55, "host-overhead kill"),
        ("N+7p2\n#448", 1 / 1.05, "queue compaction"),
        ("N+7p4\n#451", 1.37, "path regeneration"),
        ("RNG\n#456", 1.46, "template-RNG"),
        ("any-hit\n#457-9", 1.50, "any-hit + cool re-baseline"),
        ("today\n(fresh)", fresh_ratio, "this session, isolated run"),
    ]
    fig, ax = new_fig(10.5, 4.4)
    xs = np.arange(len(arc))
    ys = [a[1] for a in arc]
    cols = [ACCENT if y >= 1 else ACCENT2 for y in ys]
    bars = ax.bar(xs, ys, color=cols)
    ax.axhline(1.0, color=FG, lw=1, ls="--", alpha=0.6)
    ax.text(len(arc) - 0.6, 1.02, "megakernel parity", color=FG, fontsize=8)
    for b, (label, y, note) in zip(bars, arc):
        txt = f"{y:.2f}x" if y >= 1 else f"{1/y:.2f}x slower"
        ax.text(b.get_x() + b.get_width() / 2, y + 0.03, txt,
                ha="center", color=FG, fontsize=9, fontweight="bold")
        ax.text(b.get_x() + b.get_width() / 2, 0.06, note, rotation=90,
                ha="center", va="bottom", color="#bdc6cf", fontsize=8)
    ax.set_xticks(xs)
    ax.set_xticklabels([a[0] for a in arc], fontsize=9, color=FG)
    ax.set_ylabel("wavefront speed vs megakernel")
    ax.set_title("pkg55 GPU wavefront: 4.0x slower -> 1.50x faster in one day of increments "
                 "(historical PR series + today's re-measure)")
    return b64_fig(fig)


# --------------------------------------------------------------------------- #
# graph c — in-Blender viewport latency vs Cycles
# --------------------------------------------------------------------------- #
def _leg_stats(path: Path):
    j = json.loads(path.read_text())
    raw = j["raw_frame_ms"][1:]  # frame 0 = one-time setup, excluded
    arr = np.sort(np.asarray(raw))
    return {
        "p50": float(np.percentile(arr, 50)),
        "p99": float(np.percentile(arr, 99)),
        "mean": float(np.mean(arr)),
        "integrator": j["config"].get("integrator", "") or j["engine"],
    }


def graph_viewport() -> str:
    legs = [
        ("Cycles (OPTIX)", VP / "2026-06-12-cycles.json"),
        ("Astroray megakernel", VP / "2026-06-12-custom_raytracer-mk.json"),
        ("Astroray wavefront", VP / "2026-06-12-custom_raytracer.json"),
    ]
    stats = [(name, _leg_stats(p)) for name, p in legs if p.exists()]
    fig, ax = new_fig(9.5, 4.2)
    metrics = ["p50", "mean", "p99"]
    xs = np.arange(len(metrics))
    width = 0.25
    cols = ["#8b949e", ACCENT2, ACCENT]
    for i, (name, st) in enumerate(stats):
        vals = [st[m] for m in metrics]
        bars = ax.bar(xs + (i - 1) * width, vals, width, label=name, color=cols[i])
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 2, f"{v:.0f}",
                    ha="center", color=FG, fontsize=8)
    ax.set_xticks(xs)
    ax.set_xticklabels(["p50", "mean", "p99"], color=FG)
    ax.set_ylabel("steady-state frame time (ms)")
    ax.set_title("In-Blender viewport A/B - 99,458-tri scene, 256x256, 1 spp/frame, "
                 "30 frames, measured this session (frame 0 excluded)")
    ax.legend(facecolor=PANEL, labelcolor=FG, edgecolor="#30363d")
    return b64_fig(fig)


# --------------------------------------------------------------------------- #
# graph d — test suite state
# --------------------------------------------------------------------------- #
def graph_suite() -> str:
    history = [  # closeout series from STATUS.md (historical) + today
        ("06-11\nmorning", 1214), ("06-11\nafternoon", 1271),
        ("06-11\nevening", 1272), ("06-12\novernight", 1277),
        ("06-12\nmorning", 1289), ("06-12\ntoday", 1299),
    ]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10.5, 3.8),
                                  gridspec_kw={"width_ratios": [3, 2]})
    fig.patch.set_facecolor(PANEL)
    for a in (ax, ax2):
        a.set_facecolor(PANEL)
        for s in a.spines.values():
            s.set_color("#30363d")
        a.tick_params(colors=FG, labelsize=9)
        a.grid(True, alpha=0.15, color="#8b949e")
    ax.plot([h[0] for h in history], [h[1] for h in history], "o-", color=ACCENT3)
    ax.set_title("passing tests across round closeouts", color=FG)
    ax.set_ylabel("tests passed", color=FG)
    counts = {"passed": 1299, "skipped": 14, "xfailed": 21, "xpassed": 3, "failed": 0}
    cols = [ACCENT3, "#8b949e", ACCENT2, ACCENT, "#f97583"]
    ax2.bar(list(counts), list(counts.values()), color=cols)
    for i, (k, v) in enumerate(counts.items()):
        ax2.text(i, v + 12, str(v), ha="center", color=FG, fontsize=9, fontweight="bold")
    ax2.set_yscale("symlog")
    ax2.set_title("full suite today (7m37s, RTX 5070 Ti)", color=FG)
    return b64_fig(fig)


# --------------------------------------------------------------------------- #
# html assembly
# --------------------------------------------------------------------------- #
def img_card(path: Path, title: str, caption: str, max_w: int = 1400) -> str:
    return f"""
    <figure class="card">
      <img src="{b64_image(path, max_w=max_w)}" alt="{title}"/>
      <figcaption><b>{title}</b> — {caption}</figcaption>
    </figure>"""


def main() -> None:
    fresh = 1.50  # measured today: MK 0.494s / WF 0.329s isolated cool run
    graphs = {
        "times": graph_render_times(),
        "arc": graph_pkg55_arc(fresh),
        "viewport": graph_viewport(),
        "suite": graph_suite(),
    }

    R = REPO / "docs" / "renders"
    sections: list[str] = []

    sections.append(f"""
    <h2>New this run — GPU wavefront path tracing</h2>
    <p>The renderer's GPU integrator was rebuilt as a <b>wavefront
    (split-kernel) pipeline</b> — the architecture used by Blender Cycles X —
    over a series of increments: staged intersect/shade with material-sorted
    buckets, path regeneration, a dedicated NEE shadow stage, per-path RNG
    streams, and any-hit shadow traversal (Laine, Karras &amp; Aila 2013;
    Cycles X). In one day of merged PRs it went from <b>4x slower</b> than
    the previous one-big-kernel megakernel to <b>1.5x faster</b> on the
    7-material gate scene — re-confirmed cold today at exactly
    <b>{fresh:.2f}x</b> (megakernel 0.494&nbsp;s &rarr; wavefront
    0.329&nbsp;s, 256&sup2; @ 512&nbsp;spp), with the two pipelines'
    images agreeing to a per-channel ratio of 0.997.</p>
    <img class="graph" src="{graphs['arc']}"/>
    <img class="graph" src="{graphs['times']}"/>
    """)

    cs = SHOW / "contact_sheet_gpu-wavefront_1024.png"
    if cs.exists():
        sections.append(img_card(cs, "Disney contact sheet (GPU wavefront, 1024² @ 512 spp, 4.4 s)",
                                 "lambertian / metal / dielectric / Disney / thin glass / emitter / matte — "
                                 "the 7 wavefront material buckets on one sheet"))

    sections.append(f"""
    <h2>In Blender, next to Cycles</h2>
    <p>The Blender addon drives the same engine through a persistent viewport
    session. An A/B benchmark inside headless Blender 5.1 — identical
    generated 99,458-triangle scene, identical camera path, Cycles on OPTIX
    with 3 GPUs enabled — puts Astroray's wavefront frame times at parity or
    better: today's run measured p50 196&nbsp;ms vs Cycles 204&nbsp;ms.
    The formal pkg81 gate (PR #463, 2026-06-12) recorded steady-state
    <b>p99 = 0.84x Cycles</b> against a &le;1.2x target.</p>
    <img class="graph" src="{graphs['viewport']}"/>
    """)

    tex_astro = SHOW / "pkg115_textures_cpu" / "custom_raytracer.png"
    tex_cycles = SHOW / "pkg115_textures" / "cycles.png"
    if tex_astro.exists() and tex_cycles.exists():
        sections.append("<h2>New this run — Cycles-parity procedural textures</h2>"
                        "<p>Blender's procedural texture nodes (Noise, Voronoi, Wave, Brick, Magic, "
                        "Gradient, Checker, White Noise) were ported from Cycles' SVM kernels — "
                        "bit-exact hash family included — and the addon translates the shader "
                        "node trees directly. Same .blend, two engines (Astroray leg on CPU; "
                        "exposure differs by a known dedicated-light energy-scale gap that is "
                        "an open follow-up, pkg89):</p>")
        sections.append(img_card(tex_astro, "Astroray (in Blender, 128 spp)",
                                 "8-sphere procedural texture grid via the addon"))
        sections.append(img_card(tex_cycles, "Cycles reference (same scene)",
                                 "Blender's own render of the identical node trees"))

    feats = [
        (SHOW / "instancing_field.png", "Instancing + two-level BVH (pkg114)",
         "432 instances of 3 meshes share one BLAS each under a TLAS — 28 unique primitives "
         "on the GPU; transform-only edits re-upload just the TLAS (19.5% of a full upload). "
         "1024² @ 512 spp, 70.8 s GPU."),
        (SHOW / "light_tree_128.png", "GPU light tree (pkg86-B)",
         "128 colored area lights sampled through a Cycles-style bounding-cone light tree, "
         "uploaded to the device in 0.10 ms. 1024² @ 512 spp, 11.5 s GPU."),
        (SHOW / "motion_blur_gpu-megakernel.png", "Deformation motion blur (pkg88-C.0)",
         "Per-vertex start/end positions with time-aware BVH — three translating boxes streak "
         "while the static chrome sphere stays sharp. GPU 4.5 s vs CPU 69.2 s at 1024² @ 512 spp."),
    ]
    sections.append("<h2>New this run — instancing, many lights, motion blur</h2>")
    for p, t, c in feats:
        if p.exists():
            sections.append(img_card(p, t, c))

    sections.append("""
    <h2>Standing capabilities</h2>
    <p>The features that were already in the box — general relativity,
    spectral light transport, caustics — rendered with the same engine.</p>
    """)
    standing = [
        (R / "hero_kerr_jet.png", "Kerr black hole + synchrotron jet",
         "geodesics in the Kerr metric (validated against Bardeen-Press-Teukolsky 1972), "
         "Pandya 2016 synchrotron emission, spectral redshift. 1920x1080 @ 1024 spp (existing hero render)."),
        (R / "gallery_prism_caustics.png", "Spectral prism dispersion",
         "per-wavelength Sellmeier refraction through BK7; Specular Manifold Sampling resolves "
         "the rainbow caustic (+8.83 dB vs baseline, pkg64)."),
        (R / "gallery_hdri_world.png", "HDRI environment + MIS",
         "importance-sampled environment lighting with the Jakob-Hanika spectral atlas."),
        (R / "gallery_oidn_before_after.png", "OIDN denoising",
         "Intel Open Image Denoise as a one-line post pass; OptiX denoiser is a flag away."),
        (R / "gallery_convergence_cornell.png", "Monte Carlo convergence",
         "Cornell RMSE slope vs the ideal -1/2 line, measured against an independent reference."),
        (R / "gallery_aov_stack.png", "AOV stack",
         "beauty / normal / depth / albedo / sample heatmap / bounce heatmap from one integrator."),
    ]
    for p, t, c in standing:
        if p.exists():
            sections.append(img_card(p, t, c))

    # Latest reference-bank validation renders (512², rendered this session).
    rb_results = sorted((REPO / "benchmarks" / "reference_bank" / "results").glob("2026-06-12T*"))
    if rb_results:
        rb = rb_results[-1].parent
        latest = {}
        for run_dir in rb_results:
            for scene_dir in run_dir.iterdir():
                if (scene_dir / "actual.png").exists():
                    latest[scene_dir.name] = scene_dir / "actual.png"
        rb_picks = [
            ("synchrotron-jet-m87", "Synchrotron jet (M87-like)",
             "Pandya 2016 power-law synchrotron emission from a bipolar relativistic jet"),
            ("gr-schwarzschild", "Schwarzschild lensing",
             "photon ring + background-grid lensing, geodesics integrated in the metric"),
            ("sms-refractive-glass-sphere", "SMS refractive caustic",
             "Specular Manifold Sampling through a glass sphere — the focusing case SMS exists for"),
            ("glass-mesh-caustic", "Photon-mapped glass caustic",
             "forward photon deposition through a triangle-mesh glass object (pkg110/113)"),
        ]
        cards = [img_card(latest[k], t, c + " — reference-bank validation render, this session", max_w=700)
                 for k, t, c in rb_picks if k in latest]
        if cards:
            sections.append("<h2>Reference-bank validation renders</h2>"
                            "<p>The visual regression bank re-rendered and gated this session "
                            "(13 scenes: GR, ADAF, caustics, dispersion, Cycles A/B).</p>"
                            + "".join(cards))

    sections.append(f"""
    <h2>Test suite</h2>
    <p>Full local suite on this build: <b>1299 passed, 0 failed</b>
    (14 skipped, 21 expected-fail, 3 expected-fail-now-passing), 7m37s on the
    RTX 5070 Ti. CI additionally builds and tests on Linux/GCC.</p>
    <img class="graph" src="{graphs['suite']}"/>
    <p class="fine">All timings measured 2026-06-12 on the project workstation
    (RTX 5070 Ti, CUDA 12.8, Windows 11) with build b67b50f unless explicitly
    labeled as a historical PR series. The hero Kerr render and the pkg55
    optimization-arc ratios are reused/labeled history; everything else was
    produced fresh in this session.</p>
    """)

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Astroray — June 2026 feature showcase</title>
<style>
  body {{ background:{DARK}; color:{FG}; font-family: 'Segoe UI', system-ui, sans-serif;
         max-width: 1100px; margin: 0 auto; padding: 24px; line-height: 1.55; }}
  h1 {{ font-size: 2.1em; margin-bottom: 0.1em; }}
  h2 {{ color:{ACCENT}; border-bottom: 1px solid #30363d; padding-bottom: 6px; margin-top: 1.8em; }}
  .sub {{ color: #8b949e; margin-top: 0; }}
  .cards {{ display: flex; gap: 14px; flex-wrap: wrap; margin: 18px 0; }}
  .stat {{ background:{PANEL}; border: 1px solid #30363d; border-radius: 10px;
           padding: 14px 20px; flex: 1; min-width: 200px; }}
  .stat .n {{ font-size: 1.9em; font-weight: 700; color:{ACCENT}; }}
  .stat .d {{ color: #8b949e; font-size: 0.9em; }}
  .card {{ background:{PANEL}; border: 1px solid #30363d; border-radius: 10px;
           padding: 10px; margin: 18px 0; }}
  .card img {{ width: 100%; border-radius: 6px; display: block; }}
  figcaption {{ color: #bdc6cf; font-size: 0.92em; padding: 8px 4px 2px; }}
  .graph {{ width: 100%; border-radius: 10px; border: 1px solid #30363d; margin: 14px 0; }}
  .fine {{ color: #8b949e; font-size: 0.85em; }}
  a {{ color: {ACCENT}; }}
</style></head><body>
<h1>Astroray</h1>
<p class="sub">June 2026 feature showcase — physically based spectral path tracer
with a CUDA wavefront GPU backend, a Blender 5.1 addon, and a general-relativistic
rendering mode. All numbers measured 2026-06-12.</p>
<div class="cards">
  <div class="stat"><div class="n">1.50x</div><div class="d">GPU wavefront vs megakernel,
  re-measured today (was 4x slower at first bring-up)</div></div>
  <div class="stat"><div class="n">0.84x</div><div class="d">viewport p99 vs Blender
  Cycles-OPTIX in-Blender A/B (pkg81 gate, ≤1.2x target)</div></div>
  <div class="stat"><div class="n">1299 / 0</div><div class="d">tests passed / failed,
  full suite on RTX hardware today</div></div>
  <div class="stat"><div class="n">+8.83 dB</div><div class="d">spectral caustics via
  Specular Manifold Sampling (pkg64 receipt)</div></div>
</div>
{''.join(sections)}
</body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""pkg93 — produce the README gallery tiles.

Composites and re-exports the 6 non-Kerr-hero tiles referenced from
README.md. Each tile derives from a checked-in `test_results/` asset
(spec G2 — no untracked provenance), plus one small new HDRI-world
render at 1280x720 / 1024 spp.

Run from any CWD; outputs land in repo-root `docs/renders/`.

    python scripts/diagnostics/render_readme_gallery.py

Idempotent: regenerates every tile from sources on each run.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
RENDERS_DIR = ROOT / "docs" / "renders"


def _resolve_test_results() -> Path:
    """Find test_results/ — it's gitignored, so worktrees don't have it.

    Prefer $ASTRORAY_TEST_RESULTS; else use the current root's; else fall
    back to the main repo via `git rev-parse --git-common-dir`.
    """
    env = os.environ.get("ASTRORAY_TEST_RESULTS")
    if env:
        return Path(env)
    local = ROOT / "test_results"
    if (local / "session_close_2026-05-14b").exists():
        return local
    import subprocess
    try:
        common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"], cwd=ROOT, text=True
        ).strip()
        # common ends in .../.git ; parent is the main worktree
        main_repo = (Path(common).resolve() / "..").resolve()
        cand = main_repo / "test_results"
        if cand.exists():
            return cand
    except Exception:
        pass
    return local  # let the FileNotFoundError surface


TR = _resolve_test_results()


def _load(p: Path) -> Image.Image:
    if not p.exists():
        raise FileNotFoundError(f"source asset missing: {p}")
    return Image.open(p).convert("RGB")


def _save(img: Image.Image, name: str) -> None:
    RENDERS_DIR.mkdir(parents=True, exist_ok=True)
    out = RENDERS_DIR / name
    img.save(out, "PNG", optimize=True)
    print(f"  wrote {out.relative_to(ROOT)}  ({out.stat().st_size / 1024:.0f} KB, {img.size[0]}x{img.size[1]})")


def _fit(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize preserving aspect, then pad with black to target."""
    iw, ih = img.size
    scale = min(target_w / iw, target_h / ih)
    nw, nh = int(round(iw * scale)), int(round(ih * scale))
    resized = img.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    canvas.paste(resized, ((target_w - nw) // 2, (target_h - nh) // 2))
    return canvas


def _label(img: Image.Image, text: str, *, anchor: str = "tl", pad: int = 10) -> Image.Image:
    """Draw a small white label with black shadow at a corner."""
    out = img.copy()
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    w, h = out.size
    if anchor == "tl":
        x, y = pad, pad
    elif anchor == "tr":
        x, y = w - tw - pad, pad
    elif anchor == "bl":
        x, y = pad, h - th - pad - 4
    else:  # br
        x, y = w - tw - pad, h - th - pad - 4
    # shadow
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        draw.text((x + dx, y + dy), text, fill=(0, 0, 0), font=font)
    draw.text((x, y), text, fill=(240, 240, 240), font=font)
    return out


# ---------------------------------------------------------------------------
# Tile producers
# ---------------------------------------------------------------------------

def tile_material_contact_sheet(astroray_module) -> None:
    """Live render of the pkg55 7-material contact sheet — by the GPU
    wavefront path tracer (owner feedback 2026-06: the old re-export was
    "flat and boring"; this is the perf-gate scene at hero quality)."""
    sys.path.insert(0, str(ROOT / "tests" / "scenes"))
    import disney_contact_sheet

    r = astroray_module.Renderer()
    disney_contact_sheet.build_scene(r)
    W, H = 1280, 720
    disney_contact_sheet.setup_camera(r, width=W, height=H)
    r.set_seed(42)
    r.set_integrator("wavefront_path_tracer")
    r.set_use_gpu(True)
    spp = 2048
    print(f"  rendering contact sheet {W}x{H} @ {spp} spp (GPU wavefront)...")
    t0 = time.perf_counter()
    pixels = np.asarray(r.render(spp, 8, None, True), dtype=np.float32)
    print(f"  -> {time.perf_counter() - t0:.1f}s")
    img = Image.fromarray(np.clip(pixels * 255.0, 0, 255).astype(np.uint8))
    img = _label(img, "7 plugin materials - GPU wavefront path tracer", anchor="bl")
    _save(img, "gallery_material_contact_sheet.png")


def _build_convergence_cornell(r, width: int, height: int) -> None:
    """Cornell box mirroring benchmarks/showcase/scenes/convergence_grid.py
    (kept inline so this producer stays self-contained per pkg93 G2)."""
    r.setup_camera([0.0, 0.15, 5.4], [0.0, -0.15, 0.0], [0.0, 1.0, 0.0],
                   42.0, width / height, 0.0, 5.4, width, height)
    r.set_background_color([0.0, 0.0, 0.0])
    white = r.create_material("lambertian", [0.74, 0.74, 0.72], {})
    red = r.create_material("lambertian", [0.72, 0.08, 0.06], {})
    green = r.create_material("lambertian", [0.10, 0.50, 0.16], {})
    light = r.create_material("light", [1.0, 0.96, 0.84], {"intensity": 18.0})
    r.add_triangle([-2, -2, -2], [2, -2, -2], [2, -2, 2], white)
    r.add_triangle([-2, -2, -2], [2, -2, 2], [-2, -2, 2], white)
    r.add_triangle([-2, 2, -2], [-2, 2, 2], [2, 2, 2], white)
    r.add_triangle([-2, 2, -2], [2, 2, 2], [2, 2, -2], white)
    r.add_triangle([-2, -2, -2], [-2, 2, -2], [2, 2, -2], white)
    r.add_triangle([-2, -2, -2], [2, 2, -2], [2, -2, -2], white)
    r.add_triangle([-2, -2, -2], [-2, -2, 2], [-2, 2, 2], red)
    r.add_triangle([-2, -2, -2], [-2, 2, 2], [-2, 2, -2], red)
    r.add_triangle([2, -2, -2], [2, 2, -2], [2, 2, 2], green)
    r.add_triangle([2, -2, -2], [2, 2, 2], [2, -2, 2], green)
    r.add_sphere([0.0, -1.1, 0.55], 0.78, white)
    r.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, -0.35], [0.42, 1.96, 0.35], light)
    r.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, 0.35], [-0.42, 1.96, 0.35], light)


def tile_convergence_cornell(astroray_module) -> None:
    """Convergence strip + RMSE curve against an INDEPENDENT reference.

    Owner feedback 2026-06: the old curve used the last strip image as its
    own reference, so the final point dropped to zero artificially. Here the
    reference is 8192 spp with a different seed, so every point on the curve
    is an honest distance-to-truth and the slope stays smooth through the
    last sample count.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    spp_series = [1, 4, 16, 64, 256, 1024]
    size = 432
    renders = {}
    for spp in spp_series:
        r = astroray_module.Renderer()
        _build_convergence_cornell(r, size, size)
        r.set_seed(42)
        r.set_integrator("path_tracer")
        r.set_use_gpu(True)
        t0 = time.perf_counter()
        renders[spp] = np.asarray(r.render(spp, 8, None, False), dtype=np.float32)
        print(f"  cornell {spp:5d} spp -> {time.perf_counter() - t0:.2f}s")
    # Independent reference: different seed, 8x the highest strip spp.
    r = astroray_module.Renderer()
    _build_convergence_cornell(r, size, size)
    r.set_seed(1337)
    r.set_integrator("path_tracer")
    r.set_use_gpu(True)
    t0 = time.perf_counter()
    ref = np.asarray(r.render(8192, 8, None, False), dtype=np.float32)
    print(f"  cornell reference 8192 spp (seed 1337) -> {time.perf_counter() - t0:.2f}s")

    rmse = [float(np.sqrt(np.mean((renders[s] - ref) ** 2))) for s in spp_series]

    # Strip: 6 gamma-corrected thumbnails across the top.
    cell_w, cell_h = 1280 // len(spp_series), 360
    canvas = Image.new("RGB", (1280, 720), (0, 0, 0))
    for i, spp in enumerate(spp_series):
        img8 = np.clip(renders[spp] ** (1.0 / 2.2) * 255.0, 0, 255).astype(np.uint8)
        tile = _fit(Image.fromarray(img8), cell_w, cell_h)
        tile = _label(tile, f"{spp} spp", anchor="bl")
        canvas.paste(tile, (i * cell_w, 0))

    # Curve: log-log RMSE vs spp with the -1/2 Monte Carlo guide slope.
    fig, ax = plt.subplots(figsize=(12.8, 3.6), dpi=100)
    ax.loglog(spp_series, rmse, "o-", color="#4fc3f7", label="RMSE vs independent 8192-spp ref")
    slope = np.polyfit(np.log(spp_series), np.log(rmse), 1)[0]
    guide = rmse[0] * (np.asarray(spp_series, np.float64)) ** -0.5
    ax.loglog(spp_series, guide, "--", color="#888", label="ideal MC slope -0.5")
    ax.set_xlabel("samples per pixel")
    ax.set_ylabel("RMSE (linear)")
    ax.set_title(f"Cornell convergence - measured slope {slope:.3f}")
    ax.legend()
    ax.grid(True, which="both", alpha=0.25)
    fig.tight_layout()
    import io
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    canvas.paste(_fit(Image.open(buf).convert("RGB"), 1280, 360), (0, 360))
    _save(canvas, "gallery_convergence_cornell.png")


def _build_aov_scene(r) -> None:
    """Chrome + glass + red Disney spheres on a grey stage — clean AOVs."""
    grey = r.create_material("lambertian", [0.55, 0.55, 0.58], {})
    back = r.create_material("lambertian", [0.35, 0.38, 0.45], {})
    chrome = r.create_material("metal", [0.92, 0.92, 0.94], {"roughness": 0.06})
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})
    red = r.create_material("disney", [0.8, 0.18, 0.15],
                            {"metallic": 0.1, "roughness": 0.35})
    light = r.create_material("light", [1.0, 0.96, 0.9], {"intensity": 6.0})
    r.add_triangle([-8, -0.8, -8], [8, -0.8, -8], [8, -0.8, 6], grey)
    r.add_triangle([-8, -0.8, -8], [8, -0.8, 6], [-8, -0.8, 6], grey)
    r.add_triangle([-8, -0.8, -4], [8, -0.8, -4], [8, 5, -4], back)
    r.add_triangle([-8, -0.8, -4], [8, 5, -4], [-8, 5, -4], back)
    r.add_sphere([-1.5, 0.0, -1.0], 0.8, chrome)
    r.add_sphere([0.0, 0.0, 0.3], 0.8, glass)
    r.add_sphere([1.6, 0.0, -1.2], 0.8, red)
    r.add_triangle([-1.5, 4, -1.5], [1.5, 4, -1.5], [1.5, 4, 1.5], light)
    r.add_triangle([-1.5, 4, -1.5], [1.5, 4, 1.5], [-1.5, 4, 1.5], light)
    r.set_background_color([0.04, 0.05, 0.08])
    r.setup_camera([0.0, 1.2, 4.6], [0.0, 0.0, -0.6], [0, 1, 0],
                   42.0, 640.0 / 540.0, 0.0, 5.0, 640, 540)


def tile_aov_stack(astroray_module) -> None:
    """2x3 AOV grid: beauty / normal / depth / albedo / sample heatmap /
    bounce heatmap (owner feedback 2026-06: liked the 2x2, asked for the
    extra heatmap passes). Each pass replaces the colour output, so the
    scene renders once per pass."""
    passes = [
        ("Beauty", None, 512, False),
        ("Normal", "normal_aov", 16, False),
        ("Depth", "depth_aov", 16, False),
        ("Albedo", "albedo_aov", 16, False),
        ("Sample heatmap (adaptive)", "sample_heatmap", 64, True),
        ("Bounce heatmap", "bounce_heatmap", 64, False),
    ]
    cell_w, cell_h = 1280 // 3, 360
    canvas = Image.new("RGB", (1280, 720), (0, 0, 0))
    for idx, (label, pass_name, spp, adaptive) in enumerate(passes):
        r = astroray_module.Renderer()
        _build_aov_scene(r)
        r.set_seed(42)
        r.set_integrator("path_tracer")
        if adaptive:
            r.set_adaptive_sampling(True)
        if pass_name:
            r.add_pass(pass_name)
        t0 = time.perf_counter()
        px = np.asarray(r.render(spp, 8, None, True), dtype=np.float32)
        print(f"  AOV {label!r} ({spp} spp) -> {time.perf_counter() - t0:.1f}s")
        img = Image.fromarray(np.clip(px * 255.0, 0, 255).astype(np.uint8))
        tile = _label(_fit(img, cell_w, cell_h), label, anchor="tl")
        canvas.paste(tile, ((idx % 3) * cell_w, (idx // 3) * cell_h))
    _save(canvas, "gallery_aov_stack.png")


def _build_denoise_scene(r) -> None:
    """64 coloured area-light panels over three probe spheres — colourful and
    deliberately noisy at low spp (owner feedback 2026-06: old tile was low
    resolution and a boring scene)."""
    import math as _math
    floor = r.create_material("lambertian", [0.5, 0.5, 0.52], {})
    ext = 20.0
    r.add_triangle([-ext, 0, -ext], [ext, 0, -ext], [ext, 0, ext], floor)
    r.add_triangle([-ext, 0, -ext], [ext, 0, ext], [-ext, 0, ext], floor)
    rng = np.random.default_rng(11)
    for k in range(64):
        gx = (k % 8 - 3.5) * 2.4
        gz = (k // 8) * 1.7 - 4.0
        hue = rng.uniform(0, 1)
        col = [0.5 + 0.5 * _math.sin(6.28 * (hue + o)) for o in (0.0, 0.33, 0.67)]
        m = r.create_material("light", col, {"intensity": float(rng.uniform(4, 10))})
        y = rng.uniform(1.4, 5.0)
        s = 0.34
        r.add_triangle([gx - s, y, gz - s], [gx + s, y, gz - s], [gx + s, y, gz + s], m)
        r.add_triangle([gx - s, y, gz - s], [gx + s, y, gz + s], [gx - s, y, gz + s], m)
    probe = r.create_material("metal", [0.9, 0.9, 0.92], {"roughness": 0.08})
    matte = r.create_material("lambertian", [0.8, 0.78, 0.75], {})
    glass = r.create_material("dielectric", [1, 1, 1], {"ior": 1.5})
    r.add_sphere([-2.4, 1.0, 1.2], 1.0, probe)
    r.add_sphere([0.0, 1.0, 0.2], 1.0, matte)
    r.add_sphere([2.4, 1.0, 1.2], 1.0, glass)
    r.set_background_color([0.01, 0.012, 0.02])
    W, H = 1280, 720
    r.setup_camera([0.0, 2.8, 10.0], [0.0, 1.2, -1.5], [0, 1, 0],
                   40.0, W / H, 0.0, 10.0, W, H)


def tile_oidn_before_after(astroray_module) -> None:
    """Split-frame OIDN demo at 1280x720: same 24-spp GPU render, left raw,
    right through the OIDN pass."""
    halves = []
    for use_oidn in (False, True):
        r = astroray_module.Renderer()
        _build_denoise_scene(r)
        r.set_seed(42)
        r.set_integrator("path_tracer")
        r.set_use_gpu(True)
        if use_oidn:
            r.add_pass("oidn_denoiser")
        t0 = time.perf_counter()
        px = np.asarray(r.render(24, 6, None, True), dtype=np.float32)
        print(f"  denoise leg oidn={use_oidn} -> {time.perf_counter() - t0:.1f}s")
        halves.append(Image.fromarray(np.clip(px * 255.0, 0, 255).astype(np.uint8)))
    W, H = halves[0].size
    canvas = Image.new("RGB", (W, H))
    canvas.paste(halves[0].crop((0, 0, W // 2, H)), (0, 0))
    canvas.paste(halves[1].crop((W // 2, 0, W, H)), (W // 2, 0))
    draw = ImageDraw.Draw(canvas)
    draw.line([(W // 2, 0), (W // 2, H)], fill=(255, 255, 255), width=2)
    canvas = _label(canvas, "24 spp raw", anchor="tl")
    canvas = _label(canvas, "24 spp + OIDN", anchor="tr")
    _save(canvas, "gallery_oidn_before_after.png")


def tile_disney_sweep() -> None:
    """2x3 grid of Disney roughness (top row) + glass IOR (bottom row)."""
    sources = [
        (TR / "mat_disney_r0.05.png", "Disney r=0.05"),
        (TR / "mat_disney_r0.30.png", "Disney r=0.30"),
        (TR / "mat_disney_r0.70.png", "Disney r=0.70"),
        (TR / "mat_glass_ior1.2.png", "Glass IOR=1.2"),
        (TR / "mat_glass_ior1.5.png", "Glass IOR=1.5"),
        (TR / "mat_glass_ior2.0.png", "Glass IOR=2.0"),
    ]
    cell_w, cell_h = 1280 // 3, 720 // 2
    canvas = Image.new("RGB", (1280, 720), (0, 0, 0))
    for idx, (path, label) in enumerate(sources):
        img = _load(path)
        fitted = _fit(img, cell_w, cell_h)
        fitted = _label(fitted, label, anchor="bl")
        x = (idx % 3) * cell_w
        y = (idx // 3) * cell_h
        canvas.paste(fitted, (x, y))
    _save(canvas, "gallery_disney_sweep.png")


# ---------------------------------------------------------------------------
# Prism caustic — hero-quality re-render (pkg29a/pkg64 scene)
# ---------------------------------------------------------------------------

def tile_prism_caustic(astroray_module, *, spp: int = 256,
                       preview: bool = False, wide: bool = False) -> None:
    """Hero-quality spectral prism dispersion render.

    Renders the canonical refbank prism scene
    (benchmarks/reference_bank/scenes/prism-bk7-collimated/scene.py — the
    "pkg104 showcase composition") at README resolution: a triangulated BK7
    prism under a collimated sun, dispersed per-wavelength by Sellmeier IOR
    and deposited on the floor by the FORWARD photon caustic integrator
    (`light_tracer_caustic`, Arvo 1986 / Jensen 1996; pkg110/113). A
    backward caustic_path_tracer comp was tried first (2026-06) and produces
    spatially-chaotic specular-connection noise on a flat (non-focusing)
    prism — see the scene module's docstring for the full why.

    CPU-only (Sellmeier dispersion has no GPU lowering).
    """
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "prism_scene",
        ROOT / "benchmarks" / "reference_bank" / "scenes"
             / "prism-bk7-collimated" / "scene.py")
    prism_scene = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(prism_scene)

    r = prism_scene.make_scene(astroray_module)
    W, H = (640, 360) if preview else (1920, 1080)
    r.set_integrator_param("photon_count", 12000000)
    if wide:
        # Context framing: prism upper-left, rainbow band falling to the floor.
        r.setup_camera([4.6, 1.3, 5.6], [1.3, -1.5, 0.0], [0.0, 1.0, 0.0],
                       33.0, W / H, 0.0, 6.0, W, H)
    else:
        # Refbank's zoomed band composition ("pkg104 showcase") at 16:9,
        # tightened so the spectrum fills the frame (owner feedback: zoom in
        # on the important part).
        r.setup_camera([2.5, 0.1, 3.4], [2.5, -3.0, 0.0], [0.0, 1.0, 0.0],
                       18.0, W / H, 0.0, 4.5, W, H)
    r.set_seed(prism_scene.SEED)

    print(f"  rendering prism rainbow {W}x{H} @ {spp} spp "
          f"(CPU light_tracer_caustic, 12M photons)...")
    t0 = time.perf_counter()
    pixels = np.asarray(r.render(spp, prism_scene.MAX_DEPTH, None, True),
                        dtype=np.float32)
    elapsed = time.perf_counter() - t0
    print(f"  -> {elapsed:.1f}s ({elapsed/60:.1f} min)")
    out = Image.fromarray(np.clip(pixels * 255.0, 0, 255).astype(np.uint8))
    _save(out, "gallery_prism_caustics.png")


def _legacy_tile_prism_caustic(astroray_module, *, spp: int = 2048,
                               preview: bool = False) -> None:
    """Previous backward-tracer comp (caustic_path_tracer + area-light beam).
    Kept for reference; not called — see tile_prism_caustic docstring."""
    r = astroray_module.Renderer()

    # Classic apex-up equilateral prism with horizontal beam entering the
    # right-leaning face. Composition:
    #   - White screen on the LEFT receives the dispersed rainbow exiting the
    #     left-leaning face.
    #   - White floor below grounds the scene and catches grazing dispersion.
    #   - Camera in front-right, looking at the prism + screen.

    # Owner feedback 2026-06 (pkg93 lessons): the rainbow must read brighter
    # than the directly-lit wall. Both the rainbow and the "directly-lit
    # wall" are reflections off the same surface, so wall albedo cannot fix
    # the contrast — instead an aperture blocker just in front of the prism's
    # entry face passes the full beam onto the glass while shadowing the
    # receiver wall from the (diffuse) emitter.
    grey = r.create_material("lambertian", [0.70, 0.69, 0.67], {})
    dark = r.create_material("lambertian", [0.03, 0.03, 0.03], {})

    # Left receiver wall — vertical Y-Z plane at x = -2.5, facing +X (right)
    r.add_triangle([-2.5, -1.5, -2.0], [-2.5, -1.5, 2.0], [-2.5, 1.8, 2.0], grey)
    r.add_triangle([-2.5, -1.5, -2.0], [-2.5, 1.8, 2.0], [-2.5, 1.8, -2.0], grey)
    # Floor — horizontal X-Z plane at y = -1.5
    r.add_triangle([-2.5, -1.5, -2.0], [3.0, -1.5, -2.0], [3.0, -1.5, 2.0], grey)
    r.add_triangle([-2.5, -1.5, -2.0], [3.0, -1.5, 2.0], [-2.5, -1.5, 2.0], grey)

    # Aperture blocker at x = +0.95: a dark wall with a window matching the
    # prism's entry face (y in [-0.45, 0.60], z in [-0.75, 0.75]). The beam
    # floods the prism; the receiver wall sees almost only dispersed light.
    bx = 0.95
    by0, by1, bz0, bz1 = -1.5, 1.8, -2.0, 2.0
    ay0, ay1, az0, az1 = -0.45, 0.60, -0.75, 0.75

    def _panel(y0, y1, zz0, zz1):
        r.add_triangle([bx, y0, zz0], [bx, y1, zz0], [bx, y1, zz1], dark)
        r.add_triangle([bx, y0, zz0], [bx, y1, zz1], [bx, y0, zz1], dark)

    _panel(ay1, by1, bz0, bz1)       # above the window
    _panel(by0, ay0, bz0, bz1)       # below the window
    _panel(ay0, ay1, bz0, az0)       # window sill (front)
    _panel(ay0, ay1, az1, bz1)       # window sill (back)

    # Equilateral prism — apex up, base down. Cross-section vertices in X-Y:
    #   apex      = ( 0.0,  +0.55)
    #   bot-left  = (-0.55, -0.45)
    #   bot-right = (+0.55, -0.45)
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"glass_preset": "bk7"})
    apex_x, apex_y = 0.0, 0.55
    bl_x, bl_y = -0.55, -0.45
    br_x, br_y = +0.55, -0.45
    z0, z1 = -0.7, 0.7
    # 6 vertices: front (z=z1) and back (z=z0)
    Af, Bf, Cf = [apex_x, apex_y, z1], [bl_x, bl_y, z1], [br_x, br_y, z1]
    Ab, Bb, Cb = [apex_x, apex_y, z0], [bl_x, bl_y, z0], [br_x, br_y, z0]
    # End caps (front and back)
    r.add_triangle(Af, Bf, Cf, glass)
    r.add_triangle(Ab, Cb, Bb, glass)
    # Left-leaning face (apex to bot-left, both Z): RAINBOW EXITS HERE
    r.add_triangle(Af, Ab, Bb, glass)
    r.add_triangle(Af, Bb, Bf, glass)
    # Right-leaning face (apex to bot-right, both Z): BEAM ENTERS HERE
    r.add_triangle(Af, Cf, Cb, glass)
    r.add_triangle(Af, Cb, Ab, glass)
    # Bottom face (bot-left to bot-right, both Z)
    r.add_triangle(Bf, Bb, Cb, glass)
    r.add_triangle(Bf, Cb, Cf, glass)

    # Bright collimated beam at x = +2.5, aimed horizontally at -X to hit the
    # right-leaning face at an angle (~30° from normal). Y centered on prism
    # mid-height so beam enters cleanly into glass.
    beam = r.create_material("light", [1.0, 0.97, 0.92], {"intensity": 240.0})
    bx = 2.5
    by_c = 0.0
    bz_c = 0.0
    half = 0.05
    r.add_triangle([bx, by_c - half, bz_c - half], [bx, by_c + half, bz_c - half], [bx, by_c + half, bz_c + half], beam)
    r.add_triangle([bx, by_c - half, bz_c - half], [bx, by_c + half, bz_c + half], [bx, by_c - half, bz_c + half], beam)

    r.set_background_color([0.0, 0.0, 0.0])

    # Camera: front-right, slightly above, zoomed on the prism + the rainbow
    # on the receiver wall (owner feedback: frame the important part).
    W, H = (1920, 1080) if not preview else (640, 360)
    r.setup_camera(
        [1.4, 0.45, 3.1], [-0.9, -0.3, 0.0], [0.0, 1.0, 0.0],
        38.0, W / H, 0.0, 3.6, W, H)

    max_depth = 12
    r.set_integrator_param("max_depth", max_depth)
    r.set_integrator_param("caustic_chain_iters", 3)
    r.set_integrator("caustic_path_tracer")
    r.set_seed(145)

    print(f"  rendering prism caustic {W}x{H} @ {spp} spp (CPU, caustic_path_tracer + BK7)...")
    print(f"  this is the heavy one — expect several minutes")
    t0 = time.perf_counter()
    pixels = np.asarray(r.render(spp, max_depth, None, True), dtype=np.float32)
    elapsed = time.perf_counter() - t0
    print(f"  -> {elapsed:.1f}s ({elapsed/60:.1f} min)")

    # Log-average Reinhard so the rainbow stays vivid against the dark stage
    lum = 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]
    log_avg = float(np.exp(np.mean(np.log(lum + 1e-8))))
    scaled = pixels * (0.18 / max(log_avg, 1e-8))
    tm = scaled / (1.0 + scaled)
    pixels_u8 = np.clip(tm ** (1.0 / 2.2) * 255.0, 0, 255).astype(np.uint8)
    out = Image.fromarray(pixels_u8, mode="RGB")
    _save(out, "gallery_prism_caustics.png")


# ---------------------------------------------------------------------------
# HDRI world tile — small new render
# ---------------------------------------------------------------------------

def _write_radiance_hdr(path: Path, img: np.ndarray) -> None:
    """Minimal Radiance .hdr writer (RGBE) — mirrors tests/test_world_hdri_parity.py."""
    img = np.asarray(img, dtype=np.float32)
    height, width = img.shape[:2]
    rgbe = np.zeros((height, width, 4), dtype=np.uint8)
    m = np.max(img, axis=2)
    valid = m > 1e-32
    mant, exp = np.frexp(np.where(valid, m, 1.0))
    scale = np.where(valid, mant * 256.0 / np.where(m > 0, m, 1.0), 0.0)
    rgbe[..., 0] = np.clip(np.floor(img[..., 0] * scale), 0, 255).astype(np.uint8)
    rgbe[..., 1] = np.clip(np.floor(img[..., 1] * scale), 0, 255).astype(np.uint8)
    rgbe[..., 2] = np.clip(np.floor(img[..., 2] * scale), 0, 255).astype(np.uint8)
    rgbe[..., 3] = np.where(valid, exp + 128, 0).astype(np.uint8)
    with open(path, "wb") as f:
        f.write(b"#?RADIANCE\n")
        f.write(b"FORMAT=32-bit_rle_rgbe\n\n")
        f.write(f"-Y {height} +X {width}\n".encode("ascii"))
        f.write(rgbe.tobytes())


def _write_studio_hdri(path: Path, w: int = 512, h: int = 256) -> None:
    """Sky-with-sun procedural latlong env. Top blue, horizon warm, ground dim.

    Equirectangular: u in [0, 1] is azimuth, v in [0, 1] is polar angle
    (0 = +Y up). A single brighter sun disk at (azimuth=0.7, elevation~30°).
    """
    img = np.zeros((h, w, 3), dtype=np.float32)
    for y in range(h):
        v = y / max(1, h - 1)  # 0 zenith -> 1 nadir
        theta = v * np.pi
        # blue sky high, warm horizon, dim ground
        if theta < np.pi / 2:
            t = theta / (np.pi / 2)  # 0 zenith -> 1 horizon
            sky = (1.0 - t) * np.array([0.30, 0.55, 1.10]) + t * np.array([1.20, 0.85, 0.55])
            img[y, :, :] = sky
        else:
            t = (theta - np.pi / 2) / (np.pi / 2)
            ground = (1.0 - t) * np.array([0.50, 0.40, 0.30]) + t * np.array([0.08, 0.07, 0.06])
            img[y, :, :] = ground
    # Sun: bright disk near horizon-ish
    sun_phi = 0.7  # azimuth fraction
    sun_v = 0.35  # 0 zenith -> 1 nadir; 0.35 is ~37° from zenith
    cx = int(sun_phi * w)
    cy = int(sun_v * h)
    radius = max(2, h // 60)
    yy, xx = np.mgrid[:h, :w]
    dx = ((xx - cx + w // 2) % w) - w // 2  # azimuth wraps
    dy = yy - cy
    sun_mask = (dx * dx + dy * dy) <= (radius * radius)
    img[sun_mask] = np.array([40.0, 32.0, 22.0])
    _write_radiance_hdr(path, img)


def tile_hdri_world(astroray_module) -> None:
    """Render a small HDRI-lit scene: chrome + glass spheres on a ground plane."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        hdr_path = Path(td) / "studio.hdr"
        _write_studio_hdri(hdr_path)

        r = astroray_module.Renderer()
        if r.gpu_available:
            r.set_use_gpu(True)
        r.set_integrator("path_tracer")
        r.set_seed(7)

        # HDRI as world. signature: (path, strength, rx, ry, rz, tr, tg, tb, blender_convention)
        r.load_environment_map(str(hdr_path), 1.0,
                               0.0, 0.0, 0.0,
                               1.0, 1.0, 1.0,
                               False)

        ground = r.create_material("lambertian", [0.55, 0.55, 0.55], {})
        chrome = r.create_material("disney", [0.95, 0.95, 0.96],
                                   {"metallic": 1.0, "roughness": 0.08})
        glass = r.create_material("dielectric", [1.0, 1.0, 1.0],
                                  {"ior": 1.52})
        copper = r.create_material("disney", [0.95, 0.55, 0.30],
                                   {"metallic": 1.0, "roughness": 0.25})

        y = -0.5
        r.add_triangle([-6, y, -6], [6, y, -6], [6, y, 6], ground)
        r.add_triangle([-6, y, -6], [6, y, 6], [-6, y, 6], ground)

        r.add_sphere([-1.4, 0.0, 0.0], 0.5, chrome)
        r.add_sphere([0.0, 0.0, 0.0], 0.5, glass)
        r.add_sphere([1.4, 0.0, 0.0], 0.5, copper)

        W, H = 1280, 720
        r.setup_camera([0.0, 1.0, 4.5], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
                       28.0, W / H, 0.0, 4.5, W, H)

        spp = 1024
        print(f"  rendering HDRI world {W}x{H} @ {spp} spp on {'GPU' if r.gpu_available else 'CPU'}...")
        t0 = time.perf_counter()
        pixels = np.asarray(r.render(spp, 6, None, False), dtype=np.float32)
        print(f"  -> {time.perf_counter() - t0:.1f}s")

        pixels_u8 = np.clip(pixels * 255.0, 0, 255).astype(np.uint8)
        out = Image.fromarray(pixels_u8, mode="RGB")
        _save(out, "gallery_hdri_world.png")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    print("pkg93 gallery — producing tiles into docs/renders/")
    print()

    # All tiles except the Disney sweep are live renders now (owner feedback
    # 2026-06) — import astroray up front.
    sys.path.insert(0, str(ROOT / "tests"))
    from runtime_setup import configure_test_imports
    configure_test_imports()
    import astroray

    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1].split(",")

    def want(name: str) -> bool:
        return only is None or name in only

    if want("contact_sheet"):
        print("[1/7] material contact sheet (GPU wavefront render)")
        tile_material_contact_sheet(astroray)
    if want("convergence"):
        print("[2/7] Cornell convergence (independent 8192-spp reference)")
        tile_convergence_cornell(astroray)
    if want("aov"):
        print("[3/7] AOV stack (2x3 incl. sample/bounce heatmaps)")
        tile_aov_stack(astroray)
    if want("oidn"):
        print("[4/7] OIDN before/after (64-light scene)")
        tile_oidn_before_after(astroray)
    if want("disney"):
        print("[5/7] Disney sweep (re-export)")
        tile_disney_sweep()
    if want("hdri"):
        print("[6/7] HDRI world (rendered)")
        tile_hdri_world(astroray)
    if "--skip-prism" in sys.argv or not want("prism"):
        print("[7/7] prism caustic — SKIPPED")
    else:
        print("[7/7] prism caustic (heavy render)")
        tile_prism_caustic(astroray)

    print("\nDone. Tile sizes:")
    for p in sorted(RENDERS_DIR.glob("gallery_*.png")):
        print(f"  {p.name}: {p.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

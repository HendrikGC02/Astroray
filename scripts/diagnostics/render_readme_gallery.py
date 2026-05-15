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

def tile_material_contact_sheet() -> None:
    """Re-export the existing 25-material contact sheet."""
    src = TR / "session_close_2026-05-14b" / "contact_sheet" / "material_contact_sheet.png"
    img = _load(src)
    # Fit to 1280x720; the source is wider than 16:9 so we letterbox.
    out = _fit(img, 1280, 720)
    _save(out, "gallery_material_contact_sheet.png")


def tile_convergence_cornell() -> None:
    """Side-by-side: convergence strip (top) + MSE plot (bottom) at 1280x720."""
    strip = _load(TR / "session_close_2026-05-14b" / "convergence" / "convergence_strip.png")
    mse = _load(TR / "session_close_2026-05-14b" / "convergence" / "convergence_mse.png")
    target_w = 1280
    # Strip gets ~60% height, MSE gets ~40%. Letterbox each.
    top = _fit(strip, target_w, 432)
    bot = _fit(mse, target_w, 288)
    canvas = Image.new("RGB", (target_w, 720), (0, 0, 0))
    canvas.paste(top, (0, 0))
    canvas.paste(bot, (0, 432))
    _save(canvas, "gallery_convergence_cornell.png")


def tile_aov_stack() -> None:
    """2x2 grid: beauty / normal / depth / albedo at 1280x720."""
    aov_dir = TR / "session_close_2026-05-14b" / "aov"
    tiles = {
        "Beauty":  _load(aov_dir / "beauty.png"),
        "Normal":  _load(aov_dir / "normal.png"),
        "Depth":   _load(aov_dir / "depth.png"),
        "Albedo":  _load(aov_dir / "albedo.png"),
    }
    cell_w, cell_h = 640, 360
    canvas = Image.new("RGB", (1280, 720), (0, 0, 0))
    positions = [(0, 0), (cell_w, 0), (0, cell_h), (cell_w, cell_h)]
    for (label, img), (x, y) in zip(tiles.items(), positions):
        fitted = _fit(img, cell_w, cell_h)
        fitted = _label(fitted, label, anchor="tl")
        canvas.paste(fitted, (x, y))
    _save(canvas, "gallery_aov_stack.png")


def tile_oidn_before_after() -> None:
    """Re-export the existing OIDN before/after composite."""
    src = TR / "pkg32_oidn_check" / "oidn_before_after.png"
    img = _load(src)
    if img.size[0] < 1280:
        # Source is small (test render); upscale 2x with LANCZOS still looks ok.
        img = img.resize((img.size[0] * 2, img.size[1] * 2), Image.LANCZOS)
    out = _fit(img, 1280, 720)
    _save(out, "gallery_oidn_before_after.png")


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

def tile_prism_caustic(astroray_module, *, spp: int = 4096) -> None:
    """Hero-quality spectral prism dispersion render.

    Composition (designed for visual impact, NOT validation):
      - Camera looks down at a scene from above-front-left
      - BK7 triangular prism sits on a dark stage
      - A bright collimated "sun beam" emitter on the right side aims
        horizontally into the prism's right face
      - A large white wall behind+left receives the dispersed rainbow
      - Black background everywhere else for contrast

    Uses caustic_path_tracer (pkg64 SMS, +8.83 dB receipt) + BK7 Sellmeier
    (pkg29 dispersion). CPU-only — Sellmeier has no GPU implementation.

    Self-contained per spec G2.
    """
    r = astroray_module.Renderer()

    # Classic apex-up equilateral prism with horizontal beam entering the
    # right-leaning face. Composition:
    #   - White screen on the LEFT receives the dispersed rainbow exiting the
    #     left-leaning face.
    #   - White floor below grounds the scene and catches grazing dispersion.
    #   - Camera in front-right, looking at the prism + screen.

    white = r.create_material("lambertian", [0.95, 0.94, 0.92], {})

    # Left receiver wall — vertical Y-Z plane at x = -2.0, facing +X (right)
    r.add_triangle([-2.0, -1.5, -2.0], [-2.0, -1.5, 2.0], [-2.0, 1.8, 2.0], white)
    r.add_triangle([-2.0, -1.5, -2.0], [-2.0, 1.8, 2.0], [-2.0, 1.8, -2.0], white)
    # Floor — horizontal X-Z plane at y = -1.5
    r.add_triangle([-3.0, -1.5, -2.0], [3.0, -1.5, -2.0], [3.0, -1.5, 2.0], white)
    r.add_triangle([-3.0, -1.5, -2.0], [3.0, -1.5, 2.0], [-3.0, -1.5, 2.0], white)

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
    beam = r.create_material("light", [1.0, 0.97, 0.92], {"intensity": 120.0})
    bx = 2.5
    by_c = 0.0
    bz_c = 0.0
    half = 0.05
    r.add_triangle([bx, by_c - half, bz_c - half], [bx, by_c + half, bz_c - half], [bx, by_c + half, bz_c + half], beam)
    r.add_triangle([bx, by_c - half, bz_c - half], [bx, by_c + half, bz_c + half], [bx, by_c - half, bz_c + half], beam)

    r.set_background_color([0.0, 0.0, 0.0])

    # Camera: front-right, slightly above. Frame includes prism + left wall.
    W, H = 1920, 1080
    r.setup_camera(
        [1.5, 0.4, 3.2], [-0.6, -0.1, 0.0], [0.0, 1.0, 0.0],
        40.0, W / H, 0.0, 3.5, W, H)

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

    print("[1/6] material contact sheet")
    tile_material_contact_sheet()
    print("[2/6] Cornell convergence")
    tile_convergence_cornell()
    print("[3/6] AOV stack")
    tile_aov_stack()
    print("[4/6] OIDN before/after")
    tile_oidn_before_after()
    print("[5/6] Disney sweep")
    tile_disney_sweep()
    print("[6/7] HDRI world (rendered)")

    # Lazy-import astroray only for the rendered tiles.
    sys.path.insert(0, str(ROOT / "tests"))
    from runtime_setup import configure_test_imports
    configure_test_imports()
    import astroray
    tile_hdri_world(astroray)

    if "--skip-prism" in sys.argv:
        print("[7/7] prism caustic — SKIPPED (--skip-prism)")
    else:
        print("[7/7] prism caustic (heavy render)")
        tile_prism_caustic(astroray)

    print("\nDone. Tile sizes:")
    for p in sorted(RENDERS_DIR.glob("gallery_*.png")):
        print(f"  {p.name}: {p.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

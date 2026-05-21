#!/usr/bin/env python
"""pkg93 — Kerr black hole + synchrotron jet hero render.

Produces `docs/renders/hero_kerr_jet.png` for README masthead.

Composition (per pkg93 spec):
- Kerr spin a = 0.9, viewed at inclination 75° (near edge-on)
- Slim disk (pkg43): mdot ≈ 0.1, r_inner = r_ISCO, r_outer ≈ 20 M
- Synchrotron jet (pkg42): bipolar, half-angle 5°, power-law p = 2.5
- Dark environment (faint starfield optional, currently disabled)
- Spectral path tracer (native GR spectral dispatch)

References:
- pkg40/41: Kerr metric + geodesics, validated against BPT 1972
- pkg42: synchrotron jet plugin (Pandya et al. 2016)
- pkg43: slim disk (Abramowicz 1988, Page-Thorne 1974)
- pkg67: SampledWavelengths::redshift for GR Doppler

CPU-only — GR ray marching is not on GPU yet. Expect ~6–12 minutes
on a modern desktop CPU at 1920x1080 @ 4096 spp.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
RENDERS_DIR = ROOT / "docs" / "renders"


def tonemap(pixels: np.ndarray, exposure: float = 1.0, gamma: float = 2.2) -> np.ndarray:
    """Log-average Reinhard + gamma. The log-mean luminance is dominated by
    background sky in an astrophysical scene, so the resulting key/avg ratio
    amplifies dim lensed arcs into visibility while soft-clipping the disk
    and jet core.

    Reference: Reinhard et al. 2002 "Photographic Tone Reproduction for
    Digital Images" §3, eq. 1–3.
    """
    lum = 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]
    log_avg = float(np.exp(np.mean(np.log(lum + 1e-8))))
    key = 0.18 * exposure
    scaled = pixels * (key / max(log_avg, 1e-8))
    knee = scaled / (1.0 + scaled)
    return np.clip(knee ** (1.0 / gamma), 0.0, 1.0)


def build_scene(astroray, *, width: int, height: int, spin: float = 0.9):
    """Hero Kerr+jet composition. Returns a renderer ready for r.render()."""
    r = astroray.Renderer()
    r.set_seed(42)
    r.set_adaptive_sampling(False)
    r.set_background_color([0.0, 0.0, 0.0])

    # Camera: ~100 M from BH, inclination ~75° (edge-on enough to see jet
    # vertical and disk lensed ring).
    import math
    distance = 100.0
    incl_deg = 75.0
    incl = math.radians(incl_deg)
    # +Y is up; rotate camera around X so that (0, sin*incl, cos*incl)*d
    # places it above the equatorial plane.
    cam_y = distance * math.cos(incl)
    cam_z = distance * math.sin(incl)
    r.setup_camera(
        [0.0, cam_y, cam_z],
        [0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        18.0,  # narrow fov for tight framing; 35mm-equiv on a tight crop
        width / height,
        0.0,
        distance,
        width,
        height,
    )

    # Kerr black hole with slim disk + synchrotron jet
    mass_m_sun = 10.0
    influence_radius = 100.0
    params = {
        "disk_outer": 20.0,
        "accretion_rate": 0.1,
        "inclination": incl_deg,

        # Slim disk (pkg43) — physical accretion disk model
        "accretion_model": "SLIM_DISK",
        "slim_disk_spin": spin,
        "slim_disk_r_inner": 0.0,  # 0 => auto r_ISCO for given spin
        "slim_disk_intensity_scale": 1.0,
        "slim_disk_base_density": 1.0e3,

        # Synchrotron jet (pkg42) — bipolar
        "enable_jet": True,
        "lorentz_factor": 5.0,
        "half_angle_degrees": 5.0,
        "power_law_index": 2.5,
        "base_density": 1.0e12,
        "magnetic_field": 1.0e6,
        "intensity_scale": 5.0e13,  # pkg99 (2026-05-22): was 1.0e28 to compensate for 5e-14 exposureScale; that multiplication removed from black_hole.h → rescale by 5e-14 to preserve visual.
        "r_base": 1.0,
        "r_max": 50.0,
    }
    r.add_black_hole([0.0, 0.0, 0.0], mass_m_sun, influence_radius, params)
    r.set_integrator("path_tracer")
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--spp", type=int, default=4096)
    ap.add_argument("--max-depth", type=int, default=6)
    ap.add_argument("--spin", type=float, default=0.9)
    ap.add_argument("--preview", action="store_true",
                    help="640x360 @ 64 spp for fast framing iteration")
    ap.add_argument("--exposure", type=float, default=4.0,
                    help="Linear exposure multiplier before soft-knee tonemap")
    ap.add_argument("--out", type=Path, default=RENDERS_DIR / "hero_kerr_jet.png")
    args = ap.parse_args()

    if args.preview:
        args.width, args.height, args.spp = 640, 360, 64

    sys.path.insert(0, str(ROOT / "tests"))
    from runtime_setup import configure_test_imports
    configure_test_imports()
    import astroray

    print(f"pkg93 hero — Kerr+jet")
    print(f"  resolution: {args.width}x{args.height}")
    print(f"  spp: {args.spp}")
    print(f"  spin a = {args.spin}")
    print(f"  output: {args.out}")
    print()

    r = build_scene(astroray, width=args.width, height=args.height, spin=args.spin)

    print(f"  rendering on CPU (GR ray marching) ...")
    t0 = time.perf_counter()
    pixels = np.asarray(r.render(args.spp, args.max_depth, None, False), dtype=np.float32)
    elapsed = time.perf_counter() - t0
    print(f"  -> {elapsed:.1f}s ({elapsed/60:.1f} min)")

    finite = np.isfinite(pixels).all()
    print(f"  finite: {finite}")
    if not finite:
        print("  WARNING: non-finite pixels in output")
        pixels = np.nan_to_num(pixels, nan=0.0, posinf=0.0, neginf=0.0)

    lum = 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]
    print(f"  lum mean={float(lum.mean()):.6f} p99={float(np.percentile(lum,99)):.6f} max={float(lum.max()):.6f}")

    tm = tonemap(pixels, exposure=args.exposure)
    pixels_u8 = np.clip(tm * 255.0, 0, 255).astype(np.uint8)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels_u8, mode="RGB").save(args.out, "PNG", optimize=True)
    print(f"\n  wrote {args.out.relative_to(ROOT) if args.out.is_absolute() else args.out}  "
          f"({args.out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Convergence tracker: render a scene at increasing SPP and plot MSE vs SPP.

Writes per-SPP PNGs, a log-log MSE curve, and a thumbnail strip.

Usage:
    python scripts/convergence_tracker.py [--scene cornell|glass|metal] \
        [--max-spp 1024] [--output-dir test_results/convergence/]
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()

import astroray  # noqa: E402


ALL_SPP = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]


# ---------------------------------------------------------------------------
# Scene builders
# ---------------------------------------------------------------------------

def _make_cornell_renderer(width: int, height: int):
    """Cornell box: diffuse colored walls, diffuse sphere, ceiling light."""
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0.0, 0.15, 5.4],
        look_at=[0.0, -0.15, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=42.0,
        aspect_ratio=width / height,
        aperture=0.0,
        focus_dist=5.4,
        width=width,
        height=height,
    )
    r.set_background_color([0.0, 0.0, 0.0])
    white = r.create_material("lambertian", [0.74, 0.74, 0.72], {})
    red   = r.create_material("lambertian", [0.72, 0.08, 0.06], {})
    green = r.create_material("lambertian", [0.10, 0.50, 0.16], {})
    light = r.create_material("light",      [1.0, 0.96, 0.84],  {"intensity": 18.0})
    # Floor, ceiling, back wall
    r.add_triangle([-2, -2, -2], [2, -2, -2], [2, -2, 2], white)
    r.add_triangle([-2, -2, -2], [2, -2, 2], [-2, -2, 2], white)
    r.add_triangle([-2, 2, -2], [-2, 2, 2], [2, 2, 2], white)
    r.add_triangle([-2, 2, -2], [2, 2, 2], [2, 2, -2], white)
    r.add_triangle([-2, -2, -2], [-2, 2, -2], [2, 2, -2], white)
    r.add_triangle([-2, -2, -2], [2, 2, -2], [2, -2, -2], white)
    # Side walls
    r.add_triangle([-2, -2, -2], [-2, -2, 2], [-2, 2, 2], red)
    r.add_triangle([-2, -2, -2], [-2, 2, 2], [-2, 2, -2], red)
    r.add_triangle([2, -2, -2], [2, 2, -2], [2, 2, 2], green)
    r.add_triangle([2, -2, -2], [2, 2, 2], [2, -2, 2], green)
    # Diffuse sphere
    r.add_sphere([0.0, -1.1, 0.55], 0.78, white)
    # Ceiling light
    r.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, -0.35], [0.42, 1.96, 0.35], light)
    r.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, 0.35], [-0.42, 1.96, 0.35], light)
    return r


def _make_glass_renderer(width: int, height: int):
    """Cornell box variant with a glass sphere."""
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0.0, 0.15, 5.4],
        look_at=[0.0, -0.15, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=42.0,
        aspect_ratio=width / height,
        aperture=0.0,
        focus_dist=5.4,
        width=width,
        height=height,
    )
    r.set_background_color([0.0, 0.0, 0.0])
    white = r.create_material("lambertian", [0.74, 0.74, 0.72], {})
    red   = r.create_material("lambertian", [0.72, 0.08, 0.06], {})
    green = r.create_material("lambertian", [0.10, 0.50, 0.16], {})
    light = r.create_material("light",      [1.0, 0.96, 0.84],  {"intensity": 18.0})
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0],    {"ior": 1.5})
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
    r.add_sphere([0.0, -1.1, 0.55], 0.78, glass)
    r.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, -0.35], [0.42, 1.96, 0.35], light)
    r.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, 0.35], [-0.42, 1.96, 0.35], light)
    return r


def _make_metal_renderer(width: int, height: int):
    """Cornell box variant with a polished metal sphere."""
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0.0, 0.15, 5.4],
        look_at=[0.0, -0.15, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=42.0,
        aspect_ratio=width / height,
        aperture=0.0,
        focus_dist=5.4,
        width=width,
        height=height,
    )
    r.set_background_color([0.0, 0.0, 0.0])
    white = r.create_material("lambertian", [0.74, 0.74, 0.72], {})
    red   = r.create_material("lambertian", [0.72, 0.08, 0.06], {})
    green = r.create_material("lambertian", [0.10, 0.50, 0.16], {})
    light = r.create_material("light",      [1.0, 0.96, 0.84],  {"intensity": 18.0})
    metal = r.create_material("metal",      [0.8, 0.8, 0.9],    {"roughness": 0.05})
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
    r.add_sphere([0.0, -1.1, 0.55], 0.78, metal)
    r.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, -0.35], [0.42, 1.96, 0.35], light)
    r.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, 0.35], [-0.42, 1.96, 0.35], light)
    return r


_SCENE_BUILDERS = {
    "cornell": _make_cornell_renderer,
    "glass":   _make_glass_renderer,
    "metal":   _make_metal_renderer,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render(scene: str, spp: int, width: int, height: int, seed: int) -> np.ndarray:
    r = _SCENE_BUILDERS[scene](width, height)
    r.set_integrator("path_tracer")
    r.set_seed(seed)
    return np.asarray(r.render(spp, 6, None, False), dtype=np.float32)


def _mse(img: np.ndarray, ref: np.ndarray) -> float:
    return float(np.mean((img - ref) ** 2))


def _psnr(mse: float, peak: float = 1.0) -> float:
    if mse <= 0.0:
        return float("inf")
    return 10.0 * math.log10(peak ** 2 / mse)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_convergence(
    scene: str = "cornell",
    max_spp: int = 1024,
    output_dir: Path = ROOT / "test_results" / "convergence",
    width: int = 128,
    height: int = 128,
    seed: int = 42,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)

    spp_levels = [s for s in ALL_SPP if s <= max_spp]

    # Render at every SPP level.
    renders: dict[int, np.ndarray] = {}
    for spp in spp_levels:
        print(f"  Rendering {scene} @ {spp} spp ...", flush=True)
        renders[spp] = _render(scene, spp, width, height, seed)

    reference = renders[spp_levels[-1]]

    # Save per-SPP PNGs and build results table.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    for spp, pixels in renders.items():
        plt.imsave(str(output_dir / f"{scene}_{spp}spp.png"), np.clip(pixels, 0.0, 1.0))

    rows: list[dict] = []
    for spp in spp_levels:
        mse = _mse(renders[spp], reference)
        rows.append({"spp": spp, "mse": mse, "psnr": _psnr(mse)})

    # Print summary table.
    print(f"\n{'SPP':>6}  {'MSE':>12}  {'PSNR (dB)':>10}")
    print("-" * 34)
    for row in rows:
        psnr_str = f"{row['psnr']:10.2f}" if math.isfinite(row["psnr"]) else "       inf"
        print(f"{row['spp']:>6}  {row['mse']:>12.6f}  {psnr_str}")

    # --- convergence_mse.png (log-log MSE vs SPP) ---
    spp_vals = [row["spp"] for row in rows]
    mse_vals = [max(row["mse"], 1e-12) for row in rows]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.loglog(spp_vals, mse_vals, marker="o", color="#3b82f6", linewidth=2, markersize=6)
    ax.set_xlabel("Samples per Pixel")
    ax.set_ylabel("MSE")
    ax.set_title(f"Convergence: {scene} scene")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_dir / "convergence_mse.png", dpi=140)
    plt.close(fig)

    # --- convergence_strip.png (horizontal thumbnail strip) ---
    n = len(spp_levels)
    fig2, axes = plt.subplots(1, n, figsize=(n * 1.2, 1.8))
    if n == 1:
        axes = [axes]
    for ax2, spp in zip(axes, spp_levels):
        ax2.imshow(np.clip(renders[spp], 0.0, 1.0))
        ax2.set_title(f"{spp}spp", fontsize=7)
        ax2.axis("off")
    fig2.tight_layout(pad=0.4)
    fig2.savefig(output_dir / "convergence_strip.png", dpi=140)
    plt.close(fig2)

    print(f"\nOutputs written to: {output_dir}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=list(_SCENE_BUILDERS), default="cornell",
                        help="Scene to render (default: cornell)")
    parser.add_argument("--max-spp", type=int, default=1024,
                        help="Maximum samples per pixel (default: 1024)")
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "test_results" / "convergence",
                        help="Directory for output files")
    args = parser.parse_args()

    run_convergence(
        scene=args.scene,
        max_spp=args.max_spp,
        output_dir=args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

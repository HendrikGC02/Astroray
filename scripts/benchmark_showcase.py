#!/usr/bin/env python
"""Render canonical test scenes at production quality and composite them into a
comparison grid for portfolio/README use.

Usage:
    python scripts/benchmark_showcase.py [--resolution 512] [--samples 256] \
        [--output-dir test_results/showcase/]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()

import astroray  # noqa: E402


# ---------------------------------------------------------------------------
# Scene builders
# ---------------------------------------------------------------------------

def build_cornell_box(r, width: int, height: int) -> None:
    """Classic Cornell box: diffuse red/green/white walls, area light."""
    white = r.create_material("lambertian", [0.73, 0.73, 0.73], {})
    red = r.create_material("lambertian", [0.65, 0.05, 0.05], {})
    green = r.create_material("lambertian", [0.12, 0.45, 0.15], {})
    light = r.create_material("light", [1.0, 0.9, 0.8], {"intensity": 15.0})

    # Floor
    r.add_triangle([-2, -2, -2], [2, -2, -2], [2, -2, 2], white)
    r.add_triangle([-2, -2, -2], [2, -2, 2], [-2, -2, 2], white)
    # Ceiling
    r.add_triangle([-2, 2, -2], [-2, 2, 2], [2, 2, 2], white)
    r.add_triangle([-2, 2, -2], [2, 2, 2], [2, 2, -2], white)
    # Back wall
    r.add_triangle([-2, -2, -2], [-2, 2, -2], [2, 2, -2], white)
    r.add_triangle([-2, -2, -2], [2, 2, -2], [2, -2, -2], white)
    # Left wall (red)
    r.add_triangle([-2, -2, -2], [-2, -2, 2], [-2, 2, 2], red)
    r.add_triangle([-2, -2, -2], [-2, 2, 2], [-2, 2, -2], red)
    # Right wall (green)
    r.add_triangle([2, -2, -2], [2, 2, -2], [2, 2, 2], green)
    r.add_triangle([2, -2, -2], [2, 2, 2], [2, -2, 2], green)
    # Ceiling area light
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98, 0.5], light)
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, 0.5], [-0.5, 1.98, 0.5], light)

    r.setup_camera(
        look_from=[0.0, 0.0, 5.5],
        look_at=[0.0, 0.0, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=38.0,
        aspect_ratio=width / height,
        aperture=0.0,
        focus_dist=5.5,
        width=width,
        height=height,
    )


def build_glass_sphere(r, width: int, height: int) -> None:
    """Single glass sphere (IOR=1.5) resting on a white diffuse plane, env-lit."""
    white = r.create_material("lambertian", [0.9, 0.9, 0.9], {})
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.5})

    # Ground plane — two large triangles
    r.add_triangle([-5, -1, -5], [5, -1, -5], [5, -1, 5], white)
    r.add_triangle([-5, -1, -5], [5, -1, 5], [-5, -1, 5], white)

    # Glass sphere sitting on the plane (radius 1, centred at y=0)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, glass)

    r.set_background_color([0.6, 0.7, 0.9])
    r.setup_camera(
        look_from=[0.0, 1.5, 4.5],
        look_at=[0.0, 0.0, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=40.0,
        aspect_ratio=width / height,
        aperture=0.0,
        focus_dist=4.5,
        width=width,
        height=height,
    )


def build_metal_spheres(r, width: int, height: int) -> None:
    """Three metal spheres (gold, silver, copper) on a grey diffuse plane."""
    grey = r.create_material("lambertian", [0.5, 0.5, 0.5], {})
    gold = r.create_material("metal", [1.0, 0.71, 0.29], {"roughness": 0.05})
    silver = r.create_material("metal", [0.95, 0.93, 0.88], {"roughness": 0.05})
    copper = r.create_material("metal", [0.95, 0.64, 0.54], {"roughness": 0.15})

    # Ground plane
    r.add_triangle([-6, -1, -6], [6, -1, -6], [6, -1, 6], grey)
    r.add_triangle([-6, -1, -6], [6, -1, 6], [-6, -1, 6], grey)

    # Three spheres spaced along X
    r.add_sphere([-2.0, 0.0, 0.0], 1.0, gold)
    r.add_sphere([0.0, 0.0, 0.0], 1.0, silver)
    r.add_sphere([2.0, 0.0, 0.0], 1.0, copper)

    r.set_background_color([0.5, 0.6, 0.8])
    r.setup_camera(
        look_from=[0.0, 2.0, 6.0],
        look_at=[0.0, 0.0, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=40.0,
        aspect_ratio=width / height,
        aperture=0.0,
        focus_dist=6.0,
        width=width,
        height=height,
    )


# ---------------------------------------------------------------------------
# Render helper
# ---------------------------------------------------------------------------

SCENES = [
    ("cornell_box", build_cornell_box),
    ("glass_sphere", build_glass_sphere),
    ("metal_spheres", build_metal_spheres),
]


def render_scene(name: str, builder, resolution: int, samples: int,
                 output_dir: Path, max_depth: int = 8) -> tuple[np.ndarray, float]:
    """Build, render, save individual PNG; return (pixels, elapsed_seconds)."""
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_seed(42)
    builder(r, resolution, resolution)

    start = time.perf_counter()
    pixels = np.asarray(r.render(samples, max_depth, None, True), dtype=np.float32)
    elapsed = time.perf_counter() - start

    png_path = output_dir / f"{name}.png"
    _save_png(pixels, png_path)
    return pixels, elapsed


def _save_png(pixels: np.ndarray, path: Path) -> None:
    from PIL import Image
    img_uint8 = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(img_uint8).save(path)


# ---------------------------------------------------------------------------
# Grid composite
# ---------------------------------------------------------------------------

def save_grid(renders: list[tuple[str, np.ndarray, float]], output_dir: Path) -> Path:
    """Save a 1-row × N-column labeled composite grid image."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(renders)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5.5))
    if n == 1:
        axes = [axes]

    for ax, (name, pixels, elapsed) in zip(axes, renders):
        ax.imshow(np.clip(pixels, 0, 1))
        ax.set_title(f"{name}\n{elapsed:.2f}s", fontsize=11)
        ax.axis("off")

    fig.tight_layout()
    grid_path = output_dir / "showcase_grid.png"
    fig.savefig(grid_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return grid_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", type=int, default=512,
                        help="Width and height of each rendered image (default: 512)")
    parser.add_argument("--samples", type=int, default=256,
                        help="Samples per pixel (default: 256)")
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "test_results" / "showcase",
                        help="Directory to write PNGs and the grid (default: test_results/showcase/)")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    renders: list[tuple[str, np.ndarray, float]] = []
    for name, builder in SCENES:
        print(f"Rendering {name} ({args.resolution}×{args.resolution}, {args.samples} spp) …",
              flush=True)
        pixels, elapsed = render_scene(name, builder, args.resolution, args.samples,
                                       args.output_dir)
        renders.append((name, pixels, elapsed))
        print(f"  → {elapsed:.2f}s  ({args.output_dir / (name + '.png')})")

    grid_path = save_grid(renders, args.output_dir)
    print(f"\nGrid saved to {grid_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

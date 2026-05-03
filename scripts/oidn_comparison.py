#!/usr/bin/env python
"""Render a noisy Cornell frame, denoise with OIDN, and save a comparison PNG."""

from __future__ import annotations

import argparse
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


def _cornell_renderer(width: int, height: int):
    r = astroray.Renderer()
    r.setup_camera(
        look_from=[0, 0, 5.5], look_at=[0, 0, 0], vup=[0, 1, 0],
        vfov=40, aspect_ratio=width / height, aperture=0.0, focus_dist=5.5,
        width=width, height=height,
    )
    r.set_background_color([0.0, 0.0, 0.0])

    red = r.create_material("lambertian", [0.65, 0.05, 0.05], {})
    green = r.create_material("lambertian", [0.12, 0.45, 0.15], {})
    white = r.create_material("lambertian", [0.73, 0.73, 0.73], {})
    light = r.create_material("light", [1.0, 0.9, 0.8], {"intensity": 15.0})

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
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98, 0.5], light)
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, 0.5], [-0.5, 1.98, 0.5], light)
    r.add_sphere([0, -1.0, 0], 1.0, white)
    return r


def _local_variance(img: np.ndarray) -> float:
    padded = np.pad(img, ((1, 1), (1, 1), (0, 0)), mode="edge")
    neighbours = np.stack([
        padded[r:r + img.shape[0], c:c + img.shape[1]]
        for r in range(3) for c in range(3)
    ])
    return float(neighbours.var(axis=0).mean())


def _save_png(pixels: np.ndarray, path: Path) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    mapped = np.clip(pixels ** (1.0 / 2.2), 0.0, 1.0)
    Image.fromarray((mapped * 255).astype(np.uint8)).save(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--samples", type=int, default=4)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "test_results" / "oidn_comparison")
    args = parser.parse_args()

    if not bool(astroray.__features__.get("oidn_denoiser", False)):
        print("OIDN is not compiled in; comparison skipped.")
        return 0

    noisy_renderer = _cornell_renderer(args.width, args.height)
    noisy_renderer.set_seed(args.seed)
    noisy = np.asarray(noisy_renderer.render(args.samples, args.max_depth), dtype=np.float32)

    denoised_renderer = _cornell_renderer(args.width, args.height)
    denoised_renderer.set_seed(args.seed)
    denoised_renderer.add_pass("oidn_denoiser")
    denoised = np.asarray(denoised_renderer.render(args.samples, args.max_depth), dtype=np.float32)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    _save_png(noisy, args.output_dir / "oidn_noisy.png")
    _save_png(denoised, args.output_dir / "oidn_denoised.png")

    gap = np.ones((args.height, 8, 3), dtype=np.float32) * 0.75
    comparison = np.concatenate([noisy, gap, denoised], axis=1)
    _save_png(comparison, args.output_dir / "oidn_before_after.png")

    print(f"noisy variance:    {_local_variance(noisy):.6f}")
    print(f"denoised variance: {_local_variance(denoised):.6f}")
    print(f"wrote {args.output_dir / 'oidn_before_after.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

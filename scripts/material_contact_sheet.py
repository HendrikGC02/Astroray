#!/usr/bin/env python
"""Render an evolving material contact sheet for visual inspection.

Line-emitter swatches are diffuse narrowband emitters, not coherent/collimated
laser transport. That harder optics work is tracked separately.
"""

from __future__ import annotations

import argparse
import math
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


MATERIALS = [
    ("lambertian", "lambertian", [0.75, 0.45, 0.25], {}),
    ("metal_smooth", "metal", [0.95, 0.82, 0.42], {"roughness": 0.05}),
    ("metal_rough", "metal", [0.95, 0.64, 0.54], {"roughness": 0.45}),
    ("mirror", "mirror", [1.0, 1.0, 1.0], {}),
    ("glass_flat", "dielectric", [1.0, 1.0, 1.0], {"ior": 1.5}),
    ("glass_bk7", "dielectric", [1.0, 1.0, 1.0], {"sellmeier_preset": "bk7"}),
    ("disney_plastic", "disney", [0.65, 0.22, 0.18], {"roughness": 0.5}),
    ("disney_metal", "disney", [0.9, 0.68, 0.25], {"metallic": 1.0, "roughness": 0.22}),
    ("subsurface", "subsurface", [0.8, 0.35, 0.22], {"scatter_distance": [1.0, 0.35, 0.15], "scale": 1.0}),
    ("emissive", "emissive", [1.0, 0.7, 0.35], {"intensity": 1.4}),
    ("blackbody_2400k", "blackbody", [1.0, 1.0, 1.0], {"temperature_kelvin": 2400.0, "intensity": 0.9}),
    ("blackbody_10000k", "blackbody", [1.0, 1.0, 1.0], {"temperature_kelvin": 10000.0, "intensity": 0.9}),
    ("line_635nm", "line_emitter", [1.0, 1.0, 1.0], {"wavelength_nm": 635.0, "bandwidth_nm": 8.0, "intensity": 1.1}),
    ("line_532nm", "line_emitter", [1.0, 1.0, 1.0], {"wavelength_nm": 532.0, "bandwidth_nm": 8.0, "intensity": 1.1}),
    ("line_460nm", "line_emitter", [1.0, 1.0, 1.0], {"wavelength_nm": 460.0, "bandwidth_nm": 8.0, "intensity": 1.1}),
]


def _save_png(pixels: np.ndarray, path: Path) -> None:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    img_uint8 = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(img_uint8).save(path)


def _add_room(r, width: int, height: int) -> None:
    floor = r.create_material("lambertian", [0.58, 0.58, 0.56], {})
    light = r.create_material("light", [1.0, 0.96, 0.88], {"intensity": 7.0})
    r.add_triangle([-4, -1, -4], [4, -1, -4], [4, -1, 4], floor)
    r.add_triangle([-4, -1, -4], [4, -1, 4], [-4, -1, 4], floor)
    r.add_triangle([-1.3, 3.2, -1.2], [1.3, 3.2, -1.2], [1.3, 3.2, 1.2], light)
    r.add_triangle([-1.3, 3.2, -1.2], [1.3, 3.2, 1.2], [-1.3, 3.2, 1.2], light)
    r.set_background_color([0.06, 0.07, 0.08])
    r.setup_camera(
        look_from=[0.0, 0.55, 4.0],
        look_at=[0.0, -0.05, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=34.0,
        aspect_ratio=width / height,
        aperture=0.0,
        focus_dist=4.0,
        width=width,
        height=height,
    )


def render_tile(name: str, material_type: str, color: list[float], params: dict,
                resolution: int, samples: int, max_depth: int) -> np.ndarray:
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_seed(1000 + sum(ord(c) for c in name))
    _add_room(r, resolution, resolution)
    mat = r.create_material(material_type, color, params)
    r.add_sphere([0.0, 0.0, 0.0], 0.85, mat)
    return np.asarray(r.render(samples, max_depth, None, True), dtype=np.float32)


def save_contact_sheet(renders: list[tuple[str, np.ndarray]], output_dir: Path, columns: int) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = int(math.ceil(len(renders) / columns))
    fig, axes = plt.subplots(rows, columns, figsize=(columns * 2.7, rows * 3.0))
    axes_arr = np.atleast_1d(axes).reshape(rows, columns)
    for ax in axes_arr.flat:
        ax.axis("off")

    for ax, (name, pixels) in zip(axes_arr.flat, renders):
        ax.imshow(np.clip(pixels, 0, 1))
        ax.set_title(name, fontsize=9)
        ax.axis("off")

    fig.tight_layout()
    out = output_dir / "material_contact_sheet.png"
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution", type=int, default=160)
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--max-depth", type=int, default=8)
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "test_results" / "material_contact_sheet")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    renders: list[tuple[str, np.ndarray]] = []
    for name, mat_type, color, params in MATERIALS:
        print(f"Rendering {name} ...", flush=True)
        start = time.perf_counter()
        pixels = render_tile(name, mat_type, color, params,
                             args.resolution, args.samples, args.max_depth)
        _save_png(pixels, args.output_dir / f"{name}.png")
        renders.append((name, pixels))
        print(f"  -> {time.perf_counter() - start:.2f}s")

    sheet = save_contact_sheet(renders, args.output_dir, args.columns)
    print(f"\nContact sheet saved to {sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

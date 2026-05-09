#!/usr/bin/env python
"""Render an evolving material contact sheet for visual inspection.

Line-emitter swatches are diffuse narrowband emitters, not coherent/collimated
laser transport. That harder optics work is tracked separately.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from runtime_setup import configure_test_imports  # noqa: E402

configure_test_imports()

import astroray  # noqa: E402
from _preview_helpers import render_material_preview, save_preview_png  # noqa: E402


MATERIALS = [
    ("lambertian", "lambertian", [0.75, 0.45, 0.25], {}),
    ("metal_smooth", "metal", [0.95, 0.82, 0.42], {"roughness": 0.05}),
    ("metal_rough", "metal", [0.95, 0.64, 0.54], {"roughness": 0.45}),
    ("mirror", "mirror", [1.0, 1.0, 1.0], {}),
    ("glass_flat", "dielectric", [1.0, 1.0, 1.0], {"ior": 1.5}),
    ("glass_bk7", "dielectric", [1.0, 1.0, 1.0], {"sellmeier_preset": "bk7"}),
    ("glass_flint_sf11", "dielectric", [1.0, 1.0, 1.0], {"glass_preset": "flint_sf11"}),
    ("diamond", "dielectric", [1.0, 1.0, 1.0], {"glass_preset": "diamond"}),
    ("ruby", "dielectric", [1.0, 1.0, 1.0], {"glass_preset": "ruby"}),
    ("emerald", "dielectric", [1.0, 1.0, 1.0], {"glass_preset": "emerald"}),
    ("thin_glass_clear", "thin_glass", [1.0, 1.0, 1.0], {"ior": 1.5, "transmission": 1.0}),
    ("thin_glass_blue", "thin_glass", [0.82, 0.93, 1.0], {"ior": 1.52, "transmission": 0.85, "roughness": 0.03}),
    ("disney_glass_r0", "disney", [1.0, 1.0, 1.0], {"transmission": 1.0, "ior": 1.5, "roughness": 0.0}),
    ("disney_glass_r35", "disney", [1.0, 1.0, 1.0], {"transmission": 1.0, "ior": 1.5, "roughness": 0.35}),
    ("disney_glass_r70", "disney", [1.0, 1.0, 1.0], {"transmission": 1.0, "ior": 1.5, "roughness": 0.70}),
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

def _select_device(r, requested: str, caps: dict) -> tuple[str, str]:
    if requested == "cpu":
        return "cpu", "CPU requested"

    gpu_available = bool(getattr(r, "gpu_available", False))
    gpu_name = getattr(r, "gpu_device_name", "unknown GPU")
    if not gpu_available:
        if requested == "gpu":
            raise RuntimeError("GPU was requested, but astroray reports no available GPU renderer")
        return "cpu", "GPU unavailable"
    if not bool(caps.get("gpu", False)):
        reason = str(caps.get("notes", "material is CPU-only"))
        if requested == "gpu":
            raise RuntimeError(f"GPU was requested, but {reason}")
        return "cpu", reason

    try:
        r.set_use_gpu(True)
    except Exception:
        if requested == "gpu":
            raise
        return "cpu", "GPU enable failed; using CPU"
    spectral = "spectral " if bool(caps.get("gpu_spectral", False)) else ""
    mode = f"{spectral}approximate preview" if bool(caps.get("gpu_approximate", False)) else f"{spectral}exact"
    return f"gpu:{gpu_name}", f"{mode} GPU: {caps.get('notes', '')}"


def render_tile(name: str, material_type: str, color: list[float], params: dict,
                resolution: int, samples: int, max_depth: int, device: str) -> tuple[np.ndarray, str, str, dict]:
    r = astroray.Renderer()
    mat = r.create_material(material_type, color, params)
    caps = dict(r.get_material_backend_capabilities(mat))
    device_label, backend_reason = _select_device(r, device, caps)
    pixels = render_material_preview(r, mat, resolution, samples, max_depth)
    return pixels, device_label, backend_reason, caps


def save_stats(stats: list[dict[str, object]], output_dir: Path) -> Path:
    out = output_dir / "material_contact_sheet_stats.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "name",
                "material_type",
                "device",
                "backend_reason",
                "gpu_supported",
                "gpu_spectral",
                "gpu_approximate",
                "gpu_type",
                "capability_notes",
                "seconds",
                "mean_luminance",
                "p99_luminance",
                "max_luminance",
                "nonzero_fraction",
            ],
        )
        writer.writeheader()
        writer.writerows(stats)
    return out


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
    parser.add_argument("--device", choices=["auto", "cpu", "gpu"], default="auto",
                        help="auto uses GPU for material paths with reliable GPU upload support")
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "test_results" / "material_contact_sheet")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    renders: list[tuple[str, np.ndarray]] = []
    stats: list[dict[str, object]] = []
    for name, mat_type, color, params in MATERIALS:
        print(f"Rendering {name} ...", flush=True)
        start = time.perf_counter()
        pixels, device_label, backend_reason, caps = render_tile(
            name, mat_type, color, params,
            args.resolution, args.samples,
            args.max_depth, args.device)
        seconds = time.perf_counter() - start
        save_preview_png(pixels, args.output_dir / f"{name}.png")
        renders.append((name, pixels))
        lum = 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]
        stats.append({
            "name": name,
            "material_type": mat_type,
            "device": device_label,
            "backend_reason": backend_reason,
            "gpu_supported": bool(caps.get("gpu", False)),
            "gpu_spectral": bool(caps.get("gpu_spectral", False)),
            "gpu_approximate": bool(caps.get("gpu_approximate", False)),
            "gpu_type": caps.get("gpu_type", ""),
            "capability_notes": caps.get("notes", ""),
            "seconds": f"{seconds:.4f}",
            "mean_luminance": f"{float(np.mean(lum)):.6f}",
            "p99_luminance": f"{float(np.percentile(lum, 99.0)):.6f}",
            "max_luminance": f"{float(np.max(lum)):.6f}",
            "nonzero_fraction": f"{float(np.count_nonzero(lum > 1e-5) / lum.size):.6f}",
        })
        print(f"  -> {seconds:.2f}s [{device_label}]")

    sheet = save_contact_sheet(renders, args.output_dir, args.columns)
    stats_path = save_stats(stats, args.output_dir)
    print(f"\nContact sheet saved to {sheet}")
    print(f"Stats saved to {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Render Cornell box at 1024 spp for visual validation."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = ROOT / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from runtime_setup import configure_test_imports

configure_test_imports()

import astroray
from tests.scenes.lambertian_cornell import build_scene, setup_camera


def save_png(pixels: np.ndarray, path: Path) -> None:
    from PIL import Image
    pixels_u8 = np.clip(pixels * 255.0, 0, 255).astype(np.uint8)
    Image.fromarray(pixels_u8, mode="RGB").save(path)


def main() -> int:
    output_dir = ROOT / "test_results" / "session_close_2026-05-15"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "cornell_1024spp_gpu.png"

    print("Creating renderer...")
    r = astroray.Renderer()
    
    # Enable GPU if available
    if hasattr(r, "gpu_available") and r.gpu_available:
        try:
            r.set_use_gpu(True)
            print(f"GPU enabled: {r.gpu_device_name if hasattr(r, 'gpu_device_name') else 'unknown GPU'}")
        except Exception as e:
            print(f"GPU enable failed: {e}; using CPU")
    else:
        print("GPU not available; using CPU")

    # Build scene
    print("Building Cornell box scene...")
    build_scene(r)
    setup_camera(r, width=512, height=512)
    
    # Set path tracer integrator
    r.set_integrator("path_tracer")
    r.set_seed(42)

    # Render
    print("Rendering 1024 spp...")
    start = time.perf_counter()
    pixels = np.asarray(r.render(1024, 8, None, False), dtype=np.float32)
    elapsed = time.perf_counter() - start
    print(f"  -> {elapsed:.2f}s")

    # Save
    save_png(pixels, output_path)
    print(f"Saved to {output_path}")

    # Compute stats
    lum = 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]
    print(f"\nLuminance stats:")
    print(f"  Mean: {np.mean(lum):.6f}")
    print(f"  Max:  {np.max(lum):.6f}")
    print(f"  P99:  {np.percentile(lum, 99):.6f}")
    
    # Per-channel stats
    print(f"\nPer-channel mean:")
    print(f"  R: {np.mean(pixels[..., 0]):.6f}")
    print(f"  G: {np.mean(pixels[..., 1]):.6f}")
    print(f"  B: {np.mean(pixels[..., 2]):.6f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

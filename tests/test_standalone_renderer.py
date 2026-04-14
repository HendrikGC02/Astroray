#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test suite for the standalone raytracer C++ executable.

Supported CLI flags (from apps/main.cpp):
  --scene 1|2      1 = Cornell Box (default), 2 = Material Test
  --width N        image width  (default 800)
  --height N       image height (default 600)
  --samples N      samples per pixel (default 64)
  --depth N        max ray depth  (default 50)
  --output FILE    output path (.png or .ppm)
  --help           print usage and exit

Run with:  pytest tests/test_standalone_renderer.py -v
"""

import sys
import os
import subprocess
import time

from PIL import Image
import numpy as np

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BUILD_DIR = os.path.join(os.path.dirname(__file__), '..', 'build')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'test_results')


def _get_exe():
    candidates = [
        os.path.join(BUILD_DIR, 'bin', 'raytracer'),  # Linux-style path
        os.path.join(BUILD_DIR, 'bin', 'raytracer.exe'),  # Windows-style path
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'bin', 'raytracer'),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'bin', 'raytracer.exe'),  # Windows Release folder
        'raytracer',
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    import pytest
    pytest.skip("raytracer executable not found — build the project first")


def _run(args, timeout=120):
    exe = _get_exe()
    result = subprocess.run(
        [exe] + args,
        capture_output=True, text=True, timeout=timeout,
    )
    return result


def _assert_png_valid(path: str, min_mean: float = 0.0) -> np.ndarray:
    """Load a PNG and assert it is a non-trivial image."""
    assert os.path.exists(path), f"Output file not created: {path}"
    img = np.array(Image.open(path)).astype(np.float32) / 255.0
    assert img.ndim == 3 and img.shape[2] == 3, \
        f"Unexpected image shape: {img.shape}"
    mean = float(np.mean(img))
    assert mean > min_mean, \
        f"Image too dark (mean={mean:.4f}); rendering may have failed"
    return img


# ---------------------------------------------------------------------------
# Basic invocation tests
# ---------------------------------------------------------------------------

def test_help():
    """--help should print usage and exit 0."""
    r = _run(['--help'])
    assert r.returncode == 0, f"--help exited {r.returncode}"
    combined = (r.stdout + r.stderr).lower()
    assert any(kw in combined for kw in ('usage', 'scene', 'samples', 'output')), \
        f"--help output missing expected keywords:\n{combined}"


def test_cornell_box_scene():
    """Scene 1 (Cornell Box) should render to a valid PNG."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, 'standalone_cornell_box.png')
    r = _run(['--scene', '1',
              '--width', '200', '--height', '150',
              '--samples', '32',
              '--output', out])
    assert r.returncode == 0, f"Renderer exited {r.returncode}:\n{r.stderr}"
    img = _assert_png_valid(out, min_mean=0.05)
    # Cornell box has red left wall and green right wall — check colour bias
    left  = img[:, :img.shape[1] // 4, :]
    right = img[:, -img.shape[1] // 4:, :]
    assert np.mean(left[:, :, 0]) > np.mean(right[:, :, 0]), \
        "Left side should be redder than right in Cornell box"
    assert np.mean(right[:, :, 1]) > np.mean(left[:, :, 1]), \
        "Right side should be greener than left in Cornell box"


def test_material_test_scene():
    """Scene 2 (Material Test) should render to a valid PNG."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, 'standalone_simple.png')
    r = _run(['--scene', '2',
              '--width', '200', '--height', '150',
              '--samples', '16',
              '--output', out])
    assert r.returncode == 0, f"Renderer exited {r.returncode}:\n{r.stderr}"
    _assert_png_valid(out, min_mean=0.02)


def test_multiple_objects():
    """Material test scene with more samples produces a valid image."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, 'standalone_multiple_objects.png')
    r = _run(['--scene', '2',
              '--width', '200', '--height', '150',
              '--samples', '32',
              '--output', out])
    assert r.returncode == 0, f"Renderer exited {r.returncode}:\n{r.stderr}"
    _assert_png_valid(out, min_mean=0.02)


def test_performance():
    """100-sample Cornell Box render should complete within a reasonable time."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, 'standalone_performance.png')
    t0 = time.time()
    r = _run(['--scene', '1',
              '--width', '200', '--height', '150',
              '--samples', '100',
              '--output', out], timeout=120)
    elapsed = time.time() - t0
    assert r.returncode == 0, f"Renderer exited {r.returncode}:\n{r.stderr}"
    _assert_png_valid(out, min_mean=0.05)
    print(f"\n  Render time: {elapsed:.1f}s")


def test_width_height_respected():
    """Output image dimensions should match --width / --height."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, 'standalone_dimensions.png')
    r = _run(['--scene', '1',
              '--width', '160', '--height', '120',
              '--samples', '8',
              '--output', out])
    assert r.returncode == 0
    img = np.array(Image.open(out))
    assert img.shape[0] == 120, f"Expected height 120, got {img.shape[0]}"
    assert img.shape[1] == 160, f"Expected width 160, got {img.shape[1]}"


def test_higher_samples_closer_to_reference():
    """
    A 64spp render should be closer (lower MSE) to a 256spp reference than
    a 4spp render, demonstrating convergence toward the true image.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    def render_cornell(spp: int, suffix: str) -> np.ndarray:
        out = os.path.join(OUTPUT_DIR, f'standalone_conv_{suffix}.png')
        r = _run(['--scene', '1',
                  '--width', '80', '--height', '60',
                  '--samples', str(spp),
                  '--output', out])
        assert r.returncode == 0
        return np.array(Image.open(out)).astype(np.float32) / 255.0

    ref   = render_cornell(256, 'ref')
    low   = render_cornell(4,   'low')
    high  = render_cornell(64,  'high')

    mse_low  = float(np.mean((low  - ref) ** 2))
    mse_high = float(np.mean((high - ref) ** 2))
    assert mse_high < mse_low, \
        f"64spp should be closer to 256spp reference than 4spp " \
        f"(mse_64={mse_high:.5f} vs mse_4={mse_low:.5f})"


# ---------------------------------------------------------------------------
# Stand-alone entry-point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))

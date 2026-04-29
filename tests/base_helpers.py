#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Base helper functions for raytracer test scripts.
Provides common utilities for renderer creation, scene setup, and image handling.
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for CI/test environments
import matplotlib.pyplot as plt
import sys
import os
from typing import List, Tuple
from pathlib import Path

# Find the built module on either Windows or Linux.
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..')
DEFAULT_BUILD_DIR = os.path.join(PROJECT_ROOT, 'build')


def _candidate_build_dirs() -> list[str]:
    candidates: list[str] = []
    env_dir = os.environ.get('ASTRORAY_BUILD_DIR')
    if env_dir:
        candidates.append(env_dir)
    candidates.extend([
        DEFAULT_BUILD_DIR,
        os.path.join(DEFAULT_BUILD_DIR, 'Release'),
    ])

    seen: set[str] = set()
    existing: list[str] = []
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(candidate).rstrip(os.sep))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isdir(candidate):
            existing.append(candidate)
    return existing


BUILD_DIR_CANDIDATES = _candidate_build_dirs()
for _build_dir in reversed(BUILD_DIR_CANDIDATES):
    sys.path.insert(0, _build_dir)
BUILD_DIR = BUILD_DIR_CANDIDATES[0] if BUILD_DIR_CANDIDATES else DEFAULT_BUILD_DIR
# Also check project root in case module was copied there
sys.path.append(PROJECT_ROOT)


def _candidate_mingw_dirs() -> list[str]:
    candidates: list[str] = []
    env_dir = os.environ.get('MINGW_BIN_DIR')
    if env_dir:
        candidates.append(env_dir)

    for build_dir in BUILD_DIR_CANDIDATES:
        cache_path = Path(build_dir) / 'CMakeCache.txt'
        if not cache_path.exists() and Path(build_dir).name.lower() == 'release':
            cache_path = Path(build_dir).parent / 'CMakeCache.txt'
        if not cache_path.exists():
            continue
        for line in cache_path.read_text(encoding='utf-8', errors='ignore').splitlines():
            prefix = 'CMAKE_CXX_COMPILER:FILEPATH='
            if line.startswith(prefix):
                compiler = Path(line[len(prefix):].strip())
                if compiler.parent:
                    candidates.append(str(compiler.parent))
                break

    candidates.extend([
        r'C:\Program Files\mingw64\bin',
        r'C:\msys64\mingw64\bin',
        r'C:\msys64\ucrt64\bin',
    ])

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        normalized = os.path.normcase(candidate.rstrip(os.sep))
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(candidate)
    return unique


if sys.platform == 'win32' and hasattr(os, 'add_dll_directory'):
    for _dll_dir in _candidate_mingw_dirs():
        if os.path.isdir(_dll_dir):
            os.add_dll_directory(_dll_dir)
    for _build_dir in BUILD_DIR_CANDIDATES:
        os.add_dll_directory(os.path.abspath(_build_dir))

try:
    import astroray
except ImportError as e:
    print(f"✗ Failed to import astroray: {e}")
    print("  Make sure the module is built and in your Python path")
    sys.exit(1)


def create_renderer() -> 'astroray.Renderer':
    """Create and return a new renderer instance with the default path_tracer integrator."""
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    return r


def setup_camera(renderer: 'astroray.Renderer',
                 look_from: List[float] = [0, 0, 5],
                 look_at: List[float] = [0, 0, 0],
                 vup: List[float] = [0, 1, 0],
                 vfov: float = 40,
                 width: int = 400,
                 height: int = 300,
                 aperture: float = 0.0,
                 focus_dist: float = 5.0) -> None:
    """Setup camera with specified parameters"""
    renderer.setup_camera(
        look_from=look_from,
        look_at=look_at,
        vup=vup,
        vfov=vfov,
        aspect_ratio=width / height,
        aperture=aperture,
        focus_dist=focus_dist,
        width=width,
        height=height
    )


def render_image(renderer: 'astroray.Renderer',
                 samples: int = 32,
                 max_depth: int = 8,
                 show_progress: bool = False,
                 apply_gamma: bool = True) -> np.ndarray:
    """Render and return image as numpy array (H x W x 3)."""
    if show_progress:
        def progress_cb(p):
            print(f"\rRendering: {int(p * 100)}%", end="", flush=True)
        pixels = renderer.render(samples, max_depth, progress_cb, apply_gamma)
        print()
    else:
        pixels = renderer.render(samples, max_depth, None, apply_gamma)
    return pixels


def save_image(pixels: np.ndarray, filepath: str) -> None:
    """Save image to PNG file using PIL"""
    from PIL import Image
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    img_uint8 = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(img_uint8).save(filepath)


def save_figure(fig: plt.Figure, filepath: str) -> None:
    """Save matplotlib figure to file"""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    fig.savefig(filepath, dpi=100, bbox_inches='tight')
    plt.close(fig)


def create_cornell_box(renderer: 'astroray.Renderer') -> Tuple[int, int, int]:
    """
    Create a standard Cornell Box scene and return (white_mat, red_mat, green_mat) IDs.
    The Cornell box uses Y-up convention: floor at y=-2, ceiling at y=2.
    Camera should look from z=5.5 toward origin for a proper front-on view.
    """
    red_mat = renderer.create_material('lambertian', [0.65, 0.05, 0.05], {})
    green_mat = renderer.create_material('lambertian', [0.12, 0.45, 0.15], {})
    white_mat = renderer.create_material('lambertian', [0.73, 0.73, 0.73], {})
    light_mat = renderer.create_material('light', [1.0, 0.9, 0.8], {'intensity': 15.0})

    # Floor
    renderer.add_triangle([-2, -2, -2], [2, -2, -2], [2, -2, 2], white_mat)
    renderer.add_triangle([-2, -2, -2], [2, -2, 2], [-2, -2, 2], white_mat)

    # Ceiling
    renderer.add_triangle([-2, 2, -2], [-2, 2, 2], [2, 2, 2], white_mat)
    renderer.add_triangle([-2, 2, -2], [2, 2, 2], [2, 2, -2], white_mat)

    # Back wall
    renderer.add_triangle([-2, -2, -2], [-2, 2, -2], [2, 2, -2], white_mat)
    renderer.add_triangle([-2, -2, -2], [2, 2, -2], [2, -2, -2], white_mat)

    # Left wall (red)
    renderer.add_triangle([-2, -2, -2], [-2, -2, 2], [-2, 2, 2], red_mat)
    renderer.add_triangle([-2, -2, -2], [-2, 2, 2], [-2, 2, -2], red_mat)

    # Right wall (green)
    renderer.add_triangle([2, -2, -2], [2, 2, -2], [2, 2, 2], green_mat)
    renderer.add_triangle([2, -2, -2], [2, 2, 2], [2, -2, 2], green_mat)

    # Ceiling light
    renderer.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98, 0.5], light_mat)
    renderer.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, 0.5], [-0.5, 1.98, 0.5], light_mat)

    return white_mat, red_mat, green_mat


def calculate_image_metrics(image1: np.ndarray,
                            image2: np.ndarray) -> Tuple[float, float]:
    """Calculate MSE and PSNR between two images (both in [0,1])"""
    mse = np.mean((image1 - image2) ** 2)
    if mse == 0:
        return 0.0, float('inf')
    psnr = 20 * np.log10(1.0 / np.sqrt(mse))
    return float(mse), float(psnr)


def assert_valid_image(pixels: np.ndarray, height: int, width: int,
                       min_mean: float = 0.0, max_mean: float = 1.0,
                       min_brightness: float = 0.0,
                       label: str = "image") -> None:
    """Assert that a rendered image has the expected shape and brightness."""
    assert pixels is not None, f"{label}: render returned None"
    assert pixels.shape == (height, width, 3), \
        f"{label}: expected shape ({height}, {width}, 3), got {pixels.shape}"
    assert not np.any(np.isnan(pixels)), f"{label}: contains NaN values"
    assert not np.any(np.isinf(pixels)), f"{label}: contains Inf values"
    mean = float(np.mean(pixels))
    assert mean >= min_mean, f"{label}: mean brightness {mean:.4f} < min {min_mean}"
    assert mean <= max_mean, f"{label}: mean brightness {mean:.4f} > max {max_mean}"
    bright = float(np.max(pixels))
    assert bright >= min_brightness, \
        f"{label}: max brightness {bright:.4f} < min {min_brightness}"


def get_output_dir() -> str:
    """Get the output directory for test results"""
    return os.path.join(os.path.dirname(__file__), '..', 'test_results')

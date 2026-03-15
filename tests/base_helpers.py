#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Base helper functions for raytracer test scripts.
Provides common utilities for renderer creation, scene setup, and image handling.
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import time
import sys
import os
from typing import List, Dict, Tuple, Optional, Callable
import json

# Find the built module on either Windows or Linux
BUILD_DIR = os.path.join(os.path.dirname(__file__), '..', 'build')
sys.path.insert(0, BUILD_DIR)
# Also check project root in case module was copied there
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    import astroray
    print(f"✓ Raytracer module loaded successfully!")
    print(f"  Version: {astroray.__version__}")
    print(f"  Features: {json.dumps(astroray.__features__, indent=2)}")
except ImportError as e:
    print(f"✗ Failed to import astroray: {e}")
    print("  Make sure the module is built and in your Python path")
    sys.exit(1)


def create_renderer() -> 'astroray.Renderer':
    """Create and return a new renderer instance"""
    return astroray.Renderer()


def setup_camera(renderer: 'astroray.Renderer',
                 look_from: List[float] = [0, 0, 5],
                 look_at: List[float] = [0, 0, 0],
                 vup: List[float] = [0, -1, 0],
                 vfov: float = 40,
                 aspect_ratio: float = 1.33,
                 aperture: float = 0.0,
                 focus_dist: float = 5.0,
                 width: int = 400,
                 height: int = 300) -> None:
    """Setup camera with specified parameters"""
    renderer.setup_camera(
        look_from=look_from,
        look_at=look_at,
        vup=vup,
        vfov=vfov,
        aspect_ratio=aspect_ratio,
        aperture=aperture,
        focus_dist=focus_dist,
        width=width,
        height=height
    )


def render_image(renderer: 'astroray.Renderer',
                 samples: int = 32,
                 max_depth: int = 8,
                 show_progress: bool = False,
                 progress_callback: Optional[Callable[[float], None]] = None) -> np.ndarray:
    """Render and return image as numpy array"""
    if show_progress and progress_callback:
        def wrapped_callback(p):
            progress_callback(p)
            print(f"\rRendering: {int(p*100)}%", end="")
        pixels = renderer.render(samples, max_depth, wrapped_callback)
        print()  # New line after progress
    else:
        pixels = renderer.render(samples, max_depth)
    return pixels


def display_image(pixels: np.ndarray,
                  title: str = "Render",
                  figsize: Tuple[int, int] = (8, 6)) -> None:
    """Display rendered image"""
    plt.figure(figsize=figsize)
    plt.imshow(np.clip(pixels, 0, 1))
    plt.title(title)
    plt.axis('off')
    plt.show()


def save_image(pixels: np.ndarray,
               filename: str,
               output_dir: str = "test_results") -> None:
    """Save image to file using PIL"""
    from PIL import Image
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    
    # Convert to uint8
    img_uint8 = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
    
    # Save using PIL
    img = Image.fromarray(img_uint8)
    img.save(filepath)
    print(f"Image saved to {filepath}")


def create_cornell_box(renderer: 'astroray.Renderer',
                       offset: List[float] = [0, 0, 0]) -> Tuple['Material', 'Material', 'Material']:
    """Create a standard Cornell Box scene"""
    # Create materials
    red_mat = astroray.create_material('lambertian', [0.65, 0.05, 0.05], {})
    green_mat = astroray.create_material('lambertian', [0.12, 0.45, 0.15], {})
    white_mat = astroray.create_material('lambertian', [0.73, 0.73, 0.73], {})
    light_mat = astroray.create_material('light', [1.0, 0.9, 0.8], {'intensity': 15.0})
    
    ox, oy, oz = offset
    
    # Floor
    renderer.add_triangle([-2+ox, -2+oy, -2+oz], [2+ox, -2+oy, -2+oz], [2+ox, -2+oy, 2+oz], white_mat)
    renderer.add_triangle([-2+ox, -2+oy, -2+oz], [2+ox, -2+oy, 2+oz], [-2+ox, -2+oy, 2+oz], white_mat)
    
    # Ceiling
    renderer.add_triangle([-2+ox, 2+oy, -2+oz], [-2+ox, 2+oy, 2+oz], [2+ox, 2+oy, 2+oz], white_mat)
    renderer.add_triangle([-2+ox, 2+oy, -2+oz], [2+ox, 2+oy, 2+oz], [2+ox, 2+oy, -2+oz], white_mat)
    
    # Back wall
    renderer.add_triangle([-2+ox, -2+oy, -2+oz], [-2+ox, 2+oy, -2+oz], [2+ox, 2+oy, -2+oz], white_mat)
    renderer.add_triangle([-2+ox, -2+oy, -2+oz], [2+ox, 2+oy, -2+oz], [2+ox, -2+oy, -2+oz], white_mat)
    
    # Left wall (red)
    renderer.add_triangle([-2+ox, -2+oy, -2+oz], [-2+ox, -2+oy, 2+oz], [-2+ox, 2+oy, 2+oz], red_mat)
    renderer.add_triangle([-2+ox, -2+oy, -2+oz], [-2+ox, 2+oy, 2+oz], [-2+ox, 2+oy, -2+oz], red_mat)
    
    # Right wall (green)
    renderer.add_triangle([2+ox, -2+oy, -2+oz], [2+ox, 2+oy, -2+oz], [2+ox, 2+oy, 2+oz], green_mat)
    renderer.add_triangle([2+ox, -2+oy, -2+oz], [2+ox, 2+oy, 2+oz], [2+ox, -2+oy, 2+oz], green_mat)
    
    # Light
    renderer.add_triangle([-0.5+ox, 1.98+oy, -0.5+oz], [0.5+ox, 1.98+oy, -0.5+oz], [0.5+ox, 1.98+oy, 0.5+oz], light_mat)
    renderer.add_triangle([-0.5+ox, 1.98+oy, -0.5+oz], [0.5+ox, 1.98+oy, 0.5+oz], [-0.5+ox, 1.98+oy, 0.5+oz], light_mat)
    
    return white_mat, red_mat, green_mat


def calculate_image_metrics(image1: np.ndarray,
                            image2: np.ndarray) -> Tuple[float, float]:
    """Calculate PSNR and MSE between two images"""
    mse = np.mean((image1 - image2) ** 2)
    if mse == 0:
        psnr = float('inf')
    else:
        max_pixel = 1.0
        psnr = 20 * np.log10(max_pixel / np.sqrt(mse))
    
    return mse, psnr


def get_output_dir() -> str:
    """Get the output directory for test results"""
    return os.path.join(os.path.dirname(__file__), '..', 'test_results')
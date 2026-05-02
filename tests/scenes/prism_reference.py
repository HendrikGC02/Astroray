"""Shared spectral-prism scene for pkg29 validation."""

from __future__ import annotations

import numpy as np


WIDTH = 96
HEIGHT = 96
SAMPLES = 32
MAX_DEPTH = 10


def _add_panel(renderer, material, x0: float, x1: float, z: float) -> None:
    renderer.add_triangle([x0, -1.4, z], [x1, -1.4, z], [x1, 1.4, z], material)
    renderer.add_triangle([x0, -1.4, z], [x1, 1.4, z], [x0, 1.4, z], material)


def add_triangular_prism(renderer, material) -> None:
    """Add a closed triangular glass prism, tall in Y and wedged in X/Z."""
    y0, y1 = -0.9, 0.9
    a = [-0.65, y0, -0.45]
    b = [0.65, y0, -0.45]
    c = [0.0, y0, 0.75]
    d = [-0.65, y1, -0.45]
    e = [0.65, y1, -0.45]
    f = [0.0, y1, 0.75]

    for v0, v1, v2 in [
        (a, b, c), (d, f, e),
        (a, d, e), (a, e, b),
        (b, e, f), (b, f, c),
        (c, f, d), (c, d, a),
    ]:
        renderer.add_triangle(v0, v1, v2, material)


def make_prism_scene(astroray, *, dispersive: bool):
    """Create a compact prism scene with a structured target behind the glass."""
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_background_color([0.8, 0.9, 1.0])

    red = r.create_material("lambertian", [1.0, 0.05, 0.03], {})
    white = r.create_material("lambertian", [0.92, 0.92, 0.90], {})
    blue = r.create_material("lambertian", [0.03, 0.08, 1.0], {})
    light = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 5.0})

    _add_panel(r, red, -2.0, -0.4, -1.79)
    _add_panel(r, white, -0.45, 0.45, -1.80)
    _add_panel(r, blue, 0.4, 2.0, -1.78)

    r.add_triangle([-1.5, 1.6, 1.5], [1.5, 1.6, 1.5], [1.5, 1.6, -1.2], light)
    r.add_triangle([-1.5, 1.6, 1.5], [1.5, 1.6, -1.2], [-1.5, 1.6, -1.2], light)

    glass_params = {"sellmeier_preset": "bk7"} if dispersive else {"ior": 1.5}
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], glass_params)
    add_triangular_prism(r, glass)

    r.setup_camera(
        [0.0, 0.0, 4.2], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
        38.0, 1.0, 0.0, 4.2, WIDTH, HEIGHT)
    return r


def render_prism(astroray, *, dispersive: bool, seed: int = 17) -> np.ndarray:
    renderer = make_prism_scene(astroray, dispersive=dispersive)
    renderer.set_seed(seed)
    return np.asarray(renderer.render(SAMPLES, MAX_DEPTH, None, True), dtype=np.float32)


def red_blue_centroid_separation(pixels: np.ndarray) -> float:
    """Measure lateral split between red- and blue-dominant energy."""
    h, w, _ = pixels.shape
    yy, xx = np.mgrid[:h, :w]
    center_mask = (
        (xx > w * 0.25) & (xx < w * 0.75) &
        (yy > h * 0.20) & (yy < h * 0.80)
    )
    mean = np.mean(pixels, axis=2)

    def centroid(channel: int) -> float:
        weights = np.clip(pixels[:, :, channel] - mean, 0.0, None) * center_mask
        return float(np.sum(weights * xx) / (np.sum(weights) + 1e-6))

    return abs(centroid(0) - centroid(2))

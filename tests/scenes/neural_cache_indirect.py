"""Small indirect-lighting scene used by NRC validation and benchmarks."""

from __future__ import annotations

import numpy as np


def make_renderer(astroray_module, width: int = 32, height: int = 32):
    r = astroray_module.Renderer()
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
    return r


def add_indirect_scene(r, light_intensity: float = 18.0) -> None:
    """Cornell-style scene with colored bounce light and occluded surfaces."""
    white = r.create_material("lambertian", [0.74, 0.74, 0.72], {})
    red = r.create_material("lambertian", [0.72, 0.08, 0.06], {})
    green = r.create_material("lambertian", [0.10, 0.50, 0.16], {})
    blue = r.create_material("lambertian", [0.08, 0.12, 0.68], {})
    light = r.create_material("light", [1.0, 0.96, 0.84], {"intensity": light_intensity})

    # Floor, ceiling, back wall.
    r.add_triangle([-2, -2, -2], [2, -2, -2], [2, -2, 2], white)
    r.add_triangle([-2, -2, -2], [2, -2, 2], [-2, -2, 2], white)
    r.add_triangle([-2, 2, -2], [-2, 2, 2], [2, 2, 2], white)
    r.add_triangle([-2, 2, -2], [2, 2, 2], [2, 2, -2], white)
    r.add_triangle([-2, -2, -2], [-2, 2, -2], [2, 2, -2], white)
    r.add_triangle([-2, -2, -2], [2, 2, -2], [2, -2, -2], white)

    # Colored side walls and a blue bounce card.
    r.add_triangle([-2, -2, -2], [-2, -2, 2], [-2, 2, 2], red)
    r.add_triangle([-2, -2, -2], [-2, 2, 2], [-2, 2, -2], red)
    r.add_triangle([2, -2, -2], [2, 2, -2], [2, 2, 2], green)
    r.add_triangle([2, -2, -2], [2, 2, 2], [2, -2, 2], green)
    r.add_triangle([-0.9, -1.1, -0.25], [0.9, -1.1, -0.25], [0.9, 0.8, -0.25], blue)
    r.add_triangle([-0.9, -1.1, -0.25], [0.9, 0.8, -0.25], [-0.9, 0.8, -0.25], blue)

    # Diffuse subject and a compact ceiling emitter.
    r.add_sphere([0.0, -1.1, 0.55], 0.78, white)
    r.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, -0.35], [0.42, 1.96, 0.35], light)
    r.add_triangle([-0.42, 1.96, -0.35], [0.42, 1.96, 0.35], [-0.42, 1.96, 0.35], light)


def luminance(img: np.ndarray) -> np.ndarray:
    return 0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2]


def mean_luminance(img: np.ndarray) -> float:
    return float(np.mean(luminance(img)))


def mse_luminance(img: np.ndarray, reference: np.ndarray) -> float:
    return float(np.mean((luminance(img) - luminance(reference)) ** 2))


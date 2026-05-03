"""pkg29a validation scenes for spectral caustic transport."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from scenes.prism_reference import add_triangular_prism, red_blue_centroid_separation


WIDTH = 96
HEIGHT = 96
SAMPLES = 24
MAX_DEPTH = 12


@dataclass(frozen=True)
class RenderRecord:
    scene: str
    integrator: str
    pixels: np.ndarray
    seconds: float
    stats: dict[str, float]


def _setup_camera(r, width: int = WIDTH, height: int = HEIGHT) -> None:
    r.setup_camera(
        [0.0, 0.0, 4.2], [0.0, -0.05, 0.0], [0.0, 1.0, 0.0],
        38.0, width / height, 0.0, 4.2, width, height)


def _add_screen(r, z: float = -1.85) -> int:
    white = r.create_material("lambertian", [0.88, 0.88, 0.84], {})
    r.add_triangle([-1.8, -1.15, z], [1.8, -1.15, z], [1.8, 1.15, z], white)
    r.add_triangle([-1.8, -1.15, z], [1.8, 1.15, z], [-1.8, 1.15, z], white)
    return white


def _add_floor(r, y: float = -1.2) -> int:
    floor = r.create_material("lambertian", [0.72, 0.72, 0.68], {})
    r.add_triangle([-2.4, y, -2.2], [2.4, y, -2.2], [2.4, y, 1.6], floor)
    r.add_triangle([-2.4, y, -2.2], [2.4, y, 1.6], [-2.4, y, 1.6], floor)
    return floor


def make_prism_to_screen_scene(astroray):
    r = astroray.Renderer()
    r.set_background_color([0.02, 0.025, 0.03])
    _add_screen(r)

    slit = r.create_material("light", [1.0, 1.0, 1.0], {"intensity": 9.0})
    r.add_triangle([-0.18, 1.22, 1.35], [0.18, 1.22, 1.35], [0.18, 1.40, 1.35], slit)
    r.add_triangle([-0.18, 1.22, 1.35], [0.18, 1.40, 1.35], [-0.18, 1.40, 1.35], slit)

    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"glass_preset": "bk7"})
    add_triangular_prism(r, glass)
    _setup_camera(r)
    return r


def make_glass_caustic_scene(astroray):
    r = astroray.Renderer()
    r.set_background_color([0.02, 0.025, 0.03])
    _add_floor(r)

    light = r.create_material("light", [1.0, 0.97, 0.90], {"intensity": 12.0})
    r.add_sphere([0.0, 1.55, 1.0], 0.22, light)
    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"ior": 1.52})
    r.add_sphere([0.0, -0.35, 0.15], 0.72, glass)
    _setup_camera(r)
    return r


def make_line_emitter_scene(astroray):
    r = astroray.Renderer()
    r.set_background_color([0.01, 0.012, 0.018])
    _add_screen(r)

    line = r.create_material(
        "line_emitter", [1.0, 1.0, 1.0],
        {"wavelength_nm": 532.0, "bandwidth_nm": 8.0, "intensity": 5.0})
    r.add_sphere([-0.45, 0.85, 1.15], 0.12, line)
    glass = r.create_material("thin_glass", [0.92, 1.0, 0.95], {"ior": 1.5, "transmission": 0.96})
    r.add_triangle([-0.85, -0.75, 0.45], [0.85, -0.75, 0.45], [0.85, 0.85, 0.45], glass)
    r.add_triangle([-0.85, -0.75, 0.45], [0.85, 0.85, 0.45], [-0.85, 0.85, 0.45], glass)
    _setup_camera(r)
    return r


SCENES: dict[str, Callable[[object], object]] = {
    "prism_to_screen": make_prism_to_screen_scene,
    "glass_caustic": make_glass_caustic_scene,
    "line_emitter": make_line_emitter_scene,
}


def render_scene(
    astroray,
    scene_name: str,
    integrator: str,
    *,
    samples: int = SAMPLES,
    max_depth: int = MAX_DEPTH,
    seed: int = 145,
) -> RenderRecord:
    r = SCENES[scene_name](astroray)
    r.set_seed(seed)
    if integrator == "caustic_path_tracer":
        r.set_integrator_param("max_depth", max_depth)
        r.set_integrator_param("caustic_chain_iters", 3)
    r.set_integrator(integrator)

    start = time.perf_counter()
    pixels = np.asarray(r.render(samples, max_depth, None, True), dtype=np.float32)
    seconds = time.perf_counter() - start
    stats = {str(k): float(v) for k, v in r.get_integrator_stats().items()}
    return RenderRecord(scene_name, integrator, pixels, seconds, stats)


def image_metrics(pixels: np.ndarray, scene_name: str) -> dict[str, float]:
    lum = 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]
    h, w = lum.shape
    yy, xx = np.mgrid[:h, :w]
    receiver = (xx > w * 0.20) & (xx < w * 0.80) & (yy > h * 0.22) & (yy < h * 0.82)
    out: dict[str, float] = {
        "mean_luminance": float(np.mean(lum)),
        "p99_luminance": float(np.percentile(lum, 99.0)),
        "max_luminance": float(np.max(lum)),
        "receiver_energy": float(np.sum(lum[receiver])),
        "nonzero_fraction": float(np.count_nonzero(lum > 1e-5) / lum.size),
    }
    if scene_name == "prism_to_screen":
        out["red_blue_centroid_spread"] = red_blue_centroid_separation(pixels)
    else:
        out["red_blue_centroid_spread"] = 0.0
    return out

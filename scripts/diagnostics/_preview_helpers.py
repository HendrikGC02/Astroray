"""Shared one-sphere material preview helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def add_preview_scene(renderer, material_id: int, resolution: int, hdri_path: str | Path | None = None) -> None:
    renderer.set_integrator("path_tracer")
    if hasattr(renderer, "set_seed"):
        renderer.set_seed(12661)

    loaded_hdri = False
    if hdri_path and hasattr(renderer, "load_environment_map"):
        try:
            loaded_hdri = bool(renderer.load_environment_map(str(hdri_path), 0.7, 0.0, True))
        except TypeError:
            loaded_hdri = bool(renderer.load_environment_map(str(hdri_path)))
    if not loaded_hdri:
        renderer.set_background_color([0.18, 0.19, 0.21])

    sun = renderer.create_material("light", [1.0, 0.96, 0.88], {"intensity": 2.8})
    if hasattr(renderer, "add_sun_light"):
        renderer.add_sun_light([-0.45, -0.75, -0.48], 0.53, sun)
    else:
        renderer.add_sphere([-1.8, 2.4, 2.1], 0.25, sun)

    renderer.add_sphere([0.0, 0.0, 0.0], 0.9, material_id)
    renderer.setup_camera(
        look_from=[0.0, 0.25, 3.3],
        look_at=[0.0, 0.02, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=32.0,
        aspect_ratio=1.0,
        aperture=0.0,
        focus_dist=3.3,
        width=resolution,
        height=resolution,
    )


def render_material_preview(renderer, material_id: int, resolution: int, samples: int,
                            max_depth: int = 4, hdri_path: str | Path | None = None) -> np.ndarray:
    add_preview_scene(renderer, material_id, resolution, hdri_path)
    return np.asarray(renderer.render(samples, max_depth, None, True), dtype=np.float32)


def save_preview_png(pixels: np.ndarray, path: str | Path) -> Path:
    from PIL import Image

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pixels = np.asarray(pixels, dtype=np.float32)
    img_uint8 = (np.clip(pixels[..., :3], 0.0, 1.0) * 255).astype(np.uint8)
    Image.fromarray(img_uint8).save(out)
    return out

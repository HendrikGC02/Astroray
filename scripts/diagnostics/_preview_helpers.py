"""Shared one-sphere material preview helpers.

Lighting setup mirrors the convention used by Blender's material-preview
system and Substance Designer / Marmoset: an HDRI environment provides the
hemispherical ambient + reflections that reflective and transmissive
materials need to read correctly, plus a single sun key light for crisp
specular highlights and contact shadows. Previously this helper only had
the sun + a dark flat background, which left mirrors/glass/metal tiles
near-black in the contact sheet (silent-drift flag from PR #279 §4 / Round
8 visual validation 2026-05-15). See `test_results/session_close_2026-05-15/
verifier_report.md` for the diagnostic.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

# Default fallback HDRI for the material preview when no caller-supplied
# path is provided. Resolved relative to the repo root (`scripts/diagnostics/
# _preview_helpers.py` -> `parents[2]` is the repo root).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_HDRI = _REPO_ROOT / "samples" / "test_env.hdr"


def add_preview_scene(renderer, material_id: int, resolution: int, hdri_path: str | Path | None = None) -> None:
    renderer.set_integrator("path_tracer")
    if hasattr(renderer, "set_seed"):
        renderer.set_seed(12661)

    # Fall back to the bundled studio-style HDRI for ambient hemispherical
    # illumination if no caller-supplied path is given. Blender, Substance,
    # and Marmoset all default to an HDRI for material previews precisely
    # because reflective and transmissive materials need real ambient
    # information to render meaningfully.
    if not hdri_path and _DEFAULT_HDRI.is_file():
        hdri_path = _DEFAULT_HDRI

    loaded_hdri = False
    if hdri_path and hasattr(renderer, "load_environment_map"):
        # Strength 1.4 calibrated 2026-05-15 against the bundled test_env.hdr
        # to give Lambertian albedo (0.75, 0.45, 0.25) a mean luminance near
        # 0.45 on the contact sheet (was 0.112 with the prior sun-only setup).
        try:
            loaded_hdri = bool(renderer.load_environment_map(str(hdri_path), 1.4, 0.0, True))
        except TypeError:
            loaded_hdri = bool(renderer.load_environment_map(str(hdri_path)))
    if not loaded_hdri:
        # Brighter neutral background when HDRI is unavailable, so transmissive
        # materials at least see something through the glass instead of black.
        renderer.set_background_color([0.55, 0.57, 0.62])

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
                            max_depth: int = 8, hdri_path: str | Path | None = None) -> np.ndarray:
    # Default max_depth bumped 4 -> 8 (2026-05-15): reflective/transmissive
    # materials (mirror, glass, thin_glass, disney_glass, ruby/emerald/diamond)
    # need at least 4-6 bounces through the sphere + environment before the
    # contribution settles. The contact-sheet runner already passes 8; this
    # only changes behaviour for Blender preview callers that use the default.
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

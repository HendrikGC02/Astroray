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


SPECTRAL_WIDTH = 48
SPECTRAL_HEIGHT = 48
SPECTRAL_SAMPLES = 64
SPECTRAL_MAX_DEPTH = 8


def make_spectral_prism_scene(astroray, *, profile_name: str,
                               width: int = SPECTRAL_WIDTH, height: int = SPECTRAL_HEIGHT,
                               light_intensity: float = 90.0):
    """pkg208 -- same panel/prism/camera geometry as make_prism_scene, but lit by
    a spectral point light (measured SPD profile) on the multiwavelength path,
    so the light's own spectrum -- not just a flat RGB colour -- reaches the
    dispersive BK7 dielectric. The point light sits above the prism (same
    position/role as make_prism_scene's overhead area light) with a clear line
    of sight to the panels, so panel illumination is ordinary NEE (no glass in
    the shadow-ray path); only the CAMERA's view of the panels passes through
    the dispersive prism. See .astroray_plan/docs/pkg208-dispersion-oracle-research.md.
    """
    r = astroray.Renderer()
    r.set_use_gpu(False)
    r.set_integrator("multiwavelength_path_tracer")
    r.set_wavelength_range(380.0, 780.0)
    r.set_background_color([0.0, 0.0, 0.0])

    red = r.create_material("lambertian", [1.0, 0.05, 0.03], {})
    white = r.create_material("lambertian", [0.92, 0.92, 0.90], {})
    blue = r.create_material("lambertian", [0.03, 0.08, 1.0], {})

    _add_panel(r, red, -2.0, -0.4, -1.79)
    _add_panel(r, white, -0.45, 0.45, -1.80)
    _add_panel(r, blue, 0.4, 2.0, -1.78)

    r.add_point_light(
        position=[0.0, 1.8, 0.5],
        emission={"mode": "measured_spd", "profile_name": profile_name},
        intensity=light_intensity, radius=0.0)

    glass = r.create_material("dielectric", [1.0, 1.0, 1.0], {"sellmeier_preset": "bk7"})
    add_triangular_prism(r, glass)

    r.setup_camera(
        [0.0, 0.0, 4.2], [0.0, 0.0, 0.0], [0.0, 1.0, 0.0],
        38.0, 1.0, 0.0, 4.2, width, height)
    return r


def render_spectral_prism(astroray, *, profile_name: str, seed: int = 17) -> np.ndarray:
    renderer = make_spectral_prism_scene(astroray, profile_name=profile_name)
    renderer.set_seed(seed)
    pixels = renderer.render(SPECTRAL_SAMPLES, SPECTRAL_MAX_DEPTH, None, False)  # linear
    return np.asarray(pixels, dtype=np.float32)


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


def bright_region_mean_chroma_and_spread(pixels: np.ndarray, bright_percentile: float = 70.0):
    """pkg208 -- mean normalized-RGB chromaticity and its spread over the
    dispersed (bright) part of the panel-through-prism view.

    `red_blue_centroid_separation` above is numerically unstable for this
    oracle's narrow-line case: it centroids on (channel - mean) weights, and
    sodium_vapor's blue channel is ~0 everywhere, so the "blue centroid" is a
    near-0/near-0 division with no real signal (measured ~26px of centroid
    "separation" that is pure noise, larger than the broadband control's,
    inverting the expected relationship -- see
    .astroray_plan/docs/pkg208-dispersion-oracle-research.md). Chromaticity
    spread instead asks a channel-agnostic question: across the pixels that
    the dispersed light actually lit up, how much does the HUE vary?
    A narrow-line illuminant only has energy near one wavelength, so every
    lit pixel -- regardless of the exact exit angle sampled -- comes out
    close to the same hue (small spread). A broadband illuminant spreads many
    different wavelengths (hence hues) across those same pixels (large
    spread) -- the textbook rainbow-fringe. Returns (mean_chroma[3], spread).
    """
    h, w, _ = pixels.shape
    yy, xx = np.mgrid[:h, :w]
    center_mask = (
        (xx > w * 0.25) & (xx < w * 0.75) &
        (yy > h * 0.20) & (yy < h * 0.80)
    )
    luminance = pixels.mean(axis=2)
    threshold = np.percentile(luminance[center_mask], bright_percentile)
    bright = center_mask & (luminance > threshold) & (luminance > 1e-4)
    if not np.any(bright):
        return np.zeros(3, dtype=np.float64), 0.0

    total = np.maximum(pixels.sum(axis=2, keepdims=True), 1e-8)
    chroma = (pixels / total)[bright]  # (N, 3) normalized RGB per bright pixel
    mean_chroma = chroma.mean(axis=0)
    spread = float(np.linalg.norm(chroma - mean_chroma, axis=1).mean())
    return mean_chroma, spread

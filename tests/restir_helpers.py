"""
Shared helpers for ReSTIR validation tests (pkg24).

Provides scene builders, render wrappers, and image-quality metrics used
across test_restir_validation.py and any future ReSTIR test files.
"""

import numpy as np


# ---------------------------------------------------------------------------
# Scene builders
# ---------------------------------------------------------------------------

def make_renderer(astroray_module, width=32, height=32,
                  look_from=None, look_at=None):
    """Create a Renderer with a standard camera."""
    if look_from is None:
        look_from = [0, 0, 5.5]
    if look_at is None:
        look_at = [0, 0, 0]
    r = astroray_module.Renderer()
    r.setup_camera(
        look_from=look_from, look_at=look_at, vup=[0, 1, 0],
        vfov=45, aspect_ratio=1.0, aperture=0.0, focus_dist=5.5,
        width=width, height=height,
    )
    return r


def build_cornell_box(r, light_intensity=15.0):
    """Minimal Cornell box: 5 diffuse walls + one ceiling area light."""
    white = r.create_material("lambertian", [0.73, 0.73, 0.73], {})
    red   = r.create_material("lambertian", [0.65, 0.05, 0.05], {})
    green = r.create_material("lambertian", [0.12, 0.45, 0.15], {})
    light = r.create_material("light", [1.0, 0.9, 0.8],
                              {"intensity": light_intensity})

    # Floor + ceiling
    r.add_triangle([-2, -2, -2], [2, -2, -2], [2, -2,  2], white)
    r.add_triangle([-2, -2, -2], [2, -2,  2], [-2, -2, 2], white)
    r.add_triangle([-2,  2, -2], [-2, 2,  2], [2,  2,  2], white)
    r.add_triangle([-2,  2, -2], [2,  2,  2], [2,  2, -2], white)
    # Back wall
    r.add_triangle([-2, -2, -2], [-2, 2, -2], [2,  2, -2], white)
    r.add_triangle([-2, -2, -2], [2,  2, -2], [2, -2, -2], white)
    # Left (red) + right (green) walls
    r.add_triangle([-2, -2, -2], [-2, -2, 2], [-2, 2,  2], red)
    r.add_triangle([-2, -2, -2], [-2,  2, 2], [-2, 2, -2], red)
    r.add_triangle([2,  -2, -2], [2,   2, -2], [2, 2,  2], green)
    r.add_triangle([2,  -2, -2], [2,   2,  2], [2, -2, 2], green)
    # Ceiling light
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98, 0.5], light)
    r.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98,  0.5], [-0.5, 1.98, 0.5], light)


def build_many_light_scene(r, n_lights=5, light_intensity=8.0):
    """Diffuse floor + N small ceiling lights at regular intervals."""
    white = r.create_material("lambertian", [0.73, 0.73, 0.73], {})
    light = r.create_material("light", [1.0, 0.9, 0.8],
                              {"intensity": light_intensity})
    # Floor
    r.add_triangle([-3, -1, -3], [3, -1, -3], [3, -1, 3], white)
    r.add_triangle([-3, -1, -3], [3, -1,  3], [-3, -1, 3], white)
    # Lights spread along x-axis
    for i in range(n_lights):
        lx = -2.0 + 4.0 * i / max(n_lights - 1, 1)
        r.add_triangle([lx - 0.25, 2.0, -0.25], [lx + 0.25, 2.0, -0.25],
                       [lx + 0.25, 2.0,  0.25], light)
        r.add_triangle([lx - 0.25, 2.0, -0.25], [lx + 0.25, 2.0,  0.25],
                       [lx - 0.25, 2.0,  0.25], light)


# ---------------------------------------------------------------------------
# Render wrappers
# ---------------------------------------------------------------------------

def render(r, integrator, samples=16, seed=42, max_depth=8,
           use_temporal=False, use_spatial=False,
           spatial_radius=5, spatial_neighbors=5):
    """Set integrator + parameters and render; return float32 numpy array."""
    # Always set params before creating the integrator so previous values don't leak.
    r.set_integrator_param("use_temporal",       1 if use_temporal else 0)
    r.set_integrator_param("use_spatial",        1 if use_spatial  else 0)
    r.set_integrator_param("spatial_radius",     spatial_radius)
    r.set_integrator_param("spatial_neighbors",  spatial_neighbors)
    r.set_integrator(integrator)
    r.set_seed(seed)
    return np.array(r.render(samples_per_pixel=samples, max_depth=max_depth),
                    dtype=np.float32)


def render_sequence(astroray_module, scene_fn, integrator, n_frames,
                    width=32, height=32, samples_per_frame=1, seed=42,
                    use_temporal=False, use_spatial=False):
    """
    Render the same static scene n_frames times with a persistent renderer,
    accumulating a list of per-frame images. Used to measure temporal reuse.
    """
    r = make_renderer(astroray_module, width=width, height=height)
    scene_fn(r)
    # Params must be set before set_integrator so the integrator is created with them.
    r.set_integrator_param("use_temporal", 1 if use_temporal else 0)
    r.set_integrator_param("use_spatial",  1 if use_spatial  else 0)
    r.set_integrator(integrator)
    frames = []
    for i in range(n_frames):
        r.set_seed(seed + i)
        frames.append(np.array(
            r.render(samples_per_pixel=samples_per_frame, max_depth=8),
            dtype=np.float32))
    return frames


def render_warmed(astroray_module, scene_fn, integrator, warmup_frames,
                  measure_frames, width=32, height=32, samples=8, seed=42,
                  use_temporal=False, use_spatial=False):
    """
    Render warmup_frames to populate the history buffer, then render
    measure_frames and return those images. Suitable for testing reuse that
    depends on prior-frame data.
    """
    r = make_renderer(astroray_module, width=width, height=height)
    scene_fn(r)
    r.set_integrator_param("use_temporal", 1 if use_temporal else 0)
    r.set_integrator_param("use_spatial",  1 if use_spatial  else 0)
    r.set_integrator(integrator)
    for i in range(warmup_frames):
        r.set_seed(seed + i)
        r.render(samples_per_pixel=samples, max_depth=8)
    frames = []
    for i in range(measure_frames):
        r.set_seed(seed + warmup_frames + i)
        frames.append(np.array(
            r.render(samples_per_pixel=samples, max_depth=8),
            dtype=np.float32))
    return frames


# ---------------------------------------------------------------------------
# Image metrics
# ---------------------------------------------------------------------------

def mean_luminance(img):
    """Mean of the Y-channel proxy (0.2126R + 0.7152G + 0.0722B)."""
    return float(np.mean(0.2126 * img[..., 0] +
                         0.7152 * img[..., 1] +
                         0.0722 * img[..., 2]))


def pixel_stddev(frames):
    """Per-pixel standard deviation across a list of frames, averaged spatially."""
    stack = np.stack(frames, axis=0)   # (N, H, W, 3)
    lum = (0.2126 * stack[..., 0] +
           0.7152 * stack[..., 1] +
           0.0722 * stack[..., 2])     # (N, H, W)
    return float(np.mean(np.std(lum, axis=0)))


def mse(img_a, img_b):
    """Mean squared error between two images (luminance channel)."""
    la = 0.2126 * img_a[..., 0] + 0.7152 * img_a[..., 1] + 0.0722 * img_a[..., 2]
    lb = 0.2126 * img_b[..., 0] + 0.7152 * img_b[..., 1] + 0.0722 * img_b[..., 2]
    return float(np.mean((la - lb) ** 2))


def relative_mean_diff(img_a, img_b):
    """
    Relative difference in mean luminance: |mean(a) - mean(b)| / mean(a).
    Returns 0 when mean(a) == 0.
    """
    ma = mean_luminance(img_a)
    mb = mean_luminance(img_b)
    if ma < 1e-8:
        return 0.0
    return abs(ma - mb) / ma

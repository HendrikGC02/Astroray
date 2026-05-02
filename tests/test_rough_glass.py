"""Focused coverage for Disney/Principled rough dielectric transmission."""

import os

import numpy as np
import pytest

from runtime_setup import configure_test_imports

configure_test_imports()

try:
    import astroray
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

from base_helpers import assert_valid_image, save_image  # noqa: E402

pytestmark = pytest.mark.skipif(not AVAILABLE, reason="astroray module not available")


W, H = 128, 96


def _setup_camera(r):
    r.setup_camera(
        look_from=[0.0, 0.0, 3.8],
        look_at=[0.0, 0.0, 0.0],
        vup=[0.0, 1.0, 0.0],
        vfov=36.0,
        aspect_ratio=W / H,
        aperture=0.0,
        focus_dist=3.8,
        width=W,
        height=H,
    )


def _backdrop_scene(r, mat):
    red = r.create_material("lambertian", [0.9, 0.12, 0.08], {})
    green = r.create_material("lambertian", [0.08, 0.85, 0.16], {})
    white = r.create_material("lambertian", [0.78, 0.78, 0.74], {})
    light = r.create_material("light", [1.0, 0.96, 0.88], {"intensity": 10.0})

    # Split-color back wall so rough transmission has visible structure to blur.
    r.add_triangle([-3, -2, -2.6], [0, -2, -2.6], [0, 2, -2.6], red)
    r.add_triangle([-3, -2, -2.6], [0, 2, -2.6], [-3, 2, -2.6], red)
    r.add_triangle([0, -2, -2.6], [3, -2, -2.6], [3, 2, -2.6], green)
    r.add_triangle([0, -2, -2.6], [3, 2, -2.6], [0, 2, -2.6], green)

    r.add_triangle([-3, -1.15, -4], [3, -1.15, -4], [3, -1.15, 2], white)
    r.add_triangle([-3, -1.15, -4], [3, -1.15, 2], [-3, -1.15, 2], white)
    r.add_triangle([-0.9, 3.1, -0.9], [0.9, 3.1, -0.9], [0.9, 3.1, 0.9], light)
    r.add_triangle([-0.9, 3.1, -0.9], [0.9, 3.1, 0.9], [-0.9, 3.1, 0.9], light)
    r.add_sphere([0.0, 0.0, 0.0], 0.92, mat)
    r.set_background_color([0.0, 0.0, 0.0])
    _setup_camera(r)


def _render_disney_glass(roughness, seed=123):
    r = astroray.Renderer()
    r.set_integrator("path_tracer")
    r.set_seed(seed)
    r.set_adaptive_sampling(False)
    mat = r.create_material(
        "disney",
        [1.0, 1.0, 1.0],
        {"transmission": 1.0, "ior": 1.5, "roughness": roughness},
    )
    _backdrop_scene(r, mat)
    return np.asarray(r.render(72, 8, None, True), dtype=np.float32)


def _center(img, frac=0.48):
    h, w, _ = img.shape
    y0 = int(h * (0.5 - frac / 2.0))
    y1 = int(h * (0.5 + frac / 2.0))
    x0 = int(w * (0.5 - frac / 2.0))
    x1 = int(w * (0.5 + frac / 2.0))
    return img[y0:y1, x0:x1]


def test_rough_disney_glass_remains_transmissive_and_bounded(test_results_dir):
    smooth = _render_disney_glass(0.0)
    rough = _render_disney_glass(0.65)
    save_image(smooth, os.path.join(test_results_dir, "rough_glass_disney_smooth.png"))
    save_image(rough, os.path.join(test_results_dir, "rough_glass_disney_r065.png"))

    assert_valid_image(smooth, H, W, min_mean=0.02, label="smooth_disney_glass")
    assert_valid_image(rough, H, W, min_mean=0.02, label="rough_disney_glass")
    assert np.isfinite(rough).all()

    center = _center(rough)
    assert float(np.mean(center)) > 0.08, "rough Disney glass should not collapse to black"
    assert float(np.mean(rough)) < 0.90, "rough Disney glass should remain energy-bounded"


def test_roughness_changes_transmitted_structure(test_results_dir):
    smooth = _render_disney_glass(0.0, seed=321)
    mid = _render_disney_glass(0.35, seed=321)
    rough = _render_disney_glass(0.75, seed=321)
    save_image(mid, os.path.join(test_results_dir, "rough_glass_disney_r035.png"))
    save_image(rough, os.path.join(test_results_dir, "rough_glass_disney_r075.png"))

    smooth_center = _center(smooth)
    mid_center = _center(mid)
    rough_center = _center(rough)

    mse_smooth_mid = float(np.mean((smooth_center - mid_center) ** 2))
    mse_mid_rough = float(np.mean((mid_center - rough_center) ** 2))
    assert mse_smooth_mid > 2e-4, f"roughness 0.0 vs 0.35 too similar: {mse_smooth_mid:.6f}"
    assert mse_mid_rough > 8e-5, f"roughness 0.35 vs 0.75 too similar: {mse_mid_rough:.6f}"

    rough_mean = float(np.mean(rough_center))
    assert 0.05 < rough_mean < 0.85, (
        f"rough glass center should stay visible and bounded, got mean={rough_mean:.5f}"
    )

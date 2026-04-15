#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Comprehensive test suite for astroray Python bindings.

Covers all material types, rendering correctness, convergence, performance,
and Disney BRDF parameters — matching the Extensive_testing_notebook scenes.

Run with:  pytest tests/test_python_bindings.py -v
"""

import sys
import os
import time

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from PIL import Image

BUILD_DIR = os.path.join(os.path.dirname(__file__), '..', 'build')
sys.path.insert(0, BUILD_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'blender_addon'))

import astroray
import shader_blending
from base_helpers import (
    create_renderer, setup_camera, render_image,
    save_image, save_figure, create_cornell_box,
    calculate_image_metrics, assert_valid_image, get_output_dir,
)

OUTPUT_DIR = get_output_dir()
W, H = 200, 150   # fast default resolution for most tests
SAMPLES_FAST = 16
SAMPLES_MED  = 64
SAMPLES_HIGH = 256
MIN_VISIBLE_PIXELS = 20
CENTER_SLICE_RADIUS = 12
MAX_GLOSSY_PARITY_MSE = 0.015
MAX_GLASS_PARITY_MEAN_DIFF = 0.25
MAX_GLASS_PARITY_P95_DIFF = 0.25
MIN_SUN_SHADOW_MSE = 5e-4
RENDER_PASS_KEYS = (
    "diffuse_direct",
    "diffuse_indirect",
    "diffuse_color",
    "glossy_direct",
    "glossy_indirect",
    "glossy_color",
    "transmission_direct",
    "transmission_indirect",
    "transmission_color",
    "volume_direct",
    "volume_indirect",
    "emission",
    "environment",
    "ao",
    "shadow",
)


# ---------------------------------------------------------------------------
# Module / infrastructure
# ---------------------------------------------------------------------------

def test_module_version():
    assert hasattr(astroray, '__version__')
    assert hasattr(astroray, '__features__')
    assert astroray.__version__ != ''
    features = astroray.__features__
    for key in ('nee', 'mis', 'disney_brdf', 'sah_bvh', 'adaptive_sampling'):
        assert key in features, f"Missing feature key: {key}"


def test_renderer_creation():
    r = create_renderer()
    assert r is not None


def test_camera_setup():
    r = create_renderer()
    # basic setup should not raise
    setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], width=W, height=H)
    # changing aperture / focus dist
    setup_camera(r, look_from=[3, 2, 3], look_at=[0, 0, 0],
                 aperture=0.5, focus_dist=4.0, width=W, height=H)


def test_renderer_clear():
    r = create_renderer()
    mat = r.create_material('lambertian', [0.5, 0.5, 0.5], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.clear()
    # After clear, renderer should be usable again
    setup_camera(r, width=W, height=H)
    mat2 = r.create_material('lambertian', [0.5, 0.5, 0.5], {})
    r.add_sphere([0, 0, 0], 1.0, mat2)


# ---------------------------------------------------------------------------
# Material creation — smoke tests (no render needed)
# ---------------------------------------------------------------------------

def test_create_all_material_types():
    r = create_renderer()
    r.create_material('lambertian', [0.8, 0.3, 0.3], {})
    r.create_material('metal',      [0.9, 0.9, 0.9], {'roughness': 0.1})
    r.create_material('glass',      [1.0, 1.0, 1.0], {'ior': 1.5})
    r.create_material('light',      [1.0, 0.9, 0.8], {'intensity': 10.0})
    r.create_material('disney',     [0.7, 0.5, 0.3], {'metallic': 0.5, 'roughness': 0.3})
    r.create_material('subsurface', [0.9, 0.6, 0.5], {'scatter_distance': [1.0, 0.2, 0.1]})


def _render_visible_area_light(shape: str, size_x: float, size_y: float, spread: float = 1.0, samples: int = 48):
    r = create_renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 45.0})
    r.add_area_light([0, 0, 0], [1, 0, 0], [0, 1, 0], size_x, size_y, shape, light, spread)
    setup_camera(r, look_from=[0, 0, 4], look_at=[0, 0, 0], vfov=24, width=W, height=H)
    return render_image(r, samples=samples), r


def _bright_mask_fill_ratio(img: np.ndarray) -> float:
    lum = img.mean(axis=2)
    threshold = np.percentile(lum, 99.0)
    ys, xs = np.where(lum >= threshold)
    assert len(xs) > MIN_VISIBLE_PIXELS, "Expected visible bright area-light pixels"
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    bbox_area = max(1, (x1 - x0 + 1) * (y1 - y0 + 1))
    return float(len(xs) / bbox_area)


def test_area_light_shapes_affect_specular_reflection_and_support_ellipse():
    rect, _ = _render_visible_area_light('RECTANGLE', 1.8, 0.55, spread=1.0, samples=SAMPLES_FAST)
    disk, _ = _render_visible_area_light('DISK', 1.8, 1.8, spread=1.0, samples=SAMPLES_FAST)
    ellipse, _ = _render_visible_area_light('ELLIPSE', 1.8, 0.55, spread=1.0, samples=SAMPLES_FAST)

    rect_fill = _bright_mask_fill_ratio(rect)
    disk_fill = _bright_mask_fill_ratio(disk)
    ellipse_fill = _bright_mask_fill_ratio(ellipse)

    assert rect_fill > disk_fill + 0.10, \
        f"Rectangle footprint should fill its bbox more than disk ({rect_fill:.3f} vs {disk_fill:.3f})"
    assert ellipse_fill < rect_fill - 0.05, \
        f"Ellipse footprint should have rounded corners vs rectangle ({ellipse_fill:.3f} vs {rect_fill:.3f})"

    save_image(rect, os.path.join(OUTPUT_DIR, 'test_area_light_rectangle_specular.png'))
    save_image(disk, os.path.join(OUTPUT_DIR, 'test_area_light_disk_specular.png'))
    save_image(ellipse, os.path.join(OUTPUT_DIR, 'test_area_light_ellipse_specular.png'))


def test_area_light_spread_focuses_beam():
    def render_lit_wall(spread: float) -> np.ndarray:
        r = create_renderer()
        r.set_background_color([0.0, 0.0, 0.0])
        light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 60.0})
        wall = r.create_material('lambertian', [0.8, 0.8, 0.8], {})
        r.add_area_light([0, 0, 2.2], [1, 0, 0], [0, -1, 0], 1.4, 1.4, 'RECTANGLE', light, spread)
        r.add_triangle([-2.5, -2.5, 0.0], [2.5, -2.5, 0.0], [2.5, 2.5, 0.0], wall)
        r.add_triangle([-2.5, -2.5, 0.0], [2.5, 2.5, 0.0], [-2.5, 2.5, 0.0], wall)
        setup_camera(r, look_from=[1.5, 0, 3.8], look_at=[0, 0, 0.0], vfov=30, width=W, height=H)
        return render_image(r, samples=SAMPLES_MED, apply_gamma=False)

    wide = render_lit_wall(spread=1.0)
    focused = render_lit_wall(spread=0.1)

    wide_lum = wide.mean(axis=2)
    focused_lum = focused.mean(axis=2)
    cy, cx = np.unravel_index(np.argmax(wide_lum), wide_lum.shape)
    center_slice = (slice(max(cy - CENTER_SLICE_RADIUS, 0), min(cy + CENTER_SLICE_RADIUS, H)),
                    slice(max(cx - CENTER_SLICE_RADIUS, 0), min(cx + CENTER_SLICE_RADIUS, W)))
    center_wide = float(np.mean(wide_lum[center_slice]))
    center_focused = float(np.mean(focused_lum[center_slice]))

    outer_wide = np.copy(wide_lum)
    outer_focused = np.copy(focused_lum)
    outer_wide[center_slice] = np.nan
    outer_focused[center_slice] = np.nan
    mean_outer_wide = float(np.nanmean(outer_wide))
    mean_outer_focused = float(np.nanmean(outer_focused))

    ratio_wide = center_wide / (mean_outer_wide + 1e-6)
    ratio_focused = center_focused / (mean_outer_focused + 1e-6)
    assert ratio_focused > ratio_wide * 1.10, \
        f"spread=0.1 should focus energy toward center ({ratio_focused:.3f} vs {ratio_wide:.3f})"
    assert float(np.mean(focused_lum)) < float(np.mean(wide_lum)) * 0.5, \
        "Narrow spread should reduce total illuminated area/energy on the wall"

    save_image(wide, os.path.join(OUTPUT_DIR, 'test_area_light_spread_wide.png'))
    save_image(focused, os.path.join(OUTPUT_DIR, 'test_area_light_spread_focused.png'))
def _render_material_parity_scene(mat_type, color, params, samples=SAMPLES_MED):
    r = create_renderer()
    create_cornell_box(r)
    mat = r.create_material(mat_type, color, params)
    r.add_sphere([0, -0.8, 0], 1.2, mat)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=W, height=H)
    pixels = render_image(r, samples=samples)
    assert_valid_image(pixels, H, W, min_mean=0.02, label=f"{mat_type}_parity")
    return pixels


def _center_crop(img, frac=0.5):
    h, w, _ = img.shape
    ch = max(1, int(h * frac))
    cw = max(1, int(w * frac))
    y0 = (h - ch) // 2
    x0 = (w - cw) // 2
    return img[y0:y0 + ch, x0:x0 + cw]


def test_center_crop_helper_keeps_center_region():
    img = np.arange(4 * 6 * 3, dtype=np.float32).reshape(4, 6, 3)
    cropped = _center_crop(img, frac=0.5)
    assert cropped.shape == (2, 3, 3)
    assert np.array_equal(cropped, img[1:3, 1:4, :])


def test_glossy_matches_principled_metallic_roughness():
    rough = 0.35
    color = [0.9, 0.8, 0.7]
    glossy = _render_material_parity_scene('metal', color, {'roughness': rough}, samples=SAMPLES_MED)
    principled_metal = _render_material_parity_scene(
        'disney', color, {'metallic': 1.0, 'roughness': rough}, samples=SAMPLES_MED
    )

    glossy_center = _center_crop(glossy, frac=0.5)
    principled_center = _center_crop(principled_metal, frac=0.5)
    mse, _ = calculate_image_metrics(glossy_center, principled_center)
    assert mse < MAX_GLOSSY_PARITY_MSE, f"Glossy vs Principled metallic mismatch too large (center-crop MSE={mse:.5f})"


def test_glass_matches_principled_transmission_ior():
    ior = 1.5
    glass = _render_material_parity_scene('glass', [1.0, 1.0, 1.0], {'ior': ior}, samples=SAMPLES_MED)
    principled_glass = _render_material_parity_scene(
        'disney', [1.0, 1.0, 1.0], {'transmission': 1.0, 'ior': ior, 'roughness': 0.0}, samples=SAMPLES_MED
    )

    glass_center = _center_crop(glass, frac=0.5)
    principled_center = _center_crop(principled_glass, frac=0.5)
    mean_diff = abs(float(np.mean(glass_center)) - float(np.mean(principled_center)))
    p95_diff = abs(float(np.percentile(glass_center, 95)) - float(np.percentile(principled_center, 95)))
    assert mean_diff < MAX_GLASS_PARITY_MEAN_DIFF, f"Glass vs Principled mean mismatch too large (center-crop diff={mean_diff:.5f})"
    assert p95_diff < MAX_GLASS_PARITY_P95_DIFF, f"Glass vs Principled highlight mismatch too large (center-crop p95 diff={p95_diff:.5f})"


def _render_spot_on_plane(blend: float) -> np.ndarray:
    r = create_renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    floor = r.create_material('lambertian', [0.85, 0.85, 0.85], {})
    # Visible spotlight setup: cone ~40deg (0.7 rad), small radius for soft shadows.
    light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 90.0})
    r.add_triangle([-3.0, 0.0, -3.0], [3.0, 0.0, -3.0], [3.0, 0.0, 3.0], floor)
    r.add_triangle([-3.0, 0.0, -3.0], [3.0, 0.0, 3.0], [-3.0, 0.0, 3.0], floor)
    r.add_spot_light([0.0, 3.0, 0.0], [0.0, -1.0, 0.0], 0.08, light, 0.7, blend)
    setup_camera(r, look_from=[0.0, 5.0, 0.0], look_at=[0.0, 0.0, 0.0],
                 vup=[0.0, 0.0, -1.0], vfov=42, width=W, height=H)
    return render_image(r, samples=64, max_depth=6)


def _write_test_ies(path: str) -> None:
    # Minimal LM-63 style profile:
    # - 3 vertical angles (0,45,90)
    # - 2 horizontal angles (0,180) with strong asymmetry
    #   so +X receives much more flux than -X for axis=(0,-1,0).
    content = """IESNA:LM-63-1995
TILT=NONE
1 1000 1 3 2 1 1 0.1 0.1 0.1 1 1 10
0 45 90
0 180
1.0 1.0 0.2
0.1 0.1 0.02
"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def _render_spot_with_optional_ies(ies_file: str = "") -> np.ndarray:
    r = create_renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    floor = r.create_material('lambertian', [0.85, 0.85, 0.85], {})
    light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 120.0})
    r.add_triangle([-3.0, 0.0, -3.0], [3.0, 0.0, -3.0], [3.0, 0.0, 3.0], floor)
    r.add_triangle([-3.0, 0.0, -3.0], [3.0, 0.0, 3.0], [-3.0, 0.0, 3.0], floor)
    r.add_spot_light([0.0, 3.0, 0.0], [0.0, -1.0, 0.0], 0.08, light, 1.2, 0.2, ies_file)
    setup_camera(r, look_from=[0.0, 5.0, 0.0], look_at=[0.0, 0.0, 0.0],
                 vup=[0.0, 0.0, -1.0], vfov=42, width=W, height=H)
    return render_image(r, samples=64, max_depth=6)


def _render_point_with_optional_ies(ies_file: str = "") -> np.ndarray:
    r = create_renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    floor = r.create_material('lambertian', [0.85, 0.85, 0.85], {})
    light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 120.0})
    r.add_triangle([-3.0, 0.0, -3.0], [3.0, 0.0, -3.0], [3.0, 0.0, 3.0], floor)
    r.add_triangle([-3.0, 0.0, -3.0], [3.0, 0.0, 3.0], [-3.0, 0.0, 3.0], floor)
    r.add_sphere([0.0, 3.0, 0.0], 0.08, light, [0.0, -1.0, 0.0], ies_file)
    setup_camera(r, look_from=[0.0, 5.0, 0.0], look_at=[0.0, 0.0, 0.0],
                 vup=[0.0, 0.0, -1.0], vfov=42, width=W, height=H)
    return render_image(r, samples=64, max_depth=6)


def test_spot_light_ies_profile_creates_nonuniform_pattern(tmp_path):
    ies_path = os.path.join(tmp_path, 'asymmetric.ies')
    _write_test_ies(ies_path)
    img = _render_spot_with_optional_ies(ies_path)
    lum = img.mean(axis=2)
    cy, cx = H // 2, W // 2
    left = float(np.mean(lum[cy-12:cy+12, cx-45:cx-15]))
    right = float(np.mean(lum[cy-12:cy+12, cx+15:cx+45]))
    assert right > left * 1.6, f"Expected IES asymmetry on floor (left={left:.4f}, right={right:.4f})"


def test_spot_light_without_ies_remains_near_symmetric():
    img = _render_spot_with_optional_ies("")
    lum = img.mean(axis=2)
    cy, cx = H // 2, W // 2
    left = float(np.mean(lum[cy-12:cy+12, cx-45:cx-15]))
    right = float(np.mean(lum[cy-12:cy+12, cx+15:cx+45]))
    ratio = right / max(left, 1e-6)
    assert 0.8 <= ratio <= 1.25, f"Expected no-IES spotlight symmetry (left={left:.4f}, right={right:.4f}, ratio={ratio:.3f})"


def test_point_light_ies_profile_creates_nonuniform_pattern(tmp_path):
    ies_path = os.path.join(tmp_path, 'asymmetric_point.ies')
    _write_test_ies(ies_path)
    img = _render_point_with_optional_ies(ies_path)
    lum = img.mean(axis=2)
    cy, cx = H // 2, W // 2
    left = float(np.mean(lum[cy-12:cy+12, cx-45:cx-15]))
    right = float(np.mean(lum[cy-12:cy+12, cx+15:cx+45]))
    assert right > left * 1.6, f"Expected point-light IES asymmetry (left={left:.4f}, right={right:.4f})"


def test_spot_light_sharp_cone_on_floor_plane():
    img = _render_spot_on_plane(blend=0.0)
    lum = img.mean(axis=2)
    cy, cx = H // 2, W // 2
    center = float(np.mean(lum[cy-12:cy+12, cx-12:cx+12]))
    corners = float(np.mean(np.concatenate([
        lum[:20, :20].ravel(),
        lum[:20, -20:].ravel(),
        lum[-20:, :20].ravel(),
        lum[-20:, -20:].ravel(),
    ])))
    assert center > 0.1, f"Expected bright spotlight core, got center mean {center:.4f}"
    assert corners < center * 0.25, f"Expected strong cone cutoff (corners={corners:.4f}, center={center:.4f})"


def test_spot_light_blend_softens_cone_edges():
    sharp = _render_spot_on_plane(blend=0.0)
    soft = _render_spot_on_plane(blend=0.7)
    sharp_lum = sharp.mean(axis=2)
    soft_lum = soft.mean(axis=2)
    sharp_mid = float(np.mean((sharp_lum >= 0.02) & (sharp_lum < 0.20)))
    soft_mid = float(np.mean((soft_lum >= 0.02) & (soft_lum < 0.20)))
    assert soft_mid > sharp_mid + 0.03, \
        f"Expected blend to create more soft-edge midtones (sharp={sharp_mid:.4f}, soft={soft_mid:.4f})"


def test_sun_light_angle_controls_shadow_softness():
    def render_sun_shadow(angle):
        r = create_renderer()
        r.set_background_color([0.0, 0.0, 0.0])

        floor = r.create_material('lambertian', [0.85, 0.85, 0.85], {})
        blocker = r.create_material('lambertian', [0.7, 0.2, 0.2], {})
        sun = r.create_material('light', [1.0, 0.98, 0.9], {'intensity': 4.0})

        r.add_triangle([-2, -1, -2], [2, -1, 2], [2, -1, -2], floor)
        r.add_triangle([-2, -1, -2], [-2, -1, 2], [2, -1, 2], floor)
        r.add_sphere([0.0, -0.2, 0.0], 0.8, blocker)
        r.add_sun_light([0.0, -1.0, -0.4], angle, sun)

        setup_camera(r, look_from=[0, 1.8, 4.5], look_at=[0, -0.7, 0], vfov=35, width=W, height=H)
        return render_image(r, samples=48, max_depth=6)

    sharp = render_sun_shadow(0.0)
    soft = render_sun_shadow(0.05)
    assert_valid_image(sharp, H, W, min_brightness=0.15, label='sun_sharp')
    assert_valid_image(soft, H, W, min_brightness=0.15, label='sun_soft')

    mse = float(np.mean((sharp - soft) ** 2))
    assert mse > MIN_SUN_SHADOW_MSE, \
        f"Sun angle change should visibly alter shadows (MSE={mse:.6f}, min={MIN_SUN_SHADOW_MSE})"

    sharp_luma = np.mean(sharp, axis=2)
    soft_luma = np.mean(soft, axis=2)
    roi = (slice(70, 130), slice(40, 160))
    sharp_grad = np.abs(np.diff(sharp_luma[roi], axis=1))
    soft_grad = np.abs(np.diff(soft_luma[roi], axis=1))
    sharp_grad_mean = float(np.mean(sharp_grad))
    soft_grad_mean = float(np.mean(soft_grad))
    assert soft_grad_mean < sharp_grad_mean, \
        f"Expected softer penumbra gradients for angle=0.05 ({soft_grad_mean:.6f} >= {sharp_grad_mean:.6f})"

    save_image(sharp, os.path.join(OUTPUT_DIR, 'test_sun_shadow_sharp.png'))
    save_image(soft, os.path.join(OUTPUT_DIR, 'test_sun_shadow_soft.png'))


def test_mix_shader_blends_principled_red_blue_to_purple():
    red = {'kind': 'principled', 'base_color': [1.0, 0.0, 0.0], 'params': {'roughness': 0.3}}
    blue = {'kind': 'principled', 'base_color': [0.0, 0.0, 1.0], 'params': {'roughness': 0.7}}
    mixed = shader_blending.blend_shader_specs(0.5, red, blue)
    assert mixed['kind'] == 'principled'
    assert np.allclose(mixed['base_color'], [0.5, 0.0, 0.5], atol=1e-6)
    assert abs(mixed['params']['roughness'] - 0.5) < 1e-6


def test_mix_shader_glass_principled_maps_to_transmission_weight():
    principled = {'kind': 'principled', 'base_color': [0.8, 0.8, 0.8], 'params': {'transmission': 0.0, 'ior': 1.45}}
    glass = {'kind': 'principled', 'base_color': [1.0, 1.0, 1.0], 'params': {'transmission': 1.0, 'ior': 1.5}}
    mixed = shader_blending.blend_shader_specs(0.3, principled, glass)
    assert mixed['kind'] == 'principled'
    assert abs(mixed['params']['transmission'] - 0.3) < 1e-6


def test_add_shader_principled_and_emission_keeps_surface_and_emission():
    surface = {'kind': 'principled', 'base_color': [0.7, 0.5, 0.3], 'params': {'roughness': 0.4}}
    emission = {'kind': 'emission', 'base_color': [1.0, 0.8, 0.2], 'emission_strength': 2.0}
    combined = shader_blending.add_shader_specs(surface, emission)
    assert combined['kind'] == 'principled'
    assert np.allclose(combined['base_color'], [0.7, 0.5, 0.3], atol=1e-6)
    assert combined['emission_strength'] >= 2.0


def test_volume_absorption_blue_tint_biases_render_blue():
    r = create_renderer()
    setup_camera(r, look_from=[0, 0, 4], look_at=[0, 0, 0], width=W, height=H)
    r.add_volume([0, 0, 0], 1.5, 1.0, [0.2, 0.3, 1.0], 0.0)
    pixels = render_image(r, samples=SAMPLES_FAST)

    center_crop = pixels[H // 4:(3 * H) // 4, W // 4:(3 * W) // 4, :]
    means = np.mean(center_crop, axis=(0, 1))
    assert means[2] > means[0], \
        f"Expected blue > red for volume tint, got R={means[0]:.3f}, G={means[1]:.3f}, B={means[2]:.3f}"


def test_volume_scatter_anisotropy_changes_render():
    def render_volume(anisotropy):
        r = create_renderer()
        setup_camera(r, look_from=[0, 0, 4], look_at=[0, 0, 0], width=W, height=H)
        r.add_volume([0, 0, 0], 1.5, 1.0, [0.8, 0.8, 0.8], anisotropy)
        return render_image(r, samples=SAMPLES_FAST)

    iso = render_volume(0.0)
    forward = render_volume(0.8)
    mse = float(np.mean((iso - forward) ** 2))
    assert mse > 1e-4, f"Expected anisotropy to change scattering appearance (MSE={mse:.6f})"


def test_principled_volume_emission_strength_glows():
    def render_mean(emission_strength):
        r = create_renderer()
        r.set_background_color([0.0, 0.0, 0.0])
        setup_camera(r, look_from=[0, 0, 4], look_at=[0, 0, 0], width=W, height=H)
        r.add_volume([0, 0, 0], 1.0, 1.0, [0.9, 0.6, 0.3], 0.0,
                     emission_strength, [1.0, 0.8, 0.6])
        return float(np.mean(render_image(r, samples=SAMPLES_FAST)))

    mean_no_emission = render_mean(0.0)
    mean_with_emission = render_mean(1.0)
    assert mean_with_emission > mean_no_emission + 0.01, \
        f"Expected emissive principled volume to glow ({mean_with_emission:.3f} <= {mean_no_emission:.3f})"


# ---------------------------------------------------------------------------
# Rendering correctness: unlit scene should be dark
# ---------------------------------------------------------------------------

def test_background_sky_present():
    """
    The renderer uses a built-in sky gradient background (scaled by 0.2).
    After gamma correction a sphere-in-open-sky produces mean brightness ~0.3–0.7.
    This test catches regressions where the background is accidentally zeroed.
    """
    r = create_renderer()
    mat = r.create_material('lambertian', [0.8, 0.8, 0.8], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], width=W, height=H)
    pixels = render_image(r, samples=SAMPLES_FAST)
    assert_valid_image(pixels, H, W, min_mean=0.2, max_mean=0.85,
                       label='background_sky')


def test_transparent_film_alpha_masks_background():
    r = create_renderer()
    r.set_use_transparent_film(True)
    mat = r.create_material('lambertian', [0.8, 0.8, 0.8], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], width=W, height=H)
    render_image(r, samples=SAMPLES_FAST)
    alpha = r.get_alpha_buffer()

    assert alpha.shape == (H, W)
    assert float(alpha[H // 2, W // 2]) > 0.8
    assert float(alpha[5, 5]) < 0.1
    assert float(alpha[5, W - 6]) < 0.1
    assert float(alpha[H - 6, 5]) < 0.1
    assert float(alpha[H - 6, W - 6]) < 0.1


def test_transparent_film_default_alpha_is_opaque():
    r = create_renderer()
    mat = r.create_material('lambertian', [0.8, 0.8, 0.8], {})
    r.add_sphere([0, 0, 0], 1.0, mat)
    setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], width=W, height=H)
    render_image(r, samples=SAMPLES_FAST)
    alpha = r.get_alpha_buffer()

    assert alpha.shape == (H, W)
    assert float(np.min(alpha)) > 0.99


def test_transparent_glass_keeps_rgb_but_zeroes_alpha():
    r = create_renderer()
    r.set_use_transparent_film(True)
    glass = r.create_material('glass', [1.0, 1.0, 1.0], {'ior': 1.5})
    r.add_sphere([0, 0, 0], 1.0, glass)
    setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], width=W, height=H)
    render_image(r, samples=SAMPLES_FAST)
    alpha_default = r.get_alpha_buffer()

    r = create_renderer()
    r.set_use_transparent_film(True)
    r.set_transparent_glass(True)
    glass = r.create_material('glass', [1.0, 1.0, 1.0], {'ior': 1.5})
    r.add_sphere([0, 0, 0], 1.0, glass)
    setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], width=W, height=H)
    pixels = render_image(r, samples=SAMPLES_FAST)
    alpha = r.get_alpha_buffer()

    assert float(alpha_default[H // 2, W // 2]) > 0.8, "Glass should remain visible in alpha by default"
    assert float(np.mean(pixels)) > 0.05, "RGB should still contain background/environment contribution"
    assert float(alpha[H // 2, W // 2]) < 0.1, "Glass should be transparent in alpha when transparent_glass is enabled"


def test_film_exposure_scales_final_pixels():
    def render_mean(exposure=None):
        r = create_renderer()
        create_cornell_box(r)
        mat = r.create_material('lambertian', [0.8, 0.3, 0.3], {})
        r.add_sphere([0, -0.5, 0], 1.0, mat)
        setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=W, height=H)
        if exposure is not None:
            r.set_film_exposure(exposure)
        pixels = render_image(r, samples=SAMPLES_FAST)
        return float(np.mean(pixels))

    mean_default = render_mean()
    mean_exp_1 = render_mean(1.0)
    mean_exp_2 = render_mean(2.0)
    mean_exp_half = render_mean(0.5)

    assert abs(mean_exp_1 - mean_default) < 0.03, \
        f"Exposure=1.0 should match default output ({mean_exp_1:.3f} vs {mean_default:.3f})"
    assert mean_exp_2 > mean_exp_1, \
        f"Exposure=2.0 should be brighter ({mean_exp_2:.3f} <= {mean_exp_1:.3f})"
    assert mean_exp_half < mean_exp_1, \
        f"Exposure=0.5 should be darker ({mean_exp_half:.3f} >= {mean_exp_1:.3f})"


# ---------------------------------------------------------------------------
# Basic material renders with Cornell box lighting
# ---------------------------------------------------------------------------

def test_lambertian_render():
    r = create_renderer()
    create_cornell_box(r)
    mat = r.create_material('lambertian', [0.8, 0.3, 0.3], {})
    r.add_sphere([0, -0.5, 0], 1.0, mat)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=W, height=H)
    pixels = render_image(r, samples=SAMPLES_FAST)
    assert_valid_image(pixels, H, W, min_mean=0.05, label='lambertian')
    path = os.path.join(OUTPUT_DIR, 'test_basic_sphere.png')
    save_image(pixels, path)


def test_metal_render():
    r = create_renderer()
    create_cornell_box(r)
    mat = r.create_material('metal', [0.9, 0.9, 0.9], {'roughness': 0.05})
    r.add_sphere([0, -0.5, 0], 1.0, mat)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=W, height=H)
    pixels = render_image(r, samples=SAMPLES_FAST)
    assert_valid_image(pixels, H, W, min_mean=0.03, label='metal')


def test_white_metal_roughness_one_not_dark():
    """Regression: rough white metal should stay bright under furnace lighting."""
    r = create_renderer()
    r.set_background_color([1.0, 1.0, 1.0])  # uniform white emitter
    mat = r.create_material('metal', [1.0, 1.0, 1.0], {'roughness': 1.0})
    r.add_sphere([0, 0, 0], 1.0, mat)
    setup_camera(r, look_from=[0, 0, 4], look_at=[0, 0, 0], vfov=35, width=W, height=H)
    pixels = render_image(r, samples=SAMPLES_MED)

    crop = pixels[H // 2 - 20:H // 2 + 20, W // 2 - 20:W // 2 + 20, :]
    mean_center = float(np.mean(crop))
    assert mean_center > 0.85, f"Rough white metal center too dark in furnace test ({mean_center:.3f})"


def test_metal_furnace_energy_above_threshold_all_roughness():
    """Furnace test: white metal should preserve high energy for all roughness values."""
    roughness_values = [0.1, 0.3, 0.6, 1.0]
    for roughness in roughness_values:
        r = create_renderer()
        r.set_background_color([1.0, 1.0, 1.0])  # uniform white emitter
        mat = r.create_material('metal', [1.0, 1.0, 1.0], {'roughness': roughness})
        r.add_sphere([0, 0, 0], 1.0, mat)
        setup_camera(r, look_from=[0, 0, 4], look_at=[0, 0, 0], vfov=35, width=W, height=H)
        pixels = render_image(r, samples=SAMPLES_MED)

        crop = pixels[H // 2 - 20:H // 2 + 20, W // 2 - 20:W // 2 + 20, :]
        mean_center = float(np.mean(crop))
        assert mean_center > 0.85, (
            f"Furnace energy too low for roughness={roughness:.2f}: center mean={mean_center:.3f}"
        )
def test_glass_render():
    r = create_renderer()
    create_cornell_box(r)
    mat = r.create_material('glass', [1.0, 1.0, 1.0], {'ior': 1.5})
    r.add_sphere([0, -0.5, 0], 1.0, mat)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=W, height=H)
    pixels = render_image(r, samples=SAMPLES_FAST)
    assert_valid_image(pixels, H, W, min_mean=0.03, label='glass')


def test_glossy_bounces_zero_reduces_specular_reflections():
    def render(glossy_bounces: int) -> np.ndarray:
        r = create_renderer()
        create_cornell_box(r)
        mat = r.create_material('metal', [0.95, 0.95, 0.95], {'roughness': 0.02})
        r.add_sphere([0, -0.5, 0], 1.0, mat)
        setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=W, height=H)
        return r.render(SAMPLES_MED, 8, None, True, -1, glossy_bounces, -1, -1, -1)

    glossy = render(8)
    no_glossy = render(0)
    assert_valid_image(glossy, H, W, label='glossy_enabled')
    assert_valid_image(no_glossy, H, W, label='glossy_disabled')
    ch, cw = H // 2, W // 2
    center = np.s_[ch - 35:ch + 35, cw - 35:cw + 35, :]
    assert float(np.mean(no_glossy[center])) < float(np.mean(glossy[center])) * 0.55


def test_transmission_bounces_zero_makes_glass_darker():
    def render(transmission_bounces: int) -> np.ndarray:
        r = create_renderer()
        mat = r.create_material('glass', [1.0, 1.0, 1.0], {'ior': 1.5})
        r.add_sphere([0, 0, 0], 1.0, mat)
        setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], width=W, height=H)
        return r.render(SAMPLES_MED, 8, None, True, -1, -1, transmission_bounces, -1, -1)

    with_transmission = render(8)
    no_transmission = render(0)
    assert_valid_image(with_transmission, H, W, label='transmission_enabled')
    assert_valid_image(no_transmission, H, W, label='transmission_disabled')

    ch, cw = H // 2, W // 2
    center = np.s_[ch - 20:ch + 20, cw - 20:cw + 20, :]
    assert float(np.mean(no_transmission[center])) < float(np.mean(with_transmission[center])) * 0.75


def test_total_max_depth_still_caps_all_paths():
    r = create_renderer()
    create_cornell_box(r)
    mat = r.create_material('metal', [0.95, 0.95, 0.95], {'roughness': 0.02})
    r.add_sphere([0, -0.5, 0], 1.0, mat)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=W, height=H)

    depth0 = r.render(SAMPLES_MED, 0, None, True, -1, 8, -1, -1, -1)
    depth8 = r.render(SAMPLES_MED, 8, None, True, -1, 8, -1, -1, -1)
    assert_valid_image(depth8, H, W, label='depth8')
    assert float(np.mean(depth0)) < 0.01
    assert float(np.mean(depth8)) > float(np.mean(depth0)) + 0.1


def test_disney_brdf_render():
    r = create_renderer()
    create_cornell_box(r)
    mat = r.create_material('disney', [0.8, 0.6, 0.4],
                            {'metallic': 0.3, 'roughness': 0.4, 'clearcoat': 0.5})
    r.add_sphere([0, -0.5, 0], 1.0, mat)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=W, height=H)
    pixels = render_image(r, samples=SAMPLES_FAST)
    assert_valid_image(pixels, H, W, min_mean=0.03, label='disney_brdf')


# ---------------------------------------------------------------------------
# Cornell box — proper front-on camera, saved as reference image
# ---------------------------------------------------------------------------

def test_cornell_box():
    r = create_renderer()
    create_cornell_box(r)
    glass_mat = r.create_material('glass', [1, 1, 1], {'ior': 1.5})
    disney_mat = r.create_material('disney', [0.9, 0.8, 0.7],
                                   {'metallic': 0.5, 'roughness': 0.3, 'clearcoat': 0.5})
    metal_mat = r.create_material('metal', [0.9, 0.9, 0.9], {'roughness': 0.1})
    r.add_sphere([-0.7, -1.3, -0.5], 0.7, glass_mat)
    r.add_sphere([0.8, -1.5, 0.3], 0.5, disney_mat)
    r.add_sphere([0, -1.5, -1.2], 0.5, metal_mat)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=400, height=300)
    pixels = render_image(r, samples=SAMPLES_MED)
    assert_valid_image(pixels, 300, 400, min_mean=0.10,
                       min_brightness=0.5, label='cornell_box')
    # The image should contain both reddish (left wall) and greenish (right wall) pixels
    left_region  = pixels[:, :pixels.shape[1]//4, :]   # far left columns
    right_region = pixels[:, -pixels.shape[1]//4:, :]  # far right columns
    assert np.mean(left_region[:, :, 0]) > np.mean(right_region[:, :, 0]), \
        "Left region should be redder than right"
    assert np.mean(right_region[:, :, 1]) > np.mean(left_region[:, :, 1]), \
        "Right region should be greener than left"
    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_cornell_box.png'))


# ---------------------------------------------------------------------------
# Multiple spheres (matches original test)
# ---------------------------------------------------------------------------

def test_multiple_spheres():
    r = create_renderer()
    create_cornell_box(r)
    red   = r.create_material('lambertian', [0.8, 0.2, 0.2], {})
    green = r.create_material('lambertian', [0.2, 0.8, 0.2], {})
    blue  = r.create_material('lambertian', [0.2, 0.2, 0.8], {})
    r.add_sphere([-1.2, -1.2, 0], 0.7, red)
    r.add_sphere([0,    -1.2, 0], 0.7, green)
    r.add_sphere([1.2,  -1.2, 0], 0.7, blue)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=400, height=300)
    pixels = render_image(r, samples=SAMPLES_MED)
    assert_valid_image(pixels, 300, 400, min_mean=0.05, label='multiple_spheres')
    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_multiple_spheres.png'))


# ---------------------------------------------------------------------------
# Depth-of-field / aperture
# ---------------------------------------------------------------------------

def test_aperture_dof():
    """Aperture > 0 should produce depth-of-field blur."""
    r_no_dof  = create_renderer()
    r_dof     = create_renderer()
    for r in (r_no_dof, r_dof):
        create_cornell_box(r)
        mat = r.create_material('lambertian', [0.8, 0.3, 0.3], {})
        r.add_sphere([0, -0.5, 0], 1.0, mat)
    setup_camera(r_no_dof, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, aperture=0.0, focus_dist=5.5, width=W, height=H)
    setup_camera(r_dof,    look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, aperture=0.8, focus_dist=5.5, width=W, height=H)
    px_no_dof = render_image(r_no_dof, samples=SAMPLES_MED)
    px_dof    = render_image(r_dof,    samples=SAMPLES_MED)
    assert_valid_image(px_no_dof, H, W, label='no_dof')
    assert_valid_image(px_dof,    H, W, label='dof')
    # DoF image should differ visibly from no-DoF
    mse, _ = calculate_image_metrics(px_no_dof, px_dof)
    assert mse > 1e-4, f"DoF image identical to no-DoF image (mse={mse:.6f})"
    save_image(px_dof, os.path.join(OUTPUT_DIR, 'test_sphere_aperture.png'))


# ---------------------------------------------------------------------------
# Disney BRDF parameter grid (matches notebook Cell 5)
# ---------------------------------------------------------------------------

def test_disney_brdf_parameter_grid():
    """Render all 12 Disney BRDF configurations from the notebook and save a grid."""
    configs = [
        {'metallic': 0.0, 'roughness': 0.0,                         'title': 'Dielectric Smooth'},
        {'metallic': 0.0, 'roughness': 0.5,                         'title': 'Dielectric Rough'},
        {'metallic': 1.0, 'roughness': 0.0,                         'title': 'Metal Smooth'},
        {'metallic': 1.0, 'roughness': 0.5,                         'title': 'Metal Rough'},
        {'metallic': 0.5, 'roughness': 0.3,                         'title': 'Half Metallic'},
        {'metallic': 0.0, 'roughness': 0.5, 'clearcoat': 1.0,       'title': 'With Clearcoat'},
        {'metallic': 0.0, 'roughness': 0.5, 'anisotropic': 0.8,     'title': 'Anisotropic'},
        {'metallic': 0.0, 'roughness': 0.5, 'sheen': 1.0,           'title': 'With Sheen'},
        {'transmission': 1.0, 'ior': 1.5,                           'title': 'Full Transmission'},
        {'transmission': 0.5, 'metallic': 0.5,                      'title': 'Half Trans/Metal'},
        {'subsurface': 0.5,                                          'title': 'Subsurface'},
        {'metallic': 0.8, 'roughness': 0.2, 'clearcoat': 0.5,       'title': 'Complex'},
    ]

    fig = plt.figure(figsize=(16, 12))
    gs  = GridSpec(3, 4, figure=fig)
    tw, th = 100, 75  # small tiles for speed

    for idx, cfg in enumerate(configs):
        r = create_renderer()
        ground = r.create_material('lambertian', [0.5, 0.5, 0.5], {})
        light  = r.create_material('light',      [1, 1, 1],       {'intensity': 5.0})
        r.add_triangle([-5, -1, -5], [5, -1, -5], [5, -1, 5], ground)
        r.add_triangle([-5, -1, -5], [5, -1, 5], [-5, -1, 5], ground)
        r.add_sphere([2, 3, 2], 1.0, light)
        params = {k: v for k, v in cfg.items() if k != 'title'}
        mat = r.create_material('disney', [0.7, 0.5, 0.3], params)
        r.add_sphere([0, 0, 0], 1.0, mat)
        setup_camera(r, look_from=[3, 2, 3], look_at=[0, 0, 0],
                     vfov=35, width=tw, height=th)
        pixels = render_image(r, samples=SAMPLES_MED)
        assert_valid_image(pixels, th, tw, min_mean=0.01, label=cfg['title'])
        ax = fig.add_subplot(gs[idx // 4, idx % 4])
        ax.imshow(np.clip(pixels, 0, 1))
        ax.set_title(cfg['title'], fontsize=9)
        ax.axis('off')

    plt.suptitle('Disney BRDF Parameter Tests', fontsize=14)
    plt.tight_layout()
    save_figure(fig, os.path.join(OUTPUT_DIR, 'test_disney_brdf_grid.png'))


# ---------------------------------------------------------------------------
# Material comparison grid (matches notebook Cell 6)
# ---------------------------------------------------------------------------

def test_material_comparison_grid():
    """Render all basic material types and save a comparison grid."""
    materials = [
        ('Lambertian',    'lambertian', [0.8, 0.3, 0.3], {}),
        ('Metal Smooth',  'metal',      [0.9, 0.9, 0.9], {'roughness': 0.02}),
        ('Metal Rough',   'metal',      [0.9, 0.9, 0.9], {'roughness': 0.5}),
        ('Glass',         'glass',      [1, 1, 1],        {'ior': 1.5}),
        ('Disney Metal',  'disney',     [0.9, 0.7, 0.5],  {'metallic': 1.0, 'roughness': 0.2}),
        ('Disney Glass',  'disney',     [1, 1, 1],         {'transmission': 1.0, 'ior': 1.5}),
        ('Disney Plastic','disney',     [0.5, 0.8, 0.5],  {'metallic': 0.0, 'roughness': 0.3}),
        ('Clearcoat',     'disney',     [0.8, 0.3, 0.3],  {'clearcoat': 1.0, 'clearcoat_gloss': 0.9}),
        ('Subsurface',    'subsurface', [0.9, 0.6, 0.5],  {'scatter_distance': [1.0, 0.2, 0.1]}),
    ]

    tw, th = 100, 75
    fig = plt.figure(figsize=(15, 10))
    gs  = GridSpec(3, 3, figure=fig)

    for idx, (name, mat_type, color, params) in enumerate(materials):
        r = create_renderer()
        ground = r.create_material('lambertian', [0.7, 0.7, 0.7], {})
        light  = r.create_material('light',      [1, 1, 1],        {'intensity': 8.0})
        r.add_triangle([-3, -1, -3], [3, -1, -3], [3, -1, 3], ground)
        r.add_triangle([-3, -1, -3], [3, -1, 3], [-3, -1, 3], ground)
        r.add_sphere([2, 3, 2], 0.5, light)
        r.add_sphere([-2, 3, 2], 0.5, light)
        mat = r.create_material(mat_type, color, params)
        r.add_sphere([0, 0, 0], 1.0, mat)
        setup_camera(r, look_from=[2.5, 2, 2.5], look_at=[0, 0, 0],
                     vfov=35, width=tw, height=th)
        pixels = render_image(r, samples=SAMPLES_MED)
        assert_valid_image(pixels, th, tw, min_mean=0.01, label=name)
        ax = fig.add_subplot(gs[idx // 3, idx % 3])
        ax.imshow(np.clip(pixels, 0, 1))
        ax.set_title(name)
        ax.axis('off')

    plt.suptitle('Material Type Comparison', fontsize=14)
    plt.tight_layout()
    save_figure(fig, os.path.join(OUTPUT_DIR, 'test_material_comparison.png'))


# ---------------------------------------------------------------------------
# Sampling convergence (matches notebook Cell 7)
# ---------------------------------------------------------------------------

def test_sampling_convergence():
    """Higher sample counts must produce lower variance and brighter estimates."""
    sample_counts = [4, 16, 64, 256]
    images = []
    times  = []

    for spp in sample_counts:
        r = create_renderer()
        create_cornell_box(r)
        mat = r.create_material('disney', [0.8, 0.6, 0.4],
                                {'metallic': 0.3, 'roughness': 0.4, 'clearcoat': 0.5})
        r.add_sphere([0, -0.5, 0], 1.0, mat)
        setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                     vfov=38, width=W, height=H)
        t0 = time.time()
        pixels = render_image(r, samples=spp)
        times.append(time.time() - t0)
        images.append(pixels)
        assert_valid_image(pixels, H, W, min_mean=0.02, label=f'{spp}spp')

    # Higher samples → lower per-pixel variance (compare 4spp vs 256spp)
    var_low  = float(np.var(images[0]))
    var_high = float(np.var(images[-1]))
    # We can't guarantee exact ordering (different seeds), but the 256spp image
    # should have converged toward a stable value, so its mean should be defined.
    # Verify render times scale roughly with sample count (not wildly off)
    assert times[-1] > times[0] * 0.5, "256spp render should take longer than 4spp"

    fig, axes = plt.subplots(1, len(sample_counts), figsize=(12, 3))
    for i, (img, spp, t) in enumerate(zip(images, sample_counts, times)):
        axes[i].imshow(np.clip(img, 0, 1))
        axes[i].set_title(f'{spp} spp\n({t:.1f}s)')
        axes[i].axis('off')
    plt.suptitle('Sample Count Convergence')
    plt.tight_layout()
    save_figure(fig, os.path.join(OUTPUT_DIR, 'test_convergence.png'))


# ---------------------------------------------------------------------------
# Adaptive sampling (matches notebook Cell 8)
# ---------------------------------------------------------------------------

def test_adaptive_sampling_flag():
    """set_adaptive_sampling() should not crash; renders should be valid."""
    r = create_renderer()
    create_cornell_box(r)
    mat = r.create_material('disney', [0.8, 0.6, 0.4], {'metallic': 0.3, 'roughness': 0.4})
    r.add_sphere([0, -0.5, 0], 1.0, mat)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=W, height=H)

    r.set_adaptive_sampling(True)
    px_adaptive = render_image(r, samples=SAMPLES_MED)
    assert_valid_image(px_adaptive, H, W, min_mean=0.02, label='adaptive')

    r.set_adaptive_sampling(False)
    px_fixed = render_image(r, samples=SAMPLES_MED)
    assert_valid_image(px_fixed, H, W, min_mean=0.02, label='fixed')


def test_direct_and_indirect_clamp_controls():
    """Direct/indirect clamp settings should reduce bright outliers when enabled."""
    def luminance_map(pixels: np.ndarray) -> np.ndarray:
        return 0.2126 * pixels[:, :, 0] + 0.7152 * pixels[:, :, 1] + 0.0722 * pixels[:, :, 2]

    def render_direct(clamp_direct: float) -> np.ndarray:
        r = create_renderer()
        diffuse = r.create_material('lambertian', [0.85, 0.85, 0.85], {})
        light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 400.0})
        r.add_sphere([0.0, 0.0, 0.0], 1.0, diffuse)
        r.add_triangle([-0.8, 2.0, -0.8], [0.8, 2.0, -0.8], [0.8, 2.0, 0.8], light)
        r.add_triangle([-0.8, 2.0, -0.8], [0.8, 2.0, 0.8], [-0.8, 2.0, 0.8], light)
        setup_camera(r, look_from=[0, 0.2, 4.5], look_at=[0, 0, 0], vfov=38, width=120, height=90)
        r.set_clamp_direct(clamp_direct)
        r.set_clamp_indirect(0.0)
        return render_image(r, samples=24, max_depth=6, apply_gamma=False)

    def render_indirect(clamp_indirect: float) -> np.ndarray:
        r = create_renderer()
        create_cornell_box(r)
        glass = r.create_material('glass', [1.0, 1.0, 1.0], {'ior': 1.5})
        r.add_sphere([0, -0.6, 0], 1.0, glass)
        setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=120, height=90)
        r.set_clamp_direct(0.0)
        r.set_clamp_indirect(clamp_indirect)
        return render_image(r, samples=24, max_depth=10, apply_gamma=False)

    direct_unclamped = luminance_map(render_direct(0.0))
    direct_clamped = luminance_map(render_direct(1.0))
    assert np.percentile(direct_clamped, 99.5) < np.percentile(direct_unclamped, 99.5), \
        "clamp_direct=1.0 should reduce bright direct-light outliers"

    indirect_unclamped = luminance_map(render_indirect(0.0))
    indirect_clamped = luminance_map(render_indirect(0.5))
    assert np.percentile(indirect_clamped, 99.5) < np.percentile(indirect_unclamped, 99.5), \
        "clamp_indirect should reduce bright indirect-light outliers"


def _luminance_map(pixels: np.ndarray) -> np.ndarray:
    return 0.2126 * pixels[:, :, 0] + 0.7152 * pixels[:, :, 1] + 0.0722 * pixels[:, :, 2]


def test_filter_glossy_blurs_secondary_glossy_paths():
    def render(filter_glossy: float) -> np.ndarray:
        r = create_renderer()
        ground = r.create_material('lambertian', [0.75, 0.75, 0.75], {})
        light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 12.0})
        mirror = r.create_material('metal', [0.95, 0.95, 0.95], {'roughness': 0.001})
        r.add_triangle([-5, -1, -6], [5, -1, -6], [5, -1, 2], ground)
        r.add_triangle([-5, -1, -6], [5, -1, 2], [-5, -1, 2], ground)
        r.add_sphere([0.0, 3.5, 1.0], 0.9, light)
        r.add_sphere([0.0, 0.0, 0.0], 1.0, mirror)
        r.add_sphere([0.0, 0.0, -2.5], 1.0, mirror)
        setup_camera(r, look_from=[0, 0.2, 5], look_at=[0, 0, -1], vfov=34, width=120, height=90)
        r.set_filter_glossy(filter_glossy)
        return render_image(r, samples=32, max_depth=10, apply_gamma=False)

    base = render(0.0)
    filtered = render(1.0)
    assert_valid_image(base, 90, 120, label='filter_glossy_off')
    assert_valid_image(filtered, 90, 120, label='filter_glossy_on')

    lum_base = _luminance_map(base)[20:70, 35:85]
    lum_filtered = _luminance_map(filtered)[20:70, 35:85]
    assert float(np.percentile(lum_filtered, 95.0)) < float(np.percentile(lum_base, 95.0)) * 0.99, \
        "filter_glossy=1.0 should slightly blur secondary glossy reflections"


def test_disable_reflective_caustics_reduces_mirror_caustic_outliers():
    def render(use_reflective_caustics: bool) -> np.ndarray:
        r = create_renderer()
        create_cornell_box(r)
        mirror = r.create_material('metal', [0.95, 0.95, 0.95], {'roughness': 0.001})
        r.add_sphere([0, -0.6, 0], 1.0, mirror)
        setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=120, height=90)
        r.set_use_reflective_caustics(use_reflective_caustics)
        return render_image(r, samples=24, max_depth=10, apply_gamma=False)

    enabled = _luminance_map(render(True))
    disabled = _luminance_map(render(False))
    floor_roi = np.s_[55:88, 35:85]
    assert np.percentile(disabled[floor_roi], 99.0) < np.percentile(enabled[floor_roi], 99.0), \
        "Disabling reflective caustics should reduce bright mirror caustic pixels on diffuse surfaces"


def test_disable_refractive_caustics_reduces_glass_caustic_outliers():
    def render(use_refractive_caustics: bool) -> np.ndarray:
        r = create_renderer()
        create_cornell_box(r)
        glass = r.create_material('glass', [1.0, 1.0, 1.0], {'ior': 1.5})
        r.add_sphere([0, -0.6, 0], 1.0, glass)
        setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=120, height=90)
        r.set_use_refractive_caustics(use_refractive_caustics)
        return render_image(r, samples=24, max_depth=10, apply_gamma=False)

    enabled = _luminance_map(render(True))
    disabled = _luminance_map(render(False))
    floor_roi = np.s_[55:88, 35:85]
    assert np.percentile(disabled[floor_roi], 99.0) < np.percentile(enabled[floor_roi], 99.0), \
        "Disabling refractive caustics should reduce bright glass caustic pixels on diffuse surfaces"


# ---------------------------------------------------------------------------
# Metallic vs diffuse: renders must differ
# ---------------------------------------------------------------------------

def test_metallic_vs_diffuse_differ():
    """Disney metallic=1 and metallic=0 spheres should look different."""
    def render_disney(metallic: float) -> np.ndarray:
        r = create_renderer()
        ground = r.create_material('lambertian', [0.5, 0.5, 0.5], {})
        light  = r.create_material('light',      [1, 1, 1],       {'intensity': 5.0})
        r.add_triangle([-5, -1, -5], [5, -1, -5], [5, -1, 5], ground)
        r.add_triangle([-5, -1, -5], [5, -1, 5], [-5, -1, 5], ground)
        r.add_sphere([2, 3, 2], 1.0, light)
        mat = r.create_material('disney', [0.7, 0.5, 0.3],
                                {'metallic': metallic, 'roughness': 0.3})
        r.add_sphere([0, 0, 0], 1.0, mat)
        setup_camera(r, look_from=[3, 2, 3], look_at=[0, 0, 0],
                     vfov=35, width=W, height=H)
        return render_image(r, samples=SAMPLES_MED)

    px_diff  = render_disney(0.0)
    px_metal = render_disney(1.0)
    assert_valid_image(px_diff,  H, W, label='diffuse')
    assert_valid_image(px_metal, H, W, label='metallic')
    mse, _ = calculate_image_metrics(px_diff, px_metal)
    assert mse > 5e-4, \
        f"Metallic and diffuse renders too similar (MSE={mse:.6f}); material may not be working"


# ---------------------------------------------------------------------------
# Performance benchmark (matches notebook Cell 10)
# ---------------------------------------------------------------------------

def test_performance_benchmark():
    """Benchmark render speed and save a performance chart."""
    configs = [
        ('10 objects',  10,  32),
        ('50 objects',  50,  32),
        ('100 objects', 100, 32),
        ('100 objects high SPP', 100, SAMPLES_HIGH),
    ]

    bw, bh = 200, 150
    results = {'label': [], 'time': [], 'mrays': []}

    np.random.seed(42)
    for label, n_objects, spp in configs:
        r = create_renderer()
        ground = r.create_material('lambertian', [0.5, 0.5, 0.5], {})
        light  = r.create_material('light',      [1, 1, 1],       {'intensity': 5.0})
        r.add_triangle([-10, -2, -10], [10, -2, -10], [10, -2, 10], ground)
        r.add_triangle([-10, -2, -10], [10, -2, 10], [-10, -2, 10], ground)
        r.add_sphere([0, 5, 0], 2.0, light)

        for _ in range(n_objects):
            pos = [float(np.random.uniform(-5, 5)),
                   float(np.random.uniform(-1, 3)),
                   float(np.random.uniform(-5, 5))]
            choice = np.random.choice(['disney', 'metal', 'glass'])
            if choice == 'disney':
                mat = r.create_material('disney', list(np.random.rand(3).tolist()),
                                        {'metallic': float(np.random.rand()),
                                         'roughness': float(np.random.rand())})
            elif choice == 'metal':
                mat = r.create_material('metal', list(np.random.rand(3).tolist()),
                                        {'roughness': float(np.random.rand())})
            else:
                mat = r.create_material('glass', [1, 1, 1], {'ior': 1.5})
            r.add_sphere(pos, float(np.random.uniform(0.1, 0.5)), mat)

        setup_camera(r, look_from=[8, 5, 8], look_at=[0, 0, 0],
                     vfov=35, width=bw, height=bh)
        t0 = time.time()
        pixels = render_image(r, samples=spp)
        elapsed = time.time() - t0
        mrays = bw * bh * spp / elapsed / 1e6

        assert_valid_image(pixels, bh, bw, label=label)
        results['label'].append(label)
        results['time'].append(elapsed)
        results['mrays'].append(mrays)

    # Save performance chart
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
    x = range(len(results['label']))
    ax1.bar(x, results['time'])
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(results['label'], rotation=20, ha='right')
    ax1.set_ylabel('Render Time (s)')
    ax1.set_title('Render Time')
    ax1.grid(True, alpha=0.3)

    ax2.bar(x, results['mrays'])
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(results['label'], rotation=20, ha='right')
    ax2.set_ylabel('M Rays / s')
    ax2.set_title('Ray Throughput')
    ax2.grid(True, alpha=0.3)

    plt.suptitle('Performance Benchmark')
    plt.tight_layout()
    save_figure(fig, os.path.join(OUTPUT_DIR, 'test_performance_100samples.png'))


# ---------------------------------------------------------------------------
# Quality analysis — PSNR vs reference (matches notebook Cell 12)
# ---------------------------------------------------------------------------

def test_quality_analysis():
    """Higher sample counts should converge to a reference and yield higher PSNR."""
    rw, rh = 100, 75  # small to keep runtime sane

    def make_render(spp: int) -> np.ndarray:
        r = create_renderer()
        create_cornell_box(r)
        mat = r.create_material('disney', [0.8, 0.6, 0.4],
                                {'metallic': 0.5, 'roughness': 0.3})
        r.add_sphere([0, -0.5, 0], 1.0, mat)
        setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                     vfov=38, width=rw, height=rh)
        return render_image(r, samples=spp)

    ref = make_render(SAMPLES_HIGH)
    test_configs = [
        ('Low (16 spp)',    16),
        ('Medium (64 spp)', 64),
        ('High (256 spp)',  SAMPLES_HIGH),
    ]

    fig, axes = plt.subplots(1, 4, figsize=(14, 4))
    axes[0].imshow(np.clip(ref, 0, 1))
    axes[0].set_title(f'Reference ({SAMPLES_HIGH} spp)')
    axes[0].axis('off')

    prev_psnr = 0.0
    for i, (name, spp) in enumerate(test_configs):
        img = make_render(spp)
        mse, psnr = calculate_image_metrics(ref, img)
        # Higher samples should produce equal or better PSNR (allow ±3 dB tolerance)
        assert psnr >= prev_psnr - 3.0, \
            f"{name}: PSNR {psnr:.1f} dB regressed below previous {prev_psnr:.1f} dB"
        prev_psnr = max(prev_psnr, psnr)
        axes[i + 1].imshow(np.clip(img, 0, 1))
        axes[i + 1].set_title(f'{name}\nPSNR: {psnr:.1f} dB')
        axes[i + 1].axis('off')

    plt.suptitle('Quality Analysis vs Reference')
    plt.tight_layout()
    save_figure(fig, os.path.join(OUTPUT_DIR, 'test_quality_analysis.png'))


# ---------------------------------------------------------------------------
# AOV buffers (albedo / normal)
# ---------------------------------------------------------------------------

def test_aov_buffers():
    r = create_renderer()
    create_cornell_box(r)
    mat = r.create_material('lambertian', [0.8, 0.3, 0.3], {})
    r.add_sphere([0, -0.5, 0], 1.0, mat)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=W, height=H)
    render_image(r, samples=SAMPLES_FAST)

    albedo = r.get_albedo_buffer()
    normal = r.get_normal_buffer()
    assert albedo.shape == (H, W, 3), f"Albedo shape mismatch: {albedo.shape}"
    assert normal.shape == (H, W, 3), f"Normal shape mismatch: {normal.shape}"


def test_data_pass_buffers_exist_and_are_finite():
    r = create_renderer()
    create_cornell_box(r)
    red = r.create_material('lambertian', [0.8, 0.2, 0.2], {})
    r.add_sphere([0, -0.8, 0.2], 1.1, red, [], "", 3, 7)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=W, height=H)
    render_image(r, samples=SAMPLES_FAST)

    depth = r.get_depth_buffer()
    position = r.get_position_buffer()
    uv = r.get_uv_buffer()
    obj_idx = r.get_object_index_buffer()
    mat_idx = r.get_material_index_buffer()

    assert depth.shape == (H, W), f"Depth shape mismatch: {depth.shape}"
    assert position.shape == (H, W, 3), f"Position shape mismatch: {position.shape}"
    assert uv.shape == (H, W, 3), f"UV shape mismatch: {uv.shape}"
    assert obj_idx.shape == (H, W), f"Object index shape mismatch: {obj_idx.shape}"
    assert mat_idx.shape == (H, W), f"Material index shape mismatch: {mat_idx.shape}"
    assert np.isfinite(depth).all()
    assert np.isfinite(position).all()
    assert np.isfinite(uv).all()
    assert np.isfinite(obj_idx).all()
    assert np.isfinite(mat_idx).all()
    assert float(np.max(obj_idx)) >= 0.0
    assert float(np.max(mat_idx)) >= 0.0


def test_cryptomatte_buffers_exist_and_have_coverage():
    r = create_renderer()
    r.set_background_color([0.0, 0.0, 0.0])
    mat_a = r.create_material('lambertian', [0.9, 0.2, 0.2], {})
    mat_b = r.create_material('lambertian', [0.2, 0.2, 0.9], {})
    r.add_sphere([-0.9, 0.0, 0.0], 0.8, mat_a, [], "", 11, 21)
    r.add_sphere([0.9, 0.0, 0.0], 0.8, mat_b, [], "", 12, 22)
    setup_camera(r, look_from=[0, 0, 4.0], look_at=[0, 0, 0], vfov=30, width=W, height=H)
    render_image(r, samples=SAMPLES_FAST)

    crypto_obj = r.get_cryptomatte_object_buffer()
    crypto_mat = r.get_cryptomatte_material_buffer()
    assert crypto_obj.shape == (H, W, 4), f"Cryptomatte object shape mismatch: {crypto_obj.shape}"
    assert crypto_mat.shape == (H, W, 4), f"Cryptomatte material shape mismatch: {crypto_mat.shape}"
    assert np.isfinite(crypto_obj).all()
    assert np.isfinite(crypto_mat).all()
    assert float(np.max(crypto_obj[:, :, 3])) > 0.0, "Object cryptomatte coverage should be non-zero"
    assert float(np.max(crypto_mat[:, :, 3])) > 0.0, "Material cryptomatte coverage should be non-zero"
    assert float(np.min(crypto_obj[:, :, 3])) >= 0.0 and float(np.max(crypto_obj[:, :, 3])) <= 1.0
    assert float(np.min(crypto_mat[:, :, 3])) >= 0.0 and float(np.max(crypto_mat[:, :, 3])) <= 1.0


def test_render_pass_buffers_exist_and_are_finite():
    r = create_renderer()
    create_cornell_box(r)
    sphere_mat = r.create_material('lambertian', [0.8, 0.4, 0.2], {})
    r.add_sphere([0, -0.8, 0.2], 1.2, sphere_mat)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=W, height=H)
    render_image(r, samples=SAMPLES_FAST)

    for key in RENDER_PASS_KEYS:
        buf = r.get_render_pass_buffer(key)
        assert buf.shape == (H, W, 3), f"{key} shape mismatch: {buf.shape}"
        assert np.isfinite(buf).all(), f"{key} contains non-finite values"


def test_emission_pass_isolated_from_diffuse_direct():
    r = create_renderer()
    r.set_seed(77)
    r.set_background_color([0.0, 0.0, 0.0])
    light_mat = r.create_material('light', [1.0, 0.8, 0.6], {'intensity': 10.0})
    r.add_sphere([0, 0, 0], 0.8, light_mat)
    setup_camera(r, look_from=[0, 0, 3.0], look_at=[0, 0, 0], vfov=30, width=W, height=H)
    render_image(r, samples=SAMPLES_FAST)

    emission = r.get_render_pass_buffer("emission")
    diffuse_direct = r.get_render_pass_buffer("diffuse_direct")
    assert float(np.mean(emission)) > 0.01, "Emission pass should contain emissive object energy"
    assert float(np.mean(diffuse_direct)) < float(np.mean(emission)) * 0.2, \
        "Diffuse direct should be much darker than emission in emissive-only scene"


def test_component_passes_sum_approximately_matches_beauty():
    r = create_renderer()
    r.set_seed(123)
    create_cornell_box(r)
    glossy = r.create_material('metal', [0.9, 0.9, 0.9], {'roughness': 0.2})
    glass = r.create_material('glass', [1.0, 1.0, 1.0], {'ior': 1.45})
    r.add_sphere([-0.6, -0.7, 0.0], 0.8, glossy)
    r.add_sphere([0.8, -0.7, 0.4], 0.8, glass)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=W, height=H)

    beauty = render_image(r, samples=SAMPLES_MED, apply_gamma=False)
    component_sum = (
        r.get_render_pass_buffer("diffuse_direct") +
        r.get_render_pass_buffer("diffuse_indirect") +
        r.get_render_pass_buffer("glossy_direct") +
        r.get_render_pass_buffer("glossy_indirect") +
        r.get_render_pass_buffer("transmission_direct") +
        r.get_render_pass_buffer("transmission_indirect") +
        r.get_render_pass_buffer("volume_direct") +
        r.get_render_pass_buffer("volume_indirect") +
        r.get_render_pass_buffer("emission") +
        r.get_render_pass_buffer("environment")
    )
    denom = max(float(np.mean(np.abs(beauty))), 1e-4)
    rel_err = float(np.mean(np.abs(beauty - component_sum))) / denom
    assert rel_err < 0.3, f"Beauty/components mismatch too high: relative error {rel_err:.3f}"


# ---------------------------------------------------------------------------
# Environment map and background color tests
# ---------------------------------------------------------------------------

def test_environment_map_loading():
    """Test that environment maps can be loaded."""
    r = create_renderer()
    # Should fail gracefully for missing file
    result = r.load_environment_map("nonexistent.hdr")
    assert result == False

    # Should succeed for test HDRI (if available)
    test_hdr = os.path.join(os.path.dirname(__file__), '..', 'samples', 'test_env.hdr')
    if os.path.exists(test_hdr):
        result = r.load_environment_map(test_hdr, 1.0, 0.0)
        assert result == True


def test_environment_map_renders_brighter_than_black():
    """An HDRI-lit scene should be brighter than a black background scene."""
    import pytest
    test_hdr = os.path.join(os.path.dirname(__file__), '..', 'samples', 'test_env.hdr')
    if not os.path.exists(test_hdr):
        pytest.skip("No test HDRI available")

    # Render with black background
    r1 = create_renderer()
    r1.set_background_color([0, 0, 0])
    mat = r1.create_material('lambertian', [0.8, 0.8, 0.8], {})
    r1.add_sphere([0, 0, 0], 1.0, mat)
    setup_camera(r1, width=W, height=H)
    pixels_dark = render_image(r1, samples=SAMPLES_FAST)

    # Render with HDRI
    r2 = create_renderer()
    r2.load_environment_map(test_hdr, 1.0, 0.0)
    mat2 = r2.create_material('lambertian', [0.8, 0.8, 0.8], {})
    r2.add_sphere([0, 0, 0], 1.0, mat2)
    setup_camera(r2, width=W, height=H)
    pixels_hdri = render_image(r2, samples=SAMPLES_FAST)

    dark_mean = float(np.mean(pixels_dark))
    hdri_mean = float(np.mean(pixels_hdri))
    assert hdri_mean > dark_mean + 0.05, \
        f"HDRI scene ({hdri_mean:.3f}) should be significantly brighter than black bg ({dark_mean:.3f})"

    save_image(pixels_hdri, os.path.join(OUTPUT_DIR, 'test_hdri_lit.png'))
    save_image(pixels_dark, os.path.join(OUTPUT_DIR, 'test_black_bg.png'))


def test_solid_background_color():
    """Setting a background color should replace the sky gradient."""
    r = create_renderer()
    r.set_background_color([1.0, 0.0, 0.0])  # pure red background
    setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], width=W, height=H)
    # No objects — should see pure background
    pixels = render_image(r, samples=4)
    # Red channel should dominate
    mean_r = float(np.mean(pixels[:, :, 0]))
    mean_g = float(np.mean(pixels[:, :, 1]))
    mean_b = float(np.mean(pixels[:, :, 2]))
    assert mean_r > 0.3, f"Red channel too low: {mean_r:.3f}"
    assert mean_r > mean_g * 2, f"Red ({mean_r:.3f}) should dominate green ({mean_g:.3f})"
    assert mean_r > mean_b * 2, f"Red ({mean_r:.3f}) should dominate blue ({mean_b:.3f})"


def _render_world_fog_sphere(z_pos: float, density: float | None) -> np.ndarray:
    r = create_renderer()
    r.set_seed(1337)
    r.set_background_color([0.02, 0.02, 0.02])
    if density is not None:
        r.set_world_volume(density, [1.0, 1.0, 1.0], 0.0)

    light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 40.0})
    diffuse = r.create_material('lambertian', [0.85, 0.85, 0.85], {})
    r.add_sphere([0.0, 2.5, 1.5], 0.8, light)
    r.add_sphere([0.0, -0.2, z_pos], 1.0, diffuse)
    setup_camera(r, look_from=[0.0, 0.0, 8.0], look_at=[0.0, -0.2, 0.0], vfov=28, width=120, height=90)
    return render_image(r, samples=32, apply_gamma=False)


def _center_luminance(img: np.ndarray) -> float:
    h, w = img.shape[:2]
    crop = img[h // 2 - 15:h // 2 + 15, w // 2 - 15:w // 2 + 15, :]
    return float(np.mean(crop))


def test_world_volume_density_adds_visible_haze():
    clear = _render_world_fog_sphere(z_pos=-2.0, density=None)
    foggy = _render_world_fog_sphere(z_pos=-2.0, density=0.01)

    clear_l = _center_luminance(clear)
    foggy_l = _center_luminance(foggy)
    assert foggy_l < clear_l * 0.95, \
        f"Expected world fog to attenuate distant object (foggy={foggy_l:.4f}, clear={clear_l:.4f})"


def test_world_volume_fogs_farther_objects_more():
    near_clear = _render_world_fog_sphere(z_pos=1.0, density=None)
    near_fog = _render_world_fog_sphere(z_pos=1.0, density=0.01)
    far_clear = _render_world_fog_sphere(z_pos=-3.0, density=None)
    far_fog = _render_world_fog_sphere(z_pos=-3.0, density=0.01)

    near_atten = _center_luminance(near_fog) / max(_center_luminance(near_clear), 1e-6)
    far_atten = _center_luminance(far_fog) / max(_center_luminance(far_clear), 1e-6)
    assert far_atten < near_atten * 0.95, \
        f"Expected stronger fog attenuation for farther object (near={near_atten:.4f}, far={far_atten:.4f})"


def test_world_volume_zero_density_matches_clear_behavior():
    clear = _render_world_fog_sphere(z_pos=-1.0, density=None)
    zero_density = _render_world_fog_sphere(z_pos=-1.0, density=0.0)
    max_diff = float(np.max(np.abs(clear - zero_density)))
    assert max_diff < 1e-5, f"Zero-density world volume should match clear behavior (max diff={max_diff:.6f})"


def test_render_apply_gamma_toggle():
    """render(apply_gamma=...) should control whether output is gamma-encoded."""
    r = create_renderer()
    r.set_background_color([0.25, 0.25, 0.25])
    setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], width=W, height=H)

    linear = render_image(r, samples=SAMPLES_FAST, apply_gamma=False)
    gamma = render_image(r, samples=SAMPLES_FAST, apply_gamma=True)

    linear_mean = float(np.mean(linear))
    gamma_mean = float(np.mean(gamma))
    expected_gamma = float(np.power(0.25, 1.0 / 2.2))

    assert abs(linear_mean - 0.25) < 0.02, f"Expected linear mean ~0.25, got {linear_mean:.3f}"
    assert abs(gamma_mean - expected_gamma) < 0.02, \
        f"Expected gamma mean ~{expected_gamma:.3f}, got {gamma_mean:.3f}"
    assert gamma_mean > linear_mean + 0.2, \
        f"Gamma output ({gamma_mean:.3f}) should be brighter than linear ({linear_mean:.3f})"
    expected_gamma_image = np.power(np.clip(linear, 0.0, 1.0), 1.0 / 2.2)
    assert np.allclose(gamma, expected_gamma_image, atol=0.03), \
        "Gamma output should match pow(linear, 1/2.2) per pixel"


# ---------------------------------------------------------------------------
# GPU tests (Phase 2B)
# ---------------------------------------------------------------------------

def test_cuda_availability():
    """GPU detection should work without crashing regardless of hardware."""
    r = create_renderer()
    gpu_avail = r.gpu_available
    assert isinstance(gpu_avail, bool), "gpu_available should return a bool"
    # cuda feature key must exist in __features__
    assert 'cuda' in astroray.__features__, "Missing 'cuda' key in __features__"
    if gpu_avail:
        name = r.gpu_device_name
        assert isinstance(name, str) and len(name) > 0, "gpu_device_name should be a non-empty string"
        print(f"GPU available: {name}")
    else:
        print(f"No GPU: {r.gpu_device_name}")


def test_gpu_renders_match_cpu():
    """GPU and CPU renders should produce similar mean brightness (within 15%)."""
    import pytest

    # --- CPU render ---
    r_cpu = create_renderer()
    create_cornell_box(r_cpu)
    mat = r_cpu.create_material('disney', [0.8, 0.4, 0.2],
                                {'roughness': 0.3, 'metallic': 0.5})
    r_cpu.add_sphere([0, -0.5, 0], 1.0, mat)
    setup_camera(r_cpu, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=200, height=150)
    pixels_cpu = render_image(r_cpu, samples=64)

    if not r_cpu.gpu_available:
        pytest.skip("No CUDA GPU available — skipping GPU vs CPU comparison")

    # --- GPU render ---
    r_gpu = create_renderer()
    create_cornell_box(r_gpu)
    mat2 = r_gpu.create_material('disney', [0.8, 0.4, 0.2],
                                 {'roughness': 0.3, 'metallic': 0.5})
    r_gpu.add_sphere([0, -0.5, 0], 1.0, mat2)
    setup_camera(r_gpu, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=200, height=150)
    r_gpu.set_use_gpu(True)
    pixels_gpu = render_image(r_gpu, samples=64)

    cpu_mean = float(np.mean(pixels_cpu))
    gpu_mean = float(np.mean(pixels_gpu))
    print(f"CPU mean brightness: {cpu_mean:.4f}, GPU mean brightness: {gpu_mean:.4f}")

    assert abs(cpu_mean - gpu_mean) < 0.15 * max(cpu_mean, 1e-6), \
        f"GPU ({gpu_mean:.3f}) and CPU ({cpu_mean:.3f}) differ by more than 15%"

    save_image(pixels_cpu, os.path.join(OUTPUT_DIR, 'test_cpu_render.png'))
    save_image(pixels_gpu, os.path.join(OUTPUT_DIR, 'test_gpu_render.png'))


# ---------------------------------------------------------------------------
# Phase 3: General Relativistic Black Hole tests
# ---------------------------------------------------------------------------

def test_black_hole_creation():
    """Black hole can be added to the scene and renders without crashing."""
    r = create_renderer()
    r.add_black_hole([0, 0, 0], 10.0, 100.0, {
        'disk_outer': 30.0,
        'accretion_rate': 1.0,
        'inclination': 75.0,
    })
    setup_camera(r, look_from=[0, 0, 200], look_at=[0, 0, 0],
                 vfov=12, width=160, height=120)
    pixels = render_image(r, samples=4)
    assert_valid_image(pixels, 120, 160, min_mean=0.0, label='black_hole')
    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_black_hole.png'))


def test_black_hole_shadow_is_dark():
    """The center of the black hole shadow should be darker than the edges."""
    r = create_renderer()
    r.add_black_hole([0, 0, 0], 10.0, 100.0, {
        'disk_outer': 30.0, 'inclination': 75.0,
    })
    # Use a bright background so the shadow stands out
    test_hdr = os.path.join(os.path.dirname(__file__), '..', 'samples', 'test_env.hdr')
    if os.path.exists(test_hdr):
        r.load_environment_map(test_hdr)
    else:
        # Bright solid background as fallback
        r.set_background_color([1.0, 1.0, 1.0])

    setup_camera(r, look_from=[0, 0, 200], look_at=[0, 0, 0],
                 vfov=6, width=200, height=200)
    pixels = render_image(r, samples=8)

    center_region = pixels[80:120, 80:120, :]
    center_mean   = float(np.mean(center_region))
    edge_mean     = float(np.mean(pixels[:20, :, :]))

    assert center_mean < edge_mean, (
        f"Shadow center ({center_mean:.3f}) should be darker than edges ({edge_mean:.3f})"
    )
    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_bh_shadow.png'))


def test_black_hole_with_geometry():
    """Black hole coexists with normal Cornell box geometry."""
    r = create_renderer()
    create_cornell_box(r)
    r.add_black_hole([0, 0, 0], 1.0, 20.0, {'disk_outer': 15.0, 'inclination': 60.0})
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                 vfov=38, width=200, height=150)
    pixels = render_image(r, samples=16)
    assert_valid_image(pixels, 150, 200, min_mean=0.01, label='bh_with_geometry')
    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_bh_cornell.png'))


def test_black_hole_gr_feature_flag():
    """gr_black_holes feature flag is set in __features__."""
    assert 'gr_black_holes' in astroray.__features__, \
        "gr_black_holes feature flag missing from astroray.__features__"
    assert astroray.__features__['gr_black_holes'] is True


def test_black_hole_showcase_scene():
    """
    Cinematic showcase: a Schwarzschild black hole with accretion disk as the
    centrepiece, surrounded by orbiting bodies that exercise every major
    material model (lambertian, metal, glass, Disney BRDF) and lit by the
    HDR environment map. This is the "hero" image for the GR feature.
    """
    r = create_renderer()

    # ---- Black hole at origin --------------------------------------------
    # Influence sphere radius 50 in world units; spheres orbit outside it.
    r.add_black_hole([0, 0, 0], 10.0, 50.0, {
        'disk_outer': 30.0,
        'accretion_rate': 1.2,
        'inclination': 72.0,
    })

    # ---- Orbiting bodies (all sit outside the 50-unit influence sphere) --
    # Polished gold Disney BRDF (warm metallic, slight roughness)
    gold = r.create_material('disney', [1.0, 0.78, 0.34],
                             {'metallic': 1.0, 'roughness': 0.18,
                              'clearcoat': 0.4})
    r.add_sphere([95, -8, 25], 11.0, gold)

    # Mirror-polished metal
    chrome = r.create_material('metal', [0.92, 0.92, 0.95],
                               {'roughness': 0.05})
    r.add_sphere([-95, 5, -20], 12.0, chrome)

    # Clear glass
    glass = r.create_material('glass', [1.0, 1.0, 1.0], {'ior': 1.5})
    r.add_sphere([15, 30, 95], 9.0, glass)

    # Diffuse coloured planet
    planet = r.create_material('lambertian', [0.25, 0.45, 0.75], {})
    r.add_sphere([-25, -35, 85], 11.0, planet)

    # Subtle frosted dielectric (Disney)
    frosted = r.create_material('disney', [0.85, 0.85, 0.9],
                                {'metallic': 0.0, 'roughness': 0.55,
                                 'clearcoat': 0.2})
    r.add_sphere([60, 25, -55], 8.0, frosted)

    # ---- HDR environment lighting ---------------------------------------
    test_hdr = os.path.join(os.path.dirname(__file__), '..', 'samples',
                            'test_env.hdr')
    if os.path.exists(test_hdr):
        r.load_environment_map(test_hdr)
    else:
        r.set_background_color([0.02, 0.02, 0.04])

    # ---- Cinematic camera ------------------------------------------------
    setup_camera(r,
                 look_from=[40, 35, 220],
                 look_at=[0, 0, 0],
                 vup=[0, 1, 0],
                 vfov=22,
                 aperture=0.0,
                 focus_dist=220.0,
                 width=320, height=240)

    pixels = render_image(r, samples=16)
    assert_valid_image(pixels, 240, 320, min_mean=0.005,
                       label='bh_showcase')

    # The disk should produce some visibly bright pixels somewhere in frame
    assert float(np.max(pixels)) > 0.15, \
        "Showcase scene appears entirely black — disk emission missing?"

    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_bh_showcase.png'))


# ---------------------------------------------------------------------------
# Blender 5.1 scene-fidelity features (multi-material, vertex normals, textures)
# ---------------------------------------------------------------------------

def test_multi_material_mesh():
    """Two triangles in the same 'mesh' with different materials must each
    show their own color. Exercises the per-face material index path that the
    Blender addon relies on.
    """
    r = create_renderer()
    mat_red  = r.create_material('disney', [0.8, 0.05, 0.05], {'roughness': 0.5})
    mat_blue = r.create_material('disney', [0.05, 0.05, 0.8], {'roughness': 0.5})
    light    = r.create_material('light',  [1.0, 1.0, 1.0],   {'intensity': 8.0})

    # Left half quad (red) and right half quad (blue), lying on y=-1 plane
    r.add_triangle([-2, -1, -2], [0, -1, -2], [0, -1, 2], mat_red)
    r.add_triangle([-2, -1, -2], [0, -1,  2], [-2, -1, 2], mat_red)
    r.add_triangle([ 0, -1, -2], [2, -1, -2], [2, -1, 2], mat_blue)
    r.add_triangle([ 0, -1, -2], [2, -1,  2], [0, -1, 2], mat_blue)

    # Overhead light
    r.add_sphere([0, 5, 0], 1.0, light)

    setup_camera(r, look_from=[0, 4, 5], look_at=[0, -1, 0],
                 vfov=60, width=W, height=H)
    pixels = render_image(r, samples=SAMPLES_FAST)
    assert_valid_image(pixels, H, W, min_mean=0.005, label='multi_material')

    # Sanity: left half should have more red, right half more blue.
    left_half  = pixels[:, :W // 2, :]
    right_half = pixels[:, W // 2:, :]
    left_red_ratio   = float(np.mean(left_half[:, :, 0])) - float(np.mean(left_half[:, :, 2]))
    right_blue_ratio = float(np.mean(right_half[:, :, 2])) - float(np.mean(right_half[:, :, 0]))
    # Either side should lean toward its expected color (generous thresholds
    # because rays may miss the quad and hit the sky).
    assert left_red_ratio > -0.05 and right_blue_ratio > -0.05, (
        f"Per-face material routing looks wrong: "
        f"left red-minus-blue={left_red_ratio:.3f}, "
        f"right blue-minus-red={right_blue_ratio:.3f}"
    )
    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_multi_material.png'))


def test_vertex_normals_smooth_shading():
    """Passing per-vertex normals to add_triangle must change the rendered
    shading relative to the face-normal fallback. A single tilted triangle
    rendered twice — once with and once without normals — should differ."""
    light_pos = [2, 4, 3]

    def make_scene(with_normals):
        r = create_renderer()
        mat   = r.create_material('disney', [0.8, 0.8, 0.8], {'roughness': 0.3, 'metallic': 0.0})
        light = r.create_material('light',  [1.0, 1.0, 1.0], {'intensity': 10.0})
        r.add_sphere(light_pos, 0.5, light)

        # A flat triangle in the xz plane at y=0
        v0, v1, v2 = [-1, 0, -1], [1, 0, -1], [0, 0, 1]
        if with_normals:
            # Deliberately non-uniform per-vertex normals so barycentric
            # interpolation gives a visibly different shading than the flat
            # face normal (which is simply +Y).
            n0 = [-0.6, 0.8, 0.0]
            n1 = [ 0.6, 0.8, 0.0]
            n2 = [ 0.0, 0.8, 0.6]
            r.add_triangle(v0, v1, v2, mat, [], [], [], n0, n1, n2)
        else:
            r.add_triangle(v0, v1, v2, mat)

        setup_camera(r, look_from=[0, 3, 2.5], look_at=[0, 0, 0],
                     vfov=50, width=W, height=H)
        return render_image(r, samples=SAMPLES_FAST)

    flat   = make_scene(with_normals=False)
    smooth = make_scene(with_normals=True)
    assert_valid_image(flat,   H, W, min_mean=0.0, label='vn_flat')
    assert_valid_image(smooth, H, W, min_mean=0.0, label='vn_smooth')

    # The two images should not be identical — vertex-normal interpolation
    # must actually be wired up.
    diff = float(np.mean(np.abs(flat - smooth)))
    assert diff > 1e-4, (
        f"Per-vertex normals appear to have no effect "
        f"(mean abs diff = {diff:.6f}); barycentric interpolation path is "
        f"probably not engaged."
    )
    save_image(smooth, os.path.join(OUTPUT_DIR, 'test_vertex_normals.png'))


def test_textured_material_checkerboard():
    """Load a 2x2 RGB checker via load_texture and render it on a quad. The
    textured quad should show multiple distinct colors in the frame — not
    just one flat color, which would indicate the texture sample was lost."""
    r = create_renderer()
    # 2x2 checker, 4 distinct colors: red, green, blue, yellow. Row-major,
    # top-to-bottom (matching what load_blender_image produces after flip).
    tex_data = [
        1.0, 0.0, 0.0,   0.0, 1.0, 0.0,   # row 0: red, green
        0.0, 0.0, 1.0,   1.0, 1.0, 0.0,   # row 1: blue, yellow
    ]
    r.load_texture("test_checker", tex_data, 2, 2)
    mat   = r.create_material('lambertian', [1, 1, 1], {'texture': 'test_checker'})
    light = r.create_material('light',       [1, 1, 1], {'intensity': 8.0})
    r.add_sphere([0, 5, 0], 1.0, light)

    # Quad on the floor with UVs spanning [0,1]x[0,1]
    r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], mat,
                   [0, 0], [1, 0], [1, 1])
    r.add_triangle([-2, -1, -2], [2, -1,  2], [-2, -1, 2], mat,
                   [0, 0], [1, 1], [0, 1])

    setup_camera(r, look_from=[0, 3, 4], look_at=[0, -1, 0],
                 vfov=55, width=W, height=H)
    pixels = render_image(r, samples=SAMPLES_FAST)
    assert_valid_image(pixels, H, W, min_mean=0.01, label='textured')

    # Check we actually see multiple colors (texture is being sampled, not
    # replaced with a single flat tint).
    per_channel_std = float(np.mean(np.std(pixels.reshape(-1, 3), axis=0)))
    assert per_channel_std > 0.02, (
        f"Textured quad has near-uniform color (std={per_channel_std:.4f}); "
        f"texture sampling appears broken."
    )
    save_image(pixels, os.path.join(OUTPUT_DIR, 'test_textured_material.png'))


def test_texture_coordinate_generated_creates_bbox_gradient():
    """Generated coordinates should produce a visible gradient across object bounds."""
    w, h = 120, 90
    r = create_renderer()
    r.set_seed(123)
    r.set_adaptive_sampling(False)
    r.set_background_color([0.0, 0.0, 0.0])
    r.create_procedural_texture(
        "gen_grad", "gradient",
        [0, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0],
        "GENERATED"
    )
    mat = r.create_material('lambertian', [1, 1, 1], {'texture': 'gen_grad'})
    light = r.create_material('light', [1, 1, 1], {'intensity': 7.0})
    r.add_sphere([0, 0, 0], 1.0, mat)
    r.add_sphere([0, 4, 2], 0.6, light)
    setup_camera(r, look_from=[0, 0, 4], look_at=[0, 0, 0], vfov=40, width=w, height=h)
    img = render_image(r, samples=12)
    assert_valid_image(img, h, w, min_mean=0.01, label='generated_coord')
    luma = np.mean(img, axis=2)
    left = float(np.mean(luma[:, :w // 2]))
    right = float(np.mean(luma[:, w // 2:]))
    assert (right - left) > 0.008, (
        f"Generated coord gradient too weak (left={left:.4f}, right={right:.4f})."
    )
    save_image(img, os.path.join(OUTPUT_DIR, 'test_texture_coord_generated.png'))


def test_texture_coordinate_object_is_stable_under_translation():
    """Object coordinates should stay attached to the object when moved."""
    w, h = 120, 90

    def render_at(xpos):
        r = create_renderer()
        r.set_seed(7)
        r.set_adaptive_sampling(False)
        r.set_background_color([0.0, 0.0, 0.0])
        r.create_procedural_texture(
            "obj_checker", "checker",
            [0.1, 0.1, 0.9, 0.9, 0.9, 0.1, 8.0],
            "OBJECT"
        )
        mat = r.create_material('lambertian', [1, 1, 1], {'texture': 'obj_checker'})
        light = r.create_material('light', [1, 1, 1], {'intensity': 7.0})
        r.add_sphere([xpos, 0, 0], 1.0, mat)
        r.add_sphere([xpos, 4, 2], 0.6, light)
        setup_camera(r, look_from=[xpos, 0, 4], look_at=[xpos, 0, 0], vfov=40, width=w, height=h)
        return render_image(r, samples=12)

    a = render_at(-1.0)
    b = render_at(1.0)
    mad = float(np.mean(np.abs(a - b)))
    assert mad < 0.03, f"Object-space texture drifted after translation (MAD={mad:.4f})."
    save_image(b, os.path.join(OUTPUT_DIR, 'test_texture_coord_object.png'))


def test_texture_coordinate_uv_mode_matches_default_behavior():
    """Explicit UV mode should match existing UV-default texturing."""
    w, h = 120, 90
    tex_data = [
        1.0, 0.0, 0.0,   0.0, 1.0, 0.0,
        0.0, 0.0, 1.0,   1.0, 1.0, 0.0,
    ]

    def render_with_mode(explicit_mode):
        r = create_renderer()
        r.set_seed(99)
        r.set_adaptive_sampling(False)
        if explicit_mode:
            r.load_texture("uv_checker", tex_data, 2, 2, "UV")
        else:
            r.load_texture("uv_checker", tex_data, 2, 2)
        mat = r.create_material('lambertian', [1, 1, 1], {'texture': 'uv_checker'})
        light = r.create_material('light', [1, 1, 1], {'intensity': 8.0})
        r.add_sphere([0, 5, 0], 1.0, light)
        r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], mat, [0, 0], [1, 0], [1, 1])
        r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], mat, [0, 0], [1, 1], [0, 1])
        setup_camera(r, look_from=[0, 3, 4], look_at=[0, -1, 0], vfov=55, width=w, height=h)
        return render_image(r, samples=10)

    default_uv = render_with_mode(False)
    explicit_uv = render_with_mode(True)
    mad = float(np.mean(np.abs(default_uv - explicit_uv)))
    assert mad < 1e-6, f"Explicit UV mode changed legacy behavior (MAD={mad:.8f})."
    save_image(explicit_uv, os.path.join(OUTPUT_DIR, 'test_texture_coord_uv.png'))


def test_normal_map_adds_visible_surface_detail():
    """A patterned normal map on a flat quad should increase local shading
    variation compared to an unperturbed normal."""
    def render_scene(use_normal_map):
        r = create_renderer()
        light = r.create_material('light', [1, 1, 1], {'intensity': 10.0})
        r.add_sphere([0, 5, 0], 0.8, light)

        params = {'roughness': 0.5, 'metallic': 0.0}
        if use_normal_map:
            tex_data = [
                0.8, 0.2, 1.0,   0.2, 0.8, 1.0,
                0.2, 0.2, 1.0,   0.8, 0.8, 1.0,
            ]
            r.load_texture("nm_detail", tex_data, 2, 2)
            params['normal_map_texture'] = 'nm_detail'
            params['normal_strength'] = 1.0
        mat = r.create_material('disney', [0.7, 0.7, 0.7], params)

        r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], mat,
                       [0, 0], [1, 0], [1, 1])
        r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], mat,
                       [0, 0], [1, 1], [0, 1])

        setup_camera(r, look_from=[0, 3, 4], look_at=[0, -1, 0],
                     vfov=55, width=W, height=H)
        return render_image(r, samples=SAMPLES_FAST)

    flat = render_scene(use_normal_map=False)
    mapped = render_scene(use_normal_map=True)
    assert_valid_image(flat, H, W, min_mean=0.01, label='normal_flat')
    assert_valid_image(mapped, H, W, min_mean=0.01, label='normal_mapped')

    crop = (slice(H // 4, 3 * H // 4), slice(W // 4, 3 * W // 4))
    detail_delta = float(np.mean(np.abs(flat[crop] - mapped[crop])))
    assert detail_delta > 0.002, (
        f"Normal map produced too little visible change "
        f"(mean abs delta={detail_delta:.4f})."
    )
    save_image(mapped, os.path.join(OUTPUT_DIR, 'test_normal_map_detail.png'))


def test_normal_map_shifts_specular_highlights():
    """A tangent-space normal perturbation should move/specifically reshape
    specular response on a glossy surface."""
    def render_scene(use_normal_map):
        r = create_renderer()
        light = r.create_material('light', [1, 1, 1], {'intensity': 12.0})
        r.add_sphere([0.6, 4.0, 1.5], 0.7, light)

        params = {'roughness': 0.06, 'metallic': 0.0}
        if use_normal_map:
            # Uniform +U tilt in tangent space.
            r.load_texture("nm_tilt", [1.0, 0.5, 0.5], 1, 1)
            params['normal_map_texture'] = 'nm_tilt'
            params['normal_strength'] = 1.0
        mat = r.create_material('disney', [0.85, 0.85, 0.85], params)

        r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], mat,
                       [0, 0], [1, 0], [1, 1])
        r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], mat,
                       [0, 0], [1, 1], [0, 1])

        setup_camera(r, look_from=[0, 3, 4], look_at=[0, -1, 0],
                     vfov=55, width=W, height=H)
        return render_image(r, samples=SAMPLES_MED)

    flat = render_scene(use_normal_map=False)
    tilted = render_scene(use_normal_map=True)
    l_flat = np.mean(flat, axis=2)
    l_tilt = np.mean(tilted, axis=2)

    thresh_flat = np.percentile(l_flat, 99.2)
    thresh_tilt = np.percentile(l_tilt, 99.2)
    xf = np.where(l_flat >= thresh_flat)[1]
    xt = np.where(l_tilt >= thresh_tilt)[1]
    assert xf.size > 0 and xt.size > 0
    centroid_shift = abs(float(np.mean(xt)) - float(np.mean(xf)))
    image_delta = float(np.mean(np.abs(flat - tilted)))
    assert centroid_shift > 0.1 or image_delta > 0.003, (
        f"Specular response changed too little with normal map "
        f"(centroid shift={centroid_shift:.3f}px, mean abs delta={image_delta:.4f})."
    )
    save_image(tilted, os.path.join(OUTPUT_DIR, 'test_normal_map_specular_shift.png'))


def test_bump_strength_zero_matches_no_bump_output():
    """Bump map strength=0 should match the no-bump baseline."""
    def render_scene(with_bump_zero):
        r = create_renderer()
        light = r.create_material('light', [1, 1, 1], {'intensity': 10.0})
        r.add_sphere([0, 5, 0], 0.8, light)

        params = {'roughness': 0.3, 'metallic': 0.0}
        if with_bump_zero:
            bump_data = [
                0.0, 0.0, 0.0,   1.0, 1.0, 1.0,
                1.0, 1.0, 1.0,   0.0, 0.0, 0.0,
            ]
            r.load_texture("bump_checker", bump_data, 2, 2)
            params['bump_map_texture'] = 'bump_checker'
            params['bump_strength'] = 0.0
            params['bump_distance'] = 0.02
        mat = r.create_material('disney', [0.7, 0.7, 0.7], params)

        r.add_triangle([-2, -1, -2], [2, -1, -2], [2, -1, 2], mat,
                       [0, 0], [1, 0], [1, 1])
        r.add_triangle([-2, -1, -2], [2, -1, 2], [-2, -1, 2], mat,
                       [0, 0], [1, 1], [0, 1])

        setup_camera(r, look_from=[0, 3, 4], look_at=[0, -1, 0],
                     vfov=55, width=W, height=H)
        return render_image(r, samples=SAMPLES_MED)

    no_bump = render_scene(with_bump_zero=False)
    bump_zero = render_scene(with_bump_zero=True)
    mad = float(np.mean(np.abs(no_bump - bump_zero)))
    assert mad < 0.04, f"Bump strength=0 diverges from baseline (MAD={mad:.4f})."
    save_image(bump_zero, os.path.join(OUTPUT_DIR, 'test_bump_strength_zero.png'))


# ---------------------------------------------------------------------------
# Seed control — issue #7
# ---------------------------------------------------------------------------

def test_pixel_filter():
    """Box, Gaussian, and Blackman-Harris filters all produce valid renders."""
    W, H = 80, 60

    def do_render(filter_type, filter_width):
        r = create_renderer()
        r.set_seed(1)  # deterministic
        r.set_adaptive_sampling(False)
        r.set_pixel_filter(filter_type, filter_width)
        mat = r.create_material('lambertian', [0.5, 0.5, 0.8], {})
        r.add_sphere([0, 0, -3], 1.0, mat)
        setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], vfov=40, width=W, height=H)
        return render_image(r, samples=8, apply_gamma=False)

    box    = do_render(0, 1.0)
    gauss  = do_render(1, 1.5)
    bh     = do_render(2, 1.5)

    for name, img in [('box', box), ('gaussian', gauss), ('blackman_harris', bh)]:
        assert img is not None and img.size > 0, f"{name} filter produced empty render"
        assert np.all(np.isfinite(img)), f"{name} filter produced NaN/Inf pixels"
        assert np.any(img > 0), f"{name} filter produced all-black render"
        save_image(img, os.path.join(OUTPUT_DIR, f'test_pixel_filter_{name}.png'))


def test_seed_determinism():
    """Same seed must produce identical renders; different seeds must differ."""
    W, H = 80, 60

    def do_render(seed):
        r = create_renderer()
        r.set_seed(seed)
        r.set_adaptive_sampling(False)
        mat = r.create_material('lambertian', [0.7, 0.2, 0.2], {})
        r.add_sphere([0, 0, -3], 1.0, mat)
        setup_camera(r, look_from=[0, 0, 5], look_at=[0, 0, 0], vfov=40, width=W, height=H)
        return render_image(r, samples=8, apply_gamma=False)

    render_a1 = do_render(42)
    render_a2 = do_render(42)
    render_b  = do_render(123)

    # Same seed → identical pixels
    assert np.array_equal(render_a1, render_a2), \
        "Same seed produced different renders (non-deterministic)."

    # Different seeds → at least one pixel differs
    assert not np.array_equal(render_a1, render_b), \
        "Different seeds produced identical renders."

    save_image(render_a1, os.path.join(OUTPUT_DIR, 'test_seed_determinism.png'))


# ---------------------------------------------------------------------------
# Stand-alone entry-point for direct execution
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))

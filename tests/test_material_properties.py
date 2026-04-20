#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Material property tests.

Each test isolates one physically-meaningful property and makes a quantitative
assertion. Tests are grouped by material type.

Scene helpers used:
  _neutral_scene  — white floor + overhead panel light, no colored walls.
                    Good for color fidelity and energy tests.
  _side_light_scene — ground + single small point light from upper-right.
                    Good for specular and roughness tests.
  _backdrop_scene — colored back wall + overhead light.
                    Good for glass transparency tests.

Run with:  pytest tests/test_material_properties.py -v
"""

import sys
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'build'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import astroray
from base_helpers import (
    create_renderer, setup_camera, render_image,
    save_image, save_figure, create_cornell_box,
    assert_valid_image, get_output_dir,
)

OUTPUT_DIR = get_output_dir()
W, H = 160, 120


# ---------------------------------------------------------------------------
# Scene builders
# ---------------------------------------------------------------------------

def _neutral_scene(r, mat=None):
    """White floor + overhead panel light. No colored walls.
    Camera: look_from=[0,0,3], look_at=[0,0,0], vfov=40."""
    white = r.create_material('lambertian', [0.9, 0.9, 0.9], {})
    light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 8.0})
    r.add_triangle([-6, -1, -6], [6, -1, -6], [6, -1,  6], white)
    r.add_triangle([-6, -1, -6], [6, -1,  6], [-6, -1, 6], white)
    r.add_triangle([-1.5, 4, -1.5], [1.5, 4, -1.5], [1.5, 4, 1.5], light)
    r.add_triangle([-1.5, 4, -1.5], [1.5, 4,  1.5], [-1.5, 4, 1.5], light)
    if mat is not None:
        r.add_sphere([0, 0, 0], 1.0, mat)


def _side_light_scene(r, mat):
    """Ground + single small point light from upper-right.
    Camera: look_from=[0,0,3.5], look_at=[0,0,0], vfov=38."""
    ground = r.create_material('lambertian', [0.4, 0.4, 0.4], {})
    light  = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 15.0})
    r.add_triangle([-6, -1, -6], [6, -1, -6], [6, -1,  6], ground)
    r.add_triangle([-6, -1, -6], [6, -1,  6], [-6, -1, 6], ground)
    r.add_sphere([2.5, 3.5, 1.5], 0.3, light)
    r.add_sphere([0, 0, 0], 1.0, mat)


def _side_light_scene_specular_probe(r, mat):
    """Variant of _side_light_scene with stronger glancing highlight.
    Used for specular-vs-diffuse discrimination checks."""
    ground = r.create_material('lambertian', [0.4, 0.4, 0.4], {})
    light  = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 25.0})
    r.add_triangle([-6, -1, -6], [6, -1, -6], [6, -1,  6], ground)
    r.add_triangle([-6, -1, -6], [6, -1,  6], [-6, -1, 6], ground)
    r.add_sphere([2.5, 2.8, 1.5], 0.3, light)
    r.add_sphere([0, 0, 0], 1.0, mat)


def _backdrop_scene(r, mat, backdrop_color):
    """Colored back wall at z=-2.5 + overhead light.
    Camera: look_from=[0,0,3.5], look_at=[0,0,0], vfov=38."""
    wall  = r.create_material('lambertian', backdrop_color, {})
    light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 8.0})
    r.add_triangle([-4, -4, -2.5], [4, -4, -2.5], [4,  4, -2.5], wall)
    r.add_triangle([-4, -4, -2.5], [4,  4, -2.5], [-4, 4, -2.5], wall)
    r.add_triangle([-1, 4, -1], [1, 4, -1], [1, 4,  1], light)
    r.add_triangle([-1, 4, -1], [1, 4,  1], [-1, 4, 1], light)
    r.add_sphere([0, 0, 0], 0.85, mat)


def _cam_front(r):
    setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0], vfov=40, width=W, height=H)


def _cam_side(r):
    setup_camera(r, look_from=[0, 0, 3.5], look_at=[0, 0, 0], vfov=38, width=W, height=H)


def _center(pixels, frac=0.45):
    """Center crop — predominantly sphere pixels when sphere fills most of frame."""
    r0 = int(H * (0.5 - frac / 2));  r1 = int(H * (0.5 + frac / 2))
    c0 = int(W * (0.5 - frac / 2));  c1 = int(W * (0.5 + frac / 2))
    return pixels[r0:r1, c0:c1]


# ===========================================================================
# GROUP 1 — Lambertian
# ===========================================================================

def test_lambertian_color_fidelity():
    """Pure R/G/B Lambertian spheres must dominate their respective channel."""
    results = {}
    for name, albedo in [('red',   [1.0, 0.0, 0.0]),
                         ('green', [0.0, 1.0, 0.0]),
                         ('blue',  [0.0, 0.0, 1.0])]:
        r = create_renderer()
        mat = r.create_material('lambertian', albedo, {})
        _neutral_scene(r, mat)
        _cam_front(r)
        pixels = render_image(r, samples=32)
        assert_valid_image(pixels, H, W, label=f'lambertian_{name}')
        center = _center(pixels, frac=0.45)
        results[name] = center.mean(axis=(0, 1))   # mean [R, G, B]
        save_image(pixels, os.path.join(OUTPUT_DIR, f'mat_lambertian_{name}.png'))

    r_r, r_g, r_b = results['red']
    g_r, g_g, g_b = results['green']
    b_r, b_g, b_b = results['blue']

    assert r_r > r_g * 2.5, \
        f"Red sphere: R ({r_r:.3f}) should be >2.5× G ({r_g:.3f})"
    assert r_r > r_b * 2.5, \
        f"Red sphere: R ({r_r:.3f}) should be >2.5× B ({r_b:.3f})"
    assert g_g > g_r * 2.5, \
        f"Green sphere: G ({g_g:.3f}) should be >2.5× R ({g_r:.3f})"
    assert g_g > g_b * 2.5, \
        f"Green sphere: G ({g_g:.3f}) should be >2.5× B ({g_b:.3f})"
    assert b_b > b_r * 2.0, \
        f"Blue sphere: B ({b_b:.3f}) should be >2.0× R ({b_r:.3f})"
    assert b_b > b_g * 1.5, \
        f"Blue sphere: B ({b_b:.3f}) should be >1.5× G ({b_g:.3f})"


def test_lambertian_albedo_brightness_scales():
    """Higher albedo Lambertian → brighter sphere center (monotonic)."""
    means = {}
    for val in [0.15, 0.50, 0.85]:
        r = create_renderer()
        mat = r.create_material('lambertian', [val, val, val], {})
        _neutral_scene(r, mat)
        _cam_front(r)
        pixels = render_image(r, samples=48)
        means[val] = float(np.mean(_center(pixels, frac=0.45)))

    assert means[0.50] > means[0.15] * 1.3, \
        f"albedo 0.5 ({means[0.50]:.3f}) should be >1.3× albedo 0.15 ({means[0.15]:.3f})"
    assert means[0.85] > means[0.50] * 1.15, \
        f"albedo 0.85 ({means[0.85]:.3f}) should be >1.15× albedo 0.5 ({means[0.50]:.3f})"


# ===========================================================================
# GROUP 2 — Metal
# ===========================================================================

def test_metal_differs_from_lambertian():
    """Metal and Lambertian with the same albedo must look clearly different."""
    def render(mat_type, params):
        r = create_renderer()
        mat = r.create_material(mat_type, [0.8, 0.8, 0.8], params)
        _side_light_scene_specular_probe(r, mat)
        _cam_side(r)
        return render_image(r, samples=64)

    px_lamb  = render('lambertian', {})
    px_metal = render('metal', {'roughness': 0.2})
    assert_valid_image(px_lamb,  H, W, label='lambertian_vs_metal_ref')
    assert_valid_image(px_metal, H, W, label='metal_vs_lambertian')

    c_lamb = _center(px_lamb, frac=0.55)
    c_metal = _center(px_metal, frac=0.55)
    mse = float(np.mean((c_lamb - c_metal) ** 2))
    assert mse > 0.005, \
        f"Metal and Lambertian center-crop too similar (MSE={mse:.5f}); Metal may not be working"


def test_metal_roughness_affects_appearance():
    """Each roughness level must produce a visually distinct image."""
    images = {}
    for rval in [0.05, 0.2, 0.5]:
        r = create_renderer()
        mat = r.create_material('metal', [0.85, 0.85, 0.85], {'roughness': rval})
        _side_light_scene(r, mat)
        _cam_side(r)
        images[rval] = render_image(r, samples=64)
        assert_valid_image(images[rval], H, W, label=f'metal_r{rval}')
        save_image(images[rval], os.path.join(OUTPUT_DIR, f'mat_metal_r{rval:.2f}.png'))

    mse_a = float(np.mean((images[0.05] - images[0.20]) ** 2))
    mse_b = float(np.mean((images[0.20] - images[0.50]) ** 2))
    assert mse_a > 5e-4, \
        f"Metal roughness 0.05 vs 0.2: MSE={mse_a:.5f} — roughness has no effect"
    assert mse_b > 5e-4, \
        f"Metal roughness 0.2 vs 0.5: MSE={mse_b:.5f} — roughness has no effect"


def test_smooth_metal_has_tighter_specular_peak():
    """Smooth metal concentrates light into a bright spot; rough metal spreads it.
    Under a single point light, smooth metal must have a higher peak pixel value."""
    def render_roughness(rval):
        r = create_renderer()
        mat = r.create_material('metal', [0.9, 0.9, 0.9], {'roughness': rval})
        _side_light_scene(r, mat)
        _cam_side(r)
        return render_image(r, samples=96)

    px_smooth = render_roughness(0.05)
    px_rough  = render_roughness(0.50)
    assert_valid_image(px_smooth, H, W, label='metal_smooth')
    assert_valid_image(px_rough,  H, W, label='metal_rough')

    max_smooth = float(np.max(px_smooth))
    max_rough  = float(np.max(px_rough))

    assert max_smooth > 0.6, \
        f"Smooth metal has no visible specular highlight (max={max_smooth:.3f}); " \
        f"Metal::eval or Metal::sample may be broken"
    assert max_smooth > max_rough, \
        f"Smooth metal peak ({max_smooth:.3f}) should exceed rough metal peak ({max_rough:.3f})"

    fig, axes = plt.subplots(1, 2, figsize=(8, 4))
    axes[0].imshow(np.clip(px_smooth, 0, 1))
    axes[0].set_title(f'Smooth (r=0.05)\npeak={max_smooth:.2f}')
    axes[0].axis('off')
    axes[1].imshow(np.clip(px_rough, 0, 1))
    axes[1].set_title(f'Rough (r=0.5)\npeak={max_rough:.2f}')
    axes[1].axis('off')
    plt.tight_layout()
    save_figure(fig, os.path.join(OUTPUT_DIR, 'mat_metal_roughness_comparison.png'))


def test_metal_albedo_tints_reflection():
    """Gold-albedo metal must produce a warmer (higher R/B) reflection than silver."""
    def render_metal(albedo):
        r = create_renderer()
        mat = r.create_material('metal', albedo, {'roughness': 0.1})
        _side_light_scene(r, mat)
        _cam_side(r)
        return render_image(r, samples=64)

    px_gold   = render_metal([0.95, 0.75, 0.15])
    px_silver = render_metal([0.90, 0.90, 0.90])
    assert_valid_image(px_gold,   H, W, label='metal_gold')
    assert_valid_image(px_silver, H, W, label='metal_silver')

    def rb_ratio(px):
        c = _center(px, frac=0.45)
        return float(np.mean(c[:, :, 0])) / (float(np.mean(c[:, :, 2])) + 1e-6)

    rb_gold   = rb_ratio(px_gold)
    rb_silver = rb_ratio(px_silver)

    assert rb_gold > rb_silver + 0.02, \
        f"Gold metal R/B ({rb_gold:.3f}) should exceed silver R/B ({rb_silver:.3f}) by at least 0.02"

    fig, axes = plt.subplots(1, 2, figsize=(8, 4))
    axes[0].imshow(np.clip(px_gold, 0, 1))
    axes[0].set_title(f'Gold metal\nR/B={rb_gold:.2f}')
    axes[0].axis('off')
    axes[1].imshow(np.clip(px_silver, 0, 1))
    axes[1].set_title(f'Silver metal\nR/B={rb_silver:.2f}')
    axes[1].axis('off')
    plt.tight_layout()
    save_figure(fig, os.path.join(OUTPUT_DIR, 'mat_metal_tint.png'))


# ===========================================================================
# GROUP 3 — Glass / Dielectric
# ===========================================================================

def test_glass_transmits_background_color():
    """Glass sphere in front of a bright green wall must transmit that green.
    Center pixels through glass must be greener than through an opaque sphere."""
    backdrop = [0.1, 0.9, 0.2]   # bright green

    def render_center_green(mat_type, params):
        r = create_renderer()
        color = [1, 1, 1] if mat_type == 'glass' else [0.7, 0.7, 0.7]
        mat = r.create_material(mat_type, color, params)
        _backdrop_scene(r, mat, backdrop)
        _cam_side(r)
        pixels = render_image(r, samples=64)
        assert_valid_image(pixels, H, W, label=f'glass_backdrop_{mat_type}')
        c = _center(pixels, frac=0.40)
        return float(np.mean(c[:, :, 1]) / (np.mean(c) + 1e-6)), pixels

    gr_glass,  px_glass  = render_center_green('glass',      {'ior': 1.5})
    gr_opaque, px_opaque = render_center_green('lambertian', {})

    save_image(px_glass,  os.path.join(OUTPUT_DIR, 'mat_glass_transparent.png'))
    save_image(px_opaque, os.path.join(OUTPUT_DIR, 'mat_glass_vs_opaque.png'))

    assert gr_glass > gr_opaque + 0.05, \
        f"Glass sphere green ratio ({gr_glass:.3f}) should exceed opaque sphere " \
        f"({gr_opaque:.3f}) by at least 0.05 — glass may not be transmitting"


def test_glass_ior_changes_appearance():
    """Different IOR values must produce visually distinct images."""
    images = {}
    for ior_val in [1.2, 1.5, 2.0]:
        r = create_renderer()
        mat = r.create_material('glass', [1, 1, 1], {'ior': ior_val})
        _backdrop_scene(r, mat, [0.7, 0.3, 0.1])
        _cam_side(r)
        images[ior_val] = render_image(r, samples=64)
        assert_valid_image(images[ior_val], H, W, label=f'glass_ior{ior_val}')
        save_image(images[ior_val],
                   os.path.join(OUTPUT_DIR, f'mat_glass_ior{ior_val:.1f}.png'))

    mse_a = float(np.mean((images[1.2] - images[1.5]) ** 2))
    mse_b = float(np.mean((images[1.5] - images[2.0]) ** 2))
    assert mse_a > 1e-4, \
        f"Glass IOR 1.2 vs 1.5 are identical (MSE={mse_a:.6f}) — IOR parameter has no effect"
    assert mse_b > 1e-4, \
        f"Glass IOR 1.5 vs 2.0 are identical (MSE={mse_b:.6f}) — IOR parameter has no effect"


def test_glass_less_opaque_than_black():
    """Glass sphere must transmit more light than a fully opaque black sphere
    in the same scene. Tests that Dielectric::sample is actually producing
    transmitted paths (not absorbing all light)."""
    # Large bright backdrop so glass always sees it regardless of lens distortion
    def build_large_backdrop(r, mat, backdrop_color):
        wall  = r.create_material('lambertian', backdrop_color, {})
        light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 8.0})
        r.add_triangle([-20, -20, -3], [20, -20, -3], [20,  20, -3], wall)
        r.add_triangle([-20, -20, -3], [20,  20, -3], [-20, 20, -3], wall)
        r.add_triangle([-1, 4, -1], [1, 4, -1], [1, 4,  1], light)
        r.add_triangle([-1, 4, -1], [1, 4,  1], [-1, 4, 1], light)
        r.add_sphere([0, 0, 0], 0.85, mat)

    def render_center_mean(mat_type, color, params):
        r = create_renderer()
        mat = r.create_material(mat_type, color, params)
        build_large_backdrop(r, mat, [0.9, 0.9, 0.9])
        _cam_side(r)
        pixels = render_image(r, samples=48)
        return float(np.mean(_center(pixels, frac=0.40)))

    mean_glass = render_center_mean('glass',      [1, 1, 1], {'ior': 1.5})
    mean_black = render_center_mean('lambertian', [0, 0, 0], {})

    assert mean_glass > mean_black + 0.1, \
        f"Glass sphere center ({mean_glass:.3f}) should be clearly brighter than " \
        f"black opaque sphere ({mean_black:.3f}) — glass may not be transmitting"


# ===========================================================================
# GROUP 4 — Disney BRDF
# ===========================================================================

def test_disney_metallic_tints_specular_highlight():
    """metallic must noticeably change bright-pixel color balance vs dielectric."""
    gold = [0.95, 0.80, 0.15]

    def render_disney(metallic_val):
        r = create_renderer()
        mat = r.create_material('disney', gold,
                                {'metallic': metallic_val, 'roughness': 0.15})
        _side_light_scene_specular_probe(r, mat)
        _cam_side(r)
        return render_image(r, samples=96)

    px_metal = render_disney(1.0)
    px_dielectric = render_disney(0.0)
    assert_valid_image(px_metal,      H, W, label='disney_metallic1')
    assert_valid_image(px_dielectric, H, W, label='disney_metallic0')

    def specular_rb(px, top_percentile=99.0):
        """R/B ratio in top-luminance center pixels — approximates the highlight."""
        c = _center(px, frac=0.55)
        lum = 0.2126 * c[:, :, 0] + 0.7152 * c[:, :, 1] + 0.0722 * c[:, :, 2]
        cutoff = np.percentile(lum, top_percentile)
        mask = lum >= cutoff
        r_mean = float(c[:, :, 0][mask].mean())
        b_mean = float(c[:, :, 2][mask].mean()) + 1e-6
        return r_mean / b_mean

    rb_metal = specular_rb(px_metal)
    rb_diel  = specular_rb(px_dielectric)

    assert abs(rb_metal - rb_diel) > 0.10, \
        f"metallic=1 and metallic=0 bright-pixel R/B are too close " \
        f"({rb_metal:.3f} vs {rb_diel:.3f})"

    mse = float(np.mean((px_metal - px_dielectric) ** 2))
    assert mse > 0.002, \
        f"metallic=1 and metallic=0 renders too similar (MSE={mse:.5f})"

    fig, axes = plt.subplots(1, 2, figsize=(8, 4))
    axes[0].imshow(np.clip(px_metal, 0, 1))
    axes[0].set_title(f'metallic=1  R/B={rb_metal:.2f}')
    axes[0].axis('off')
    axes[1].imshow(np.clip(px_dielectric, 0, 1))
    axes[1].set_title(f'metallic=0  R/B={rb_diel:.2f}')
    axes[1].axis('off')
    plt.tight_layout()
    save_figure(fig, os.path.join(OUTPUT_DIR, 'mat_disney_metallic_vs_dielectric.png'))


def test_disney_roughness_changes_glossiness():
    """Disney roughness sweep must produce distinct images; smooth variant must
    have a higher specular peak than the rough variant."""
    images = {}
    for rval in [0.05, 0.30, 0.70]:
        r = create_renderer()
        mat = r.create_material('disney', [0.8, 0.6, 0.4],
                                {'metallic': 0.7, 'roughness': rval})
        _side_light_scene(r, mat)
        _cam_side(r)
        images[rval] = render_image(r, samples=64)
        assert_valid_image(images[rval], H, W, label=f'disney_r{rval}')
        save_image(images[rval],
                   os.path.join(OUTPUT_DIR, f'mat_disney_r{rval:.2f}.png'))

    mse_lo_mid = float(np.mean((images[0.05] - images[0.30]) ** 2))
    mse_mid_hi = float(np.mean((images[0.30] - images[0.70]) ** 2))
    assert mse_lo_mid > 5e-4, \
        f"Disney roughness 0.05 vs 0.3 MSE={mse_lo_mid:.5f} — roughness has no effect"
    assert mse_mid_hi > 5e-4, \
        f"Disney roughness 0.3 vs 0.7 MSE={mse_mid_hi:.5f} — roughness has no effect"

    smooth_center = _center(images[0.05], frac=0.45)
    rough_center = _center(images[0.70], frac=0.45)
    smooth_contrast = float(np.percentile(smooth_center, 99.5) - np.percentile(smooth_center, 50))
    rough_contrast = float(np.percentile(rough_center, 99.5) - np.percentile(rough_center, 50))

    assert smooth_contrast > rough_contrast + 0.003, \
        "Smooth Disney (r=0.05) should show stronger highlight contrast than rough (r=0.7)"


def test_disney_clearcoat_adds_gloss():
    """Clearcoat=1 must produce a higher specular peak than clearcoat=0 on a
    rough diffuse base (rough base alone has a low peak; clearcoat adds one).
    Uses a darker base color and slightly higher spp to reduce stochastic noise."""
    min_p99p5_delta = 0.001
    min_bright_mean_delta = 0.003
    bright_pixel_percentile = 98.5

    y_coords, x_coords = np.mgrid[0:H, 0:W]
    cy, cx = H * 0.5, W * 0.5
    radius = min(H, W) * 0.30
    sphere_mask = ((x_coords - cx) ** 2 + (y_coords - cy) ** 2) <= radius ** 2

    def render_clearcoat(coat_val):
        r = create_renderer()
        mat = r.create_material('disney', [0.1, 0.1, 0.1],
                                {'metallic': 0.0, 'roughness': 0.85,
                                 'clearcoat': coat_val, 'clearcoat_gloss': 1.0})
        _side_light_scene_specular_probe(r, mat)
        _cam_side(r)
        # Slightly higher spp for stable percentile comparisons on highlight pixels.
        return render_image(r, samples=128)

    px_no_coat = render_clearcoat(0.0)
    px_coat    = render_clearcoat(1.0)
    assert_valid_image(px_no_coat, H, W, label='no_clearcoat')
    assert_valid_image(px_coat,    H, W, label='clearcoat')

    lum_no_coat = (0.2126 * px_no_coat[:, :, 0] +
                   0.7152 * px_no_coat[:, :, 1] +
                   0.0722 * px_no_coat[:, :, 2])
    lum_coat = (0.2126 * px_coat[:, :, 0] +
                0.7152 * px_coat[:, :, 1] +
                0.0722 * px_coat[:, :, 2])

    sph_no_coat = lum_no_coat[sphere_mask]
    sph_coat = lum_coat[sphere_mask]
    rgb_no_coat = px_no_coat[sphere_mask]
    rgb_coat = px_coat[sphere_mask]

    p99_no_coat = float(np.percentile(sph_no_coat, 99.5))
    p99_coat = float(np.percentile(sph_coat, 99.5))
    bright_threshold_no_coat = np.percentile(sph_no_coat, bright_pixel_percentile)
    bright_threshold_coat = np.percentile(sph_coat, bright_pixel_percentile)
    bright_no_coat = sph_no_coat[sph_no_coat >= bright_threshold_no_coat]
    bright_coat = sph_coat[sph_coat >= bright_threshold_coat]
    bright_mean_no_coat = float(np.mean(bright_no_coat))
    bright_mean_coat = float(np.mean(bright_coat))

    assert p99_coat > p99_no_coat + min_p99p5_delta, \
        f"Clearcoat=1 sphere p99.5 luminance ({p99_coat:.3f}) should exceed clearcoat=0 " \
        f"({p99_no_coat:.3f}) by at least {min_p99p5_delta:.3f} — clearcoat may not be contributing"
    assert bright_mean_coat > bright_mean_no_coat + min_bright_mean_delta, \
        f"Clearcoat=1 bright-pixel mean ({bright_mean_coat:.3f}) should exceed clearcoat=0 " \
        f"({bright_mean_no_coat:.3f}) by at least {min_bright_mean_delta:.3f}"

    mse = float(np.mean((rgb_no_coat - rgb_coat) ** 2))
    assert mse > 5e-5, \
        f"Clearcoat has no visible effect on sphere pixels (MSE={mse:.6f})"

    fig, axes = plt.subplots(1, 2, figsize=(8, 4))
    axes[0].imshow(np.clip(px_no_coat, 0, 1))
    axes[0].set_title(f'Clearcoat=0\nsphere p99.5={p99_no_coat:.2f}')
    axes[0].axis('off')
    axes[1].imshow(np.clip(px_coat, 0, 1))
    axes[1].set_title(f'Clearcoat=1\nsphere p99.5={p99_coat:.2f}')
    axes[1].axis('off')
    plt.tight_layout()
    save_figure(fig, os.path.join(OUTPUT_DIR, 'mat_disney_clearcoat.png'))


def test_disney_transmission_passes_light():
    """Disney material with transmission=1 must transmit the backdrop color,
    just like a glass sphere (green backdrop → green-tinted sphere center)."""
    backdrop = [0.1, 0.9, 0.2]

    def render_center_green(mat_type, params):
        r = create_renderer()
        color = [1, 1, 1] if mat_type == 'disney' else [0.7, 0.7, 0.7]
        mat = r.create_material(mat_type, color, params)
        _backdrop_scene(r, mat, backdrop)
        _cam_side(r)
        pixels = render_image(r, samples=64)
        assert_valid_image(pixels, H, W, label=f'disney_trans_{mat_type}')
        c = _center(pixels, frac=0.40)
        return float(np.mean(c[:, :, 1]) / (np.mean(c) + 1e-6))

    gr_trans  = render_center_green('disney',     {'transmission': 1.0, 'ior': 1.5})
    gr_opaque = render_center_green('lambertian', {})

    assert gr_trans > gr_opaque + 0.03, \
        f"Disney transmission sphere green ratio ({gr_trans:.3f}) should exceed " \
        f"opaque sphere ({gr_opaque:.3f}) — transmission may not be working"


# ===========================================================================
# GROUP 5 — DiffuseLight
# ===========================================================================

def test_light_intensity_scales_scene_brightness():
    """Higher light intensity must produce a clearly brighter scene.
    Uses an enclosed Cornell box to minimise the constant sky background
    so intensity changes are clearly visible."""
    def render_mean(intensity):
        r = create_renderer()
        # Build Cornell box walls (no default light)
        white = r.create_material('lambertian', [0.73, 0.73, 0.73], {})
        red   = r.create_material('lambertian', [0.65, 0.05, 0.05], {})
        green = r.create_material('lambertian', [0.12, 0.45, 0.15], {})
        light = r.create_material('light', [1.0, 0.9, 0.8], {'intensity': intensity})
        r.add_triangle([-2,-2,-2],[2,-2,-2],[2,-2,2],  white)   # floor
        r.add_triangle([-2,-2,-2],[2,-2,2], [-2,-2,2], white)
        r.add_triangle([-2,2,-2], [-2,2,2], [2,2,2],   white)   # ceiling
        r.add_triangle([-2,2,-2], [2,2,2],  [2,2,-2],  white)
        r.add_triangle([-2,-2,-2],[-2,2,-2],[2,2,-2],  red)     # left wall
        r.add_triangle([-2,-2,-2],[-2,2,2], [-2,2,-2], red)
        r.add_triangle([2,-2,-2], [2,2,-2], [2,2,2],   green)   # right wall
        r.add_triangle([2,-2,-2], [2,2,2],  [2,-2,2],  green)
        r.add_triangle([-0.5,1.98,-0.5],[0.5,1.98,-0.5],[0.5,1.98,0.5],  light)
        r.add_triangle([-0.5,1.98,-0.5],[0.5,1.98,0.5], [-0.5,1.98,0.5], light)
        mat = r.create_material('lambertian', [0.73, 0.73, 0.73], {})
        r.add_sphere([0, -0.5, 0], 0.8, mat)
        setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                     vfov=38, width=W, height=H)
        return float(np.mean(render_image(r, samples=48)))

    mean_low  = render_mean(3.0)
    mean_high = render_mean(15.0)   # 5× brighter

    assert mean_high > mean_low * 1.3, \
        f"5× intensity (mean={mean_high:.3f}) is not clearly brighter than " \
        f"1× intensity (mean={mean_low:.3f}) — light intensity may have no effect"


def test_light_emits_only_from_front_face():
    """DiffuseLight emits only from its front face (direct ray hits).
    A camera looking directly at the front face must see bright emission;
    looking at the back face must see near-sky-background darkness.

    Note: NEE (sampleDirect) does not check frontFace, so the test measures
    direct camera visibility of the emitter panel, not scene brightness."""
    def render_center_mean(face_toward_camera: bool):
        r = create_renderer()
        light = r.create_material('light', [1.0, 1.0, 1.0], {'intensity': 5.0})
        if face_toward_camera:
            # CCW winding from camera at z=3 → front face normal (0,0,+1) toward camera
            r.add_triangle([-0.5,-0.5,0],[0.5,-0.5,0],[0.5,0.5,0],  light)
            r.add_triangle([-0.5,-0.5,0],[0.5, 0.5,0],[-0.5,0.5,0], light)
        else:
            # Reversed winding → front face normal (0,0,-1) away from camera
            r.add_triangle([-0.5, 0.5,0],[0.5,0.5,0],[0.5,-0.5,0],  light)
            r.add_triangle([-0.5, 0.5,0],[0.5,-0.5,0],[-0.5,-0.5,0],light)
        setup_camera(r, look_from=[0, 0, 3], look_at=[0, 0, 0],
                     vfov=20, width=W, height=H)
        pixels = render_image(r, samples=16)
        return float(np.mean(_center(pixels, frac=0.3)))

    mean_front = render_center_mean(face_toward_camera=True)
    mean_back  = render_center_mean(face_toward_camera=False)

    assert mean_front > 0.5, \
        f"Camera-facing light panel center should be very bright (mean={mean_front:.3f}) " \
        f"— DiffuseLight may not emit toward the camera"
    assert mean_back < mean_front * 0.5, \
        f"Back-facing panel center ({mean_back:.3f}) should be ≤50% of front-facing " \
        f"({mean_front:.3f}) — front-face-only emission may be broken"


# ===========================================================================
# GROUP 6 — Energy conservation / no overexposure
# ===========================================================================

def test_no_material_is_overexposed():
    """In the standard Cornell box, every material must stay within a sane
    brightness range. mean >= 0.9 indicates a broken BRDF (energy not conserved);
    mean <= 0.08 indicates the material is effectively black."""
    materials = [
        ('lambertian',       'lambertian', [0.8, 0.6, 0.4], {}),
        ('metal_smooth',     'metal',      [0.9, 0.9, 0.9], {'roughness': 0.05}),
        ('metal_rough',      'metal',      [0.8, 0.5, 0.2], {'roughness': 0.60}),
        ('glass',            'glass',      [1.0, 1.0, 1.0], {'ior': 1.5}),
        ('disney_metallic',  'disney',     [0.9, 0.7, 0.2], {'metallic': 1.0, 'roughness': 0.2}),
        ('disney_plastic',   'disney',     [0.7, 0.3, 0.3], {'metallic': 0.0, 'roughness': 0.5}),
        ('disney_clearcoat', 'disney',     [0.5, 0.4, 0.8], {'clearcoat': 1.0, 'roughness': 0.6}),
        ('disney_glass',     'disney',     [1.0, 1.0, 1.0], {'transmission': 1.0, 'ior': 1.5}),
    ]

    for name, mat_type, color, params in materials:
        r = create_renderer()
        create_cornell_box(r)
        mat = r.create_material(mat_type, color, params)
        r.add_sphere([0, -0.5, 0], 1.0, mat)
        setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0],
                     vfov=38, width=W, height=H)
        pixels = render_image(r, samples=64)
        mean_val = float(np.mean(pixels))
        save_image(pixels, os.path.join(OUTPUT_DIR, f'mat_overexposure_{name}.png'))

        assert mean_val < 0.90, \
            f"{name}: mean {mean_val:.3f} ≥ 0.90 — BRDF likely broken (energy not conserved)"
        assert mean_val > 0.08, \
            f"{name}: mean {mean_val:.3f} ≤ 0.08 — material appears black (BRDF returns zero)"


def test_white_lambertian_is_brightest_diffuse():
    """A white Lambertian sphere (albedo=1) must be at least as bright as any
    other same-albedo Lambertian in the same scene. Tests the BRDF energy ceiling."""
    scene_means = {}
    for name, albedo in [('white', [1.0, 1.0, 1.0]),
                         ('red',   [1.0, 0.0, 0.0]),
                         ('green', [0.0, 1.0, 0.0]),
                         ('blue',  [0.0, 0.0, 1.0])]:
        r = create_renderer()
        mat = r.create_material('lambertian', albedo, {})
        _neutral_scene(r, mat)
        _cam_front(r)
        pixels = render_image(r, samples=48)
        scene_means[name] = float(np.mean(_center(pixels, frac=0.45)))

    white_mean = scene_means['white']
    for name in ('red', 'green', 'blue'):
        assert scene_means[name] <= white_mean * 1.05, \
            f"Lambertian {name} ({scene_means[name]:.3f}) exceeds white ({white_mean:.3f}) " \
            f"— violates energy conservation"


# ===========================================================================
# GROUP 7 — Energy conservation / no overexposure for Metal
# ===========================================================================

def test_metal_energy_conservation():
    """Metal material should conserve energy."""
    def render_mean(metallic: float) -> np.ndarray:
        r = create_renderer()
        r.set_background_color([0.0, 0.0, 0.0])
        setup_camera(r, look_from=[0, 0, 4], look_at=[0, 0, 0], width=W, height=H)
        mat = r.create_material('metal', [0.8, 0.3, 0.3], {'metallic': metallic})
        r.add_sphere([0, -0.5, 0], 1.0, mat)
        pixels = render_image(r, samples=SAMPLES_FAST)
        mean = np.mean(pixels, axis=(0, 1))
        return mean

    # Test with metallic=0 (diffuse) and metallic=1 (metallic)
    diff_mean = render_mean(0.0)
    metal_mean = render_mean(1.0)

    # Energy should be conserved, so the means should be close
    assert np.allclose(diff_mean, metal_mean, atol=1e-2), "Energy conservation failed for Metal material"

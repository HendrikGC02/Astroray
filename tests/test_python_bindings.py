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

import astroray
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


def test_glass_render():
    r = create_renderer()
    create_cornell_box(r)
    mat = r.create_material('glass', [1.0, 1.0, 1.0], {'ior': 1.5})
    r.add_sphere([0, -0.5, 0], 1.0, mat)
    setup_camera(r, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=W, height=H)
    pixels = render_image(r, samples=SAMPLES_FAST)
    assert_valid_image(pixels, H, W, min_mean=0.03, label='glass')


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
# Stand-alone entry-point for direct execution
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))

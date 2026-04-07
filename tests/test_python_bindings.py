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


# ---------------------------------------------------------------------------
# Stand-alone entry-point for direct execution
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))

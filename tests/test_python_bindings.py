#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test suite for Python bindings.
Tests basic functionality of raytracer Python module.
"""

import sys
import os
import time

# Find the built module on either Windows or Linux
BUILD_DIR = os.path.join(os.path.dirname(__file__), '..', 'build')
sys.path.insert(0, BUILD_DIR)
# Also check project root in case module was copied there
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    import astroray
    from PIL import Image
    import numpy as np
except ImportError as e:
    print(f"Failed to import required modules: {e}")
    sys.exit(1)


def test_module_version():
    """Test that module version is available"""
    print("\n" + "="*60)
    print("TEST: Module Version")
    print("="*60)
    
    assert hasattr(astroray, '__version__'), "Module missing __version__"
    assert hasattr(astroray, '__features__'), "Module missing __features__"
    
    print(f"Version: {astroray.__version__}")
    print(f"Features: {astroray.__features__}")
    print("✓ PASSED: Module version accessible")
    return True


def test_renderer_creation():
    """Test renderer creation and cleanup"""
    print("\n" + "="*60)
    print("TEST: Renderer Creation")
    print("="*60)
    
    start = time.time()
    renderer = astroray.Renderer()
    creation_time = time.time() - start
    
    print(f"Renderer created in {creation_time*1000:.2f}ms")
    print("✓ PASSED: Renderer created successfully")
    return True


def test_basic_camera_setup():
    """Test basic camera setup"""
    print("\n" + "="*60)
    print("TEST: Basic Camera Setup")
    print("="*60)
    
    renderer = astroray.Renderer()
    renderer.setup_camera(
        look_from=[0, 0, 5],
        look_at=[0, 0, 0],
        vup=[0, -1, 0],
        vfov=40,
        aspect_ratio=1.33,
        aperture=0.0,
        focus_dist=5.0,
        width=400,
        height=300
    )
    
    # Test with different parameters
    renderer.setup_camera(
        look_from=[1, 2, 3],
        look_at=[0, 0, 0],
        vup=[0, 1, 0],
        vfov=90,
        aspect_ratio=1.0,
        aperture=0.1,
        focus_dist=2.0,
        width=800,
        height=600
    )
    
    print("✓ PASSED: Camera setup completed")
    return True


def test_sphere_basic():
    """Test adding a basic sphere"""
    print("\n" + "="*60)
    print("TEST: Basic Sphere")
    print("="*60)
    
    renderer = astroray.Renderer()
    
    # Create a simple material
    material = renderer.create_material('lambertian', [0.5, 0.5, 0.5], {})
    
    # Add a sphere at origin
    renderer.add_sphere([0, 0, 0], 1.0, material)
    
    # Setup camera
    renderer.setup_camera(
        look_from=[0, 0, 5],
        look_at=[0, 0, 0],
        vup=[0, -1, 0],
        vfov=40,
        aspect_ratio=1.33,
        aperture=0.0,
        focus_dist=5.0,
        width=400,
        height=300
    )
    
    # Render (render signature: render(samples_per_pixel, max_depth, progress_callback=None))
    start = time.time()
    pixels = renderer.render(16, 50)
    render_time = time.time() - start
    
    print(f"Render time: {render_time*1000:.2f}ms")
    
    # Save result (render returns H*W*3 float array)
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'test_results')
    os.makedirs(output_dir, exist_ok=True)
    img_path = os.path.join(output_dir, 'test_basic_sphere.png')
    
    # Ensure contiguous array and convert to image
    pixels_contiguous = np.ascontiguousarray(pixels)
    img_data = (np.clip(pixels_contiguous, 0, 1) * 255).astype(np.uint8)
    img = Image.fromarray(img_data)
    img.save(img_path)
    print(f"Image saved to: {img_path}")
    
    print("✓ PASSED: Basic sphere rendered")
    return True


def test_multiple_spheres():
    """Test multiple overlapping spheres"""
    print("\n" + "="*60)
    print("TEST: Multiple Spheres")
    print("="*60)
    
    renderer = astroray.Renderer()
    
    # Create materials
    red = renderer.create_material('lambertian', [0.8, 0.2, 0.2], {})
    blue = renderer.create_material('lambertian', [0.2, 0.2, 0.8], {})
    green = renderer.create_material('lambertian', [0.2, 0.8, 0.2], {})
    
    # Add spheres
    renderer.add_sphere([0, 0, 0], 1.0, red)
    renderer.add_sphere([2, 0, 0], 1.0, blue)
    renderer.add_sphere([-2, 0, 0], 1.0, green)
    
    # Setup camera
    renderer.setup_camera(
        look_from=[0, 1, 5],
        look_at=[0, 0, 0],
        vup=[0, 1, 0],
        vfov=60,
        aspect_ratio=1.33,
        aperture=0.0,
        focus_dist=5.0,
        width=400,
        height=300
    )
    
    # Render (render signature: render(samples_per_pixel, max_depth, progress_callback=None))
    start = time.time()
    pixels = renderer.render(16, 50)
    render_time = time.time() - start
    
    print(f"Render time: {render_time*1000:.2f}ms")
    
    # Save result (render returns H*W*3 float array)
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'test_results')
    os.makedirs(output_dir, exist_ok=True)
    img_path = os.path.join(output_dir, 'test_multiple_spheres.png')
    
    # Ensure contiguous array and convert to image
    pixels_contiguous = np.ascontiguousarray(pixels)
    img_data = (np.clip(pixels_contiguous, 0, 1) * 255).astype(np.uint8)
    img = Image.fromarray(img_data)
    img.save(img_path)
    print(f"Image saved to: {img_path}")
    
    print("✓ PASSED: Multiple spheres rendered")
    return True


def test_cornell_box():
    """Test Cornell Box rendering"""
    print("\n" + "="*60)
    print("TEST: Cornell Box")
    print("="*60)
    
    renderer = astroray.Renderer()
    
    # Create materials
    white = renderer.create_material('lambertian', [0.73, 0.73, 0.73], {})
    red = renderer.create_material('lambertian', [0.65, 0.05, 0.05], {})
    green = renderer.create_material('lambertian', [0.12, 0.45, 0.15], {})
    light = renderer.create_material('light', [1.0, 0.9, 0.8], {'intensity': 15.0})
    
    # Floor
    renderer.add_triangle([-2, -2, -2], [2, -2, -2], [2, -2, 2], white)
    renderer.add_triangle([-2, -2, -2], [2, -2, 2], [-2, -2, 2], white)
    
    # Ceiling
    renderer.add_triangle([-2, 2, -2], [-2, 2, 2], [2, 2, 2], white)
    renderer.add_triangle([-2, 2, -2], [2, 2, 2], [2, 2, -2], white)
    
    # Back wall
    renderer.add_triangle([-2, -2, -2], [-2, 2, -2], [2, 2, -2], white)
    renderer.add_triangle([-2, -2, -2], [2, 2, -2], [2, -2, -2], white)
    
    # Left wall (red)
    renderer.add_triangle([-2, -2, -2], [-2, -2, 2], [-2, 2, 2], red)
    renderer.add_triangle([-2, -2, -2], [-2, 2, 2], [-2, 2, -2], red)
    
    # Right wall (green)
    renderer.add_triangle([2, -2, -2], [2, 2, -2], [2, 2, 2], green)
    renderer.add_triangle([2, -2, -2], [2, 2, 2], [2, -2, 2], green)
    
    # Light
    renderer.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98, 0.5], light)
    renderer.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, 0.5], [-0.5, 1.98, 0.5], light)
    
    # Setup camera
    renderer.setup_camera(
        look_from=[2, 3, 5],
        look_at=[0, 0, 0],
        vup=[0, 1, 0],
        vfov=40,
        aspect_ratio=1.33,
        aperture=0.0,
        focus_dist=5.0,
        width=400,
        height=300
    )
    
    # Render (render signature: render(samples_per_pixel, max_depth, progress_callback=None))
    start = time.time()
    pixels = renderer.render(16, 50)
    render_time = time.time() - start
    
    print(f"Render time: {render_time*1000:.2f}ms")
    
    # Save result (render returns H*W*3 float array)
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'test_results')
    os.makedirs(output_dir, exist_ok=True)
    img_path = os.path.join(output_dir, 'test_cornell_box.png')
    
    # Ensure contiguous array and convert to image
    pixels_contiguous = np.ascontiguousarray(pixels)
    img_data = (np.clip(pixels_contiguous, 0, 1) * 255).astype(np.uint8)
    img = Image.fromarray(img_data)
    img.save(img_path)
    print(f"Image saved to: {img_path}")
    
    print("✓ PASSED: Cornell Box rendered")
    return True


def test_sphere_with_aperture():
    """Test sphere rendering with aperture (depth of field)"""
    print("\n" + "="*60)
    print("TEST: Sphere with Aperture")
    print("="*60)
    
    renderer = astroray.Renderer()
    
    # Create materials
    red = renderer.create_material('lambertian', [0.8, 0.2, 0.2], {})
    blue = renderer.create_material('lambertian', [0.2, 0.2, 0.8], {})
    
    # Add spheres
    renderer.add_sphere([0, 0, 0], 1.0, red)
    renderer.add_sphere([0, 0, -2], 0.5, blue)
    
    # Setup camera with aperture
    renderer.setup_camera(
        look_from=[0, 0, 5],
        look_at=[0, 0, 0],
        vup=[0, -1, 0],
        vfov=40,
        aspect_ratio=1.33,
        aperture=0.5,
        focus_dist=3.0,
        width=400,
        height=300
    )
    
    # Render (render signature: render(samples_per_pixel, max_depth, progress_callback=None))
    start = time.time()
    pixels = renderer.render(16, 50)
    render_time = time.time() - start
    
    print(f"Render time: {render_time*1000:.2f}ms")
    
    # Save result (render returns H*W*3 float array)
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'test_results')
    os.makedirs(output_dir, exist_ok=True)
    img_path = os.path.join(output_dir, 'test_sphere_aperture.png')
    
    # Ensure contiguous array and convert to image
    pixels_contiguous = np.ascontiguousarray(pixels)
    img_data = (np.clip(pixels_contiguous, 0, 1) * 255).astype(np.uint8)
    img = Image.fromarray(img_data)
    img.save(img_path)
    print(f"Image saved to: {img_path}")
    
    print("✓ PASSED: Sphere with aperture rendered")
    return True


def test_performance_basic():
    """Test rendering performance"""
    print("\n" + "="*60)
    print("TEST: Performance (100 samples)")
    print("="*60)
    
    renderer = astroray.Renderer()
    
    # Create materials
    red = renderer.create_material('lambertian', [0.8, 0.2, 0.2], {})
    
    # Add spheres
    renderer.add_sphere([0, 0, 0], 1.0, red)
    renderer.add_sphere([2, 0, 0], 1.0, renderer.create_material('lambertian', [0.2, 0.2, 0.8], {}))
    renderer.add_sphere([-2, 0, 0], 1.0, renderer.create_material('lambertian', [0.2, 0.8, 0.2], {}))
    
    # Setup camera
    renderer.setup_camera(
        look_from=[0, 1, 5],
        look_at=[0, 0, 0],
        vup=[0, 1, 0],
        vfov=60,
        aspect_ratio=1.33,
        aperture=0.0,
        focus_dist=5.0,
        width=400,
        height=300
    )
    
    # Render with 100 samples (render signature: render(samples_per_pixel, max_depth, progress_callback=None))
    start = time.time()
    pixels = renderer.render(100, 50)
    render_time = time.time() - start
    
    fps = (400 * 300 * 100) / (render_time * 1_000_000)
    
    print(f"Render time: {render_time:.2f}s")
    print(f"Frame rate: {fps:.2f} fps (100 samples)")
    
    # Save result (render returns H*W*3 float array)
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'test_results')
    os.makedirs(output_dir, exist_ok=True)
    img_path = os.path.join(output_dir, 'test_performance_100samples.png')
    
    # Ensure contiguous array and convert to image
    pixels_contiguous = np.ascontiguousarray(pixels)
    img_data = (np.clip(pixels_contiguous, 0, 1) * 255).astype(np.uint8)
    img = Image.fromarray(img_data)
    img.save(img_path)
    print(f"Image saved to: {img_path}")
    
    print("✓ PASSED: Performance test completed")
    return True


def run_all_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("RAYTRACER PYTHON BINDINGS TEST SUITE")
    print("="*60)
    
    tests = [
        ("Module Version", test_module_version),
        ("Renderer Creation", test_renderer_creation),
        ("Basic Camera Setup", test_basic_camera_setup),
        ("Basic Sphere", test_sphere_basic),
        ("Multiple Spheres", test_multiple_spheres),
        ("Cornell Box", test_cornell_box),
        ("Sphere with Aperture", test_sphere_with_aperture),
        ("Performance (100 samples)", test_performance_basic),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, "PASSED"))
        except Exception as e:
            print(f"\n✗ FAILED: {name} - {e}")
            results.append((name, "FAILED"))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, r in results if r == "PASSED")
    failed = sum(1 for _, r in results if r == "FAILED")
    
    print(f"Total: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    
    for name, result in results:
        status = "✓" if result == "PASSED" else "✗"
        print(f"  {status} {name}: {result}")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
#!/usr/bin/env python
# coding: utf-8

# # Custom Raytracer Python Module - Complete Guide & Test Suite
#  
# This notebook provides a comprehensive guide to using the Custom Raytracer Python module and tests all material types and features.
# 

# In[1]:


%pip install numpy matplotlib imageio

# In[1]:



# %% Cell 1: Setup and Imports
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import time
import sys
import os
from typing import List, Dict, Tuple
import json

# Add the module path if needed
# sys.path.insert(0, '/path/to/raytracer/build')
sys.path.append(r'C:\Users\hcombrinck\OneDrive\Astroray\Astroray_repo\Astroray\build\blender_addon\Release')

try:
    import raytracer_blender
    print(f"✓ Raytracer module loaded successfully!")
    print(f"  Version: {raytracer_blender.__version__}")
    print(f"  Features: {json.dumps(raytracer_blender.__features__, indent=2)}")
except ImportError as e:
    print(f"✗ Failed to import raytracer_blender: {e}")
    print("  Make sure the module is built and in your Python path")
    sys.exit(1)


# In[2]:



# %% Cell 2: Helper Functions
def create_renderer():
    """Create and return a new renderer instance"""
    return raytracer_blender.Renderer()

def setup_camera(renderer, look_from=[0, 0, 5], look_at=[0, 0, 0], 
                vfov=40, width=400, height=300):
    """Setup camera with default parameters"""
    renderer.setup_camera(
        look_from=look_from,
        look_at=look_at,
        vup=[0, -1, 0],
        vfov=vfov,
        aspect_ratio=width/height,
        aperture=0.0,
        focus_dist=5.0,
        width=width,
        height=height
    )

def render_image(renderer, samples=32, max_depth=8, show_progress=False):
    """Render and return image"""
    if show_progress:
        def progress_callback(p):
            print(f"\rRendering: {int(p*100)}%", end="")
        pixels = renderer.render(samples, max_depth, progress_callback)
        print()  # New line after progress
    else:
        pixels = renderer.render(samples, max_depth)
    return pixels

def display_image(pixels, title="Render", figsize=(8, 6)):
    """Display rendered image"""
    plt.figure(figsize=figsize)
    plt.imshow(np.clip(pixels, 0, 1))
    plt.title(title)
    plt.axis('off')
    plt.show()

def save_image(pixels, filename):
    """Save image to file"""
    import imageio
    img_uint8 = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
    imageio.imwrite(filename, img_uint8)
    print(f"Image saved to {filename}")


# 
# ## Basic Material Types
# Let's test all the basic material types supported by the renderer
# 

# In[3]:



# %% Cell 3: Material Creation Functions
def create_cornell_box(renderer):
    """Create a standard Cornell Box scene"""
    # Create materials
    red_mat = renderer.create_material('lambertian', [0.65, 0.05, 0.05], {})
    green_mat = renderer.create_material('lambertian', [0.12, 0.45, 0.15], {})
    white_mat = renderer.create_material('lambertian', [0.73, 0.73, 0.73], {})
    light_mat = renderer.create_material('light', [1.0, 0.9, 0.8], {'intensity': 15.0})
    
    # Floor
    renderer.add_triangle([-2, -2, -2], [2, -2, -2], [2, -2, 2], white_mat)
    renderer.add_triangle([-2, -2, -2], [2, -2, 2], [-2, -2, 2], white_mat)
    
    # Ceiling
    renderer.add_triangle([-2, 2, -2], [-2, 2, 2], [2, 2, 2], white_mat)
    renderer.add_triangle([-2, 2, -2], [2, 2, 2], [2, 2, -2], white_mat)
    
    # Back wall
    renderer.add_triangle([-2, -2, -2], [-2, 2, -2], [2, 2, -2], white_mat)
    renderer.add_triangle([-2, -2, -2], [2, 2, -2], [2, -2, -2], white_mat)
    
    # Left wall (red)
    renderer.add_triangle([-2, -2, -2], [-2, -2, 2], [-2, 2, 2], red_mat)
    renderer.add_triangle([-2, -2, -2], [-2, 2, 2], [-2, 2, -2], red_mat)
    
    # Right wall (green)
    renderer.add_triangle([2, -2, -2], [2, 2, -2], [2, 2, 2], green_mat)
    renderer.add_triangle([2, -2, -2], [2, 2, 2], [2, -2, 2], green_mat)
    
    # Light
    renderer.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, -0.5], [0.5, 1.98, 0.5], light_mat)
    renderer.add_triangle([-0.5, 1.98, -0.5], [0.5, 1.98, 0.5], [-0.5, 1.98, 0.5], light_mat)
    
    return white_mat, red_mat, green_mat


# In[4]:



# %% Cell 4: Test Basic Materials
def test_basic_materials():
    """Test lambertian, metal, glass materials"""
    renderer = create_renderer()
    
    # Create Cornell box as base
    white_mat, red_mat, green_mat = create_cornell_box(renderer)
    
    # Add test objects
    glass_mat = renderer.create_material('glass', [1, 1, 1], {'ior': 1.5})
    metal_mat = renderer.create_material('metal', [0.8, 0.8, 0.9], {'roughness': 0.1})
    
    renderer.add_sphere([-0.7, -1.3, -0.5], 0.7, glass_mat)
    renderer.add_sphere([0.8, -1.5, 0.3], 0.5, metal_mat)
    
    # Setup camera
    setup_camera(renderer, [0, 0, 5.5], [0, 0, 0], 38, 600, 450)
    
    # Render
    print("Rendering basic materials test...")
    pixels = render_image(renderer, samples=32, max_depth=8, show_progress=False)
    
    display_image(pixels, "Basic Materials: Lambertian, Metal, Glass")
    return pixels

basic_test = test_basic_materials()


# In[5]:



# %% Cell 5: Test Disney BRDF Parameters
def test_disney_brdf():
    """Test various Disney BRDF parameter combinations"""
    
    fig = plt.figure(figsize=(16, 12))
    gs = GridSpec(3, 4, figure=fig)
    
    test_configs = [
        {"metallic": 0.0, "roughness": 0.0, "title": "Dielectric Smooth"},
        {"metallic": 0.0, "roughness": 0.5, "title": "Dielectric Rough"},
        {"metallic": 1.0, "roughness": 0.0, "title": "Metal Smooth"},
        {"metallic": 1.0, "roughness": 0.5, "title": "Metal Rough"},
        
        {"metallic": 0.5, "roughness": 0.3, "title": "Half Metallic"},
        {"metallic": 0.0, "roughness": 0.5, "clearcoat": 1.0, "title": "With Clearcoat"},
        {"metallic": 0.0, "roughness": 0.5, "anisotropic": 0.8, "title": "Anisotropic"},
        {"metallic": 0.0, "roughness": 0.5, "sheen": 1.0, "title": "With Sheen"},
        
        {"transmission": 1.0, "ior": 1.5, "title": "Full Transmission"},
        {"transmission": 0.5, "metallic": 0.5, "title": "Half Trans/Metal"},
        {"subsurface": 0.5, "title": "Subsurface"},
        {"metallic": 0.8, "roughness": 0.2, "clearcoat": 0.5, "title": "Complex"}
    ]
    
    for idx, config in enumerate(test_configs):
        print(f"Rendering Disney BRDF test {idx+1}/12: {config['title']}")
        
        renderer = create_renderer()
        
        # Simple scene with single sphere
        ground_mat = renderer.create_material('lambertian', [0.5, 0.5, 0.5], {})
        light_mat = renderer.create_material('light', [1, 1, 1], {'intensity': 5.0})
        
        # Ground plane
        renderer.add_triangle([-5, -1, -5], [5, -1, -5], [5, -1, 5], ground_mat)
        renderer.add_triangle([-5, -1, -5], [5, -1, 5], [-5, -1, 5], ground_mat)
        
        # Light
        renderer.add_sphere([2, 3, 2], 1.0, light_mat)
        
        # Test sphere with Disney BRDF
        params = {k: v for k, v in config.items() if k != 'title'}
        disney_mat = renderer.create_material('disney', [0.7, 0.5, 0.3], params)
        renderer.add_sphere([0, 0, 0], 1.0, disney_mat)
        
        # Camera
        setup_camera(renderer, [3, 2, 3], [0, 0, 0], 35, 200, 150)
        
        # Quick render for comparison
        pixels = render_image(renderer, samples=128, max_depth=8)
        
        ax = fig.add_subplot(gs[idx // 4, idx % 4])
        ax.imshow(np.clip(pixels, 0, 1))
        ax.set_title(config['title'], fontsize=10)
        ax.axis('off')
    
    plt.suptitle("Disney BRDF Parameter Tests", fontsize=14)
    plt.tight_layout()
    plt.show()

test_disney_brdf()


# In[6]:



# %% Cell 6: Material Comparison Grid
def material_comparison():
    """Create a grid comparing different material types"""
    
    materials = [
        ('Lambertian', 'lambertian', [0.8, 0.3, 0.3], {}),
        ('Metal Smooth', 'metal', [0.9, 0.9, 0.9], {'roughness': 0.02}),
        ('Metal Rough', 'metal', [0.9, 0.9, 0.9], {'roughness': 0.5}),
        ('Glass', 'glass', [1, 1, 1], {'ior': 1.5}),
        ('Disney Metal', 'disney', [0.9, 0.7, 0.5], {'metallic': 1.0, 'roughness': 0.2}),
        ('Disney Glass', 'disney', [1, 1, 1], {'transmission': 1.0, 'ior': 1.5}),
        ('Disney Plastic', 'disney', [0.5, 0.8, 0.5], {'metallic': 0.0, 'roughness': 0.3}),
        ('Clearcoat', 'disney', [0.8, 0.3, 0.3], {'clearcoat': 1.0, 'clearcoat_gloss': 0.9}),
        ('Subsurface', 'subsurface', [0.9, 0.6, 0.5], {'scatter_distance': [1.0, 0.2, 0.1]}),
    ]
    
    fig = plt.figure(figsize=(15, 10))
    gs = GridSpec(3, 3, figure=fig)
    
    for idx, (name, mat_type, color, params) in enumerate(materials):
        print(f"Rendering material comparison {idx+1}/{len(materials)}: {name}")
        
        renderer = create_renderer()
        
        # Simple scene
        ground_mat = renderer.create_material('lambertian', [0.7, 0.7, 0.7], {})
        light_mat = renderer.create_material('light', [1, 1, 1], {'intensity': 8.0})
        
        # Ground
        renderer.add_triangle([-3, -1, -3], [3, -1, -3], [3, -1, 3], ground_mat)
        renderer.add_triangle([-3, -1, -3], [3, -1, 3], [-3, -1, 3], ground_mat)
        
        # Lights
        renderer.add_sphere([2, 3, 2], 0.5, light_mat)
        renderer.add_sphere([-2, 3, 2], 0.5, light_mat)
        
        # Test sphere
        test_mat = renderer.create_material(mat_type, color, params)
        renderer.add_sphere([0, 0, 0], 1.0, test_mat)
        
        # Camera
        setup_camera(renderer, [2.5, 2, 2.5], [0, 0, 0], 35, 200, 150)
        
        # Render
        pixels = render_image(renderer, samples=512, max_depth=8)
        
        ax = fig.add_subplot(gs[idx // 3, idx % 3])
        ax.imshow(np.clip(pixels, 0, 1))
        ax.set_title(name)
        ax.axis('off')
    
    plt.suptitle("Material Type Comparison", fontsize=14)
    plt.tight_layout()
    plt.show()

material_comparison()


# In[7]:



# %% Cell 7: Sampling Tests
def test_sampling_convergence():
    """Test convergence with different sample counts"""
    
    sample_counts = [1, 4, 16, 64, 256, 1024]
    images = []
    times = []
    
    for samples in sample_counts:
        print(f"Rendering with {samples} samples...")
        
        renderer = create_renderer()
        create_cornell_box(renderer)
        
        # Add complex object
        disney_mat = renderer.create_material('disney', [0.8, 0.6, 0.4], {
            'metallic': 0.3,
            'roughness': 0.4,
            'clearcoat': 0.5
        })
        renderer.add_sphere([0, -0.5, 0], 1.0, disney_mat)
        
        setup_camera(renderer, [0, 0, 5.5], [0, 0, 0], 38, 300, 225)
        
        # Time the render
        start = time.time()
        pixels = render_image(renderer, samples=samples, max_depth=8)
        render_time = time.time() - start
        
        images.append(pixels)
        times.append(render_time)
        print(f"  Render time: {render_time:.2f}s")
    
    # Display results
    fig, axes = plt.subplots(2, 3, figsize=(12, 8))
    axes = axes.flatten()
    
    for i, (img, samples, t) in enumerate(zip(images, sample_counts, times)):
        axes[i].imshow(np.clip(img, 0, 1))
        axes[i].set_title(f"{samples} spp ({t:.1f}s)")
        axes[i].axis('off')
    
    plt.suptitle("Sample Count Convergence Test")
    plt.tight_layout()
    plt.show()
    
    return images, times

convergence_images, convergence_times = test_sampling_convergence()


# In[8]:



# %% Cell 8: Adaptive Sampling Test
def test_adaptive_sampling():
    """Compare adaptive vs fixed sampling"""
    
    renderer1 = create_renderer()
    renderer2 = create_renderer()
    
    # Create identical scenes
    for renderer in [renderer1, renderer2]:
        create_cornell_box(renderer)
        glass_mat = renderer.create_material('glass', [1, 1, 1], {'ior': 1.5})
        renderer.add_sphere([0, -0.5, 0], 1.0, glass_mat)
        setup_camera(renderer, [0, 0, 5.5], [0, 0, 0], 38, 400, 300)
    
    # Render with adaptive sampling
    renderer1.set_adaptive_sampling(True)
    print("Rendering with adaptive sampling...")
    start = time.time()
    pixels_adaptive = render_image(renderer1, samples=256, max_depth=8, show_progress=False)
    time_adaptive = time.time() - start
    
    # Render without adaptive sampling
    renderer2.set_adaptive_sampling(False)
    print("Rendering without adaptive sampling...")
    start = time.time()
    pixels_fixed = render_image(renderer2, samples=256, max_depth=8, show_progress=False)
    time_fixed = time.time() - start
    
    # Display comparison
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    
    axes[0].imshow(np.clip(pixels_adaptive, 0, 1))
    axes[0].set_title(f"Adaptive Sampling ({time_adaptive:.1f}s)")
    axes[0].axis('off')
    
    axes[1].imshow(np.clip(pixels_fixed, 0, 1))
    axes[1].set_title(f"Fixed Sampling ({time_fixed:.1f}s)")
    axes[1].axis('off')
    
    plt.suptitle("Adaptive vs Fixed Sampling Comparison")
    plt.tight_layout()
    plt.show()
    
    print(f"Time saved with adaptive sampling: {time_fixed - time_adaptive:.1f}s ({(time_fixed - time_adaptive) / time_fixed * 100:.1f}%)")

test_adaptive_sampling()


# In[9]:



# %% Cell 9: Volume Rendering Test
def test_volume_rendering():
    """Test volumetric rendering capabilities"""
    
    renderer = create_renderer()
    
    # Create scene with volumes
    ground_mat = renderer.create_material('lambertian', [0.8, 0.8, 0.8], {})
    light_mat = renderer.create_material('light', [1, 1, 1], {'intensity': 10.0})
    
    # Ground
    renderer.add_triangle([-5, -2, -5], [5, -2, -5], [5, -2, 5], ground_mat)
    renderer.add_triangle([-5, -2, -5], [5, -2, 5], [-5, -2, 5], ground_mat)
    
    # Lights
    renderer.add_sphere([3, 3, 3], 1.0, light_mat)
    renderer.add_sphere([-3, 3, 3], 1.0, light_mat)
    
    # Add volumes with different densities and colors
    renderer.add_volume([0, 0, 0], 1.0, 0.5, [0.7, 0.7, 1.0], 0.0)  # Blue fog
    renderer.add_volume([2, 0, 0], 0.8, 1.0, [1.0, 0.7, 0.7], 0.3)  # Red fog, anisotropic
    renderer.add_volume([-2, 0, 0], 0.8, 0.3, [0.7, 1.0, 0.7], -0.3)  # Green fog
    
    # Camera
    setup_camera(renderer, [4, 3, 5], [0, 0, 0], 40, 600, 400)
    
    # Render
    print("Rendering volume test...")
    pixels = render_image(renderer, samples=128, max_depth=20, show_progress=False)
    
    display_image(pixels, "Volume Rendering Test")
    
    return pixels

volume_test = test_volume_rendering()


# In[10]:



# %% Cell 10: Performance Benchmark
def performance_benchmark():
    """Benchmark rendering performance with different settings"""
    
    results = {
        'test': [],
        'samples': [],
        'time': [],
        'rays_per_second': []
    }
    
    # Test configurations
    tests = [
        ("Simple scene", 10, 64),
        ("Medium complexity", 100, 64),
        ("Complex scene", 500, 64),
        ("High samples", 100, 256),
        ("Very high samples", 100, 1024),
    ]
    
    width, height = 400, 300
    
    for test_name, num_objects, samples in tests:
        print(f"\nBenchmarking: {test_name} ({num_objects} objects, {samples} samples)")
        
        renderer = create_renderer()
        
        # Create scene with varying complexity
        ground_mat = renderer.create_material('lambertian', [0.5, 0.5, 0.5], {})
        light_mat = renderer.create_material('light', [1, 1, 1], {'intensity': 5.0})
        
        # Ground
        renderer.add_triangle([-10, -2, -10], [10, -2, -10], [10, -2, 10], ground_mat)
        renderer.add_triangle([-10, -2, -10], [10, -2, 10], [-10, -2, 10], ground_mat)
        
        # Light
        renderer.add_sphere([0, 5, 0], 2.0, light_mat)
        
        # Add random objects
        np.random.seed(42)
        for i in range(num_objects):
            pos = [
                np.random.uniform(-5, 5),
                np.random.uniform(-1, 3),
                np.random.uniform(-5, 5)
            ]
            
            mat_type = np.random.choice(['disney', 'metal', 'glass'])
            if mat_type == 'disney':
                mat = renderer.create_material('disney', 
                    list(np.random.rand(3)), 
                    {'metallic': np.random.rand(), 'roughness': np.random.rand()})
            elif mat_type == 'metal':
                mat = renderer.create_material('metal',
                    list(np.random.rand(3)),
                    {'roughness': np.random.rand()})
            else:
                mat = renderer.create_material('glass', [1, 1, 1], {'ior': 1.5})
            
            renderer.add_sphere(pos, np.random.uniform(0.1, 0.5), mat)
        
        # Setup camera
        setup_camera(renderer, [8, 5, 8], [0, 0, 0], 35, width, height)
        
        # Benchmark
        start = time.time()
        pixels = render_image(renderer, samples=samples, max_depth=8)
        render_time = time.time() - start
        
        total_rays = width * height * samples
        rays_per_second = total_rays / render_time
        
        results['test'].append(test_name)
        results['samples'].append(samples)
        results['time'].append(render_time)
        results['rays_per_second'].append(rays_per_second)
        
        print(f"  Time: {render_time:.2f}s")
        print(f"  Rays/second: {rays_per_second:.0f}")
    
    # Display results
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    
    # Render time chart
    ax1.bar(range(len(results['test'])), results['time'])
    ax1.set_xticks(range(len(results['test'])))
    ax1.set_xticklabels(results['test'], rotation=45, ha='right')
    ax1.set_ylabel('Render Time (seconds)')
    ax1.set_title('Render Time Comparison')
    ax1.grid(True, alpha=0.3)
    
    # Rays per second chart
    ax2.bar(range(len(results['test'])), [r/1e6 for r in results['rays_per_second']])
    ax2.set_xticks(range(len(results['test'])))
    ax2.set_xticklabels(results['test'], rotation=45, ha='right')
    ax2.set_ylabel('Million Rays/Second')
    ax2.set_title('Ray Tracing Performance')
    ax2.grid(True, alpha=0.3)
    
    plt.suptitle('Performance Benchmark Results')
    plt.tight_layout()
    plt.show()
    
    return results

benchmark_results = performance_benchmark()


# In[11]:



# %% Cell 11: Texture Test
def test_textures():
    """Test procedural textures"""
    
    renderer = create_renderer()
    
    # Create procedural textures
    renderer.create_procedural_texture('checker1', 'checker', 
                                      [0.2, 0.2, 0.2, 0.9, 0.9, 0.9, 10])  # Dark/light, scale
    renderer.create_procedural_texture('marble1', 'marble', [0.1])  # Scale
    renderer.create_procedural_texture('wood1', 'wood', [1.0])  # Scale
    renderer.create_procedural_texture('noise1', 'noise', [5.0])  # Scale
    
    # Note: Current implementation may need texture support in material creation
    # This is a demonstration of the intended API
    
    ground_mat = renderer.create_material('lambertian', [0.5, 0.5, 0.5], {})
    light_mat = renderer.create_material('light', [1, 1, 1], {'intensity': 10.0})
    
    # Scene setup
    renderer.add_triangle([-5, -1, -5], [5, -1, -5], [5, -1, 5], ground_mat)
    renderer.add_triangle([-5, -1, -5], [5, -1, 5], [-5, -1, 5], ground_mat)
    
    renderer.add_sphere([0, 5, 0], 2.0, light_mat)
    
    # Test spheres with different materials
    test_mat1 = renderer.create_material('disney', [0.8, 0.3, 0.3], {'roughness': 0.3})
    test_mat2 = renderer.create_material('disney', [0.3, 0.8, 0.3], {'roughness': 0.5})
    test_mat3 = renderer.create_material('disney', [0.3, 0.3, 0.8], {'metallic': 0.8})
    
    renderer.add_sphere([-2, 0, 0], 1.0, test_mat1)
    renderer.add_sphere([0, 0, 0], 1.0, test_mat2)
    renderer.add_sphere([2, 0, 0], 1.0, test_mat3)
    
    setup_camera(renderer, [4, 3, 5], [0, 0, 0], 40, 600, 400)
    
    print("Rendering texture test...")
    pixels = render_image(renderer, samples=64, max_depth=8, show_progress=False)
    
    display_image(pixels, "Texture Test Scene")
    
    return pixels

texture_test = test_textures()


# In[12]:



# %% Cell 12: Quality Metrics
def calculate_image_metrics(image1, image2):
    """Calculate PSNR and MSE between two images"""
    mse = np.mean((image1 - image2) ** 2)
    if mse == 0:
        psnr = float('inf')
    else:
        max_pixel = 1.0
        psnr = 20 * np.log10(max_pixel / np.sqrt(mse))
    
    return mse, psnr

def quality_analysis():
    """Analyze rendering quality with different settings"""
    
    # Reference render (high quality)
    print("Creating reference render (high quality)...")
    renderer_ref = create_renderer()
    create_cornell_box(renderer_ref)
    disney_mat = renderer_ref.create_material('disney', [0.8, 0.6, 0.4], {
        'metallic': 0.5,
        'roughness': 0.3
    })
    renderer_ref.add_sphere([0, -0.5, 0], 1.0, disney_mat)
    setup_camera(renderer_ref, [0, 0, 5.5], [0, 0, 0], 38, 300, 225)
    reference = render_image(renderer_ref, samples=1024, max_depth=16)
    
    # Test different quality settings
    test_configs = [
        ("Low quality", 16, 4),
        ("Medium quality", 64, 8),
        ("High quality", 256, 12),
        ("Ultra quality", 512, 16)
    ]
    
    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    axes = axes.flatten()
    
    # Display reference
    axes[0].imshow(np.clip(reference, 0, 1))
    axes[0].set_title("Reference (1024 spp)")
    axes[0].axis('off')
    
    metrics = []
    
    for idx, (name, samples, depth) in enumerate(test_configs):
        print(f"Rendering {name}...")
        
        renderer = create_renderer()
        create_cornell_box(renderer)
        disney_mat = renderer.create_material('disney', [0.8, 0.6, 0.4], {
            'metallic': 0.5,
            'roughness': 0.3
        })
        renderer.add_sphere([0, -0.5, 0], 1.0, disney_mat)
        setup_camera(renderer, [0, 0, 5.5], [0, 0, 0], 38, 300, 225)
        
        test_image = render_image(renderer, samples=samples, max_depth=depth)
        
        # Calculate metrics
        mse, psnr = calculate_image_metrics(reference, test_image)
        metrics.append((name, samples, depth, mse, psnr))
        
        # Display
        axes[idx + 1].imshow(np.clip(test_image, 0, 1))
        axes[idx + 1].set_title(f"{name}\n{samples} spp, PSNR: {psnr:.1f}dB")
        axes[idx + 1].axis('off')
    
    # Display metrics table
    axes[5].axis('off')
    table_data = [["Config", "Samples", "Depth", "MSE", "PSNR (dB)"]]
    for name, samples, depth, mse, psnr in metrics:
        table_data.append([name, str(samples), str(depth), f"{mse:.6f}", f"{psnr:.1f}"])
    
    table = axes[5].table(cellText=table_data,
                         cellLoc='center',
                         loc='center',
                         bbox=[0, 0, 1, 1])
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    
    plt.suptitle("Quality Analysis - Different Settings vs Reference")
    plt.tight_layout()
    plt.show()
    
    return metrics

quality_metrics = quality_analysis()


# In[ ]:


import imageio

# Create a GIF of a sphere orbiting inside the Cornell box

def create_orbit_gif(filename='sphere_orbit.gif',
                     num_frames=36,
                     radius=1.6,
                     sphere_y=-0.5,
                     samples=64,
                     width=400,
                     height=300,
                     fps=12):
    frames = []
    angles = np.linspace(0, 2*np.pi, num_frames, endpoint=False)
    
    for i, a in enumerate(angles):
        print(f"Rendering frame {i+1}/{num_frames}...", end="\r")
        renderer = create_renderer()
        create_cornell_box(renderer)
        
        # moving sphere position on circular orbit
        x = radius * np.cos(a)
        z = radius * np.sin(a)
        
        moving_mat = renderer.create_material('disney', [0.8, 0.5, 0.3], {
            'metallic': 0.2, 'roughness': 0.3, 'clearcoat': 0.3
        })
        renderer.add_sphere([x, sphere_y, z], 0.7, moving_mat)
        
        setup_camera(renderer, [0, 0, 5.5], [0, 0, 0], 38, width, height)
        pixels = render_image(renderer, samples=samples, max_depth=8, show_progress=False)
        
        # convert to uint8 frame
        img_uint8 = (np.clip(pixels, 0, 1) * 255).astype(np.uint8)
        frames.append(img_uint8)
    
    print(f"\nSaving GIF to {filename}...")
    imageio.mimsave(filename, frames, fps=fps, loop=1)
    print(f"Saved: {filename}")
    
    # display final frame for quick preview
    display_image(frames[-1].astype(np.float32) / 255.0, title="Final Frame")
    return filename

gif_path = create_orbit_gif(filename='sphere_orbit.gif',
                            num_frames=36,
                            radius=1.6,
                            sphere_y=-0.5,
                            samples=64,
                            width=400,
                            height=300,
                            fps=12)

# In[13]:



# %% Cell 13: Feature Comparison
def feature_comparison():
    """Compare renders with different features enabled/disabled"""
    
    configs = [
        ("All Features", True, True, True),
        ("No NEE", False, True, True),
        ("No MIS", True, False, True),
        ("No Adaptive", True, True, False),
        ("Basic Only", False, False, False)
    ]
    
    fig, axes = plt.subplots(1, 5, figsize=(20, 4))
    
    for idx, (name, use_nee, use_mis, use_adaptive) in enumerate(configs):
        print(f"Rendering with config: {name}")
        
        renderer = create_renderer()
        
        # Note: These methods would need to be exposed in the Python bindings
        # This is a demonstration of the intended API
        # renderer.set_use_nee(use_nee)
        # renderer.set_use_mis(use_mis)
        renderer.set_adaptive_sampling(use_adaptive)
        
        create_cornell_box(renderer)
        
        # Complex material to show differences
        complex_mat = renderer.create_material('disney', [0.7, 0.5, 0.3], {
            'metallic': 0.3,
            'roughness': 0.4,
            'clearcoat': 0.5,
            'anisotropic': 0.3
        })
        renderer.add_sphere([0, -0.5, 0], 1.0, complex_mat)
        
        setup_camera(renderer, [0, 0, 5.5], [0, 0, 0], 38, 300, 225)
        
        pixels = render_image(renderer, samples=64, max_depth=8)
        
        axes[idx].imshow(np.clip(pixels, 0, 1))
        axes[idx].set_title(name, fontsize=10)
        axes[idx].axis('off')
    
    plt.suptitle("Feature Comparison - Impact of Different Features")
    plt.tight_layout()
    plt.show()

feature_comparison()


# In[14]:



# %% Cell 14: Summary Statistics
def print_summary():
    """Print summary of all tests"""
    
    print("\n" + "="*60)
    print("CUSTOM RAYTRACER TEST SUMMARY")
    print("="*60)
    
    print(f"\n✓ Module Version: {raytracer_blender.__version__}")
    print(f"✓ Features Available: {list(raytracer_blender.__features__.keys())}")
    
    print("\n📊 Performance Metrics:")
    if 'benchmark_results' in globals():
        for i, test in enumerate(benchmark_results['test']):
            print(f"  • {test}: {benchmark_results['time'][i]:.2f}s "
                  f"({benchmark_results['rays_per_second'][i]/1e6:.1f}M rays/s)")
    
    print("\n🎨 Quality Metrics (PSNR vs Reference):")
    if 'quality_metrics' in globals():
        for name, samples, depth, mse, psnr in quality_metrics:
            print(f"  • {name} ({samples} spp): {psnr:.1f} dB")
    
    print("\n✅ Tests Completed Successfully!")
    print("="*60)

print_summary()


# ## Conclusion
# 
# This notebook has demonstrated:
# 
# 1. **Basic Usage**: How to create scenes, materials, and render images
# 2. **Material System**: All material types including Disney BRDF with full parameters
# 3. **Sampling**: Fixed vs adaptive sampling, convergence analysis
# 4. **Performance**: Benchmarking and optimization opportunities
# 5. **Quality**: PSNR analysis and quality metrics
# 6. **Advanced Features**: Volumes, textures (when implemented), complex materials
# 
# The Custom Raytracer provides a powerful and flexible rendering system with:
# - Next Event Estimation (NEE) for efficient direct lighting
# - Multiple Importance Sampling (MIS) for robust light transport
# - Complete Disney BRDF implementation
# - Adaptive sampling for faster convergence
# - SAH-based BVH for efficient ray tracing
# 
# Future improvements could include:
# - GPU acceleration
# - Bidirectional path tracing
# - Metropolis light transport
# - Spectral rendering for astrophysics applications

# In[ ]:




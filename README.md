# Astroray

A modern C++ path tracer (v3.0.0) with physically-based rendering, BVH acceleration, CUDA GPU support, general-relativistic black hole rendering, and Blender integration.

## Project Structure

```
Astroray/
├── include/                     # Header files and third-party libraries
│   ├── raytracer.h             # Core ray tracing data structures
│   ├── advanced_features.h     # Transform, textured materials, mesh, volumes, black holes
│   ├── blender_integration.h   # Blender addon integration interface
│   ├── stb_image.h             # Image read library (header)
│   ├── stb_image_write.h       # Image write library (header)
│   └── stb_image_write_impl.c  # Image write library (implementation)
├── src/                         # C++ source files
│   ├── stb_impl.cpp            # stb_image implementation unit
│   └── gpu/                    # CUDA GPU backend
│       ├── cuda_renderer.cu
│       ├── path_trace_kernel.cu
│       └── scene_upload.cu
├── apps/                        # Standalone applications
│   └── main.cpp                # Main ray tracer executable
├── module/                      # Python module source
│   └── blender_module.cpp      # pybind11 module (astroray)
├── blender_addon/               # Blender addon
│   └── __init__.py             # Addon registration and render engine
├── samples/                     # Sample scenes and test assets
├── docs/                        # Documentation
├── tests/                       # Test suite (pytest)
├── CMakeLists.txt              # CMake build configuration
├── AGENTS.md                   # Agent configuration
└── README.md                   # This file
```

## Features

- **Physically-Based Path Tracing**: Full Monte Carlo path tracing with unbiased global illumination
- **SAH BVH Acceleration**: Surface Area Heuristic Bounding Volume Hierarchy for fast ray traversal
- **NEE + MIS**: Next Event Estimation and Multiple Importance Sampling for reduced noise
- **CUDA GPU Acceleration**: Optional NVIDIA GPU backend (Turing/Ampere/Ada Lovelace — sm 75/86/89)
- **Disney BRDF**: Full principled BRDF with metallic, roughness, clearcoat, anisotropic, sheen, subsurface, and transmission parameters
- **Multiple Material Types**: Lambertian, Metal, Dielectric (glass), Diffuse Light, Subsurface, Disney BRDF
- **Adaptive Sampling**: Noise-threshold-guided sample budget allocation
- **General-Relativistic Black Holes**: Numerically-integrated geodesic rendering with accretion disk emission
- **Volumetric Rendering**: Constant-medium fog and participating media with anisotropic scattering
- **OBJ Mesh Loading**: Triangle mesh import with per-vertex UV support
- **Environment Maps**: HDRI lighting via equirectangular `.hdr` images with strength and rotation control
- **Procedural Textures**: Checker, Noise, Marble, and Wood textures
- **Image Textures**: Load arbitrary floating-point texture maps
- **AOV Buffers**: Albedo and surface normal auxiliary output buffers
- **Depth-of-Field**: Thin-lens camera model with aperture and focus-distance control
- **Blender Integration**: Render engine addon for Blender 5.0+

## Build Instructions

### Prerequisites

- CMake 3.18+
- C++17 compatible compiler (GCC 9+, Clang 10+, MSVC 2019+)
- OpenMP (required for parallel CPU rendering)
- Python 3.7+ with development headers (for Python module)
- pybind11 (auto-fetched from GitHub if not installed)
- CUDA Toolkit 12.x (optional, for GPU acceleration)

### Build Steps

```bash
# Create build directory
mkdir build && cd build

# Configure with CMake (Python module built by default)
cmake .. -DCMAKE_BUILD_TYPE=Release

# Build
make -j8
```

The Python module `astroray.cpython-*.so` (Linux) or `astroray.pyd` (Windows) is written to `build/`.  
The standalone binary is written to `build/bin/raytracer`.

### Build Options

| Option | Description | Default |
|--------|-------------|---------|
| `BUILD_PYTHON_MODULE` | Build `astroray` Python module | ON |
| `BUILD_BLENDER_MODULE` | Build Blender addon module | OFF |
| `BUILD_DOCS` | Generate Doxygen documentation | OFF |
| `USE_NATIVE_ARCH` | Compile with `-march=native` | ON |
| `USE_FAST_MATH` | Enable fast math optimizations | ON |
| `ASTRORAY_ENABLE_CUDA` | Enable CUDA GPU backend (auto-detected) | ON |

### Building the Blender Addon

```bash
cmake .. -DCMAKE_BUILD_TYPE=Release -DBUILD_BLENDER_MODULE=ON
make -j8
```

The compiled module is placed in `build/blender_addon/` and a copy of `blender_addon/__init__.py` is staged there for installation.

## Usage

### Standalone Ray Tracer

```bash
# Run with default settings (Cornell Box, 800×600, 64 spp → output.ppm)
./build/bin/raytracer

# Custom parameters — output format detected from file extension
./build/bin/raytracer --scene 2 --width 1920 --height 1080 --samples 256 --output output.png
```

### Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--scene 1\|2` | 1 = Cornell Box with glass/Disney/metal spheres, 2 = Material grid | 1 |
| `--width N` | Image width in pixels | 800 |
| `--height N` | Image height in pixels | 600 |
| `--samples N` | Samples per pixel | 64 |
| `--depth N` | Maximum ray recursion depth | 50 |
| `--output FILE` | Output path; `.png` or `.ppm` auto-detected from extension | output.ppm |
| `--help` | Print usage and exit | — |

### Python API

The `astroray` module is importable directly from the build directory:

```python
import sys
sys.path.insert(0, 'build')
import astroray

print(astroray.__version__)   # "3.0.0"
print(astroray.__features__)  # dict of enabled feature flags

# Create renderer
renderer = astroray.Renderer()

# Setup camera (width/height control output resolution)
renderer.setup_camera(
    look_from=[0, 0, 5],
    look_at=[0, 0, 0],
    vup=[0, 1, 0],
    vfov=60,
    aspect_ratio=16/9,
    aperture=0.0,
    focus_dist=5.0,
    width=800,
    height=450,
)

# Add geometry
mat = renderer.create_material('disney', [0.8, 0.4, 0.2], {
    'metallic': 0.5,
    'roughness': 0.3,
    'clearcoat': 0.8,
})
renderer.add_sphere([0, 0, 0], 1.0, mat)
renderer.add_triangle([-3, -1, -3], [3, -1, -3], [3, -1, 3],
                      renderer.create_material('lambertian', [0.5, 0.5, 0.5], {}))

# Optional: HDRI environment lighting
renderer.load_environment_map('samples/test_env.hdr', strength=1.0, rotation=0.0)

# Optional: GPU rendering (requires CUDA)
if renderer.gpu_available:
    renderer.set_use_gpu(True)

# Render → numpy array (H × W × 3, float32 in [0, 1], gamma-corrected)
pixels = renderer.render(samples_per_pixel=128, max_depth=8)

# Auxiliary buffers (available after render())
albedo = renderer.get_albedo_buffer()   # H × W × 3
normals = renderer.get_normal_buffer()  # H × W × 3
```

#### Material Types

| Type | Key parameters |
|------|---------------|
| `'lambertian'` | — |
| `'metal'` | `roughness` |
| `'glass'` / `'dielectric'` | `ior` |
| `'light'` / `'emission'` | `intensity` |
| `'subsurface'` | `scatter_distance` (RGB list), `scale` |
| `'disney'` | `metallic`, `roughness`, `transmission`, `ior`, `clearcoat`, `clearcoat_gloss`, `anisotropic`, `anisotropic_rotation`, `sheen`, `sheen_tint`, `subsurface` |

#### Black Hole Rendering

```python
renderer.add_black_hole(
    position=[0, 0, 0],
    mass=10.0,              # solar masses
    influence_radius=100.0, # scene units
    params={
        'disk_outer': 30.0,
        'accretion_rate': 1.0,
        'inclination': 75.0,
    }
)
```

#### Volumetric Fog

```python
renderer.add_volume(
    center=[0, 0, 0],
    radius=2.0,
    density=0.5,
    color=[0.8, 0.9, 1.0],
    anisotropy=0.0,  # Henyey-Greenstein g parameter
)
```

#### OBJ Mesh Loading

```python
mat = renderer.create_material('disney', [0.7, 0.7, 0.7], {'roughness': 0.4})
renderer.add_mesh('model.obj', mat,
                  position=[0, 0, 0], scale=[1, 1, 1], rotation_y=45.0)
```

### Blender Integration

1. Build the Blender addon module (see [Building the Blender Addon](#building-the-blender-addon))

2. Copy the staged `build/blender_addon/` folder into Blender's add-ons directory:
   - **Windows**: `%APPDATA%\Blender Foundation\Blender\5.x\scripts\addons\`
   - **macOS**: `~/Library/Application Support/Blender/5.x/scripts/addons/`
   - **Linux**: `~/.config/blender/5.x/scripts/addons/`

3. In Blender: enable **"Custom Raytracer Pro"** in *Preferences > Add-ons*

4. Select **"Custom Raytracer"** as the render engine in *Render Properties*

The addon exposes samples, max bounces, adaptive sampling, and GPU toggle directly from Blender's render properties panel.

## Testing

```bash
# Run all tests (requires built module)
pytest tests/ -v

# Python bindings (30 tests — materials, Cornell box, Disney BRDF, convergence,
#                  performance, quality analysis, AOV buffers, HDRI, GPU, black holes)
pytest tests/test_python_bindings.py -v

# Material property tests (17 tests — per-material quantitative assertions)
pytest tests/test_material_properties.py -v

# Standalone binary (7 tests — help, scene rendering, dimensions, convergence)
pytest tests/test_standalone_renderer.py -v
```

Test images and performance charts are saved to `test_results/` (gitignored).

### What the tests verify

| Test | What it catches |
|------|----------------|
| `test_background_sky_present` | Background accidentally zeroed |
| `test_cornell_box` | Red/green wall colour-bleeding, scene brightness |
| `test_metallic_vs_diffuse_differ` | Disney BRDF metallic parameter broken |
| `test_aperture_dof` | Depth-of-field has no effect |
| `test_quality_analysis` | PSNR regression at higher sample counts |
| `test_disney_brdf_parameter_grid` | Any of the 12 BRDF parameter combos black |
| `test_aov_buffers` | Albedo/normal buffer shape and content |
| `test_cuda_availability` | GPU detection crashes or missing feature flag |
| `test_black_hole_creation` | GR black hole rendering crashes |
| `test_black_hole_shadow_is_dark` | Shadow region brighter than surrounding sky |
| `test_width_height_respected` | Standalone binary ignores dimension flags |
| `test_higher_samples_closer_to_reference` | Standalone convergence regression |

## Domain Context

### Key Concepts

- **Vec3**: 3D vector class for positions, normals, and colors
- **Ray**: Ray structure with origin and direction
- **Material**: Base material interface with scatter method
- **Hittable**: Ray-object intersection interface
- **BVH**: Bounding Volume Hierarchy with SAH splits for acceleration
- **NEE / MIS**: Next Event Estimation / Multiple Importance Sampling for efficient light sampling
- **MoE**: Monte Carlo Estimation for unbiased rendering

### Core Files

- `include/raytracer.h` — Core data structures (Vec3, Ray, Material, Hittable, BVH, Renderer)
- `include/advanced_features.h` — Transform classes, textured materials, OBJ mesh, volumes, black holes
- `include/blender_integration.h` — Blender addon interface
- `apps/main.cpp` — Standalone application entry point
- `module/blender_module.cpp` — pybind11 Python module (`astroray`)
- `src/gpu/` — CUDA path-tracing kernel and scene upload
- `CMakeLists.txt` — Build configuration

## License

MIT License - See LICENSE file for details.
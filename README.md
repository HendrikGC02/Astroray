# Astroray

A modern C++ ray tracer with physically-based rendering, BVH acceleration, and Blender integration.

## Project Structure

```
Astroray/
├── include/                  # Header files and third-party libraries
│   ├── raytracer.h          # Core ray tracing data structures
│   ├── advanced_features.h  # Transform, textured materials, mesh support
│   ├── blender_integration.h# Blender addon integration interface
│   ├── stb_image_write.h    # Image write library (header)
│   └── stb_image_write_impl.c # Image write library (implementation)
├── src/                      # Legacy source files (deprecated)
├── apps/                     # Standalone applications
│   └── main.cpp             # Main ray tracer executable
├── module/                   # Blender addon module
│   └── blender_module.cpp   # Python module for Blender
├── samples/                  # Sample scenes and test files
├── docs/                     # Documentation
├── tests/                    # Unit tests
├── lib/                      # External libraries
├── api/                      # API bindings
├── renderer/                 # Renderer implementations
├── CMakeLists.txt           # CMake build configuration
├── AGENTS.md                # Agent configuration
└── README.md                # This file
```

## Features

- **Physically-Based Rendering**: Realistic lighting and materials
- **BVH Acceleration**: Bounding Volume Hierarchy for efficient ray tracing
- **Monte Carlo Estimation**: Advanced sampling techniques
- **Blender Integration**: Python module for Blender 4.2+
- **Multiple Material Types**: Lambertian, Metal, Dielectric, Diffuse Light, Disney BRDF
- **Texture Support**: Checkerboard, procedural textures
- **Subsurface Scattering**: Advanced material effects
- **Clearcoat Coating**: Automotive-grade finish support

## Build Instructions

### Prerequisites

- CMake 3.14+
- C++17 compatible compiler (GCC 9+, Clang 10+, MSVC 2019+)
- OpenMP (optional, for parallel rendering)
- Python 3.7+ (for Blender addon)

### Build Steps

```bash
# Create build directory
mkdir build && cd build

# Configure with CMake
cmake .. -DCMAKE_BUILD_TYPE=Release

# Build
cmake --build . --config Release
```

### Build Options

| Option | Description | Default |
|--------|-------------|---------|
| `ASTRORAY_BUILD_TESTS` | Build unit tests | OFF |
| `ASTRORAY_BUILD_DOCS` | Generate documentation | OFF |
| `ASTRORAY_BUILD_BLENDER` | Build Blender addon | OFF |
| `ASTRORAY_USE_OPENMP` | Enable OpenMP parallelization | ON |
| `ASTRORAY_USE_FAST_MATH` | Enable fast math optimizations | ON |

### Building Blender Addon

```bash
# Configure with Blender addon enabled
cmake .. -DCMAKE_BUILD_TYPE=Release -DASTRORAY_BUILD_BLENDER=ON -DPYTHON_EXECUTABLE=python

# Build
cmake --build . --config Release
```

The Python module `astroray.pyd` will be generated in `build/Release/`.

## Usage

### Standalone Ray Tracer

```bash
# Run with default settings (Cornell Box scene, 800x600, 64spp → output.ppm)
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

The Python module `astroray` can be imported after building:

```python
import sys
sys.path.insert(0, 'build/Release')
import astroray

# Create renderer
renderer = astroray.Renderer()

# Setup camera
renderer.setup_camera(
    look_from=[0, 0, 5],
    look_at=[0, 0, 0],
    vup=[0, 1, 0],
    vfov=60,
    aspect_ratio=1.0,
    aperture=0,
    focus_dist=10
)

# Add a sphere
sphere_material = renderer.create_material('disney', [1, 0.2, 0.2], {
    'roughness': 0.1,
    'metallic': 0
})
renderer.add_sphere([0, 0, -1], 1.0, sphere_material)

# Render
pixels = renderer.render(samples=100, max_bounces=8)
```

### Blender Integration

1. Build the Blender addon:
```bash
cmake .. -DASTRORAY_BUILD_BLENDER=ON -DCMAKE_BUILD_TYPE=Release
cmake --build . --config Release
```

2. Copy `blender_addon` folder to Blender's scripts/addons directory

3. In Blender: Enable "Custom Raytracer Pro" addon in Preferences > Add-ons

## Testing

```bash
# Run all tests (requires built module)
pytest tests/ -v

# Python bindings (21 tests — materials, Cornell box, Disney BRDF, convergence,
#                  performance benchmark, quality analysis, AOV buffers)
pytest tests/test_python_bindings.py -v

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
| `test_width_height_respected` | Standalone binary ignores dimension flags |
| `test_higher_samples_closer_to_reference` | Standalone convergence regression |

## Domain Context

### Key Concepts

- **Vec3**: 3D vector class for positions, normals, and colors
- **Ray**: Ray structure with origin and direction
- **Material**: Base material interface with scatter method
- **Hittable**: Ray-object intersection interface
- **BVH**: Bounding Volume Hierarchy for acceleration
- **MoE**: Monte Carlo Estimation for rendering

### Core Data Structures

- `include/raytracer.h` - Core data structures (Vec3, Ray, Material, Hittable)
- `include/advanced_features.h` - Transform classes, textured materials, mesh support
- `include/blender_integration.h` - Blender addon interface

### Important Files

- `apps/main.cpp` - Main application entry point
- `module/blender_module.cpp` - Blender Python module
- `CMakeLists.txt` - Build configuration
- `include/stb_image_write.h` - PNG image output library

## License

MIT License - See LICENSE file for details.
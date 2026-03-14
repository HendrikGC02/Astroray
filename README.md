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
# Find Python installation
python -c "import sys; print(sys.prefix)"

# Configure with Blender addon enabled
cmake .. -DCMAKE_BUILD_TYPE=Release -DASTRORAY_BUILD_BLENDER=ON -DPYTHON_EXECUTABLE=python

# Build
cmake --build . --config Release
```

## Usage

### Standalone Ray Tracer

```bash
# Run with default settings (Cornell Box scene)
./build/bin/raytracer.exe

# Custom parameters
./build/bin/raytracer.exe --scene 2 --width 1920 --height 1080 --samples 256 --output output.png
```

### Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--scene 1|2` | Scene selection (1=Cornell Box, 2=Sphere) | 1 |
| `--width N` | Image width in pixels | 640 |
| `--height N` | Image height in pixels | 480 |
| `--samples N` | Samples per pixel | 50 |
| `--depth N` | Maximum ray recursion depth | 10 |
| `--output FILE` | Output PNG filename | output.png |

### Blender Integration

1. Build the Blender addon:
```bash
cmake .. -DASTRORAY_BUILD_BLENDER=ON -DCMAKE_BUILD_TYPE=Release
cmake --build . --config Release
```

2. Copy `blender_addon` folder to Blender's scripts/addons directory

3. In Blender: Enable "Astroray" addon in Preferences > Add-ons

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
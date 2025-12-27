# Custom Path Tracer for Blender 5.0

A production-quality path tracing render engine for Blender 5.0, featuring physically-based rendering with Disney BRDF, Next Event Estimation (NEE), Multiple Importance Sampling (MIS), and adaptive sampling.

## Features

### Rendering
- **Path Tracing** with configurable bounce depth
- **Next Event Estimation (NEE)** for efficient direct lighting
- **Multiple Importance Sampling (MIS)** combining BSDF and light sampling
- **Adaptive Sampling** focuses compute on noisy regions
- **Russian Roulette** path termination for efficiency
- **Firefly Clamping** prevents bright pixel artifacts

### Materials
- **Disney Principled BRDF** with full parameter support
- **Lambertian Diffuse** for matte surfaces
- **Metal** with GGX microfacet model
- **Dielectric (Glass)** with proper Fresnel and refraction
- **Subsurface Scattering** for translucent materials
- **Emission** for area lights and emissive surfaces

### Textures
- **Image Textures** loaded from numpy arrays
- **Procedural Textures**: Checker, Noise, Marble, Wood

### Geometry
- **Spheres** and **Triangles** as primitives
- **OBJ Mesh Loading** with UV support
- **Transforms**: Translate, Scale, Rotate
- **Volumes** (constant density medium)

### Acceleration
- **SAH-based BVH** for fast ray intersection
- **OpenMP Parallelization** across CPU cores
- **Tile-based Rendering** (16×16 tiles)

### Integration
- Full Blender 5.0 render engine integration
- Reads Principled BSDF node parameters
- Supports Point, Sun, and Area lights
- World background lighting
- Depth of Field from camera settings

---

## Requirements

- **Blender 5.0** (uses Python 3.11)
- **Python 3.11** (matching Blender's bundled version)
- **CMake 3.15+**
- **C++17 compatible compiler**:
  - Windows: Visual Studio 2019+ or MinGW
  - Linux: GCC 8+ or Clang 10+
  - macOS: Xcode 12+ or Clang

---

## Installation

### Step 1: Build the Module

#### Windows (PowerShell)

```powershell
# Navigate to addon directory
cd raytracer_addon

# Create build directory
mkdir build
cd build

# Configure with your Python 3.11 path
cmake .. -DBUILD_BLENDER_MODULE=ON -DCMAKE_BUILD_TYPE=Release `
  -DPython3_EXECUTABLE="C:\Users\YourName\AppData\Local\Programs\Python\Python311\python.exe"

# Build
cmake --build . --config Release
```

#### Linux / macOS

```bash
cd raytracer_addon
mkdir build && cd build

# Configure (Python 3.11 should be auto-detected)
cmake .. -DBUILD_BLENDER_MODULE=ON -DCMAKE_BUILD_TYPE=Release

# Build
make -j$(nproc)
```

### Step 2: Install the Addon

Copy the built module and Python file to Blender's addon directory:

**Windows:**
```
%APPDATA%\Blender Foundation\Blender\5.0\scripts\addons\custom_raytracer\
```

**Linux:**
```
~/.config/blender/5.0/scripts/addons/custom_raytracer/
```

**macOS:**
```
~/Library/Application Support/Blender/5.0/scripts/addons/custom_raytracer/
```

Required files:
- `raytracer_blender.pyd` (Windows) or `raytracer_blender.so` (Linux/macOS)
- `__init__.py`

### Step 3: Enable in Blender

1. Open Blender 5.0
2. Go to **Edit → Preferences → Add-ons**
3. Search for "Custom Raytracer"
4. Enable the checkbox
5. **Restart Blender** (important for first-time setup)

---

## Usage

### Basic Workflow

1. **Set Render Engine**: Render Properties → Engine → **Custom Raytracer**
2. **Configure Samples**: Render Properties → Sampling panel
3. **Add Materials**: Use Principled BSDF in the Shader Editor
4. **Add Lights**: Shift+A → Light (Point, Sun, or Area)
5. **Render**: Press F12

### Render Settings

| Setting | Description | Default |
|---------|-------------|---------|
| Samples | Maximum samples per pixel | 128 |
| Preview Samples | Samples for viewport | 32 |
| Max Bounces | Maximum ray depth | 8 |
| Adaptive Sampling | Focus samples on noisy areas | On |
| Noise Threshold | Target noise level for adaptive | 0.01 |
| Clamp Indirect | Limit indirect light intensity | 10.0 |

### Material Support

The renderer reads from Blender's **Principled BSDF** node:

| Parameter | Supported | Notes |
|-----------|-----------|-------|
| Base Color | ✅ | RGB color |
| Metallic | ✅ | 0 = dielectric, 1 = metal |
| Roughness | ✅ | 0 = mirror, 1 = diffuse |
| IOR | ✅ | Index of refraction |
| Transmission | ✅ | 0 = opaque, 1 = glass |
| Coat Weight | ✅ | Clearcoat layer |
| Coat Roughness | ✅ | Clearcoat glossiness |
| Sheen Weight | ✅ | Fabric-like sheen |
| Subsurface Weight | ✅ | Translucency |
| Anisotropic | ✅ | Stretched highlights |
| Emission Color | ✅ | Makes surface emissive |
| Emission Strength | ✅ | Light intensity |

**Other supported shaders:**
- **Emission** → Emissive material
- **Glass BSDF** → Dielectric with custom IOR
- **Glossy BSDF** → Treated as metal

### Light Types

| Type | Rendered As | Notes |
|------|-------------|-------|
| Point | Small sphere | Color and energy supported |
| Sun | Distant large sphere | Directional lighting |
| Area | Sphere | Size determines radius |
| World Background | Environment sphere | Uses Background node strength |

---

## Troubleshooting

### Black Render
- **Add lights**: Shift+A → Light → Point/Sun
- **Or add emission**: Create material with Emission Strength > 0
- **Check world**: World Properties → Background → Strength > 0

### Materials Not Working
- Restart Blender after first install
- Ensure shader is connected to Material Output
- Check that Principled BSDF is the surface shader

### Crash on Render
- Update to latest build (memory management fixed)
- Check console for errors: Window → Toggle System Console
- Reduce samples/bounces if running out of memory

### Viewport Preview Issues
- Switch to Solid shading, then back to Rendered
- Viewport uses lower samples for speed

### Module Not Loading
```
Failed to load raytracer module: ...
```
- Verify Python version matches (3.11 for Blender 5.0)
- Check that .pyd/.so file is in addon directory
- On Windows, ensure Visual C++ Redistributable is installed

---

## Performance Tips

### For Speed
- Start with **16-32 samples** while iterating
- Use **4-5 max bounces** for most scenes
- Enable **Adaptive Sampling**
- Reduce resolution during testing

### For Quality
- Final renders: **128-512 samples**
- Complex lighting: **8-12 max bounces**
- Lower noise threshold: **0.005**
- Disable clamping for HDR accuracy (set to 0)

### Benchmarks

Tested on AMD Ryzen 9 5950X (16 cores, 32 threads):

| Scene | Resolution | Samples | Bounces | Time |
|-------|------------|---------|---------|------|
| Cornell Box | 800×600 | 64 | 8 | ~5s |
| Cornell Box | 1920×1080 | 128 | 8 | ~45s |
| Material Grid | 1920×1080 | 256 | 8 | ~2m |

---

## Technical Details

### Path Tracing Algorithm

```
for each pixel:
    for each sample:
        ray = camera.generateRay(pixel + jitter)
        color += tracePath(ray)
    pixel = color / samples
```

The path tracer uses:

1. **Russian Roulette** starting at bounce 3
2. **Next Event Estimation** samples lights directly at each bounce
3. **MIS** combines light sampling (NEE) with BSDF sampling using power heuristic (β=2)
4. **Firefly Clamping** limits throughput to prevent bright pixels

### Disney BRDF Implementation

Based on the Disney Principled BRDF paper with:
- GGX/Trowbridge-Reitz microfacet distribution
- Smith G masking-shadowing function
- Schlick Fresnel approximation (with reduced intensity to prevent over-brightness)
- Clearcoat as separate specular lobe
- Sheen for fabric-like appearance

### BVH Acceleration

Surface Area Heuristic (SAH) construction:
- Evaluates 16 split candidates per axis
- Chooses split minimizing: `cost = traversal + (leftArea × leftCount + rightArea × rightCount) / totalArea`
- Flattened to linear array for cache-efficient traversal

---

## File Structure

```
raytracer_addon/
├── raytracer.h          # Core: Vec3, Ray, materials, BVH, renderer
├── advanced_features.h  # Disney BRDF, textures, volumes, transforms
├── blender_module.cpp   # pybind11 Python bindings
├── __init__.py          # Blender addon (UI, scene conversion)
├── main.cpp             # Standalone test renderer
├── CMakeLists.txt       # Build configuration
└── README.md            # This file
```

---

## Standalone Renderer

Build and run without Blender for testing:

```bash
# Build standalone
cmake .. -DBUILD_STANDALONE=ON
make

# Render Cornell Box
./bin/raytracer --scene 1 --samples 64 --output cornell.ppm

# Render Material Grid
./bin/raytracer --scene 2 --width 1280 --height 720 --samples 128 --output materials.ppm

# Options
./bin/raytracer --help
```

---

## Known Limitations

1. **No GPU acceleration** (CPU only, uses OpenMP)
2. **No motion blur** 
3. **No denoising** (auxiliary buffers available for external denoisers)
4. **Area lights rendered as spheres** (not rectangular)
5. **No texture nodes** (only Principled BSDF base color)
6. **No displacement/bump mapping**

---

## Future Roadmap

- [ ] Intel OIDN / OpenImageDenoise integration
- [ ] CUDA/OptiX GPU acceleration
- [ ] Image texture support from Blender
- [ ] HDRI environment maps
- [ ] True area light shapes
- [ ] Displacement mapping
- [ ] Motion blur
- [ ] Spectral rendering (for astrophysics applications)

---

## Extending the Renderer

### Adding a New Material

1. Create class in `advanced_features.h`:
```cpp
class MyMaterial : public Material {
public:
    Vec3 eval(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override;
    BSDFSample sample(const HitRecord& rec, const Vec3& wo, std::mt19937& gen) const override;
    float pdf(const HitRecord& rec, const Vec3& wo, const Vec3& wi) const override;
};
```

2. Add to `createMaterial()` in `blender_module.cpp`:
```cpp
else if (type == "my_material") {
    mat = std::make_shared<MyMaterial>(color, params...);
}
```

3. Map from Blender node in `__init__.py`:
```python
elif node.type == 'MY_NODE':
    return renderer.create_material('my_material', color, {...})
```

### Adding a New Primitive

1. Inherit from `Hittable` in `raytracer.h`
2. Implement `hit()` and `boundingBox()`
3. Optionally implement `pdfValue()` and `random()` for light sampling
4. Add Python binding in `blender_module.cpp`

---

## References

- [Physically Based Rendering (PBRT)](https://pbr-book.org/)
- [Ray Tracing in One Weekend](https://raytracing.github.io/)
- [Disney Principled BRDF](https://blog.selfshadow.com/publications/s2012-shading-course/)
- [Blender Python API](https://docs.blender.org/api/current/)

---

## License

Personal use and modification. This is your renderer—build what you want!

---

**Version 3.0.0** — December 2024

- Complete rewrite with all bug fixes
- Fixed black metal materials
- Fixed overly bright Disney BRDF Fresnel
- Fixed emissive-looking subsurface
- Fixed Blender memory management crashes
- Updated for Blender 5.0 / Python 3.11

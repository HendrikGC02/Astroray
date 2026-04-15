# Astroray Phase 2: CUDA GPU Acceleration

## Goal

Add an optional CUDA GPU rendering backend that runs the full path tracer (Disney BRDF, NEE+MIS, BVH traversal, environment maps) on NVIDIA GPUs. The CPU backend remains the default fallback. The user selects GPU rendering via a flag in the Python API and Blender addon.

## Architecture Overview

```
include/
  raytracer.h              ← existing (CPU renderer stays here, untouched)
  advanced_features.h      ← existing
  astroray/
    gpu_types.h            ← POD structs mirroring CPU types (__host__ __device__)
    gpu_materials.h        ← Material evaluation as device functions (no virtual dispatch)
    gpu_bvh.h              ← Flattened BVH traversal device functions
    gpu_renderer.h         ← CUDARenderer C++ interface (no CUDA types in this header)
src/
  gpu/
    cuda_renderer.cu       ← CUDARenderer implementation, kernel launch
    path_trace_kernel.cu   ← The megakernel: per-sample path tracing
    scene_upload.cu        ← Host→device scene transfer
module/
  blender_module.cpp       ← Add use_gpu flag, create CUDARenderer when requested
```

### Key design constraint: pybind11 and nvcc do NOT mix

pybind11 headers use C++ features (visibility attributes, LTO) that nvcc chokes on. Solution: `.cu` files compile into a **static library** (`astroray_cuda`), which exposes a pure C++ interface via `gpu_renderer.h`. The pybind11 module links against this static lib but never includes any CUDA headers.

`gpu_renderer.h` contains:
```cpp
// NO cuda includes, NO __device__ annotations — pure C++ interface
class CUDARenderer {
public:
    CUDARenderer();
    ~CUDARenderer();
    bool isAvailable() const;  // checks cudaGetDeviceCount > 0
    void uploadScene(/* CPU-side scene data */);
    void render(float* outputPixels, int width, int height, int samples, int maxDepth);
private:
    struct Impl;
    std::unique_ptr<Impl> impl;  // pimpl hides all CUDA types
};
```

## Phase 2A: Foundation (do this first)

### Task 1: GPU-compatible POD types (`include/astroray/gpu_types.h`)

Create GPU-portable versions of the core types. These must be trivially copyable (no std::string, no shared_ptr, no virtual functions).

```cpp
#pragma once
#ifdef __CUDACC__
#define HD __host__ __device__
#else
#define HD
#endif

struct GVec3 {
    float x, y, z;
    HD GVec3() : x(0), y(0), z(0) {}
    HD GVec3(float a, float b, float c) : x(a), y(b), z(c) {}
    HD GVec3(float v) : x(v), y(v), z(v) {}
    HD GVec3 operator+(const GVec3& o) const { return {x+o.x, y+o.y, z+o.z}; }
    HD GVec3 operator-(const GVec3& o) const { return {x-o.x, y-o.y, z-o.z}; }
    HD GVec3 operator*(float s) const { return {x*s, y*s, z*s}; }
    HD GVec3 operator*(const GVec3& o) const { return {x*o.x, y*o.y, z*o.z}; }
    HD GVec3 operator/(float s) const { float inv=1.f/s; return {x*inv, y*inv, z*inv}; }
    HD GVec3& operator+=(const GVec3& o) { x+=o.x; y+=o.y; z+=o.z; return *this; }
    HD GVec3& operator*=(float s) { x*=s; y*=s; z*=s; return *this; }
    HD float dot(const GVec3& o) const { return x*o.x + y*o.y + z*o.z; }
    HD GVec3 cross(const GVec3& o) const { return {y*o.z-z*o.y, z*o.x-x*o.z, x*o.y-y*o.x}; }
    HD float length() const { return sqrtf(dot(*this)); }
    HD GVec3 normalized() const { float l=length(); return l>0 ? *this*(1.f/l) : GVec3(0); }
    HD float maxComponent() const { return fmaxf(x, fmaxf(y, z)); }
    HD bool operator!=(const GVec3& o) const { return x!=o.x||y!=o.y||z!=o.z; }
};

HD inline float luminance(const GVec3& c) { return 0.2126f*c.x + 0.7152f*c.y + 0.0722f*c.z; }

struct GRay {
    GVec3 origin, direction;
    HD GRay() {}
    HD GRay(GVec3 o, GVec3 d) : origin(o), direction(d.normalized()) {}
};

struct GAABB {
    GVec3 min, max;
    HD bool hit(const GRay& r, float tMin, float tMax) const {
        // Slab method — standard GPU BVH traversal
        for (int a = 0; a < 3; a++) {
            float invD = 1.0f / ((&r.direction.x)[a]);
            float t0 = ((&min.x)[a] - (&r.origin.x)[a]) * invD;
            float t1 = ((&max.x)[a] - (&r.origin.x)[a]) * invD;
            if (invD < 0) { float tmp = t0; t0 = t1; t1 = tmp; }
            if (t0 > tMin) tMin = t0;
            if (t1 < tMax) tMax = t1;
            if (tMax <= tMin) return false;
        }
        return true;
    }
};

// Flattened BVH node — matches existing LinearBVHNode layout
struct GBVHNode {
    GAABB bounds;
    union {
        int primitivesOffset;   // leaf
        int secondChildOffset;  // interior
    };
    uint16_t nPrimitives;  // 0 = interior
    uint8_t axis;
    uint8_t pad;
};

struct GTriangle {
    GVec3 v0, v1, v2;
    GVec3 n0, n1, n2;  // per-vertex normals (or face normal repeated)
    int materialId;
};

struct GSphere {
    GVec3 center;
    float radius;
    int materialId;
};

// Tagged union for primitives — GPU can't do virtual dispatch
enum GPrimType : uint8_t { GPRIM_TRIANGLE = 0, GPRIM_SPHERE = 1 };
struct GPrimitive {
    GPrimType type;
    int index;  // index into triangle or sphere array
};

// Material as a flat struct with a type tag — replaces virtual dispatch
enum GMaterialType : uint8_t {
    GMAT_LAMBERTIAN = 0,
    GMAT_METAL = 1,
    GMAT_DIELECTRIC = 2,
    GMAT_DIFFUSE_LIGHT = 3,
    GMAT_DISNEY = 4
};

struct GMaterial {
    GMaterialType type;
    GVec3 baseColor;
    float roughness;
    float metallic;
    float ior;
    float transmission;
    float clearcoat;
    float clearcoatGloss;
    float emission_intensity;  // >0 means emissive
    // Add more Disney params as needed
};

struct GHitRecord {
    GVec3 point, normal, tangent, bitangent;
    float t;
    int materialId;
    bool frontFace;
    bool isDelta;
};

struct GBSDFSample {
    GVec3 wi, f;
    float pdf;
    bool isDelta;
};

// Light info for NEE
struct GLight {
    int primitiveIndex;
    float power;       // for selection probability
    float cumulativePower;  // for CDF sampling
};

// Environment map data (device pointers set during upload)
struct GEnvMap {
    float* data;           // RGB interleaved, device memory
    float* conditionalCdf; // device
    float* conditionalFunc;// device
    float* marginalCdf;    // device
    float* marginalFunc;   // device
    int width, height;
    float strength, rotation, totalPower;
    bool loaded;
};
```

### Task 2: GPU material evaluation (`include/astroray/gpu_materials.h`)

Port each material's `eval()`, `sample()`, and `pdf()` as `__device__` functions that switch on `GMaterialType`. This is the most code-heavy task — essentially rewriting all material logic without virtual dispatch.

Key pattern:
```cpp
__device__ GVec3 gpu_material_eval(const GMaterial& mat, const GHitRecord& rec,
                                    const GVec3& wo, const GVec3& wi) {
    switch (mat.type) {
        case GMAT_LAMBERTIAN: return gpu_lambertian_eval(mat, rec, wo, wi);
        case GMAT_METAL:      return gpu_metal_eval(mat, rec, wo, wi);
        case GMAT_DIELECTRIC: return GVec3(0); // delta material
        case GMAT_DISNEY:     return gpu_disney_eval(mat, rec, wo, wi);
        default: return GVec3(0);
    }
}
```

**Port the exact same formulas from raytracer.h and advanced_features.h.** The CPU code is the reference. Key things:
- Lambertian: `baseColor / π × NdotL`
- Metal: GGX microfacet with Fresnel, including the roughness < 0.08 delta path
- Dielectric: Schlick Fresnel, refraction via Snell's law, isDelta = true always
- Disney BRDF: the full `eval()` from advanced_features.h (D_GTR2, smithG_GGX, fresnelSchlick)
- Use `curand_uniform()` for random numbers (passed via `curandState*`)

**CRITICAL: Use the CORRECTED formulas from raytracer.h**, not textbook formulas. The codebase has specific fixes (e.g., Metal reflection direction is `2*(wo·n)*n - wo`, NOT `wo - 2*(wo·n)*n`; eval() returns brdf×NdotL with cosine included; roughness < 0.08 uses perfect mirror path).

### Task 3: GPU BVH traversal (`include/astroray/gpu_bvh.h`)

Port the existing `BVHAccel::hit()` iterative traversal. The CPU code already uses a flat array with explicit stack — this maps almost directly to GPU:

```cpp
__device__ bool gpu_bvh_hit(const GBVHNode* nodes, const GPrimitive* prims,
                             const GTriangle* tris, const GSphere* spheres,
                             const GRay& ray, float tMin, float tMax,
                             GHitRecord& rec, const GMaterial* materials) {
    // Iterative traversal with thread-local stack[64]
    // Identical logic to BVHAccel::hit() in raytracer.h
}
```

Also port ray-triangle (Möller–Trumbore) and ray-sphere intersection as `__device__` functions. These already exist in raytracer.h — translate them to use GVec3/GRay.

### Task 4: CMake CUDA integration

Add CUDA support to CMakeLists.txt with graceful fallback:

```cmake
# After the existing project() declaration:
option(ASTRORAY_ENABLE_CUDA "Enable CUDA GPU acceleration" ON)

if(ASTRORAY_ENABLE_CUDA)
    include(CheckLanguage)
    check_language(CUDA)
    if(CMAKE_CUDA_COMPILER)
        enable_language(CUDA)
        find_package(CUDAToolkit REQUIRED)
        set(CMAKE_CUDA_ARCHITECTURES "75;86;89")  # Turing, Ampere, Ada Lovelace
        set(ASTRORAY_CUDA_FOUND TRUE)
        message(STATUS "CUDA found: ${CMAKE_CUDA_COMPILER}")
    else()
        set(ASTRORAY_CUDA_FOUND FALSE)
        message(STATUS "CUDA not found — GPU acceleration disabled")
    endif()
else()
    set(ASTRORAY_CUDA_FOUND FALSE)
endif()

# CUDA static library (only if CUDA available)
if(ASTRORAY_CUDA_FOUND)
    add_library(astroray_cuda STATIC
        src/gpu/cuda_renderer.cu
        src/gpu/path_trace_kernel.cu
        src/gpu/scene_upload.cu
    )
    target_include_directories(astroray_cuda PUBLIC ${CMAKE_SOURCE_DIR}/include)
    target_compile_options(astroray_cuda PRIVATE
        $<$<COMPILE_LANGUAGE:CUDA>:--extended-lambda --expt-relaxed-constexpr -O3>
    )
    set_target_properties(astroray_cuda PROPERTIES
        CUDA_SEPARABLE_COMPILATION ON
        POSITION_INDEPENDENT_CODE ON
        CUDA_RESOLVE_DEVICE_SYMBOLS ON
    )
    target_link_libraries(astroray_cuda PRIVATE CUDA::curand)
endif()

# Link CUDA lib into existing targets (AFTER their definitions)
if(ASTRORAY_CUDA_FOUND)
    target_link_libraries(astroray PRIVATE astroray_cuda)
    target_compile_definitions(astroray PRIVATE ASTRORAY_CUDA_ENABLED)

    target_link_libraries(raytracer_standalone PRIVATE astroray_cuda)
    target_compile_definitions(raytracer_standalone PRIVATE ASTRORAY_CUDA_ENABLED)
endif()
```

**IMPORTANT:** The pybind11 module (`astroray`) and standalone binary link against `astroray_cuda` as a regular C++ library. They never include CUDA headers — only `gpu_renderer.h` which is pure C++.

## Phase 2B: The Megakernel

### Task 5: Scene upload (`src/gpu/scene_upload.cu`)

Converts CPU scene data to GPU arrays. The CUDARenderer holds device pointers:

```cpp
struct CUDARenderer::Impl {
    // Device arrays
    GBVHNode* d_bvhNodes = nullptr;
    GPrimitive* d_primitives = nullptr;
    GTriangle* d_triangles = nullptr;
    GSphere* d_spheres = nullptr;
    GMaterial* d_materials = nullptr;
    GLight* d_lights = nullptr;
    int numLights = 0;
    float totalLightPower = 0;

    // Environment map
    GEnvMap d_envMap = {};

    // Output
    float* d_framebuffer = nullptr;  // width * height * 3

    // RNG states
    curandState* d_rngStates = nullptr;

    int width = 0, height = 0;
};
```

Implement `uploadScene()` that takes the CPU Renderer's data and:
1. Flattens BVH nodes → `GBVHNode[]` (the LinearBVHNode array already exists, just convert types)
2. Converts primitives → `GPrimitive[]` with type tags
3. Converts triangles/spheres → `GTriangle[]`/`GSphere[]`
4. Converts materials → `GMaterial[]` (map from shared_ptr<Material> to flat GMaterial by checking dynamic_cast or a type tag)
5. Builds light list → `GLight[]` with CDF for power-weighted selection
6. Uploads environment map data if present
7. Allocates framebuffer and curand states
8. Uses `cudaMalloc` + `cudaMemcpy` for each array

**Scene extraction from CPU Renderer:** The CPU `Renderer` class currently stores `scene` (vector of Hittable*), `bvh`, and `lights`. You'll need to add accessor methods or a friend declaration so CUDARenderer can read these. Simplest: add public getters:
```cpp
// In Renderer class (raytracer.h):
const std::vector<std::shared_ptr<Hittable>>& getScene() const { return scene; }
const std::shared_ptr<BVHAccel>& getBVH() const { return bvh; }
const LightList& getLights() const { return lights; }
```

### Task 6: Path tracing megakernel (`src/gpu/path_trace_kernel.cu`)

One CUDA thread per (pixel, sample) pair. Each thread runs the full path tracing loop independently.

```cpp
__global__ void pathTraceKernel(
    float* framebuffer, int width, int height, int samplesPerPixel, int maxDepth,
    const GBVHNode* bvhNodes, const GPrimitive* prims,
    const GTriangle* tris, const GSphere* spheres,
    const GMaterial* materials,
    const GLight* lights, int numLights, float totalLightPower,
    GEnvMap envMap,
    // Camera params (passed as kernel args, not struct, to avoid alignment issues)
    GVec3 camOrigin, GVec3 camLowerLeft, GVec3 camHorizontal, GVec3 camVertical,
    GVec3 camU, GVec3 camV, float camLensRadius,
    curandState* rngStates
) {
    int pixelIdx = blockIdx.x * blockDim.x + threadIdx.x;
    int totalPixels = width * height;
    if (pixelIdx >= totalPixels) return;

    int px = pixelIdx % width;
    int py = pixelIdx / width;
    curandState localRng = rngStates[pixelIdx];

    GVec3 color(0);
    for (int s = 0; s < samplesPerPixel; s++) {
        float u = (px + curand_uniform(&localRng)) / (width - 1);
        float v = 1.0f - (py + curand_uniform(&localRng)) / (height - 1);

        // Generate camera ray (with DOF if lensRadius > 0)
        GRay ray = generateCameraRay(camOrigin, camLowerLeft, camHorizontal,
                                      camVertical, camU, camV, camLensRadius,
                                      u, v, &localRng);

        GVec3 sampleColor = tracePathGPU(ray, maxDepth, bvhNodes, prims, tris,
                                          spheres, materials, lights, numLights,
                                          totalLightPower, envMap, &localRng);

        // Firefly clamp
        float lum = luminance(sampleColor);
        if (lum > 20.0f) sampleColor = sampleColor * (20.0f / lum);
        color += sampleColor;
    }

    color = color / (float)samplesPerPixel;
    // Gamma + clamp
    color.x = powf(fminf(fmaxf(color.x, 0.f), 1.f), 1.f/2.2f);
    color.y = powf(fminf(fmaxf(color.y, 0.f), 1.f), 1.f/2.2f);
    color.z = powf(fminf(fmaxf(color.z, 0.f), 1.f), 1.f/2.2f);

    framebuffer[pixelIdx * 3 + 0] = color.x;
    framebuffer[pixelIdx * 3 + 1] = color.y;
    framebuffer[pixelIdx * 3 + 2] = color.z;

    rngStates[pixelIdx] = localRng;
}
```

The `tracePathGPU()` device function is a direct port of `Renderer::pathTrace()`:
- Same bounce loop structure
- Same NEE+MIS via `sampleDirectGPU()`
- Same Russian Roulette after bounce 3
- Same throughput clamping
- Replace `std::mt19937` + `std::uniform_real_distribution` with `curand_uniform()`
- Replace `std::make_shared<>` with nothing (materials are in a flat array, indexed by materialId)

### Task 7: CUDARenderer C++ interface (`src/gpu/cuda_renderer.cu` + `include/astroray/gpu_renderer.h`)

```cpp
// gpu_renderer.h — pure C++, no CUDA
#pragma once
#include <memory>
#include <vector>
#include <string>

// Forward declare to avoid including raytracer.h if possible,
// but it's fine to include it since gpu_renderer.h is pure C++
#include "raytracer.h"

class CUDARenderer {
public:
    CUDARenderer();
    ~CUDARenderer();

    bool isAvailable() const;
    std::string deviceName() const;

    // Upload scene from CPU renderer
    void uploadScene(const Renderer& cpuRenderer, const Camera& camera);

    // Upload environment map
    void uploadEnvironmentMap(const EnvironmentMap& envMap);

    // Render to pixel buffer (host memory, HxWx3 float, post-gamma)
    void render(std::vector<Vec3>& pixels, int width, int height,
                int samplesPerPixel, int maxDepth);

    // Progress query (for async rendering later)
    float getProgress() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};
```

### Task 8: Python bindings integration

Modify `module/blender_module.cpp` to add GPU support:

```cpp
// In PyRenderer class:
#ifdef ASTRORAY_CUDA_ENABLED
#include "astroray/gpu_renderer.h"
std::unique_ptr<CUDARenderer> cudaRenderer;
#endif
bool useGPU = false;

void setUseGPU(bool enable) {
#ifdef ASTRORAY_CUDA_ENABLED
    if (enable && !cudaRenderer) {
        cudaRenderer = std::make_unique<CUDARenderer>();
        if (!cudaRenderer->isAvailable()) {
            cudaRenderer.reset();
            throw std::runtime_error("No CUDA GPU available");
        }
    }
    useGPU = enable && cudaRenderer && cudaRenderer->isAvailable();
#else
    if (enable) throw std::runtime_error("CUDA support not compiled");
#endif
}
```

In `render()`, branch on `useGPU`:
```cpp
if (useGPU) {
    cudaRenderer->uploadScene(renderer, *camera);
    if (envMap && envMap->loaded()) cudaRenderer->uploadEnvironmentMap(*envMap);
    std::vector<Vec3> gpuPixels(camera->width * camera->height);
    cudaRenderer->render(gpuPixels, camera->width, camera->height, samplesPerPixel, maxDepth);
    camera->pixels = std::move(gpuPixels);
} else {
    renderer.render(*camera, samplesPerPixel, maxDepth, callback, useAdaptiveSampling);
}
```

Expose in pybind11:
```cpp
.def("set_use_gpu", &PyRenderer::setUseGPU, "enable"_a)
.def_property_readonly("gpu_available", [](PyRenderer& self) {
#ifdef ASTRORAY_CUDA_ENABLED
    CUDARenderer test;
    return test.isAvailable();
#else
    return false;
#endif
})
.def_property_readonly("gpu_device_name", [](PyRenderer& self) -> std::string {
#ifdef ASTRORAY_CUDA_ENABLED
    CUDARenderer test;
    return test.isAvailable() ? test.deviceName() : "none";
#else
    return "CUDA not compiled";
#endif
})
```

Also update `__features__` dict to include `"cuda"_a = ...`.

### Task 9: Blender addon GPU toggle

Add to `CustomRaytracerRenderSettings`:
```python
use_gpu: BoolProperty(name="Use GPU", default=False,
    description="Use CUDA GPU for rendering (requires NVIDIA GPU)")
```

In `render()`:
```python
if settings.use_gpu:
    try:
        renderer.set_use_gpu(True)
        print(f"GPU rendering: {renderer.gpu_device_name}")
    except Exception as e:
        print(f"GPU not available, falling back to CPU: {e}")
```

Add to the sampling panel UI:
```python
col.prop(settings, "use_gpu")
if hasattr(renderer, 'gpu_available'):
    if renderer.gpu_available:
        col.label(text=f"GPU: {renderer.gpu_device_name}")
```

### Task 10: Tests

```python
def test_cuda_availability():
    """Check that GPU detection works without crashing."""
    r = create_renderer()
    gpu_avail = r.gpu_available
    assert isinstance(gpu_avail, bool)
    if gpu_avail:
        print(f"GPU available: {r.gpu_device_name}")

def test_gpu_renders_match_cpu():
    """GPU and CPU should produce similar results (not identical due to FP ordering)."""
    r_cpu = create_renderer()
    create_cornell_box(r_cpu)
    mat = r_cpu.create_material('disney', [0.8, 0.4, 0.2], {'roughness': 0.3, 'metallic': 0.5})
    r_cpu.add_sphere([0, -0.5, 0], 1.0, mat)
    setup_camera(r_cpu, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=200, height=150)
    pixels_cpu = render_image(r_cpu, samples=64)

    if not r_cpu.gpu_available:
        pytest.skip("No CUDA GPU")

    r_gpu = create_renderer()
    create_cornell_box(r_gpu)
    mat2 = r_gpu.create_material('disney', [0.8, 0.4, 0.2], {'roughness': 0.3, 'metallic': 0.5})
    r_gpu.add_sphere([0, -0.5, 0], 1.0, mat2)
    setup_camera(r_gpu, look_from=[0, 0, 5.5], look_at=[0, 0, 0], vfov=38, width=200, height=150)
    r_gpu.set_use_gpu(True)
    pixels_gpu = render_image(r_gpu, samples=64)

    # Mean brightness should be within 15% (Monte Carlo variance + FP differences)
    cpu_mean = float(np.mean(pixels_cpu))
    gpu_mean = float(np.mean(pixels_gpu))
    assert abs(cpu_mean - gpu_mean) < 0.15 * cpu_mean, \
        f"GPU ({gpu_mean:.3f}) and CPU ({cpu_mean:.3f}) differ too much"
```

## Critical Implementation Notes

### RNG on GPU
Use cuRAND device API. Initialize states once per pixel:
```cpp
__global__ void initRNG(curandState* states, int n, unsigned long long seed) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < n) curand_init(seed, idx, 0, &states[idx]);
}
```
Then `curand_uniform(&state)` replaces `dist(gen)`. Use `curand_normal(&state)` for Gaussian samples if needed.

### Warp divergence mitigation
The biggest divergence source is material dispatch (the `switch` in eval/sample). In a megakernel this is unavoidable — warps containing mixed material types will serialize. This is acceptable for Phase 2. Phase 3 (if needed) would move to wavefront architecture.

### Memory alignment
`GMaterial` should be padded to 64 bytes for coalesced access. Use `__align__(16)` on structs if needed. The BVH node should be 32 bytes (matches cache lines).

### Thread configuration
```cpp
int threadsPerBlock = 256;
int totalPixels = width * height;
int blocks = (totalPixels + threadsPerBlock - 1) / threadsPerBlock;
pathTraceKernel<<<blocks, threadsPerBlock>>>(...);
```

### Error checking
Wrap every CUDA call:
```cpp
#define CUDA_CHECK(call) do { \
    cudaError_t err = call; \
    if (err != cudaSuccess) { \
        fprintf(stderr, "CUDA error at %s:%d: %s\n", __FILE__, __LINE__, \
                cudaGetErrorString(err)); \
        throw std::runtime_error(cudaGetErrorString(err)); \
    } \
} while(0)
```

### Build verification
After building, verify:
1. `cmake ..` shows "CUDA found: /path/to/nvcc"
2. Building without CUDA toolkit installed still succeeds (CPU-only mode)
3. `import astroray; print(astroray.__features__['cuda'])` returns True/False correctly
4. `r.gpu_available` returns True on a machine with NVIDIA GPU
5. GPU render produces a non-black image matching CPU output within Monte Carlo noise

## File dependency graph

```
gpu_types.h (no deps)
  ├── gpu_materials.h (depends on gpu_types.h)
  ├── gpu_bvh.h (depends on gpu_types.h)
  └── gpu_renderer.h (depends on raytracer.h — for the upload interface)
        └── cuda_renderer.cu (depends on gpu_types, gpu_materials, gpu_bvh)
        └── path_trace_kernel.cu (depends on gpu_types, gpu_materials, gpu_bvh)
        └── scene_upload.cu (depends on gpu_types, raytracer.h)
```

## What NOT to do

- Do NOT put `#include <cuda_runtime.h>` in any header that pybind11 includes
- Do NOT use `thrust` unless absolutely necessary (adds compile time, often slower than raw CUDA for path tracing)
- Do NOT attempt OptiX yet — that's Phase 3 after the megakernel works
- Do NOT rewrite the CPU renderer — it stays exactly as-is
- Do NOT use CUDA unified memory (it's slower than explicit cudaMemcpy for this workload pattern)
- Do NOT try to make materials use virtual dispatch on GPU (no vtables in device code)
- Do NOT put samples-per-pixel in the thread index — put pixels in the thread index and loop over samples per thread (reduces RNG state memory and register pressure)

// cuda_renderer.cu — CUDARenderer implementation.
// This file is the single point where all CUDA runtime calls live.
// It exposes the pure-C++ CUDARenderer interface from gpu_renderer.h.

#include "astroray/gpu_renderer.h"
#include "astroray/gpu_scene_upload.h"
#include "astroray/gpu_types.h"
#include "raytracer.h"
#include "advanced_features.h"

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <vector>
#include <string>
#include <stdexcept>
#include <cstdio>
#include <ctime>

#define CUDA_CHECK(call) do {                                           \
    cudaError_t _e = (call);                                           \
    if (_e != cudaSuccess) {                                           \
        fprintf(stderr, "CUDA error at %s:%d: %s\n",                  \
                __FILE__, __LINE__, cudaGetErrorString(_e));           \
        throw std::runtime_error(cudaGetErrorString(_e));             \
    }                                                                   \
} while(0)

// Forward declarations of kernel launcher functions defined in path_trace_kernel.cu
void launchInitRNG(curandState* d_states, int n, unsigned long long seed);
void launchPathTraceKernel(
    float* d_framebuffer, int width, int height,
    int samplesPerPixel, int maxDepth,
    const GBVHNode*  d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials,
    const GLight*     d_lights, int numLights, float totalLightPower,
    GEnvMap envMap,
    GCameraParams cam,
    float filmExposure,
    GVec3 backgroundColor, bool hasBackgroundColor,
    curandState* d_rngStates);

// ---------------------------------------------------------------------------
// Helper: upload host vector → device array
// ---------------------------------------------------------------------------
template<typename T>
static void devUpload(const std::vector<T>& src, T** d_ptr) {
    if (*d_ptr) { cudaFree(*d_ptr); *d_ptr = nullptr; }
    if (src.empty()) return;
    CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(d_ptr), src.size() * sizeof(T)));
    CUDA_CHECK(cudaMemcpy(*d_ptr, src.data(), src.size() * sizeof(T), cudaMemcpyHostToDevice));
}

// ---------------------------------------------------------------------------
// CUDARenderer::Impl — holds all device allocations
// ---------------------------------------------------------------------------
struct CUDARenderer::Impl {
    // Device scene arrays
    GBVHNode*   d_bvhNodes   = nullptr;
    GPrimitive* d_prims      = nullptr;
    GTriangle*  d_triangles  = nullptr;
    GSphere*    d_spheres    = nullptr;
    GMaterial*  d_materials  = nullptr;
    GLight*     d_lights     = nullptr;
    int         numLights    = 0;
    float       totalLightPower = 0.f;

    // Environment map device buffers
    float* d_envData      = nullptr;
    float* d_envCondCdf   = nullptr;
    float* d_envCondFunc  = nullptr;
    float* d_envMargCdf   = nullptr;
    float* d_envMargFunc  = nullptr;
    GEnvMap envMap        = {};

    // Camera
    GCameraParams camera  = {};
    GVec3 backgroundColor = {};
    bool  hasBackgroundColor = false;
    float filmExposure    = 1.0f;

    // Output / RNG
    float*       d_framebuffer = nullptr;
    curandState* d_rngStates   = nullptr;
    int          fbWidth = 0, fbHeight = 0;

    // Device info
    bool        available = false;
    std::string devName   = "none";

    Impl() {
        int count = 0;
        cudaError_t err = cudaGetDeviceCount(&count);
        if (err == cudaSuccess && count > 0) {
            available = true;
            cudaDeviceProp prop;
            cudaGetDeviceProperties(&prop, 0);
            devName = prop.name;
        }
    }

    ~Impl() { freeAll(); }

    void freeAll() {
        if (d_bvhNodes)   { cudaFree(d_bvhNodes);   d_bvhNodes   = nullptr; }
        if (d_prims)      { cudaFree(d_prims);       d_prims      = nullptr; }
        if (d_triangles)  { cudaFree(d_triangles);   d_triangles  = nullptr; }
        if (d_spheres)    { cudaFree(d_spheres);     d_spheres    = nullptr; }
        if (d_materials)  { cudaFree(d_materials);   d_materials  = nullptr; }
        if (d_lights)     { cudaFree(d_lights);      d_lights     = nullptr; }
        freeEnv();
        if (d_framebuffer){ cudaFree(d_framebuffer); d_framebuffer= nullptr; }
        if (d_rngStates)  { cudaFree(d_rngStates);  d_rngStates  = nullptr; }
    }

    void freeEnv() {
        if (d_envData)     { cudaFree(d_envData);     d_envData     = nullptr; }
        if (d_envCondCdf)  { cudaFree(d_envCondCdf);  d_envCondCdf  = nullptr; }
        if (d_envCondFunc) { cudaFree(d_envCondFunc); d_envCondFunc = nullptr; }
        if (d_envMargCdf)  { cudaFree(d_envMargCdf);  d_envMargCdf  = nullptr; }
        if (d_envMargFunc) { cudaFree(d_envMargFunc); d_envMargFunc = nullptr; }
        envMap = {};
    }

    void ensureFramebuffer(int w, int h) {
        if (w == fbWidth && h == fbHeight && d_framebuffer) return;
        if (d_framebuffer) { cudaFree(d_framebuffer); d_framebuffer = nullptr; }
        if (d_rngStates)   { cudaFree(d_rngStates);   d_rngStates   = nullptr; }
        fbWidth = w; fbHeight = h;
        int n = w * h;
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_framebuffer), n * 3 * sizeof(float)));
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_rngStates),   n * sizeof(curandState)));
        // Seed RNG once; re-seed will be called from render()
    }
};

// ---------------------------------------------------------------------------
// CUDARenderer public API
// ---------------------------------------------------------------------------
CUDARenderer::CUDARenderer() : impl(std::make_unique<Impl>()) {}
CUDARenderer::~CUDARenderer() = default;

bool CUDARenderer::isAvailable() const { return impl->available; }
std::string CUDARenderer::deviceName() const { return impl->devName; }
float CUDARenderer::getProgress() const { return 0.f; }

void CUDARenderer::uploadScene(const Renderer& cpuRenderer, const Camera& cam) {
    if (!impl->available) throw std::runtime_error("No CUDA GPU available");

    // Build flat arrays on the host
    SceneUploadResult r = buildSceneArrays(cpuRenderer, cam);

    // Upload to device
    devUpload(r.nodes,     &impl->d_bvhNodes);
    devUpload(r.prims,     &impl->d_prims);
    devUpload(r.triangles, &impl->d_triangles);
    devUpload(r.spheres,   &impl->d_spheres);
    devUpload(r.materials, &impl->d_materials);
    devUpload(r.lights,    &impl->d_lights);

    impl->numLights       = (int)r.lights.size();
    impl->totalLightPower = r.totalLightPower;
    impl->camera          = r.camera;

    // Film exposure
    impl->filmExposure = cpuRenderer.getFilmExposure();

    // Background color
    Vec3 bg = cpuRenderer.getBackgroundColor();
    if (bg.x >= 0.f) {
        impl->backgroundColor    = GVec3(bg.x, bg.y, bg.z);
        impl->hasBackgroundColor = true;
    } else {
        impl->hasBackgroundColor = false;
    }

    // Upload env map if present
    if (r.envLoaded) {
        impl->freeEnv();
        devUpload(r.envData,     &impl->d_envData);
        devUpload(r.envCondCdf,  &impl->d_envCondCdf);
        devUpload(r.envCondFunc, &impl->d_envCondFunc);
        devUpload(r.envMargCdf,  &impl->d_envMargCdf);
        devUpload(r.envMargFunc, &impl->d_envMargFunc);

        impl->envMap.data            = impl->d_envData;
        impl->envMap.conditionalCdf  = impl->d_envCondCdf;
        impl->envMap.conditionalFunc = impl->d_envCondFunc;
        impl->envMap.marginalCdf     = impl->d_envMargCdf;
        impl->envMap.marginalFunc    = impl->d_envMargFunc;
        impl->envMap.width           = r.envWidth;
        impl->envMap.height          = r.envHeight;
        impl->envMap.strength        = r.envStrength;
        impl->envMap.rotation        = r.envRotation;
        impl->envMap.totalPower      = r.envTotalPower;
        impl->envMap.loaded          = true;
    }

    printf("[CUDA] Scene uploaded: %zu nodes, %zu prims, %zu mats, %d lights\n",
           r.nodes.size(), r.prims.size(), r.materials.size(), impl->numLights);
}

void CUDARenderer::uploadEnvironmentMap(const EnvironmentMap& envMap) {
    if (!impl->available) return;
    if (!envMap.loaded()) return;

    impl->freeEnv();

    auto doUpload = [&](const std::vector<float>& v, float** d) {
        if (v.empty()) return;
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(d), v.size() * sizeof(float)));
        CUDA_CHECK(cudaMemcpy(*d, v.data(), v.size() * sizeof(float), cudaMemcpyHostToDevice));
    };
    doUpload(envMap.getData(),            &impl->d_envData);
    doUpload(envMap.getConditionalCdf(),  &impl->d_envCondCdf);
    doUpload(envMap.getConditionalFunc(), &impl->d_envCondFunc);
    doUpload(envMap.getMarginalCdf(),     &impl->d_envMargCdf);
    doUpload(envMap.getMarginalFunc(),    &impl->d_envMargFunc);

    impl->envMap.data            = impl->d_envData;
    impl->envMap.conditionalCdf  = impl->d_envCondCdf;
    impl->envMap.conditionalFunc = impl->d_envCondFunc;
    impl->envMap.marginalCdf     = impl->d_envMargCdf;
    impl->envMap.marginalFunc    = impl->d_envMargFunc;
    impl->envMap.width           = envMap.getWidth();
    impl->envMap.height          = envMap.getHeight();
    impl->envMap.strength        = envMap.getStrength();
    impl->envMap.rotation        = envMap.getRotation();
    impl->envMap.totalPower      = envMap.getTotalPower();
    impl->envMap.loaded          = true;
}

void CUDARenderer::render(
    std::vector<Vec3>& pixels, int width, int height,
    int samplesPerPixel, int maxDepth)
{
    if (!impl->available) throw std::runtime_error("No CUDA GPU available");
    if (!impl->d_bvhNodes) throw std::runtime_error("Scene not uploaded — call uploadScene() first");

    impl->ensureFramebuffer(width, height);
    int totalPixels = width * height;

    // Re-seed RNG every render (use time + address for unique seed)
    unsigned long long seed = (unsigned long long)time(nullptr);
    launchInitRNG(impl->d_rngStates, totalPixels, seed);

    // Launch megakernel
    launchPathTraceKernel(
        impl->d_framebuffer, width, height, samplesPerPixel, maxDepth,
        impl->d_bvhNodes, impl->d_prims, impl->d_triangles, impl->d_spheres,
        impl->d_materials,
        impl->d_lights, impl->numLights, impl->totalLightPower,
        impl->envMap,
        impl->camera,
        impl->filmExposure,
        impl->backgroundColor, impl->hasBackgroundColor,
        impl->d_rngStates);

    // Copy result back to host
    std::vector<float> hostFb(totalPixels * 3);
    CUDA_CHECK(cudaMemcpy(hostFb.data(), impl->d_framebuffer,
                          totalPixels * 3 * sizeof(float),
                          cudaMemcpyDeviceToHost));

    pixels.resize(totalPixels);
    for (int i = 0; i < totalPixels; ++i)
        pixels[i] = Vec3(hostFb[i*3], hostFb[i*3+1], hostFb[i*3+2]);

    printf("[CUDA] Render complete: %dx%d, %d spp\n", width, height, samplesPerPixel);
}

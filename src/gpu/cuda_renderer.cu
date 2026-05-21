// cuda_renderer.cu — CUDARenderer implementation.
// This file is the single point where all CUDA runtime calls live.
// It exposes the pure-C++ CUDARenderer interface from gpu_renderer.h.

#include "astroray/gpu_renderer.h"
#include "astroray/gpu_scene_upload.h"
#include "astroray/gpu_types.h"
#include "raytracer.h"
#include "advanced_features.h"
#include "profile.h"  // pkg55-A: env-gated NVTX ranges around upload + render
#ifdef ASTRORAY_WAVEFRONT_INTERSECT
// pkg55-A.1: wavefront SoA primary-ray + intersect kernels (opt-in).
#include "astroray/integrator_state_soa.h"
#endif

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <vector>
#include <string>
#include <stdexcept>
#include <cstring>
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

// pkg54a — copies per-material spectral profiles into MW kernel constant memory.
void uploadProfileTable(const float* host, int count);
// pkg54b — one-time copy of CIE 1964 10° CMF tables into MW kernel constant memory.
void uploadCmfTables();
// pkg54c — one-time copy of the Jakob-Hanika sRGB sigmoid LUT into MW kernel
// global memory; required by gpu_jhEvalSpectrum (the new upsampling path).
void uploadJakobHanikaLut();
float launchProfileLookup(int profileIndex, float lambda);

// pkg64-gpu Phase 1 probe harness (defined in pkg64_sms_probe.cu).
void launchPkg64SmsProbe(
    const Renderer& hostRenderer,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials,
    const GLight*     d_lights,
    int numLights);

void launchMultiwavelengthKernel(
    float* d_framebuffer, int width, int height,
    int samplesPerPixel, int maxDepth,
    float lambdaMin, float lambdaMax, bool useLuminanceOutput,
    bool enableNEE,
    const GBVHNode*  d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials,
    const GLight*     d_lights, int numLights, float totalLightPower,
    GEnvMap envMap,
    GCameraParams cam,
    GVec3 backgroundColor, bool hasBackgroundColor,
    curandState* d_rngStates);

// ---------------------------------------------------------------------------
// Helper: upload host vector → device array
// ---------------------------------------------------------------------------
template<typename T>
static void devUpload(const std::vector<T>& src, T** d_ptr) {
    if (*d_ptr) {
        cudaFree(*d_ptr);
        *d_ptr = nullptr;
        // pkg85-B: clear any latent error from cudaFree (or from a prior
        // kernel) so cudaMalloc below isn't blamed for a stale error.
        cudaGetLastError();
    }
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
    int          profileCount = 0;

    // pkg64-gpu Phase 1 probe: stashed host Renderer for CPU reference.
    const Renderer* hostRenderer = nullptr;

    // Device info
    bool        available = false;
    std::string devName   = "none";

    Impl() {
        int count = 0;
        cudaError_t err = cudaGetDeviceCount(&count);
        if (err == cudaSuccess && count > 0) {
            cudaDeviceProp prop;
            err = cudaGetDeviceProperties(&prop, 0);
            if (err == cudaSuccess) {
                available = true;
                devName = prop.name;
            }
        }
        // pkg85: Clear any latent error from cudaGetDeviceCount or
        // cudaGetDeviceProperties so it doesn't contaminate future CUDA
        // calls in other tests/renderers. Must be called unconditionally
        // because even if we return early, a prior CUDA call may have left
        // an error.
        cudaGetLastError();
    }

    ~Impl() {
        freeAll();
        // pkg85: Clear any latent error from cleanup so it doesn't contaminate
        // future CUDA calls. The destructor is noexcept so we can't throw; we
        // must clear the error to prevent it from propagating.
        cudaGetLastError();
    }

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
        // pkg85-B: swallow any latent error from cudaFree (or from a prior
        // kernel launch that surfaced only here). freeAll() runs from both
        // the destructor (noexcept) and production cleanup paths; throwing
        // here would crash teardown and leak into the next test.
        cudaGetLastError();
    }

    void freeEnv() {
        if (d_envData)     { cudaFree(d_envData);     d_envData     = nullptr; }
        if (d_envCondCdf)  { cudaFree(d_envCondCdf);  d_envCondCdf  = nullptr; }
        if (d_envCondFunc) { cudaFree(d_envCondFunc); d_envCondFunc = nullptr; }
        if (d_envMargCdf)  { cudaFree(d_envMargCdf);  d_envMargCdf  = nullptr; }
        if (d_envMargFunc) { cudaFree(d_envMargFunc); d_envMargFunc = nullptr; }
        envMap = {};
        // pkg85-B: same rationale as freeAll(); cleanup path must not leak.
        cudaGetLastError();
    }

    void ensureFramebuffer(int w, int h) {
        if (w == fbWidth && h == fbHeight && d_framebuffer) return;
        if (d_framebuffer) { cudaFree(d_framebuffer); d_framebuffer = nullptr; }
        if (d_rngStates)   { cudaFree(d_rngStates);   d_rngStates   = nullptr; }
        // pkg85-B: free errors above must not contaminate the cudaMalloc below.
        cudaGetLastError();
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

// pkg56 Phase B — per-domain incremental uploaders.
//
// The CUDA scene state is partitioned into four independent slices
// (geometry, materials, lights, environment) plus camera + film state.
// Each slice has its own uploader that re-pushes only its device buffers.
// uploadScene() composes them into the full sequenced upload that today's
// callers (PyRenderer::render() on the GPU path) still rely on.
//
// Reference: Cycles BlenderSync per-domain upload pattern in
// intern/cycles/blender/sync.cpp (Apache-2.0). The per-domain split there
// is the BlenderSync class's geometry / shader / light / world members,
// each with their own dirty flag and update() entry; we mirror it at the
// CUDA layer so Phase C's depsgraph dispatch can target them individually.

void CUDARenderer::uploadGeometry(const Renderer& cpuRenderer, const Camera& cam) {
    if (!impl->available) throw std::runtime_error("No CUDA GPU available");

    // Mirrors BlenderSync::sync_geometry: rebuild the geometry-only slice and
    // push it. Materials/lights/env device buffers are intentionally untouched.
    SceneUploadResult r = buildSceneArrays(cpuRenderer, &cam);

    devUpload(r.nodes,     &impl->d_bvhNodes);
    devUpload(r.prims,     &impl->d_prims);
    devUpload(r.triangles, &impl->d_triangles);
    devUpload(r.spheres,   &impl->d_spheres);

    // Camera + film + background piggyback on geometry uploads — they're
    // tiny scalars and any caller that just changed geometry almost always
    // wants the projection fresh too.
    impl->camera       = r.camera;
    impl->filmExposure = cpuRenderer.getFilmExposure();
    Vec3 bg = cpuRenderer.getBackgroundColor();
    if (bg.x >= 0.f) {
        impl->backgroundColor    = GVec3(bg.x, bg.y, bg.z);
        impl->hasBackgroundColor = true;
    } else {
        impl->hasBackgroundColor = false;
    }

    printf("[CUDA] Geometry uploaded: %zu nodes, %zu prims, %zu tris, %zu spheres\n",
           r.nodes.size(), r.prims.size(), r.triangles.size(), r.spheres.size());
}

void CUDARenderer::uploadMaterials(const Renderer& cpuRenderer) {
    if (!impl->available) throw std::runtime_error("No CUDA GPU available");

    // Mirrors BlenderSync::sync_shaders / Shader::tag_update: refresh the
    // GMaterial flat array and the spectral-profile table only. Geometry,
    // lights, env device buffers are untouched. We pass nullptr for camera
    // because a material-only edit must not republish camera state.
    if (!cpuRenderer.getBVH()) {
        // No geometry to attach materials to yet. Caller is in the
        // "materials defined, no triangles" partial-state corner case
        // (research note §7 Phase B acceptance). Emit a clear log; render
        // will just produce a black image.
        printf("[CUDA] Materials upload: BVH not built; skipping (no primitives)\n");
        return;
    }
    SceneUploadResult r = buildSceneArrays(cpuRenderer, nullptr);

    devUpload(r.materials, &impl->d_materials);
    impl->profileCount = r.profileCount;

    // pkg54a: re-upload spectral profile table; it's keyed by material slot.
    if (r.profileCount > 0 && !r.profileTable.empty()) {
        uploadProfileTable(r.profileTable.data(), r.profileCount);
    }

    printf("[CUDA] Materials uploaded: %zu mats, %d profiles\n",
           r.materials.size(), r.profileCount);
}

void CUDARenderer::uploadLights(const Renderer& cpuRenderer) {
    if (!impl->available) throw std::runtime_error("No CUDA GPU available");

    // Mirrors BlenderSync::sync_lights: refresh the light buffer + power CDF.
    // Geometry/materials/env device buffers are untouched.
    if (!cpuRenderer.getBVH()) {
        printf("[CUDA] Lights upload: BVH not built; skipping\n");
        return;
    }
    SceneUploadResult r = buildSceneArrays(cpuRenderer, nullptr);

    devUpload(r.lights, &impl->d_lights);
    impl->numLights       = (int)r.lights.size();
    impl->totalLightPower = r.totalLightPower;

    printf("[CUDA] Lights uploaded: %d lights, total power %g\n",
           impl->numLights, impl->totalLightPower);
}

void CUDARenderer::uploadEnvironment(const Renderer& cpuRenderer) {
    if (!impl->available) throw std::runtime_error("No CUDA GPU available");

    // Mirrors BlenderSync world_recalc + Background::tag_update: refresh the
    // env atlas, sampling tables, rotation/tint, and (post-pkg63) the MIS CDF.
    // Geometry/materials/lights device buffers are untouched.
    auto& em = cpuRenderer.getEnvironmentMap();
    if (!em || !em->loaded()) {
        // World cleared — drop the device-side env state.
        impl->freeEnv();
        printf("[CUDA] Environment uploaded: cleared\n");
        return;
    }

    // The EnvironmentMap path is identical to uploadEnvironmentMap() — keep
    // the two entry points in sync. We delegate to it for the actual copy
    // so there's a single place where env device buffers are managed.
    uploadEnvironmentMap(*em);

    printf("[CUDA] Environment uploaded: %dx%d, strength %g\n",
           impl->envMap.width, impl->envMap.height, impl->envMap.strength);
}

void CUDARenderer::uploadScene(const Renderer& cpuRenderer, const Camera& cam) {
    // pkg56 Phase B: the monolithic upload now coexists with the four
    // per-domain entry points (uploadGeometry / uploadMaterials /
    // uploadLights / uploadEnvironment). When the caller wants the *full*
    // upload (final render path, viewport first frame, fallback for
    // unrecognised depsgraph updates) we do a single buildSceneArrays and
    // push every slice — the per-domain methods exist as Phase C dispatch
    // targets, NOT as the fast path for full sync. Calling them four
    // times here would re-run buildSceneArrays four times and regress the
    // Phase A baseline (~80 ms geometry build on a 100k-tri scene).
    //
    // Reference: Cycles BlenderSync per-domain upload pattern in
    // intern/cycles/blender/sync.cpp (Apache-2.0). The BlenderSync class
    // also has a single sync_data() that builds the host scene once, then
    // calls per-domain device_update() entry points — same factoring.
    astroray::gpu_profile::NvtxRange _nvtx_upload("CUDARenderer::uploadScene");
    if (!impl->available) throw std::runtime_error("No CUDA GPU available");

    // pkg64-gpu Phase 1 probe: stash host Renderer for CPU reference.
    impl->hostRenderer = &cpuRenderer;

    // Build flat arrays on the host (single pass).
    SceneUploadResult r = buildSceneArrays(cpuRenderer, &cam);

    // Upload to device — every slice.
    devUpload(r.nodes,     &impl->d_bvhNodes);
    devUpload(r.prims,     &impl->d_prims);
    devUpload(r.triangles, &impl->d_triangles);
    devUpload(r.spheres,   &impl->d_spheres);
    devUpload(r.materials, &impl->d_materials);
    devUpload(r.lights,    &impl->d_lights);

    impl->numLights       = (int)r.lights.size();
    impl->totalLightPower = r.totalLightPower;
    impl->camera          = r.camera;
    impl->profileCount    = r.profileCount;

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

    // Upload env map if present.
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
        // pkg63: rotation matrix + color tint replace single rotation float.
        std::memcpy(impl->envMap.rotMat, r.envRotMat, 9 * sizeof(float));
        std::memcpy(impl->envMap.colorTint, r.envColorTint, 3 * sizeof(float));
        impl->envMap.totalPower      = r.envTotalPower;
        impl->envMap.loaded          = true;
    }

    // pkg54a: upload spectral profile table (no-op when no profiles attached).
    if (r.profileCount > 0 && !r.profileTable.empty()) {
        uploadProfileTable(r.profileTable.data(), r.profileCount);
    }

    printf("[CUDA] Scene uploaded: %zu nodes, %zu prims, %zu mats, %d lights, %d profiles\n",
           r.nodes.size(), r.prims.size(), r.materials.size(), impl->numLights,
           r.profileCount);
}

float CUDARenderer::lookupProfileReflectance(int profileIndex, float lambda) const {
    if (!impl->available) throw std::runtime_error("No CUDA GPU available");
    if (profileIndex < 0 || profileIndex >= impl->profileCount) {
        throw std::runtime_error("Profile index was not uploaded in the current CUDA scene");
    }
    return launchProfileLookup(profileIndex, lambda);
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
    // pkg63: rotation matrix + color tint replace single rotation float.
    std::memcpy(impl->envMap.rotMat, envMap.getRotationMatrix(), 9 * sizeof(float));
    std::memcpy(impl->envMap.colorTint, envMap.getColorTint(), 3 * sizeof(float));
    impl->envMap.totalPower      = envMap.getTotalPower();
    impl->envMap.loaded          = true;
}

void CUDARenderer::render(
    std::vector<Vec3>& pixels, int width, int height,
    int seed, int samplesPerPixel, int maxDepth)
{
    if (!impl->available) throw std::runtime_error("No CUDA GPU available");
    // pkg85-C: allow world-only renders. The path-trace kernel's
    // gpu_bvh_hit() already returns false when d_bvhNodes is null, so a
    // scene with an environment map but no geometry should produce a
    // pure-env image rather than throwing here. Only fail if neither a
    // scene nor an environment map has been uploaded.
    if (!impl->d_bvhNodes && !impl->envMap.loaded)
        throw std::runtime_error("Scene not uploaded — call uploadScene() first");

    astroray::gpu_profile::NvtxRange _nvtx_render("CUDARenderer::render");
    impl->ensureFramebuffer(width, height);
    int totalPixels = width * height;

    // path_trace_kernel.cu uses gpu_rgbToSampledSpectrum(...) with
    // GSPEC_RGB_ILLUMINANT for environment colour, which now reads the
    // D65 SPD baked into MW kernel constant memory — make sure it's
    // uploaded before the kernel runs. pkg54c additionally requires the
    // Jakob-Hanika sigmoid LUT in device global memory because
    // gpu_rgbSpectrumAt now upsamples via gpu_jhEvalSpectrum.
    uploadCmfTables();
    uploadJakobHanikaLut();

    unsigned long long rngSeed = (seed == 0)
        ? (unsigned long long)time(nullptr)
        : (unsigned long long)seed;
    launchInitRNG(impl->d_rngStates, totalPixels, rngSeed);

    // pkg64-gpu Phase 1 probe hook — when ASTRORAY_PKG64_GPU_SMS_PROBE env
    // var is set, run the SMS probe harness (pkg64_sms_probe.cu) instead of
    // the normal render. The probe emits a single stderr line for
    // test_pkg64_gpu_sms_attempt_unit.py to parse.
    {
        const char* probe_env = std::getenv("ASTRORAY_PKG64_GPU_SMS_PROBE");
        bool probe_on = probe_env && probe_env[0] && std::strcmp(probe_env, "0") != 0;
        if (probe_on) {
            if (!impl->hostRenderer) {
                std::fprintf(stderr,
                    "[pkg64-gpu] sms attempt probe: no host Renderer stashed "
                    "(uploadScene not called before render)\n");
                return;
            }
            launchPkg64SmsProbe(
                *impl->hostRenderer,
                impl->d_bvhNodes, impl->d_prims, impl->d_triangles,
                impl->d_spheres, impl->d_materials,
                impl->d_lights, impl->numLights);
            // Return early without rendering — the probe ran instead.
            return;
        }
    }

#ifdef ASTRORAY_WAVEFRONT_INTERSECT
    // pkg55-A.1 dual-trace parity hook. Only fires when the env var is
    // set; even then, the AoS megakernel runs unchanged because we
    // restore d_rngStates from a snapshot before launchPathTraceKernel().
    //
    // Reference pattern: Cycles' debug-cuda-kernel-paranoia mode
    // (intern/cycles/device/cuda/queue.cpp) — runs a reference trace
    // alongside the production launch and traps on mismatch.
    {
        const char* parity_env = std::getenv("ASTRORAY_WAVEFRONT_INTERSECT_PARITY");
        bool parity_on = parity_env && parity_env[0] && std::strcmp(parity_env, "0") != 0;
        if (parity_on) {
            astroray::gpu_profile::NvtxRange _nvtx_w("wavefront_intersect_parity_dual_trace");
            using astroray::wavefront::IntegratorStateSoA;
            using astroray::wavefront::allocateSoAState;
            using astroray::wavefront::freeSoAState;
            using astroray::wavefront::launchStageInit;
            using astroray::wavefront::launchStageIntersect;
            using astroray::wavefront::launchIntersectParity;

            IntegratorStateSoA soa;
            if (!allocateSoAState(soa, totalPixels)) {
                throw std::runtime_error(
                    "[pkg55-A.1] allocateSoAState failed (totalPixels=" +
                    std::to_string(totalPixels) + ")");
            }

            // Snapshot freshly-init RNG so parity verifier can re-run the
            // same primary-ray sequence, and so we can restore d_rngStates
            // before the megakernel launches (preserving AoS parity).
            curandState* rng_snapshot = nullptr;
            CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&rng_snapshot),
                                  totalPixels * sizeof(curandState)));
            CUDA_CHECK(cudaMemcpy(rng_snapshot, impl->d_rngStates,
                                  totalPixels * sizeof(curandState),
                                  cudaMemcpyDeviceToDevice));
            // SoA path uses a private rng buffer (not d_rngStates) so the
            // megakernel's RNG state is unaffected by the dual-trace.
            CUDA_CHECK(cudaMemcpy(soa.rng_state, rng_snapshot,
                                  totalPixels * sizeof(curandState),
                                  cudaMemcpyDeviceToDevice));

            launchStageInit(soa, impl->camera, width, height);
            launchStageIntersect(soa,
                impl->d_bvhNodes, impl->d_prims,
                impl->d_triangles, impl->d_spheres);
            int mismatches = launchIntersectParity(
                soa, rng_snapshot, impl->camera, width, height,
                impl->d_bvhNodes, impl->d_prims,
                impl->d_triangles, impl->d_spheres);
            std::fprintf(stderr,
                "[pkg55-A.1] wavefront intersect parity: %d / %d rays mismatched\n",
                mismatches, totalPixels);
            if (mismatches != 0) {
                cudaFree(rng_snapshot);
                freeSoAState(soa);
                cudaGetLastError();  // pkg85-B: swallow cleanup errors before throw
                throw std::runtime_error(
                    "[pkg55-A.1] wavefront intersect parity check found mismatches");
            }
            CUDA_CHECK(cudaFree(rng_snapshot));
            freeSoAState(soa);
            // d_rngStates was never advanced (SoA path used its own buffer);
            // megakernel below sees exactly the post-launchInitRNG state,
            // i.e. bit-identical to the no-parity build.
        }
    }
#endif  // ASTRORAY_WAVEFRONT_INTERSECT

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

void CUDARenderer::renderMultiwavelength(
    std::vector<Vec3>& pixels, int width, int height,
    int seed, int samplesPerPixel, int maxDepth,
    float lambdaMin, float lambdaMax, bool useLuminanceOutput,
    bool enableNEE)
{
    if (!impl->available) throw std::runtime_error("No CUDA GPU available");
    // pkg85-C: see CUDARenderer::render() — world-only renders are valid.
    if (!impl->d_bvhNodes && !impl->envMap.loaded)
        throw std::runtime_error("Scene not uploaded — call uploadScene() first");

    astroray::gpu_profile::NvtxRange _nvtx_mw("CUDARenderer::renderMultiwavelength");
    impl->ensureFramebuffer(width, height);
    int totalPixels = width * height;

    // pkg54b: ensure CMF tables are present in MW kernel constant memory.
    uploadCmfTables();
    // pkg54c: ensure the Jakob-Hanika sRGB sigmoid LUT is in device global
    // memory before any gpu_jhEvalSpectrum call.
    uploadJakobHanikaLut();

    unsigned long long rngSeed = (seed == 0)
        ? (unsigned long long)time(nullptr)
        : (unsigned long long)seed;
    launchInitRNG(impl->d_rngStates, totalPixels, rngSeed);

    launchMultiwavelengthKernel(
        impl->d_framebuffer, width, height, samplesPerPixel, maxDepth,
        lambdaMin, lambdaMax, useLuminanceOutput, enableNEE,
        impl->d_bvhNodes, impl->d_prims, impl->d_triangles, impl->d_spheres,
        impl->d_materials,
        impl->d_lights, impl->numLights, impl->totalLightPower,
        impl->envMap,
        impl->camera,
        impl->backgroundColor, impl->hasBackgroundColor,
        impl->d_rngStates);

    std::vector<float> hostFb(totalPixels * 3);
    CUDA_CHECK(cudaMemcpy(hostFb.data(), impl->d_framebuffer,
                          totalPixels * 3 * sizeof(float),
                          cudaMemcpyDeviceToHost));

    pixels.resize(totalPixels);
    for (int i = 0; i < totalPixels; ++i)
        pixels[i] = Vec3(hostFb[i*3], hostFb[i*3+1], hostFb[i*3+2]);

    printf("[CUDA] MW render complete: %dx%d, %d spp, [%.0f, %.0f] nm, %s\n",
           width, height, samplesPerPixel, lambdaMin, lambdaMax,
           useLuminanceOutput ? "luminance" : "visible");
}

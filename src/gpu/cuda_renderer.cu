// cuda_renderer.cu — CUDARenderer implementation.
// This file is the single point where all CUDA runtime calls live.
// It exposes the pure-C++ CUDARenderer interface from gpu_renderer.h.

#include "astroray/gpu_renderer.h"
#include "astroray/gpu_scene_upload.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_photon_store.h"     // pkg113 Phase 3: GPhotonGrid
#include "astroray/gpu_photon_caustic.h"   // pkg113 Phase 3: scene-driven pre-pass
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
#include <chrono>  // pkg86-B: light-tree upload timing
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
    bool useCaustics,  // pkg64-gpu Phase 2
    const GTLASNode*  d_tlas, const GInstance* d_instances, const GBLAS* d_blas,  // pkg114
    const GBVHNode*  d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials,
    const GLight*     d_lights, int numLights, float totalLightPower,
    GLightTreeView lightTree,  // pkg86-B
    const astroray::manifold::device::GSMSCaster* d_smsCasters, int numSMSCasters,  // pkg64-gpu Phase 2
    GEnvMap envMap,
    GCameraParams cam,
    float filmExposure,
    GVec3 backgroundColor, bool hasBackgroundColor,
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid,  // pkg113 Phase 3
    float photonScale,                                                   // pkg113 Phase 3
    const GVec3* d_motionVertices,  // pkg88-C.0
    curandState* d_rngStates,
    float* d_cryptoObjectBuffer = nullptr,      // pkg87b
    float* d_cryptoMaterialBuffer = nullptr,    // pkg87b
    int cryptoDepth = 6,                         // pkg87b
    bool cryptomatteEnabled = false);            // pkg87b

// pkg86-B — batch light-tree pick probe (defined in path_trace_kernel.cu).
void launchLightTreePick(
    GLightTreeView view, const float* d_pts, const float* d_nrms,
    const float* d_us, int n, int* d_outIdx, float* d_outPdf);

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
    bool useCaustics,  // pkg64-gpu Phase 2
    const GTLASNode*  d_tlas, const GInstance* d_instances, const GBLAS* d_blas,  // pkg114
    const GBVHNode*  d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials,
    const GLight*     d_lights, int numLights, float totalLightPower,
    GLightTreeView lightTree,  // pkg86-B
    const astroray::manifold::device::GSMSCaster* d_smsCasters, int numSMSCasters,  // pkg64-gpu Phase 2
    GEnvMap envMap,
    GCameraParams cam,
    GVec3 backgroundColor, bool hasBackgroundColor,
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid,  // pkg113 Phase 3
    float photonScale,                                                   // pkg113 Phase 3
    const GVec3* d_motionVertices,  // pkg88-C.0
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
    // pkg114 — two-level BVH device arrays. Non-null only for instanced scenes;
    // when null, the megakernels' gpu_tlas_hit falls back to gpu_bvh_hit.
    GTLASNode*  d_tlas       = nullptr;
    GInstance*  d_instances  = nullptr;
    GBLAS*      d_blas       = nullptr;
    GPrimitive* d_prims      = nullptr;
    GTriangle*  d_triangles  = nullptr;
    GSphere*    d_spheres    = nullptr;
    GMaterial*  d_materials  = nullptr;
    GLight*     d_lights     = nullptr;
    GVec3*      d_motionVertices = nullptr;  // pkg88-C.0 deformation motion buffer
    int         numLights    = 0;
    float       totalLightPower = 0.f;

    // pkg86-B: light tree device arrays (populated only in Tree sampler mode)
    GLightTreeNode*    d_lightTreeNodes    = nullptr;
    GLightTreeEmitter* d_lightTreeEmitters = nullptr;
    int*               d_lightToEmitter    = nullptr;
    int                numLightTreeNodes   = 0;
    float              lightTreeUploadMs   = 0.f;

    GLightTreeView lightTreeView() const {
        return GLightTreeView{d_lightTreeNodes, d_lightTreeEmitters,
                              d_lightToEmitter, numLightTreeNodes,
                              numLightTreeNodes > 0 ? 1 : 0};
    }

    // pkg64-gpu Phase 2: caustic-caster array (flagged transmissive spheres)
    astroray::manifold::device::GSMSCaster* d_smsCasters = nullptr;
    int         numSMSCasters = 0;

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

    // pkg87b: Cryptomatte device buffers + state
    float*       d_cryptoObjectBuffer = nullptr;
    float*       d_cryptoMaterialBuffer = nullptr;
    bool         cryptomatteEnabled = false;
    int          cryptoDepth = 6;

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
        if (d_tlas)       { cudaFree(d_tlas);        d_tlas       = nullptr; }  // pkg114
        if (d_instances)  { cudaFree(d_instances);   d_instances  = nullptr; }  // pkg114
        if (d_blas)       { cudaFree(d_blas);        d_blas       = nullptr; }  // pkg114
        if (d_prims)      { cudaFree(d_prims);       d_prims      = nullptr; }
        if (d_triangles)  { cudaFree(d_triangles);   d_triangles  = nullptr; }
        if (d_spheres)    { cudaFree(d_spheres);     d_spheres    = nullptr; }
        if (d_materials)  { cudaFree(d_materials);   d_materials  = nullptr; }
        if (d_lights)     { cudaFree(d_lights);      d_lights     = nullptr; }
        if (d_motionVertices) { cudaFree(d_motionVertices); d_motionVertices = nullptr; }  // pkg88-C.0
        if (d_lightTreeNodes)    { cudaFree(d_lightTreeNodes);    d_lightTreeNodes    = nullptr; }  // pkg86-B
        if (d_lightTreeEmitters) { cudaFree(d_lightTreeEmitters); d_lightTreeEmitters = nullptr; }  // pkg86-B
        if (d_lightToEmitter)    { cudaFree(d_lightToEmitter);    d_lightToEmitter    = nullptr; }  // pkg86-B
        numLightTreeNodes = 0;
        if (d_smsCasters) { cudaFree(d_smsCasters);  d_smsCasters = nullptr; }  // pkg64-gpu Phase 2
        freeEnv();
        if (d_framebuffer){ cudaFree(d_framebuffer); d_framebuffer= nullptr; }
        if (d_rngStates)  { cudaFree(d_rngStates);  d_rngStates  = nullptr; }
        if (d_cryptoObjectBuffer){ cudaFree(d_cryptoObjectBuffer); d_cryptoObjectBuffer= nullptr; }  // pkg87b
        if (d_cryptoMaterialBuffer){ cudaFree(d_cryptoMaterialBuffer); d_cryptoMaterialBuffer= nullptr; }  // pkg87b
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

    void ensureFramebuffer(int w, int h, int cryptoDepth = 0, bool needCrypto = false) {
        bool resize = (w != fbWidth || h != fbHeight);
        if (!resize && d_framebuffer && (!needCrypto || d_cryptoObjectBuffer)) return;
        if (d_framebuffer) { cudaFree(d_framebuffer); d_framebuffer = nullptr; }
        if (d_rngStates)   { cudaFree(d_rngStates);   d_rngStates   = nullptr; }
        if (d_cryptoObjectBuffer) { cudaFree(d_cryptoObjectBuffer); d_cryptoObjectBuffer = nullptr; }  // pkg87b
        if (d_cryptoMaterialBuffer) { cudaFree(d_cryptoMaterialBuffer); d_cryptoMaterialBuffer = nullptr; }  // pkg87b
        // pkg85-B: free errors above must not contaminate the cudaMalloc below.
        cudaGetLastError();
        fbWidth = w; fbHeight = h;
        int n = w * h;
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_framebuffer), n * 3 * sizeof(float)));
        CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_rngStates),   n * sizeof(curandState)));
        // pkg87b: allocate crypto buffers when needed
        if (needCrypto && cryptoDepth > 0) {
            size_t cryptoSize = n * cryptoDepth * 2 * sizeof(float);
            CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_cryptoObjectBuffer), cryptoSize));
            CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_cryptoMaterialBuffer), cryptoSize));
            CUDA_CHECK(cudaMemset(d_cryptoObjectBuffer, 0, cryptoSize));
            CUDA_CHECK(cudaMemset(d_cryptoMaterialBuffer, 0, cryptoSize));
        }
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

// pkg87b
void CUDARenderer::setCryptomatteEnabled(bool enabled) { impl->cryptomatteEnabled = enabled; }
bool CUDARenderer::getCryptomatteEnabled() const { return impl->cryptomatteEnabled; }
void CUDARenderer::copyCryptoBuffersToHost(std::vector<float>& objectBuffer,
                                             std::vector<float>& materialBuffer,
                                             int width, int height, int depth) {
    if (!impl->d_cryptoObjectBuffer || !impl->d_cryptoMaterialBuffer) {
        objectBuffer.clear();
        materialBuffer.clear();
        return;
    }
    size_t size = width * height * depth * 2;
    objectBuffer.resize(size);
    materialBuffer.resize(size);
    CUDA_CHECK(cudaMemcpy(objectBuffer.data(), impl->d_cryptoObjectBuffer,
                          size * sizeof(float), cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(materialBuffer.data(), impl->d_cryptoMaterialBuffer,
                          size * sizeof(float), cudaMemcpyDeviceToHost));
}

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
    devUpload(r.tlas,      &impl->d_tlas);        // pkg114 (empty unless instanced)
    devUpload(r.instances, &impl->d_instances);   // pkg114
    devUpload(r.blas,      &impl->d_blas);         // pkg114
    devUpload(r.prims,     &impl->d_prims);
    devUpload(r.triangles, &impl->d_triangles);
    devUpload(r.spheres,   &impl->d_spheres);
    devUpload(r.motionVertices, &impl->d_motionVertices);  // pkg88-C.0

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

    uploadLightTree(r);  // pkg86-B: tree arrays track the light buffer

    printf("[CUDA] Lights uploaded: %d lights, total power %g\n",
           impl->numLights, impl->totalLightPower);
}

// pkg86-B: upload (or clear) the flattened light tree. Timed because the
// spec gates one-time upload cost at <= 10 ms on a 10k-light scene.
void CUDARenderer::uploadLightTree(const SceneUploadResult& r) {
    auto t0 = std::chrono::steady_clock::now();
    devUpload(r.lightTreeNodes,    &impl->d_lightTreeNodes);
    devUpload(r.lightTreeEmitters, &impl->d_lightTreeEmitters);
    devUpload(r.lightToEmitter,    &impl->d_lightToEmitter);
    impl->numLightTreeNodes = (int)r.lightTreeNodes.size();
    impl->lightTreeUploadMs = std::chrono::duration<float, std::milli>(
        std::chrono::steady_clock::now() - t0).count();
    if (impl->numLightTreeNodes > 0) {
        printf("[CUDA] Light tree uploaded: %d nodes, %d emitters, %.2f ms\n",
               impl->numLightTreeNodes, (int)r.lightTreeEmitters.size(),
               impl->lightTreeUploadMs);
    }
}

float CUDARenderer::lightTreeUploadMs() const { return impl->lightTreeUploadMs; }

// pkg86-B: run gpu_light_tree_pick on a batch of (point, normal, u) queries.
// Mirrors the exact device function the NEE path uses, so the parity gate
// measures the production traversal, not a test-only re-implementation.
bool CUDARenderer::debugLightTreePick(const std::vector<Vec3>& points,
                                      const std::vector<Vec3>& normals,
                                      const std::vector<float>& us,
                                      std::vector<int>& outLightIndex,
                                      std::vector<float>& outPdf)
{
    int n = (int)us.size();
    outLightIndex.assign(n, -1);
    outPdf.assign(n, 0.f);
    if (!impl->available || impl->numLightTreeNodes == 0) return false;
    if (n == 0) return true;

    std::vector<float> pts(n * 3), nrms(n * 3);
    for (int i = 0; i < n; ++i) {
        pts[i*3+0] = points[i].x;  pts[i*3+1] = points[i].y;  pts[i*3+2] = points[i].z;
        nrms[i*3+0] = normals[i].x; nrms[i*3+1] = normals[i].y; nrms[i*3+2] = normals[i].z;
    }

    float *d_pts = nullptr, *d_nrms = nullptr, *d_us = nullptr, *d_pdf = nullptr;
    int *d_idx = nullptr;
    CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_pts),  n * 3 * sizeof(float)));
    CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_nrms), n * 3 * sizeof(float)));
    CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_us),   n * sizeof(float)));
    CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_idx),  n * sizeof(int)));
    CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d_pdf),  n * sizeof(float)));
    CUDA_CHECK(cudaMemcpy(d_pts,  pts.data(),  n * 3 * sizeof(float), cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_nrms, nrms.data(), n * 3 * sizeof(float), cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_us,   us.data(),   n * sizeof(float),     cudaMemcpyHostToDevice));

    launchLightTreePick(impl->lightTreeView(), d_pts, d_nrms, d_us, n, d_idx, d_pdf);

    CUDA_CHECK(cudaMemcpy(outLightIndex.data(), d_idx, n * sizeof(int),   cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaMemcpy(outPdf.data(),        d_pdf, n * sizeof(float), cudaMemcpyDeviceToHost));

    cudaFree(d_pts); cudaFree(d_nrms); cudaFree(d_us);
    cudaFree(d_idx); cudaFree(d_pdf);
    cudaGetLastError();  // pkg85-B: swallow cleanup errors
    return true;
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
    devUpload(r.tlas,      &impl->d_tlas);        // pkg114 (empty unless instanced)
    devUpload(r.instances, &impl->d_instances);   // pkg114
    devUpload(r.blas,      &impl->d_blas);         // pkg114
    devUpload(r.prims,     &impl->d_prims);
    devUpload(r.triangles, &impl->d_triangles);
    devUpload(r.spheres,   &impl->d_spheres);
    devUpload(r.materials, &impl->d_materials);
    devUpload(r.lights,    &impl->d_lights);
    devUpload(r.smsCasters, &impl->d_smsCasters);  // pkg64-gpu Phase 2
    devUpload(r.motionVertices, &impl->d_motionVertices);  // pkg88-C.0
    uploadLightTree(r);  // pkg86-B

    impl->numLights       = (int)r.lights.size();
    impl->totalLightPower = r.totalLightPower;
    impl->numSMSCasters   = (int)r.smsCasters.size();  // pkg64-gpu Phase 2
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

// pkg113 Phase 3 — build the forward-photon aperture aim from the CPU Renderer,
// mirroring the host setup in spectral_path_tracer.cpp::buildPhotonMap (l.346-368):
// union AABB of flagged caustic casters → centroid + radius; collimated sun
// direction → an aperture disc upstream of the casters. Returns aim.valid=false
// when there are no casters or no lights (the pre-pass is then skipped).
static astroray::photon::gpu::PhotonCausticAim buildCausticAim(
    const Renderer& scene, int maxDepth) {
    astroray::photon::gpu::PhotonCausticAim aim{};
    aim.valid = false;
    aim.lambdaMin = 380.0f;
    aim.lambdaMax = 720.0f;
    aim.maxDepth  = maxDepth;
    aim.boost     = 1.2f;   // CPU caustic_boost default (spectral_path_tracer.cpp:499)
    aim.photonCount = 4000000;  // forward photons (≈2000² lattice); CPU traces 3e6

    // Union AABB of all flagged caustic-caster objects.
    AABB casterBounds; bool any = false;
    for (const auto& obj : scene.getScene()) {
        if (!obj || !obj->isCausticCaster()) continue;
        AABB ob;
        if (!obj->boundingBox(ob)) continue;
        casterBounds = any ? casterBounds.merge(ob) : ob;
        any = true;
    }
    if (!any) return aim;

    const Vec3 casterC = casterBounds.centroid();
    const float crad = (casterBounds.max - casterBounds.min).length() * 0.55f + 1e-3f;

    const auto& lights = scene.getLights();
    if (lights.empty()) return aim;

    // Probe one light sample toward the caster centroid to get the sun direction
    // (CPU :356-362). A fixed seed keeps the aim deterministic frame-to-frame.
    std::mt19937 gen(12345u);
    astroray::SampledWavelengths probe = astroray::SampledWavelengths::sampleUniform(0.5f);
    LightSample ls;
    lights.sample(ls, casterC, Vec3(0, 1, 0), probe, gen);
    Vec3 sunDir = (casterC - ls.position).normalized();
    if (sunDir.length2() < 1e-6f) return aim;

    Vec3 origin0 = casterC - sunDir * (crad + 2.0f);
    aim.sunDir         = GVec3(sunDir.x, sunDir.y, sunDir.z);
    aim.apertureOrigin = GVec3(origin0.x, origin0.y, origin0.z);
    aim.apertureRadius = crad;
    aim.valid = true;
    return aim;
}

void CUDARenderer::render(
    std::vector<Vec3>& pixels, int width, int height,
    int seed, int samplesPerPixel, int maxDepth,
    bool use_refractive_caustics,
    bool use_reflective_caustics)
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
    impl->ensureFramebuffer(width, height, impl->cryptoDepth, impl->cryptomatteEnabled);  // pkg87b
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

    // pkg64-gpu Phase 3: enable caustics only if casters exist and flags are set.
    // SMS requires BOTH refractive AND reflective flags to be true (matching
    // the CPU integrator convention — per-vertex SMS attempt checks both).
    bool useCaustics = use_refractive_caustics && use_reflective_caustics;

    // pkg113 Phase 3: scene-driven photon-map caustic pre-pass. When refractive
    // caustics are on and the uploaded scene has flagged caster glass, forward-
    // trace photons through it, build a resident hash grid, and hand the grid +
    // calibrated brightness scale to the megakernel (it gathers at receiver hits).
    // Mirrors the CPU pkg111 beginFrame pre-pass + sampleFull gather. Gated on the OPT-IN
    // usePhotonCaustics flag (pkg113 Phase-3): the photon map is the canonical GPU caustic
    // path (parity doc Decisions §1), but during the SMS->photon-map transition it is opt-in
    // so legacy SMS-GPU scenes (use_refractive_caustics alone) keep the SMS path unchanged
    // (otherwise the pre-pass disables SMS and regresses the pkg64-gpu receiver-energy gate).
    astroray::photon::gpu::GPhotonCausticResult caustic{};
    caustic.ready = false;
    if (use_refractive_caustics && impl->hostRenderer &&
        impl->hostRenderer->getUsePhotonCaustics()) {
        astroray::photon::gpu::PhotonCausticAim aim =
            buildCausticAim(*impl->hostRenderer, maxDepth);
        if (aim.valid) {
            astroray::gpu_profile::NvtxRange _nvtx_pm("pkg113 photon caustic pre-pass");
            caustic = astroray::photon::gpu::cuda_photon_caustic_build(
                impl->d_bvhNodes, impl->d_prims, impl->d_triangles,
                impl->d_spheres, impl->d_materials, aim);
            if (caustic.ready) {
                printf("[CUDA] pkg113 photon caustic: %d photons, scale %g\n",
                       caustic.numPhotons, caustic.scale);
            }
        }
    }
    // pkg113 / parity doc Decisions §1: the photon map is the canonical GPU
    // caustic path; SMS-GPU is legacy. When the photon caustic grid is active,
    // disable the legacy SMS attempt so the caustic is not double-counted.
    if (caustic.ready) useCaustics = false;

    // Launch megakernel
    launchPathTraceKernel(
        impl->d_framebuffer, width, height, samplesPerPixel, maxDepth, useCaustics,
        impl->d_tlas, impl->d_instances, impl->d_blas,  // pkg114
        impl->d_bvhNodes, impl->d_prims, impl->d_triangles, impl->d_spheres,
        impl->d_materials,
        impl->d_lights, impl->numLights, impl->totalLightPower,
        impl->lightTreeView(),  // pkg86-B
        impl->d_smsCasters, impl->numSMSCasters,
        impl->envMap,
        impl->camera,
        impl->filmExposure,
        impl->backgroundColor, impl->hasBackgroundColor,
        caustic.grid, caustic.ready, caustic.scale,  // pkg113 Phase 3
        impl->d_motionVertices,  // pkg88-C.0
        impl->d_rngStates,
        impl->d_cryptoObjectBuffer, impl->d_cryptoMaterialBuffer,  // pkg87b
        impl->cryptoDepth, impl->cryptomatteEnabled);              // pkg87b

    // pkg113 Phase 3: release the resident photon grid after the render.
    astroray::photon::gpu::cuda_photon_caustic_free(caustic);

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
    bool enableNEE,
    bool use_refractive_caustics,
    bool use_reflective_caustics)
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

    // pkg64-gpu Phase 3: enable caustics only if casters exist and flags are set.
    // SMS requires BOTH refractive AND reflective flags to be true (matching
    // the CPU integrator convention — per-vertex SMS attempt checks both).
    bool useCaustics = use_refractive_caustics && use_reflective_caustics;

    // pkg113 Phase 3: scene-driven photon-map caustic pre-pass (see render()).
    // The spectral `path_tracer` routes here, so this is the canonical caustic
    // path for the dispersive acceptance scenes. Gated on the OPT-IN usePhotonCaustics
    // flag (transition-clean; legacy SMS scenes keep SMS — see render()).
    astroray::photon::gpu::GPhotonCausticResult caustic{};
    caustic.ready = false;
    if (use_refractive_caustics && impl->hostRenderer &&
        impl->hostRenderer->getUsePhotonCaustics()) {
        astroray::photon::gpu::PhotonCausticAim aim =
            buildCausticAim(*impl->hostRenderer, maxDepth);
        if (aim.valid) {
            astroray::gpu_profile::NvtxRange _nvtx_pm("pkg113 photon caustic pre-pass (MW)");
            caustic = astroray::photon::gpu::cuda_photon_caustic_build(
                impl->d_bvhNodes, impl->d_prims, impl->d_triangles,
                impl->d_spheres, impl->d_materials, aim);
            if (caustic.ready) {
                printf("[CUDA] pkg113 photon caustic (MW): %d photons, scale %g\n",
                       caustic.numPhotons, caustic.scale);
            }
        }
    }
    // pkg113 / parity doc Decisions §1: photon map supersedes the legacy SMS
    // attempt; disable SMS when the photon grid is active (no double-count).
    if (caustic.ready) useCaustics = false;

    launchMultiwavelengthKernel(
        impl->d_framebuffer, width, height, samplesPerPixel, maxDepth,
        lambdaMin, lambdaMax, useLuminanceOutput, enableNEE, useCaustics,
        impl->d_tlas, impl->d_instances, impl->d_blas,  // pkg114
        impl->d_bvhNodes, impl->d_prims, impl->d_triangles, impl->d_spheres,
        impl->d_materials,
        impl->d_lights, impl->numLights, impl->totalLightPower,
        impl->lightTreeView(),  // pkg86-B
        impl->d_smsCasters, impl->numSMSCasters,
        impl->envMap,
        impl->camera,
        impl->backgroundColor, impl->hasBackgroundColor,
        caustic.grid, caustic.ready, caustic.scale,  // pkg113 Phase 3
        impl->d_motionVertices,  // pkg88-C.0
        impl->d_rngStates);

    astroray::photon::gpu::cuda_photon_caustic_free(caustic);  // pkg113 Phase 3

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

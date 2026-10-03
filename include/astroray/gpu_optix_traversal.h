#pragma once
// gpu_optix_traversal.h — pkg299 host API for OptiX hardware traversal of the
// GPU wavefront intersect and shadow stages. Pure C++ (no OptiX / CUDA headers),
// so the wavefront driver, the pybind TU and non-OptiX builds all include it.
//
// Contract: OptiX only traverses. The closest-hit launch writes (t, primitive,
// barycentrics, instance) per path slot into HwHitBuffers; the CUDA intersect
// kernel <HwHits=true> rebuilds the GHitRecord with the software path's own
// code. The shadow launch writes a per-slot occlusion flag the CUDA shadow
// kernels <HwOcc=true> read instead of walking the BVH. Shading, queues, path
// state and GPUWavefrontHitBuffers are unchanged.
//
// Without ASTRORAY_OPTIX_TRAVERSAL (no OptiX SDK / CPU builds) every entry point
// is an inline no-op reporting "unavailable", so callers need no #ifdefs.

#include <cstdlib>
#include <cstring>
#include <string>

#include <vector>

struct GPrimitive;
struct GTriangle;
struct GInstance;
struct GBLAS;
class Renderer;

namespace astroray {
namespace optix_trav {

struct ClosestLaunch;
struct ShadowLaunch;

// Per-slot side buffers (device pointers, capacity = wavefront pool size).
struct HwHitBuffers {
    float* t        = nullptr;   // < 0 = miss
    int*   prim     = nullptr;
    float* u        = nullptr;
    float* v        = nullptr;
    int*   inst     = nullptr;   // instance index, -1 when the root is a GAS
    int*   occluded = nullptr;   // shadow launch output
};

enum class Request { Default, Software, Optix };

// ASTRORAY_GPU_TRAVERSAL = "software" | "optix" (read on every call). Unset /
// "optix": OptiX on triangle-only scenes; "software": the software BVH.
inline Request requested() {
    const char* e = std::getenv("ASTRORAY_GPU_TRAVERSAL");
    if (e == nullptr) return Request::Default;
    if (std::strcmp(e, "software") == 0) return Request::Software;
    if (std::strcmp(e, "optix") == 0) return Request::Optix;
    return Request::Default;
}

#ifdef ASTRORAY_OPTIX_TRAVERSAL

// OptiX initialised on the current device and the device has RT cores.
bool available();
// Last initialisation / build error (empty when none).
std::string lastError();

// Build the device accel (GAS per BLAS + IAS when instanced, else one GAS over
// all prims). Caller guarantees the scene is all triangles with no motion.
// Returns false (software fallback) on any failure.
bool buildAccel(const GPrimitive* d_prims, int numPrims, const GTriangle* d_tris,
                const GInstance* h_instances, int numInstances,
                const GBLAS* h_blas, int numBlas);
bool accelReady();
void releaseAccel();
// pkg291 (#875): in-place object moves. buildAccelUpdatable builds the single-
// level GAS with OPTIX_BUILD_FLAG_ALLOW_UPDATE (uncompacted, keeping its vertex
// stream + update scratch); refitAccel re-packs the vertices from d_tris and runs
// OPTIX_BUILD_OPERATION_UPDATE (same topology). False = fall back (rebuild).
bool buildAccelUpdatable(const GPrimitive* d_prims, int numPrims, const GTriangle* d_tris);
bool refitAccel(const GPrimitive* d_prims, int numPrims, const GTriangle* d_tris);
bool accelUpdatable();

// Grow-only side buffers for `capacity` path slots.
HwHitBuffers ensureBuffers(int capacity);

// Launch `width` raygen threads (threads past *count return). Throw on error.
void traceClosest(const ClosestLaunch& p, int width);
void traceShadow(const ShadowLaunch& p, int width);

// Fixed-ray A/B test hook (src/gpu/optix/optix_ray_ab.cu): the same n rays
// (origins/dirs = n*3 floats, tmax = n floats, shadow extent only) through the
// software BVH and through OptiX (+ gpu_hw_hit_record). Closest mode fills the
// sw*/hw*/d*/same* arrays; shadow mode fills swOccluded/hwOccluded.
struct RayAbResult {
    std::vector<int>   swHit, hwHit, swPrim, hwPrim, sameFace, sameMat;
    std::vector<float> swT, hwT, dPoint, dNormal;
    std::vector<int>   swOccluded, hwOccluded;
};
RayAbResult cuda_optix_ray_ab(const Renderer& cpu, const float* origins, const float* dirs,
                              const float* tmax, int n, bool shadow);

#else

inline bool available() { return false; }
inline std::string lastError() { return "built without ASTRORAY_OPTIX_TRAVERSAL"; }
inline bool buildAccel(const GPrimitive*, int, const GTriangle*, const GInstance*, int,
                       const GBLAS*, int) { return false; }
inline bool accelReady() { return false; }
inline void releaseAccel() {}
inline bool buildAccelUpdatable(const GPrimitive*, int, const GTriangle*) { return false; }
inline bool refitAccel(const GPrimitive*, int, const GTriangle*) { return false; }
inline bool accelUpdatable() { return false; }
inline HwHitBuffers ensureBuffers(int) { return HwHitBuffers{}; }
inline void traceClosest(const ClosestLaunch&, int) {}
inline void traceShadow(const ShadowLaunch&, int) {}

#endif

}  // namespace optix_trav
}  // namespace astroray

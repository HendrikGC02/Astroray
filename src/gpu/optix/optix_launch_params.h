#pragma once
// optix_launch_params.h — pkg299 launch parameters shared by the OptiX programs
// (optix_trace_programs.cu, compiled to OptiX-IR) and the host launcher
// (optix_pipeline.cpp). Plain C layout, no OptiX or engine types, so both the
// OptiX-IR compile and the MSVC host TU see the same struct.
//
// Pattern: NVIDIA OptiX SDK 9.1 sample optixRaycasting (BSD-3-Clause) — rays
// read from CUDA buffers by launch index, hits written back to CUDA buffers.

namespace astroray {
namespace optix_trav {

// Closest-hit launch over the wavefront intersect queue. Mirrors the ray setup
// of intersectPathSlotT (stage_advance_device.cuh): SoA ray, tMin 0.001, and the
// #873 camera clip planes on bounce-0 rays only.
struct ClosestLaunch {
    const int*   queue;      // queue_in
    const int*   count;      // *count_in (device-side population)
    const int*   alive;      // state.path_alive
    const int*   bounce;     // state.bounce
    const float* ox; const float* oy; const float* oz;
    const float* dx; const float* dy; const float* dz;
    // #873 primary clip (GWavefrontPrimaryClip copied field by field).
    int   clipActive, clipHasFar;
    float clipNear, clipFar;
    float fwdX, fwdY, fwdZ;
    // Outputs, indexed by slot idx. t < 0 = miss.
    float* outT;
    int*   outPrim;    // GAS primitive index (global prim id, or BLAS-local when instanced)
    float* outU;       // barycentric b1 (weight of v1)
    float* outV;       // barycentric b2 (weight of v2)
    int*   outInst;    // OptixInstance::instanceId (index into GInstance[]), -1 without IAS
};

// Any-hit occlusion launch over a parked-NEE shadow queue. Rays come from the
// float lanes f[lane * cap + idx]: origin lanes 0..2, direction lanes 3..5, and
// the occlusion extent tMax in lane `maxDistLane` (< 0 = 1e30 sentinel, the env
// NEE convention). tMin is 0.001 (gpu_nee_occlude).
struct ShadowLaunch {
    const int*   queue;
    const int*   count;
    const float* f;
    int          cap;
    int          maxDistLane;
    int*         outOccluded;   // indexed by slot idx: 1 occluded, 0 visible
};

struct LaunchParams {
    unsigned long long handle;  // OptixTraversableHandle (GAS or IAS root)
    int                hasIas;  // 1 when the root is an IAS
    ClosestLaunch      closest;
    ShadowLaunch       shadow;
};

}  // namespace optix_trav
}  // namespace astroray

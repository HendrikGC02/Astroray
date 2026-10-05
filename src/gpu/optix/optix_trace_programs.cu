// optix_trace_programs.cu — pkg299 OptiX programs for the wavefront intersect
// and shadow stages. Compiled to OptiX-IR as its own TU (CMakeLists.txt,
// never -rdc linked into stage_advance.cu), embedded in the engine and loaded by
// optix_pipeline.cpp. Traversal only: no shading here (pbrt-v4 pattern).
//
// References:
//   - NVIDIA OptiX SDK 9.1 sample optixRaycasting (BSD-3-Clause):
//     __raygen__from_buffer / __closesthit__buffer_hit / __miss__buffer_miss.
//   - pbrt-v4 src/pbrt/gpu/optix/optix.cu (Apache-2.0): raygen reads the
//     wavefront ray queue by launch index; the shadow miss marks "unoccluded".
//   - OptiX 9.1 Programming Guide, "Ray flags": TERMINATE_ON_FIRST_HIT for
//     shadow rays; DISABLE_CLOSESTHIT still runs the miss program.
//   - Barycentrics: optixGetTriangleBarycentrics() = (b1, b2) with
//     P = (1-b1-b2) v0 + b1 v1 + b2 v2, the same (u, v) as Moller-Trumbore in
//     gpu_triangle_hit (include/astroray/gpu_bvh.h).
//
// Empty unless ASTRORAY_OPTIX_TRAVERSAL is defined (the Linux cuda-syntax-check
// CI job compiles every src/**/*.cu without the OptiX SDK).

#ifdef ASTRORAY_OPTIX_TRAVERSAL

#include <optix.h>
#include "optix_launch_params.h"

using astroray::optix_trav::LaunchParams;

extern "C" {
__constant__ LaunchParams params;
}

// Ray types: 0 = closest hit (intersect stage), 1 = shadow (any hit).
// One hit group (SBT offset 0, stride 0); the miss index selects the ray type.

extern "C" __global__ void __raygen__closest()
{
    const unsigned int i = optixGetLaunchIndex().x;
    const auto& c = params.closest;
    if ((int)i >= *c.count) return;
    const int idx = c.queue[i];
    // Same dead-slot guard as stageIntersectQueuedKernel: its record is unused.
    if (c.alive[idx] == 0) return;

    const float3 o = make_float3(c.ox[idx], c.oy[idx], c.oz[idx]);
    const float3 d = make_float3(c.dx[idx], c.dy[idx], c.dz[idx]);
    // #873 camera clip, identical expression to intersectPathSlotT.
    float tNear = 0.001f, tFar = 1e30f;
    if (c.bounce[idx] == 0 && c.clipActive) {
        // #1033: after a transparent pass-through (passDist > 0) the near clip is not
        // re-applied; the far clip still bounds the continuation from the camera.
        const float pd = (c.passDist != nullptr) ? c.passDist[idx] : 0.f;
        const float zInv = 1.f / fmaxf(1e-6f, d.x * c.fwdX + d.y * c.fwdY + d.z * c.fwdZ);
        if (pd == 0.f) tNear = fmaxf(0.001f, c.clipNear * zInv);
        if (c.clipHasFar) tFar = c.clipFar * zInv - pd;
    }

    unsigned int p0 = __float_as_uint(-1.f), p1 = 0u, p2 = 0u, p3 = 0u, p4 = 0xffffffffu;
    if (tFar > tNear) {
        optixTrace(params.handle, o, d, tNear, tFar, 0.0f, OptixVisibilityMask(255),
                   OPTIX_RAY_FLAG_DISABLE_ANYHIT,
                   /*SBToffset*/ 0, /*SBTstride*/ 0, /*missSBTIndex*/ 0,
                   p0, p1, p2, p3, p4);
    }
    c.outT[idx]    = __uint_as_float(p0);
    c.outPrim[idx] = (int)p1;
    c.outU[idx]    = __uint_as_float(p2);
    c.outV[idx]    = __uint_as_float(p3);
    c.outInst[idx] = (int)p4;
}

extern "C" __global__ void __closesthit__closest()
{
    const float2 b = optixGetTriangleBarycentrics();
    optixSetPayload_0(__float_as_uint(optixGetRayTmax()));
    optixSetPayload_1(optixGetPrimitiveIndex());
    optixSetPayload_2(__float_as_uint(b.x));
    optixSetPayload_3(__float_as_uint(b.y));
    optixSetPayload_4(params.hasIas ? optixGetInstanceId() : 0xffffffffu);
}

extern "C" __global__ void __miss__closest()
{
    optixSetPayload_0(__float_as_uint(-1.f));
}

extern "C" __global__ void __raygen__shadow()
{
    const unsigned int i = optixGetLaunchIndex().x;
    const auto& s = params.shadow;
    if ((int)i >= *s.count) return;
    const int idx = s.queue[i];
    const int cap = s.cap;
    const float3 o = make_float3(s.f[0 * cap + idx], s.f[1 * cap + idx], s.f[2 * cap + idx]);
    const float3 d = make_float3(s.f[3 * cap + idx], s.f[4 * cap + idx], s.f[5 * cap + idx]);
    // gpu_nee_occlude: any hit in [0.001, maxDist] occludes. maxDist is an
    // occlusion extent (1e30 for env / distant rays), never a distance.
    const float tMax = (s.maxDistLane >= 0) ? s.f[s.maxDistLane * cap + idx] : 1e30f;

    unsigned int occluded = 0u;
    if (tMax > 0.001f) {
        occluded = 1u;   // cleared by the miss program
        optixTrace(params.handle, o, d, 0.001f, tMax, 0.0f, OptixVisibilityMask(255),
                   OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT | OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT |
                   OPTIX_RAY_FLAG_DISABLE_ANYHIT,
                   /*SBToffset*/ 0, /*SBTstride*/ 0, /*missSBTIndex*/ 1,
                   occluded);
    }
    s.outOccluded[idx] = (int)occluded;
}

extern "C" __global__ void __miss__shadow()
{
    optixSetPayload_0(0u);
}

#endif  // ASTRORAY_OPTIX_TRAVERSAL

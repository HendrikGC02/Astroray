// stage_shade_fleet.cuh - pkg300 Phase 1: the fleet shade kernel. For launches
// whose only active axis is HasPrincipled (no texture, photons, dispersion,
// light-pass AOVs, op-VM program or normal map), stageShadeBucketed runs this
// kernel instead of the generic variant: the shade body and every callee fully
// inlined (shade_force_inline.cuh) under __maxnreg__(128) at 256 threads,
// i.e. 2 blocks = 16 warps per SM against 8 for the 254-register generic kernel.
// Measured on the pkg298 Cornell pair (1024^2, 256 spp, min of 5): 2.65x simple,
// 2.32x heavy vs main; the generic kernel (__grid_constant__ only) gives 1.59x /
// 1.46x. Full inlining of all 128 variants doubled the build (1189 s vs ~460 s),
// so it is limited to these two variants, one TU each (stage_shade_fleet_p<P>.cu).
// Budget after Cycles kernel/device/cuda/config.h (GPU_KERNEL_MAX_REGISTERS via
// __launch_bounds__, Apache-2.0); the sweep is in
// .astroray_plan/docs/pkg300-shade-counter-attribution.md.
#pragma once
#include "stage_advance_device.cuh"

#define ASTRORAY_DEFINE_SHADE_FLEET(P) \
namespace astroray::wavefront { \
__global__ void __maxnreg__(128) stageShadeFleetKernel_##P( \
    __grid_constant__ const GPUWavefrontState state, \
    __grid_constant__ const GPUWavefrontHitBuffers hitBufs, \
    const int* shade_queues, const int* shade_counts, int capacity, \
    int* queue_out, int* count_out, \
    float* nee_f, int* nee_i, int* shadow_queue, int* shadow_count, \
    const GTLASNode* tlas, const GInstance* instances, const GBLAS* blas, \
    const GBVHNode* bvhNodes, const GPrimitive* prims, const GTriangle* tris, \
    const GSphere* spheres, const GVec3* motionVerts, const ::GMaterial* materials, \
    const ::GLight* lights, int numLights, float totalLightPower, \
    const GDedicatedLight* dedLights, int numDed, GLightTreeView lightTree, \
    int max_depth, bool useLuminanceOutput, bool enableNEE, \
    float clampDirect, float clampIndirect, \
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid, float photonScale, \
    float* cryptoObjectRanks, float* cryptoMaterialRanks, int cryptoDepth) \
{ \
    int i = blockIdx.x * blockDim.x + threadIdx.x; \
    int bucket = i / capacity; \
    int pos    = i - bucket * capacity; \
    if (bucket >= G_WF_NUM_MAT_TYPES) return; \
    if (pos >= shade_counts[bucket]) return; \
    int idx = shade_queues[bucket * capacity + pos]; \
    bool alive = shadePathSlotImpl<true, (P != 0)>( \
        idx, state, hitBufs, tlas, instances, blas, bvhNodes, prims, tris, spheres, \
        motionVerts, materials, lights, numLights, totalLightPower, dedLights, numDed, \
        lightTree, max_depth, nee_f, nee_i, shadow_queue, shadow_count, capacity, \
        useLuminanceOutput, enableNEE, clampDirect, clampIndirect, \
        photonGrid, hasPhotonGrid, photonScale, false, \
        cryptoObjectRanks, cryptoMaterialRanks, cryptoDepth); \
    if (alive) { int slot = atomicAdd(count_out, 1); queue_out[slot] = idx; } \
} \
const void* stageShadeFleet_##P(bool launch, int blocks, int threads, const StageShadeArgs& a) \
{ \
    if (launch) stageShadeFleetKernel_##P<<<blocks, threads>>>( \
        *a.state, *a.hitBufs, a.shade_queues, a.shade_counts, a.capacity, \
        a.queue_out, a.count_out, a.nee_f, a.nee_i, a.shadow_queue, a.shadow_count, \
        a.tlas, a.instances, a.blas, a.bvhNodes, a.prims, a.tris, a.spheres, \
        a.motionVerts, a.materials, a.lights, a.numLights, a.totalLightPower, \
        a.dedLights, a.numDed, a.lightTree, a.max_depth, \
        a.useLuminanceOutput, a.enableNEE, a.clampDirect, a.clampIndirect, \
        a.photonGrid, a.hasPhotonGrid, a.photonScale, \
        a.cryptoObjectRanks, a.cryptoMaterialRanks, a.cryptoDepth); \
    return (const void*)stageShadeFleetKernel_##P; \
} \
}

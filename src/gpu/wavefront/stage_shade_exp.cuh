// stage_shade_exp.cuh - pkg300 sweep-only: one fleet-axis (HasPrincipled=false)
// shade kernel, fully inlined under __maxnreg__(128). Each stage_shade_exp_*.cu
// TU instantiates it under different ptxas flags (CMakeLists.txt) so the per-TU
// compile time and the render time of each flag set can be compared.
// Selected by ASTRORAY_SHADE_EXP=<k> (stage_advance.cu); removed before merge.
#pragma once
#include "stage_advance_device.cuh"

#define ASTRORAY_DEFINE_SHADE_EXP(K) \
namespace astroray::wavefront { \
__global__ void __maxnreg__(128) stageShadeExpKernel_##K( \
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
    bool alive = shadePathSlotImpl<true, false>( \
        idx, state, hitBufs, tlas, instances, blas, bvhNodes, prims, tris, spheres, \
        motionVerts, materials, lights, numLights, totalLightPower, dedLights, numDed, \
        lightTree, max_depth, nee_f, nee_i, shadow_queue, shadow_count, capacity, \
        useLuminanceOutput, enableNEE, clampDirect, clampIndirect, \
        photonGrid, hasPhotonGrid, photonScale, false, \
        cryptoObjectRanks, cryptoMaterialRanks, cryptoDepth); \
    if (alive) { int slot = atomicAdd(count_out, 1); queue_out[slot] = idx; } \
} \
const void* stageShadeExp_##K(bool launch, int blocks, int threads, const StageShadeArgs& a) \
{ \
    if (launch) stageShadeExpKernel_##K<<<blocks, threads>>>( \
        *a.state, *a.hitBufs, a.shade_queues, a.shade_counts, a.capacity, \
        a.queue_out, a.count_out, a.nee_f, a.nee_i, a.shadow_queue, a.shadow_count, \
        a.tlas, a.instances, a.blas, a.bvhNodes, a.prims, a.tris, a.spheres, \
        a.motionVerts, a.materials, a.lights, a.numLights, a.totalLightPower, \
        a.dedLights, a.numDed, a.lightTree, a.max_depth, \
        a.useLuminanceOutput, a.enableNEE, a.clampDirect, a.clampIndirect, \
        a.photonGrid, a.hasPhotonGrid, a.photonScale, \
        a.cryptoObjectRanks, a.cryptoMaterialRanks, a.cryptoDepth); \
    return (const void*)stageShadeExpKernel_##K; \
} \
}

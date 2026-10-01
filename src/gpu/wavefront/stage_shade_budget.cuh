// stage_shade_budget.cuh - pkg300 Phase 1: shared parameter list, body and launch
// macros of the register-budget sweep kernels (stage_shade_budget*.cu).
#pragma once
#include "stage_advance_device.cuh"

#define ASTRORAY_PKG300_SHADE_PARAMS \
    GPUWavefrontState state, GPUWavefrontHitBuffers hitBufs, \
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
    float* cryptoObjectRanks, float* cryptoMaterialRanks, int cryptoDepth

// Same body as stageShadeBucketedKernel; SLOTFN picks inlined vs out-of-line.
#define ASTRORAY_PKG300_SHADE_BODY(SLOTFN, P) \
    int i = blockIdx.x * blockDim.x + threadIdx.x; \
    int bucket = i / capacity; \
    int pos    = i - bucket * capacity; \
    if (bucket >= G_WF_NUM_MAT_TYPES) return; \
    if (pos >= shade_counts[bucket]) return; \
    int idx = shade_queues[bucket * capacity + pos]; \
    bool alive = SLOTFN<true, P, false, false, false, false, false, false>( \
        idx, state, hitBufs, tlas, instances, blas, bvhNodes, prims, tris, spheres, \
        motionVerts, materials, lights, numLights, totalLightPower, dedLights, numDed, \
        lightTree, max_depth, nee_f, nee_i, shadow_queue, shadow_count, capacity, \
        useLuminanceOutput, enableNEE, clampDirect, clampIndirect, \
        photonGrid, hasPhotonGrid, photonScale, false, \
        cryptoObjectRanks, cryptoMaterialRanks, cryptoDepth); \
    if (alive) { int slot = atomicAdd(count_out, 1); queue_out[slot] = idx; }

#define ASTRORAY_PKG300_LAUNCH(K) \
    K<<<blocks, threads>>>( \
        *a.state, *a.hitBufs, a.shade_queues, a.shade_counts, a.capacity, \
        a.queue_out, a.count_out, a.nee_f, a.nee_i, a.shadow_queue, a.shadow_count, \
        a.tlas, a.instances, a.blas, a.bvhNodes, a.prims, a.tris, a.spheres, \
        a.motionVerts, a.materials, a.lights, a.numLights, a.totalLightPower, \
        a.dedLights, a.numDed, a.lightTree, a.max_depth, \
        a.useLuminanceOutput, a.enableNEE, a.clampDirect, a.clampIndirect, \
        a.photonGrid, a.hasPhotonGrid, a.photonScale, \
        a.cryptoObjectRanks, a.cryptoMaterialRanks, a.cryptoDepth)


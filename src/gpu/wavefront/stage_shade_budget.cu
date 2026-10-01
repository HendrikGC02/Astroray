// stage_shade_budget.cu - pkg300 Phase 1 register-budget sweep kernels.
//
// The generic stageShadeBucketedKernel calls shadePathSlot out of line (it is
// not inlined under -rdc), so a __launch_bounds__/__maxnreg__ on the kernel only
// bounds the ~40-register kernel shell, never the shade body. That is why pkg174
// saw __launch_bounds__(256,2) "ignored". These kernels inline the body
// (shadePathSlotImpl is __forceinline__) so the budget covers it. Only the fleet
// axis combination (Texture/Photons/Dispersion/LightPassAOVs/Program/
// NormalPerturb all false) is instantiated, for HasPrincipled false and true.
// Budgets follow the Cycles kernel/device/cuda/config.h pattern
// (GPU_KERNEL_MAX_REGISTERS 168 at 384 threads; Apache-2.0) and the 128 point
// of the spec's sweep. Selected at runtime by ASTRORAY_SHADE_BUDGET (sweep only).
#include "stage_advance_device.cuh"

namespace astroray::wavefront {

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

template<bool P> __global__ void stageShadeInlKernel(ASTRORAY_PKG300_SHADE_PARAMS)
{ ASTRORAY_PKG300_SHADE_BODY(shadePathSlotImpl, P) }
template<bool P> __global__ void __maxnreg__(168) stageShadeInl168Kernel(ASTRORAY_PKG300_SHADE_PARAMS)
{ ASTRORAY_PKG300_SHADE_BODY(shadePathSlotImpl, P) }
template<bool P> __global__ void __maxnreg__(128) stageShadeInl128Kernel(ASTRORAY_PKG300_SHADE_PARAMS)
{ ASTRORAY_PKG300_SHADE_BODY(shadePathSlotImpl, P) }
// Control: out-of-line body + __maxnreg__(128) - reproduces the pkg174 "ignored" result
// if the linked REG stays at the callee's count.
__global__ void __maxnreg__(128) stageShadeCall128Kernel(ASTRORAY_PKG300_SHADE_PARAMS)
{ ASTRORAY_PKG300_SHADE_BODY(shadePathSlot, false) }

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

// mode: 1 = inline/no budget, 2 = inline/168, 3 = inline/128, 4 = call/128 (P=false only).
// Returns the kernel pointer (for the profiler) or nullptr when the combination
// has no budget kernel; launch == true also launches it.
const void* stageShadeBudget(int mode, bool P, bool launch,
                             int blocks, int threads, const StageShadeArgs& a)
{
    switch (mode) {
    case 1:
        if (P) { if (launch) ASTRORAY_PKG300_LAUNCH(stageShadeInlKernel<true>);  return (const void*)stageShadeInlKernel<true>; }
        else   { if (launch) ASTRORAY_PKG300_LAUNCH(stageShadeInlKernel<false>); return (const void*)stageShadeInlKernel<false>; }
    case 2:
        if (P) { if (launch) ASTRORAY_PKG300_LAUNCH(stageShadeInl168Kernel<true>);  return (const void*)stageShadeInl168Kernel<true>; }
        else   { if (launch) ASTRORAY_PKG300_LAUNCH(stageShadeInl168Kernel<false>); return (const void*)stageShadeInl168Kernel<false>; }
    case 3:
        if (P) { if (launch) ASTRORAY_PKG300_LAUNCH(stageShadeInl128Kernel<true>);  return (const void*)stageShadeInl128Kernel<true>; }
        else   { if (launch) ASTRORAY_PKG300_LAUNCH(stageShadeInl128Kernel<false>); return (const void*)stageShadeInl128Kernel<false>; }
    case 4:
        if (P) return nullptr;
        if (launch) ASTRORAY_PKG300_LAUNCH(stageShadeCall128Kernel);
        return (const void*)stageShadeCall128Kernel;
    default:
        return nullptr;
    }
}

}  // namespace astroray::wavefront

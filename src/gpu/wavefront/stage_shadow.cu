// stage_shadow.cu — pkg55 Phase B
//
// Shadow ray occlusion testing for NEE (Next Event Estimation). Reads shadow
// rays emitted by shade kernels, performs any-hit BVH traversal, accumulates
// NEE radiance contribution if unoccluded.
//
// Architecture: Cycles (blender/cycles @ c9227ff, Apache-2.0)
//   intern/cycles/kernel/integrator/shadow_catcher.h — shadow ray test +
//   direct lighting accumulation pattern.
//
// BVH any-hit: gpu_bvh_hit is shared with the intersect stage (src/gpu/gpu_bvh.h).
//   Undergraduate-level BVH traversal (trivial per CLAUDE.md §6).

#include "astroray/integrator_state_soa.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_bvh.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <cstdio>

namespace astroray::wavefront {

namespace {

__global__ void shadowKernel(
    const float4*  shadow_origin,
    const float4*  shadow_dir,
    const float*   shadow_tmax,
    const uint8_t* nee_active,
    const float4*  nee_contrib,
    const float4*  throughput,
    float4*  accum_rgb,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    int num_active)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= num_active) return;
    if (nee_active[idx] == 0) return;

    // Read shadow ray from SoA
    GRay shadowRay;
    shadowRay.origin    = GVec3(shadow_origin[idx].x, shadow_origin[idx].y, shadow_origin[idx].z);
    shadowRay.direction = GVec3(shadow_dir[idx].x,    shadow_dir[idx].y,    shadow_dir[idx].z);
    float tmax = shadow_tmax[idx];

    // Any-hit BVH test
    GHitRecord shadowHit;
    bool occluded = gpu_bvh_hit(bvhNodes, prims, tris, spheres,
                                shadowRay, 0.001f, tmax - 0.001f, shadowHit);

    if (!occluded) {
        // Add NEE contribution to accumulated radiance
        // nee_contrib already carries the combined BSDF * Le * MIS weight
        // (simplified in Phase B; full MIS in Phase C)
        GVec3 contrib(nee_contrib[idx].x, nee_contrib[idx].y, nee_contrib[idx].z);
        GVec3 tp(throughput[idx].x, throughput[idx].y, throughput[idx].z);
        GVec3 radiance = tp * contrib;

        float4 current_accum = accum_rgb[idx];
        current_accum.x += radiance.x;
        current_accum.y += radiance.y;
        current_accum.z += radiance.z;
        accum_rgb[idx] = current_accum;
    }
    // If occluded, NEE contribution is discarded (no light reaches the surface)
}

}  // namespace

void launchStageShadow(
    IntegratorStateSoA& state,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres)
{
    int n = state.num_active;
    if (n <= 0) return;

    int threads = 256;
    int blocks = (n + threads - 1) / threads;

    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_shadow",
            (const void*)shadowKernel, blocks, threads);
        shadowKernel<<<blocks, threads>>>(
            reinterpret_cast<const float4*>(state.shadow_origin),
            reinterpret_cast<const float4*>(state.shadow_dir),
            state.shadow_tmax,
            state.nee_active,
            reinterpret_cast<const float4*>(state.nee_contrib),
            reinterpret_cast<const float4*>(state.throughput),
            reinterpret_cast<float4*>(state.accum_rgb),
            d_bvhNodes, d_prims, d_tris, d_spheres,
            n);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_shadow launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        cudaDeviceSynchronize();
    }
}

}  // namespace astroray::wavefront

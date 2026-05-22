// stage_intersect_session_n3.cu — pkg55-B' Session N+3 part 2
//
// Wavefront intersect stage kernel for GPUWavefrontState (Session N+3 rewrite).
//
// This REPLACES the Phase A.1 stage_intersect.cu (which used IntegratorStateSoA).
// Session N+3 scope:
//   - Read ray from GPUWavefrontState (separate x/y/z float arrays).
//   - Call gpu_bvh_hit() (same BVH traversal as megakernel).
//   - Write hit record into separate hit buffers (GPUWavefrontHitBuffers).
//   - Terminate miss paths (path_alive = 0 for misses).
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §4.2 Session N+3.
// Design: PR #296 §4.1, §4.2 (two-tier gate: CPU↔GPU ULP ≤ 4 for PostIntersect geometry).
//
// Reference (Apache-2.0):
//   - Cycles intern/cycles/kernel/integrator/intersect_closest.h
//   - PBRT-v4 src/pbrt/wavefront/integrator.cpp BasicIntersect
//   - CPU mirror: src/cpu/wavefront/path_kernel.cpp::advance_one_bounce() intersect block

#include "astroray/gpu_wavefront_state.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_bvh.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <cstdio>
#include <stdexcept>

namespace astroray::wavefront {

namespace {

__global__ void stageIntersectKernel_N3(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= state.num_active) return;

    // Only process alive paths
    if (state.path_alive[idx] == 0) {
        hitBufs.hit_valid[idx] = 0;
        return;
    }

    // Read ray from SoA. Direction is ALREADY normalized (never renormalize at boundaries).
    GVec3 ray_origin(state.ray_origin_x[idx],
                     state.ray_origin_y[idx],
                     state.ray_origin_z[idx]);
    GVec3 ray_direction(state.ray_direction_x[idx],
                        state.ray_direction_y[idx],
                        state.ray_direction_z[idx]);

    // Construct GRay WITHOUT the normalizing ctor (already normalized by stage_init).
    GRay ray;
    ray.origin    = ray_origin;
    ray.direction = ray_direction;  // already unit; do NOT renormalize

    // BVH traversal (same entry point as megakernel and Phase A.1).
    GHitRecord rec;
    rec.primId = -1;
    bool hit = gpu_bvh_hit(bvhNodes, prims, tris, spheres,
                           ray, 0.001f, 1e30f, rec);

    if (hit) {
        // Write hit record into SoA. Mirrors CPU PostIntersect snapshot fields.
        hitBufs.hit_t[idx] = rec.t;
        hitBufs.hit_point_x[idx] = rec.point.x;
        hitBufs.hit_point_y[idx] = rec.point.y;
        hitBufs.hit_point_z[idx] = rec.point.z;
        hitBufs.hit_normal_x[idx] = rec.normal.x;
        hitBufs.hit_normal_y[idx] = rec.normal.y;
        hitBufs.hit_normal_z[idx] = rec.normal.z;
        hitBufs.hit_tangent_x[idx] = rec.tangent.x;
        hitBufs.hit_tangent_y[idx] = rec.tangent.y;
        hitBufs.hit_tangent_z[idx] = rec.tangent.z;
        hitBufs.hit_bitangent_x[idx] = rec.bitangent.x;
        hitBufs.hit_bitangent_y[idx] = rec.bitangent.y;
        hitBufs.hit_bitangent_z[idx] = rec.bitangent.z;
        hitBufs.hit_material_id[idx] = rec.materialId;
        hitBufs.hit_front_face[idx] = rec.frontFace ? 1 : 0;
        hitBufs.hit_is_delta[idx] = rec.isDelta ? 1 : 0;
        hitBufs.hit_valid[idx] = 1;
    } else {
        // Miss: terminate path (CPU handles env-map evaluation in post-processing).
        hitBufs.hit_valid[idx] = 0;
        hitBufs.hit_t[idx] = -1.0f;
        hitBufs.hit_material_id[idx] = -1;
        state.path_alive[idx] = 0;  // terminate miss paths
    }
}

}  // namespace

void launchStageIntersect_SessionN3(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres)
{
    int n = state.num_active;
    if (n <= 0) return;

    int threads = 256;
    int blocks  = (n + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_intersect_n3",
            (const void*)stageIntersectKernel_N3, blocks, threads);
        stageIntersectKernel_N3<<<blocks, threads>>>(
            state, hitBufs, d_bvhNodes, d_prims, d_tris, d_spheres);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_intersect_n3 launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        cudaError_t syncErr = cudaDeviceSynchronize();
        if (syncErr != cudaSuccess) {
            std::fprintf(stderr, "stage_intersect_n3 runtime error: %s\n",
                         cudaGetErrorString(syncErr));
            throw std::runtime_error(cudaGetErrorString(syncErr));
        }
    }
}

}  // namespace astroray::wavefront

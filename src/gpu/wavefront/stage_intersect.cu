// stage_intersect.cu — pkg55 Phase A.1
//
// Wavefront closest-hit intersect stage. Reads ray_origin/ray_direction
// from the SoA, runs gpu_bvh_hit() (the exact same BVH traversal the
// AoS megakernel uses — see src/gpu/path_trace_kernel.cu:265), writes
// hit_t/hit_prim/hit_mat into the SoA. Miss is encoded as
// hit_t=-1, hit_prim=-1, hit_mat=-1.
//
// Bit-identity to the AoS path is by construction: this kernel literally
// calls the same gpu_bvh_hit() entry point the megakernel does, with
// rays that the parity verifier in intersect_parity.cu re-derives from
// the same RNG snapshot.
//
// Reference (Apache-2.0):
//   - intern/cycles/kernel/integrator/intersect_closest.h —
//       integrator_intersect_closest() — reads ray from state, traces,
//       writes the hit slot back into state.
//   - mmp/pbrt-v4 src/pbrt/wavefront/integrator.cpp:GenerateRays() and
//     the BasicIntersect kernel: same pattern, RayWorkItem→hit fields.

#include "astroray/integrator_state_soa.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_bvh.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <cstdio>
#include <stdexcept>

namespace astroray::wavefront {

namespace {

__global__ void stageIntersectKernel(
    const float4* ray_origin,
    const float4* ray_direction,
    float*        hit_t,
    int*          hit_prim,
    int*          hit_mat,
    uint32_t*     sort_key,
    int           num_active,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= num_active) return;

    float4 o = ray_origin[idx];
    float4 d = ray_direction[idx];
    // IMPORTANT: bypass GRay(o,d) ctor — it would re-normalize the
    // direction. stage_init already wrote the once-normalized direction
    // returned by gpu_generateCameraRay(); a second normalize() pass
    // produces a 1-ulp drift relative to the AoS megakernel which
    // normalizes exactly once. Default-construct + field-assign keeps
    // the SoA path bit-identical to AoS.
    GRay ray;
    ray.origin    = GVec3(o.x, o.y, o.z);
    ray.direction = GVec3(d.x, d.y, d.z);

    GHitRecord rec;
    rec.primId = -1;
    bool hit = gpu_bvh_hit(bvhNodes, prims, tris, spheres,
                           ray, 0.001f, 1e30f, rec);
    if (hit) {
        hit_t[idx]    = rec.t;
        hit_prim[idx] = rec.primId;
        hit_mat[idx]  = rec.materialId;
        // Phase A.1 placeholder sort key: low 24 bits = materialId; alive
        // bit set. Phase B will re-encode (material_type, depth, ...).
        sort_key[idx] = (1u << 31) | (uint32_t)(rec.materialId & 0x00FFFFFF);
    } else {
        hit_t[idx]    = -1.f;
        hit_prim[idx] = -1;
        hit_mat[idx]  = -1;
        sort_key[idx] = 0u;  // dead path sorts first
    }
}

}  // namespace

void launchStageIntersect(
    IntegratorStateSoA& state,
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
            "wavefront_stage_intersect",
            (const void*)stageIntersectKernel, blocks, threads);
        stageIntersectKernel<<<blocks, threads>>>(
            reinterpret_cast<const float4*>(state.ray_origin),
            reinterpret_cast<const float4*>(state.ray_direction),
            state.hit_t, state.hit_prim, state.hit_mat, state.sort_key,
            n, d_bvhNodes, d_prims, d_tris, d_spheres);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_intersect launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        cudaDeviceSynchronize();
    }
}

}  // namespace astroray::wavefront

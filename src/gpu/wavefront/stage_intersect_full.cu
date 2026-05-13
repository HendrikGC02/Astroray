// stage_intersect_full.cu — pkg55 Phase B
//
// Extended intersect stage: BVH traversal (same as Phase A.1 stage_intersect.cu)
// plus full GHitRecord unpacking into Phase B SoA geometry fields.  Also
// initialises GSampledWavelengths per path (spectral state for shade stage).
//
// Key difference from Phase A.1 stage_intersect.cu:
//   - Writes hit_point / hit_normal / hit_tangent / hit_bitangent / hit_flags.
//   - Encodes Phase B sort_key: (alive<<31 | mat_type<<4).
//   - Initialises lambda[] / lambda_pdf[] from gpu_sampleUniformWavelengths().
//   - Resets path_alive, was_specular, nee_active, nee_contrib for first
//     bounce; subsequent bounces have these preserved from previous shade.
//     (The init kernel sets was_specular=1 for bounce 0.)
//
// Reference (Apache-2.0):
//   - intern/cycles/kernel/integrator/intersect_closest.h —
//     integrator_intersect_closest(): reads ray SoA, traces, writes isect SoA
//     including hit geometry + shader sort key.
//   - mmp/pbrt-v4 src/pbrt/wavefront/integrator.cpp GenerateRays() + BasicIntersect
//     pattern: same read→trace→write structure.

#include "astroray/integrator_state_soa.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_bvh.h"
#include "astroray/gpu_materials.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdio>
#include <stdexcept>

namespace astroray::wavefront {

namespace {

__global__ void stageIntersectFullKernel(
    // Ray SoA (read)
    const float4* ray_origin,
    const float4* ray_direction,
    // Hit SoA (write — Phase A.1 fields)
    float*    hit_t,
    int*      hit_prim,
    int*      hit_mat,
    uint32_t* sort_key,
    // Hit SoA (write — Phase B fields)
    float4*   hit_point,
    float4*   hit_normal,
    float4*   hit_tangent,
    float4*   hit_bitangent,
    uint8_t*  hit_flags,
    uint8_t*  path_alive,
    uint8_t*  was_specular_init,  // only set on bounce 0 (see caller)
    // Spectral init (write — Phase B fields)
    float4*   lambda,
    float4*   lambda_pdf,
    float4*   throughput_sp,
    // NEE reset (write — Phase B fields)
    uint8_t*  nee_active,
    float4*   nee_contrib,
    // RNG
    curandState* rng_state,
    // Scene
    int           num_active,
    bool          init_spectral,   // true only on first bounce
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= num_active) return;

    // Skip dead paths — they don't contribute; sort will move them to front.
    if (path_alive[idx] == 0) {
        hit_t[idx]    = -1.f;
        hit_prim[idx] = -1;
        hit_mat[idx]  = -1;
        sort_key[idx] = 0u;
        nee_active[idx] = 0;
        return;
    }

    // Read ray SoA — bypass GRay ctor (no re-normalise; see Phase A.1 note).
    float4 o = ray_origin[idx];
    float4 d = ray_direction[idx];
    GRay ray;
    ray.origin    = GVec3(o.x, o.y, o.z);
    ray.direction = GVec3(d.x, d.y, d.z);

    GHitRecord rec;
    rec.primId = -1;
    bool hit = gpu_bvh_hit(bvhNodes, prims, tris, spheres, ray, 0.001f, 1e30f, rec);

    // Reset per-bounce NEE state.
    nee_active[idx]  = 0;
    nee_contrib[idx] = make_float4(0.f, 0.f, 0.f, 0.f);

    if (!hit) {
        hit_t[idx]    = -1.f;
        hit_prim[idx] = -1;
        hit_mat[idx]  = -1;
        sort_key[idx] = 0u;   // miss: sort to dead bucket
        // hit_point / normal / flags left from previous bounce — won't be read.
        return;
    }

    // Phase A.1 fields.
    hit_t[idx]    = rec.t;
    hit_prim[idx] = rec.primId;
    hit_mat[idx]  = rec.materialId;

    // Phase B geometry.
    hit_point[idx]     = make_float4(rec.point.x,     rec.point.y,     rec.point.z,     0.f);
    hit_normal[idx]    = make_float4(rec.normal.x,    rec.normal.y,    rec.normal.z,    0.f);
    hit_tangent[idx]   = make_float4(rec.tangent.x,   rec.tangent.y,   rec.tangent.z,   0.f);
    hit_bitangent[idx] = make_float4(rec.bitangent.x, rec.bitangent.y, rec.bitangent.z, 0.f);
    uint8_t flags = 0;
    if (rec.frontFace) flags |= 0x1u;
    if (rec.isDelta)   flags |= 0x2u;
    hit_flags[idx] = flags;

    // Phase B sort key: alive=1, material type in bits [7:4].
    // CUB radix sort ascending → alive=1 + low mat_type sorts after dead (key=0).
    // Reference: Cycles integrator_state.h `shader_sort_key` encoding.
    uint32_t mat_type = (uint32_t)(prims[rec.primId].type == GPRIM_SPHERE
        ? spheres[tris[0].materialId].materialId  // unused — see below
        : tris[rec.primId < 0 ? 0 : rec.primId].materialId);
    // materialId is the index into d_mats; we need the GMaterialType.
    // But we don't have d_mats here. Encode materialId and let the sort
    // create coherent buckets — Phase B shade kernels filter by hit_mat
    // modulo the runtime d_mats[hit_mat].type check.  Sort key:
    //   alive=1 → bit 31 set; material id in bits 0-23.
    sort_key[idx] = (1u << 31) | (uint32_t)(rec.materialId & 0x00FFFFFFu);

    // Spectral: initialise wavelengths on first bounce; on subsequent bounces
    // lambda[] was already written by the previous shade kernel.
    if (init_spectral) {
        curandState localRng = rng_state[idx];
        GSampledWavelengths wl = gpu_sampleUniformWavelengths(&localRng);
        rng_state[idx] = localRng;
        lambda[idx]     = make_float4(wl.lambda[0], wl.lambda[1], wl.lambda[2], wl.lambda[3]);
        lambda_pdf[idx] = make_float4(wl.pdf[0],    wl.pdf[1],    wl.pdf[2],    wl.pdf[3]);
        throughput_sp[idx] = make_float4(1.f, 1.f, 1.f, 1.f);
        // was_specular: true for bounce 0 (camera ray has no prior event).
        was_specular_init[idx] = 1;
    }
}

}  // namespace

void launchStageIntersectFull(
    IntegratorStateSoA& state,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres)
{
    int n = state.num_active;
    if (n <= 0) return;

    // init_spectral = true only on bounce 0 (depth == 0 for all slots after
    // stage_init).  We detect this by checking depth[0]; all slots start at 0.
    // The caller (wavefront_render_loop) passes bounce index; we use the
    // was_specular pointer as the "first-bounce flag" — see wavefront_render_loop.cu.
    // For the standalone launcher, always init.
    bool init_spectral = true;

    int threads = 256;
    int blocks  = (n + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_intersect_full",
            (const void*)stageIntersectFullKernel, blocks, threads);
        stageIntersectFullKernel<<<blocks, threads>>>(
            reinterpret_cast<const float4*>(state.ray_origin),
            reinterpret_cast<const float4*>(state.ray_direction),
            state.hit_t, state.hit_prim, state.hit_mat, state.sort_key,
            reinterpret_cast<float4*>(state.hit_point),
            reinterpret_cast<float4*>(state.hit_normal),
            reinterpret_cast<float4*>(state.hit_tangent),
            reinterpret_cast<float4*>(state.hit_bitangent),
            state.hit_flags,
            state.path_alive,
            state.was_specular,
            reinterpret_cast<float4*>(state.lambda),
            reinterpret_cast<float4*>(state.lambda_pdf),
            reinterpret_cast<float4*>(state.throughput_sp),
            state.nee_active,
            reinterpret_cast<float4*>(state.nee_contrib),
            reinterpret_cast<curandState*>(state.rng_state),
            n, init_spectral,
            d_bvhNodes, d_prims, d_tris, d_spheres);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_intersect_full launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        cudaDeviceSynchronize();
    }
}

// Bounced intersect (not init): does not re-initialise spectral state.
// Called from wavefront_render_loop.cu for bounce > 0.
void launchStageIntersectFullBounce(
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
    stageIntersectFullKernel<<<blocks, threads>>>(
        reinterpret_cast<const float4*>(state.ray_origin),
        reinterpret_cast<const float4*>(state.ray_direction),
        state.hit_t, state.hit_prim, state.hit_mat, state.sort_key,
        reinterpret_cast<float4*>(state.hit_point),
        reinterpret_cast<float4*>(state.hit_normal),
        reinterpret_cast<float4*>(state.hit_tangent),
        reinterpret_cast<float4*>(state.hit_bitangent),
        state.hit_flags,
        state.path_alive,
        state.was_specular,
        reinterpret_cast<float4*>(state.lambda),
        reinterpret_cast<float4*>(state.lambda_pdf),
        reinterpret_cast<float4*>(state.throughput_sp),
        state.nee_active,
        reinterpret_cast<float4*>(state.nee_contrib),
        reinterpret_cast<curandState*>(state.rng_state),
        n, /*init_spectral=*/false,
        d_bvhNodes, d_prims, d_tris, d_spheres);
    cudaDeviceSynchronize();
}

}  // namespace astroray::wavefront

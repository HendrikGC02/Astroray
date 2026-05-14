// intersect_parity.cu — pkg55 Phase A.1
//
// Dual-trace parity verifier for the wavefront intersect stage. For each
// SoA slot, re-derives the AoS-equivalent reference path (re-init local
// RNG from the pre-init snapshot, regenerate the camera ray with the
// same gpu_generateCameraRay() call sequence the megakernel inlines,
// run gpu_bvh_hit()), and compares the resulting hit_t/hit_prim/hit_mat
// against what stage_intersect wrote. On mismatch: printf the diverging
// triple, then __trap().
//
// This is the build-flag-gated, env-var-triggered "kernel-side assert"
// described in the pkg55-A.1 PR plan. AoS megakernel output is
// unaffected — the host wrapper restores rng_state from the snapshot
// before calling launchPathTraceKernel().
//
// Reference patterns (Apache-2.0; cite, do not blindly mirror):
//   - intern/cycles/device/cuda/queue.cpp + kernel/integrator/state_test.h —
//       Cycles' "verify state" debug pass re-traces from snapshot rng
//       and aborts on mismatch when --debug-cuda-kernel-paranoia is set.
//   - mmp/pbrt-v4 src/pbrt/wavefront/integrator.cpp:debugStart hook —
//       optional reference-path comparator launched alongside production
//       kernels under --debug.

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

__global__ void intersectParityKernel(
    const float4*      soa_ray_origin,
    const float4*      soa_ray_direction,
    const float*       soa_hit_t,
    const int*         soa_hit_prim,
    const int*         soa_hit_mat,
    const curandState* rng_snapshot,
    GCameraParams      cam,
    int width, int height,
    const GBVHNode*    bvhNodes,
    const GPrimitive*  prims,
    const GTriangle*   tris,
    const GSphere*     spheres,
    int* mismatch_count)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    int total = width * height;
    if (idx >= total) return;

    int px = idx % width;
    int py = idx / width;

    // Reference path: same rng, same camera-ray helper, same BVH call.
    curandState localRng = rng_snapshot[idx];
    GRay aos_ray = gpu_generateCameraRay(cam, px, py, &localRng);

    GHitRecord aos_rec;
    aos_rec.primId = -1;
    bool aos_hit = gpu_bvh_hit(bvhNodes, prims, tris, spheres,
                               aos_ray, 0.001f, 1e30f, aos_rec);
    float aos_t   = aos_hit ? aos_rec.t          : -1.f;
    int   aos_p   = aos_hit ? aos_rec.primId     : -1;
    int   aos_m   = aos_hit ? aos_rec.materialId : -1;

    // First check: ray inputs must match what stage_init wrote. If this
    // diverges, downstream hit fields cannot match either; report it
    // up front so the trap message points at the real cause.
    float4 so = soa_ray_origin[idx];
    float4 sd = soa_ray_direction[idx];
    if (so.x != aos_ray.origin.x || so.y != aos_ray.origin.y || so.z != aos_ray.origin.z ||
        sd.x != aos_ray.direction.x || sd.y != aos_ray.direction.y || sd.z != aos_ray.direction.z) {
        atomicAdd(mismatch_count, 1);
        printf("[wavefront-parity] ray %d: ray-input divergence\n"
               "  aos.o=(%.9g,%.9g,%.9g) soa.o=(%.9g,%.9g,%.9g)\n"
               "  aos.d=(%.9g,%.9g,%.9g) soa.d=(%.9g,%.9g,%.9g)\n",
               idx,
               aos_ray.origin.x, aos_ray.origin.y, aos_ray.origin.z,
               so.x, so.y, so.z,
               aos_ray.direction.x, aos_ray.direction.y, aos_ray.direction.z,
               sd.x, sd.y, sd.z);
        __trap();
    }

    float st = soa_hit_t[idx];
    int   sp = soa_hit_prim[idx];
    int   sm = soa_hit_mat[idx];

    bool t_diff = (st != aos_t);
    bool p_diff = (sp != aos_p);
    bool m_diff = (sm != aos_m);
    if (t_diff || p_diff || m_diff) {
        atomicAdd(mismatch_count, 1);
        printf("[wavefront-parity] ray %d: hit divergence\n"
               "  aos.t=%.9g  soa.t=%.9g  delta_t=%.3e\n"
               "  aos.prim=%d soa.prim=%d\n"
               "  aos.mat=%d  soa.mat=%d\n",
               idx,
               aos_t, st, st - aos_t,
               aos_p, sp,
               aos_m, sm);
        __trap();
    }
}

}  // namespace

int launchIntersectParity(
    const IntegratorStateSoA& state,
    const void*       rng_snapshot,
    const GCameraParams& cam,
    int width, int height,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres)
{
    int total = width * height;
    if (total <= 0) return 0;
    if (!rng_snapshot) return 0;
    if (state.num_active < total) {
        throw std::runtime_error(
            "wavefront::launchIntersectParity — num_active < pixel count");
    }

    int* d_mismatch = nullptr;
    // pkg85-B: previously discarded errors from cudaMalloc/cudaMemset.
    {
        cudaError_t e = cudaMalloc(reinterpret_cast<void**>(&d_mismatch),
                                   sizeof(int));
        if (e != cudaSuccess) {
            std::fprintf(stderr, "intersect_parity cudaMalloc failed: %s\n",
                         cudaGetErrorString(e));
            throw std::runtime_error(cudaGetErrorString(e));
        }
        e = cudaMemset(d_mismatch, 0, sizeof(int));
        if (e != cudaSuccess) {
            cudaFree(d_mismatch);
            cudaGetLastError();
            std::fprintf(stderr, "intersect_parity cudaMemset failed: %s\n",
                         cudaGetErrorString(e));
            throw std::runtime_error(cudaGetErrorString(e));
        }
    }

    int threads = 256;
    int blocks  = (total + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_intersect_parity",
            (const void*)intersectParityKernel, blocks, threads);
        intersectParityKernel<<<blocks, threads>>>(
            reinterpret_cast<const float4*>(state.ray_origin),
            reinterpret_cast<const float4*>(state.ray_direction),
            state.hit_t, state.hit_prim, state.hit_mat,
            reinterpret_cast<const curandState*>(rng_snapshot),
            cam, width, height,
            d_bvhNodes, d_prims, d_tris, d_spheres,
            d_mismatch);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            cudaFree(d_mismatch);
            cudaGetLastError();  // pkg85-B: swallow cleanup error pre-throw
            std::fprintf(stderr, "intersect_parity launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        // pkg85-B: async runtime errors must not be silently discarded.
        cudaError_t syncErr = cudaDeviceSynchronize();
        if (syncErr != cudaSuccess) {
            cudaFree(d_mismatch);
            cudaGetLastError();
            std::fprintf(stderr, "intersect_parity runtime error: %s\n",
                         cudaGetErrorString(syncErr));
            throw std::runtime_error(cudaGetErrorString(syncErr));
        }
    }
    int h_mismatch = 0;
    // pkg85-B: check the readback and the final free.
    cudaError_t cpyErr = cudaMemcpy(&h_mismatch, d_mismatch, sizeof(int),
                                    cudaMemcpyDeviceToHost);
    if (cpyErr != cudaSuccess) {
        cudaFree(d_mismatch);
        cudaGetLastError();
        std::fprintf(stderr, "intersect_parity cudaMemcpy failed: %s\n",
                     cudaGetErrorString(cpyErr));
        throw std::runtime_error(cudaGetErrorString(cpyErr));
    }
    cudaError_t freeErr = cudaFree(d_mismatch);
    if (freeErr != cudaSuccess) {
        cudaGetLastError();
        std::fprintf(stderr, "intersect_parity cudaFree failed: %s\n",
                     cudaGetErrorString(freeErr));
    }
    return h_mismatch;
}

}  // namespace astroray::wavefront

// tlas_parity.cu — pkg114 increment 1.
//
// Identity-passthrough parity probe for the two-level (TLAS-over-BLAS)
// traversal. Builds ONE identity instance (a single BLAS = the whole uploaded
// scene, M = Minv = I, a 1-leaf TLAS) and, for every primary camera ray,
// dual-traces gpu_tlas_hit(identity) against the single-level gpu_bvh_hit.
//
// If the two-level plumbing (struct upload, leaf/instance indirection, BLAS
// root-pointer offset, primId remap, ray field-assign, back-transform) is
// correct, the identity case must reduce EXACTLY to the single-level result on
// t / primId / materialId / frontFace / point, with at most a sub-ulp normal
// drift from the (no-op) inverse-transpose renormalize.
//
// Mirrors the dual-trace pattern of src/gpu/wavefront/intersect_parity.cu.
// Touches NO production kernel (zero render risk for increment 1).
//
// References (Apache-2.0; see .astroray_plan/docs/two-level-bvh-research.md):
//   pbrt-v4 src/pbrt/cpu/primitive.cpp TransformedPrimitive::Intersect;
//   Cycles  src/kernel/bvh/bvh.h bvh_instance_push.

#include "astroray/gpu_tlas_parity.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_bvh.h"
#include "astroray/gpu_materials.h"     // gpu_generateCameraRay
#include "astroray/gpu_scene_upload.h"  // SceneUploadResult, buildSceneArrays
#include "raytracer.h"                  // Renderer, Camera

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <vector>
#include <cstdio>
#include <stdexcept>
#include <algorithm>

namespace astroray {
namespace twolevel {

namespace {

#define TLAS_CUDA_CHECK(call) do {                                          \
    cudaError_t _e = (call);                                                \
    if (_e != cudaSuccess) {                                                \
        std::fprintf(stderr, "[tlas-parity] CUDA error %s:%d: %s\n",        \
                     __FILE__, __LINE__, cudaGetErrorString(_e));           \
        throw std::runtime_error(cudaGetErrorString(_e));                   \
    }                                                                       \
} while (0)

template <typename T>
T* devUpload(const std::vector<T>& host) {
    if (host.empty()) return nullptr;
    T* d = nullptr;
    TLAS_CUDA_CHECK(cudaMalloc(reinterpret_cast<void**>(&d), host.size() * sizeof(T)));
    TLAS_CUDA_CHECK(cudaMemcpy(d, host.data(), host.size() * sizeof(T),
                               cudaMemcpyHostToDevice));
    return d;
}

__global__ void tlasParityKernel(
    GCameraParams     cam, int width, int height,
    const GBVHNode*   nodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GTLASNode*  tlas,
    const GInstance*  instances,
    const GBLAS*      blas,
    int*   out_disagree,
    int*   out_fieldmm,
    float* out_td,
    float* out_pd,
    float* out_nd)
{
    int idx   = blockIdx.x * blockDim.x + threadIdx.x;
    int total = width * height;
    if (idx >= total) return;

    int px = idx % width;
    int py = idx / width;

    // One camera ray, generated once and fed to BOTH traversals so the only
    // variable under test is single-level vs two-level traversal.
    curandState rng;
    curand_init(0ULL, idx, 0, &rng);
    GRay ray = gpu_generateCameraRay(cam, px, py, &rng);

    GHitRecord refRec; refRec.primId = -1;
    bool refHit = gpu_bvh_hit(nodes, prims, tris, spheres,
                              ray, 0.001f, 1e30f, refRec);

    GHitRecord tRec; tRec.primId = -1;
    bool tHit = gpu_tlas_hit(tlas, instances, blas, nodes, prims, tris, spheres,
                             ray, 0.001f, 1e30f, tRec);

    out_disagree[idx] = 0;
    out_fieldmm[idx]  = 0;
    out_td[idx] = 0.f;
    out_pd[idx] = 0.f;
    out_nd[idx] = 0.f;

    if (refHit != tHit) { out_disagree[idx] = 1; return; }
    if (!refHit) return;  // both missed — agreement

    bool fmm = (refRec.t          != tRec.t) ||
               (refRec.primId     != tRec.primId) ||
               (refRec.materialId != tRec.materialId) ||
               (refRec.frontFace  != tRec.frontFace);
    out_fieldmm[idx] = fmm ? 1 : 0;
    out_td[idx] = fabsf(tRec.t - refRec.t);
    out_pd[idx] = (tRec.point  - refRec.point ).length();
    out_nd[idx] = (tRec.normal - refRec.normal).length();
}

}  // namespace

TlasParityResult cuda_tlas_identity_parity(
    const Renderer& cpu, const Camera& cam, int width, int height)
{
    TlasParityResult res;
    res.totalRays = width * height;
    if (res.totalRays <= 0) return res;

    // Host-side flat scene arrays (requires a built CPU BVH).
    SceneUploadResult s = buildSceneArrays(cpu, &cam);
    if (s.nodes.empty())
        throw std::runtime_error("[tlas-parity] empty BVH — build the scene first");

    // The kernel maps pixels via cam.width/height; keep the probe grid matched.
    s.camera.width  = width;
    s.camera.height = height;

    // --- Synthesize the identity two-level structure ---
    // One BLAS = the whole uploaded scene (its leaf prim offsets are already
    // global, so primOffset = 0; its node array starts at 0, so nodeOffset = 0).
    std::vector<GBLAS> blas = { GBLAS{ /*nodeOffset*/0, /*primOffset*/0 } };
    GInstance inst;
    inst.worldFromObject = GMat4::identity();
    inst.objectFromWorld = GMat4::identity();
    inst.blasIndex       = 0;
    inst.instanceId      = 0;
    std::vector<GInstance> instances = { inst };
    // 1-leaf TLAS whose bounds equal the scene root AABB; points at instance 0.
    GTLASNode tnode = s.nodes[0];        // copy scene-root bounds
    tnode.primitivesOffset = 0;          // into instances[]
    tnode.nPrimitives      = 1;
    tnode.axis             = 0;
    tnode.pad              = 0;
    std::vector<GTLASNode> tlas = { tnode };

    // --- Upload everything ---
    GBVHNode*   d_nodes     = devUpload(s.nodes);
    GPrimitive* d_prims     = devUpload(s.prims);
    GTriangle*  d_tris      = devUpload(s.triangles);
    GSphere*    d_spheres   = devUpload(s.spheres);
    GTLASNode*  d_tlas      = devUpload(tlas);
    GInstance*  d_instances = devUpload(instances);
    GBLAS*      d_blas      = devUpload(blas);

    int total = res.totalRays;
    int   *d_disagree = nullptr, *d_fieldmm = nullptr;
    float *d_td = nullptr, *d_pd = nullptr, *d_nd = nullptr;
    TLAS_CUDA_CHECK(cudaMalloc(&d_disagree, total * sizeof(int)));
    TLAS_CUDA_CHECK(cudaMalloc(&d_fieldmm,  total * sizeof(int)));
    TLAS_CUDA_CHECK(cudaMalloc(&d_td, total * sizeof(float)));
    TLAS_CUDA_CHECK(cudaMalloc(&d_pd, total * sizeof(float)));
    TLAS_CUDA_CHECK(cudaMalloc(&d_nd, total * sizeof(float)));

    int threads = 256;
    int blocks  = (total + threads - 1) / threads;
    tlasParityKernel<<<blocks, threads>>>(
        s.camera, width, height,
        d_nodes, d_prims, d_tris, d_spheres,
        d_tlas, d_instances, d_blas,
        d_disagree, d_fieldmm, d_td, d_pd, d_nd);
    cudaError_t launchErr = cudaGetLastError();
    if (launchErr == cudaSuccess) launchErr = cudaDeviceSynchronize();

    // Download (even on success path) then free.
    std::vector<int>   h_disagree(total), h_fieldmm(total);
    std::vector<float> h_td(total), h_pd(total), h_nd(total);
    cudaError_t cpyErr = launchErr;
    if (cpyErr == cudaSuccess) cpyErr = cudaMemcpy(h_disagree.data(), d_disagree, total*sizeof(int), cudaMemcpyDeviceToHost);
    if (cpyErr == cudaSuccess) cpyErr = cudaMemcpy(h_fieldmm.data(),  d_fieldmm,  total*sizeof(int), cudaMemcpyDeviceToHost);
    if (cpyErr == cudaSuccess) cpyErr = cudaMemcpy(h_td.data(), d_td, total*sizeof(float), cudaMemcpyDeviceToHost);
    if (cpyErr == cudaSuccess) cpyErr = cudaMemcpy(h_pd.data(), d_pd, total*sizeof(float), cudaMemcpyDeviceToHost);
    if (cpyErr == cudaSuccess) cpyErr = cudaMemcpy(h_nd.data(), d_nd, total*sizeof(float), cudaMemcpyDeviceToHost);

    cudaFree(d_disagree); cudaFree(d_fieldmm);
    cudaFree(d_td); cudaFree(d_pd); cudaFree(d_nd);
    cudaFree(d_nodes); cudaFree(d_prims); cudaFree(d_tris); cudaFree(d_spheres);
    cudaFree(d_tlas); cudaFree(d_instances); cudaFree(d_blas);
    cudaGetLastError();  // swallow any cleanup error

    if (cpyErr != cudaSuccess) {
        std::fprintf(stderr, "[tlas-parity] kernel/copy error: %s\n",
                     cudaGetErrorString(cpyErr));
        throw std::runtime_error(cudaGetErrorString(cpyErr));
    }

    for (int i = 0; i < total; ++i) {
        res.hitDisagree   += h_disagree[i];
        res.fieldMismatch += h_fieldmm[i];
        res.maxTDelta      = std::max(res.maxTDelta,      h_td[i]);
        res.maxPointDelta  = std::max(res.maxPointDelta,  h_pd[i]);
        res.maxNormalDelta = std::max(res.maxNormalDelta, h_nd[i]);
    }
    return res;
}

}  // namespace twolevel
}  // namespace astroray

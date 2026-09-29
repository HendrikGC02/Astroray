// optix_ray_ab.cu — pkg299 fixed-ray A/B probe: traces the same rays through
// the software BVH (gpu_tlas_hit / gpu_tlas_occluded, the wavefront's own
// traversal) and through the OptiX launches + gpu_hw_hit_record (the
// <HwHits=true> intersect reconstruction), and returns both per ray. Test hook
// only (tests/test_pkg299_optix_traversal.py), in the style of tlas_parity.cu;
// no production kernel calls it.

#ifdef ASTRORAY_OPTIX_TRAVERSAL

#include "astroray/gpu_types.h"
#include "astroray/gpu_bvh.h"
#include "astroray/gpu_scene_upload.h"
#include "astroray/gpu_optix_traversal.h"
#include "optix_launch_params.h"

#include <cuda_runtime.h>

#include <stdexcept>
#include <string>
#include <vector>

namespace astroray {
namespace optix_trav {

namespace {

template <typename T>
T* upload(const std::vector<T>& v) {
    if (v.empty()) return nullptr;
    T* d = nullptr;
    if (cudaMalloc(&d, v.size() * sizeof(T)) != cudaSuccess)
        throw std::runtime_error("[pkg299 ray A/B] cudaMalloc failed");
    cudaMemcpy(d, v.data(), v.size() * sizeof(T), cudaMemcpyHostToDevice);
    return d;
}

template <typename T>
std::vector<T> download(const T* d, int n) {
    std::vector<T> h(n);
    cudaMemcpy(h.data(), d, n * sizeof(T), cudaMemcpyDeviceToHost);
    return h;
}

__global__ void abClosestKernel(
    int n, const float* f, const GTLASNode* tlas, const GInstance* instances,
    const GBLAS* blas, const GBVHNode* nodes, const GPrimitive* prims,
    const GTriangle* tris, const GSphere* spheres,
    const float* hwT, const int* hwPrim, const float* hwU, const float* hwV, const int* hwInst,
    int* swHit, float* swT, int* swPrimOut, int* hwHit, float* hwTOut, int* hwPrimOut,
    float* dPoint, float* dNormal, int* sameFace, int* sameMat)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    GRay ray;   // raw SoA-style ray (no ctor renormalisation), as intersectPathSlotT
    ray.origin    = GVec3(f[0 * n + i], f[1 * n + i], f[2 * n + i]);
    ray.direction = GVec3(f[3 * n + i], f[4 * n + i], f[5 * n + i]);
    const float tMax = 1e30f;   // wavefront intersect extent (lane 6 is shadow-only)
    GHitRecord a, b;
    a.primId = -1; b.primId = -1;
    const bool ha = gpu_tlas_hit(tlas, instances, blas, nodes, prims, tris, spheres,
                                 ray, 0.001f, tMax, a);
    const bool hb = gpu_hw_hit_record(hwT[i], hwPrim[i], hwU[i], hwV[i], hwInst[i],
                                      instances, blas, prims, tris, ray, b);
    swHit[i] = ha; hwHit[i] = hb;
    swT[i] = ha ? a.t : -1.f;       swPrimOut[i] = ha ? a.primId : -1;
    hwTOut[i] = hb ? b.t : -1.f;    hwPrimOut[i] = hb ? b.primId : -1;
    dPoint[i]  = (ha && hb) ? (a.point - b.point).length() : 0.f;
    dNormal[i] = (ha && hb) ? (a.normal - b.normal).length() : 0.f;
    sameFace[i] = (ha && hb) ? (a.frontFace == b.frontFace) : 1;
    sameMat[i]  = (ha && hb) ? (a.materialId == b.materialId) : 1;
}

__global__ void abShadowKernel(
    int n, const float* f, const GTLASNode* tlas, const GInstance* instances,
    const GBLAS* blas, const GBVHNode* nodes, const GPrimitive* prims,
    const GTriangle* tris, const GSphere* spheres, int* swOcc)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    GRay ray;
    ray.origin    = GVec3(f[0 * n + i], f[1 * n + i], f[2 * n + i]);
    ray.direction = GVec3(f[3 * n + i], f[4 * n + i], f[5 * n + i]);
    // gpu_nee_occlude's triangle-light branch: any hit in [0.001, maxDist].
    swOcc[i] = gpu_tlas_occluded(tlas, instances, blas, nodes, prims, tris, spheres,
                                 ray, 0.001f, f[6 * n + i]) ? 1 : 0;
}

__global__ void iotaKernel(int* q, int* alive, int* bounce, int n)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    q[i] = i; alive[i] = 1; bounce[i] = 1;   // bounce 1: no camera clip
}

}  // namespace

RayAbResult cuda_optix_ray_ab(const Renderer& cpu, const float* origins, const float* dirs,
                              const float* tmax, int n, bool shadow)
{
    RayAbResult r;
    if (n <= 0) return r;
    SceneUploadResult s = buildSceneArrays(cpu, nullptr);
    if (!s.spheres.empty() || !s.curveSegments.empty() || !s.motionVertices.empty())
        throw std::runtime_error("[pkg299 ray A/B] scene is not triangle-only");

    std::vector<float> f(size_t(7) * n);
    for (int i = 0; i < n; ++i) {
        for (int k = 0; k < 3; ++k) {
            f[size_t(k) * n + i]     = origins[3 * i + k];
            f[size_t(3 + k) * n + i] = dirs[3 * i + k];
        }
        f[size_t(6) * n + i] = tmax[i];
    }
    GBVHNode*   d_nodes = upload(s.nodes);
    GPrimitive* d_prims = upload(s.prims);
    GTriangle*  d_tris  = upload(s.triangles);
    GTLASNode*  d_tlas  = upload(s.tlas);
    GInstance*  d_inst  = upload(s.instances);
    GBLAS*      d_blas  = upload(s.blas);
    float*      d_f     = upload(f);

    if (!buildAccel(d_prims, (int)s.prims.size(), d_tris, s.instances.data(),
                    (int)s.instances.size(), s.blas.data(), (int)s.blas.size()))
        throw std::runtime_error("[pkg299 ray A/B] OptiX accel build failed: " + lastError());
    HwHitBuffers hb = ensureBuffers(n);

    int *d_q = nullptr, *d_alive = nullptr, *d_bounce = nullptr, *d_count = nullptr;
    cudaMalloc(&d_q, n * sizeof(int)); cudaMalloc(&d_alive, n * sizeof(int));
    cudaMalloc(&d_bounce, n * sizeof(int)); cudaMalloc(&d_count, sizeof(int));
    cudaMemcpy(d_count, &n, sizeof(int), cudaMemcpyHostToDevice);
    const int threads = 256, blocks = (n + threads - 1) / threads;
    iotaKernel<<<blocks, threads>>>(d_q, d_alive, d_bounce, n);

    const int nb = 10;   // abClosestKernel outputs
    std::vector<void*> outs(nb, nullptr);
    for (auto& o : outs) cudaMalloc(&o, n * sizeof(float));

    if (shadow) {
        ShadowLaunch sl{};
        sl.queue = d_q; sl.count = d_count; sl.f = d_f; sl.cap = n; sl.maxDistLane = 6;
        sl.outOccluded = hb.occluded;
        traceShadow(sl, n);
        abShadowKernel<<<blocks, threads>>>(n, d_f, d_tlas, d_inst, d_blas, d_nodes, d_prims,
                                            d_tris, nullptr, (int*)outs[0]);
    } else {
        // Bounce-1 rays (no camera clip): [0.001, 1e30], the wavefront extent.
        ClosestLaunch cl{};
        cl.queue = d_q; cl.count = d_count; cl.alive = d_alive; cl.bounce = d_bounce;
        cl.ox = d_f + 0 * size_t(n); cl.oy = d_f + 1 * size_t(n); cl.oz = d_f + 2 * size_t(n);
        cl.dx = d_f + 3 * size_t(n); cl.dy = d_f + 4 * size_t(n); cl.dz = d_f + 5 * size_t(n);
        cl.outT = hb.t; cl.outPrim = hb.prim; cl.outU = hb.u; cl.outV = hb.v; cl.outInst = hb.inst;
        traceClosest(cl, n);
        abClosestKernel<<<blocks, threads>>>(
            n, d_f, d_tlas, d_inst, d_blas, d_nodes, d_prims, d_tris, nullptr,
            hb.t, hb.prim, hb.u, hb.v, hb.inst,
            (int*)outs[0], (float*)outs[1], (int*)outs[2], (int*)outs[3], (float*)outs[4],
            (int*)outs[5], (float*)outs[6], (float*)outs[7], (int*)outs[8], (int*)outs[9]);
    }
    cudaError_t err = cudaDeviceSynchronize();
    if (err == cudaSuccess) {
        if (shadow) {
            r.swOccluded = download((const int*)outs[0], n);
            r.hwOccluded = download((const int*)hb.occluded, n);
        } else {
            r.swHit   = download((const int*)outs[0], n);
            r.swT     = download((const float*)outs[1], n);
            r.swPrim  = download((const int*)outs[2], n);
            r.hwHit   = download((const int*)outs[3], n);
            r.hwT     = download((const float*)outs[4], n);
            r.hwPrim  = download((const int*)outs[5], n);
            r.dPoint  = download((const float*)outs[6], n);
            r.dNormal = download((const float*)outs[7], n);
            r.sameFace = download((const int*)outs[8], n);
            r.sameMat  = download((const int*)outs[9], n);
        }
    }
    for (auto& o : outs) cudaFree(o);
    cudaFree(d_q); cudaFree(d_alive); cudaFree(d_bounce); cudaFree(d_count);
    cudaFree(d_nodes); cudaFree(d_prims); cudaFree(d_tris); cudaFree(d_tlas);
    cudaFree(d_inst); cudaFree(d_blas); cudaFree(d_f);
    // The probe replaced whatever accel the wavefront cached: drop it so the next
    // render rebuilds (a reuse render falls back to the software BVH).
    releaseAccel();
    if (err != cudaSuccess)
        throw std::runtime_error(std::string("[pkg299 ray A/B] ") + cudaGetErrorString(err));
    return r;
}

}  // namespace optix_trav
}  // namespace astroray

#endif  // ASTRORAY_OPTIX_TRAVERSAL

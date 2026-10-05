// optix_accel.cu — pkg299 device-built OptiX acceleration structures for the
// wavefront: one triangle GAS per pkg114 BLAS plus a single-level IAS carrying
// the instance transforms, or one GAS over the whole flat scene when there are
// no instances. Also owns the per-slot hit/occlusion side buffers.
//
// References:
//   - NVIDIA OptiX SDK 9.1 samples optixTriangle / sutil Scene::buildMeshAccels
//     and buildInstanceAccel (BSD-3-Clause): optixAccelComputeMemoryUsage ->
//     optixAccelBuild with OPTIX_PROPERTY_TYPE_COMPACTED_SIZE -> optixAccelCompact.
//   - OptiX 9.1 Programming Guide, "Triangle build inputs": triangles with NaN
//     vertices are inactive, so non-triangle prims keep their index slot.
//   - Cycles intern/cycles/device/optix/device_impl.cpp (Apache-2.0): IAS over
//     per-object GAS, one SBT record for all geometry.
//
// Primitive index contract: the GAS for a BLAS is built over
// prims[primOffset .. primOffset + count) in order, so optixGetPrimitiveIndex()
// is the BLAS-local prim id gpu_tlas_hit reports (global when flat).
// OptixInstance::instanceId = index into the uploaded GInstance array.

#ifdef ASTRORAY_OPTIX_TRAVERSAL

#include "astroray/gpu_types.h"
#include "optix_internal.h"
#include "astroray/gpu_optix_traversal.h"

#include <cuda_runtime.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <vector>

namespace astroray {
namespace optix_trav {

namespace {

struct DevBuf {
    CUdeviceptr ptr = 0;
    size_t bytes = 0;
    void release() {
        if (ptr) cudaFree(reinterpret_cast<void*>(ptr));
        ptr = 0; bytes = 0;
    }
};

struct AccelState {
    std::vector<DevBuf> gas;           // one per BLAS (or one for the flat scene)
    std::vector<OptixTraversableHandle> gasHandle;
    DevBuf ias;
    OptixTraversableHandle root = 0;
    bool ready = false;
    std::string error;
    // pkg291 (#875): updatable single-level GAS (buildAccelUpdatable).
    bool updatable = false;
    int updPrims = 0;
    DevBuf updVerts, updTemp;
    // Side buffers (grow-only).
    int capacity = 0;
    HwHitBuffers bufs{};
};

AccelState& S() {
    static AccelState s;
    return s;
}

// Pack prims[start .. start+n) into a non-indexed float3 vertex stream. A
// non-triangle prim becomes a NaN (inactive) triangle so indices stay aligned.
__global__ void packTrianglesKernel(const GPrimitive* prims, const GTriangle* tris,
                                    int start, int n, float3* out)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    const GPrimitive p = prims[start + i];
    if (p.type == GPRIM_TRIANGLE) {
        const GTriangle& t = tris[p.index];
        out[3 * i + 0] = make_float3(t.v0.x, t.v0.y, t.v0.z);
        out[3 * i + 1] = make_float3(t.v1.x, t.v1.y, t.v1.z);
        out[3 * i + 2] = make_float3(t.v2.x, t.v2.y, t.v2.z);
    } else {
        const float q = __int_as_float(0x7fc00000);
        out[3 * i + 0] = make_float3(q, q, q);
        out[3 * i + 1] = make_float3(q, q, q);
        out[3 * i + 2] = make_float3(q, q, q);
    }
}

// Build + compact one acceleration structure from `input` (sample pattern).
OptixTraversableHandle buildAndCompact(OptixDeviceContext ctx, const OptixBuildInput& input,
                                       unsigned int buildFlags, DevBuf& out)
{
    OptixAccelBuildOptions opts = {};
    opts.buildFlags = buildFlags | OPTIX_BUILD_FLAG_ALLOW_COMPACTION;
    opts.operation  = OPTIX_BUILD_OPERATION_BUILD;

    OptixAccelBufferSizes sizes = {};
    ASTRORAY_OPTIX_TRAV_CHECK(optixAccelComputeMemoryUsage(ctx, &opts, &input, 1, &sizes));

    DevBuf temp, full, compactedSize;
    ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(reinterpret_cast<void**>(&temp.ptr), sizes.tempSizeInBytes));
    ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(reinterpret_cast<void**>(&full.ptr), sizes.outputSizeInBytes));
    full.bytes = sizes.outputSizeInBytes;
    ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(reinterpret_cast<void**>(&compactedSize.ptr), sizeof(size_t)));

    OptixAccelEmitDesc emit = {};
    emit.type   = OPTIX_PROPERTY_TYPE_COMPACTED_SIZE;
    emit.result = compactedSize.ptr;

    OptixTraversableHandle handle = 0;
    try {
        ASTRORAY_OPTIX_TRAV_CHECK(optixAccelBuild(ctx, /*stream*/ 0, &opts, &input, 1,
                                                  temp.ptr, sizes.tempSizeInBytes,
                                                  full.ptr, sizes.outputSizeInBytes,
                                                  &handle, &emit, 1));
        size_t compacted = 0;
        ASTRORAY_OPTIX_TRAV_CUDA(cudaMemcpy(&compacted, reinterpret_cast<void*>(compactedSize.ptr),
                                            sizeof(size_t), cudaMemcpyDeviceToHost));
        temp.release();
        compactedSize.release();
        if (compacted > 0 && compacted < sizes.outputSizeInBytes) {
            DevBuf small;
            ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(reinterpret_cast<void**>(&small.ptr), compacted));
            small.bytes = compacted;
            ASTRORAY_OPTIX_TRAV_CHECK(optixAccelCompact(ctx, 0, handle, small.ptr, compacted, &handle));
            ASTRORAY_OPTIX_TRAV_CUDA(cudaStreamSynchronize(0));
            full.release();
            out = small;
        } else {
            out = full;
        }
    } catch (...) {
        temp.release(); full.release(); compactedSize.release();
        throw;
    }
    return handle;
}

OptixTraversableHandle buildTriangleGas(OptixDeviceContext ctx, const GPrimitive* d_prims,
                                        const GTriangle* d_tris, int start, int n, DevBuf& out)
{
    DevBuf verts;
    const size_t vbytes = sizeof(float3) * 3 * static_cast<size_t>(n);
    ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(reinterpret_cast<void**>(&verts.ptr), vbytes));
    const int threads = 256;
    packTrianglesKernel<<<(n + threads - 1) / threads, threads>>>(
        d_prims, d_tris, start, n, reinterpret_cast<float3*>(verts.ptr));
    cudaError_t le = cudaGetLastError();
    if (le != cudaSuccess) { verts.release(); ASTRORAY_OPTIX_TRAV_CUDA(le); }

    const unsigned int flags[1] = { OPTIX_GEOMETRY_FLAG_DISABLE_ANYHIT };
    OptixBuildInput in = {};
    in.type = OPTIX_BUILD_INPUT_TYPE_TRIANGLES;
    in.triangleArray.vertexFormat        = OPTIX_VERTEX_FORMAT_FLOAT3;
    in.triangleArray.vertexStrideInBytes = sizeof(float3);
    in.triangleArray.numVertices         = static_cast<unsigned int>(3 * n);
    in.triangleArray.vertexBuffers       = &verts.ptr;
    in.triangleArray.flags               = flags;
    in.triangleArray.numSbtRecords       = 1;
    OptixTraversableHandle h = 0;
    try {
        h = buildAndCompact(ctx, in, OPTIX_BUILD_FLAG_PREFER_FAST_TRACE, out);
    } catch (...) {
        verts.release();
        throw;
    }
    // The GAS owns its copy of the geometry; the build is complete once the
    // compaction synchronised, so the vertex stream can go.
    verts.release();
    return h;
}

// Build the single-level IAS over the already-built per-BLAS GAS handles from
// the GInstance array (instanceId = index into that array). Returns 0 when no
// instance has geometry. Shared by buildAccel and rebuildInstanceAccel.
OptixTraversableHandle buildIas(OptixDeviceContext ctx, const GInstance* h_instances,
                                int numInstances,
                                const std::vector<OptixTraversableHandle>& gasHandle,
                                int numBlas, DevBuf& out)
{
    std::vector<OptixInstance> oi;
    oi.reserve(numInstances);
    for (int j = 0; j < numInstances; ++j) {
        const GInstance& gi = h_instances[j];
        if (gi.blasIndex < 0 || gi.blasIndex >= numBlas || gasHandle[gi.blasIndex] == 0)
            continue;   // empty mesh: nothing to hit
        OptixInstance x = {};
        // Row-major 3x4 object->world = the top three rows of worldFromObject.
        for (int k = 0; k < 12; ++k) x.transform[k] = gi.worldFromObject.m[k];
        x.instanceId        = static_cast<unsigned int>(j);
        x.sbtOffset         = 0;
        x.visibilityMask    = 255;
        x.flags             = OPTIX_INSTANCE_FLAG_NONE;
        x.traversableHandle = gasHandle[gi.blasIndex];
        oi.push_back(x);
    }
    if (oi.empty()) return 0;
    DevBuf dInst;
    ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(reinterpret_cast<void**>(&dInst.ptr),
                                        sizeof(OptixInstance) * oi.size()));
    OptixTraversableHandle root = 0;
    try {
        ASTRORAY_OPTIX_TRAV_CUDA(cudaMemcpy(reinterpret_cast<void*>(dInst.ptr), oi.data(),
                                            sizeof(OptixInstance) * oi.size(),
                                            cudaMemcpyHostToDevice));
        OptixBuildInput in = {};
        in.type = OPTIX_BUILD_INPUT_TYPE_INSTANCES;
        in.instanceArray.instances    = dInst.ptr;
        in.instanceArray.numInstances = static_cast<unsigned int>(oi.size());
        root = buildAndCompact(ctx, in, OPTIX_BUILD_FLAG_PREFER_FAST_TRACE, out);
    } catch (...) {
        dInst.release();
        throw;
    }
    ASTRORAY_OPTIX_TRAV_CUDA(cudaStreamSynchronize(0));
    dInst.release();
    return root;
}

void releaseAll(AccelState& s) {
    for (auto& g : s.gas) g.release();
    s.gas.clear();
    s.gasHandle.clear();
    s.ias.release();
    s.updVerts.release();
    s.updTemp.release();
    s.updatable = false;
    s.updPrims = 0;
    s.root = 0;
    s.ready = false;
    setRoot(0, 0);
}

// pkg291: triangle build input over a packed non-indexed vertex stream (the
// same input buildTriangleGas uses).
OptixBuildInput triangleInput(const CUdeviceptr* verts, int n, const unsigned int* flags) {
    OptixBuildInput in = {};
    in.type = OPTIX_BUILD_INPUT_TYPE_TRIANGLES;
    in.triangleArray.vertexFormat        = OPTIX_VERTEX_FORMAT_FLOAT3;
    in.triangleArray.vertexStrideInBytes = sizeof(float3);
    in.triangleArray.numVertices         = static_cast<unsigned int>(3 * n);
    in.triangleArray.vertexBuffers       = verts;
    in.triangleArray.flags               = flags;
    in.triangleArray.numSbtRecords       = 1;
    return in;
}

void packInto(const GPrimitive* d_prims, const GTriangle* d_tris, int n, DevBuf& verts) {
    const int threads = 256;
    packTrianglesKernel<<<(n + threads - 1) / threads, threads>>>(
        d_prims, d_tris, 0, n, reinterpret_cast<float3*>(verts.ptr));
    ASTRORAY_OPTIX_TRAV_CUDA(cudaGetLastError());
}

constexpr unsigned int kUpdatableFlags =
    OPTIX_BUILD_FLAG_PREFER_FAST_TRACE | OPTIX_BUILD_FLAG_ALLOW_UPDATE;

}  // namespace

bool buildAccel(const GPrimitive* d_prims, int numPrims, const GTriangle* d_tris,
                const GInstance* h_instances, int numInstances,
                const GBLAS* h_blas, int numBlas)
{
    AccelState& s = S();
    releaseAll(s);
    s.error.clear();
    if (!available()) { s.error = lastError(); return false; }
    if (numPrims <= 0 || d_prims == nullptr || d_tris == nullptr) {
        s.error = "empty scene";
        return false;
    }
    OptixDeviceContext ctx = context();
    try {
        if (numInstances <= 0 || h_instances == nullptr || numBlas <= 0) {
            // Single level: one GAS, primitive index == global prim id.
            s.gas.resize(1);
            s.gasHandle.push_back(buildTriangleGas(ctx, d_prims, d_tris, 0, numPrims, s.gas[0]));
            s.root = s.gasHandle[0];
            setRoot(s.root, 0);
        } else {
            // BLAS prim ranges: [primOffset, next larger primOffset or numPrims).
            std::vector<int> offsets;
            for (int b = 0; b < numBlas; ++b) offsets.push_back(h_blas[b].primOffset);
            std::sort(offsets.begin(), offsets.end());
            offsets.erase(std::unique(offsets.begin(), offsets.end()), offsets.end());
            s.gas.resize(numBlas);
            s.gasHandle.assign(numBlas, 0);
            for (int b = 0; b < numBlas; ++b) {
                const int start = h_blas[b].primOffset;
                auto it = std::upper_bound(offsets.begin(), offsets.end(), start);
                const int end = (it == offsets.end()) ? numPrims : *it;
                if (end > start)
                    s.gasHandle[b] = buildTriangleGas(ctx, d_prims, d_tris, start, end - start, s.gas[b]);
            }
            s.root = buildIas(ctx, h_instances, numInstances, s.gasHandle, numBlas, s.ias);
            if (s.root == 0) throw std::runtime_error("[pkg299] no instances with geometry");
            setRoot(s.root, 1);
        }
        s.ready = true;
    } catch (const std::exception& e) {
        s.error = e.what();
        std::fprintf(stderr, "%s — GPU traversal falls back to the software BVH\n", e.what());
        (void)cudaGetLastError();
        releaseAll(s);
        s.error = e.what();
        return false;
    }
    return true;
}

// #1001: transform-only edit of pkg114 instances. Every GAS (and so every BLAS
// vertex stream) is kept; only the IAS is rebuilt from the new transforms.
// OptiX 9.1 Programming Guide, "Acceleration structures" / "Dynamic updates":
// an instance AS is cheap to rebuild (it never touches triangle data), and the
// instance count must not change (checked by the caller, as the instance->BLAS
// map is). On failure the whole accel is released (it would be stale against the
// new transforms) and the caller falls back to the software BVH.
bool rebuildInstanceAccel(const GInstance* h_instances, int numInstances) {
    AccelState& s = S();
    if (!s.ready || s.updatable || s.gas.empty() || s.ias.ptr == 0 ||
        h_instances == nullptr || numInstances <= 0)
        return false;
    try {
        DevBuf fresh;
        OptixTraversableHandle root = 0;
        try {
            root = buildIas(context(), h_instances, numInstances, s.gasHandle,
                            static_cast<int>(s.gasHandle.size()), fresh);
        } catch (...) { fresh.release(); throw; }
        if (root == 0) { fresh.release(); return false; }
        s.ias.release();
        s.ias = fresh;
        s.root = root;
        setRoot(s.root, 1);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "%s -- IAS rebuild failed; software fallback\n", e.what());
        (void)cudaGetLastError();
        releaseAll(s);
        s.error = e.what();
        return false;
    }
    return true;
}

// pkg291 (#875): updatable single-level GAS. OptiX 9.1 Programming Guide,
// "Dynamic updates": build with OPTIX_BUILD_FLAG_ALLOW_UPDATE, then refit with
// OPTIX_BUILD_OPERATION_UPDATE on the same input layout (vertex positions may
// change, topology may not) into the same output buffer, using
// tempUpdateSizeInBytes of scratch. Not compacted (kept simple; viewport only).
bool buildAccelUpdatable(const GPrimitive* d_prims, int numPrims, const GTriangle* d_tris) {
    AccelState& s = S();
    releaseAll(s);
    s.error.clear();
    if (!available()) { s.error = lastError(); return false; }
    if (numPrims <= 0 || d_prims == nullptr || d_tris == nullptr) {
        s.error = "empty scene";
        return false;
    }
    OptixDeviceContext ctx = context();
    DevBuf temp, out;
    try {
        ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(reinterpret_cast<void**>(&s.updVerts.ptr),
                                            sizeof(float3) * 3 * static_cast<size_t>(numPrims)));
        s.updVerts.bytes = sizeof(float3) * 3 * static_cast<size_t>(numPrims);
        packInto(d_prims, d_tris, numPrims, s.updVerts);
        const unsigned int flags[1] = { OPTIX_GEOMETRY_FLAG_DISABLE_ANYHIT };
        OptixBuildInput in = triangleInput(&s.updVerts.ptr, numPrims, flags);
        OptixAccelBuildOptions opts = {};
        opts.buildFlags = kUpdatableFlags;
        opts.operation  = OPTIX_BUILD_OPERATION_BUILD;
        OptixAccelBufferSizes sizes = {};
        ASTRORAY_OPTIX_TRAV_CHECK(optixAccelComputeMemoryUsage(ctx, &opts, &in, 1, &sizes));
        ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(reinterpret_cast<void**>(&temp.ptr), sizes.tempSizeInBytes));
        ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(reinterpret_cast<void**>(&out.ptr), sizes.outputSizeInBytes));
        out.bytes = sizes.outputSizeInBytes;
        ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(reinterpret_cast<void**>(&s.updTemp.ptr),
                                            std::max<size_t>(sizes.tempUpdateSizeInBytes, 1)));
        s.updTemp.bytes = sizes.tempUpdateSizeInBytes;
        OptixTraversableHandle h = 0;
        ASTRORAY_OPTIX_TRAV_CHECK(optixAccelBuild(ctx, 0, &opts, &in, 1, temp.ptr,
                                                  sizes.tempSizeInBytes, out.ptr,
                                                  sizes.outputSizeInBytes, &h, nullptr, 0));
        ASTRORAY_OPTIX_TRAV_CUDA(cudaStreamSynchronize(0));
        temp.release();
        s.gas.assign(1, out);
        s.gasHandle.assign(1, h);
        s.root = h;
        setRoot(s.root, 0);
        s.updatable = true;
        s.updPrims = numPrims;
        s.ready = true;
    } catch (const std::exception& e) {
        temp.release(); out.release();
        std::fprintf(stderr, "%s — GPU traversal falls back to the software BVH\n", e.what());
        (void)cudaGetLastError();
        releaseAll(s);
        s.error = e.what();
        return false;
    }
    return true;
}

bool refitAccel(const GPrimitive* d_prims, int numPrims, const GTriangle* d_tris) {
    AccelState& s = S();
    if (!s.ready || !s.updatable || numPrims != s.updPrims || s.gas.size() != 1) return false;
    try {
        packInto(d_prims, d_tris, numPrims, s.updVerts);
        const unsigned int flags[1] = { OPTIX_GEOMETRY_FLAG_DISABLE_ANYHIT };
        OptixBuildInput in = triangleInput(&s.updVerts.ptr, numPrims, flags);
        OptixAccelBuildOptions opts = {};
        opts.buildFlags = kUpdatableFlags;
        opts.operation  = OPTIX_BUILD_OPERATION_UPDATE;
        OptixTraversableHandle h = 0;
        ASTRORAY_OPTIX_TRAV_CHECK(optixAccelBuild(context(), 0, &opts, &in, 1, s.updTemp.ptr,
                                                  s.updTemp.bytes, s.gas[0].ptr, s.gas[0].bytes,
                                                  &h, nullptr, 0));
        s.gasHandle[0] = h;
        s.root = h;
        setRoot(s.root, 0);
    } catch (const std::exception& e) {
        std::fprintf(stderr, "%s — OptiX refit failed; rebuilding\n", e.what());
        (void)cudaGetLastError();
        releaseAll(s);
        return false;
    }
    return true;
}

bool accelUpdatable() { return S().ready && S().updatable; }

bool accelReady() { return S().ready; }

void releaseAccel() { releaseAll(S()); }

HwHitBuffers ensureBuffers(int capacity)
{
    AccelState& s = S();
    if (capacity > s.capacity) {
        cudaFree(s.bufs.t); cudaFree(s.bufs.prim); cudaFree(s.bufs.u);
        cudaFree(s.bufs.v); cudaFree(s.bufs.inst); cudaFree(s.bufs.occluded);
        s.bufs = HwHitBuffers{};
        s.capacity = 0;
        const size_t n = static_cast<size_t>(capacity);
        ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(&s.bufs.t, n * sizeof(float)));
        ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(&s.bufs.prim, n * sizeof(int)));
        ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(&s.bufs.u, n * sizeof(float)));
        ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(&s.bufs.v, n * sizeof(float)));
        ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(&s.bufs.inst, n * sizeof(int)));
        ASTRORAY_OPTIX_TRAV_CUDA(cudaMalloc(&s.bufs.occluded, n * sizeof(int)));
        s.capacity = capacity;
    }
    return s.bufs;
}

}  // namespace optix_trav
}  // namespace astroray

#endif  // ASTRORAY_OPTIX_TRAVERSAL

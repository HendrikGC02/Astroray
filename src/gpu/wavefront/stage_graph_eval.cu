// stage_graph_eval.cu - pkg314: the dedicated graph-evaluation kernel.
//
// Plan of record: .astroray_plan/docs/shader-graph-architecture-2026-10-03.md
// (option B, Phase 2). Dynamic value programs (include/astroray/shader_graph.h)
// run HERE, once per bounce, before the shade launch, over the same per-bucket
// shade queues; the interpreter is compiled once in this TU and never inlined
// into shadePathSlot or the fleet kernels. Each hit whose material carries graph
// programs writes its results to a per-path output buffer
// ([k*outStride + pathIdx], k 0..3 = Roughness/Metallic/Transmission/IOR, 4..6 =
// base colour; NaN = an input missed at this hit, the shade keeps the constant).
// Only the <HasProgram=true> shade variants read it (GWavefrontProgramBinding).
//
// Scratch: persistent threads. The launch has exactly `batch` threads; thread t
// keeps program slot s at scratch[s*batch + t] (coalesced across a warp) and
// strides over every queued hit, so scratch is batch x maxSlots GVec3 however
// many hits a round carries (allocated from the scene's largest program,
// gpu_wavefront_snapshot.cu). Nothing is added to GPUWavefrontHitBuffers and
// GMaterial is unchanged.
#include "stage_advance_device.cuh"
#include "astroray/shader_graph.h"
#include <math_constants.h>  // CUDART_NAN_F

namespace astroray::wavefront {

__constant__ GWavefrontGraphBinding c_wfGraphBinding;

void setWavefrontGraphBinding(const GWavefrontGraphBinding& binding)
{
    cudaMemcpyToSymbol(c_wfGraphBinding, &binding, sizeof(GWavefrontGraphBinding));
}

namespace {

// Active-layer UV at a triangle hit: barycentrics recomputed from the hit point
// (Ericson, Real-Time Collision Detection §3.4), as gpu_progInputTexel's 2-D
// branch (stage_advance_device.cuh). false on a non-triangle / UV-less hit.
__device__ bool graphHitUV(GVec3 point, int primId, const GPrimitive* prims,
                           const GTriangle* tris, float& u, float& v)
{
    if (!(primId >= 0 && prims[primId].type == GPRIM_TRIANGLE)) return false;
    const GTriangle& t = tris[prims[primId].index];
    if (!t.hasUV) return false;
    const GVec3 e1 = t.v1 - t.v0, e2 = t.v2 - t.v0, ep = point - t.v0;
    const float d00 = e1.dot(e1), d01 = e1.dot(e2), d11 = e2.dot(e2);
    const float d20 = ep.dot(e1), d21 = ep.dot(e2);
    const float denom = d00 * d11 - d01 * d01;
    if (fabsf(denom) <= 1e-20f) return false;
    const float b1 = (d11 * d20 - d01 * d21) / denom;
    const float b2 = (d00 * d21 - d01 * d20) / denom;
    const float b0 = 1.0f - b1 - b2;
    u = b0 * t.uv0.x + b1 * t.uv1.x + b2 * t.uv2.x;
    v = b0 * t.uv0.y + b1 * t.uv1.y + b2 * t.uv2.y;
    return true;
}

// Texture / geometry services of graph_eval on the GPU (CPU twin:
// GraphProgramTexture::CpuSvc, include/advanced_features.h).
struct GpuGraphSvc {
    GVec3 point;
    int primId;
    const GPrimitive* prims;
    const GTriangle* tris;
    astroray::svm::SvmShading sh;

    // Input at its own coordinate contract: the descriptor carries the input's
    // Mapping (image), its per-hit evaluator (#1007 procId) or its baked
    // coordinate domain (procedural, pkg190/#994).
    __device__ bool tex_native(uint32_t ref, GVec3& o) const {
        const int texId = c_wfGraphBinding.texRefs[ref];
        if (texId < 0) return false;
        const GProgInputTexel s = gpu_progInputEval(point, primId, prims, tris, texId);
        o = s.c;
        return s.ok;
    }
    // Image at a computed uv (the descriptor has no Mapping; scene_upload checks).
    __device__ bool tex_coord(uint32_t ref, const GVec3& c, GVec3& o) const {
        const int texId = c_wfGraphBinding.texRefs[ref];
        if (texId < 0) return false;
        o = gpu_sampleImageTexture(c_wfTexBinding.textures[texId], c_wfTexBinding.texelBuf,
                                   c.x, c.y);
        return true;
    }
    __device__ bool geom(unsigned char, GVec3& o) const {   // GEOM_UV
        float u, v;
        if (!graphHitUV(point, primId, prims, tris, u, v)) return false;
        o = GVec3(u, v, 0.0f);
        return true;
    }
    __device__ const astroray::svm::SvmShading& shading() const { return sh; }
};

}  // namespace

__global__ void stageGraphEvalKernel(
    __grid_constant__ const GPUWavefrontState state,
    __grid_constant__ const GPUWavefrontHitBuffers hitBufs,
    const int* shade_queues, const int* shade_counts, int capacity,
    const GPrimitive* prims, const GTriangle* tris)
{
    using namespace astroray::sgraph;
    const GWavefrontGraphBinding& g = c_wfGraphBinding;
    const int t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= g.batch) return;
    const GraphArenas ar{g.instrs, g.consts, g.tables, g.tableData};
    GVec3* regs = g.scratch + t;
    for (int bucket = 0; bucket < G_WF_NUM_MAT_TYPES; ++bucket) {
        const int count = shade_counts[bucket];
        for (int pos = t; pos < count; pos += g.batch) {
            const int idx = shade_queues[bucket * capacity + pos];
            const int* slots = g.matGraphProg + hitBufs.hit_material_id[idx] * GRAPH_MAT_SLOTS;
            int progs[GRAPH_MAT_SLOTS];
            bool any = false;
            for (int s = 0; s < GRAPH_MAT_SLOTS; ++s) {
                progs[s] = slots[s];
                any |= progs[s] >= 0;
            }
            if (!any) continue;
            GpuGraphSvc svc;
            svc.point = GVec3(hitBufs.hit_point_x[idx], hitBufs.hit_point_y[idx],
                              hitBufs.hit_point_z[idx]);
            svc.primId = hitBufs.hit_prim_id[idx];
            svc.prims = prims;
            svc.tris = tris;
            // #989 shading context (CPU twin: GraphProgramTexture::valueAtHit):
            // cos(view, N) with the interpolated shading normal of the parked hit.
            const GVec3 wo = GVec3(-state.ray_direction_x[idx], -state.ray_direction_y[idx],
                                   -state.ray_direction_z[idx]).normalized();
            const GVec3 n(hitBufs.hit_normal_x[idx], hitBufs.hit_normal_y[idx],
                          hitBufs.hit_normal_z[idx]);
            svc.sh.cosI = wo.dot(n);
            svc.sh.backfacing = hitBufs.hit_front_face[idx] != 0 ? 0.0f : 1.0f;
            for (int s = 0; s < GRAPH_MAT_SLOTS; ++s) {
                if (progs[s] < 0) continue;
                GVec3 r;
                const bool ok = graph_eval(g.programs[progs[s]], ar, regs, g.batch, svc, r);
                if (s < GRAPH_SLOT_BASE_COLOR) {
                    g.out[s * g.outStride + idx] = ok ? r.x : CUDART_NAN_F;
                } else {
                    g.out[4 * g.outStride + idx] = ok ? r.x : CUDART_NAN_F;
                    g.out[5 * g.outStride + idx] = ok ? r.y : CUDART_NAN_F;
                    g.out[6 * g.outStride + idx] = ok ? r.z : CUDART_NAN_F;
                }
            }
        }
    }
}

void launchStageGraphEval(GPUWavefrontState& state, GPUWavefrontHitBuffers& hitBufs,
                          const int* d_shade_queues, const int* d_shade_counts,
                          int capacity, const GPrimitive* d_prims,
                          const GTriangle* d_tris, int batch)
{
    if (capacity <= 0 || batch <= 0) return;
    const int threads = 256;
    const int blocks = (batch + threads - 1) / threads;
    astroray::gpu_profile::ScopedTimer _t("wavefront_stage_graph_eval",
                                          (const void*)stageGraphEvalKernel, blocks, threads);
    stageGraphEvalKernel<<<blocks, threads>>>(state, hitBufs, d_shade_queues, d_shade_counts,
                                              capacity, d_prims, d_tris);
    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        std::fprintf(stderr, "stage_graph_eval launch error: %s\n", cudaGetErrorString(err));
        throw std::runtime_error(cudaGetErrorString(err));
    }
}

}  // namespace astroray::wavefront

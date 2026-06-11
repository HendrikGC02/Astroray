from pathlib import Path

# ---- A. stage_advance.cu: fwd decls, shadePathSlot deferral, shadow kernel.
p = Path('src/gpu/wavefront/stage_advance.cu')
t = p.read_text(encoding='utf-8')

old = """// Non-inline XYZ wrapper exported by multiwavelength_kernel.cu (Session N+6)"""
new = """// pkg55-B' shadow stage: the factored NEE thirds from
// multiwavelength_kernel.cu (rdc-linked; blueprint
// pkg55-nee-shadow-stage-blueprint.md). One generator of the NEE math.
__device__ GNEESample gpu_nee_sample(
    const GHitRecord& rec,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GLight*   lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    curandState*      rng);

__device__ GNEEOcclusion gpu_nee_occlude(
    const GNEESample& s,
    const GTLASNode*  tlas,
    const GInstance*  instances,
    const GBLAS*      blas,
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    float             time,
    const GVec3*      motionVerts);

__device__ GSampledSpectrum gpu_nee_resolve(
    const GHitRecord& rec, const GVec3& wo,
    const GSampledWavelengths& lambdas,
    const ::GMaterial* materials,
    const GNEESample& s,
    bool              lightFront);

// Non-inline XYZ wrapper exported by multiwavelength_kernel.cu (Session N+6)"""
assert old in t, 'fwd anchor'
t = t.replace(old, new, 1)

# NEE park layout constants near the bucket constant.
old = """// GMAT_LAMBERTIAN=0 .. GMAT_CLOSURE_GRAPH=6 (gpu_types.h GMaterialType).
constexpr int G_WF_NUM_MAT_TYPES = 7;"""
new = """// GMAT_LAMBERTIAN=0 .. GMAT_CLOSURE_GRAPH=6 (gpu_types.h GMaterialType).
constexpr int G_WF_NUM_MAT_TYPES = 7;

// pkg55-B' shadow stage: NEE park SoA layout (field-major: field*capacity+idx).
// Float fields: 0-2 origin, 3-5 wi, 6 maxDist, 7 lightPdf, 8-10 wo,
// 11-14 throughput-at-NEE. Int fields: 0 lightMatId, 1 isSphere.
constexpr int G_WF_NEE_FLOATS = 15;
constexpr int G_WF_NEE_INTS   = 2;"""
assert old in t, 'const anchor'
t = t.replace(old, new, 1)

# shadePathSlot: add deferral params + replace the NEE block.
old = """__device__ bool shadePathSlot(
    int idx,
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    int               max_depth)
{"""
new = """// nee_f/nee_i/shadow_queue/shadow_count non-null => DEFER the NEE shadow
// trace + resolve to the dedicated shadow stage (park the sample + wo +
// throughput, enqueue the slot). Null => immediate occlude+resolve inline
// (the flat/dense schedulings keep their original single-kernel behavior).
__device__ bool shadePathSlot(
    int idx,
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    int               max_depth,
    float*            nee_f, int* nee_i,
    int*              shadow_queue, int* shadow_count, int nee_capacity)
{"""
assert old in t, 'shade sig'
t = t.replace(old, new, 1)

old = """    // ---- NEE (skipped on delta lobes). CPU draws light_seed -> mt19937;
    // GPU twin draws the same dimension -> local curandState (see header).
    // The light_seed draw is gated EXACTLY like the CPU (path_kernel.cpp:230,
    // !isDelta && !lights.empty()) so the RNG dimension stream stays keyed
    // identically even when all lights have zero power (pkg98 N+6 review
    // finding); only the sampling CALL is guarded on totalLightPower — the
    // CPU's lights.sample returns pdf<=0 there and contributes nothing.
    if (!rec.isDelta && numLights > 0) {
        uint32_t light_seed = rng.UniformUInt32();
        if (totalLightPower > 0.f) {
            curandState light_state;
            curand_init((unsigned long long)light_seed, 0, 0, &light_state);
            GSampledSpectrum nee = sampleDirectSpectralMW(
                rec, wo, lambdas,
                /*tlas=*/nullptr, /*instances=*/nullptr, /*blas=*/nullptr,
                bvhNodes, prims, tris, spheres, materials,
                lights, numLights, totalLightPower, lightTree,
                /*rayTime=*/0.0f, /*motionVerts=*/nullptr,
                &light_state);
            color += throughput * nee;
        }
    }"""
new = """    // ---- NEE (skipped on delta lobes). CPU draws light_seed -> mt19937;
    // GPU twin draws the same dimension -> local curandState (see header).
    // The light_seed draw is gated EXACTLY like the CPU (path_kernel.cpp:230,
    // !isDelta && !lights.empty()) so the RNG dimension stream stays keyed
    // identically even when all lights have zero power (pkg98 N+6 review
    // finding); only the sampling CALL is guarded on totalLightPower — the
    // CPU's lights.sample returns pdf<=0 there and contributes nothing.
    if (!rec.isDelta && numLights > 0) {
        uint32_t light_seed = rng.UniformUInt32();
        if (totalLightPower > 0.f) {
            curandState light_state;
            curand_init((unsigned long long)light_seed, 0, 0, &light_state);
            GNEESample s = gpu_nee_sample(rec, prims, tris, spheres,
                                          lights, numLights, totalLightPower,
                                          lightTree, &light_state);
            if (s.valid) {
                if (nee_f != nullptr) {
                    // Defer: park sample + wo + throughput-at-NEE, enqueue.
                    nee_f[ 0 * nee_capacity + idx] = s.origin.x;
                    nee_f[ 1 * nee_capacity + idx] = s.origin.y;
                    nee_f[ 2 * nee_capacity + idx] = s.origin.z;
                    nee_f[ 3 * nee_capacity + idx] = s.wi.x;
                    nee_f[ 4 * nee_capacity + idx] = s.wi.y;
                    nee_f[ 5 * nee_capacity + idx] = s.wi.z;
                    nee_f[ 6 * nee_capacity + idx] = s.maxDist;
                    nee_f[ 7 * nee_capacity + idx] = s.lightPdf;
                    nee_f[ 8 * nee_capacity + idx] = wo.x;
                    nee_f[ 9 * nee_capacity + idx] = wo.y;
                    nee_f[10 * nee_capacity + idx] = wo.z;
                    nee_f[11 * nee_capacity + idx] = throughput.v[0];
                    nee_f[12 * nee_capacity + idx] = throughput.v[1];
                    nee_f[13 * nee_capacity + idx] = throughput.v[2];
                    nee_f[14 * nee_capacity + idx] = throughput.v[3];
                    nee_i[ 0 * nee_capacity + idx] = s.lightMatId;
                    nee_i[ 1 * nee_capacity + idx] = s.isSphere;
                    int qslot = atomicAdd(shadow_count, 1);
                    shadow_queue[qslot] = idx;
                } else {
                    // Immediate (flat/dense schedulings): original behavior.
                    GNEEOcclusion occ = gpu_nee_occlude(
                        s, /*tlas=*/nullptr, /*instances=*/nullptr,
                        /*blas=*/nullptr, bvhNodes, prims, tris, spheres,
                        /*time=*/0.0f, /*motionVerts=*/nullptr);
                    if (!occ.occluded) {
                        GSampledSpectrum nee = gpu_nee_resolve(
                            rec, wo, lambdas, materials, s,
                            s.isSphere ? (occ.frontFace != 0) : true);
                        color += throughput * nee;
                    }
                }
            }
        }
    }"""
assert old in t, 'nee block'
t = t.replace(old, new, 1)

# advancePathSlot composition + bucketed shade kernel call sites: pass nulls
# (immediate) for flat/dense; the bucketed kernel gains the defer params.
old = """    return shadePathSlot(idx, state, hitBufs, bvhNodes, prims, tris, spheres,
                         materials, lights, numLights, totalLightPower,
                         lightTree, max_depth);
}"""
new = """    return shadePathSlot(idx, state, hitBufs, bvhNodes, prims, tris, spheres,
                         materials, lights, numLights, totalLightPower,
                         lightTree, max_depth,
                         /*nee_f=*/nullptr, /*nee_i=*/nullptr,
                         /*shadow_queue=*/nullptr, /*shadow_count=*/nullptr,
                         /*nee_capacity=*/0);
}"""
assert old in t, 'compose call'
t = t.replace(old, new, 1)

old = """__global__ void stageShadeBucketedKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const int* shade_queues, const int* shade_counts, int capacity,
    int* queue_out, int* count_out,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    int               max_depth)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    int bucket = i / capacity;
    int pos    = i - bucket * capacity;
    if (bucket >= G_WF_NUM_MAT_TYPES) return;
    if (pos >= shade_counts[bucket]) return;
    int idx = shade_queues[bucket * capacity + pos];
    bool alive = shadePathSlot(idx, state, hitBufs, bvhNodes, prims, tris,
                               spheres, materials, lights, numLights,
                               totalLightPower, lightTree, max_depth);"""
new = """__global__ void stageShadeBucketedKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const int* shade_queues, const int* shade_counts, int capacity,
    int* queue_out, int* count_out,
    float* nee_f, int* nee_i, int* shadow_queue, int* shadow_count,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    int               max_depth)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    int bucket = i / capacity;
    int pos    = i - bucket * capacity;
    if (bucket >= G_WF_NUM_MAT_TYPES) return;
    if (pos >= shade_counts[bucket]) return;
    int idx = shade_queues[bucket * capacity + pos];
    bool alive = shadePathSlot(idx, state, hitBufs, bvhNodes, prims, tris,
                               spheres, materials, lights, numLights,
                               totalLightPower, lightTree, max_depth,
                               nee_f, nee_i, shadow_queue, shadow_count,
                               capacity);"""
assert old in t, 'bucketed kernel'
t = t.replace(old, new, 1)

# Shadow kernel after the bucketed kernel.
old = """// Fills queue with 0..n-1 and *count = n (bounce-0 population)."""
new = """// ---------------------------------------------------------------------------
// pkg55-B' shadow stage: lean occlusion + resolve over the parked NEE
// samples (Laine 2013's dedicated shadow-ray stage). No sampling RNG, no
// BSDF-sampling dispatch — just the trace + the lazy material evals the
// original ran post-trace. Contribution adds into color (one entry per
// slot per pass: non-atomic).
// ---------------------------------------------------------------------------
__global__ void stageShadowKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const float* nee_f, const int* nee_i,
    const int* shadow_queue, const int* shadow_count, int nee_capacity,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= *shadow_count) return;
    int idx = shadow_queue[i];

    GNEESample s{};
    s.origin     = GVec3(nee_f[0 * nee_capacity + idx],
                         nee_f[1 * nee_capacity + idx],
                         nee_f[2 * nee_capacity + idx]);
    s.wi         = GVec3(nee_f[3 * nee_capacity + idx],
                         nee_f[4 * nee_capacity + idx],
                         nee_f[5 * nee_capacity + idx]);
    s.maxDist    = nee_f[6 * nee_capacity + idx];
    s.lightPdf   = nee_f[7 * nee_capacity + idx];
    s.lightMatId = nee_i[0 * nee_capacity + idx];
    s.isSphere   = nee_i[1 * nee_capacity + idx];
    s.valid      = 1;

    GNEEOcclusion occ = gpu_nee_occlude(
        s, /*tlas=*/nullptr, /*instances=*/nullptr, /*blas=*/nullptr,
        bvhNodes, prims, tris, spheres, /*time=*/0.0f, /*motionVerts=*/nullptr);
    if (occ.occluded) return;

    // Reconstruct rec (hitBufs is untouched until the next pass's
    // intersect), wo and lambdas for the lazy resolve.
    GHitRecord rec;
    rec.t          = hitBufs.hit_t[idx];
    rec.point      = GVec3(hitBufs.hit_point_x[idx], hitBufs.hit_point_y[idx],
                           hitBufs.hit_point_z[idx]);
    rec.normal     = GVec3(hitBufs.hit_normal_x[idx], hitBufs.hit_normal_y[idx],
                           hitBufs.hit_normal_z[idx]);
    rec.tangent    = GVec3(hitBufs.hit_tangent_x[idx], hitBufs.hit_tangent_y[idx],
                           hitBufs.hit_tangent_z[idx]);
    rec.bitangent  = GVec3(hitBufs.hit_bitangent_x[idx], hitBufs.hit_bitangent_y[idx],
                           hitBufs.hit_bitangent_z[idx]);
    rec.materialId = hitBufs.hit_material_id[idx];
    rec.primId     = hitBufs.hit_prim_id[idx];
    rec.frontFace  = hitBufs.hit_front_face[idx] != 0;
    rec.isDelta    = hitBufs.hit_is_delta[idx] != 0;

    GVec3 wo(nee_f[ 8 * nee_capacity + idx],
             nee_f[ 9 * nee_capacity + idx],
             nee_f[10 * nee_capacity + idx]);

    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[idx];
    lambdas.lambda[1] = state.lambda_1[idx];
    lambdas.lambda[2] = state.lambda_2[idx];
    lambdas.lambda[3] = state.lambda_3[idx];
    lambdas.pdf[0] = state.lambda_pdf_0[idx];
    lambdas.pdf[1] = state.lambda_pdf_1[idx];
    lambdas.pdf[2] = state.lambda_pdf_2[idx];
    lambdas.pdf[3] = state.lambda_pdf_3[idx];

    GSampledSpectrum nee = gpu_nee_resolve(
        rec, wo, lambdas, materials, s,
        s.isSphere ? (occ.frontFace != 0) : true);

    state.color_0[idx] += nee_f[11 * nee_capacity + idx] * nee.v[0];
    state.color_1[idx] += nee_f[12 * nee_capacity + idx] * nee.v[1];
    state.color_2[idx] += nee_f[13 * nee_capacity + idx] * nee.v[2];
    state.color_3[idx] += nee_f[14 * nee_capacity + idx] * nee.v[3];
}

// Fills queue with 0..n-1 and *count = n (bounce-0 population)."""
assert old in t, 'shadow kernel anchor'
t = t.replace(old, new, 1)

# Launchers: bucketed-shade launcher signature + call + new shadow launcher.
old = """void launchStageShadeBucketed(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const int* d_shade_queues, const int* d_shade_counts, int capacity,
    int* d_queue_out, int* d_count_out,
    const GBVHNode*   d_bvhNodes,"""
new = """void launchStageShadeBucketed(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const int* d_shade_queues, const int* d_shade_counts, int capacity,
    int* d_queue_out, int* d_count_out,
    float* d_nee_f, int* d_nee_i, int* d_shadow_queue, int* d_shadow_count,
    const GBVHNode*   d_bvhNodes,"""
assert old in t, 'shade launcher sig'
t = t.replace(old, new, 1)
old = """        stageShadeBucketedKernel<<<blocks, threads>>>(
            state, hitBufs, d_shade_queues, d_shade_counts, capacity,
            d_queue_out, d_count_out,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
            d_lights, num_lights, total_light_power, lightTree, max_depth);"""
new = """        stageShadeBucketedKernel<<<blocks, threads>>>(
            state, hitBufs, d_shade_queues, d_shade_counts, capacity,
            d_queue_out, d_count_out,
            d_nee_f, d_nee_i, d_shadow_queue, d_shadow_count,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
            d_lights, num_lights, total_light_power, lightTree, max_depth);"""
assert old in t, 'shade launcher call'
t = t.replace(old, new, 1)

anchor = "\n}  // namespace astroray::wavefront"
shadow_launcher = """
void launchStageShadow(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const float* d_nee_f, const int* d_nee_i,
    const int* d_shadow_queue, const int* d_shadow_count, int nee_capacity,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const ::GMaterial* d_materials)
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_shadow_n7",
            (const void*)stageShadowKernel, blocks, threads);
        stageShadowKernel<<<blocks, threads>>>(
            state, hitBufs, d_nee_f, d_nee_i,
            d_shadow_queue, d_shadow_count, nee_capacity,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_materials);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_shadow launch error: %s\\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

}  // namespace astroray::wavefront"""
assert t.count(anchor) == 1, 'ns anchor'
t = t.replace(anchor, shadow_launcher, 1)
p.write_text(t, encoding='utf-8')
print('stage_advance shadow OK')

# ---- B. Header decls.
h = Path('include/astroray/gpu_wavefront_state.h')
t = h.read_text(encoding='utf-8')
old = """void launchStageShadeBucketed(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const int* d_shade_queues, const int* d_shade_counts, int capacity,
    int* d_queue_out, int* d_count_out,
    const GBVHNode*   d_bvhNodes,"""
new = """void launchStageShadeBucketed(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const int* d_shade_queues, const int* d_shade_counts, int capacity,
    int* d_queue_out, int* d_count_out,
    float* d_nee_f, int* d_nee_i, int* d_shadow_queue, int* d_shadow_count,
    const GBVHNode*   d_bvhNodes,"""
assert old in t, 'hdr shade sig'
t = t.replace(old, new, 1)

old = """// Session N+7 part 4: path regeneration"""
new = """// pkg55-B' shadow stage: lean occlusion + lazy resolve over the NEE
// samples parked by the deferring bucketed shade. nee_f = 15 floats/slot
// (field-major), nee_i = 2 ints/slot; see stage_advance.cu layout consts.
void launchStageShadow(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const float* d_nee_f, const int* d_nee_i,
    const int* d_shadow_queue, const int* d_shadow_count, int nee_capacity,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const ::GMaterial* d_materials);

// Session N+7 part 4: path regeneration"""
assert old in t, 'hdr shadow anchor'
t = t.replace(old, new, 1)
h.write_text(t, encoding='utf-8')
print('header OK')

# ---- C. Driver: alloc NEE park buffers + shadow queue; wire pass order.
d = Path('src/gpu/wavefront/gpu_wavefront_snapshot.cu')
t = d.read_text(encoding='utf-8')

old = """        int* d_shadeQueues = nullptr;
        int* d_shadeCounts = nullptr;"""
new = """        int* d_shadeQueues = nullptr;
        int* d_shadeCounts = nullptr;
        float* d_neeF = nullptr;      // 15 floats/slot, field-major
        int*   d_neeI = nullptr;      // 2 ints/slot
        int*   d_shadowQueue = nullptr;
        int*   d_shadowCount = nullptr;"""
assert old in t, 'drv decls'
t = t.replace(old, new, 1)

old = """        if (qe == cudaSuccess)
            qe = cudaMalloc(reinterpret_cast<void**>(&d_shadeCounts),
                            kNumMatTypes * sizeof(int));
        if (qe != cudaSuccess) {
            if (d_shadeQueues) cudaFree(d_shadeQueues);
            if (d_shadeCounts) cudaFree(d_shadeCounts);
            qfree();
            freeGPUWavefrontHitBuffers(hitBufs);
            cudaFree(d_accum);
            throw std::runtime_error(cudaGetErrorString(qe));
        }"""
new = """        if (qe == cudaSuccess)
            qe = cudaMalloc(reinterpret_cast<void**>(&d_shadeCounts),
                            kNumMatTypes * sizeof(int));
        if (qe == cudaSuccess)
            qe = cudaMalloc(reinterpret_cast<void**>(&d_neeF),
                            size_t(15) * total_paths * sizeof(float));
        if (qe == cudaSuccess)
            qe = cudaMalloc(reinterpret_cast<void**>(&d_neeI),
                            size_t(2) * total_paths * sizeof(int));
        if (qe == cudaSuccess)
            qe = cudaMalloc(reinterpret_cast<void**>(&d_shadowQueue),
                            size_t(total_paths) * sizeof(int));
        if (qe == cudaSuccess)
            qe = cudaMalloc(reinterpret_cast<void**>(&d_shadowCount), sizeof(int));
        auto sfree = [&]() {
            if (d_neeF) cudaFree(d_neeF);
            if (d_neeI) cudaFree(d_neeI);
            if (d_shadowQueue) cudaFree(d_shadowQueue);
            if (d_shadowCount) cudaFree(d_shadowCount);
            cudaGetLastError();
        };
        if (qe != cudaSuccess) {
            sfree();
            if (d_shadeQueues) cudaFree(d_shadeQueues);
            if (d_shadeCounts) cudaFree(d_shadeCounts);
            qfree();
            freeGPUWavefrontHitBuffers(hitBufs);
            cudaFree(d_accum);
            throw std::runtime_error(cudaGetErrorString(qe));
        }"""
assert old in t, 'drv alloc'
t = t.replace(old, new, 1)

old = """                cudaMemsetAsync(cout, 0, sizeof(int));
                cudaMemsetAsync(d_shadeCounts, 0, kNumMatTypes * sizeof(int));
                launchStageIntersectQueued(state, hitBufs, d_queueA, d_counts + 0,
                                           d_shadeQueues, d_shadeCounts,
                                           total_paths,
                                           d_bvhNodes, d_prims, d_tris,
                                           d_spheres, d_materials,
                                           envMap, gbg, hasBg,
                                           worldMaxBounces);
                launchStageShadeBucketed(state, hitBufs,
                                         d_shadeQueues, d_shadeCounts,
                                         total_paths, d_queueB, cout,
                                         d_bvhNodes, d_prims, d_tris,
                                         d_spheres, d_materials, d_lights,
                                         (int)res.lights.size(),
                                         res.totalLightPower,
                                         treeView, max_depth);"""
new = """                cudaMemsetAsync(cout, 0, sizeof(int));
                cudaMemsetAsync(d_shadeCounts, 0, kNumMatTypes * sizeof(int));
                cudaMemsetAsync(d_shadowCount, 0, sizeof(int));
                launchStageIntersectQueued(state, hitBufs, d_queueA, d_counts + 0,
                                           d_shadeQueues, d_shadeCounts,
                                           total_paths,
                                           d_bvhNodes, d_prims, d_tris,
                                           d_spheres, d_materials,
                                           envMap, gbg, hasBg,
                                           worldMaxBounces);
                launchStageShadeBucketed(state, hitBufs,
                                         d_shadeQueues, d_shadeCounts,
                                         total_paths, d_queueB, cout,
                                         d_neeF, d_neeI, d_shadowQueue,
                                         d_shadowCount,
                                         d_bvhNodes, d_prims, d_tris,
                                         d_spheres, d_materials, d_lights,
                                         (int)res.lights.size(),
                                         res.totalLightPower,
                                         treeView, max_depth);
                launchStageShadow(state, hitBufs, d_neeF, d_neeI,
                                  d_shadowQueue, d_shadowCount, total_paths,
                                  d_bvhNodes, d_prims, d_tris, d_spheres,
                                  d_materials);"""
assert old in t, 'drv loop'
t = t.replace(old, new, 1)

# Frees: happy + error paths.
old = "        cudaFree(d_shadeQueues);\n        cudaFree(d_shadeCounts);\n        freeGPUWavefrontHitBuffers(hitBufs);\n        qfree();\n        cudaFree(d_accum);\n        if (de != cudaSuccess)"
new = "        sfree();\n        cudaFree(d_shadeQueues);\n        cudaFree(d_shadeCounts);\n        freeGPUWavefrontHitBuffers(hitBufs);\n        qfree();\n        cudaFree(d_accum);\n        if (de != cudaSuccess)"
assert old in t, 'happy free'
t = t.replace(old, new, 1)
old = """        } catch (...) {
            cudaFree(d_shadeQueues);
            cudaFree(d_shadeCounts);
            freeGPUWavefrontHitBuffers(hitBufs);
            qfree();
            cudaFree(d_accum);
            throw;
        }"""
new = """        } catch (...) {
            sfree();
            cudaFree(d_shadeQueues);
            cudaFree(d_shadeCounts);
            freeGPUWavefrontHitBuffers(hitBufs);
            qfree();
            cudaFree(d_accum);
            throw;
        }"""
assert old in t, 'err free'
t = t.replace(old, new, 1)
d.write_text(t, encoding='utf-8')
print('driver OK')

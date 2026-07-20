// stage_restir.cu — pkg55-C6: ReSTIR reservoir SoA + reuse stages on GPU wavefront
//
// Implements ReSTIR-DI on the GPU wavefront following plan §5:
//   0. Primary stage    — init the bounce-0 ray + intersect for every pixel
//                         (reuses the shared initPathSlot/intersectPathSlot).
//   1. Initial RIS      — draw numCandidates light samples, reservoir update
//   2. Temporal reuse   — merge previous frame's reservoir (validity-gated)
//   3. Spatial reuse    — merge spatial neighbours from previous frame
//   4. Resolve          — finalize weight, shadow ray, BSDF eval, accumulate
//
// This is the C6b completion of the C6a skeleton: real light sampling (via the
// shared gpu_nee_sample), temporal + spatial reuse, and a complete resolve that
// mirrors the CPU restir_di.cpp sampleFull direct-lighting block term-for-term.
//
// One-generator rule (plan decision #9): the reservoir arithmetic is the shared
// astroray::restir::Reservoir<T, TRng> template (restir/reservoir.h) — the CPU
// restir_di and these GPU stages call the SAME update()/merge()/finalizeWeight()
// with TRng = WavefrontRNG here, std::mt19937 there. The light sampling reuses
// the shared gpu_nee_sample (gpu_nee.cuh). No transcribed second implementation.
//
// Each stage runs 1 thread per pixel (slot = pixel at bounce 0). The reservoir
// SoA is per-pixel, so there are NO atomics into the reservoir arrays and the
// arithmetic is race-free and deterministic. Reuse stages read the PREVIOUS
// buffer and write the CURRENT one, exactly like the CPU race-free policy
// (restir_di.cpp:20-31).
//
// References:
//   - Bitterli et al. 2020 (ReSTIR DI), DOI 10.1145/3386569.3392481
//     — Algorithm 1 (RIS update), Algorithm 2 (reservoir merge), §5.2 (M-cap).
//   - Lin et al. 2022 (GRIS), DOI 10.1145/3528223.3530158 — the resampling
//     generalization this DI port is the classic special case of (plan §5).
//   - DQLin/ReSTIR_PT (BSD-3-Clause, NVIDIA Corporation) — reservoir/reuse SoA
//     structure reference (license cleared: restir-pt-license-verification.md).
//   - CPU reference: plugins/integrators/restir_di.cpp (mirrored term-for-term).
//   - pkg55 Phase C plan §5 (one-generator rule, double-buffered SoA layout).

#include "astroray/gpu_wavefront_state.h"
#include "astroray/gpu_types.h"       // GVec3, GEnvMap, GHitRecord, GNEESample, ...
#include "astroray/gpu_materials.h"
#include "astroray/gpu_bvh.h"
#include "astroray/restir/reservoir.h"  // shared Reservoir<T,TRng> (one-generator rule)
#include "astroray/sampling/wavefront_rng_device.h"  // astroray::WavefrontRNG
                                                       // + ADL rng_uniform() overload
#include <cuda_runtime.h>
#include <curand_kernel.h>

// NB: the CPU ReSTIRCandidate (restir/light_sample.h) is intentionally NOT
// included — it pulls the host raytracer.h into this device TU. This file uses
// its own device-callable GReSTIRCandidate (GVec3) mirror instead.

// pkg55-B' template-RNG arc: gpu_rng_uniform(WavefrontRNG*) overload so the
// templated gpu_nee_sample (gpu_nee.cuh) draws directly from the per-pixel
// PCG32 stream. Defined in namespace astroray so ADL finds it at template
// instantiation. This mirrors the identical definition in stage_advance.cu
// (each TU needs its own inline definition — it is not rdc-exported).
namespace astroray {
__device__ inline float gpu_rng_uniform(WavefrontRNG* rng) {
    return rng->Uniform();
}
}  // namespace astroray
using astroray::gpu_rng_uniform;

// Shared NEE thirds (header-inline under the template-RNG arc). gpu_nee_sample
// gives us CPU-faithful light selection (tree/power-CDF) + point sampling.
#include "../gpu_nee.cuh"

// Non-inline XYZ wrapper (defined in stage_advance.cu / the spectral-tables TU,
// rdc-linked) — the same CMF integration the RR/accumulate stages use.
__device__ GVec3 gpu_spectrum_to_xyz(
    const GSampledSpectrum& s, const GSampledWavelengths& wl);

namespace astroray::wavefront {

// Shared per-slot primary init + intersect (rdc-linked from stage_init.cu /
// stage_advance.cu). initPathSlot consumes no reservoir state; intersectPathSlot
// accumulates env/emissive radiance into state.color, parks the shading hit, and
// sets hitBufs.hit_valid=1 for a surviving (non-emissive) hit.
__device__ void initPathSlot(
    int slot, int pixel, int sample_idx,
    GPUWavefrontState& state,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed,
    float lambdaMin,
    float lambdaMax);

__device__ int intersectPathSlot(
    int idx,
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const GTLASNode*  tlas,
    const GInstance*  instances,
    const GBLAS*      blas,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GVec3*      motionVerts,
    const ::GMaterial* materials,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    bool              useLuminanceOutput);

using ::astroray::WavefrontRNG;

// ---------------------------------------------------------------------------
// Device ReSTIRCandidate (mirrors CPU ReSTIRCandidate, light_sample.h, but with
// GVec3 for device-callability). RGB luminance target (wavelength-independent),
// matching CPU targetLuminanceRGB so W values are consistent across frames with
// different wavelength samples (restir_di.cpp:198).
// ---------------------------------------------------------------------------
struct GReSTIRCandidate {
    GVec3 position;
    GVec3 normal;
    GVec3 emission;   // RGB
    float pdf;
    float distance;

    // __host__ __device__ so any host-side instantiation of the
    // Reservoir<GReSTIRCandidate, ..> template (reset()'s `y = T{}`) still has a
    // callable default ctor. Uses no device-only math.
    __host__ __device__ GReSTIRCandidate()
        : position{0, 0, 0}, normal{0, 0, 1}, emission{0, 0, 0}, pdf(0), distance(0) {}

    __device__ bool isValid() const {
        return pdf > 0.0f && isfinite(pdf) &&
               isfinite(emission.x) && isfinite(emission.y) && isfinite(emission.z) &&
               isfinite(position.x) && isfinite(position.y) && isfinite(position.z);
    }

    // RIS target p_hat(y): RGB luminance of the emission (CIE Y coeffs).
    // Mirrors ReSTIRCandidate::targetLuminanceRGB (light_sample.h:66).
    __device__ float targetLuminanceRGB() const {
        if (!isValid()) return 0.0f;
        float Y = 0.2126f * emission.x + 0.7152f * emission.y + 0.0722f * emission.z;
        return Y > 0.0f ? Y : 0.0f;
    }

    // Build a candidate from a shared gpu_nee_sample result + the light material.
    // Mirrors CPU ReSTIRCandidate::fromLightSample(LightSample) where the
    // LightList::sample fills {position, normal, emission, pdf, distance}
    // (light_sampler.cpp:60-70). gpu_nee_sample returns direction+pdf+lightMatId;
    // we reconstruct the sampled light-surface point from (origin, wi, maxDist)
    // and read the emission RGB from the light material (front face), exactly the
    // CPU emittedRadiance()·directionFalloff for a diffuse area emitter.
    //
    // Triangle area lights (the gate scene): maxDist = dist - 0.001, so the
    // sampled point is origin + wi·(maxDist + 0.001). Sphere sources leave
    // maxDist unbounded (1e30) — out of the DI-gate scope; documented.
    __device__ static GReSTIRCandidate fromNEE(
        const GNEESample& s, const ::GMaterial* materials)
    {
        GReSTIRCandidate c;
        if (!s.valid) { c.pdf = 0.0f; return c; }
        float dist = s.maxDist + 0.001f;
        c.position = s.origin + s.wi * dist;
        c.normal   = s.wi * -1.0f;   // light-facing (toward the shading point)
        c.emission = s.isDedicated
                       ? s.dedEmissionRGB * s.dedGeoScale
                       : gpu_material_emitted(materials[s.lightMatId], /*frontFace=*/true);
        c.pdf      = s.lightPdf;
        c.distance = dist;
        return c;
    }
};

using ResType = ::astroray::restir::Reservoir<GReSTIRCandidate, WavefrontRNG>;

// ---- Reservoir SoA <-> ResType round-trip helpers ------------------------
__device__ inline ResType loadReservoir(const GPUReservoirSoA& r, int i) {
    ResType res;
    res.y.position = GVec3(r.res_y_pos_x[i],      r.res_y_pos_y[i],      r.res_y_pos_z[i]);
    res.y.normal   = GVec3(r.res_y_normal_x[i],   r.res_y_normal_y[i],   r.res_y_normal_z[i]);
    res.y.emission = GVec3(r.res_y_emission_x[i], r.res_y_emission_y[i], r.res_y_emission_z[i]);
    res.y.pdf      = r.res_y_pdf[i];
    res.y.distance = r.res_y_distance[i];
    res.w_sum      = r.res_w_sum[i];
    res.M          = r.res_M[i];
    res.W          = r.res_W[i];
    return res;
}

__device__ inline void storeReservoir(GPUReservoirSoA& r, int i, const ResType& res) {
    r.res_y_pos_x[i]      = res.y.position.x;
    r.res_y_pos_y[i]      = res.y.position.y;
    r.res_y_pos_z[i]      = res.y.position.z;
    r.res_y_normal_x[i]   = res.y.normal.x;
    r.res_y_normal_y[i]   = res.y.normal.y;
    r.res_y_normal_z[i]   = res.y.normal.z;
    r.res_y_emission_x[i] = res.y.emission.x;
    r.res_y_emission_y[i] = res.y.emission.y;
    r.res_y_emission_z[i] = res.y.emission.z;
    r.res_y_pdf[i]        = res.y.pdf;
    r.res_y_distance[i]   = res.y.distance;
    r.res_w_sum[i]        = res.w_sum;
    r.res_M[i]            = res.M;
    r.res_W[i]            = res.W;
}

// Device twin of isTemporallyValid (frame_state.h:89-112). `idx` indexes the
// PREVIOUS buffer; the caller supplies the CURRENT shading normal + depth.
__device__ inline bool gIsTemporallyValid(
    const GPUReservoirSoA& prev, int idx,
    const GVec3& curNormal, float curDepth,
    float normalThreshold = 0.9f, float depthThreshold = 0.1f)
{
    if (idx < 0 || idx >= prev.numPixels) return false;
    if (prev.meta_valid[idx] == 0) return false;
    GVec3 pn(prev.meta_normal_x[idx], prev.meta_normal_y[idx], prev.meta_normal_z[idx]);
    float ndot = curNormal.x * pn.x + curNormal.y * pn.y + curNormal.z * pn.z;
    if (ndot < normalThreshold) return false;
    float pd = prev.meta_depth[idx];
    float maxD = pd > curDepth ? pd : curDepth;
    if (maxD > 1e-4f && fabsf(curDepth - pd) / maxD > depthThreshold) return false;
    return true;
}

// Reconstruct the primary hit record parked by intersectPathSlot.
__device__ inline GHitRecord loadHit(const GPUWavefrontHitBuffers& hb, int i) {
    GHitRecord rec;
    rec.t          = hb.hit_t[i];
    rec.point      = GVec3(hb.hit_point_x[i], hb.hit_point_y[i], hb.hit_point_z[i]);
    rec.normal     = GVec3(hb.hit_normal_x[i], hb.hit_normal_y[i], hb.hit_normal_z[i]);
    rec.tangent    = GVec3(hb.hit_tangent_x[i], hb.hit_tangent_y[i], hb.hit_tangent_z[i]);
    rec.bitangent  = GVec3(hb.hit_bitangent_x[i], hb.hit_bitangent_y[i], hb.hit_bitangent_z[i]);
    rec.materialId = hb.hit_material_id[i];
    rec.primId     = hb.hit_prim_id[i];
    rec.frontFace  = hb.hit_front_face[i] != 0;
    rec.isDelta    = hb.hit_is_delta[i] != 0;
    return rec;
}

__device__ inline WavefrontRNG loadRNG(const GPUWavefrontState& state, int i) {
    WavefrontRNG rng(state.rng_pixel[i], state.rng_sample[i], state.rng_seed[i]);
    rng.setDimension(state.rng_dimension[i]);
    return rng;
}

// ===========================================================================
// Stage 0 — primary init + intersect (1 thread per pixel; slot = pixel)
// ===========================================================================
__global__ void stageRestirPrimaryKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    GCameraParams cam,
    int width, int height, int sample_index, uint64_t seed,
    float lambdaMin, float lambdaMax,
    const GTLASNode*  tlas, const GInstance* instances, const GBLAS* blas,
    const GBVHNode*   bvhNodes, const GPrimitive* prims,
    const GTriangle*  tris, const GSphere* spheres, const GVec3* motionVerts,
    const ::GMaterial* materials,
    GEnvMap envMap, GVec3 backgroundColor, bool hasBackgroundColor,
    int worldMaxBounces, bool useLuminanceOutput, int numPixels)
{
    int p = blockIdx.x * blockDim.x + threadIdx.x;
    if (p >= numPixels) return;

    // Reset the hit-validity flag: intersectPathSlot sets it to 1 ONLY for a
    // surviving (non-emissive) shading hit; miss/emissive return early without
    // clearing it, so a stale value from the previous sample would wrongly
    // trigger RIS. Clear it here before the intersect.
    hitBufs.hit_valid[p] = 0;

    initPathSlot(/*slot=*/p, /*pixel=*/p, sample_index, state, cam,
                 width, height, seed, lambdaMin, lambdaMax);
    intersectPathSlot(p, state, hitBufs, tlas, instances, blas, bvhNodes,
                      prims, tris, spheres, motionVerts, materials, envMap,
                      backgroundColor, hasBackgroundColor, worldMaxBounces,
                      useLuminanceOutput);
}

// ===========================================================================
// Stage 1 — initial RIS (Bitterli 2020, Algorithm 1)
// Mirrors restir_di.cpp:194-210.
// ===========================================================================
__global__ void stageRestirInitialRISKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    GPUReservoirSoA cur,
    const GPrimitive* prims, const GTriangle* tris, const GSphere* spheres,
    const ::GMaterial* materials,
    const ::GLight* lights, int numLights, float totalLightPower,
    GLightTreeView lightTree,
    int numCandidates, int mCap, int numPixels)
{
    int p = blockIdx.x * blockDim.x + threadIdx.x;
    if (p >= numPixels) return;

    ResType res;
    res.reset();

    // Pixels that missed / hit an emitter directly are not shading points: mark
    // the reservoir empty + history invalid (so next frame's temporal gate skips
    // them, and this frame's resolve accumulates only env/emissive radiance).
    if (hitBufs.hit_valid[p] == 0) {
        cur.meta_valid[p] = 0;
        storeReservoir(cur, p, res);
        return;
    }

    GHitRecord rec = loadHit(hitBufs, p);
    WavefrontRNG rng = loadRNG(state, p);

    // Delta surfaces get no direct-light RIS (restir_di.cpp:193 !rec.isDelta).
    if (!rec.isDelta && (numLights > 0) && (totalLightPower > 0.0f)) {
        // Initial sampling (Algorithm 1): draw numCandidates light samples,
        // RIS weight w_i = p_hat(x_i)/q(x_i) (restir_di.cpp:199-206).
        for (int i = 0; i < numCandidates; ++i) {
            GNEESample s = gpu_nee_sample(
                rec, prims, tris, spheres, lights, numLights, totalLightPower,
                /*dedLights=*/nullptr, /*numDed=*/0, lightTree, &rng);
            if (!s.valid || s.lightPdf <= 0.0f || !isfinite(s.lightPdf)) continue;
            GReSTIRCandidate cand = GReSTIRCandidate::fromNEE(s, materials);
            float pHat = cand.targetLuminanceRGB();
            res.update(cand, pHat / s.lightPdf, rng);
        }
    }

    // M-cap (Bitterli §5.2): cap after initial sampling (restir_di.cpp:209-210).
    res.M = min(res.M, mCap);

    // Write the initial reservoir + geometry metadata for reuse/resolve.
    storeReservoir(cur, p, res);
    cur.meta_normal_x[p] = rec.normal.x;
    cur.meta_normal_y[p] = rec.normal.y;
    cur.meta_normal_z[p] = rec.normal.z;
    cur.meta_depth[p]    = rec.t;
    cur.meta_valid[p]    = 1;

    state.rng_dimension[p] = rng.dimension();
}

// ===========================================================================
// Stage 2 — temporal reuse (Bitterli 2020, Algorithm 2)
// Mirrors restir_di.cpp:222-231. Same pixel, no reprojection (static camera).
// ===========================================================================
__global__ void stageRestirTemporalReuseKernel(
    GPUWavefrontState state,
    GPUReservoirSoA cur,
    GPUReservoirSoA prev,
    int mCap, int numPixels)
{
    int p = blockIdx.x * blockDim.x + threadIdx.x;
    if (p >= numPixels) return;
    if (cur.meta_valid[p] == 0) return;  // not a shading point this frame

    GVec3 curN(cur.meta_normal_x[p], cur.meta_normal_y[p], cur.meta_normal_z[p]);
    float curDepth = cur.meta_depth[p];
    if (!gIsTemporallyValid(prev, p, curN, curDepth)) return;

    ResType res  = loadReservoir(cur, p);
    ResType pr   = loadReservoir(prev, p);
    if (pr.M <= 0) return;

    WavefrontRNG rng = loadRNG(state, p);

    // merge(prev, p_hat(prev.y)) — Algorithm 2. prev carries its fully-finalized
    // W from last frame's resolve, so the merge weight is prev.W·p_hat·prev.M
    // (reservoir.h:92-96, restir_di.cpp:228-229).
    float pHatPrev = pr.y.targetLuminanceRGB();
    res.merge(pr, pHatPrev, rng);
    res.M = min(res.M, mCap);  // restir_di.cpp:230

    storeReservoir(cur, p, res);
    state.rng_dimension[p] = rng.dimension();
}

// ===========================================================================
// Stage 3 — spatial reuse (Bitterli 2020, Algorithm 3)
// Mirrors restir_di.cpp:234-252 + selectSpatialNeighbors (frame_state.h:124).
// ===========================================================================
__global__ void stageRestirSpatialReuseKernel(
    GPUWavefrontState state,
    GPUReservoirSoA cur,
    GPUReservoirSoA prev,
    int width, int height, int spatialRadius, int spatialNeighbors,
    int mCap, int numPixels)
{
    int p = blockIdx.x * blockDim.x + threadIdx.x;
    if (p >= numPixels) return;
    if (cur.meta_valid[p] == 0) return;

    int cx = p % width;
    int cy = p / width;
    GVec3 curN(cur.meta_normal_x[p], cur.meta_normal_y[p], cur.meta_normal_z[p]);
    float curDepth = cur.meta_depth[p];

    ResType res = loadReservoir(cur, p);
    WavefrontRNG rng = loadRNG(state, p);

    int nActual = spatialNeighbors < 32 ? spatialNeighbors : 32;
    for (int ni = 0; ni < nActual; ++ni) {
        // selectSpatialNeighbors device twin: uniform draw in the
        // (2r+1)×(2r+1) window. The CPU uses uniform_int_distribution[-r,r];
        // we reproduce it via floor(u·(2r+1)) - r, u in [0,1).
        int span = 2 * spatialRadius + 1;
        int dx = (int)(rng.Uniform() * (float)span) - spatialRadius;
        int dy = (int)(rng.Uniform() * (float)span) - spatialRadius;
        int nx = cx + dx;
        int ny = cy + dy;
        if (nx < 0 || nx >= width || ny < 0 || ny >= height) continue;
        int nIdx = ny * width + nx;
        if (!gIsTemporallyValid(prev, nIdx, curN, curDepth)) continue;

        ResType nbr = loadReservoir(prev, nIdx);
        if (nbr.M <= 0) continue;
        float pHatNbr = nbr.y.targetLuminanceRGB();
        res.merge(nbr, pHatNbr, rng);
        res.M = min(res.M, mCap);  // restir_di.cpp:250
    }

    storeReservoir(cur, p, res);
    state.rng_dimension[p] = rng.dimension();
}

// ===========================================================================
// Stage 4 — resolve (finalize weight, shadow ray, BSDF eval, accumulate)
// Mirrors restir_di.cpp:255-313. Runs over ALL pixels: every pixel accumulates
// its primary env/emissive radiance (state.color); shading points additionally
// accumulate the ReSTIR direct-light term.
// ===========================================================================
__global__ void stageRestirResolveKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    GPUReservoirSoA cur,
    float* accum_xyz,
    const GTLASNode*  tlas, const GInstance* instances, const GBLAS* blas,
    const GBVHNode*   bvhNodes, const GPrimitive* prims,
    const GTriangle*  tris, const GSphere* spheres, const GVec3* motionVerts,
    const ::GMaterial* materials,
    int numPixels)
{
    int p = blockIdx.x * blockDim.x + threadIdx.x;
    if (p >= numPixels) return;

    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[p];
    lambdas.lambda[1] = state.lambda_1[p];
    lambdas.lambda[2] = state.lambda_2[p];
    lambdas.lambda[3] = state.lambda_3[p];
    lambdas.pdf[0]    = state.lambda_pdf_0[p];
    lambdas.pdf[1]    = state.lambda_pdf_1[p];
    lambdas.pdf[2]    = state.lambda_pdf_2[p];
    lambdas.pdf[3]    = state.lambda_pdf_3[p];

    // Primary env/emissive radiance (accumulated by intersectPathSlot).
    GSampledSpectrum total;
    total.v[0] = state.color_0[p];
    total.v[1] = state.color_1[p];
    total.v[2] = state.color_2[p];
    total.v[3] = state.color_3[p];

    if (hitBufs.hit_valid[p] != 0) {
        ResType res = loadReservoir(cur, p);

        // Finalize AFTER all reuse: W = w_sum / (p_hat(y)·M). Store it back so
        // next frame's temporal merge uses the correct W (restir_di.cpp:257-269).
        float pHatY = res.y.targetLuminanceRGB();
        res.finalizeWeight(pHatY);
        cur.res_W[p] = res.W;

        if (res.W > 0.0f && res.y.isValid()) {
            GHitRecord rec = loadHit(hitBufs, p);
            GVec3 rayDir(state.ray_direction_x[p], state.ray_direction_y[p],
                         state.ray_direction_z[p]);
            GVec3 wo = (rayDir * -1.0f).normalized();
            float ptime = state.path_time[p];

            GSampledSpectrum throughput;
            throughput.v[0] = state.throughput_0[p];
            throughput.v[1] = state.throughput_1[p];
            throughput.v[2] = state.throughput_2[p];
            throughput.v[3] = state.throughput_3[p];

            // Recompute the direction/distance from THIS shading point (not the
            // pixel that originally sampled the candidate) — restir_di.cpp:273-277.
            GVec3 toLight = res.y.position - rec.point;
            float distLocal = toLight.length();
            GVec3 wi = distLocal > 1e-6f ? toLight * (1.0f / distLocal)
                                         : toLight.normalized();

            // Shadow ray: any occluder in [eps, dist-eps] blocks (matches CPU
            // triangle-source occlusion; the light geometry itself sits just past
            // dist-0.001). restir_di.cpp:279-282.
            bool occluded = gpu_tlas_occluded(
                tlas, instances, blas, bvhNodes, prims, tris, spheres,
                GRay(rec.point, wi, ptime), 0.001f, distLocal - 0.001f, motionVerts);

            if (!occluded) {
                GSampledSpectrum f_spec = gpu_material_eval_spectral(
                    materials[rec.materialId], rec, wo, wi, lambdas);
                // L_spec = RGBIlluminant(emission).sample(lambdas)
                // (restir_di.cpp:286-289).
                GSampledSpectrum L_spec = gpu_rgbToSampledSpectrum(
                    res.y.emission, lambdas, GSPEC_RGB_ILLUMINANT);
                // color += throughput · f_spec · L_spec · W (restir_di.cpp:312).
                total += throughput * f_spec * L_spec * res.W;
            }
        }
    }

    // Convert to XYZ + firefly clamp (mirrors the regen accumulate,
    // stage_advance.cu:1224-1236), then add to the per-pixel accumulator.
    GVec3 xyz = gpu_spectrum_to_xyz(total, lambdas);
    float lum = xyz.y;
    if (lum > 20.0f) {
        xyz.x *= (20.0f / lum);
        xyz.y = 20.0f;
        xyz.z *= (20.0f / lum);
    }
    accum_xyz[p * 3 + 0] += xyz.x;
    accum_xyz[p * 3 + 1] += xyz.y;
    accum_xyz[p * 3 + 2] += xyz.z;
}

// ===========================================================================
// Launchers
// ===========================================================================
static inline int gGrid(int n, int tpb) { return (n + tpb - 1) / tpb; }

void launchStageRestirPrimary(
    GPUWavefrontState& state, GPUWavefrontHitBuffers& hitBufs,
    const GCameraParams& cam, int width, int height, int sample_index,
    uint64_t seed, float lambdaMin, float lambdaMax,
    const GTLASNode* d_tlas, const GInstance* d_instances, const GBLAS* d_blas,
    const GBVHNode* d_bvhNodes, const GPrimitive* d_prims,
    const GTriangle* d_tris, const GSphere* d_spheres, const GVec3* d_motionVerts,
    const ::GMaterial* d_materials, GEnvMap envMap,
    GVec3 backgroundColor, bool hasBackgroundColor,
    int worldMaxBounces, bool useLuminanceOutput)
{
    int numPixels = width * height;
    int tpb = 256;
    stageRestirPrimaryKernel<<<gGrid(numPixels, tpb), tpb>>>(
        state, hitBufs, cam, width, height, sample_index, seed, lambdaMin, lambdaMax,
        d_tlas, d_instances, d_blas, d_bvhNodes, d_prims, d_tris, d_spheres,
        d_motionVerts, d_materials, envMap, backgroundColor, hasBackgroundColor,
        worldMaxBounces, useLuminanceOutput, numPixels);
}

void launchStageRestirInitialRIS(
    GPUWavefrontState& state, GPUWavefrontHitBuffers& hitBufs, GPUReservoirSoA& cur,
    const GPrimitive* d_prims, const GTriangle* d_tris, const GSphere* d_spheres,
    const ::GMaterial* d_materials,
    const ::GLight* d_lights, int num_lights, float total_light_power,
    GLightTreeView lightTree, int numCandidates, int mCap, int numPixels)
{
    int tpb = 256;
    stageRestirInitialRISKernel<<<gGrid(numPixels, tpb), tpb>>>(
        state, hitBufs, cur, d_prims, d_tris, d_spheres, d_materials,
        d_lights, num_lights, total_light_power, lightTree,
        numCandidates, mCap, numPixels);
}

void launchStageRestirTemporalReuse(
    GPUWavefrontState& state, GPUReservoirSoA& cur, const GPUReservoirSoA& prev,
    int mCap, int numPixels)
{
    int tpb = 256;
    stageRestirTemporalReuseKernel<<<gGrid(numPixels, tpb), tpb>>>(
        state, cur, prev, mCap, numPixels);
}

void launchStageRestirSpatialReuse(
    GPUWavefrontState& state, GPUReservoirSoA& cur, const GPUReservoirSoA& prev,
    int width, int height, int spatialRadius, int spatialNeighbors,
    int mCap, int numPixels)
{
    int tpb = 256;
    stageRestirSpatialReuseKernel<<<gGrid(numPixels, tpb), tpb>>>(
        state, cur, prev, width, height, spatialRadius, spatialNeighbors,
        mCap, numPixels);
}

void launchStageRestirResolve(
    GPUWavefrontState& state, GPUWavefrontHitBuffers& hitBufs, GPUReservoirSoA& cur,
    float* d_accum_xyz,
    const GTLASNode* d_tlas, const GInstance* d_instances, const GBLAS* d_blas,
    const GBVHNode* d_bvhNodes, const GPrimitive* d_prims,
    const GTriangle* d_tris, const GSphere* d_spheres, const GVec3* d_motionVerts,
    const ::GMaterial* d_materials, int numPixels)
{
    int tpb = 256;
    stageRestirResolveKernel<<<gGrid(numPixels, tpb), tpb>>>(
        state, hitBufs, cur, d_accum_xyz, d_tlas, d_instances, d_blas,
        d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials, numPixels);
}

}  // namespace astroray::wavefront

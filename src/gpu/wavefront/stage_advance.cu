// stage_advance.cu — pkg55-B' Session N+6
//
// Full one-bounce wavefront advance: the device twin of the CPU shared
// kernel src/cpu/wavefront/path_kernel.cpp::advance_one_bounce. This is the
// kernel that makes the GPU wavefront produce IMAGES, unlocking the
// final-image gate (the per-stage N+3..N+5 gates compare only
// deterministic-given-stage fields; BSDF/NEE sampling correctness is owned
// by the image gate per spec §4.2 design decision #2).
//
// Stage order mirrors the CPU kernel EXACTLY (the final-image gate is
// sensitive to it): intersect -> env-miss accumulate -> emissive accumulate
// (gated bounce==0||wasSpecular, path ends) -> NEE (skipped on delta) ->
// Russian roulette (bounce > 3) -> BSDF sample -> throughput update + clamp
// -> next ray.
//
// RNG convention (spec §4.2 design decision #2, the N+3..N+5 precedent):
// where the CPU seeds a fresh std::mt19937 from rng.UniformUInt32() (NEE
// light sampling, BSDF sampling), the GPU draws the SAME seed from the same
// WavefrontRNG dimension (alignment preserved) and seeds a LOCAL curandState
// from it. Same architecture, different generator — independent MC samples
// with matched dimension consumption. This lets the kernel call the
// UNMODIFIED megakernel-proven device functions (gpu_material_sample_spectral,
// sampleDirectSpectralMW) — one generator of the sampling math on GPU, never
// a second transcription (design decision #9 applied to the GPU side).
//
// Session N+6 scope notes (documented divergences, all out of the gate
// scene's reach):
//   - Static geometry only: motionVerts/TLAS passed null (pkg88/pkg114
//     wavefront integration is a later session).
//   - The MW kernel's non-visible-band profile override block is NOT
//     replicated (gpu_profile_reflectance is TU-local to the MW kernel);
//     visible-band scenes are unaffected. Non-visible wavefront bands are a
//     later session.
//   - NEE uses sampleDirectSpectralMW (power-CDF GLight + solid-angle
//     sampling + power-heuristic MIS) — the same algorithm the CPU
//     wavefront's LightList::sample NEE mirrors.
//
// References:
//   - CPU mirror: src/cpu/wavefront/path_kernel.cpp::advance_one_bounce.
//   - Cycles intern/cycles/kernel/integrator/shade_surface.h (Apache-2.0) —
//     the wavefront shade-stage structure this program mirrors.
//   - Laine, Karras, Aila 2013 (HPG) — wavefront scheduling.

#include "stage_advance_device.cuh"
#include <cstdlib>  // pkg300: std::getenv (shade reference kernel)

namespace astroray::wavefront {

// __constant__ symbol DEFINITIONS (declared extern in stage_advance_device.cuh,
// where each symbol's design comment lives).
__constant__ GWavefrontGuideBinding c_wfGuideBinding;
__constant__ float* c_wfMissCoverage = nullptr;
__constant__ GWorldVolume c_worldVolume;
__constant__ GWavefrontGridVolumeBinding c_wfGridVolume = {};
__constant__ GWavefrontEnvNeeBinding c_wfEnvNeeBinding = {};
__constant__ GWavefrontPrimaryClip c_wfPrimaryClip = {};
__constant__ GWavefrontHwHitBinding c_wfHwHits = {};   // pkg299
__constant__ int c_wfLightNeeOff = 0;
__constant__ GWavefrontLightPassBinding c_wfLpBinding;
__constant__ int c_wfBounceLimit[3] = { -1, -1, -1 };
__constant__ int c_wfTransparentLimit = kWfTransparentOff;   // #1033
__constant__ int c_wfCausticGate[2] = { 1, 1 };
__constant__ int c_wfSamplerMode = 0;
__constant__ int c_hasHair = 0;
__constant__ int c_wfEmissionTex = 0;
__constant__ int c_wfEmissionFlatPrims = 0x7fffffff;
__constant__ uint32_t c_sobolMatrices[kSobolNumDims][kSobolMatrixSize];
__constant__ GWavefrontAdaptiveBinding c_wfAdaptive = { nullptr, nullptr, nullptr, 0, 0, 0 };
__constant__ GWavefrontPhotonSplit c_wfPhotonSplit = { nullptr, 0u };
__constant__ GWavefrontTextureBinding c_wfTexBinding;
__constant__ GWavefrontProgramBinding c_wfProgBinding;
__constant__ GWavefrontLightPathBinding c_wfLightPath = { nullptr, 0 };  // #991

// pkg199 Stage 2 — non-template `intersectPathSlot` symbol. Forwards to the
// <false> (Stage-1, no medium scatter) specialization. This is the symbol the
// cross-TU callers link against: the ReSTIR primary stage (stage_restir.cu, which
// publishes scatter=0) and the MIS-audit kernel — neither runs the volume-scatter
// stage, so <false> is correct and keeps their forward declaration valid without
// exposing intersectPathSlotT across translation units.
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
    bool              useLuminanceOutput,
    bool              enableNEE,
    float             clampDirect, float clampIndirect,
    const ::GLight*   lights, int numLights, float totalLightPower,
    const GDedicatedLight* dedLights, int numDed,
    GLightTreeView    lightTree)
{
    return intersectPathSlotT<false>(idx, state, hitBufs, tlas, instances, blas,
        bvhNodes, prims, tris, spheres, motionVerts, materials, envMap,
        backgroundColor, hasBackgroundColor, worldMaxBounces, useLuminanceOutput,
        enableNEE, clampDirect, clampIndirect, lights, numLights, totalLightPower,
        dedLights, numDed, lightTree);
}

// #1042 -- curve-aware twin of intersectPathSlot for the ReSTIR primary stage
// (stage_restir.cu; scatter=0, no pass AOVs). Forwards to the <false,false,true>
// (HasCurves) specialization with the device curve segments, exactly like the
// path tracer's stageIntersectQueuedKernel<..., true, ...> axis (pkg225 Stage 3).
// Non-curve ReSTIR scenes keep calling the symbol above (curve leaf compiled out).
__device__ int intersectPathSlotCurves(
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
    bool              useLuminanceOutput,
    bool              enableNEE,
    float             clampDirect, float clampIndirect,
    const ::GLight*   lights, int numLights, float totalLightPower,
    const GDedicatedLight* dedLights, int numDed,
    GLightTreeView    lightTree,
    const GCurveSegment* curves)
{
    return intersectPathSlotT<false, false, true>(idx, state, hitBufs, tlas, instances, blas,
        bvhNodes, prims, tris, spheres, motionVerts, materials, envMap,
        backgroundColor, hasBackgroundColor, worldMaxBounces, useLuminanceOutput,
        enableNEE, clampDirect, clampIndirect, lights, numLights, totalLightPower,
        dedLights, numDed, lightTree, curves);
}

// ---------------------------------------------------------------------------
// pkg55-B' shadow stage: lean occlusion + resolve over the parked NEE
// samples (Laine 2013's dedicated shadow-ray stage). No sampling RNG, no
// BSDF-sampling dispatch — just the trace + the lazy material evals the
// original ran post-trace. Contribution adds into color (one entry per
// slot per pass: non-atomic).
// ---------------------------------------------------------------------------
// pkg253 HasAlphaShadow — transparent-shadow (Principled alpha) isolation. The
// <*, false> specialisation keeps the binary gpu_nee_occlude (fleet byte-
// identical); <*, true> walks transparent occluders and attenuates the NEE
// contribution by the accumulated transmittance.
template<bool HasCurves = false, bool HasAlphaShadow = false,
         bool HasGridVolume = false,  // pkg269 — bounded-media isolation axis
         bool HwOcc = false>  // pkg299 — occlusion traced by the OptiX shadow launch
__global__ void stageShadowKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const float* nee_f, const int* nee_i,
    const int* shadow_queue, const int* shadow_count, int nee_capacity,
    const GTLASNode*  tlas,        // pkg55-C4 / pkg114
    const GInstance*  instances,   // pkg55-C4 / pkg114
    const GBLAS*      blas,        // pkg55-C4 / pkg114
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GVec3*      motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* materials,
    bool              useLuminanceOutput,   // pkg157
    float             clampDirect, float clampIndirect,  // pkg157
    const GCurveSegment* curves,  // pkg225 Stage 3 — curve shadow occluders
    int               volSegment)  // #929: volume-segment direct-light records
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
    s.lightMatId = nee_i[0 * nee_capacity + idx];
    const int sphLane = nee_i[1 * nee_capacity + idx];   // #929: bit 1 = triangle back face
    s.isSphere   = sphLane & 1;
    // pkg89-wavefront: dedicated-light payload (dedGeoScale was folded into
    // the parked throughput·f·scale lanes at shade time; only the reference
    // RGB is needed here for the per-λ illuminant upsample).
    s.isDedicated    = nee_i[2 * nee_capacity + idx];
    s.dedEmissionRGB = GVec3(nee_f[11 * nee_capacity + idx],
                             nee_f[12 * nee_capacity + idx],
                             nee_f[13 * nee_capacity + idx]);
    s.dedEmissionProfileIndex = nee_i[5 * nee_capacity + idx];  // pkg218
    s.valid      = 1;

    // pkg55-C4: thread TLAS + path time + motionVerts to shadow rays.
    float time = state.path_time[idx];
    // pkg253: transparent-shadow transmittance. In the <*, true> specialisation
    // EVERY light type (triangle / sphere / dedicated point-spot-area-distant)
    // walks its occluders so a Principled alpha<1 surface lets (1-alpha) through
    // (gpu_shadow_transmittance, device twin of CPU shadowTransmittance, which
    // attenuates all light types). The <*, false> fleet path is exactly the
    // original binary gpu_nee_occlude — the geomDist read below lives inside the
    // HasAlphaShadow branch so the fleet shadow kernel stays byte-identical.
    GNEEOcclusion occ{};
    occ.frontFace = 1;
    float shadowTr = 1.0f;
    // #1037: a surface record leaves the shading vertex's prim (hit_prim_id is
    // still that vertex: this stage runs between shade and the next intersect;
    // a medium-scatter vertex reset it to -1 in the intersect stage). Volume
    // segment records start inside a medium -> no skip.
    const int skipPrim = (HasCurves && volSegment == 0) ? hitBufs.hit_prim_id[idx] : -1;
    if constexpr (HasAlphaShadow) {
        // True vertex->light distance (lane 14) bounds the walk for finite sources
        // (NOT the 1e30 maxDist occlusion sentinel — memory
        // occlusion-sentinel-as-distance-class-of-bug). 0 for distant/infinite.
        s.geomDist = nee_f[14 * nee_capacity + idx];
        // #1073: the shadow ray shares the path's transparent budget (Cycles
        // integrate_shadow_max_transparent_hits): transparent_max_bounces minus the
        // passes the path already took (int lane 6, parked pre-advance). 0x7fffffff =
        // unlimited (-1); the count saturates at 31, so a limit > 31 over-grants.
        const int maxHits = (c_wfTransparentLimit >= 0)
            ? max(c_wfTransparentLimit - nee_i[6 * nee_capacity + idx], 0) : 0x7fffffff;
        shadowTr = gpu_shadow_transmittance<HasCurves>(
            s, tlas, instances, blas, bvhNodes, prims, tris, spheres,
            materials, time, motionVerts, curves, &occ.frontFace, skipPrim,
            c_wfLightPath.sw, maxHits);  // #991: Is Shadow Ray Mix Shader
        if (shadowTr <= 0.0f) return;
    } else if constexpr (HwOcc) {
        // pkg299: __raygen__shadow traced [0.001, maxDist] any-hit, the triangle
        // branch of gpu_nee_occlude. HwOcc scenes carry no sphere lights (the
        // driver's triangle-only gate), so the reach-the-sphere branch never applies.
        if (c_wfHwHits.occluded[idx]) return;
    } else {
        occ = gpu_nee_occlude<HasCurves>(
            s, tlas, instances, blas, bvhNodes, prims, tris, spheres,
            time, motionVerts, curves, skipPrim);
        if (occ.occluded) return;
    }

    // #962: textured emitter — fetch the texel at the exact sampled light point
    // (parked in lanes 11-13, gpu_nee.cuh) so NEE and the BSDF-hit leg (intersect
    // stage) integrate the same emission (CPU light_sampler.cpp #776). Done here,
    // before the spectral state is loaded, so little is live across the call.
    GProgInputTexel emTex{GVec3(0.0f, 0.0f, 0.0f), false};
    if (c_wfEmissionTex && !s.isDedicated &&
        materials[s.lightMatId].type == GMAT_DIFFUSE_LIGHT)
        emTex = gpu_emissionTexelAtLightSample(
            s.origin, s.wi, nee_f[14 * nee_capacity + idx], s.dedEmissionRGB,
            s.lightMatId, prims, tris, spheres);

    // Emission upsample only (the BSDF/MIS parts were pre-resolved in the
    // shade stage); lambdas from the slot's live spectral state.
    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[idx];
    lambdas.lambda[1] = state.lambda_1[idx];
    lambdas.lambda[2] = state.lambda_2[idx];
    lambdas.lambda[3] = state.lambda_3[idx];
    lambdas.pdf[0] = state.lambda_pdf_0[idx];
    lambdas.pdf[1] = state.lambda_pdf_1[idx];
    lambdas.pdf[2] = state.lambda_pdf_2[idx];
    lambdas.pdf[3] = state.lambda_pdf_3[idx];

    GSampledSpectrum L_spec;
    if (s.isDedicated) {
        // pkg89-wavefront: dedicated lights carry emission intrinsically —
        // same RGBIlluminant upsample gpu_nee_resolve uses (dedGeoScale
        // already folded into the parked lanes at shade time).
        // pkg218: non-RGB emission modes read the baked device SPD instead
        // (dedEmissionProfileIndex >= 0) — same substitution as gpu_nee_resolve
        // (gpu_nee.cuh), parked/read via nee_i lane 5 since this kernel resolves
        // the emission in a LATER launch than gpu_dedicated_sample. This lean
        // shadow-resolve kernel is explicitly not register-critical (see the
        // file-header note above), so the branch costs nothing worth measuring.
        if (s.dedEmissionProfileIndex >= 0) {
            for (int k = 0; k < G_SPECTRUM_SAMPLES; ++k)
                L_spec[k] = gpu_emission_profile(s.dedEmissionProfileIndex,
                                                 lambdas.lambda[k]);
        } else {
            L_spec = gpu_rgbToSampledSpectrum(s.dedEmissionRGB, lambdas,
                                              GSPEC_RGB_ILLUMINANT);  // #1012 one lookup
        }
    } else {
        bool lightFront = s.isSphere ? (occ.frontFace != 0) : !(sphLane & 2);
        L_spec = gpu_material_emitted_spectral(
            materials[s.lightMatId], lightFront, lambdas);
        if (emTex.ok && L_spec.maxValue() > 0.f)   // #962 (front face only)
            L_spec = gpu_rgbToSampledSpectrum(
                emTex.c * materials[s.lightMatId].emissionIntensity, lambdas,
                materials[s.lightMatId].spectralMode);
    }
    if (L_spec.maxValue() <= 0.f) return;

    GSampledSpectrum contrib;
    contrib.v[0] = nee_f[ 7 * nee_capacity + idx] * L_spec.v[0];
    contrib.v[1] = nee_f[ 8 * nee_capacity + idx] * L_spec.v[1];
    contrib.v[2] = nee_f[ 9 * nee_capacity + idx] * L_spec.v[2];
    contrib.v[3] = nee_f[10 * nee_capacity + idx] * L_spec.v[3];
    // pkg253: attenuate by the transparent-shadow transmittance (1.0 for sphere/
    // dedicated sources and every opaque occluder). Compiled out of the <*,false>
    // fleet kernel so its generated code is byte-identical.
    if constexpr (HasAlphaShadow) {
        contrib.v[0] *= shadowTr;
        contrib.v[1] *= shadowTr;
        contrib.v[2] *= shadowTr;
        contrib.v[3] *= shadowTr;
    }
    // pkg199 Stage 1 (role 2): attenuate the NEE contribution over the shadow-ray
    // segment (vertex→lamp). Uses the TRUE geometric vertex→light distance parked
    // in lane 14 (geomDist), NOT lane 6 (maxDist) — maxDist is a 1e30 OCCLUSION
    // sentinel for sphere-primitive and distant lights, and exp(-σ·1e30)=0 would
    // collapse every fogged NEE-to-sphere contribution to black at any density
    // (the HW-611 regression). geomDist==0 for distant/infinite lights =>
    // gpu_worldTransmittanceMW returns Tr=1 (non-attenuated, env-miss convention).
    // The parked lanes already carry the camera→vertex fog (role 1 → SoA
    // throughput), so this adds the vertex→light leg — total Tr(rec.t)·Tr(geomDist),
    // matching the CPU NEE role-2 multiply (ls.distance, geometric). Vacuum:
    // skipped (byte-identical).
    if (c_worldVolume.hasVolume) {
        float geomDist = nee_f[14 * nee_capacity + idx];
        contrib *= gpu_worldTransmittanceMW(geomDist, lambdas);
    }
    // pkg269 — per-λ ratio-tracking transmittance through every bounded medium
    // the shadow segment crosses (device twin of the CPU medium/surface NEE
    // attenuation, Novák 2014). Behind the HasGridVolume axis: the grid-free
    // <..., false> shadow kernels compile this out entirely (REG/STACK unchanged).
    // geomDist==0 (distant/infinite light) => cross the whole AABB, like the
    // CPU's ls.distance for an infinite light.
    if constexpr (HasGridVolume) if (c_wfGridVolume.count > 0) {
        float geomDist = nee_f[14 * nee_capacity + idx];
        float segFar = (geomDist > 0.f) ? geomDist : 1e30f;  // (`far` is a windef.h macro)
        int parkedBounce = nee_i[3 * nee_capacity + idx];
        for (int k = 0; k < c_wfGridVolume.count; ++k) {
            float s0, s1;
            if (gpu_gridAabbOverlap(c_wfGridVolume.media[k], s.origin, s.wi, 1e-3f, segFar, s0, s1)) {
                uint32_t salt = gpu_gridShadowSalt(parkedBounce, k);   // #828
                contrib *= gpu_gridVolumeTransmittance(k, s.origin, s.wi, s0, s1, lambdas,
                                                       state.rng_pixel[idx], state.rng_sample[idx],
                                                       state.rng_seed[idx], salt);
            }
        }
    }
    // pkg157: direct/indirect clamp split. bounce is the PARKED depth (lane
    // 3, see G_WF_NEE_I_LANES) the NEE sample was taken at, not state.bounce
    // (already advanced by the time this later-launched kernel runs).
    int bounce = nee_i[3 * nee_capacity + idx];
    contrib = gpu_clampContribMW(contrib, lambdas, bounce,
                                 clampDirect, clampIndirect, useLuminanceOutput);
    state.color_0[idx] += contrib.v[0];
    state.color_1[idx] += contrib.v[1];
    state.color_2[idx] += contrib.v[2];
    state.color_3[idx] += contrib.v[3];
    // pkg198 Stage 2: attribute this resolved NEE to the light-path partition.
    // NEE at bounce 0 is DIRECT (fired before the first-BSDF firstCat lock in the
    // CPU); a deeper NEE is INDIRECT, tagged by firstCat. Runtime-gated (this lean
    // resolve kernel is not register-critical, so no compile-time axis — the fleet
    // pays one predicated branch on a constant null pointer). Direct is routed to
    // the reflect-lobe pass (diffuse/glossy only — NEE never fires on a delta lobe,
    // so a shadow connection is a reflection event; transmission(2) maps to glossy
    // and transmission_direct stays black, matching the CPU documented invariant).
    if (c_wfLpBinding.passAccum != nullptr) {
        unsigned char fc = c_wfLpBinding.firstCat[idx];
        int passIdx;
        if (volSegment) {
            // pkg204/#929: the segment direct light parked int lane 4 = +(bounce+1)
            // when no category was locked at park time (CPU firstCat < 0 =>
            // PASS_VOLUME_DIRECT), else -(bounce+1) (PASS_VOLUME_INDIRECT).
            passIdx = (nee_i[4 * nee_capacity + idx] > 0) ? (3 * 3 + 0) : (3 * 3 + 1);
        } else if (fc == 3) {
            passIdx = 3 * 3 + 1;               // surface NEE after a volume lock
        } else if (bounce == 0) {
            int dc = (fc == G_LP_CAT_UNSET) ? 0 : (fc >= 2 ? 1 : (int)fc);
            passIdx = dc * 3 + 0;              // <reflectLobe>_DIRECT
        } else {
            int ic = (fc == G_LP_CAT_UNSET) ? 0 : (int)fc;
            passIdx = ic * 3 + 1;              // <firstCat>_INDIRECT
        }
        lpAccumulate(idx, passIdx, contrib);
    }
}

// ---------------------------------------------------------------------------
// pkg258 - env NEE shadow-resolve stage. Independent additive twin of
// stageShadowKernel over the SEPARATE env records parked by gpu_env_nee_generate
// (c_wfEnvNeeBinding.envNeeF/envNeeI/envShadowQueue). Each parked ray is traced to
// INFINITY (maxDist sentinel 1e30f, isSphere=0 -> any-hit occlusion) but carries
// ZERO geometric distance for volume attenuation (env miss convention: geomDist=0
// => gpu_worldTransmittanceMW=1), so the shadow segment is not fogged while the
// camera->vertex fog already rides the prefolded throughput (memory
// occlusion-sentinel-as-distance-class-of-bug). The env radiance L_spec comes from
// the SAME spectral lookup the miss leg uses (gpu_env_miss_spectral); everything
// else (throughput*f*wt/envPdf) was prefolded at shade time. Not register-critical.
// No-op when envShadowCount is 0 (env NEE off / no HDRI).
template<bool HasCurves = false, bool HwOcc = false>  // pkg299 HwOcc: OptiX occlusion
__global__ void stageEnvShadowKernel(
    GPUWavefrontState state,
    const GTLASNode*  tlas,
    const GInstance*  instances,
    const GBLAS*      blas,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GVec3*      motionVerts,
    bool              useLuminanceOutput,
    float             clampDirect, float clampIndirect,
    const GCurveSegment* curves,
    const int*        hitPrimId)  // #1037: shading vertex prim (env NEE is surface-only)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    const int* countPtr = c_wfEnvNeeBinding.envShadowCount;
    if (countPtr == nullptr || i >= *countPtr) return;
    const int cap = c_wfEnvNeeBinding.capacity;
    const float* ef = c_wfEnvNeeBinding.envNeeF;
    const int*   ei = c_wfEnvNeeBinding.envNeeI;
    int idx = c_wfEnvNeeBinding.envShadowQueue[i];

    GNEESample s{};
    s.origin  = GVec3(ef[0 * cap + idx], ef[1 * cap + idx], ef[2 * cap + idx]);
    s.wi      = GVec3(ef[3 * cap + idx], ef[4 * cap + idx], ef[5 * cap + idx]);
    s.maxDist = 1e30f;   // infinite occlusion distance (Terra GPU-leg constraint 4)
    s.isSphere   = 0;    // any-hit occlusion (no finite emitter to reach)
    s.lightMatId = -1;
    s.valid   = 1;

    if constexpr (HwOcc) {
        if (c_wfHwHits.occluded[idx]) return;   // pkg299: __raygen__shadow, tMax 1e30
    } else {
        float time = state.path_time[idx];
        // #1037: env NEE records are parked only at surface vertices, and this
        // stage runs before the next intersect rewrites hit_prim_id.
        const int skipPrim = (HasCurves && hitPrimId != nullptr) ? hitPrimId[idx] : -1;
        GNEEOcclusion occ = gpu_nee_occlude<HasCurves>(
            s, tlas, instances, blas, bvhNodes, prims, tris, spheres,
            time, motionVerts, curves, skipPrim);
        if (occ.occluded) return;
    }

    // pkg258 (Terra item 10): use the wavelength state PARKED with the record
    // (generate-time lambdas), NOT state.lambda_*[idx] — a dispersive refraction
    // on the continuation ray may have collapsed the slot's wavelengths to
    // hero-only after this record was parked, which would resolve L_spec at
    // different wavelengths than f_spec was evaluated at (dispersive bias).
    GSampledWavelengths lambdas;
    lambdas.lambda[0] = ef[10 * cap + idx]; lambdas.lambda[1] = ef[11 * cap + idx];
    lambdas.lambda[2] = ef[12 * cap + idx]; lambdas.lambda[3] = ef[13 * cap + idx];
    lambdas.pdf[0] = ef[14 * cap + idx]; lambdas.pdf[1] = ef[15 * cap + idx];
    lambdas.pdf[2] = ef[16 * cap + idx]; lambdas.pdf[3] = ef[17 * cap + idx];

    // Env radiance from the SAME spectral lookup the miss leg uses (Terra
    // constraint 3). backgroundColor is irrelevant here (env NEE only parks when
    // envMap.loaded), but pass the binding's values for a single code path.
    GVec3 bg(c_wfEnvNeeBinding.bgR, c_wfEnvNeeBinding.bgG, c_wfEnvNeeBinding.bgB);
    GSampledSpectrum L_spec = gpu_env_miss_spectral(
        c_wfEnvNeeBinding.envMap, bg, c_wfEnvNeeBinding.hasBackgroundColor != 0,
        s.wi, lambdas);
    if (L_spec.maxValue() <= 0.f) return;

    GSampledSpectrum contrib;
    contrib.v[0] = ef[6 * cap + idx] * L_spec.v[0];
    contrib.v[1] = ef[7 * cap + idx] * L_spec.v[1];
    contrib.v[2] = ef[8 * cap + idx] * L_spec.v[2];
    contrib.v[3] = ef[9 * cap + idx] * L_spec.v[3];
    // Volume: env NEE shadow segment carries geomDist=0 -> Tr=1 (no attenuation of
    // the connection; the camera->vertex fog already rode the prefolded lanes).

    int bounce = ei[idx];
    contrib = gpu_clampContribMW(contrib, lambdas, bounce,
                                 clampDirect, clampIndirect, useLuminanceOutput);
    state.color_0[idx] += contrib.v[0];
    state.color_1[idx] += contrib.v[1];
    state.color_2[idx] += contrib.v[2];
    state.color_3[idx] += contrib.v[3];
    // pkg198 Stage 2: attribute resolved env NEE like the lamp NEE resolve (env
    // NEE never fires on a delta lobe -> a reflection event; bounce 0 direct,
    // deeper indirect by firstCat). Runtime-gated on passAccum (fleet: null).
    if (c_wfLpBinding.passAccum != nullptr) {
        unsigned char fc = c_wfLpBinding.firstCat[idx];
        int passIdx;
        if (fc == 3) {
            passIdx = 3 * 3 + 1;               // PASS_VOLUME_INDIRECT
        } else if (bounce == 0) {
            int dc = (fc == G_LP_CAT_UNSET) ? 0 : (fc >= 2 ? 1 : (int)fc);
            passIdx = dc * 3 + 0;              // <reflectLobe>_DIRECT
        } else {
            int ic = (fc == G_LP_CAT_UNSET) ? 0 : (int)fc;
            passIdx = ic * 3 + 1;              // <firstCat>_INDIRECT
        }
        lpAccumulate(idx, passIdx, contrib);
    }
}

// Fills queue with 0..n-1 and *count = n (bounce-0 population).
__global__ void stageQueueIotaKernel(int* queue, int* count, int n)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    queue[i] = i;
    if (i == 0) *count = n;
}

// ---------------------------------------------------------------------------
// N+7 part 3: staged scheduling -- intersect stage buckets surviving paths
// by material type into per-type shade queues (fixed stride `capacity` per
// bucket), then ONE shade launch covers all buckets with warp-coherent
// material types (thread i -> bucket i/capacity). This is the sort-by-
// material dispatch of Laine 2013 sec. 5 / Cycles X shader sorting, realized
// as bucketed atomic append instead of a radix sort (7 types only).
// ---------------------------------------------------------------------------
template<bool HasWorldScatter, bool HasLightPassAOVs = false,
         bool HasCurves = false,   // pkg225 Stage 3 — curve-leaf isolation axis
         bool HasGridVolume = false,  // pkg269 — bounded-media isolation axis
         bool HwHits = false>  // pkg299 — hits from the OptiX closest-hit launch
__global__ void stageIntersectQueuedKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const int* queue_in, const int* count_in,
    int* shade_queues,     // NUM_TYPES * capacity ints, bucket m at m*capacity
    int* shade_counts,     // NUM_TYPES ints
    int  capacity,
    const GTLASNode*  tlas,        // pkg55-C4 / pkg114
    const GInstance*  instances,   // pkg55-C4 / pkg114
    const GBLAS*      blas,        // pkg55-C4 / pkg114
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GVec3*      motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* materials,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    bool              useLuminanceOutput,
    bool              enableNEE,        // pkg156: gates the pkg120 two-sided-MIS leg
    float             clampDirect, float clampIndirect,  // pkg157
    // pkg120: light data threaded to the two-sided-MIS emissive-hit block.
    const ::GLight*   lights, int numLights, float totalLightPower,
    // pkg181: dedicated lamps for the BSDF-ray lamp-intersection pass.
    const GDedicatedLight* dedLights, int numDed,
    GLightTreeView    lightTree,
    // pkg199 Stage 2 — volume-scatter queue: intersectPathSlot returns -2 for a
    // path that scattered in the medium; that slot is routed here (not the shade
    // bucket) for the dedicated stageVolumeScatterKernel. Null when the medium
    // does not scatter (scatter==0) — the -2 return never fires then.
    int* vol_queue, int* vol_count,
    // pkg225 Stage 3 — device curve segments (nullptr = no curves).
    const GCurveSegment* curves,
    // pkg269 — heterogeneous-medium queue (intersect returns -3). Null in the
    // fleet <..., false> kernels (the -3 return never fires there).
    int* grid_queue, int* grid_count)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= *count_in) return;
    int idx = queue_in[i];
    // N+7 part 4: dead-slot guard. Part-3 flat queues are guaranteed-alive
    // (no-op there); the regeneration driver iterates a dense identity
    // queue where exhausted slots stay dead.
    if (state.path_alive[idx] == 0) return;
    int matType = intersectPathSlotT<HasWorldScatter, HasLightPassAOVs, HasCurves,
                                     HasGridVolume, HwHits>(
                                    idx, state, hitBufs, tlas, instances, blas,
                                    bvhNodes, prims, tris, spheres, motionVerts,
                                    materials, envMap, backgroundColor,
                                    hasBackgroundColor, worldMaxBounces,
                                    useLuminanceOutput, enableNEE,
                                    clampDirect, clampIndirect,
                                    lights, numLights, totalLightPower,
                                    dedLights, numDed, lightTree,  // pkg120+pkg181
                                    curves);  // pkg225 Stage 3
    if (matType == -2) {   // pkg199 Stage 2: scattered → volume-scatter queue
        int vslot = atomicAdd(vol_count, 1);
        vol_queue[vslot] = idx;
        return;
    }
    if constexpr (HasGridVolume) if (matType == -3) {   // pkg269: bounded-medium scatter
        int gslot = atomicAdd(grid_count, 1);
        grid_queue[gslot] = idx;
        return;
    }
    if (matType < 0) return;
    if (matType >= G_WF_NUM_MAT_TYPES) matType = G_WF_NUM_MAT_TYPES - 1;
    int slot = atomicAdd(&shade_counts[matType], 1);
    shade_queues[matType * capacity + slot] = idx;
}


void launchStageQueueIota(int* d_queue, int* d_count, int n)
{
    if (n <= 0) return;
    int threads = 256;
    int blocks  = (n + threads - 1) / threads;
    stageQueueIotaKernel<<<blocks, threads>>>(d_queue, d_count, n);
    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        std::fprintf(stderr, "stage_queue_iota launch error: %s\n",
                     cudaGetErrorString(err));
        throw std::runtime_error(cudaGetErrorString(err));
    }
}

void launchStageIntersectQueued(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const int* d_queue_in, const int* d_count_in,
    int* d_shade_queues, int* d_shade_counts, int capacity,
    const GTLASNode*  d_tlas,        // pkg55-C4 / pkg114
    const GInstance*  d_instances,   // pkg55-C4 / pkg114
    const GBLAS*      d_blas,        // pkg55-C4 / pkg114
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GVec3*      d_motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* d_materials,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    bool              useLuminanceOutput,
    bool              enableNEE,        // pkg156: gates the pkg120 two-sided-MIS leg
    float             clampDirect, float clampIndirect,  // pkg157
    // pkg120: light data for the two-sided-MIS emissive-hit reconstruction.
    const ::GLight*   d_lights, int num_lights, float total_light_power,
    // pkg181: dedicated lamps for the BSDF-ray lamp-intersection pass.
    const GDedicatedLight* d_dedLights, int num_ded,
    GLightTreeView    lightTree,
    int* d_vol_queue, int* d_vol_count,   // pkg199 Stage 2
    bool has_world_scatter,               // pkg199 Stage 2: picks the fleet-isolation axis
    bool has_light_pass_aovs,             // pkg198 Stage 2: picks the pass-AOV axis
    const GCurveSegment* d_curveSegments, // pkg225 Stage 3 (nullptr = no curves)
    int* d_grid_queue, int* d_grid_count, // pkg269 (nullptr = no bounded media)
    bool has_grid_volume,                 // pkg269: picks the bounded-media axis
    bool hw_hits)                         // pkg299: hits precomputed by OptiX
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    // pkg199 Stage 2: the <false> specialization (the fleet, scatter==0) compiles
    // the medium free-flight block OUT → REG 127 / 2 blocks/SM, byte-identical
    // Stage-1. Only scattering fog scenes launch <true>. Both instantiations are
    // referenced here so both land in the cubin for the cuobjdump register report.
    #define ASTRORAY_PKG199_INTERSECT_ARGS \
        state, hitBufs, d_queue_in, d_count_in, \
        d_shade_queues, d_shade_counts, capacity, \
        d_tlas, d_instances, d_blas, \
        d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials, \
        envMap, backgroundColor, hasBackgroundColor, worldMaxBounces, \
        useLuminanceOutput, enableNEE, clampDirect, clampIndirect, \
        d_lights, num_lights, total_light_power, \
        d_dedLights, num_ded, lightTree, \
        d_vol_queue, d_vol_count, \
        d_curveSegments, \
        d_grid_queue, d_grid_count
    {
        // pkg198 Stage 2: the second axis picks the pass-AOV specialization. The
        // fleet (no scatter, no passes) launches <false,false> — REG 127, byte-
        // identical Stage-1. All four instantiations are referenced so they land in
        // the cubin for the cuobjdump register report (intersect<false,false> must
        // stay 127/616).
        // pkg225 Stage 3: the 3rd (HasCurves) axis. NON-curve scenes launch the
        // <..,..,false> kernels (the curve leaf DCE'd → intersect<false,false,false>
        // stays REG 127 / 616, byte-identical Stage-1); only scenes carrying curve
        // segments launch <..,..,true>. All 8 instantiations are referenced so they
        // land in the cubin for the cuobjdump register report.
        const bool hc = (d_curveSegments != nullptr);
        const int sel = (has_world_scatter ? 2 : 0) | (has_light_pass_aovs ? 1 : 0);
        // pkg269: the 4th (HasGridVolume) axis. Scenes without bounded media
        // launch the <..,..,..,false> kernels (the whole grid block DCE'd →
        // intersect<false,false,false,false> unchanged, byte-identical); only
        // scenes carrying grid/homogeneous media launch <..,..,..,true>. All 16
        // instantiations are referenced so they land in the cubin.
        #define ASTRORAY_PKG269_KSEL(G) \
            (hc ? \
                (sel == 3 ? (const void*)stageIntersectQueuedKernel<true, true, true, G>  : \
                 sel == 2 ? (const void*)stageIntersectQueuedKernel<true, false, true, G> : \
                 sel == 1 ? (const void*)stageIntersectQueuedKernel<false, true, true, G> : \
                            (const void*)stageIntersectQueuedKernel<false, false, true, G>) : \
                (sel == 3 ? (const void*)stageIntersectQueuedKernel<true, true, false, G>  : \
                 sel == 2 ? (const void*)stageIntersectQueuedKernel<true, false, false, G> : \
                 sel == 1 ? (const void*)stageIntersectQueuedKernel<false, true, false, G> : \
                            (const void*)stageIntersectQueuedKernel<false, false, false, G>))
        // pkg299: the HwHits axis exists only for curve-free scenes (OptiX
        // traversal is triangle-only), so it adds 8 instantiations, not 16.
        #define ASTRORAY_PKG299_KSEL(G) \
                (sel == 3 ? (const void*)stageIntersectQueuedKernel<true, true, false, G, true>  : \
                 sel == 2 ? (const void*)stageIntersectQueuedKernel<true, false, false, G, true> : \
                 sel == 1 ? (const void*)stageIntersectQueuedKernel<false, true, false, G, true> : \
                            (const void*)stageIntersectQueuedKernel<false, false, false, G, true>)
        const bool hw = hw_hits && !hc;
        const void* kptr = hw ? (has_grid_volume ? ASTRORAY_PKG299_KSEL(true) : ASTRORAY_PKG299_KSEL(false))
                              : (has_grid_volume ? ASTRORAY_PKG269_KSEL(true) : ASTRORAY_PKG269_KSEL(false));
        #undef ASTRORAY_PKG299_KSEL
        #undef ASTRORAY_PKG269_KSEL
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_intersect_queued_n7", kptr, blocks, threads);
        #define ASTRORAY_PKG269_LAUNCH(G) \
            if (hc) { \
                switch (sel) { \
                    case 3: stageIntersectQueuedKernel<true, true, true, G> <<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break; \
                    case 2: stageIntersectQueuedKernel<true, false, true, G><<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break; \
                    case 1: stageIntersectQueuedKernel<false, true, true, G> <<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break; \
                    default:stageIntersectQueuedKernel<false, false, true, G><<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break; \
                } \
            } else { \
                switch (sel) { \
                    case 3: stageIntersectQueuedKernel<true, true, false, G> <<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break; \
                    case 2: stageIntersectQueuedKernel<true, false, false, G><<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break; \
                    case 1: stageIntersectQueuedKernel<false, true, false, G> <<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break; \
                    default:stageIntersectQueuedKernel<false, false, false, G><<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break; \
                } \
            }
        #define ASTRORAY_PKG299_LAUNCH(G) \
            switch (sel) { \
                case 3: stageIntersectQueuedKernel<true, true, false, G, true> <<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break; \
                case 2: stageIntersectQueuedKernel<true, false, false, G, true><<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break; \
                case 1: stageIntersectQueuedKernel<false, true, false, G, true> <<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break; \
                default:stageIntersectQueuedKernel<false, false, false, G, true><<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break; \
            }
        if (hw) {
            if (has_grid_volume) { ASTRORAY_PKG299_LAUNCH(true) } else { ASTRORAY_PKG299_LAUNCH(false) }
        } else if (has_grid_volume) { ASTRORAY_PKG269_LAUNCH(true) } else { ASTRORAY_PKG269_LAUNCH(false) }
        #undef ASTRORAY_PKG299_LAUNCH
        #undef ASTRORAY_PKG269_LAUNCH
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_intersect_queued launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
    #undef ASTRORAY_PKG199_INTERSECT_ARGS
}

// ---------------------------------------------------------------------------
// pkg199 Stage 2 — dedicated volume-scatter wavefront stage. Scheduled between
// stageIntersectQueued and stageShadeBucketed. Drains the volume-scatter queue
// (slots intersectPathSlot routed via its -2 return) and emits the HG
// phase-sampled continuation ray from the scatter point (#929: no NEE here, see
// gpu_volumeSegmentDirect), requeuing the survivor for the next bounce. The REG-254 shade kernel is
// never touched → byte-identical (this is the whole point of Option A). Device
// twin of the CPU pathTraceSpectral scatter branch (HG NEE + phase continuation).
// ---------------------------------------------------------------------------
__global__ void stageVolumeScatterKernel(
    GPUWavefrontState state,
    const int* vol_queue, const int* vol_count,
    int* queue_out, int* count_out,          // requeue survivors → next bounce
    float* nee_f, int* nee_i, int* shadow_queue, int* shadow_count, int nee_capacity,
    const GPrimitive* prims, const GTriangle* tris, const GSphere* spheres,
    const ::GLight* lights, int numLights, float totalLightPower,
    const GDedicatedLight* dedLights, int numDed,
    GLightTreeView lightTree,
    int max_depth,
    bool useLuminanceOutput,
    bool enableNEE)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= *vol_count) return;
    int idx = vol_queue[i];
    if (state.path_alive[idx] == 0) return;
    const int bounce = state.bounce[idx];

    // pkg198 Stage 2: a volume scatter locks the light-path category to VOLUME (3)
    // at the FIRST interaction (CPU: firstInteraction => firstCat=3), so every
    // downstream surface/emission/env event this path sees folds into the volume
    // INDIRECT pass (3*3+1 = PASS_VOLUME_INDIRECT), matching the CPU. Runtime-gated;
    // set only when unset so a deeper scatter does not relabel an earlier lock.
    if (c_wfLpBinding.passAccum != nullptr &&
        c_wfLpBinding.firstCat[idx] == G_LP_CAT_UNSET)
        c_wfLpBinding.firstCat[idx] = 3;

    // Reconstruct: ray_origin == scatter point P (intersect wrote it), and
    // ray_direction == incoming direction (woMedium = -direction), per the pinned
    // snapshot semantics. throughput already carries Tr·σ_s/pdf (applied in intersect).
    GVec3 inDir = GVec3(state.ray_direction_x[idx], state.ray_direction_y[idx],
                        state.ray_direction_z[idx]);
    GVec3 woMedium = (inDir * -1.f).normalized();
    const float g = c_worldVolume.anisotropy;

    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[idx]; lambdas.lambda[1] = state.lambda_1[idx];
    lambdas.lambda[2] = state.lambda_2[idx]; lambdas.lambda[3] = state.lambda_3[idx];
    lambdas.pdf[0] = state.lambda_pdf_0[idx]; lambdas.pdf[1] = state.lambda_pdf_1[idx];
    lambdas.pdf[2] = state.lambda_pdf_2[idx]; lambdas.pdf[3] = state.lambda_pdf_3[idx];

    GSampledSpectrum throughput;
    throughput.v[0] = state.throughput_0[idx]; throughput.v[1] = state.throughput_1[idx];
    throughput.v[2] = state.throughput_2[idx]; throughput.v[3] = state.throughput_3[idx];

    WavefrontRNG rng(state.rng_pixel[idx], state.rng_sample[idx], state.rng_seed[idx]);
    rng.setDimension(state.rng_dimension[idx]);

    // #929: no NEE at this vertex — direct light is the per-segment sample the
    // intersect stage parked (gpu_volumeSegmentDirect); this vertex only
    // continues (its lamp-hit MIS is the complement). The nee/light parameters
    // are unused since #929.

    // pkg271 — Cycles volume_bounce (+1 at this scatter); past the cap the
    // continuation is terminate-after (see intersectPathSlotT volTerm).
    gpu_countVolumeBounce(state.per_type_bounce, idx, c_wfGridVolume.volumeBounceCap);
    // #991 — Light Path: the continuation is a volume-scatter ray.
    if (c_wfLightPath.enabled) state.lp_state[idx] = gpu_lpVolume(state.lp_state[idx]);

    // ---- HG phase-sampled continuation from P (throughput *= phase/pdf = 1) ----
    float phasePdf;
    GVec3 wiCont = gpu_sampleHG(woMedium, g, rng.Uniform(), rng.Uniform(), phasePdf);

    // Russian roulette (mirror the shade-kernel / CPU scatter-branch RR, kRRDepth=3).
    if (bounce > 3) {
        float p;
        if (useLuminanceOutput) {
            float L = 0.f;
            for (int k = 0; k < G_SPECTRUM_SAMPLES; ++k) L += throughput.v[k];
            p = fminf(0.95f, fmaxf(0.f, L / float(G_SPECTRUM_SAMPLES)));
        } else {
            GVec3 xyz = gpu_spectrum_to_xyz(throughput, lambdas);
            p = fminf(0.95f, fmaxf(0.f, xyz.y));
        }
        if (rng.Uniform() > p) {
            state.path_alive[idx] = 0;
            state.rng_dimension[idx] = rng.dimension();
            return;   // color already in SoA; regen accumulates it
        }
        if (p > 0.f) for (int k = 0; k < G_SPECTRUM_SAMPLES; ++k) throughput.v[k] *= (1.f / p);
    }

    // ---- Continuation write-back (ray_origin already == P from intersect) ----
    state.ray_direction_x[idx] = wiCont.x;
    state.ray_direction_y[idx] = wiCont.y;
    state.ray_direction_z[idx] = wiCont.z;
    state.throughput_0[idx] = throughput.v[0];
    state.throughput_1[idx] = throughput.v[1];
    state.throughput_2[idx] = throughput.v[2];
    state.throughput_3[idx] = throughput.v[3];
    state.was_specular[idx]  = 0;
    // pkg258: a volume phase scatter does lamp NEE only (never env NEE), so clear
    // the env-NEE-competed flag -- otherwise the next-bounce env miss would be
    // wrongly discounted (was_specular==0 alone is insufficient after a phase
    // event; memory occlusion-sentinel / wavefront-snapshot-semantics).
    // #961: 2 = medium vertex (Cycles PATH_RAY_VOLUME_SCATTER): no env NEE ran,
    // and path_mis_n*/path_mis_dt (written by intersect) hold the NEE segment.
    state.env_nee_sampled_prev[idx] = 2;
    state.path_bsdf_pdf[idx] = phasePdf;
    state.rng_dimension[idx] = rng.dimension();
    int next_bounce = bounce + 1;
    state.bounce[idx] = next_bounce;
    if (next_bounce >= max_depth) { state.path_alive[idx] = 0; return; }
    int slot = atomicAdd(count_out, 1);
    queue_out[slot] = idx;
}

void launchStageVolumeScatter(
    GPUWavefrontState& state,
    const int* d_vol_queue, const int* d_vol_count,
    int* d_queue_out, int* d_count_out,
    float* d_nee_f, int* d_nee_i, int* d_shadow_queue, int* d_shadow_count,
    int nee_capacity,
    const GPrimitive* d_prims, const GTriangle* d_tris, const GSphere* d_spheres,
    const ::GLight* d_lights, int num_lights, float total_light_power,
    const GDedicatedLight* d_dedLights, int num_ded,
    GLightTreeView lightTree,
    int max_depth, bool useLuminanceOutput, bool enableNEE)
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_volume_scatter",
            (const void*)stageVolumeScatterKernel, blocks, threads);
        stageVolumeScatterKernel<<<blocks, threads>>>(
            state, d_vol_queue, d_vol_count, d_queue_out, d_count_out,
            d_nee_f, d_nee_i, d_shadow_queue, d_shadow_count, nee_capacity,
            d_prims, d_tris, d_spheres,
            d_lights, num_lights, total_light_power,
            d_dedLights, num_ded, lightTree,
            max_depth, useLuminanceOutput, enableNEE);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_volume_scatter launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

// pkg186 — publish the frame's image-texture arrays into the __constant__
// c_wfTexBinding symbol. Called ONCE per frame by the driver (before the shade
// launches), so the shade kernel reads texture data from constant memory instead
// of per-launch signature params. For untextured scenes the driver skips this
// (the <false,*> kernel never reads the symbol).
void setWavefrontTextureBinding(const GWavefrontTextureBinding& binding)
{
    cudaMemcpyToSymbol(c_wfTexBinding, &binding, sizeof(GWavefrontTextureBinding));
}

// pkg197 — publish the frame's first-hit denoise-guide output pointers into the
// __constant__ c_wfGuideBinding symbol (read by intersectPathSlot at bounce 0 /
// sample 0). Called ONCE per frame by cuda_wavefront_render. Passing all-null
// disables guide capture (the ReSTIR/snapshot drivers leave it null).
void setWavefrontGuideBinding(const GWavefrontGuideBinding& binding)
{
    cudaMemcpyToSymbol(c_wfGuideBinding, &binding, sizeof(GWavefrontGuideBinding));
}

// pkg199 Stage 1 — publish the frame's homogeneous world-volume medium into the
// __constant__ c_worldVolume symbol (read by intersectPathSlot + stageShadowKernel
// at runtime). Called ONCE per frame by cuda_wavefront_render. Passing
// hasVolume==0 (vacuum) disables the Beer-Lambert branch — byte-identical renders.
void setWavefrontWorldVolume(const GWorldVolume& volume)
{
    cudaMemcpyToSymbol(c_worldVolume, &volume, sizeof(GWorldVolume));
}

// pkg269 — publish the frame's bounded-media side table into the __constant__
// c_wfGridVolume symbol (read by intersectPathSlotT<...,true>, stageShadowKernel
// and the hetero scatter stage). Called ONCE per frame by every wavefront driver;
// count==0 disables every grid branch (byte-identical renders).
void setWavefrontGridVolumeBinding(const GWavefrontGridVolumeBinding& binding)
{
    cudaMemcpyToSymbol(c_wfGridVolume, &binding, sizeof(GWavefrontGridVolumeBinding));
}

// pkg201 Stage 2 (Finding F) — publish the frame's transparent-film coverage
// accumulator pointer into the __constant__ c_wfMissCoverage symbol (read by
// intersectPathSlot at bounce 0). Called ONCE per frame by cuda_wavefront_render;
// pass nullptr (the default) to disable the coverage count (opaque alpha).
void setWavefrontMissCoverage(float* coverage)
{
    cudaMemcpyToSymbol(c_wfMissCoverage, &coverage, sizeof(float*));
}

// pkg201 Stage 3 (Finding A) — publish the Cycles per-type bounce limits into the
// __constant__ c_wfBounceLimit[3] symbol (read by shadePathSlot). Called ONCE per
// frame by cuda_wavefront_render; all-unlimited (-1,-1,-1) is the byte-identical
// fleet default (the shade kernel's any-limit early-out skips the per-type block).
void setWavefrontBounceLimits(int diffuse, int glossy, int transmission)
{
    const int limits[3] = { diffuse, glossy, transmission };
    cudaMemcpyToSymbol(c_wfBounceLimit, limits, sizeof(limits));
}

// #1033 — publish the transparent pass-through budget (see
// gpu_wavefront_state.h). kWfTransparentOff = legacy / byte-identical.
void setWavefrontTransparentLimit(int limit)
{
    cudaMemcpyToSymbol(c_wfTransparentLimit, &limit, sizeof(limit));
}

// pkg201 Stage 3 (Finding E) — publish the native caustic toggles into the
// __constant__ c_wfCausticGate[2] symbol (read by shadePathSlot). Both-allow
// (1,1) is the byte-identical fleet default.
void setWavefrontCausticGate(bool reflective, bool refractive)
{
    const int gate[2] = { reflective ? 1 : 0, refractive ? 1 : 0 };
    cudaMemcpyToSymbol(c_wfCausticGate, gate, sizeof(gate));
}

// pkg224 — publish the progressive-sampler mode into the __constant__
// c_wfSamplerMode symbol (read by WavefrontRNG::Uniform() in the shade + init
// kernels). false (PCG32) is the byte-identical fleet default.
void setWavefrontSamplerMode(bool useProgressive)
{
    const int mode = useProgressive ? 1 : 0;
    cudaMemcpyToSymbol(c_wfSamplerMode, &mode, sizeof(mode));
    if (useProgressive) {
        // Upload the direction-vector table from the single host source only
        // when the progressive sampler is on (8 KB; the default path uploads
        // nothing, so it stays byte-identical to pre-pkg224).
        cudaMemcpyToSymbol(c_sobolMatrices, astroray::kSobolMatrices32,
                           sizeof(astroray::kSobolMatrices32));
    }
}

// pkg225 Stage 4 — publish the scene-has-hair flag into __constant__ c_hasHair
// (read by shadePathSlot to gate the hair uvTangent/hairV SoA restore). false (the
// default) keeps the fleet shade kernel byte-identical for non-hair scenes.
void setWavefrontHairEnabled(bool hasHair)
{
    const int flag = hasHair ? 1 : 0;
    cudaMemcpyToSymbol(c_hasHair, &flag, sizeof(flag));
}

// #962 — publish the textured-emission flag into __constant__ c_wfEmissionTex
// (1: emission textures bound this frame) and the flat-scene prim count.
void setWavefrontEmissionTexture(int flags, int flatPrims)
{
    cudaMemcpyToSymbol(c_wfEmissionTex, &flags, sizeof(flags));
    cudaMemcpyToSymbol(c_wfEmissionFlatPrims, &flatPrims, sizeof(flatPrims));
}


// #909 - publish the photon-map split (per render; chain=null disables).
void setWavefrontPhotonSplit(const GWavefrontPhotonSplit& split)
{
    cudaMemcpyToSymbol(c_wfPhotonSplit, &split, sizeof(GWavefrontPhotonSplit));
}

// pkg131 — publish the adaptive-round binding into __constant__ c_wfAdaptive.
// Called once per round by cuda_wavefront_render. enabled=0 (the default binding)
// keeps stageRegenKernel on the byte-identical flat-pool mapping.
void setWavefrontAdaptiveBinding(const GWavefrontAdaptiveBinding& binding)
{
    cudaMemcpyToSymbol(c_wfAdaptive, &binding, sizeof(GWavefrontAdaptiveBinding));
}

// pkg198 Stage 2 — publish the frame's light-path pass buffers into the
// __constant__ c_wfLpBinding symbol (read by the shade classification lock, the
// intersect emission/env/lamp writes, the shadow-resolve NEE attribution, the
// volume-scatter firstCat lock, and the regen accumulate-at-death flush). Called
// ONCE per frame by cuda_wavefront_render; ALWAYS set (to real pointers or all-null)
// so a prior render's pointers can never be read stale. passAccum==nullptr disables
// the whole partition (fleet renders byte-identical).
void setWavefrontLightPassBinding(const GWavefrontLightPassBinding& binding)
{
    cudaMemcpyToSymbol(c_wfLpBinding, &binding, sizeof(GWavefrontLightPassBinding));
}

// pkg219b — publish the frame's op-VM program array + per-material index into the
// __constant__ c_wfProgBinding symbol. Called ONCE per frame by the driver before
// the shade launches. All-null (no program materials) leaves the <false> shade
// kernel never reading the symbol — byte-identical fleet.
void setWavefrontProgramBinding(const GWavefrontProgramBinding& binding)
{
    cudaMemcpyToSymbol(c_wfProgBinding, &binding, sizeof(GWavefrontProgramBinding));
}

// #991 — publish the Light Path switch side table + lp_state maintenance flag.
// All-null (every non-Light-Path render and every harness entry point) makes
// the intersect remap, the shadow resolve and the lp_state updates no-ops.
void setWavefrontLightPathBinding(const GWavefrontLightPathBinding& binding)
{
    cudaMemcpyToSymbol(c_wfLightPath, &binding, sizeof(GWavefrontLightPathBinding));
}

// Build-speed split: host entry points of the 12 shade part TUs
// (src/gpu/wavefront/stage_shade_part<k>.cu). k = 0..3: HasPrincipled=false,
// (HasTexture,HasPhotons) = k, both HasDispersion values. k = 4..11: HasPrincipled=true,
// k = 4 + 2*(T*2+Ph) + HasDispersion (the heavy principled variants are split by D).
#define ASTRORAY_DECL_SHADE_PART(K) \
    const void* stageShadePartKernelPtr_##K(bool, bool, bool, bool); \
    void stageShadePartLaunch_##K(bool, bool, bool, bool, int, int, const StageShadeArgs&);
ASTRORAY_DECL_SHADE_PART(0) ASTRORAY_DECL_SHADE_PART(1) ASTRORAY_DECL_SHADE_PART(2)
ASTRORAY_DECL_SHADE_PART(3) ASTRORAY_DECL_SHADE_PART(4) ASTRORAY_DECL_SHADE_PART(5)
ASTRORAY_DECL_SHADE_PART(6) ASTRORAY_DECL_SHADE_PART(7) ASTRORAY_DECL_SHADE_PART(8)
ASTRORAY_DECL_SHADE_PART(9) ASTRORAY_DECL_SHADE_PART(10) ASTRORAY_DECL_SHADE_PART(11)
#undef ASTRORAY_DECL_SHADE_PART
using ShadePartKptrFn   = const void* (*)(bool, bool, bool, bool);
using ShadePartLaunchFn = void (*)(bool, bool, bool, bool, int, int, const StageShadeArgs&);
static const ShadePartKptrFn kShadePartKptr[12] = {
    stageShadePartKernelPtr_0, stageShadePartKernelPtr_1, stageShadePartKernelPtr_2,
    stageShadePartKernelPtr_3, stageShadePartKernelPtr_4, stageShadePartKernelPtr_5,
    stageShadePartKernelPtr_6, stageShadePartKernelPtr_7, stageShadePartKernelPtr_8,
    stageShadePartKernelPtr_9, stageShadePartKernelPtr_10, stageShadePartKernelPtr_11 };
static const ShadePartLaunchFn kShadePartLaunch[12] = {
    stageShadePartLaunch_0, stageShadePartLaunch_1, stageShadePartLaunch_2,
    stageShadePartLaunch_3, stageShadePartLaunch_4, stageShadePartLaunch_5,
    stageShadePartLaunch_6, stageShadePartLaunch_7, stageShadePartLaunch_8,
    stageShadePartLaunch_9, stageShadePartLaunch_10, stageShadePartLaunch_11 };

// pkg300 equivalence reference (stage_shade_reference.cu): ASTRORAY_SHADE_REFERENCE=1
// runs the pre-pkg300 shade kernel (by-value params copied to the stack for the
// out-of-line call, no cap) instead of the fleet kernel for fleet-axis launches.
const void* stageShadeReference(bool P, bool launch, int blocks, int threads,
                                const StageShadeArgs& a);
// pkg300 fleet shade kernels (stage_shade_fleet_p<P>.cu), used whenever
// HasPrincipled is the only active axis (P=0 fully inlined under __maxnreg__(128)).
const void* stageShadeFleet_0(bool, int, int, const StageShadeArgs&);
const void* stageShadeFleet_1(bool, int, int, const StageShadeArgs&);

void launchStageShadeBucketed(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const int* d_shade_queues, const int* d_shade_counts, int capacity,
    int* d_queue_out, int* d_count_out,
    float* d_nee_f, int* d_nee_i, int* d_shadow_queue, int* d_shadow_count,
    const GTLASNode*  d_tlas,        // pkg55-C4 / pkg114
    const GInstance*  d_instances,   // pkg55-C4 / pkg114
    const GBLAS*      d_blas,        // pkg55-C4 / pkg114
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GVec3*      d_motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* d_materials,
    const ::GLight*    d_lights, int num_lights, float total_light_power,
    const GDedicatedLight* d_dedLights, int num_ded,   // pkg89-wavefront (C7)
    GLightTreeView    lightTree,
    int               max_depth,
    bool              useLuminanceOutput,
    bool              enableNEE,
    float             clampDirect, float clampIndirect,  // pkg157
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid,
    float             photonScale,
    // pkg159: per-pixel cryptomatte rank arrays (driver-owned; null/0 = off).
    float* d_cryptoObjectRanks, float* d_cryptoMaterialRanks, int cryptoDepth,
    bool              hasPrincipled,  // pkg178 Stage-3b D4
    // pkg186: hasTexture selects the <*,true> instantiation. The texture DATA is
    // NOT passed here — the driver publishes it to c_wfTexBinding (constant
    // memory) once per frame via setWavefrontTextureBinding, so this signature
    // (shared by the untextured fleet kernel) stays at its pre-pkg186 footprint.
    bool              hasTexture,
    // pkg189: selects the <*,*,*,true> instantiation carrying the hero-λ collapse
    // write-back. Host-side flag (any uploaded material isDispersive); the
    // non-dispersive fleet passes false and stays register/stack-identical.
    bool              hasDispersion,
    // pkg198 Stage 2: selects the <*,*,*,*,true> instantiation carrying the
    // first-bounce classification lock. The fleet passes false and stays byte-
    // identical (254/3352/1700 — the REGISTER PROBE result, PR #620).
    bool              hasLightPassAOVs,
    // pkg219b: selects the <*,*,*,*,*,true> instantiation carrying the per-texel
    // op-VM. The fleet (no material carries a VM program) passes false and stays
    // byte-identical — the register probe gate for this package.
    bool              hasProgram,
    // pkg223: selects the <…,true> instantiation carrying the tangent-space
    // normal-map perturbation. The fleet (no material carries a normal map)
    // passes false and reaches the byte-identical <…,false> kernel — the
    // register-probe gate. Data (matNormalTexId/Strength) rides c_wfTexBinding.
    bool              hasNormalPerturb)
{
    if (capacity <= 0) return;
    // One launch covers all buckets: grid = NUM_TYPES * capacity threads;
    // capacity is a multiple of the block size in practice but the kernel
    // handles any value. Threads past a bucket's count retire immediately;
    // surviving warps are material-coherent within their bucket.
    long long total = (long long)G_WF_NUM_MAT_TYPES * capacity;
    static const bool kReference = [] {
        const char* v = std::getenv("ASTRORAY_SHADE_REFERENCE");
        return v && *v == '1';
    }();
    int threads = 256;
    int blocks  = (int)((total + threads - 1) / threads);
    {
        // pkg178 Stage-3b D4 / pkg186 / pkg184 / pkg189 / pkg198 / pkg219b / pkg223:
        // the 16-way P/T/Ph/D selection (axis notes and register/stack invariants
        // in stage_advance_device.cuh) now dispatches to one of 12 part TUs
        // (stage_shade_part<k>.cu; k = sel>>1 for P=false, 4 + 2*(sel>>1 & 3) + D for
        // P=true); the part picks the runtime LP x Program x NormalPerturb axes. The fleet
        // path (all of those false) reaches the same <..., false, false, false>
        // instantiations. All 128 variants are referenced by the parts so they
        // land in the cubin for the register report (cuobjdump).
        // The texture arrays are NOT in the arg struct: they live in the
        // __constant__ c_wfTexBinding symbol (setWavefrontTextureBinding, once per
        // frame), which keeps the untextured <false,false> signature at its
        // pre-pkg186 REG/STACK footprint.
        const bool hasPhotons = hasPhotonGrid;
        const int sel = (hasPrincipled ? 8 : 0) | (hasTexture ? 4 : 0)
                      | (hasPhotons ? 2 : 0) | (hasDispersion ? 1 : 0);
        const bool hasD = (sel & 1) != 0;
        const int part = (sel < 8) ? (sel >> 1) : 4 + 2 * ((sel >> 1) & 3) + (hasD ? 1 : 0);
        const bool fleetAxes = !hasTexture && !hasPhotons && !hasD && !hasLightPassAOVs
                            && !hasProgram && !hasNormalPerturb;
        const bool useRef = kReference && fleetAxes;
        const bool useFleet = fleetAxes && !useRef;
        const auto fleetFn = hasPrincipled ? stageShadeFleet_1 : stageShadeFleet_0;
        const void* kptr = useRef
            ? stageShadeReference(hasPrincipled, false, 0, 0, StageShadeArgs{})
            : useFleet ? fleetFn(false, 0, 0, StageShadeArgs{})
            : kShadePartKptr[part](hasD, hasLightPassAOVs, hasProgram, hasNormalPerturb);
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_shade_bucketed_n7", kptr, blocks, threads);
        StageShadeArgs a = {
            &state, &hitBufs, d_shade_queues, d_shade_counts, capacity,
            d_queue_out, d_count_out,
            d_nee_f, d_nee_i, d_shadow_queue, d_shadow_count,
            d_tlas, d_instances, d_blas,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials,
            d_lights, num_lights, total_light_power,
            d_dedLights, num_ded, lightTree, max_depth,
            useLuminanceOutput, enableNEE,
            clampDirect, clampIndirect,
            photonGrid, hasPhotonGrid, photonScale,
            d_cryptoObjectRanks, d_cryptoMaterialRanks, cryptoDepth };
        if (useRef)
            stageShadeReference(hasPrincipled, true, blocks, threads, a);
        else if (useFleet)
            fleetFn(true, blocks, threads, a);
        else
            kShadePartLaunch[part](hasD, hasLightPassAOVs, hasProgram, hasNormalPerturb,
                                   blocks, threads, a);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_shade_bucketed launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}


// ---------------------------------------------------------------------------
// N+7 part 4: path regeneration (Laine 2013 sec. 4).
//
// Dense pass over all slots: a DEAD slot first accumulates its radiance
// (the same XYZ conversion math as stageAccumulateXYZKernel -- the
// accumulate-at-death form; pkg157 moved the firefly clamp upstream to the
// per-contribution sites, see gpu_clampContribMW), zeroes its color (so an
// exhausted slot adds 0 on later passes), then claims the next unscheduled
// (pixel, sample) work
// item from a global counter and re-initializes itself via initPathSlot.
// The pool therefore stays ~full for the whole render and kernel launches
// amortize across ALL samples instead of running depth x spp rounds over
// emptying queues (the part-3 diagnosis).
//
// work item w -> pixel = w % numPixels, sample = w / numPixels, so wave k
// schedules sample k for every pixel: coalesced and identical per-path RNG
// keying to the per-round scheduling (streams keyed by (pixel, sample)).
// ---------------------------------------------------------------------------
__global__ void stageRegenKernel(
    GPUWavefrontState state,
    float* accum_xyz,
    int* work_counter,
    int total_work,
    int numPixels,
    GCameraParams cam,
    int width, int height,
    uint64_t seed,
    float lambdaMin,
    float lambdaMax,
    int* count_out,      // pkg55-C7 perf: fused per-pass counter zeroing —
    int* shade_counts,   // replaces 3 cudaMemsetAsync launches per pass
    int* shadow_count,   // (~3.6k extra launches per 512-spp render).
    int* vol_count,      // pkg199 Stage 2: volume-scatter queue counter (null = skip)
    bool useLuminanceOutput)  // pkg55-C7: non-visible-band accumulation —
                              // grey band-mean radiance instead of the CMF
                              // XYZ projection (which is ~0 outside 380-780,
                              // silently zeroing all non-visible energy).
                              // Mirrors the deleted MW megakernel
                              // (multiwavelength_kernel.cu:510-518).
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    // Thread 0 zeroes the per-pass queue counters BEFORE the early-outs
    // (its own slot may be alive). Same-stream ordering makes this visible
    // to the intersect/shade/shadow launches that follow, exactly like the
    // memsets it replaces.
    if (idx == 0 && count_out != nullptr) {
        *count_out    = 0;
        *shadow_count = 0;
        if (vol_count != nullptr) *vol_count = 0;   // pkg199 Stage 2
        // pkg258: reset the env NEE shadow queue count each pass (thread 0, same
        // same-stream ordering as *shadow_count). Null when env NEE is off.
        if (c_wfEnvNeeBinding.envShadowCount != nullptr)
            *c_wfEnvNeeBinding.envShadowCount = 0;
        #pragma unroll
        for (int m = 0; m < G_WF_NUM_MAT_TYPES; ++m) shade_counts[m] = 0;
    }
    if (idx >= state.num_active) return;
    if (state.path_alive[idx] != 0) return;

    // ---- Accumulate the dead path's radiance into ITS pixel (not the
    // slot index -- under regeneration slots host arbitrary pixels).
    GSampledSpectrum rad;
    rad.v[0] = state.color_0[idx];
    rad.v[1] = state.color_1[idx];
    rad.v[2] = state.color_2[idx];
    rad.v[3] = state.color_3[idx];
    bool hasRad = (rad.v[0] != 0.f) | (rad.v[1] != 0.f) |
                  (rad.v[2] != 0.f) | (rad.v[3] != 0.f);
    if (hasRad) {
        GVec3 xyz;
        if (useLuminanceOutput) {
            // pkg55-C7: band-mean radiance as neutral grey (the MW megakernel
            // luminance convention). No CMF projection — the CMFs are ~0
            // outside the visible band. No lum>20 clamp here either: the MW
            // kernel applied none in luminance mode, and the CPU naive
            // multiwavelength reference is the parity target.
            float L = 0.f;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) L += rad.v[i];
            L = fmaxf(0.f, L / float(G_SPECTRUM_SAMPLES));
            xyz = GVec3(L, L, L);
        } else {
            GSampledWavelengths lambdas;
            lambdas.lambda[0] = state.lambda_0[idx];
            lambdas.lambda[1] = state.lambda_1[idx];
            lambdas.lambda[2] = state.lambda_2[idx];
            lambdas.lambda[3] = state.lambda_3[idx];
            lambdas.pdf[0] = state.lambda_pdf_0[idx];
            lambdas.pdf[1] = state.lambda_pdf_1[idx];
            lambdas.pdf[2] = state.lambda_pdf_2[idx];
            lambdas.pdf[3] = state.lambda_pdf_3[idx];
            // pkg157: the always-on, whole-path `lum > 20` clamp that used to
            // live here has been REMOVED -- see gpu_clampContribMW calls in
            // intersectPathSlot / shadePathSlot / stageShadowKernel, which now
            // clamp direct vs indirect contributions independently, per
            // bounce, mirroring the CPU fix (Renderer::clampContribSpectral)
            // and the deleted MW megakernel's identical removal (PR #515,
            // commit 1af7eca).
            xyz = gpu_spectrum_to_xyz(rad, lambdas);
        }
        int pixel = state.pixel_index[idx];
        // Multiple slots can die holding the same pixel (different samples)
        // within one pass: atomic adds.
        atomicAdd(&accum_xyz[pixel * 3 + 0], xyz.x);
        atomicAdd(&accum_xyz[pixel * 3 + 1], xyz.y);
        atomicAdd(&accum_xyz[pixel * 3 + 2], xyz.z);
        // pkg131 — scalar-luminance half-buffer: even-indexed samples feed the
        // Dammertz convergence check (host reads accum as the full sum, halfLumSum
        // as the even-sample sum). Photon-caustic energy is added to both below
        // (#909). Zeroing color_* below is the double-add guard, shared.
        if (c_wfAdaptive.enabled && (state.sample_index[idx] & 1) == 0)
            atomicAdd(&c_wfAdaptive.halfLumSum[pixel], xyz.x + xyz.y + xyz.z);
        state.color_0[idx] = 0.f;
        state.color_1[idx] = 0.f;
        state.color_2[idx] = 0.f;
        state.color_3[idx] = 0.f;
    }
    // pkg55-C5 / pkg113: flush the photon caustic XYZ contrib (if any) to the
    // dead path's pixel. INDEPENDENT of hasRad -- a path can carry photon
    // energy with zero spectral radiance (e.g. no NEE-visible lights), and the
    // MW kernel adds photonXYZ to the sample unconditionally
    // (multiwavelength_kernel.cu:502). Zero after adding: a dead slot that is
    // NOT reclaimed below stays dead and re-enters this block next pass -- the
    // zeroing (like color_* above) is the double-add guard.
    {
        float photon_x = state.photon_xyz_x[idx];
        float photon_y = state.photon_xyz_y[idx];
        float photon_z = state.photon_xyz_z[idx];
        if (photon_x != 0.f || photon_y != 0.f || photon_z != 0.f) {
            int pixel = state.pixel_index[idx];
            atomicAdd(&accum_xyz[pixel * 3 + 0], photon_x);
            atomicAdd(&accum_xyz[pixel * 3 + 1], photon_y);
            atomicAdd(&accum_xyz[pixel * 3 + 2], photon_z);
            // #909: keep the adaptive half-buffer on the same sum as accum.
            if (c_wfAdaptive.enabled && (state.sample_index[idx] & 1) == 0)
                atomicAdd(&c_wfAdaptive.halfLumSum[pixel], photon_x + photon_y + photon_z);
            state.photon_xyz_x[idx] = 0.f;
            state.photon_xyz_y[idx] = 0.f;
            state.photon_xyz_z[idx] = 0.f;
        }
    }

    // pkg198 Stage 2: flush this dead slot's per-pass spectral accumulators to the
    // per-PIXEL XYZ pass buffer (accumulate-at-death, mirroring the beauty flush
    // above), then zero them for slot reuse. Runtime-gated — the fleet (passAccum
    // null) skips entirely, so the non-AOV regen kernel pays only one predicated
    // branch. Uses the SAME XYZ/grey conversion + slot lambdas as beauty, so
    // Σ_pass toXYZ(passAccum_p) == toXYZ(color) == beauty per pixel (sum-to-beauty
    // holds by construction: every color += site has a mirrored passAccum +=, and
    // spectrum→XYZ is linear).
    if (c_wfLpBinding.passAccum != nullptr) {
        const int pxi = state.pixel_index[idx];
        float* slotBase = c_wfLpBinding.passAccum
                        + (size_t)idx * (ASTRORAY_LP_NUM_PASSES * G_SPECTRUM_SAMPLES);
        GSampledWavelengths plam;
        plam.lambda[0] = state.lambda_0[idx]; plam.lambda[1] = state.lambda_1[idx];
        plam.lambda[2] = state.lambda_2[idx]; plam.lambda[3] = state.lambda_3[idx];
        plam.pdf[0] = state.lambda_pdf_0[idx]; plam.pdf[1] = state.lambda_pdf_1[idx];
        plam.pdf[2] = state.lambda_pdf_2[idx]; plam.pdf[3] = state.lambda_pdf_3[idx];
        for (int p = 0; p < ASTRORAY_LP_NUM_PASSES; ++p) {
            float* pb = slotBase + (size_t)p * G_SPECTRUM_SAMPLES;
            GSampledSpectrum pr;
            bool any = false;
            #pragma unroll
            for (int k = 0; k < G_SPECTRUM_SAMPLES; ++k) {
                pr.v[k] = pb[k];
                any = any || (pb[k] != 0.f);
                pb[k] = 0.f;
            }
            if (!any) continue;
            GVec3 pxyz;
            if (useLuminanceOutput) {
                float L = 0.f;
                for (int k = 0; k < G_SPECTRUM_SAMPLES; ++k) L += pr.v[k];
                L = fmaxf(0.f, L / float(G_SPECTRUM_SAMPLES));
                pxyz = GVec3(L, L, L);
            } else {
                pxyz = gpu_spectrum_to_xyz(pr, plam);
            }
            float* out = c_wfLpBinding.passXYZ
                       + ((size_t)pxi * ASTRORAY_LP_NUM_PASSES + p) * 3;
            atomicAdd(&out[0], pxyz.x);
            atomicAdd(&out[1], pxyz.y);
            atomicAdd(&out[2], pxyz.z);
        }
    }

    // ---- Claim the next work item; leave the slot dead when exhausted.
    int w = atomicAdd(work_counter, 1);
    if (w >= total_work) return;
    int pixel, sample;
    if (c_wfAdaptive.enabled) {
        // pkg131 — adaptive round: work items index the compacted active-pixel
        // list; the round contributes samples [baseSample, baseSample+perPixel).
        // total_work is numActive * samplesThisRound, so w/numActive is the
        // in-round sample offset. Count each claimed sample per pixel (the final
        // divide is per-pixel accum/sampleCount, not the uniform /samples).
        pixel  = c_wfAdaptive.activePixels[w % c_wfAdaptive.numActive];
        sample = c_wfAdaptive.baseSample + w / c_wfAdaptive.numActive;
        atomicAdd(&c_wfAdaptive.sampleCount[pixel], 1);
    } else {
        // Flat pool (byte-identical pre-pkg131): wave k = sample k for every pixel.
        // #909: baseSample offsets the photon-map rounds (0 for a single round).
        pixel  = w % numPixels;
        sample = c_wfAdaptive.baseSample + w / numPixels;
    }
    initPathSlot(idx, pixel, sample, state, cam, width, height, seed,
                 lambdaMin, lambdaMax);
    // pkg198 Stage 2: a reused slot hosts a fresh path — reset its locked category
    // so the new path's bounce-0 events attribute to PASS_EMISSION/PASS_ENVIRONMENT
    // (firstCat unset), not the previous path's lobe. The render-start memset seeds
    // the first wave; this covers every regeneration.
    if (c_wfLpBinding.passAccum != nullptr) {
        c_wfLpBinding.firstCat[idx] = G_LP_CAT_UNSET;
    }
}

void launchStageRegen(
    GPUWavefrontState& state,
    float* d_accum_xyz,
    int* d_work_counter,
    int total_work,
    int numPixels,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed,
    float lambdaMin,
    float lambdaMax,
    int* d_count_out,      // pkg55-C7: fused counter zeroing (nullptr = skip)
    int* d_shade_counts,
    int* d_shadow_count,
    int* d_vol_count,      // pkg199 Stage 2 (nullptr = skip)
    bool useLuminanceOutput)  // pkg55-C7: non-visible-band accumulation
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_regen_n7",
            (const void*)stageRegenKernel, blocks, threads);
        stageRegenKernel<<<blocks, threads>>>(
            state, d_accum_xyz, d_work_counter, total_work, numPixels,
            cam, width, height, seed,
            lambdaMin, lambdaMax,
            d_count_out, d_shade_counts, d_shadow_count, d_vol_count,
            useLuminanceOutput);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_regen launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

void launchStageShadow(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const float* d_nee_f, const int* d_nee_i,
    const int* d_shadow_queue, const int* d_shadow_count, int nee_capacity,
    const GTLASNode*  d_tlas,        // pkg55-C4 / pkg114
    const GInstance*  d_instances,   // pkg55-C4 / pkg114
    const GBLAS*      d_blas,        // pkg55-C4 / pkg114
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GVec3*      d_motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* d_materials,
    bool              useLuminanceOutput,   // pkg157
    float             clampDirect, float clampIndirect,  // pkg157
    const GCurveSegment* d_curveSegments,  // pkg225 Stage 3 (nullptr = no curves)
    bool              hasAlphaShadow,  // pkg253 (scene has a Principled alpha<1)
    bool              hasGridVolume,   // pkg269 (bounded media present)
    bool              volSegment,      // #929: volume-segment direct-light records
    bool              hw_occ)          // pkg299: occlusion from c_wfHwHits.occluded
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        // pkg225 Stage 3: curve shadow-occlusion axis. Non-curve scenes launch
        // stageShadowKernel<false,…> (curve leaf DCE'd, byte-identical); only curve
        // scenes launch <true,…>. pkg253: HasAlphaShadow axis — only scenes with a
        // Principled alpha<1 launch <…,true> (the transparent-shadow walk); the
        // fleet path stays <…,false> (binary occlusion, byte-identical). All four
        // specialisations are referenced so they land in the cubin.
        const bool hc = (d_curveSegments != nullptr);
        // pkg269: third axis. Grid-free scenes launch <..,..,false> (unchanged);
        // all eight specialisations are referenced so they land in the cubin.
        #define ASTRORAY_PKG269_SHADOW_KFN(G) \
            (hc ? (hasAlphaShadow ? (const void*)stageShadowKernel<true,  true,  G> \
                                  : (const void*)stageShadowKernel<true,  false, G>) \
                : (hasAlphaShadow ? (const void*)stageShadowKernel<false, true,  G> \
                                  : (const void*)stageShadowKernel<false, false, G>))
        // pkg299: HwOcc only for the binary-occlusion, curve-free kernels (the
        // transparent-shadow walk stays on the software BVH): 2 instantiations.
        const bool hw = hw_occ && !hc && !hasAlphaShadow;
        const void* kfn = hw ? (hasGridVolume ? (const void*)stageShadowKernel<false, false, true, true>
                                              : (const void*)stageShadowKernel<false, false, false, true>)
                             : hasGridVolume ? ASTRORAY_PKG269_SHADOW_KFN(true)
                                             : ASTRORAY_PKG269_SHADOW_KFN(false);
        #undef ASTRORAY_PKG269_SHADOW_KFN
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_shadow_n7", kfn, blocks, threads);
        #define ASTRORAY_PKG225_SHADOW_ARGS \
            state, hitBufs, d_nee_f, d_nee_i, \
            d_shadow_queue, d_shadow_count, nee_capacity, \
            d_tlas, d_instances, d_blas, \
            d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials, \
            useLuminanceOutput, clampDirect, clampIndirect, d_curveSegments, \
            (volSegment ? 1 : 0)
        #define ASTRORAY_PKG269_SHADOW_LAUNCH(G) \
            if (hc) { \
                if (hasAlphaShadow) stageShadowKernel<true,  true,  G><<<blocks, threads>>>(ASTRORAY_PKG225_SHADOW_ARGS); \
                else                stageShadowKernel<true,  false, G><<<blocks, threads>>>(ASTRORAY_PKG225_SHADOW_ARGS); \
            } else { \
                if (hasAlphaShadow) stageShadowKernel<false, true,  G><<<blocks, threads>>>(ASTRORAY_PKG225_SHADOW_ARGS); \
                else                stageShadowKernel<false, false, G><<<blocks, threads>>>(ASTRORAY_PKG225_SHADOW_ARGS); \
            }
        if (hw) {
            if (hasGridVolume) stageShadowKernel<false, false, true, true> <<<blocks, threads>>>(ASTRORAY_PKG225_SHADOW_ARGS);
            else               stageShadowKernel<false, false, false, true><<<blocks, threads>>>(ASTRORAY_PKG225_SHADOW_ARGS);
        } else if (hasGridVolume) { ASTRORAY_PKG269_SHADOW_LAUNCH(true) } else { ASTRORAY_PKG269_SHADOW_LAUNCH(false) }
        #undef ASTRORAY_PKG269_SHADOW_LAUNCH
        #undef ASTRORAY_PKG225_SHADOW_ARGS
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_shadow launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

// ---------------------------------------------------------------------------
// pkg258 - publish the frame's env-NEE binding into the __constant__ symbol.
void setWavefrontEnvNeeBinding(const GWavefrontEnvNeeBinding& binding)
{
    cudaMemcpyToSymbol(c_wfEnvNeeBinding, &binding, sizeof(GWavefrontEnvNeeBinding));
}

// #877 - publish the frame's set_light_nee(False) pure-BSDF flag.
void setWavefrontLightNeeOff(bool off)
{
    const int v = off ? 1 : 0;
    cudaMemcpyToSymbol(c_wfLightNeeOff, &v, sizeof(int));
}

// #873 - publish the frame's primary-ray clip planes.
void setWavefrontPrimaryClip(const GWavefrontPrimaryClip& clip)
{
    cudaMemcpyToSymbol(c_wfPrimaryClip, &clip, sizeof(GWavefrontPrimaryClip));
}

// pkg299 - publish the OptiX hardware-traversal side buffers.
void setWavefrontHwHitBinding(const GWavefrontHwHitBinding& binding)
{
    cudaMemcpyToSymbol(c_wfHwHits, &binding, sizeof(GWavefrontHwHitBinding));
}

// pkg258 - env NEE shadow-resolve launch (twin of launchStageShadow). Reads the
// env queue / arrays / HDRI from c_wfEnvNeeBinding, so only geometry pointers are
// passed. The kernel early-outs on an empty queue, so calling it every pass with
// env NEE off (envShadowCount==0) is a cheap no-op.
void launchStageEnvShadow(
    GPUWavefrontState& state,
    const GTLASNode*  d_tlas,
    const GInstance*  d_instances,
    const GBLAS*      d_blas,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GVec3*      d_motionVerts,
    bool              useLuminanceOutput,
    float             clampDirect, float clampIndirect,
    const GCurveSegment* d_curves,
    bool              hw_occ,          // pkg299: occlusion from c_wfHwHits.occluded
    const int*        d_hitPrimId)     // #1037
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    const bool hc = (d_curves != nullptr);
    const bool hw = hw_occ && !hc;
    astroray::gpu_profile::ScopedTimer _t(
        "wavefront_stage_env_shadow_pkg258",
        hw ? (const void*)stageEnvShadowKernel<false, true>
           : hc ? (const void*)stageEnvShadowKernel<true> : (const void*)stageEnvShadowKernel<false>,
        blocks, threads);
    #define ASTRORAY_PKG258_ENV_SHADOW_ARGS         state, d_tlas, d_instances, d_blas,         d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts,         useLuminanceOutput, clampDirect, clampIndirect, d_curves, d_hitPrimId
    if (hw)      stageEnvShadowKernel<false, true><<<blocks, threads>>>(ASTRORAY_PKG258_ENV_SHADOW_ARGS);
    else if (hc) stageEnvShadowKernel<true> <<<blocks, threads>>>(ASTRORAY_PKG258_ENV_SHADOW_ARGS);
    else         stageEnvShadowKernel<false><<<blocks, threads>>>(ASTRORAY_PKG258_ENV_SHADOW_ARGS);
    #undef ASTRORAY_PKG258_ENV_SHADOW_ARGS
    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        std::fprintf(stderr, "stage_env_shadow launch error: %s\n",
                     cudaGetErrorString(err));
        throw std::runtime_error(cudaGetErrorString(err));
    }
}
// ---------------------------------------------------------------------------
// pkg55-C2 MIS audit snapshot kernel. Runs the PRODUCTION intersect + shade
// halves for one bounce over every path with the deferred (parking) NEE
// branch enabled (nee_f != nullptr), so shadePathSlot records the real
// power-heuristic MIS pdfs into state.path_light_pdf / path_mis_pdf /
// path_mis_weight. This is the exact code the bucketed production pipeline
// runs (intersectPathSlot + shadePathSlot); it is invoked ONLY by the
// PostNEE_MIS snapshot harness, never by the render driver. The nee_f/nee_i/
// shadow buffers are throwaway parking scratch — the shadow trace is NOT run
// here; the audit inspects the shade-time MIS weight, not the occlusion.
// ---------------------------------------------------------------------------
template<bool HasPrincipled>  // pkg178 Stage-3b D4
__global__ void stageShadeNeeMisKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    float* nee_f, int* nee_i,
    int* shadow_queue, int* shadow_count, int nee_capacity,
    const GTLASNode*  tlas,        // pkg55-C4 / pkg114
    const GInstance*  instances,   // pkg55-C4 / pkg114
    const GBLAS*      blas,        // pkg55-C4 / pkg114
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GVec3*      motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    const GDedicatedLight* dedLights, int numDed,   // pkg89-wavefront (C7)
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth,
    bool              useLuminanceOutput,
    bool              enableNEE,
    float             clampDirect, float clampIndirect)  // pkg157
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= state.num_active) return;
    if (state.path_alive[idx] == 0) return;
    int matType = intersectPathSlot(idx, state, hitBufs, tlas, instances, blas,
                                    bvhNodes, prims, tris, spheres, motionVerts,
                                    materials, envMap, backgroundColor,
                                    hasBackgroundColor, worldMaxBounces,
                                    useLuminanceOutput, enableNEE,
                                    clampDirect, clampIndirect,
                                    lights, numLights, totalLightPower,
                                    dedLights, numDed, lightTree);  // pkg120+pkg181
    if (matType < 0) return;  // env miss / emissive hit: path died, no NEE.
    shadePathSlot<true, HasPrincipled>(idx, state, hitBufs, tlas, instances, blas,
                  bvhNodes, prims, tris, spheres, motionVerts,
                  materials, lights, numLights, totalLightPower,
                  dedLights, numDed, lightTree, max_depth,
                  nee_f, nee_i, shadow_queue, shadow_count, nee_capacity,
                  useLuminanceOutput, enableNEE,
                  clampDirect, clampIndirect,
                  astroray::photon::gpu::GPhotonGrid{}, false, 0.0f,
                  /*captureMis=*/true);  // pkg55-C7: snapshot harness captures
}

void launchStageShadeNeeMis(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    float* d_nee_f, int* d_nee_i,
    int* d_shadow_queue, int* d_shadow_count, int nee_capacity,
    const GTLASNode*  d_tlas,        // pkg55-C4 / pkg114
    const GInstance*  d_instances,   // pkg55-C4 / pkg114
    const GBLAS*      d_blas,        // pkg55-C4 / pkg114
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GVec3*      d_motionVerts, // pkg55-C4 / pkg88-C.0
    const ::GMaterial* d_materials,
    const ::GLight*    d_lights, int num_lights, float total_light_power,
    const GDedicatedLight* d_dedLights, int num_ded,   // pkg89-wavefront (C7)
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth,
    bool              useLuminanceOutput,
    bool              enableNEE,
    float             clampDirect, float clampIndirect,  // pkg157
    bool              hasPrincipled)  // pkg178 Stage-3b D4
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    // pkg178 Stage-3b D4: select the HasPrincipled specialization (see
    // launchStageShadeBucketed). Both referenced so both land in the cubin.
    if (hasPrincipled)
        stageShadeNeeMisKernel<true><<<blocks, threads>>>(
            state, hitBufs, d_nee_f, d_nee_i,
            d_shadow_queue, d_shadow_count, nee_capacity,
            d_tlas, d_instances, d_blas,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials,
            d_lights, num_lights, total_light_power,
            d_dedLights, num_ded, lightTree,
            envMap, backgroundColor, hasBackgroundColor, worldMaxBounces,
            max_depth, useLuminanceOutput, enableNEE,
            clampDirect, clampIndirect);
    else
        stageShadeNeeMisKernel<false><<<blocks, threads>>>(
            state, hitBufs, d_nee_f, d_nee_i,
            d_shadow_queue, d_shadow_count, nee_capacity,
            d_tlas, d_instances, d_blas,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials,
            d_lights, num_lights, total_light_power,
            d_dedLights, num_ded, lightTree,
            envMap, backgroundColor, hasBackgroundColor, worldMaxBounces,
            max_depth, useLuminanceOutput, enableNEE,
            clampDirect, clampIndirect);
    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        std::fprintf(stderr, "stage_shade_nee_mis launch error: %s\n",
                     cudaGetErrorString(err));
        throw std::runtime_error(cudaGetErrorString(err));
    }
}
}  // namespace astroray::wavefront

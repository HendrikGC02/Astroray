// stage_advance_device.cuh - device code + kernel templates of the wavefront
// one-bounce advance, split out of stage_advance.cu so the 128 shade variants
// can compile in parallel TUs (see the "Build-speed split" note near the end).
// The file-level design notes (stage order, RNG convention, references) stay in
// stage_advance.cu. __constant__ symbols are only DECLARED here (extern; legal
// under -rdc); each is DEFINED exactly once in stage_advance.cu with its host
// setter.
#pragma once
#include "astroray/gpu_shade_noinline.h"  // pkg300: ASTRORAY_SHADE_NOINLINE

#include "astroray/gpu_wavefront_state.h"
#include "astroray/gpu_types.h"
#include "astroray/shader_vm.h"  // pkg219b — op-VM program + svm_eval
#include "astroray/procedural_tex.h"  // #1007 — per-hit procedural point clamp
#include "astroray/shader_graph.h"  // pkg314 — GRAPH_MAT_SLOTS (graph-kernel outputs)
#include "astroray/gpu_materials.h"
#include "astroray/gpu_bvh.h"
#include "astroray/gpu_env_spectral.cuh"
#include "astroray/sampling/wavefront_rng_device.h"
#include "../profile.h"
#include "../gpu_spectral_tables.h"  // pkg55-C3: gpu_profile_reflectance
#include "astroray/gpu_photon_store.h"  // pkg55-C5 / pkg113: photonGridGatherKnn
#include "astroray/cryptomatte.h"  // pkg159: hash_to_float + atomic rank insert

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdio>
#include <stdexcept>

// pkg55-B' template-RNG arc: gpu_rng_uniform overload so the templated
// material/NEE samplers (gpu_materials.h, gpu_nee.cuh) draw directly from
// the per-path WavefrontRNG (PCG32) stream. Defined in namespace astroray
// so ADL finds it at template instantiation.
namespace astroray {
__device__ inline float gpu_rng_uniform(WavefrontRNG* rng) {
    return rng->Uniform();
}
}  // namespace astroray
using astroray::gpu_rng_uniform;

// pkg55-B' shadow stage: shared NEE thirds (header-inline since the
// template-RNG arc — one compiled implementation in both TUs).
#include "../gpu_nee.cuh"

// Non-inline XYZ wrapper exported by multiwavelength_kernel.cu (Session N+6)
// — spectrumToXYZ itself is TU-local inline over the constant CMF tables.
__device__ GVec3 gpu_spectrum_to_xyz(
    const GSampledSpectrum& s, const GSampledWavelengths& wl);

// Per-slot init from stage_init.cu (N+7 part 4, rdc-linked) — one generator
// of the init draws shared with stageInitKernel.
namespace astroray { namespace wavefront {
__device__ void initPathSlot(
    int slot, int pixel, int sample_idx,
    GPUWavefrontState& state,
    const GCameraParams& cam,
    int width, int height,
    uint64_t seed,
    float lambdaMin,
    float lambdaMax);
} }

namespace astroray::wavefront {

namespace {

constexpr int kRRDepth = 3;  // mirrors CPU path_kernel.cpp kRRDepth

// pkg55-C3: Rayleigh scattering scale for non-visible-band sky fallback.
// Mirrors multiwavelength_kernel.cu:76 (MW-kernel-local helper).
__device__ inline float rayleighScale(float lambda_nm) {
    float r = 550.f / lambda_nm;
    return r * r * r * r;
}

}  // namespace

// GMAT_LAMBERTIAN=0 .. GMAT_CLOSURE_GRAPH=6 (gpu_types.h GMaterialType).
constexpr int G_WF_NUM_MAT_TYPES = 7;

// pkg55-B' shadow stage: NEE park SoA layout (field-major: field*capacity+idx).
// Float fields: 0-2 origin, 3-5 wi, 6 maxDist, 7-10 the pre-resolved
// contribution throughput*f*wt/(lightPdf+eps) — everything except the
// emission spectrum, which needs the trace result (sphere frontFace).
// Int fields: 0 lightMatId, 1 isSphere. Mirrors Cycles' design: bsdf_eval
// is computed in shade BEFORE queuing intersect_shadow
// (kernel/integrator/shade_surface.h, integrate_surface_direct_light).
constexpr int G_WF_NEE_FLOATS = 11;
constexpr int G_WF_NEE_INTS   = 2;

// ---------------------------------------------------------------------------
// N+7: the one-bounce advance body, split at the post-emissive boundary into
// intersectPathSlot (intersect + env-miss + emissive; consumes NO RNG
// dimensions, so the cut preserves the RNG stream exactly) and
// shadePathSlot (NEE + RR + BSDF) -- one generator of the per-bounce math
// (design decision #9). The production scheduling is stageRegen ->
// stageIntersectQueued -> stageShadeBucketed -> stageShadow (Laine 2013
// sec. 4 compaction; Cycles X uses the same dense-active-queue structure).
// (Hygiene 2026-08-11: the caller-less dense/flat-queued reference kernels
// stageAdvanceKernel / stageAdvanceQueuedKernel and their composition
// wrapper advancePathSlot were removed.)
//
// pkg197 — first-hit denoise-guide AOV output binding (base-colour albedo +
// shading normal + depth). Published once per frame by the driver
// (setWavefrontGuideBinding) so the intersect stage writes the guides WITHOUT
// growing the kernel signature — same constant-memory rationale as
// c_wfTexBinding below (a signature pointer would bump CONSTANT[0]). All three
// pointers null == guides disabled (the ReSTIR/snapshot drivers never set it, so
// the `if (guide.albedo)` predicate below skips the write). The driver
// zero-inits the target buffers, so miss/sky pixels — which return before the
// write — keep the CPU miss convention (albedo 0, normal 0, depth 0).
extern __constant__ GWavefrontGuideBinding c_wfGuideBinding;

// pkg201 Stage 2 (Finding F, transparent film) — bounce-0 background-miss coverage
// accumulator, published ONCE per frame (setWavefrontMissCoverage), read by
// intersectPathSlot. For each primary-ray sample (bounce 0) that misses to the
// background, atomicAdd 1.0 into c_wfMissCoverage[pixel]; the driver then derives
// per-pixel alpha = clamp(1 - miss/samples, 0, 1) for transparent film. Null (the
// default — ReSTIR/snapshot drivers, and every non-transparent render) skips the
// add entirely → byte-identical, and it lives in the intersect stage so the
// REG-254 stageShadeBucketedKernel is untouched (the pkg197 guide-AOV precedent).
extern __constant__ float* c_wfMissCoverage;

// pkg199 Stage 1 — homogeneous world-volume medium (Beer-Lambert absorption).
// Published once per frame by cuda_wavefront_render (setWavefrontWorldVolume),
// read by intersectPathSlot (free-flight + lamp-MIS) and stageShadowKernel (NEE)
// at RUNTIME behind `if (c_worldVolume.hasVolume)`. Kept out of the
// REG-254-saturated stageShadeBucketedKernel entirely (which is therefore
// byte-identical) — the pkg197 guide-AOV precedent. Default-zero (hasVolume==0)
// so the snapshot/ReSTIR drivers that never publish it render as vacuum.
extern __constant__ GWorldVolume c_worldVolume;

// pkg269 — bounded (grid / homogeneous) media side table. Published once per
// frame by cuda_wavefront_render (setWavefrontGridVolumeBinding); read by
// intersectPathSlotT<..., HasGridVolume=true> (free flight), stageShadowKernel
// (per-λ ratio-tracking NEE transmittance, runtime `count > 0` gate) and the
// dedicated stageVolumeHeteroScatterKernel (stage_volume_hetero.cu). count==0
// (the default; the snapshot/ReSTIR drivers publish it explicitly) keeps every
// fleet kernel byte-identical.
extern __constant__ GWavefrontGridVolumeBinding c_wfGridVolume;

// pkg258 - environment-NEE side-table binding (see GWavefrontEnvNeeBinding).
// Published once per frame by cuda_wavefront_render (setWavefrontEnvNeeBinding).
// enabled==0 (the default) means the env-NEE generate body is never entered and
// the miss-leg env-MIS branch is skipped, so fleet renders are byte-identical and
// consume no extra RNG. Read by shadePathSlot (generate), intersectPathSlot (miss
// MIS weight + gate), stageEnvShadowKernel (resolve), and stageRegenKernel (per-
// pass env queue-count reset) -- all behind `c_wfEnvNeeBinding.enabled`.
extern __constant__ GWavefrontEnvNeeBinding c_wfEnvNeeBinding;

// #873: primary-ray clip planes (setWavefrontPrimaryClip), read by
// intersectPathSlotT at bounce 0 only. active 0 (default) = unclipped.
extern __constant__ GWavefrontPrimaryClip c_wfPrimaryClip;

// pkg299: OptiX hardware-traversal results (setWavefrontHwHitBinding), read only
// by the <HwHits=true> intersect and <HwOcc=true> shadow specialisations; the
// software-BVH kernels never reference it.
extern __constant__ GWavefrontHwHitBinding c_wfHwHits;

// pkg296: where bounded media start on this ray — the bounce-0 clip start
// (tNear) when a near clip beyond the 0.001 default is set, else 0.001. CPU
// twin: raytracer.h mediaT0 (Cycles camera.h moves ray->P by nearclip*D, so
// shade_volume never sees [0, nearclip)). Reuses the tNear already computed
// for the hit; no per-path state.
__device__ __forceinline__ float gpu_wfMediaStart(int bounce, float tNear)
{
    return (bounce == 0 && c_wfPrimaryClip.active && c_wfPrimaryClip.nearDist > 0.001f)
               ? tNear : 0.001f;
}

// #877: set_light_nee(False) = pure BSDF sampling: the path_tracer runs with
// enableNEE false (no surface / medium light sampling) and takes every emitter
// or lamp hit at w_B = 1 (CPU raytracer.h pkg265). 0 (default) keeps the
// naive-multiwavelength meaning of enableNEE false (emission only after
// camera / specular bounces). Read only by intersectPathSlotT.
extern __constant__ int c_wfLightNeeOff;

// pkg198 Stage 2 — light-path pass binding in constant memory (see
// GWavefrontLightPassBinding in gpu_types.h). Set once per frame by
// setWavefrontLightPassBinding; the shade/intersect kernels read it ONLY inside
// `if constexpr (HasLightPassAOVs)` (keeping the fleet <…,false> specializations
// byte-identical — the REGISTER PROBE result, PR #620), while the non-register-gated
// shadow/volume/regen kernels read it behind a runtime `passAccum != nullptr` guard.
// Declared here (before intersectPathSlotT) because both the intersect and shade
// kernels reference it, exactly like c_wfGuideBinding / c_worldVolume above.
extern __constant__ GWavefrontLightPassBinding c_wfLpBinding;

// pkg201 Stage 3 (Finding A) — Cycles per-type bounce limits (index 0=diffuse,
// 1=glossy, 2=transmission; -1 = unlimited). Published once per frame by
// cuda_wavefront_render (setWavefrontBounceLimits). shadePathSlot reads it only
// when a limit is set (≥0) — the all-unlimited default (this static initializer,
// used by every render that does not set per-type bounces AND by the
// snapshot/ReSTIR drivers that never publish) makes the per-type block a no-op,
// so the fleet stageShadeBucketedKernel stays byte-identical (register-probe
// gate). Counters ride the GPUWavefrontState.per_type_bounce SoA field, not this
// symbol, mirroring the c_wfTexBinding side-table pattern (pkg186/pkg223).
extern __constant__ int c_wfBounceLimit[3];

// pkg201 Stage 3 (Finding E) — native caustic toggles (index 0=reflective,
// 1=refractive; 1=allow, 0=cull). Published once per frame by
// cuda_wavefront_render (setWavefrontCausticGate). Both-allow (this static
// default, and every render that does not turn a toggle off) makes shadePathSlot
// skip the caustic-cull block entirely → the fleet kernel stays byte-identical.
extern __constant__ int c_wfCausticGate[2];

// pkg224 — progressive (hash-Owen Sobol') sampler opt-in. Published once per
// frame by cuda_wavefront_render (setWavefrontSamplerMode). 0 = PCG32 white
// noise (this static default, and every render that leaves the sampler on
// "white" plus the snapshot/ReSTIR drivers that never publish) → the shade
// kernel's WavefrontRNG::Uniform() takes the untouched PCG32 path, byte-identical
// to pre-pkg224 (register-probe gate). 1 = progressive Sobol' (opt-in). This is
// a plain runtime flag (NOT a template axis), the pkg201-S3/pkg186 pattern.
extern __constant__ int c_wfSamplerMode;

// pkg225 Stage 4 — scene-has-any-principled-hair flag. Published once per frame by
// cuda_wavefront_render (setWavefrontHairEnabled). 0 (this static default, and
// every non-hair render) makes shadePathSlot skip the hair uvTangent/hairV SoA
// restore ENTIRELY, so the fleet <…> shade kernel stays register-byte-identical.
// The GMAT_HAIR_PRINCIPLED BSDF math is reached through the ordinary material-type
// dispatch and lives in __noinline__ device functions (gpu_hair.cuh), so a curve-
// less scene never executes it and its register pressure never enters the fleet
// kernel. Plain runtime flag, NOT a template axis (architect-pinned).
extern __constant__ int c_hasHair;

// #962 — textured Emission Color flag, published once per frame by
// cuda_wavefront_render (setWavefrontEmissionTexture). 1: some emissive material
// carries a matTexId, so c_wfTexBinding is valid this frame (an emitter's op-VM
// chain is baked host-side, scene_upload.cu). 0 (the default, reset by
// every other wavefront entry point) keeps the intersect-stage emissive hit and
// the shadow-stage NEE resolve on the flat mean-colour path: bit-identical output.
// A plain runtime flag, not a template axis: the fetch lives in __noinline__
// helpers (memory noinline-runtime-flag-avoids-shade-spill).
extern __constant__ int c_wfEmissionTex;
// #962 — global prim ids >= this belong to instanced BLASes (pkg114: flat-scene
// prims occupy offset 0), whose triangles are object-space while the hit point is
// world-space: those keep the flat mean (DEGRADED, reported host-side).
extern __constant__ int c_wfEmissionFlatPrims;

// #991 — Light Path binding (GWavefrontLightPathBinding, astroray/light_path.h),
// published once per frame by setWavefrontLightPathBinding. sw == nullptr (every
// scene without a Light Path node) skips the intersect remap and the shadow
// resolve; enabled == 0 skips the lp_state updates (shade / volume stages).
extern __constant__ GWavefrontLightPathBinding c_wfLightPath;

// #991 — Light Path services, defined ONCE out of line in shading_inputs_eval.cu
// (one call per site here, not the body: build time + register isolation).
// gpu_lpContext: the hit's PathContext; gpu_lpRemap: the Mix Shader closure-
// switch child (intersect, only when c_wfLightPath.sw); gpu_lpAdvance /
// gpu_lpVolume: the per-bounce lp_state update (only when c_wfLightPath.enabled).
__device__ astroray::lightpath::PathContext gpu_lpContext(
    unsigned lpState, int bounce, float t, GVec3 dir);
__device__ int gpu_lpRemap(int matId, unsigned lpState, int bounce, float t, GVec3 dir);
__device__ unsigned gpu_lpAdvance(unsigned lpState, const ::GMaterial* mat,
                                  GVec3 wo, GVec3 n, GVec3 wi, bool isDelta);
__device__ unsigned gpu_lpVolume(unsigned lpState);

struct GProgInputTexel { GVec3 c; bool ok; };
// Defined after c_wfTexBinding below.
static __device__ ASTRORAY_SHADE_NOINLINE inline GProgInputTexel gpu_emissionTexel(
    GVec3 point, int primId, const GPrimitive* prims, const GTriangle* tris,
    const GSphere* spheres, int matId);


// pkg224 — Sobol' direction-vector table in __constant__ memory (8 KB). Filled
// from the host constexpr kSobolMatrices32 by setWavefrontSamplerMode(true)
// (only when the progressive sampler is enabled); the byte-identical PCG32
// default never touches it. Read by SobolDirect() in the shade + init kernels.
extern __constant__ uint32_t c_sobolMatrices[kSobolNumDims][kSobolMatrixSize];

// pkg131 — zero-knob adaptive sampling binding, published once per round by
// cuda_wavefront_render (setWavefrontAdaptiveBinding). enabled=0 (the default)
// leaves stageRegenKernel on the byte-identical flat-pool mapping.
extern __constant__ GWavefrontAdaptiveBinding c_wfAdaptive;

// #909 - photon-map split (setWavefrontPhotonSplit). chain == nullptr: inert.
extern __constant__ GWavefrontPhotonSplit c_wfPhotonSplit;

// #909 - transmissive caustic caster (mirror of photon_caustic.cu pc_isTransmissive).
__device__ inline bool wf_isPhotonCaster(const ::GMaterial& m) {
    if (m.type == GMAT_DIELECTRIC || m.type == GMAT_THIN_GLASS) return true;
    if (m.type == GMAT_CLOSURE_GRAPH) {
        if (m.transmission > 0.0f) return true;
        for (int i = 0; i < m.closureCount; ++i)
            if (m.closures[i].type == GCLOSURE_DIELECTRIC_TRANSMISSION ||
                m.closures[i].type == GCLOSURE_THIN_GLASS)
                return true;
    }
    return false;
}

// Splat a spectral contribution into slot `idx`'s pass `passIdx` accumulator.
// Per-slot (mirrors the color SoA — accumulate-at-death like beauty), so no atomics:
// one path owns one slot for the duration of a bounce, exactly like the color_/
// throughput_ SoA writes. RMW into global memory — the caller holds only the
// constant-mem base pointer + the already-live `c`, not N register accumulators
// (this is what keeps the pass writes off the register budget).
__device__ __forceinline__ void lpAccumulate(int idx, int passIdx,
                                              const GSampledSpectrum& c) {
    float* base = c_wfLpBinding.passAccum
                + (size_t)idx * (ASTRORAY_LP_NUM_PASSES * G_SPECTRUM_SAMPLES)
                + (size_t)passIdx * G_SPECTRUM_SAMPLES;
    #pragma unroll
    for (int k = 0; k < G_SPECTRUM_SAMPLES; ++k) base[k] += c.v[k];
}

// firstCat "not yet locked" sentinel (device twin of the CPU firstCat == -1).
constexpr unsigned char G_LP_CAT_UNSET = 0xFFu;
// RenderPassIndex mirror (raytracer.h) — the two standalone buckets the light-path
// partition writes by name; the lobe passes are computed as cat*3+{0,1}.
constexpr int G_LP_PASS_EMISSION    = 11;  // == PASS_EMISSION
constexpr int G_LP_PASS_ENVIRONMENT = 12;  // == PASS_ENVIRONMENT

// Pass index for a directly-visible EMISSION/BACKGROUND event, given the locked
// category (Cycles film_write_emission_or_background_pass, Apache-2.0). Not yet
// locked (camera-visible) → the standalone PASS_EMISSION / PASS_ENVIRONMENT bucket;
// after a bounce → the first category's INDIRECT pass. `emissionBucket` selects
// PASS_EMISSION (11) vs PASS_ENVIRONMENT (12).
__device__ __forceinline__ int lpEmitOrBgPass(unsigned char cat, int emissionBucket) {
    return (cat == G_LP_CAT_UNSET) ? emissionBucket : ((int)cat * 3 + 1);
}

// gpu_material_is_glossy: moved to gpu_material_class.cuh (#991, shared with
// shading_inputs_eval.cu).
#include "gpu_material_class.cuh"

// pkg199 Stage 1 — spectral Beer-Lambert transmittance exp(-sigma_t·d) per
// wavelength through the homogeneous world medium (PBRT-v4 §11.3; Cycles
// kernel/integrator/volume.h). Spectral discipline: upsample the reflectance-like
// tint through the JH albedo LUT (GSPEC_RGB_ALBEDO), THEN Beer-Lambert per-λ —
// identical to the CPU twin Renderer::worldTransmittanceSpectral, so CPU↔GPU
// parity holds by construction. Caller guards on c_worldVolume.hasVolume.
__device__ inline GSampledSpectrum gpu_worldTransmittanceMW(
    float dist, const GSampledWavelengths& lambdas)
{
    GSampledSpectrum tr;
    // pkg199: dist <= 0 OR a distant/infinite sentinel (geomDist==0 for distant
    // NEE; a huge lampT for a distant lamp; DistantLight's FLT_MAX) => Tr=1,
    // treated like an env-miss (Stage-1 infinite-segment convention). 1e18 is far
    // above any scene extent, below FLT_MAX — finite lights keep Beer-Lambert.
    if (c_worldVolume.density <= 0.f || dist <= 0.f || dist >= 1e18f) {
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) tr.v[i] = 1.f;
        return tr;
    }
    GSampledSpectrum sigmaColor = gpu_rgbToSampledSpectrum(
        GVec3(c_worldVolume.colorR, c_worldVolume.colorG, c_worldVolume.colorB),
        lambdas, GSPEC_RGB_ALBEDO);
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        float sigmaT = fmaxf(0.f, sigmaColor.v[i]) * c_worldVolume.density;
        tr.v[i] = __expf(-sigmaT * dist);
    }
    return tr;
}

// pkg199 Stage 2 — per-λ extinction σ_t[λ] = upsample(color)[λ]·density (the same
// quantity gpu_worldTransmittanceMW exponentiates; device twin of the CPU
// Renderer::worldSigmaT). Caller guards on c_worldVolume.hasVolume.
__device__ inline GSampledSpectrum gpu_worldSigmaT(const GSampledWavelengths& lambdas)
{
    GSampledSpectrum sigmaColor = gpu_rgbToSampledSpectrum(
        GVec3(c_worldVolume.colorR, c_worldVolume.colorG, c_worldVolume.colorB),
        lambdas, GSPEC_RGB_ALBEDO);
    GSampledSpectrum s;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
        s.v[i] = fmaxf(0.f, sigmaColor.v[i]) * c_worldVolume.density;
    return s;
}

// pkg199 Stage 2 — gpu_phaseHG / gpu_sampleHG / G_WF_VOL_DIM_SALT /
// gpu_freeflightUniform live in src/gpu/gpu_volume_phase.cuh since pkg269
// (moved verbatim; shared with stage_volume_hetero.cu).
#include "../gpu_volume_phase.cuh"

// intersectPathSlotT returns -1 when the path died, else the GMaterialType
// of the hit (0..GMAT_CLOSURE_GRAPH) for shade-queue bucketing. The hit
// record is parked in GPUWavefrontHitBuffers SoA at the slot index.
//
// pkg199 Stage 2 — templated on HasWorldScatter (the established fleet-isolation
// pattern, pkg178/184/189): the medium free-flight decision block is behind
// `if constexpr (HasWorldScatter)`, so the fleet <false> specialization compiles
// it out ENTIRELY and returns to the pre-pkg199 register footprint (127 REG →
// 2 blocks/SM at 256 threads; the always-present form measured 130 → 1 block →
// a cooled+bracketed +3.3% fog-free fleet regression). Only scattering fog scenes
// launch <true> (which pays the 130, but they are scattering-bound anyway). The
// non-template `intersectPathSlot` symbol below forwards to <false> so the
// cross-TU callers (ReSTIR primary, MIS-audit; both scatter=0) link unchanged.
template<bool HasWorldScatter, bool HasLightPassAOVs = false,
         bool HasCurves = false,  // pkg225 Stage 3 — curve-leaf isolation axis
         bool HasGridVolume = false,  // pkg269 — bounded-media (NanoVDB) isolation axis
         bool HwHits = false>  // pkg299 — hit precomputed by the OptiX closest-hit launch
__device__ int intersectPathSlotT(
    int idx,
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
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
    // pkg120: light data for the two-sided-MIS emissive-hit reconstruction.
    const ::GLight*   lights, int numLights, float totalLightPower,
    // pkg181: dedicated lamps for the BSDF-ray lamp-intersection pass.
    const GDedicatedLight* dedLights, int numDed,
    GLightTreeView    lightTree,
    // pkg225 Stage 3 — device curve segments (nullptr = no curves; the curve
    // leaf inside gpu_tlas_hit → gpu_bvh_hit is guarded on this pointer).
    const GCurveSegment* curves = nullptr)
{
    const int bounce = state.bounce[idx];

    // ---- Reconstruct live path state from SoA (already-normalized ray
    // direction restored verbatim — the Phase A.1 ulp rule).
    GRay ray;
    ray.origin = GVec3(state.ray_origin_x[idx], state.ray_origin_y[idx],
                       state.ray_origin_z[idx]);
    ray.direction = GVec3(state.ray_direction_x[idx], state.ray_direction_y[idx],
                          state.ray_direction_z[idx]);
    // pkg55-C4: deformation-motion time (pkg88-C.0). Sampled once at init,
    // carried through all bounces (mirrors MW kernel multiwavelength_kernel.cu:361).
    ray.time = state.path_time[idx];

    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[idx];
    lambdas.lambda[1] = state.lambda_1[idx];
    lambdas.lambda[2] = state.lambda_2[idx];
    lambdas.lambda[3] = state.lambda_3[idx];
    lambdas.pdf[0] = state.lambda_pdf_0[idx];
    lambdas.pdf[1] = state.lambda_pdf_1[idx];
    lambdas.pdf[2] = state.lambda_pdf_2[idx];
    lambdas.pdf[3] = state.lambda_pdf_3[idx];

    GSampledSpectrum throughput;
    throughput.v[0] = state.throughput_0[idx];
    throughput.v[1] = state.throughput_1[idx];
    throughput.v[2] = state.throughput_2[idx];
    throughput.v[3] = state.throughput_3[idx];

    GSampledSpectrum color;
    color.v[0] = state.color_0[idx];
    color.v[1] = state.color_1[idx];
    color.v[2] = state.color_2[idx];
    color.v[3] = state.color_3[idx];

    bool wasSpecular = state.was_specular[idx] != 0;

    // ---- Intersect (CPU: bvh->hit; ray direction NOT renormalized).
    // This half consumes no RNG dimensions; state.rng_dimension is untouched.
    // pkg55-C4 / pkg114: route through gpu_tlas_hit when TLAS exists (two-level
    // traversal for instanced scenes). Null-TLAS fallback (tlas==nullptr) routes
    // to the single-level gpu_bvh_hit path inside gpu_tlas_hit, so static scenes
    // stay byte-identical (pkg114 inc-1 identity test).
    GHitRecord rec;
    // #873: camera clip planes bound the bounce-0 hit only, exactly the CPU
    // raytracer.h tMin/tMax (view-axis depth / dot(D, forward), dot floored at
    // 1e-6). The origin stays at the camera, so media, lamp hits and the depth
    // AOV see the same segment as on the CPU.
    float tNear = 0.001f, tFar = 1e30f;
    if (bounce == 0 && c_wfPrimaryClip.active) {
        const float zInv = 1.f / fmaxf(1e-6f, ray.direction.dot(GVec3(
            c_wfPrimaryClip.fwdX, c_wfPrimaryClip.fwdY, c_wfPrimaryClip.fwdZ)));
        tNear = fmaxf(0.001f, c_wfPrimaryClip.nearDist * zInv);
        if (c_wfPrimaryClip.hasFar) tFar = c_wfPrimaryClip.farDist * zInv;
    }
    bool hit;
    if constexpr (HwHits) {
        // pkg299: OptiX traversed [tNear, tFar] already (same bounds, computed by
        // __raygen__closest); rebuild the record with the software path's helpers.
        hit = gpu_hw_hit_record(c_wfHwHits.t[idx], c_wfHwHits.prim[idx],
                                c_wfHwHits.u[idx], c_wfHwHits.v[idx], c_wfHwHits.inst[idx],
                                instances, blas, prims, tris, ray, rec);
    } else {
        // #1037: a continuation ray leaves the previous vertex's prim, still in
        // hit_prim_id (written by the previous intersect; reset to -1 at a medium
        // scatter vertex). Only the HasCurves curve leaf reads it.
        int skipPrim = -1;
        if constexpr (HasCurves) {
            if (bounce > 0) skipPrim = hitBufs.hit_prim_id[idx];
        }
        hit = gpu_tlas_hit<HasCurves>(tlas, instances, blas, bvhNodes, prims, tris, spheres,
                                      ray, tNear, tFar, rec, motionVerts, curves, skipPrim);
    }

    // pkg199 Stage 2 — homogeneous medium free-flight scatter DECISION (Option A:
    // the cheap decision + queue routing lives here; the register-heavy scatter
    // processing — phase NEE + HG continuation — lives in the dedicated
    // stageVolumeScatterKernel, so this kernel's footprint grows only by the
    // decision). Device twin of the CPU pathTraceSpectral medium block, gated on
    // the SAME condition so the scatter==0 path is byte-identical Stage-1. PBRT-v3
    // HomogeneousMedium::Sample (BSD): per-channel selection distance sampling,
    // balance-heuristic pdf averaged over the spectral channels. Runs BEFORE the
    // lamp-MIS / emission / role-1 blocks so a scatter intercepts the segment
    // exactly like the CPU top-of-loop medium block.
    // HasWorldScatter folds this to a compile-time false in the fleet <false>
    // kernel, so the block below is removed and the role-1/role-3 gates collapse
    // to their Stage-1 form (byte-identical).
    // pkg269 — bounded grid/homogeneous medium free flight (device twin of the
    // CPU pathTraceSpectral pkg268/pkg270 block: nearest entered medium on the
    // segment [0.001, surfaceT], hero-wavelength spectral-MIS tracking with
    // per-path r_u lanes, emission at the null-collision vertices). Compiled out
    // of the fleet <..., HasGridVolume=false> kernels entirely; runs after the
    // lamp pass (#929, CPU #925 order) and BEFORE the world-volume block and the
    // emission/env legs so a scatter or an absorption intercepts the segment.
    // pkg271 — volume_bounces exhausted (Cycles PATH_RAY_TERMINATE_AFTER_TRANSPARENT,
    // flag set by a volume-scatter kernel in per_type_bounce byte 3): media only
    // attenuate + emit, and a non-emissive surface hit ends the path below. Only
    // the <HasGridVolume | HasWorldScatter> kernels read it; in the fleet <false>
    // kernels volTerm is a compile-time false.
    bool volTerm = false;
    if constexpr (HasGridVolume || HasWorldScatter)
        volTerm = gpu_volumeTerminateAfter(state.per_type_bounce, idx,
                                           c_wfGridVolume.volumeBounceCap);
    // pkg181: dedicated-light visibility to BSDF rays (Cycles lights_intersect
    // parity) — device twin of production pathTraceSpectral. Lamps are invisible
    // to camera rays (bounce == 0). Placed in the INTERSECT stage (this kernel),
    // NOT the REG:254-saturated shade stage (memory
    // wavefront-shade-kernels-register-saturated). Emission + MIS mirror the
    // emissive-Hittable block below (wB = 1 after specular / NEE off; the power
    // heuristic otherwise; naive mode = enableNEE false takes specular only).
    // #903: bounce 0 tests only cameraVisible lamps (sky-texture sun disc).
    // pkg288 (#915): a lamp hit is not a vertex — Cycles integrator_shade_light
    // (kernel/integrator/shade_light.h, Apache-2.0) adds it and re-intersects
    // from t_lamp. Every lamp on [0.001, surfaceT) adds in t order (strict tMin
    // skips the lamp just added, cap 4 = CPU kMaxLampPassthrough), then the path
    // continues to the surface / env. Runs BEFORE the fog free flight, which no
    // longer stops at lamps; each lamp's emission carries Tr(lampT) explicitly.
    // The bounce-0 sun disc no longer counts miss coverage here: the continued
    // ray misses below and counts it once.
    if (numDed > 0) {
        const float surfaceT = hit ? rec.t : 1e30f;
        float lampTMin = 0.001f;
        bool lampAdded = false;
        for (int k = 0; k < 4; ++k) {
            float lampT, lampScale;
            int lampIdx = gpu_dedicated_intersect_closest(
                dedLights, numDed, ray.origin, ray.direction, lampTMin, surfaceT,
                &lampT, &lampScale, bounce == 0);
            if (lampIdx < 0) break;
            lampTMin = lampT;
            // pkg218: baked device SPD for non-RGB emission modes (gpu_nee_resolve twin).
            int profIdx = dedLights[lampIdx].emissionProfileIndex;
            GSampledSpectrum Le;
            if (dedLights[lampIdx].hasDiscProfile) {
                // #946: Cycles sun-disc profile (CPU DistantLight::intersect twin),
                // out of line (gpu_nee.cuh) so the intersect kernel stays at baseline.
                Le = gpu_disc_profile_Le(&dedLights[lampIdx], ray.direction, &lambdas, lampScale);
            } else if (profIdx >= 0) {
                for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                    Le.v[i] = gpu_emission_profile(profIdx, lambdas.lambda[i]) * lampScale;
            } else {
                Le = gpu_rgbToSampledSpectrum(dedLights[lampIdx].emissionRGB, lambdas,
                                              GSPEC_RGB_ILLUMINANT) * lampScale;  // #1012
            }
            // #909: receiver -> glass (exited) -> a photon-emitting light is
            // already in the bounce-0 gather; drop it here (no double count).
            if (bounce > 0 && lampIdx < 32 &&
                ((c_wfPhotonSplit.lampMask >> lampIdx) & 1u) &&
                c_wfPhotonSplit.chain != nullptr && c_wfPhotonSplit.chain[idx] == 3)
                Le = GSampledSpectrum(0.f);
            if (!(Le.maxValue() > 0.f)) continue;
            // pkg199 role 3: attenuate over the origin→lamp segment (lampT).
            if (c_worldVolume.hasVolume)
                Le *= gpu_worldTransmittanceMW(lampT, lambdas);
            // #929 (CPU #925 twin): bounded media too. This pass runs before their
            // free flight, so the lamp carries Tr(lampT) explicitly instead of the
            // flight's survival to the surface (which under-counted a lamp inside
            // a medium box).
            if constexpr (HasGridVolume) {
                if (c_wfGridVolume.count > 0) {
                    for (int m = 0; m < c_wfGridVolume.count; ++m) {
                        float s0, s1;
                        if (gpu_gridAabbOverlap(c_wfGridVolume.media[m], ray.origin, ray.direction,
                                                gpu_wfMediaStart(bounce, tNear), lampT, s0, s1))
                            Le *= gpu_gridVolumeTransmittance(
                                m, ray.origin, ray.direction, s0, s1, lambdas,
                                state.rng_pixel[idx], state.rng_sample[idx], state.rng_seed[idx],
                                gpu_segSalt(bounce, 10 + m));
                    }
                }
            }
            GSampledSpectrum contrib(0.f);
            if (bounce == 0 || wasSpecular || c_wfLightNeeOff) {  // #877
                contrib = throughput * Le;                 // w_B = 1
            } else if (enableNEE) {
                GVec3 misNormalPrev(state.path_mis_nx[idx], state.path_mis_ny[idx],
                                    state.path_mis_nz[idx]);
                // #961: medium vertex -> the segment its NEE light was picked for.
                const float misSegT = (state.env_nee_sampled_prev[idx] == 2)
                                    ? state.path_mis_dt[idx] : 0.f;
                float lp = gpu_dedicated_reconstruct_pdf(
                    dedLights, numDed, totalLightPower, ray.origin, ray.direction,
                    lightTree, numLights, misNormalPrev, lampIdx, misSegT);  // #912
                float wB = gpu_mw_powerHeuristic(state.path_bsdf_pdf[idx], lp);
                contrib = throughput * Le * wB;
            }
            // naive mode (enableNEE == false, non-specular): no NEE leg to
            // complement, so nothing is added — mirrors the emissive block.
            GSampledSpectrum lampContrib = gpu_clampContribMW(
                contrib, lambdas, bounce - 1,   // #860: emission hit = Cycles bounce-1
                clampDirect, clampIndirect, useLuminanceOutput);
            color += lampContrib;
            lampAdded = true;
            // pkg198 Stage 2: continuation-ray lamp -> firstCat's INDIRECT pass
            // (CPU lampPass = (firstCat<0?0:firstCat)*3+1).
            if constexpr (HasLightPassAOVs) {
                unsigned char cat = c_wfLpBinding.firstCat[idx];
                // #903: camera-visible sky disc -> PASS_ENVIRONMENT (CPU twin).
                int lampPass = (bounce == 0) ? G_LP_PASS_ENVIRONMENT
                             : (cat == G_LP_CAT_UNSET ? 0 : (int)cat) * 3 + 1;
                lpAccumulate(idx, lampPass, lampContrib);
            }
        }
        if (lampAdded) {
            state.color_0[idx] = color.v[0];
            state.color_1[idx] = color.v[1];
            state.color_2[idx] = color.v[2];
            state.color_3[idx] = color.v[3];
        }
    }

    if constexpr (HasGridVolume) if (c_wfGridVolume.count > 0) {
        const float surfaceT = hit ? rec.t : 1e30f;
        // #929 (CPU #925 boundedSegmentDirect twin): one direct-light distance on
        // the media hull of [0.001, surfaceT], decoupled from the flight below
        // (Kulla & Fajardo 2012; Cycles shade_volume.h). Parked into segment slot
        // 0 for the shadow stage; uses the pre-flight throughput.
        if (enableNEE && !volTerm)
            gpu_volumeSegmentDirect(idx, bounce, 0, ray.origin, ray.direction,
                                    gpu_wfMediaStart(bounce, tNear), surfaceT,
                                    GSampledSpectrum(0.f), throughput, lambdas, 0.f, 0.f,
                                    prims, tris, spheres, lights, numLights, totalLightPower,
                                    dedLights, numDed, lightTree, state.rng_pixel[idx],
                                    state.rng_sample[idx], state.rng_seed[idx]);
        // r_u lanes live in the side table (not GPUWavefrontState). A path starts
        // at bounce 0 with r_u = 1: reset there (no regen-kernel change needed).
        const int ruCap = c_wfGridVolume.capacity;
        float* const ruLane = c_wfGridVolume.ru;
        if (bounce == 0)
            for (int l = 0; l < G_SPECTRUM_SAMPLES; ++l) ruLane[l * ruCap + idx] = 1.f;
        // #842: every medium on [0.001, surfaceT], swept in AABB-boundary order
        // (device twin of astroray::volume::spectralTrackSegment; was: only the
        // nearest-entered medium). One medium on a piece => gpu_gridVolumeTrack
        // (single-medium scenes byte-identical); several => the overlap flight.
        bool entered = false;
        int ev = 0, mi = -1;
        float tEv = 0.f;
        GSampledSpectrum ru, beta, emission(0.f);
        uint32_t draw = 0;
        const uint32_t salt = gpu_gridTrackSalt(bounce);   // #828 disjoint fields
        float cursor = gpu_wfMediaStart(bounce, tNear);  // pkg296 camera clip
        while (cursor < surfaceT) {
            uint32_t mask = 0u;
            int first = -1, n = 0;
            float segEnd = surfaceT;
            bool later = false;
            for (int k = 0; k < c_wfGridVolume.count; ++k) {
                float t0, t1;
                if (!gpu_gridAabbOverlap(c_wfGridVolume.media[k], ray.origin, ray.direction,
                                         cursor, surfaceT, t0, t1))
                    continue;
                if (t0 > cursor) { segEnd = fminf(segEnd, t0); later = true; }
                else if (t1 > cursor) {
                    segEnd = fminf(segEnd, t1);
                    mask |= 1u << k;
                    if (first < 0) first = k;
                    ++n;
                }
            }
            if (n == 0) {
                if (!later) break;
                cursor = segEnd;
                continue;
            }
            if (!entered) {
                entered = true;
                for (int l = 0; l < G_SPECTRUM_SAMPLES; ++l) ru.v[l] = ruLane[l * ruCap + idx];
                beta = throughput * gpu_heroAverage(ru, lambdas);
            }
            if (n == 1) {
                mi = first;
                ev = gpu_gridVolumeTrack(first, ray.origin, ray.direction, cursor, segEnd,
                                         lambdas, beta, ru, emission, tEv,
                                         state.rng_pixel[idx], state.rng_sample[idx],
                                         state.rng_seed[idx], salt, draw, volTerm);
            } else {
                ev = gpu_gridVolumeTrackOverlap(mask, ray.origin, ray.direction, cursor, segEnd,
                                                lambdas, beta, ru, emission, tEv, mi,
                                                state.rng_pixel[idx], state.rng_sample[idx],
                                                state.rng_seed[idx], salt, draw, volTerm);
            }
            if (ev != 0) break;
            cursor = segEnd;
        }
        if (entered) {
            if (emission.maxValue() > 0.f) {
                // Volume emission along the flight (pkg270): Emission pass when
                // directly visible, else <firstCat>_INDIRECT (surface-emission rule).
                GSampledSpectrum ce = gpu_clampContribMW(
                    emission, lambdas, bounce - 1, clampDirect, clampIndirect, useLuminanceOutput);  // #860
                color += ce;
                if constexpr (HasLightPassAOVs) {
                    unsigned char cat = c_wfLpBinding.firstCat[idx];
                    lpAccumulate(idx, lpEmitOrBgPass(cat, G_LP_PASS_EMISSION), ce);
                }
                state.color_0[idx] = color.v[0]; state.color_1[idx] = color.v[1];
                state.color_2[idx] = color.v[2]; state.color_3[idx] = color.v[3];
            }
            {
                float rAvg = gpu_heroAverage(ru, lambdas);
                throughput = (rAvg > 0.f) ? beta * (1.f / rAvg) : GSampledSpectrum(0.f);
            }
            for (int l = 0; l < G_SPECTRUM_SAMPLES; ++l) ruLane[l * ruCap + idx] = ru.v[l];
            state.throughput_0[idx] = throughput.v[0];
            state.throughput_1[idx] = throughput.v[1];
            state.throughput_2[idx] = throughput.v[2];
            state.throughput_3[idx] = throughput.v[3];
            if (ev == 1) {                       // absorbed: the path ends here
                state.path_alive[idx] = 0;
                return -1;
            }
            if (ev == 2) {                       // scattered at P: hetero queue
                // Snapshot semantics as pkg199: P becomes ray_origin, ray_direction
                // stays the incoming direction (woMedium = -direction downstream).
                GVec3 P = ray.origin + ray.direction * tEv;
                state.ray_origin_x[idx] = P.x;
                state.ray_origin_y[idx] = P.y;
                state.ray_origin_z[idx] = P.z;
                // #961: the segment the NEE light was picked for (CPU misSeg*;
                // Cycles mis_origin_n / previous_dt), for the next hit's MIS.
                state.path_mis_nx[idx] = ray.direction.x * tEv;
                state.path_mis_ny[idx] = ray.direction.y * tEv;
                state.path_mis_nz[idx] = ray.direction.z * tEv;
                state.path_mis_dt[idx] = surfaceT;
                c_wfGridVolume.mediumId[idx] = mi;
                if (c_wfPhotonSplit.chain != nullptr) c_wfPhotonSplit.chain[idx] = 0;  // #909
                if constexpr (HasCurves) hitBufs.hit_prim_id[idx] = -1;  // #1037: medium vertex
                return -3;
            }
            // escaped: delta-track survival IS the transmittance — fall through.
        }
    }

    const bool mediumScatters = HasWorldScatter &&
                                c_worldVolume.hasVolume &&
                                c_worldVolume.density > 0.f &&
                                c_worldVolume.scatter > 0.f &&
                                !volTerm;   // pkg271: terminate-after => absorb only
    if constexpr (HasWorldScatter) if (mediumScatters) {
        float surfaceT = hit ? rec.t : 1e30f;
        float termT = surfaceT;   // pkg288: lamps are transparent
        // Object-free counter-based free-flight draws (Option 3): no WavefrontRNG
        // object held, no rng_dimension round-trip — keeps this kernel register-
        // light. Salt varies per bounce (·2) and per draw (+0/+1), disjoint from the
        // shade stream; shade/volume read the UNTOUCHED rng_dimension (as Stage-1).
        uint32_t rpix = state.rng_pixel[idx];
        uint32_t rsmp = state.rng_sample[idx];
        uint64_t rsd  = state.rng_seed[idx];
        uint32_t salt = G_WF_VOL_DIM_SALT + (uint32_t)bounce * 2u;
        GSampledSpectrum sigmaT = gpu_worldSigmaT(lambdas);
        // #929 (CPU #925 twin): per-segment direct light on [0, surfaceT] before the
        // free flight (Tr(t)·σ_s·NEE at a one-sample-MIS distance), segment slot 1.
        if (enableNEE)
            gpu_volumeSegmentDirect(idx, bounce, 1, ray.origin, ray.direction, 0.f, surfaceT,
                                    sigmaT, throughput, lambdas, c_worldVolume.scatter,
                                    c_worldVolume.anisotropy, prims, tris, spheres, lights,
                                    numLights, totalLightPower, dedLights, numDed, lightTree,
                                    rpix, rsmp, rsd);
        int ch = (int)(gpu_freeflightUniform(rpix, rsmp, rsd, salt) * G_SPECTRUM_SAMPLES);
        if (ch >= G_SPECTRUM_SAMPLES) ch = G_SPECTRUM_SAMPLES - 1;
        float sigTc = sigmaT.v[ch];
        float xi = gpu_freeflightUniform(rpix, rsmp, rsd, salt + 1u);
        float fdist = (sigTc > 0.f) ? -__logf(1.f - xi) / sigTc : 1e30f;
        if (fdist < termT) {
            // SCATTER: throughput *= Tr(fdist)·σ_s/pdf, pdf = avg(σ_t·Tr).
            GSampledSpectrum Tr;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                Tr.v[i] = __expf(-sigmaT.v[i] * fdist);
            float pdf = 0.f;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) pdf += sigmaT.v[i] * Tr.v[i];
            pdf /= float(G_SPECTRUM_SAMPLES);
            if (pdf <= 0.f) { state.path_alive[idx] = 0; return -1; }
            float invPdf = 1.f / pdf;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                throughput.v[i] *= Tr.v[i] * (sigmaT.v[i] * c_worldVolume.scatter) * invPdf;
            // Scatter point P = origin + dir·fdist. Snapshot semantics (pinned in
            // .astroray_plan/docs/pkg199-stage2-scattering-research.md): capture P
            // from the PRE-update ray and store it as the new ray_origin;
            // ray_direction is LEFT as the incoming direction so the volume kernel
            // recovers woMedium = -direction for the HG frame — mirrors the CPU.
            GVec3 P = ray.origin + ray.direction * fdist;
            state.ray_origin_x[idx] = P.x;
            state.ray_origin_y[idx] = P.y;
            state.ray_origin_z[idx] = P.z;
            // #961: NEE segment for the next hit's MIS (see the grid scatter above).
            state.path_mis_nx[idx] = ray.direction.x * fdist;
            state.path_mis_ny[idx] = ray.direction.y * fdist;
            state.path_mis_nz[idx] = ray.direction.z * fdist;
            state.path_mis_dt[idx] = surfaceT;
            state.throughput_0[idx] = throughput.v[0];
            state.throughput_1[idx] = throughput.v[1];
            state.throughput_2[idx] = throughput.v[2];
            state.throughput_3[idx] = throughput.v[3];
            if (c_wfPhotonSplit.chain != nullptr) c_wfPhotonSplit.chain[idx] = 0;  // #909
            if constexpr (HasCurves) hitBufs.hit_prim_id[idx] = -1;  // #1037: medium vertex
            return -2;  // scattered → the wrapper enqueues to the volume queue
        } else {
            // Reached the terminating event (surface / env): throughput *=
            // Tr(termT)/pdf, pdf = avg(Tr). Replaces the Stage-1 role-1 multiply
            // (gated off below).
            float capT = fminf(termT, 1e18f);
            GSampledSpectrum Tr;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                Tr.v[i] = __expf(-sigmaT.v[i] * capT);
            float pdf = 0.f;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) pdf += Tr.v[i];
            pdf /= float(G_SPECTRUM_SAMPLES);
            if (pdf <= 0.f) { state.path_alive[idx] = 0; return -1; }
            float invPdf = 1.f / pdf;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) throughput.v[i] *= Tr.v[i] * invPdf;
            state.throughput_0[idx] = throughput.v[0];
            state.throughput_1[idx] = throughput.v[1];
            state.throughput_2[idx] = throughput.v[2];
            state.throughput_3[idx] = throughput.v[3];
            // fall through to env / role-1(gated) / emission.
        }
    }

    if (!hit) {
        // pkg201 Stage 2 (Finding F) — a bounce-0 primary-ray sample that reaches
        // here saw the background, not foreground geometry: count it toward the
        // transparent-film alpha coverage (alpha = 1 - miss/samples). Gated on the
        // published pointer (null for every non-transparent render → byte-identical)
        // and on bounce == 0 (deeper env escapes do NOT reduce foreground coverage).
        if (bounce == 0 && c_wfMissCoverage != nullptr)
            atomicAdd(&c_wfMissCoverage[state.pixel_index[idx]], 1.0f);
        // ---- Env-map miss (CPU path_kernel: worldMaxBounces gate; the
        // shared helper mirrors EnvironmentMap::evalSpectral).
        // pkg55-C3: Rayleigh sky fallback for non-visible-band luminance-output
        // mode (multiwavelength_kernel.cu:171-177).
        if (bounce <= worldMaxBounces) {
            GVec3 dir = ray.direction.normalized();
            GSampledSpectrum envSpec(0.f);
            if (useLuminanceOutput && !hasBackgroundColor && !envMap.loaded) {
                // Rayleigh sky fallback for outside-visible bands.
                for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
                    float scale = rayleighScale(lambdas.lambda[i]);
                    float horizonFade = 0.5f * (dir.y + 1.f);
                    envSpec.v[i] = 0.08f * scale * (0.5f + horizonFade);
                }
            } else {
                envSpec = gpu_env_miss_spectral(
                    envMap, backgroundColor, hasBackgroundColor, dir, lambdas);
            }
            // pkg258: two-strategy MIS for the background (twin of CPU
            // pathTraceSpectral / path_kernel.cpp miss leg). A camera ray or a
            // post-specular miss takes the full env (unweighted -> sky exact);
            // after a NON-specular surface bounce where env NEE actually competed
            // for this direction, discount by the power heuristic against the env
            // importance pdf. env_nee_sampled_prev distinguishes a surface bounce
            // (env NEE ran) from a post-phase-scatter miss (lamp NEE only) so the
            // latter is NOT wrongly discounted. Gated on the loaded HDRI + the
            // runtime enabled flag: no-op (byte-identical) otherwise.
            if (c_wfEnvNeeBinding.enabled && envMap.loaded && bounce > 0 &&
                !wasSpecular && state.env_nee_sampled_prev[idx] == 1) {  // #961: 2 = medium
                float ep = gpu_envmap_pdf(envMap, dir);
                float bsdfPdfPrev = state.path_bsdf_pdf[idx];
                // pkg258 (Terra item 6): complementary heuristic — this w(bsdf,env)
                // plus the env-NEE leg's w(env,bsdf) sum to EXACTLY one (no 1e-8
                // denom epsilon), so the miss/NEE pair loses no energy (dark bias).
                float wMiss = gpu_mw_powerHeuristicExact(bsdfPdfPrev, ep);
                for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) envSpec.v[i] *= wMiss;
            }
            // pkg157: clamp by bounce depth (Cycles film_clamp_light split);
            // see gpu_clampContribMW (gpu_spectral_tables.h).
            GSampledSpectrum envContrib = gpu_clampContribMW(
                throughput * envSpec, lambdas, bounce - 1,   // #860
                clampDirect, clampIndirect, useLuminanceOutput);
            color += envContrib;
            // pkg198 Stage 2: directly-visible background → PASS_ENVIRONMENT; a
            // background reached after a bounce → firstCat's INDIRECT pass (CPU
            // envPass = firstCat<0 ? PASS_ENVIRONMENT : firstCat*3+1).
            if constexpr (HasLightPassAOVs) {
                unsigned char cat = c_wfLpBinding.firstCat[idx];
                lpAccumulate(idx, lpEmitOrBgPass(cat, G_LP_PASS_ENVIRONMENT), envContrib);
            }
            state.color_0[idx] = color.v[0];
            state.color_1[idx] = color.v[1];
            state.color_2[idx] = color.v[2];
            state.color_3[idx] = color.v[3];
        }
        state.path_alive[idx] = 0;
        return -1;
    }

    // #991 — a Mix Shader with a Light Path Fac shades as the child this ray
    // type selects (Is Camera Ray -> hidden emitter). Downstream (emission,
    // bucketing, the parked hit) all see the resolved id.
    if (c_wfLightPath.sw)
        rec.materialId = gpu_lpRemap(rec.materialId, state.lp_state[idx], bounce, rec.t,
                                     ray.direction);
    const ::GMaterial& mat = materials[rec.materialId];

    // #909: photon-map split chain (see GWavefrontPhotonSplit). Live from a
    // bounce-0 photon receiver; each later hit must be a caster (any face,
    // reflected or refracted: #959, the photon trace Fresnel-samples both), else dead.
    if (c_wfPhotonSplit.chain != nullptr) {
        unsigned char c;
        if (bounce == 0) {
            c = (mat.emissionIntensity <= 0.f && !wf_isPhotonCaster(mat)) ? 1 : 0;
        } else {
            c = c_wfPhotonSplit.chain[idx];
            if (c & 1) c = wf_isPhotonCaster(mat) ? 3 : 0;
        }
        c_wfPhotonSplit.chain[idx] = c;
    }

    // pkg197 — first-hit denoise-guide AOV capture. Written from the INTERSECT
    // stage (not the REG:254-saturated shade kernel — memory
    // wavefront-shade-kernels-register-saturated) so the fleet
    // stageShadeBucketedKernel<false,…> specialization stays byte-identical
    // (STACK 3608 / REG 254 / CONSTANT[0] 1700). Placed here, right after the
    // material load and BEFORE the emissive early-return, so it captures the raw
    // first geometric hit — exactly the CPU spectral_path_tracer semantics
    // (plugins/integrators/spectral_path_tracer.cpp: r.albedo =
    // rec.material->getAlbedo(); r.depth = rec.t; r.normal = rec.normal — the
    // first bvh->hit, unconditional of emissive). Gated on bounce == 0 &&
    // sample_index == 0: the regen scheme maps sample-0 work items to w == pixel
    // (stageRegenKernel: pixel = w % numPixels), so exactly ONE path per pixel
    // writes each guide — a race-free single write that matches the CPU's s == 0
    // capture (include/raytracer.h:3129,3173-3175). mat.baseColor is the GPU
    // getAlbedo() (same value the pkg113 photon gather uses); rec.normal is the
    // front-facing world-space shading normal (gpu_bvh sets rec.normal =
    // frontFace?out:-out — the get_normal_buffer convention, pkg75). The three
    // output pointers ride in the c_wfGuideBinding constant, so no signature grows.
    if (bounce == 0 && state.sample_index[idx] == 0 &&
        c_wfGuideBinding.albedo != nullptr) {
        const int pixel = state.pixel_index[idx];
        c_wfGuideBinding.albedo[pixel * 3 + 0] = mat.baseColor.x;
        c_wfGuideBinding.albedo[pixel * 3 + 1] = mat.baseColor.y;
        c_wfGuideBinding.albedo[pixel * 3 + 2] = mat.baseColor.z;
        c_wfGuideBinding.normal[pixel * 3 + 0] = rec.normal.x;
        c_wfGuideBinding.normal[pixel * 3 + 1] = rec.normal.y;
        c_wfGuideBinding.normal[pixel * 3 + 2] = rec.normal.z;
        c_wfGuideBinding.depth[pixel] = rec.t;
    }

    // pkg199 Stage 1 (role 1): Beer-Lambert free-flight attenuation over the
    // segment just traversed (rec.t), on a confirmed surface hit, BEFORE this
    // vertex is shaded — device twin of the CPU pathTraceSpectral role-1 multiply.
    // The attenuated throughput is written back to the per-path SoA so the shade
    // stage (NEE park) and the next bounce both inherit the fog; the emission
    // block below uses the attenuated local. Kept in THIS (intersect) kernel, not
    // the REG-254 shade kernel, so stageShadeBucketedKernel stays byte-identical.
    // Vacuum (hasVolume==0): skipped, throughput SoA untouched → byte-identical.
    // pkg199 Stage 2: in scatter mode the free-flight estimator above already
    // applied Tr(termT)/pdf, so skip this deterministic role-1 multiply.
    if (c_worldVolume.hasVolume && !mediumScatters) {
        throughput *= gpu_worldTransmittanceMW(rec.t, lambdas);
        state.throughput_0[idx] = throughput.v[0];
        state.throughput_1[idx] = throughput.v[1];
        state.throughput_2[idx] = throughput.v[2];
        state.throughput_3[idx] = throughput.v[3];
    }

    // ---- Emission (gated on camera ray or post-specular bounce; path ends).
    GSampledSpectrum Le = gpu_material_emitted_spectral(mat, rec.frontFace, lambdas);
    if (Le.maxValue() > 0.f) {
        // #962: textured Emission Color — replace the flat mean with the texel
        // at this hit (CPU TexturedLight::emittedSpectral: RGBIlluminant of
        // texel x intensity). Le > 0 already implies the front face.
        if (c_wfEmissionTex && mat.type == GMAT_DIFFUSE_LIGHT) {
            GProgInputTexel e = gpu_emissionTexel(rec.point, rec.primId, prims, tris,
                                                  spheres, rec.materialId);
            if (e.ok)
                Le = gpu_rgbToSampledSpectrum(e.c * mat.emissionIntensity, lambdas,
                                              mat.spectralMode);
        }
        if (bounce == 0 || wasSpecular || c_wfLightNeeOff) {  // #877: NEE off -> w_B = 1
            // pkg157: emissive-hit direct term, same clamp split as above.
            // Camera / post-specular ray: no NEE leg competes (w_B = 1).
            GSampledSpectrum emitContrib = gpu_clampContribMW(
                throughput * Le, lambdas, bounce - 1,   // #860
                clampDirect, clampIndirect, useLuminanceOutput);
            color += emitContrib;
            // pkg198 Stage 2: directly-visible surface emission → PASS_EMISSION;
            // emission after a non-specular bounce → firstCat's INDIRECT pass.
            if constexpr (HasLightPassAOVs) {
                unsigned char cat = c_wfLpBinding.firstCat[idx];
                lpAccumulate(idx, lpEmitOrBgPass(cat, G_LP_PASS_EMISSION), emitContrib);
            }
        } else if (enableNEE) {
            // pkg120: two-sided MIS BSDF-sampled leg — device twin of CPU
            // pathTraceSpectral. This continuation ray was BSDF-sampled at a
            // diffuse bounce; weight its emission by the power heuristic against
            // the light-sampling pdf that would have generated this same hit.
            // prevPoint = ray.origin (this ray's origin is the previous shading
            // vertex, written verbatim by shadePathSlot), dir = ray.direction
            // (the sampled BSDF direction) — same values on CPU and GPU, so the
            // pdf reconstruction matches by construction (no snapshot skew).
            //
            // pkg156: gated on enableNEE. The w_B leg is only meaningful as the
            // complement of the NEE light-sampling leg (w_L). In naive mode
            // (enableNEE == false, the multiwavelength_path_tracer route) there
            // is no NEE leg, so the CPU oracle (MultiwavelengthPathTracer::
            // pathTrace) accumulates NOTHING on a diffuse emitter hit — it only
            // takes emission on bounce == 0 || wasSpecular. Applying w_B here
            // diverged the GPU bright from that oracle (bounce-2 onset, the
            // pkg156 residual); skipping it restores CPU/GPU parity and the
            // pre-pkg120 naive behaviour. NEE mode (path_tracer) is unchanged.
            float bsdfPdfPrev = state.path_bsdf_pdf[idx];
            // #851: the NEE normal of the previous vertex (tree pick == pdf).
            GVec3 misNormalPrev(state.path_mis_nx[idx], state.path_mis_ny[idx],
                                state.path_mis_nz[idx]);
            // #961: medium vertex -> the segment its NEE light was picked for.
            const float misSegT = (state.env_nee_sampled_prev[idx] == 2)
                                ? state.path_mis_dt[idx] : 0.f;
            float lp = gpu_reconstruct_light_pdf(
                rec, ray.origin, ray.direction,
                lights, numLights, totalLightPower,
                prims, tris, spheres, lightTree, misNormalPrev, misSegT);
            float wB = gpu_mw_powerHeuristic(bsdfPdfPrev, lp);
            GSampledSpectrum contrib = throughput * Le;
            contrib *= wB;
            GSampledSpectrum emitContrib = gpu_clampContribMW(
                contrib, lambdas, bounce - 1,   // #860
                clampDirect, clampIndirect, useLuminanceOutput);
            color += emitContrib;
            // pkg198 Stage 2: two-sided-MIS emissive hit at a diffuse bounce is
            // indirect light → firstCat's INDIRECT pass (firstCat is always locked
            // here: this branch is bounce>0 && !wasSpecular).
            if constexpr (HasLightPassAOVs) {
                unsigned char cat = c_wfLpBinding.firstCat[idx];
                lpAccumulate(idx, lpEmitOrBgPass(cat, G_LP_PASS_EMISSION), emitContrib);
            }
        }
        state.color_0[idx] = color.v[0];
        state.color_1[idx] = color.v[1];
        state.color_2[idx] = color.v[2];
        state.color_3[idx] = color.v[3];
        state.path_alive[idx] = 0;
        return -1;
    }

    // pkg271 — a terminate-after path (volume_bounces exhausted) has taken this
    // surface's emission above; it ends here instead of being shaded.
    if constexpr (HasGridVolume || HasWorldScatter) if (volTerm) {
        state.path_alive[idx] = 0;
        return -1;
    }

    // ---- Park the hit record in SoA for the shade stage.
    hitBufs.hit_t[idx]           = rec.t;
    hitBufs.hit_point_x[idx]     = rec.point.x;
    hitBufs.hit_point_y[idx]     = rec.point.y;
    hitBufs.hit_point_z[idx]     = rec.point.z;
    hitBufs.hit_normal_x[idx]    = rec.normal.x;
    hitBufs.hit_normal_y[idx]    = rec.normal.y;
    hitBufs.hit_normal_z[idx]    = rec.normal.z;
    hitBufs.hit_tangent_x[idx]   = rec.tangent.x;
    hitBufs.hit_tangent_y[idx]   = rec.tangent.y;
    hitBufs.hit_tangent_z[idx]   = rec.tangent.z;
    hitBufs.hit_bitangent_x[idx] = rec.bitangent.x;
    hitBufs.hit_bitangent_y[idx] = rec.bitangent.y;
    hitBufs.hit_bitangent_z[idx] = rec.bitangent.z;
    hitBufs.hit_material_id[idx] = rec.materialId;
    hitBufs.hit_prim_id[idx]     = rec.primId;
    hitBufs.hit_front_face[idx]  = rec.frontFace ? 1 : 0;
    hitBufs.hit_is_delta[idx]    = rec.isDelta ? 1 : 0;
    hitBufs.hit_valid[idx]       = 1;
    // pkg225 Stage 4 — persist the strand tangent + azimuthal v across the
    // intersect->shade hand-off (the curve leaf set them in the register-resident
    // GHitRecord; nothing else parks them). Written unconditionally in the (non-
    // register-critical) intersect stage; a triangle hit stores the default
    // uvTangent/hairV=0.5, which the shade side only reads for a GMAT_HAIR_PRINCIPLED
    // (curve) hit, so it is a harmless don't-care for every other material.
    hitBufs.hit_uv_tangent_x[idx] = rec.uvTangent.x;
    hitBufs.hit_uv_tangent_y[idx] = rec.uvTangent.y;
    hitBufs.hit_uv_tangent_z[idx] = rec.uvTangent.z;
    hitBufs.hit_hair_v[idx]       = rec.hairV;
    return (int)mat.type;
}
// pkg199 Stage 2 - non-template `intersectPathSlot` (forwards to <false>); defined
// in stage_advance.cu (see the comment there), declared here for in-header users.
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
    GLightTreeView    lightTree);

// Shade half: NEE + RR + BSDF over the parked hit record. Returns true when
// the path survives into the next bounce.
// nee_f/nee_i/shadow_queue/shadow_count non-null => DEFER the NEE shadow
// trace + resolve to the dedicated shadow stage (park the sample + wo +
// throughput, enqueue the slot). Null => immediate occlude+resolve inline
// (the flat/dense schedulings keep their original single-kernel behavior).
// pkg174: template on Deferred. The production bucketed/NeeMis schedulings
// always park NEE work to the deferred shadow stage (nee_f != nullptr), so the
// immediate-NEE `else` branch (inline gpu_nee_occlude shadow-ray BVH/TLAS
// traversal) is DEAD in those instantiations. Compiling it out with
// `if constexpr (Deferred)` frees ptxas from allocating for its shadow-traversal
// live set in the REG:254-saturated shade kernel. Deferred=false keeps the
// immediate path for advancePathSlot (the dense/flat reference schedulings).
// PERF ONLY — the compiled-out branch is unreachable in the deferred callers.
// pkg178 Stage-3b D4: HasPrincipled is threaded into the material dispatch so
// non-principled scenes launch a shade kernel with ZERO gpu_principled_* codegen
// (if constexpr in gpu_materials.h), restoring main's footprint. The launchers
// pick <true>/<false> off scene_upload's host-side flag. See
// .astroray_plan/docs/pkg178-stage3-d4-and-forks-decision.md §2b.
// pkg186 — image-texture binding in constant memory (see GWavefrontTextureBinding
// in gpu_types.h). Set once per frame by setWavefrontTextureBinding before the
// shade launches; read only inside `if constexpr (HasTexture)`. Keeping it OUT of
// the kernel signature is what leaves the untextured <false,false> fleet kernel at
// its pre-pkg186 REG/STACK footprint (the three signature params cost +24 B stack).
extern __constant__ GWavefrontTextureBinding c_wfTexBinding;

// pkg219b — op-VM program binding in constant memory (see GWavefrontProgramBinding
// in astroray/shader_vm.h). Set once per frame by setWavefrontProgramBinding; read
// only inside `if constexpr (HasProgram)`. The <false> fleet kernel never reads it.
extern __constant__ GWavefrontProgramBinding c_wfProgBinding;

// pkg219d — scalar BSDF-parameter op-VM override storage. Only the
// <HasProgram=true> shade specialization instantiates a full GMaterial copy to
// hold the per-hit-substituted roughness/metallic/transmission/ior;
// GScalarOverride<false> is an EMPTY struct (zero stack), so the fleet
// <HasProgram=false> shade kernel allocates nothing and stays byte-identical.
template<bool> struct GScalarOverride {};
template<> struct GScalarOverride<true> { ::GMaterial mat; };

// #826 — sample an op-VM program input: base-colour input t >= 1 (Noise -> Mix
// <- Checker, two images into one Mix) and, since #846, every scalar-program input. Same fetch as input 0 in shadePathSlot's HasTexture
// block: a 3D voxel bake (depth > 1; Generated coord rebuilt from the hit point
// and THIS descriptor's genMin/genSize) or a 2D image / UV bake (triangle-UV
// barycentric recompute, Ericson §3.4, + THIS descriptor's Mapping). ok=false on
// a non-triangle / UV-less / degenerate 2D hit; the caller then skips the whole
// texture, exactly as when input 0 misses. __noinline__ with by-value args keeps
// the body out of the REG:254 <HasProgram=true> caller's allocation (memory
// noinline-runtime-flag-avoids-shade-spill). Only ever called from
// <HasProgram=true>.
//
// #847 — Generated coordinate for a 3D-bake fetch (depth > 1). A triangle with
// per-vertex Generated coords (c_wfTexBinding.triGenerated, Cycles
// ATTR_STD_GENERATED: object-space texture space, per object) interpolates them
// with barycentrics recomputed from the hit point (Ericson §3.4, as the UV fetch
// below). Otherwise the pre-#847 per-texture bbox frame:
// g = (point - genMin)/genSize (include/advanced_features.h CoordMode::Generated).
// __noinline__ keeps the body out of the REG:254 shade kernel's allocation.
// #1006 — OBJECT coordinate at a hit: the triangle's per-vertex object-local
// positions (c_wfTexBinding.triObjectLocal, the inverse object transform of the
// world-baked vertices; Cycles svm/tex_coord.h object_inverse_position_transform)
// interpolated with barycentrics recomputed from the hit point (Ericson §3.4, as
// gpu_generatedCoord), else the world point (CPU CoordMode::Object fallback).
static __device__ ASTRORAY_SHADE_NOINLINE inline GVec3 gpu_objectCoord(
    GVec3 point, int primId, const GPrimitive* prims, const GTriangle* tris)
{
    const GVec3* to = c_wfTexBinding.triObjectLocal;
    if (to && primId >= 0 && prims[primId].type == GPRIM_TRIANGLE) {
        const int ti = prims[primId].index;
        const GVec3 o0 = to[3 * ti];
        if (!isnan(o0.x)) {
            const GTriangle& t = tris[ti];
            GVec3 e1 = t.v1 - t.v0, e2 = t.v2 - t.v0, ep = point - t.v0;
            float d00 = e1.dot(e1), d01 = e1.dot(e2), d11 = e2.dot(e2);
            float d20 = ep.dot(e1), d21 = ep.dot(e2);
            float denom = d00 * d11 - d01 * d01;
            if (fabsf(denom) > 1e-20f) {
                float b1 = (d11 * d20 - d01 * d21) / denom;
                float b2 = (d00 * d21 - d01 * d20) / denom;
                return o0 + (to[3 * ti + 1] - o0) * b1 + (to[3 * ti + 2] - o0) * b2;
            }
        }
    }
    return point;
}

static __device__ ASTRORAY_SHADE_NOINLINE inline GVec3 gpu_generatedCoord(
    GVec3 point, int primId, const GPrimitive* prims, const GTriangle* tris, int texId)
{
    const GVec3* tg = c_wfTexBinding.triGenerated;
    // #994: an OBJECT-coordinate bake is indexed by the world hit point in its
    // bbox frame (below), never by the per-vertex Generated coords.
    if (tg && !c_wfTexBinding.textures[texId].objectCoord &&
        primId >= 0 && prims[primId].type == GPRIM_TRIANGLE) {
        const int ti = prims[primId].index;
        const GVec3 g0 = tg[3 * ti];
        if (!isnan(g0.x)) {
            const GTriangle& t = tris[ti];
            GVec3 e1 = t.v1 - t.v0, e2 = t.v2 - t.v0, ep = point - t.v0;
            float d00 = e1.dot(e1), d01 = e1.dot(e2), d11 = e2.dot(e2);
            float d20 = ep.dot(e1), d21 = ep.dot(e2);
            float denom = d00 * d11 - d01 * d01;
            if (fabsf(denom) > 1e-20f) {
                float b1 = (d11 * d20 - d01 * d21) / denom;
                float b2 = (d00 * d21 - d01 * d20) / denom;
                // Edge form: exact when all three vertices share a coordinate
                // (flat plane z = 0.5 stays 0.5, see gpu_sampleProcedural3D).
                return g0 + (tg[3 * ti + 1] - g0) * b1 + (tg[3 * ti + 2] - g0) * b2;
            }
        }
    }
    const GImageTexture& tdesc = c_wfTexBinding.textures[texId];
    // #1006: an OBJECT bake's bbox frame is object-local (scene_upload.cu matWorldBox).
    if (tdesc.objectCoord) point = gpu_objectCoord(point, primId, prims, tris);
    GVec3 g;
    g.x = tdesc.genSize.x > 1e-6f ? (point.x - tdesc.genMin.x) / tdesc.genSize.x : 0.0f;
    g.y = tdesc.genSize.y > 1e-6f ? (point.y - tdesc.genMin.y) / tdesc.genSize.y : 0.0f;
    g.z = tdesc.genSize.z > 1e-6f ? (point.z - tdesc.genMin.z) / tdesc.genSize.z : 0.0f;
    return g;
}

static __device__ ASTRORAY_SHADE_NOINLINE inline GProgInputTexel gpu_progInputTexel(
    GVec3 point, int primId, const GPrimitive* prims, const GTriangle* tris, int texId)
{
    const GImageTexture& tdesc = c_wfTexBinding.textures[texId];
    if (tdesc.depth > 1) {
        GVec3 g = gpu_generatedCoord(point, primId, prims, tris, texId);  // #847
        return {gpu_sampleProcedural3D(tdesc, c_wfTexBinding.texelBuf, g), true};
    }
    const GProgInputTexel miss{GVec3(0.0f, 0.0f, 0.0f), false};
    if (!(primId >= 0 && prims[primId].type == GPRIM_TRIANGLE)) return miss;
    const GTriangle& ttri = tris[prims[primId].index];
    if (!ttri.hasUV) return miss;
    GVec3 e1 = ttri.v1 - ttri.v0, e2 = ttri.v2 - ttri.v0;
    GVec3 ep = point - ttri.v0;
    float d00 = e1.dot(e1), d01 = e1.dot(e2), d11 = e2.dot(e2);
    float d20 = ep.dot(e1), d21 = ep.dot(e2);
    float denom = d00 * d11 - d01 * d01;
    if (fabsf(denom) <= 1e-20f) return miss;
    float b1 = (d11 * d20 - d01 * d21) / denom;
    float b2 = (d00 * d21 - d01 * d20) / denom;
    float b0 = 1.0f - b1 - b2;
    float uu = b0*ttri.uv0.x + b1*ttri.uv1.x + b2*ttri.uv2.x;
    float vv = b0*ttri.uv0.y + b1*ttri.uv1.y + b2*ttri.uv2.y;
    if (tdesc.hasMapping) {
        const float* m = tdesc.mapping;
        float mu = m[0]*uu + m[1]*vv + m[3];
        float mv = m[4]*uu + m[5]*vv + m[7];
        uu = mu; vv = mv;
    }
    return {gpu_sampleImageTexture(tdesc, c_wfTexBinding.texelBuf, uu, vv), true};
}

// #1007 — a program / base-colour input in the <HasProgram=true> kernel. A
// descriptor with procId >= 0 (scene_upload.cu perHitTexId) is a Noise / Wave /
// Voronoi evaluated at this hit instead of a 64^3 bake: the CPU texture point
// (Object: gpu_objectCoord, the object-local point (#1006); Generated:
// gpu_generatedCoord clamped to [0,1], advanced_features.h CoordMode::Generated),
// then the 3-D Mapping M*p (Texture::value), then gpu_procTexEval
// (proc_tex_eval.cu). Every other descriptor is the texel fetch above. Never
// called from the emission (intersect / shadow) paths, so the evaluator's
// registers stay out of those kernels.
__device__ GVec3 gpu_procTexEval(int procId, GVec3 p);  // proc_tex_eval.cu
// #990 — shading attribute layer at the hit (shading_inputs_eval.cu).
__device__ GVec3 gpu_attrTexel(int texId, GVec3 point, int primId,
                               const GPrimitive* prims, const GTriangle* tris);
static __device__ ASTRORAY_SHADE_NOINLINE inline GProgInputTexel gpu_progInputEval(
    GVec3 point, int primId, const GPrimitive* prims, const GTriangle* tris, int texId)
{
    const GImageTexture& tdesc = c_wfTexBinding.textures[texId];
    if (tdesc.attrLayer >= 0)  // #990
        return {gpu_attrTexel(texId, point, primId, prims, tris), true};
    if (tdesc.procId < 0) return gpu_progInputTexel(point, primId, prims, tris, texId);
    GVec3 p = point;
    if (tdesc.objectCoord) {
        p = gpu_objectCoord(point, primId, prims, tris);  // #1006
    } else {
        const GVec3 g = gpu_generatedCoord(point, primId, prims, tris, texId);
        p = GVec3(astroray::proc::pclamp(g.x, 0.0f, 1.0f),
                  astroray::proc::pclamp(g.y, 0.0f, 1.0f),
                  astroray::proc::pclamp(g.z, 0.0f, 1.0f));
    }
    if (tdesc.hasMapping) {
        const float* m = tdesc.mapping;
        p = GVec3(m[0]*p.x + m[1]*p.y + m[2]*p.z  + m[3],
                  m[4]*p.x + m[5]*p.y + m[6]*p.z  + m[7],
                  m[8]*p.x + m[9]*p.y + m[10]*p.z + m[11]);
    }
    return {gpu_procTexEval(tdesc.procId, p), true};
}

// #988 — per-texel Base Color of a native Principled material (scene_upload.cu
// uploads it on the base-colour slots: matTexId = input 0, matProgId + matProgInTexId
// for an op-VM program). Same fetch + svm_eval as the textured-lambertian block of
// shadePathSlot; returns the RGB the CPU PrincipledPlugin::substituted() writes into
// baseColor_. ok=false when untextured or when any input misses at this hit (the
// caller keeps the constant base colour, as the lambertian path does). __noinline__
// keeps the fetch + VM register file out of the REG:254 <HasProgram=true> caller.
static __device__ ASTRORAY_SHADE_NOINLINE inline GProgInputTexel gpu_principledBaseTexel(
    GVec3 point, int primId, const GPrimitive* prims, const GTriangle* tris, int matId,
    astroray::svm::SvmShading sh)
{
    const GProgInputTexel miss{GVec3(0.0f, 0.0f, 0.0f), false};
    const int texId = c_wfTexBinding.matTexId ? c_wfTexBinding.matTexId[matId] : -1;
    const int progId = c_wfProgBinding.matProgId ? c_wfProgBinding.matProgId[matId] : -1;
    if (texId < 0 && progId < 0) return miss;
    // #989: a program over per-hit shading inputs only has no texture (texId -1).
    GProgInputTexel t0{GVec3(0.0f, 0.0f, 0.0f), true};
    if (texId >= 0) {
        t0 = gpu_progInputEval(point, primId, prims, tris, texId);
        if (!t0.ok) return miss;
    }
    if (progId < 0) return t0;
    GVec3 vmIn[astroray::svm::VM_MAX_TEX];
    vmIn[0] = t0.c;
    const int* inTexIds = c_wfProgBinding.matProgInTexId;
    const int inBase = matId * astroray::svm::VM_MAX_TEX;
    for (int t = 1; t < astroray::svm::VM_MAX_TEX; ++t) {
        vmIn[t] = t0.c;  // single-input program: broadcast input 0 (#826)
        const int inTex = inTexIds ? inTexIds[inBase + t] : -1;
        if (inTex >= 0) {
            const GProgInputTexel s = gpu_progInputEval(point, primId, prims, tris, inTex);
            if (!s.ok) return miss;
            vmIn[t] = s.c;
        }
    }
    return {astroray::svm::svm_eval(c_wfProgBinding.programs[progId], vmIn, &sh), true};
}

// #962 — per-hit textured Emission Color (TexturedLight uploaded by
// scene_upload.cu on the matTexId slot; an op-VM chain arrives pre-baked). Linear
// RGB texel at a point on emissive material matId via the SAME fetch as
// shadePathSlot's HasTexture block (gpu_progInputTexel: 3D bake / UV barycentric
// + Mapping; 2D on a sphere: the CPU sphere UV). ok=false when untextured,
// instanced (object-space triangles) or
// unsampleable (caller keeps the flat mean). CPU twin: TexturedLight::emitted()/
// emittedSpectral() = texel x intensity, evaluated per BSDF hit and per NEE
// sample (light_sampler.cpp #776); Cycles likewise evaluates the emission shader
// at every emitter hit and at the light-sampled point
// (intern/cycles/kernel/light/triangle.h + kernel/integrator/shade_surface.h).
// Caller guards on c_wfEmissionTex, so c_wfTexBinding is valid this frame.
static __device__ ASTRORAY_SHADE_NOINLINE inline GProgInputTexel gpu_emissionTexel(
    GVec3 point, int primId, const GPrimitive* prims, const GTriangle* tris,
    const GSphere* spheres, int matId)
{
    const int texId = c_wfTexBinding.matTexId[matId];
    if (texId < 0 || primId < 0 || primId >= c_wfEmissionFlatPrims)
        return {GVec3(0.0f, 0.0f, 0.0f), false};
    const GImageTexture& tdesc = c_wfTexBinding.textures[texId];
    if (tdesc.depth <= 1 && prims[primId].type == GPRIM_SPHERE) {
        // 2D texture on a sphere emitter: the CPU Sphere UV (shapes.h):
        // theta = acos(-n.y), phi = atan2(-n.z, n.x) + pi, uv = (phi/2pi, theta/pi)
        // with n the outward unit normal, then the same Mapping + fetch as the
        // triangle UV path (gpu_progInputTexel).
        const GSphere& sp = spheres[prims[primId].index];
        GVec3 n = (point - sp.center) * (1.0f / sp.radius);
        float theta = acosf(fminf(1.0f, fmaxf(-1.0f, -n.y)));
        float phi = atan2f(-n.z, n.x) + M_PI_F;
        float uu = phi / (2.0f * M_PI_F), vv = theta / M_PI_F;
        if (tdesc.hasMapping) {
            const float* m = tdesc.mapping;
            float mu = m[0]*uu + m[1]*vv + m[3];
            float mv = m[4]*uu + m[5]*vv + m[7];
            uu = mu; vv = mv;
        }
        return {gpu_sampleImageTexture(tdesc, c_wfTexBinding.texelBuf, uu, vv), true};
    }
    return gpu_progInputTexel(point, primId, prims, tris, texId);
}

// #962 — NEE twin: the exact light point gpu_nee_sample_light drew, parked in
// the dedicated-RGB lanes 11-13 for hittable lights ((b1, b2, primIdx bits);
// gpu_nee.cuh). Triangle: v0 + e1*b1 + e2*b2 (the sampled lpos); sphere: the
// parked true distance along wi. No re-trace, so the fetched texel is the one
// the BSDF-hit leg sees at that point.
static __device__ ASTRORAY_SHADE_NOINLINE inline GProgInputTexel gpu_emissionTexelAtLightSample(
    GVec3 origin, GVec3 wi, float geomDist, GVec3 packed, int lightMatId,
    const GPrimitive* prims, const GTriangle* tris, const GSphere* spheres)
{
    const int primId = __float_as_int(packed.z);
    if (primId < 0) return {GVec3(0.0f, 0.0f, 0.0f), false};
    GVec3 p = origin + wi * geomDist;
    if (prims[primId].type == GPRIM_TRIANGLE) {
        const GTriangle& t = tris[prims[primId].index];
        p = t.v0 + (t.v1 - t.v0) * packed.x + (t.v2 - t.v0) * packed.y;
    }
    return gpu_emissionTexel(p, primId, prims, tris, spheres, lightMatId);
}


// pkg219d — apply one op-VM scalar result to the LOCAL GMaterial copy. Overwrites
// EVERY representation the closure dispatch may read: the top-level field (plain
// lambertian/metal + the GCLOSURE_DIFFUSE path, which reads parent.roughness), the
// native-Principled block (gpu_principled_* fast path), and every closure lobe
// (gpu_closure_as_material reads closure.{roughness,metallic,ior,transmission}).
// Clamps MUST match the CPU DisneyPlugin::substituted() and its constructor.
// Lobe mix: a Disney material with a metallic/transmission program lowers to ONE
// closure (pkg293, disney.cpp closureGraph()); Principled is monolithic. The per-hit
// closure.metallic/transmission written here therefore re-derive the diffuse/
// specular/glass weights inside gpu_disney_* / gpu_principled_* (no baked weight).
__device__ __forceinline__ void gpu_applyScalarOverride(
    ::GMaterial& mat, int slot, float v)
{
    switch (slot) {
        case astroray::svm::SCALAR_ROUGHNESS: {
            float r = fminf(fmaxf(v, 0.001f), 1.0f);
            mat.roughness = r; mat.principled.roughness = r;
            for (int i = 0; i < mat.closureCount; ++i) mat.closures[i].roughness = r;
            break;
        }
        case astroray::svm::SCALAR_METALLIC: {
            float m = fminf(fmaxf(v, 0.0f), 1.0f);
            mat.metallic = m; mat.principled.metallic = m;
            for (int i = 0; i < mat.closureCount; ++i) mat.closures[i].metallic = m;
            break;
        }
        case astroray::svm::SCALAR_TRANSMISSION: {
            float t = fminf(fmaxf(v, 0.0f), 1.0f);
            mat.transmission = t; mat.principled.transmission = t;
            for (int i = 0; i < mat.closureCount; ++i) mat.closures[i].transmission = t;
            break;
        }
        case astroray::svm::SCALAR_IOR: {
            float io = fmaxf(v, 1.0f);
            mat.ior = io; mat.principled.ior = io;
            for (int i = 0; i < mat.closureCount; ++i) mat.closures[i].ior = io;
            break;
        }
        default: break;
    }
}

// pkg184 — HasPhotons isolates the bounce-0 photon-map caustic KNN gather
// (photonGridGatherKnn, 50-neighbour live set) behind `if constexpr`. The gather
// only ever fires at bounce 0 in scenes that carry a photon grid, yet ptxas had to
// allocate its registers/stack in EVERY instantiation of the REG:254-pinned shade
// kernel. Threading HasPhotons lets the fleet's non-photon <*,*,false> kernels
// compile with ZERO gather codegen; the launcher picks <true> off hasPhotonGrid.
// See .astroray_plan/packages/pkg184-stage-advance-hasphotons-isolation.md.
// pkg189 — HasDispersion isolates the hero-λ collapse write-back for dispersive
// refraction (dielectric Sellmeier + Principled Cauchy glass) behind
// `if constexpr`. The dispersive sampler (gpu_material_sample_spectral) calls
// wl.terminateSecondary() on a refraction event, which zeroes the secondary
// wavelengths' pdfs on the LOCAL `lambdas` reconstructed from SoA at the top of
// this function. Without persisting that mutated `lambdas` back to the per-path
// SoA, the collapse evaporates the moment this bounce returns: the next bounce
// re-reads the un-collapsed pdfs, and stageRegenKernel's spectrumToXYZ still sums
// all 4 wavelengths — so every dispersive path deposits a broadband spectrum at a
// hero-bent location and the chromatic separation washes out to flat-IOR glass
// (the pkg187 no-op: GPU BK7 0.2139 ≈ flat 0.2131). The CPU wavefront mirror
// (src/cpu/wavefront/path_kernel.cpp::advance_one_bounce) does not need this: its
// ps.lambdas is a member of the persistent PathState, so the collapse persists
// for free. Threading HasDispersion lets the fleet's non-dispersive
// <*,*,*,false> kernels compile with ZERO extra live state (the REG:254-pinned
// shade kernel stays byte-identical); the launcher picks <true> off the
// host-side hasDispersive scene flag. See
// .astroray_plan/packages/pkg189-gpu-wavefront-dispersion-enablement.md.
// pkg258 - environment NEE sample generation, register-isolated OUT of the
// REG-254 shade kernel via __noinline__ so the fleet kernel's live set is
// unchanged (memory noinline-runtime-flag-avoids-shade-spill / pkg224 pattern).
// Called from shadePathSlot only when c_wfEnvNeeBinding.enabled && a loaded HDRI
// && the (bounce+1)<=worldMaxBounces gate holds -- an INDEPENDENT additive
// strategy, disjoint from lamp NEE (env miss vs finite emitter). RNG contract
// (Terra GPU-leg constraint 1): the two CDF uniforms are drawn FIRST and
// UNCONDITIONALLY (even on rejection), matching the CPU wavefront's unconditional
// env_seed draw so the RNG dimension is consumed before RR. Returns true whenever
// the env-NEE strategy ran at this vertex (drew RNG), regardless of whether a
// record was parked -- the caller stores this into env_nee_sampled_prev so the
// next-bounce miss leg knows env NEE competed. The env radiance L_spec is resolved
// lazily in stageEnvShadowKernel (register economy); here we prefold everything
// except L_spec: throughput * f_spec * (wt / envPdf).
template<bool HasPrincipled>
__device__ ASTRORAY_SHADE_NOINLINE inline bool gpu_env_nee_generate(
    int idx, int bounce, GHitRecord& rec, const GVec3& wo,
    const GMaterial& mat, const GSampledSpectrum& throughput,
    const GSampledWavelengths& lambdas, WavefrontRNG* rng)
{
    const GEnvMap& em = c_wfEnvNeeBinding.envMap;
    // pkg258 (Terra item 3): RNG contract — draw exactly ONE main-stream
    // dimension (UniformUInt32), matching the CPU wavefront oracle
    // (path_kernel.cpp:374) which seeds a std::mt19937 from a single draw. The
    // two CDF uniforms come from a LOCAL PCG32 hash of that seed, so downstream
    // RR + the next bounce stay dimension-aligned with the CPU on HDRI scenes.
    // The draw is UNCONDITIONAL (even on the rejections below), mirroring the
    // CPU's unconditional env_seed draw inside its gated block.
    uint32_t env_seed = rng->UniformUInt32();
    float xi1 = gpu_env_seed_uniform(env_seed, 0);
    float xi2 = gpu_env_seed_uniform(env_seed, 1);
    GEnvSample es = gpu_envmap_sample_dir_pdf(em, xi1, xi2);
    if (es.pdf <= 0.f) return true;
    GVec3 wi = es.direction.normalized();
    // Delta guard (Terra Q1d): rec.isDelta is not set before NEE; guard per
    // direction on bsdfPdf>0 so a near-delta metal (f!=0, pdf==0) does not
    // double-count with its unweighted specular miss.
    float bsdfPdf = gpu_material_pdf<HasPrincipled>(mat, rec, wo, wi);
    if (bsdfPdf <= 0.f) return true;
    GSampledSpectrum f_spec = gpu_material_eval_spectral<HasPrincipled>(mat, rec, wo, wi, lambdas);
    if (f_spec.maxValue() <= 0.f) return true;
    // pkg258 (Terra item 6): COMPLEMENTARY power heuristic (Veach 1997). This
    // w(env,bsdf) plus the miss leg's w(bsdf,env) sum to EXACTLY one; the old
    // gpu_mw_powerHeuristic 1e-8 denom epsilon made the pair sum to < 1 (dark
    // bias). The lamp/emissive legs keep the epsilon form unchanged.
    float wt = gpu_mw_powerHeuristicExact(es.pdf, bsdfPdf);
    float scale = wt / es.pdf;
    int cap = c_wfEnvNeeBinding.capacity;
    float* ef = c_wfEnvNeeBinding.envNeeF;
    ef[0 * cap + idx] = rec.point.x;
    ef[1 * cap + idx] = rec.point.y;
    ef[2 * cap + idx] = rec.point.z;
    ef[3 * cap + idx] = wi.x;
    ef[4 * cap + idx] = wi.y;
    ef[5 * cap + idx] = wi.z;
    ef[6 * cap + idx] = throughput.v[0] * f_spec.v[0] * scale;
    ef[7 * cap + idx] = throughput.v[1] * f_spec.v[1] * scale;
    ef[8 * cap + idx] = throughput.v[2] * f_spec.v[2] * scale;
    ef[9 * cap + idx] = throughput.v[3] * f_spec.v[3] * scale;
    // pkg258 (Terra item 10): park the GENERATE-TIME wavelength state with the
    // record. f_spec above was evaluated at THESE lambdas, but a dispersive
    // refraction on the continuation ray (gpu_material_sample_spectral →
    // terminateSecondary, written back to state.lambda_*) mutates the slot's
    // wavelengths BEFORE stageEnvShadowKernel resolves L_spec. Reading the
    // post-mutation state there would evaluate the env radiance at collapsed
    // hero-only wavelengths while f_spec used the full spectrum — a dispersive
    // bias. Parking the pre-sample lambdas + pdfs keeps L_spec and the clamp
    // consistent with f_spec. Non-dispersive paths write back identical values.
    ef[10 * cap + idx] = lambdas.lambda[0];
    ef[11 * cap + idx] = lambdas.lambda[1];
    ef[12 * cap + idx] = lambdas.lambda[2];
    ef[13 * cap + idx] = lambdas.lambda[3];
    ef[14 * cap + idx] = lambdas.pdf[0];
    ef[15 * cap + idx] = lambdas.pdf[1];
    ef[16 * cap + idx] = lambdas.pdf[2];
    ef[17 * cap + idx] = lambdas.pdf[3];
    c_wfEnvNeeBinding.envNeeI[idx] = bounce;
    int q = atomicAdd(c_wfEnvNeeBinding.envShadowCount, 1);
    c_wfEnvNeeBinding.envShadowQueue[q] = idx;
    return true;
}

template<bool Deferred, bool HasPrincipled, bool HasTexture = false, bool HasPhotons = false,
         bool HasDispersion = false, bool HasLightPassAOVs = false,  // pkg198 S2 pass axis
         bool HasProgram = false,   // pkg219b — per-texel op-VM axis
         bool HasNormalPerturb = false>  // pkg223 — tangent-space normal-map axis
// pkg300: the body is __forceinline__ so a kernel can inline it (the pkg300 fleet
// kernels in stage_shade_fleet_p<P>.cu); stageShadeBucketedKernel and the MIS-snapshot
// kernel call the out-of-line shadePathSlot wrapper below.
__device__ __forceinline__ bool shadePathSlotImpl(
    int idx,
    const GPUWavefrontState& state,       // pkg300: const so the kernel can pass its
    const GPUWavefrontHitBuffers& hitBufs, // __grid_constant__ params without a copy
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
    int               max_depth,
    float*            nee_f, int* nee_i,
    int*              shadow_queue, int* shadow_count, int nee_capacity,
    bool              useLuminanceOutput,
    bool              enableNEE,
    float             clampDirect, float clampIndirect,  // pkg157
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid,
    float             photonScale,
    bool              captureMis = false,  // pkg55-C7: MIS instrumentation
                                           // stores only for the PostNEE_MIS
                                           // snapshot harness (perf: the #484
                                           // always-on stores were 3 global
                                           // writes per NEE shade in the
                                           // production hot path)
    // pkg159: per-PIXEL cryptomatte rank arrays (numPixels*depth*2 floats
    // each), owned by the driver. cryptoDepth == 0 or null pointers = crypto
    // disabled, which is the default and costs one predicated branch.
    float*            cryptoObjectRanks = nullptr,
    float*            cryptoMaterialRanks = nullptr,
    int               cryptoDepth = 0)
{
    const int bounce = state.bounce[idx];

    GRay ray;
    ray.direction = GVec3(state.ray_direction_x[idx], state.ray_direction_y[idx],
                          state.ray_direction_z[idx]);
    // pkg55-C4: deformation-motion time (pkg88-C.0). Carried from init, threaded
    // to shadow rays (gpu_nee_occlude).
    ray.time = state.path_time[idx];

    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[idx];
    lambdas.lambda[1] = state.lambda_1[idx];
    lambdas.lambda[2] = state.lambda_2[idx];
    lambdas.lambda[3] = state.lambda_3[idx];
    lambdas.pdf[0] = state.lambda_pdf_0[idx];
    lambdas.pdf[1] = state.lambda_pdf_1[idx];
    lambdas.pdf[2] = state.lambda_pdf_2[idx];
    lambdas.pdf[3] = state.lambda_pdf_3[idx];

    GSampledSpectrum throughput;
    throughput.v[0] = state.throughput_0[idx];
    throughput.v[1] = state.throughput_1[idx];
    throughput.v[2] = state.throughput_2[idx];
    throughput.v[3] = state.throughput_3[idx];

    GSampledSpectrum color;
    color.v[0] = state.color_0[idx];
    color.v[1] = state.color_1[idx];
    color.v[2] = state.color_2[idx];
    color.v[3] = state.color_3[idx];

    WavefrontRNG rng(state.rng_pixel[idx], state.rng_sample[idx],
                     state.rng_seed[idx]);
    rng.setDimension(state.rng_dimension[idx]);

    bool wasSpecular = state.was_specular[idx] != 0;

    // ---- Reconstruct the hit record parked by intersectPathSlot.
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

    // pkg178 Stage-3b PR-4b — UV-aligned shading tangent for anisotropic
    // Principled. Default to the arbitrary frame; override from the hit triangle's
    // uploaded active-layer UVs when present. Behind `if constexpr (HasPrincipled)`
    // so the non-principled <false> shade kernel compiles this out entirely, and
    // behind the per-triangle `uvAuthored` runtime gate (pkg242): the CPU only
    // builds a UV-aligned tangent for meshes with a real UV layer (shapes.h), so a
    // UV-less aniso surface keeps the arbitrary frame here too — and non-aniso
    // principled scenes pay nothing. Computed here (not the intersect stage) to avoid a per-path
    // hit-buffer SoA field (see PR report: honors "zero device memory" for
    // non-aniso scenes at the cost of the aniso branch's registers in the <true>
    // kernel — LEAD measures via cuobjdump). NOTE: uses the triangle's stored
    // (object-local for instanced BLAS) verts; correct for the non-instanced flat
    // scene the parity gates use; instanced-aniso tangent orientation is a
    // declared follow-up.
    rec.uvTangent = rec.tangent;
    rec.uvBitangentSign = 1.0f;
    if constexpr (HasPrincipled) {
        if (rec.primId >= 0 && prims[rec.primId].type == GPRIM_TRIANGLE) {
            const GTriangle& utri = tris[prims[rec.primId].index];
            if (utri.uvAuthored) {  // pkg242: UV-aligned frame only for authored UVs (CPU parity)
                GVec3 uvT; float uvSign;
                if (gpu_pr_uvAlignedTangent(utri.v0, utri.v1, utri.v2,
                                            utri.uv0, utri.uv1, utri.uv2,
                                            rec.normal, uvT, uvSign)) {
                    rec.uvTangent = uvT;
                    rec.uvBitangentSign = uvSign;
                }
            }
        }
    }

    // pkg223 — tangent-space normal-map perturbation of the shading normal.
    // Behind `if constexpr (HasNormalPerturb)` so every fleet <…,false> shade
    // specialization compiles this out ENTIRELY and stays byte-identical
    // (GMaterial is untouched — the normal map rides the __constant__
    // c_wfTexBinding side arrays, memory wavefront-shade-kernels-register-
    // saturated). Mirrors the CPU NormalMappedPlugin::perturbNormal EXACTLY for
    // parity: build the UV-aligned (Mikk-TSpace / Lengyel) frame from the hit
    // triangle (gpu_pr_uvAlignedTangent — the lambertian path has no precomputed
    // uvTangent, that is HasPrincipled-only), decode n_ts = 2·rgb − 1, rotate,
    // and lerp toward the geometric normal by the Cycles Strength. Rebuilds the
    // ONB so the BSDF sample/eval below shade against the perturbed frame.
    if constexpr (HasNormalPerturb) {
        const int nmTexId = c_wfTexBinding.matNormalTexId[rec.materialId];
        if (nmTexId >= 0 && rec.primId >= 0 &&
            prims[rec.primId].type == GPRIM_TRIANGLE) {
            const GTriangle& ntri = tris[prims[rec.primId].index];
            if (ntri.uvAuthored) {  // pkg242: keep arbitrary frame for UV-less normal-map (CPU parity)
                GVec3 nT; float nSign;
                if (gpu_pr_uvAlignedTangent(ntri.v0, ntri.v1, ntri.v2,
                                            ntri.uv0, ntri.uv1, ntri.uv2,
                                            rec.normal, nT, nSign)) {
                    // Barycentric UV at the hit (same recompute as the texture
                    // path; short-lived, folded into the perturbed normal).
                    GVec3 e1 = ntri.v1 - ntri.v0, e2 = ntri.v2 - ntri.v0;
                    GVec3 ep = rec.point - ntri.v0;
                    float d00 = e1.dot(e1), d01 = e1.dot(e2), d11 = e2.dot(e2);
                    float d20 = ep.dot(e1), d21 = ep.dot(e2);
                    float denom = d00 * d11 - d01 * d01;
                    if (fabsf(denom) > 1e-20f) {
                        float b1 = (d11 * d20 - d01 * d21) / denom;
                        float b2 = (d00 * d21 - d01 * d20) / denom;
                        float b0 = 1.0f - b1 - b2;
                        float uu = b0*ntri.uv0.x + b1*ntri.uv1.x + b2*ntri.uv2.x;
                        float vv = b0*ntri.uv0.y + b1*ntri.uv1.y + b2*ntri.uv2.y;
                        const GImageTexture& ndesc = c_wfTexBinding.textures[nmTexId];
                        if (ndesc.hasMapping) {
                            const float* m = ndesc.mapping;
                            float mu = m[0]*uu + m[1]*vv + m[3];
                            float mv = m[4]*uu + m[5]*vv + m[7];
                            uu = mu; vv = mv;
                        }
                        GVec3 rgb = gpu_sampleImageTexture(
                            ndesc, c_wfTexBinding.texelBuf, uu, vv);
                        GVec3 nTS = rgb * 2.0f - GVec3(1.0f);
                        GVec3 B = rec.normal.cross(nT) * nSign;
                        GVec3 mapped = (nT * nTS.x + B * nTS.y +
                                        rec.normal * nTS.z).normalized();
                        float t = fminf(fmaxf(
                            c_wfTexBinding.matNormalStrength[rec.materialId], 0.0f), 1.0f);
                        rec.normal = (rec.normal * (1.0f - t) +
                                      mapped * t).normalized();
                        gpu_buildONB(rec.normal, rec.tangent, rec.bitangent);
                    }
                }
            }
        }
        // pkg223b — Bump node (device twin of NormalMappedPlugin's corrected bump
        // branch). Mutually exclusive with a normal map per material; try it when a
        // height texture is set. Cycles svm_node_set_bump surface-gradient formula
        // (Mikkelsen 2010) sourcing dP.dx/dP.dy from the UV-aligned tangent frame.
        const int bmTexId = c_wfTexBinding.matBumpTexId[rec.materialId];
        if (bmTexId >= 0 && rec.primId >= 0 &&
            prims[rec.primId].type == GPRIM_TRIANGLE) {
            const GTriangle& btri = tris[prims[rec.primId].index];
            if (btri.uvAuthored) {  // pkg242: keep arbitrary frame for UV-less bump (CPU parity)
                GVec3 bT; float bSign;
                float bScaleU = 1.0f, bScaleV = 1.0f;  // #753 world-per-UV-unit scale
                if (gpu_pr_uvAlignedTangent(btri.v0, btri.v1, btri.v2,
                                            btri.uv0, btri.uv1, btri.uv2,
                                            rec.normal, bT, bSign,
                                            &bScaleU, &bScaleV)) {
                    GVec3 e1 = btri.v1 - btri.v0, e2 = btri.v2 - btri.v0;
                    GVec3 ep = rec.point - btri.v0;
                    float d00 = e1.dot(e1), d01 = e1.dot(e2), d11 = e2.dot(e2);
                    float d20 = ep.dot(e1), d21 = ep.dot(e2);
                    float denom = d00 * d11 - d01 * d01;
                    if (fabsf(denom) > 1e-20f) {
                        float b1 = (d11 * d20 - d01 * d21) / denom;
                        float b2 = (d00 * d21 - d01 * d20) / denom;
                        float b0 = 1.0f - b1 - b2;
                        float uu = b0*btri.uv0.x + b1*btri.uv1.x + b2*btri.uv2.x;
                        float vv = b0*btri.uv0.y + b1*btri.uv1.y + b2*btri.uv2.y;
                        const GImageTexture& bdesc = c_wfTexBinding.textures[bmTexId];
                        // valueOffset offsets in POST-mapping UV space (CPU parity).
                        if (bdesc.hasMapping) {
                            const float* m = bdesc.mapping;
                            float mu = m[0]*uu + m[1]*vv + m[3];
                            float mv = m[4]*uu + m[5]*vv + m[7];
                            uu = mu; vv = mv;
                        }
                        // Texel-relative step (~1.5 texels) — nearest-neighbour
                        // sampling needs the finite difference to cross a texel
                        // boundary; mirrors the CPU NormalMappedPlugin bump branch.
                        int bw = bdesc.width > bdesc.height ? bdesc.width : bdesc.height;
                        float eps = (bw > 0) ? (1.5f / (float)bw) : 1.0e-2f;
                        GVec3 hc = gpu_sampleImageTexture(bdesc, c_wfTexBinding.texelBuf, uu, vv);
                        GVec3 hx = gpu_sampleImageTexture(bdesc, c_wfTexBinding.texelBuf, uu + eps, vv);
                        GVec3 hy = gpu_sampleImageTexture(bdesc, c_wfTexBinding.texelBuf, uu, vv + eps);
                        float h_c = 0.2126f*hc.x + 0.7152f*hc.y + 0.0722f*hc.z;
                        float h_x = 0.2126f*hx.x + 0.7152f*hx.y + 0.0722f*hx.z;
                        float h_y = 0.2126f*hy.x + 0.7152f*hy.y + 0.0722f*hy.z;
                        GVec3 N = rec.normal;
                        GVec3 Bt = N.cross(bT) * bSign;
                        // #753 — dPdx/dPdy must be WORLD-space position
                        // differentials (Cycles svm_node_set_bump dP.dx/dP.dy),
                        // not UV-space ones; bT/Bt are unit vectors, so scale
                        // the UV-space step `eps` by the world-per-UV-unit
                        // factor (mirrors normal_mapped.cpp's CPU fix exactly).
                        GVec3 dPdx = bT * (eps * bScaleU), dPdy = Bt * (eps * bScaleV);
                        GVec3 Rx = dPdy.cross(N), Ry = N.cross(dPdx);
                        float det = dPdx.dot(Rx);
                        GVec3 surfgrad = Rx * (h_x - h_c) + Ry * (h_y - h_c);
                        float dist = c_wfTexBinding.matBumpDistance[rec.materialId];
                        float sgn = (det < 0.0f) ? -1.0f : 1.0f;
                        GVec3 perturbed = N * fabsf(det) - surfgrad * (dist * sgn);
                        float len = perturbed.length();
                        perturbed = (len > 1e-8f) ? perturbed * (1.0f / len) : N;
                        float s = fminf(fmaxf(
                            c_wfTexBinding.matBumpStrength[rec.materialId], 0.0f), 1.0f);
                        rec.normal = (perturbed * s + N * (1.0f - s)).normalized();
                        gpu_buildONB(rec.normal, rec.tangent, rec.bitangent);
                    }
                }
            }
        }
    }

    // pkg219d — scalar BSDF-parameter op-VM override. Independent of the base-colour
    // texture (a roughness-only material has base-colour texId == -1), so it runs
    // HERE (before the HasTexture base-colour block and before the NEE/BSDF closure
    // is built). Each of the K slots fetches its OWN source image (matScalarTexId)
    // and runs the SAME shared svm_eval as the CPU DisneyPlugin::substituted() twin,
    // then overwrites a LOCAL GMaterial copy. The copy + the whole block live ONLY in
    // the <HasProgram=true> specialization (an already-isolated axis); the fleet
    // <false> kernel keeps `mat` a plain reference to the uploaded material and
    // allocates ZERO extra stack (GScalarOverride<false> is empty), so it stays
    // byte-identical (register-probe gate). matPtr never re-points in the <false>
    // path, so the compiler collapses it back to the original reference.
    const ::GMaterial* matPtr = &materials[rec.materialId];
    GScalarOverride<HasProgram> matScalarOv;
    if constexpr (HasProgram) {
        bool anyOverride = false;
        // #989 — per-hit shading context for OP_SHADING (CPU twin: ProgramTexture::
        // valueAtHit): cos(view, shading normal) and the back-face flag.
        astroray::svm::SvmShading sh;
        // pkg314: Cycles sd->N, i.e. the parked shading normal BEFORE the Bump /
        // Normal Map perturbation above (verified against Cycles 5.2; CPU twin
        // HitRecord::shadingContextNormal, GPU graph kernel stage_graph_eval.cu).
        const GVec3 svmN(hitBufs.hit_normal_x[idx], hitBufs.hit_normal_y[idx],
                         hitBufs.hit_normal_z[idx]);
        sh.cosI = (ray.direction * -1.0f).normalized().dot(svmN);
        sh.backfacing = rec.frontFace ? 0.0f : 1.0f;
        // #991 — Light Path outputs: path state + the parked hit distance.
        if (c_wfLightPath.enabled)
            sh.path = gpu_lpContext(state.lp_state[idx], bounce, rec.t, ray.direction);
        if (c_wfProgBinding.matScalarProgId && c_wfProgBinding.matScalarTexId) {
            const int base = rec.materialId * astroray::svm::VM_SCALAR_SLOTS;
            for (int slot = 0; slot < astroray::svm::VM_SCALAR_SLOTS; ++slot) {
                int sProg = c_wfProgBinding.matScalarProgId[base + slot];
                int sTex  = c_wfProgBinding.matScalarTexId[base + slot];
                if (sProg < 0) continue;
                // #846: same fetch as base-colour inputs — 2D image / UV bake or a
                // Generated 3D voxel bake of a procedural input. #989: sTex -1 with
                // a program = shading inputs only (scene_upload uploadProgramTexture).
                GProgInputTexel src{GVec3(0.0f, 0.0f, 0.0f), true};
                if (sTex >= 0)
                    src = gpu_progInputEval(rec.point, rec.primId, prims, tris, sTex);
                if (!src.ok)
                    continue;  // non-triangle / UV-less hit → skip (mirrors base colour)
                GVec3 vmIn[astroray::svm::VM_MAX_TEX];
                for (int t = 0; t < astroray::svm::VM_MAX_TEX; ++t) vmIn[t] = src.c;
                float v = astroray::svm::svm_eval(
                    c_wfProgBinding.programs[sProg], vmIn, &sh).x;
                if (!anyOverride) {
                    matScalarOv.mat = materials[rec.materialId];
                    anyOverride = true;
                }
                gpu_applyScalarOverride(matScalarOv.mat, slot, v);
            }
        }
        // #988 — per-texel Base Color of a native Principled (CPU twin:
        // PrincipledPlugin::substituted). The Principled lobes are not linear in
        // base colour, so the texel is written into the LOCAL copy's every base-
        // colour representation (gpu_principled_* reads principled.color) instead
        // of the lambertian throughput swap (skipped for Principled below).
        if (gpu_closure_graph_is_principled(materials[rec.materialId])) {
            const GProgInputTexel bc = gpu_principledBaseTexel(
                rec.point, rec.primId, prims, tris, rec.materialId, sh);
            if (bc.ok) {
                if (!anyOverride) {
                    matScalarOv.mat = materials[rec.materialId];
                    anyOverride = true;
                }
                matScalarOv.mat.baseColor = bc.c;
                matScalarOv.mat.principled.color = bc.c;
                matScalarOv.mat.closures[0].color = bc.c;
            }
        }
        // pkg314 — graph value programs. The dedicated graph-evaluation kernel
        // (stage_graph_eval.cu) ran this round's programs before this launch; read
        // its per-path results (NaN = an input missed at this hit -> constant kept,
        // as the op-VM path). CPU twin: GraphProgramTexture via the plugins' scalar
        // programs / PrincipledPlugin::substituted.
        if (c_wfProgBinding.matGraphProg) {
            const int* gp = c_wfProgBinding.matGraphProg +
                            rec.materialId * astroray::sgraph::GRAPH_MAT_SLOTS;
            const float* go = c_wfProgBinding.graphOut;
            const int gst = c_wfProgBinding.graphOutStride;
            for (int slot = 0; slot < astroray::svm::VM_SCALAR_SLOTS; ++slot) {
                if (gp[slot] < 0) continue;
                const float v = go[slot * gst + idx];
                if (isnan(v)) continue;
                if (!anyOverride) {
                    matScalarOv.mat = materials[rec.materialId];
                    anyOverride = true;
                }
                gpu_applyScalarOverride(matScalarOv.mat, slot, v);
            }
            if (gp[astroray::sgraph::GRAPH_SLOT_BASE_COLOR] >= 0 &&
                gpu_closure_graph_is_principled(materials[rec.materialId])) {
                const GVec3 c(go[4 * gst + idx], go[5 * gst + idx], go[6 * gst + idx]);
                if (!isnan(c.x)) {
                    if (!anyOverride) {
                        matScalarOv.mat = materials[rec.materialId];
                        anyOverride = true;
                    }
                    matScalarOv.mat.baseColor = c;
                    matScalarOv.mat.principled.color = c;
                    matScalarOv.mat.closures[0].color = c;
                }
            }
        }
        if (anyOverride) matPtr = &matScalarOv.mat;
    }
    const ::GMaterial& mat = *matPtr;

    // pkg225 Stage 4 — restore the strand tangent + azimuthal v for a curve/hair
    // hit. The curve leaf set rec.uvTangent (∂p/∂u) and rec.hairV in the register-
    // resident GHitRecord, but the default parking does not persist them and the
    // shade reconstruction above defaulted rec.uvTangent to the arbitrary `tangent`
    // frame (the triangle-UV override is HasPrincipled+GPRIM_TRIANGLE only). Gated
    // by the runtime c_hasHair flag AND the hair material type, so a non-hair fleet
    // scene NEVER emits these SoA loads → the fleet shade kernel is register-byte-
    // identical (register-probe gate). h = 2·hairV − 1 is applied in gpu_hair.cuh.
    if (c_hasHair && mat.type == GMAT_HAIR_PRINCIPLED) {
        rec.uvTangent = GVec3(hitBufs.hit_uv_tangent_x[idx],
                              hitBufs.hit_uv_tangent_y[idx],
                              hitBufs.hit_uv_tangent_z[idx]);
        rec.hairV = hitBufs.hit_hair_v[idx];
    }

    // pkg186 — image-texture base color for a textured lambertian. The whole
    // diffuse bounce (NEE eval, BSDF throughput, continuation) is LINEAR in
    // albedo_spec = upsample(baseColor), so substituting the sampled texel is a
    // SINGLE multiply of `throughput` by the spectral ratio
    // upsample(texColor)/upsample(baseColor), applied here BEFORE NEE and BSDF.
    // This leaves the shared material dispatch untouched — no per-hit GMaterial
    // copy (GMaterial is a zero-slack 640 B struct; a copy spills the shared
    // kernel) — and, gated behind `if constexpr (HasTexture)`, compiles to
    // nothing in the untextured <...,false> kernel the fleet runs. UVs are
    // interpolated from the hit triangle's uploaded active-layer texcoords
    // (scene_upload sets hasUV on image-textured triangles) via barycentrics
    // recomputed from the world hit point (Ericson, Real-Time Collision
    // Detection §3.4) — mirrors pkg178's in-kernel recompute (no extra per-path
    // SoA field; correct for the non-instanced meshes the parity gate uses;
    // instanced-texture UV is a declared follow-up, same cut pkg178 took for
    // instanced aniso). matTexId[]==-1 (every non-image material) skips this.
    // NOTE: Russian roulette (bounce > kRRDepth) then keys off the already-
    // textured throughput one bounce earlier than the CPU folds albedo in; RR is
    // unbiased/mean-preserving so the per-channel mean-ratio gate is unaffected.
    //
    // The texture arrays are read from the __constant__ c_wfTexBinding symbol
    // (set once per frame via setWavefrontTextureBinding), NOT from kernel
    // signature params. Threading them as three per-launch pointer params grew
    // the SHARED kernel signature (CONSTANT[0] +28 B) and cost +24 B STACK on the
    // untextured <false,false> fleet kernel even though the code is if-constexpr'd
    // out — measured on native sm_120 (STACK 3632 vs main's 3608). Moving them to
    // constant memory keeps the <false,*> signature at its pre-pkg186 footprint.
    if constexpr (HasTexture) {
        const int* matTexId = c_wfTexBinding.matTexId;
        int texId = matTexId[rec.materialId];
        // pkg314 — a textured lambertian whose base colour is a graph value
        // program (texId -1): the graph-evaluation kernel's per-path result, then
        // the SAME albedo swap as the texture path below (scene_upload neutralises
        // baseColor to (1,1,1) for it as for any textured lambertian).
        if constexpr (HasProgram) {
            const int* gp = c_wfProgBinding.matGraphProg;
            if (texId < 0 && gp && !gpu_closure_graph_is_principled(mat) &&
                gp[rec.materialId * astroray::sgraph::GRAPH_MAT_SLOTS +
                   astroray::sgraph::GRAPH_SLOT_BASE_COLOR] >= 0) {
                const float* go = c_wfProgBinding.graphOut;
                const int gst = c_wfProgBinding.graphOutStride;
                const GVec3 gc(go[4 * gst + idx], go[5 * gst + idx], go[6 * gst + idx]);
                if (!isnan(gc.x)) {
                    GSampledSpectrum texUp = gpu_rgbToSampledSpectrum(gc, lambdas, mat.spectralMode);
                    GSampledSpectrum baseUp =
                        gpu_rgbToSampledSpectrum(mat.baseColor, lambdas, mat.spectralMode);
                    for (int s = 0; s < G_SPECTRUM_SAMPLES; ++s)
                        throughput.v[s] *= texUp[s] / fmaxf(baseUp[s], 1e-4f);
                }
            }
        }
        // #988: a Principled base-colour texture was already substituted into the
        // material above (HasProgram block); the lambertian swap must not re-apply it.
        if (texId >= 0 && !gpu_closure_graph_is_principled(mat)) {
            const GImageTexture& tdesc = c_wfTexBinding.textures[texId];
            GVec3 texColor;
            bool  haveTex = false;
            // #1007: a per-hit procedural descriptor only exists when scene_upload
            // set hasProgram, so the <HasProgram=false> kernels compile this out.
            bool perHitProc = false;
            if constexpr (HasProgram) perHitProc = tdesc.procId >= 0 || tdesc.attrLayer >= 0;  // #990
            if (perHitProc) {
                texColor = gpu_progInputEval(rec.point, rec.primId, prims, tris, texId).c;
                haveTex = true;
            } else if (tdesc.depth > 1) {
                // pkg190 — 3D voxel procedural (Generated coord; Object-mode
                // procedurals are never baked — scene_upload.cu convention:
                // CPU Object passes the raw unnormalized objectPoint). Rebuild
                // the SAME normalized coordinate the CPU used
                // (include/advanced_features.h CoordMode::Generated):
                //   g = clamp((objectPoint - genMin)/genSize, 0, 1).
                // The addon bakes world transforms into vertices, so world ==
                // object space for these (non-instanced) meshes and rec.point IS
                // objectPoint. Needs no triangle UVs (works for any hit prim);
                // instanced-mesh object-local Generated coords are the same cut
                // pkg178/pkg186 took for instanced anisotropy/texture.
                // #847: per-vertex object-space Generated first (see
                // gpu_generatedCoord), else the bbox frame above.
                GVec3 g = gpu_generatedCoord(rec.point, rec.primId, prims, tris, texId);
                texColor = gpu_sampleProcedural3D(tdesc, c_wfTexBinding.texelBuf, g);
                haveTex = true;
            } else if (rec.primId >= 0 &&
                       prims[rec.primId].type == GPRIM_TRIANGLE) {
                const GTriangle& ttri = tris[prims[rec.primId].index];
                if (ttri.hasUV) {
                    GVec3 e1 = ttri.v1 - ttri.v0, e2 = ttri.v2 - ttri.v0;
                    GVec3 ep = rec.point - ttri.v0;
                    float d00 = e1.dot(e1), d01 = e1.dot(e2), d11 = e2.dot(e2);
                    float d20 = ep.dot(e1), d21 = ep.dot(e2);
                    float denom = d00 * d11 - d01 * d01;
                    if (fabsf(denom) > 1e-20f) {
                        float b1 = (d11 * d20 - d01 * d21) / denom;
                        float b2 = (d00 * d21 - d01 * d20) / denom;
                        float b0 = 1.0f - b1 - b2;
                        float uu = b0*ttri.uv0.x + b1*ttri.uv1.x + b2*ttri.uv2.x;
                        float vv = b0*ttri.uv0.y + b1*ttri.uv1.y + b2*ttri.uv2.y;
                        // pkg219a — full 3-D Blender Mapping on the sample coord.
                        // Matrix lives in __constant__ (c_wfTexBinding); apply as
                        // (M*(u,v,0)).xy, the exact CPU UV-mode path
                        // (advanced_features.h Texture::value). A few FMAs on the
                        // already-live (uu,vv); no new per-ray state. Register
                        // probe (cuobjdump -res-usage): shade-kernel REG/STACK
                        // histogram identical with vs without this block.
                        if (tdesc.hasMapping) {
                            const float* m = tdesc.mapping;
                            float mu = m[0]*uu + m[1]*vv + m[3];
                            float mv = m[4]*uu + m[5]*vv + m[7];
                            uu = mu; vv = mv;
                        }
                        texColor = gpu_sampleImageTexture(
                            tdesc, c_wfTexBinding.texelBuf, uu, vv);
                        haveTex = true;
                    }
                }
            }
            // pkg219b — per-texel op-VM: transform the sampled image colour
            // through the material's compiled shader program (Color Ramp / Mix /
            // Math / Map Range downstream of the texture). The program + per-
            // material index live in constant/global memory (c_wfProgBinding);
            // svm_eval is the SAME HD evaluator the CPU ProgramTexture runs, so
            // parity is by construction. `if constexpr (HasProgram)` compiles this
            // OUT of every fleet (<false>) shade specialization — byte-identical.
            if constexpr (HasProgram) {
                if (haveTex && c_wfProgBinding.matProgId) {
                    int progId = c_wfProgBinding.matProgId[rec.materialId];
                    if (progId >= 0) {
                        GVec3 vmIn[astroray::svm::VM_MAX_TEX];
                        vmIn[0] = texColor;
                        // #826 — inputs t >= 1 use their own texId; a single-input
                        // program has -1 there and broadcasts input 0 (as before).
                        // An input that cannot be sampled at this hit skips the
                        // whole texture, like an input-0 miss (haveTex = false).
                        const int* inTexIds = c_wfProgBinding.matProgInTexId;
                        const int inBase = rec.materialId * astroray::svm::VM_MAX_TEX;
                        for (int t = 1; t < astroray::svm::VM_MAX_TEX; ++t) {
                            int inTex = inTexIds ? inTexIds[inBase + t] : -1;
                            vmIn[t] = texColor;
                            if (inTex >= 0) {
                                GProgInputTexel s = gpu_progInputEval(
                                    rec.point, rec.primId, prims, tris, inTex);
                                vmIn[t] = s.c;
                                haveTex = haveTex && s.ok;
                            }
                        }
                        if (haveTex) {
                            // #989: same per-hit shading context as the override block.
                            astroray::svm::SvmShading shL;
                            shL.cosI = (ray.direction * -1.0f).normalized().dot(GVec3(
                                hitBufs.hit_normal_x[idx], hitBufs.hit_normal_y[idx],
                                hitBufs.hit_normal_z[idx]));  // pkg314: sd->N, pre-bump
                            shL.backfacing = rec.frontFace ? 0.0f : 1.0f;
                            if (c_wfLightPath.enabled)  // #991
                                shL.path = gpu_lpContext(state.lp_state[idx], bounce,
                                                         rec.t, ray.direction);
                            texColor = astroray::svm::svm_eval(
                                c_wfProgBinding.programs[progId], vmIn, &shL);
                        }
                    }
                }
            }
            if (haveTex) {
                GSampledSpectrum texUp =
                    gpu_rgbToSampledSpectrum(texColor, lambdas, mat.spectralMode);
                // pkg190 fold-guard (advisory #1, PR #590): mat.baseColor is
                // upload-neutralized to (1,1,1) for EVERY textured material
                // (scene_upload.cu), so baseUp is a FIXED neutral reference with no
                // near-zero band. The albedo swap throughput *= texUp/baseUp is an
                // exact, chroma-independent substitution (net reflectance = texUp,
                // since the downstream diffuse fold re-multiplies by this same
                // baseUp). Clamp the denominator instead of the old hard-zero
                // branch (which would nuke a band for a saturated base).
                GSampledSpectrum baseUp =
                    gpu_rgbToSampledSpectrum(mat.baseColor, lambdas, mat.spectralMode);
                for (int s = 0; s < G_SPECTRUM_SAMPLES; ++s) {
                    throughput.v[s] *= texUp[s] / fmaxf(baseUp[s], 1e-4f);
                }
            }
        }
    }

    GVec3 wo = (ray.direction * -1.0f).normalized();

    // ---- NEE (skipped on delta lobes). CPU draws light_seed -> mt19937;
    // GPU twin draws the same dimension -> local curandState (see header).
    // The light_seed draw is gated EXACTLY like the CPU (path_kernel.cpp:230,
    // !isDelta && !lights.empty()) so the RNG dimension stream stays keyed
    // identically even when all lights have zero power (pkg98 N+6 review
    // finding); only the sampling CALL is guarded on totalLightPower — the
    // CPU's lights.sample returns pdf<=0 there and contributes nothing.
    // pkg55-B' template-RNG arc (CONVENTION AMENDMENT to spec sec. 4.2
    // decision #2): the wavefront now draws its NEE/BSDF sampling uniforms
    // DIRECTLY from the per-path PCG32 stream instead of seeding throwaway
    // curandStates from drawn seeds (2x XORWOW curand_init per bounce was
    // the last wavefront-only cost vs the megakernel's one init per path).
    // Per-bounce dimension counts now vary by branch (CPU keeps mt19937
    // sub-streams); the per-stage gates compare only deterministic-given-
    // stage fields and the final-image gates remain the sampling oracle.
    // pkg55-C3: enableNEE flag gates NEE sampling (naive multiwavelength mode).
    // pkg89-wavefront (C7): dedicated lights (point/spot/distant/area lamps)
    // join the wavefront NEE via the SAME unified power-CDF + device sampleLi
    // the MW megakernel uses (gpu_nee.cuh::gpu_dedicated_sample, #489/#500;
    // Cycles kernel/light/{point,spot,distant,area}.h via the CPU mirrors).
    // The (numLights + numDed) gate mirrors both the CPU light_seed gate
    // (path_kernel.cpp:230 !lights.empty() — the CPU LightList spans both
    // kinds) and gpu_nee_sample's own emptiness check.
    if (enableNEE && !rec.isDelta && (numLights + numDed) > 0) {
        if (totalLightPower > 0.f) {
            GNEESample s = gpu_nee_sample(rec, prims, tris, spheres,
                                          lights, numLights, totalLightPower,
                                          dedLights, numDed,
                                          lightTree, &rng);
            if (s.valid) {
                if constexpr (Deferred) {
                    // Defer the TRACE + emission to the shadow stage; the
                    // BSDF eval/pdf/MIS happen HERE where the material code
                    // already lives (Cycles shade_surface.h ordering). The
                    // original lazy post-trace eval order is a pure-math
                    // reorder: identical output, evals paid on occluded
                    // samples in exchange for a lean ~100-reg shadow kernel
                    // (measured tradeoff per the blueprint).
                    GSampledSpectrum f_spec = gpu_material_eval_spectral<HasPrincipled>(
                        mat, rec, wo, s.wi, lambdas);
                    if (f_spec.maxValue() > 0.f) {
                        float bsdfPdf = gpu_material_pdf<HasPrincipled>(mat, rec, wo, s.wi);
                        // Power heuristic (Veach 1997) — mirrors
                        // gpu_mw_powerHeuristic in the MW TU. Delta lights
                        // (pkg140, e.g. zero-diameter sun) force wt = 1
                        // exactly like gpu_nee_resolve: a BSDF ray has zero
                        // probability of hitting a delta direction.
                        float a2 = s.lightPdf * s.lightPdf;
                        float b2 = bsdfPdf * bsdfPdf;
                        float wt = s.isDeltaLight ? 1.0f
                                                  : a2 / (a2 + b2 + 1e-8f);
                        // pkg172(A) secondary: guarded light-pdf (pbrt-v4
                        // convention) — was wt/(lightPdf+1e-3), a biasing
                        // additive-epsilon under-weighting of NEE. Mirrors the
                        // CPU NEE twin (raytracer.h:2558, path_kernel.cpp:290)
                        // already guarded on main (#551); brings the deferred
                        // GPU NEE leg back into CPU parity.
                        float scale = s.lightPdf > 1e-8f ? wt / s.lightPdf : 0.0f;
                        // pkg89-wavefront: dedicated emission is
                        // rgbAt(dedEmissionRGB, λ)·dedGeoScale (gpu_nee_resolve);
                        // dedGeoScale is λ-independent, so fold it into the
                        // parked scale and park only the RGB for the shadow
                        // stage's per-λ upsample.
                        if (s.isDedicated) scale *= s.dedGeoScale;
                        // pkg55-C2 MIS audit: capture the exact pdfs and the
                        // resulting power-heuristic weight (Veach 1997) this NEE
                        // sample used, for the PostNEE_MIS gate. Pure stores to
                        // instrumentation arrays — no RNG draw, no reorder, and
                        // never read by accumulation, so renders are unchanged.
                        // pkg55-C7 perf: gated on captureMis (true only in the
                        // stageShadeNeeMisKernel snapshot path; the production
                        // bucketed pipeline skips the 3 global writes).
                        if (captureMis) {
                            state.path_light_pdf[idx]  = s.lightPdf;
                            state.path_mis_pdf[idx]    = bsdfPdf;
                            state.path_mis_weight[idx] = wt;
                        }
                        nee_f[ 0 * nee_capacity + idx] = s.origin.x;
                        nee_f[ 1 * nee_capacity + idx] = s.origin.y;
                        nee_f[ 2 * nee_capacity + idx] = s.origin.z;
                        nee_f[ 3 * nee_capacity + idx] = s.wi.x;
                        nee_f[ 4 * nee_capacity + idx] = s.wi.y;
                        nee_f[ 5 * nee_capacity + idx] = s.wi.z;
                        nee_f[ 6 * nee_capacity + idx] = s.maxDist;
                        nee_f[ 7 * nee_capacity + idx] = throughput.v[0] * f_spec.v[0] * scale;
                        nee_f[ 8 * nee_capacity + idx] = throughput.v[1] * f_spec.v[1] * scale;
                        nee_f[ 9 * nee_capacity + idx] = throughput.v[2] * f_spec.v[2] * scale;
                        nee_f[10 * nee_capacity + idx] = throughput.v[3] * f_spec.v[3] * scale;
                        // pkg89-wavefront: dedicated-light payload lanes.
                        nee_f[11 * nee_capacity + idx] = s.dedEmissionRGB.x;
                        nee_f[12 * nee_capacity + idx] = s.dedEmissionRGB.y;
                        nee_f[13 * nee_capacity + idx] = s.dedEmissionRGB.z;
                        // pkg199: TRUE vertex->light distance for the world-volume
                        // Beer-Lambert Tr in stageShadowKernel (NOT maxDist, lane
                        // 6, which is a 1e30 occlusion sentinel for sphere/distant
                        // sources). distant/infinite => 0 (non-attenuated).
                        nee_f[14 * nee_capacity + idx] = s.geomDist;
                        nee_i[ 0 * nee_capacity + idx] = s.lightMatId;
                        nee_i[ 1 * nee_capacity + idx] = s.isSphere | (s.lightBack << 1);  // #929
                        nee_i[ 2 * nee_capacity + idx] = s.isDedicated;  // pkg89-wavefront
                        nee_i[ 5 * nee_capacity + idx] = s.dedEmissionProfileIndex;  // pkg218
                        // pkg157: park the bounce depth this NEE sample was taken
                        // at -- the shadow-resolve kernel runs in a later launch,
                        // after state.bounce[idx] may already have advanced (see
                        // the G_WF_NEE_I_LANES comment, gpu_wavefront_state.h).
                        nee_i[ 3 * nee_capacity + idx] = bounce;
                        int qslot = atomicAdd(shadow_count, 1);
                        shadow_queue[qslot] = idx;
                    }
                } else {
                    // Immediate (flat/dense schedulings): original behavior.
                    // pkg55-C4: thread TLAS + ray.time + motionVerts (null-TLAS path
                    // routes to single-level inside gpu_nee_occlude → gpu_tlas_hit).
                    GNEEOcclusion occ = gpu_nee_occlude(
                        s, tlas, instances, blas, bvhNodes, prims, tris, spheres,
                        ray.time, motionVerts);
                    if (!occ.occluded) {
                        GSampledSpectrum nee = gpu_nee_resolve<HasPrincipled>(
                            rec, wo, lambdas, materials, s,
                            s.isSphere ? (occ.frontFace != 0) : true);
                        // pkg157: direct/indirect clamp split (bounce is the
                        // shading vertex's own depth here, no park needed).
                        color += gpu_clampContribMW(throughput * nee, lambdas, bounce,
                                                    clampDirect, clampIndirect,
                                                    useLuminanceOutput);
                    }
                }
            }
        }
    }

    // pkg55-C5 / pkg113: spectral photon-map caustic gather at the PRIMARY hit
    // (bounce==0). Mirrors multiwavelength_kernel.cu:490-507 (MW megakernel gather).
    // Gated on hasPhotonGrid + non-emissive + !useLuminanceOutput (the MW conditions).
    //
    // The MW kernel accumulates in XYZ space (line 481 converts spectral rad→XYZ sample,
    // line 502 adds photon XYZ to sample). The wavefront accumulates in spectral space
    // (color SoA) and converts to XYZ at the regen stage. To match MW behavior, we store
    // photon XYZ contrib in separate photon_xyz_* SoA fields and add it to accum_xyz
    // during regen (after spectral color→XYZ conversion), preserving the XYZ+XYZ math.
    // pkg184: gated at COMPILE time on HasPhotons so ptxas allocates the 50-neighbour
    // gather's live set only in the <*,*,true> instantiations. The runtime guard is
    // preserved unchanged inside — a HasPhotons=true kernel is byte-identical to the
    // pre-pkg184 kernel; a HasPhotons=false kernel (launched when hasPhotonGrid is
    // false) never gathered anyway, so this is behaviour-preserving.
    if constexpr (HasPhotons) {
        if (bounce == 0 && hasPhotonGrid && !useLuminanceOutput && photonGrid.numPhotons > 0) {
            // rec is already the primary hit from intersectPathSlot; check non-emissive.
            // #959: receivers only (a caster holds no photons; the split chain
            // starts only at a non-caster receiver) -- CPU sampleFull twin.
            if (mat.emissionIntensity <= 0.0f && !wf_isPhotonCaster(mat)) {
                int found = 0;
                GVec3 E = astroray::photon::gpu::photonGridGatherKnn(
                    photonGrid, rec.point, 50, 1.1f, found);
                if (found > 0) {
                    GVec3 alb = mat.baseColor;
                    GVec3 photonContrib = GVec3(alb.x * E.x, alb.y * E.y, alb.z * E.z)
                                          * photonScale;
                    // Store in photon_xyz SoA; will be added to accum_xyz during regen.
                    state.photon_xyz_x[idx] = photonContrib.x;
                    state.photon_xyz_y[idx] = photonContrib.y;
                    state.photon_xyz_z[idx] = photonContrib.z;
                }
            }
        }
    }

    // ---- Environment NEE (pkg258). Independent additive strategy (disjoint
    // from lamp NEE), MIS-combined with BSDF sampling via the power heuristic.
    // Placed AFTER lamp NEE and BEFORE RR to match the CPU wavefront oracle's RNG
    // ordering (path_kernel.cpp env block before the RR draw; Terra GPU-leg
    // constraint 1). Register-isolated: the sample generation is a __noinline__
    // body entered only when env NEE is enabled AND an importance-sampled HDRI is
    // loaded AND the (bounce+1)<=worldMaxBounces gate holds -- so non-env / fleet
    // renders never draw the two env uniforms and stay byte-identical (REG 254).
    bool envNeeRan = false;
    if (c_wfEnvNeeBinding.enabled && c_wfEnvNeeBinding.envMap.loaded &&
        (bounce + 1) <= c_wfEnvNeeBinding.worldMaxBounces) {
        envNeeRan = gpu_env_nee_generate<HasPrincipled>(
            idx, bounce, rec, wo, mat, throughput, lambdas, &rng);
    }

    // ---- Russian roulette on luminance of throughput's XYZ (bounce > 3).
    // pkg55-C3: for useLuminanceOutput (non-visible bands), use average of
    // spectral samples instead of XYZ.Y (multiwavelength_kernel.cu:315-318).
    if (bounce > kRRDepth) {
        float p;
        if (useLuminanceOutput) {
            float avg = 0.f;
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) avg += throughput.v[i];
            p = fminf(0.95f, fmaxf(0.0f, avg / float(G_SPECTRUM_SAMPLES)));
        } else {
            GVec3 thrXYZ = gpu_spectrum_to_xyz(throughput, lambdas);
            p = fminf(0.95f, fmaxf(0.0f, thrXYZ.y));
        }
        float rr_u = rng.Uniform();
        bool survived = (rr_u <= p);
        if (!survived) {
            state.color_0[idx] = color.v[0];
            state.color_1[idx] = color.v[1];
            state.color_2[idx] = color.v[2];
            state.color_3[idx] = color.v[3];
            state.path_alive[idx] = 0;
            state.rng_dimension[idx] = rng.dimension();
            return false;
        }
        if (p > 0.0f) throughput *= (1.0f / p);
    }

    // ---- BSDF sampling via the templated megakernel material dispatch
    // (all 7 GMAT types + closure graphs), drawing directly from the
    // per-path PCG32 stream (template-RNG arc; see the NEE note above).
    GBSDFSample bss = gpu_material_sample_spectral<HasPrincipled>(mat, rec, wo, lambdas, &rng);
    if (bss.pdf <= 0.0f) {
        state.color_0[idx] = color.v[0];
        state.color_1[idx] = color.v[1];
        state.color_2[idx] = color.v[2];
        state.color_3[idx] = color.v[3];
        state.path_alive[idx] = 0;
        state.rng_dimension[idx] = rng.dimension();
        return false;
    }
    wasSpecular = bss.isDelta;
    // pkg198 Stage 2: lock the first-bounce light-path category (Cycles locks pass
    // weights at bounce 0). TRANSMISSION if the sampled wi crossed the surface (a
    // geometric sign test on rec.normal — no distance/sentinel per
    // [[occlusion-sentinel-as-distance-class-of-bug]]); else GLOSSY for a delta/
    // mirror reflection or a glossy material; else DIFFUSE. Device twin of the CPU
    // pathTraceSpectral firstCat lock (raytracer.h). Persisted per-slot in the
    // constant-bound firstCat buffer so the intersect/shadow/regen kernels attribute
    // indirect light to the same category. The write is the ONLY shade-kernel cost of
    // the pass partition (NEE is deferred to the shadow kernel) — the REGISTER PROBE
    // (PR #620) measured it at zero STACK / no tier change. Compiled OUT of the fleet
    // <…,false> kernel by if constexpr → byte-identical 254/3352/1700.
    if constexpr (HasLightPassAOVs) {
        if (bounce == 0) {
            float sWo = wo.dot(rec.normal);
            float sWi = bss.wi.dot(rec.normal);
            bool transmitted = (sWo * sWi) < 0.f;
            unsigned char cat = transmitted ? 2
                              : ((bss.isDelta || gpu_material_is_glossy(mat)) ? 1 : 0);
            c_wfLpBinding.firstCat[idx] = cat;
        }
    }
    // pkg120: park this bounce's BSDF pdf so the NEXT bounce's intersect stage
    // can weight a diffuse-bounce emissive hit by the two-sided MIS heuristic
    // (mirrors CPU bsdfPdfPrev = bss.pdf in pathTraceSpectral).
    state.path_bsdf_pdf[idx] = bss.pdf;
    // #851: the normal NEE used at this vertex, for the next hit's tree MIS pdf.
    state.path_mis_nx[idx] = rec.normal.x;
    state.path_mis_ny[idx] = rec.normal.y;
    state.path_mis_nz[idx] = rec.normal.z;
    // pkg258: record whether env NEE competed at THIS vertex so the next-bounce
    // miss leg applies the env power heuristic only when it actually ran (mirrors
    // CPU pathTraceSpectral envNeeSampledPrev; the miss leg also requires
    // !wasSpecular, so a specular continuation stays unweighted regardless).
    state.env_nee_sampled_prev[idx] = envNeeRan ? 1 : 0;

    // pkg55-C3/C7: non-visible-band profile override — mirrors the deleted
    // MW megakernel block (multiwavelength_kernel.cu:376-390) and CPU
    // Material::evalSpectralExt EXACTLY:
    //   * visible λ → keep the RGB-upsampled bss.fSpectral,
    //   * non-visible λ + profile → reflectance(λ) · cosθ / π,
    //   * non-visible λ + NO profile → 0 (RGB albedo is undefined outside
    //     the visible band — the else-zero was dropped in the C3 port and
    //     restored in C7).
    if (!wasSpecular) {
        float cosTheta = fmaxf(0.f, rec.normal.dot(bss.wi));
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
            float lam = lambdas.lambda[i];
            if (lam < 380.f || lam > 780.f) {
                if (mat.profileIndex >= 0) {
                    bss.fSpectral.v[i] =
                        gpu_profile_reflectance(mat.profileIndex, lam)
                        * cosTheta / M_PI_F;
                } else {
                    bss.fSpectral.v[i] = 0.f;
                }
            }
        }
    }

    // pkg159: Cryptomatte per-shade-point accumulation, the device twin of
    // Renderer::pathTraceSpectral (raytracer.h:2581-2602).
    //
    // Placed HERE — after the BSDF sample (the weight needs bss.fSpectral) and
    // BEFORE the throughput update — exactly like the CPU oracle. Sits after
    // the non-visible-band profile override above so bss.fSpectral carries the
    // same value the CPU's Material::sampleSpectral returns.
    //
    // Three deliberate divergences from the DELETED RGB megakernel
    // (path_trace_kernel.cu:602-629, recoverable at 9fa91c8^), all specified by
    // pkg159 and all bug fixes rather than ports:
    //   1. bounce == 0 gate. The CPU records the FIRST HIT only
    //      ("Cryptomatte records only the first hit", raytracer.h:2580); the
    //      megakernel accumulated at every bounce. The CPU is the oracle.
    //   2. hash_to_float(). The megakernel did `float id = tri.objectHash;` —
    //      an implicit uint32→float NUMERIC conversion, so its IDs matched
    //      neither the CPU nor the Psyop `uint32_to_float32` manifest.
    //   3. ATOMIC insert. The megakernel ran one thread per pixel; the
    //      wavefront has many concurrent slots per pixel (regeneration), so the
    //      rank read-modify-write is a data race without atomics. See
    //      crypto_insert_atomic (Cycles film_write_cryptomatte_slots under
    //      __ATOMIC_PASS_WRITE__, Apache-2.0).
    //
    // Weight = average(throughput · bsdf_eval) over linear sRGB, per Cycles
    // film_write_cryptomatte_slots; the matrix is the CIE XYZ D65 → linear
    // sRGB one the CPU inlines at raytracer.h:2586-2588.
    if (bounce == 0 && cryptoDepth > 0 &&
        cryptoObjectRanks != nullptr && cryptoMaterialRanks != nullptr) {
        GSampledSpectrum contrib = throughput * bss.fSpectral;
        GVec3 xyz = gpu_spectrum_to_xyz(contrib, lambdas);
        float r =  3.2406f * xyz.x - 1.5372f * xyz.y - 0.4986f * xyz.z;
        float g = -0.9689f * xyz.x + 1.8758f * xyz.y + 0.0415f * xyz.z;
        float b =  0.0557f * xyz.x - 0.2040f * xyz.y + 1.0570f * xyz.z;
        float weight = (r + g + b) / 3.0f;

        // Object/material hashes ride on the uploaded primitive (scene_upload.cu
        // stores the raw MurmurHash3_x86_32 uint32). GHitRecord carries primId
        // (index into prims[]); the GPrimitive carries type + index into
        // tris[]/spheres[] — there is no rec.primType/primIndex.
        float objectId = CRYPTO_ID_NONE, materialId = CRYPTO_ID_NONE;
        const GPrimitive& prim = prims[rec.primId];
        if (prim.type == GPRIM_TRIANGLE) {
            const GTriangle& tri = tris[prim.index];
            objectId   = hash_to_float(tri.objectHash);
            materialId = hash_to_float(tri.materialHash);
        } else if (prim.type == GPRIM_SPHERE) {
            const GSphere& sph = spheres[prim.index];
            objectId   = hash_to_float(sph.objectHash);
            materialId = hash_to_float(sph.materialHash);
        }

        // Ranks are per-PIXEL, not per-slot: under path regeneration a slot
        // hosts an arbitrary (pixel, sample), so index by pixel_index exactly
        // like stageRegenKernel's radiance accumulation.
        crypto_accumulate_shade_point_atomic(
            cryptoObjectRanks, cryptoMaterialRanks,
            state.pixel_index[idx], cryptoDepth, objectId, materialId, weight);
    }

    throughput *= bss.fSpectral * (bss.pdf > 1e-8f ? 1.0f / bss.pdf : 0.0f);

    // #991 — advance the Light Path state across this bounce (CPU twin:
    // pathTraceSpectral lpc = next_surface(lpc, lobeCat, isDelta)), with the
    // pkg201 bounce class. Light Path scenes always run the HasProgram kernel
    // (scene_upload forces it), so the other variants compile this out.
    if constexpr (HasProgram) {
        if (c_wfLightPath.enabled)
            state.lp_state[idx] = gpu_lpAdvance(state.lp_state[idx], &mat, wo, rec.normal,
                                                bss.wi, bss.isDelta);
    }

    // ---- Throughput clamp (CPU: maxC > 10 -> scale to 10).
    float maxC = throughput.maxValue();
    if (maxC > 10.0f) throughput *= (10.0f / maxC);

    // ---- Advance ray. Single normalization of the BSDF direction (the
    // Phase A.1 rule: normalize HERE, store verbatim, never renormalize at
    // the SoA boundary).
    GVec3 nextDir = bss.wi.normalized();

    // ---- SoA write-back.
    state.ray_origin_x[idx] = rec.point.x;
    state.ray_origin_y[idx] = rec.point.y;
    state.ray_origin_z[idx] = rec.point.z;
    state.ray_direction_x[idx] = nextDir.x;
    state.ray_direction_y[idx] = nextDir.y;
    state.ray_direction_z[idx] = nextDir.z;
    state.throughput_0[idx] = throughput.v[0];
    state.throughput_1[idx] = throughput.v[1];
    state.throughput_2[idx] = throughput.v[2];
    state.throughput_3[idx] = throughput.v[3];
    state.color_0[idx] = color.v[0];
    state.color_1[idx] = color.v[1];
    state.color_2[idx] = color.v[2];
    state.color_3[idx] = color.v[3];
    state.was_specular[idx] = wasSpecular ? 1 : 0;
    state.rng_dimension[idx] = rng.dimension();

    // pkg189 — persist the hero-λ collapse. gpu_material_sample_spectral above
    // called wl.terminateSecondary() on a dispersive refraction event (setting
    // lambda[i]=lambda[0], pdf[i]=0 for the secondaries). Write the mutated
    // lambdas back to SoA so the collapse survives into the next bounce AND into
    // stageRegenKernel's spectrumToXYZ accumulation (which skips pdf==0 samples).
    // For a non-refracting dispersive hit lambdas is unchanged, so this writes
    // back identical values (bit-neutral). Compiled out entirely on the
    // <*,*,*,false> fleet kernels via if constexpr, keeping their footprint and
    // output bit-identical (register gate). Placed only on the surviving/max-depth
    // path: the RR-kill and pdf<=0 early returns above cannot follow a collapse
    // (RR runs before sampling; a dispersive refraction always yields pdf=1).
    if constexpr (HasDispersion) {
        state.lambda_0[idx] = lambdas.lambda[0];
        state.lambda_1[idx] = lambdas.lambda[1];
        state.lambda_2[idx] = lambdas.lambda[2];
        state.lambda_3[idx] = lambdas.lambda[3];
        state.lambda_pdf_0[idx] = lambdas.pdf[0];
        state.lambda_pdf_1[idx] = lambdas.pdf[1];
        state.lambda_pdf_2[idx] = lambdas.pdf[2];
        state.lambda_pdf_3[idx] = lambdas.pdf[3];
    }

    // pkg201 Stage 3 (Finding A) — per-type bounce limit (Cycles
    // max_diffuse/glossy/transmission_bounce). Device twin of the CPU
    // pathTraceSpectral check: classify this bounce's lobe with the SAME
    // geometric-sign + glossy test as the AOV firstCat lock, and if a limit is
    // set for that type and already reached, terminate the path (no continuation
    // ray) exactly like the max_depth cap below — color/rng_dimension are already
    // persisted to SoA above, so this only clears path_alive. The `any-limit`
    // early-out (constant-memory compares only) keeps the all-unlimited fleet
    // default off the SoA counter path: this is the OPTION 2 runtime compare
    // (memory pkg201-s3-runtime-comparison-not-axis), probe-gated — if it moves
    // the fleet <…> REG/STACK it escalates to a compile-time axis.
    if (c_wfBounceLimit[0] >= 0 || c_wfBounceLimit[1] >= 0 || c_wfBounceLimit[2] >= 0) {
        float sWo = wo.dot(rec.normal);
        float sWi = bss.wi.dot(rec.normal);
        int lobeCat = (sWo * sWi < 0.f) ? 2
                    : ((bss.isDelta || gpu_material_is_glossy(mat)) ? 1 : 0);
        int lim = c_wfBounceLimit[lobeCat];
        if (lim >= 0) {
            uint32_t packed = state.per_type_bounce[idx];
            int cnt = (int)((packed >> (lobeCat * 8)) & 0xFFu);
            if (cnt >= lim) {
                state.path_alive[idx] = 0;
                return false;
            }
            // ABI-2: saturate at 255 — an increment past it would carry into the
            // next byte (transmission carries into byte 3, pkg271's volume
            // counter/terminate-after flag). A limit above 255 is unreachable
            // before max_depth ends the path.
            if (cnt < 255)
                state.per_type_bounce[idx] = packed + (1u << (lobeCat * 8));
        }
    }

    // pkg201 Stage 3 (Finding E) — native caustic toggle cull (device twin of the
    // CPU pathTraceSpectral cull). Sticky had_diffuse_ancestor: once the path has
    // scattered off a diffuse surface, a subsequent delta bounce forms a caustic;
    // terminate it when the matching toggle is off (a delta reflection ⇒ cat 1 ⇒
    // reflective; a delta transmission ⇒ cat 2 ⇒ refractive). Both-allow (the
    // fleet default) skips this entirely → byte-identical. Runtime-gated like the
    // Finding-A block above (OPTION-2 shape), probe-decided.
    if (c_wfCausticGate[0] == 0 || c_wfCausticGate[1] == 0) {
        float sWo = wo.dot(rec.normal);
        float sWi = bss.wi.dot(rec.normal);
        int cat = (sWo * sWi < 0.f) ? 2
                : ((bss.isDelta || gpu_material_is_glossy(mat)) ? 1 : 0);
        if (state.had_diffuse_ancestor[idx] && bss.isDelta &&
            ((cat == 2 && c_wfCausticGate[1] == 0) ||
             (cat == 1 && c_wfCausticGate[0] == 0))) {
            state.path_alive[idx] = 0;
            return false;
        }
        if (cat == 0) state.had_diffuse_ancestor[idx] = 1;
    }

    int next_bounce = bounce + 1;
    state.bounce[idx] = next_bounce;
    if (next_bounce >= max_depth) {
        state.path_alive[idx] = 0;
        return false;
    }
    return true;
}

template<bool Deferred, bool HasPrincipled, bool HasTexture = false, bool HasPhotons = false,
         bool HasDispersion = false, bool HasLightPassAOVs = false,
         bool HasProgram = false, bool HasNormalPerturb = false>
__device__ bool shadePathSlot(
    int idx, const GPUWavefrontState& state, const GPUWavefrontHitBuffers& hitBufs,
    const GTLASNode* tlas, const GInstance* instances, const GBLAS* blas,
    const GBVHNode* bvhNodes, const GPrimitive* prims, const GTriangle* tris,
    const GSphere* spheres, const GVec3* motionVerts, const ::GMaterial* materials,
    const ::GLight* lights, int numLights, float totalLightPower,
    const GDedicatedLight* dedLights, int numDed, GLightTreeView lightTree,
    int max_depth, float* nee_f, int* nee_i,
    int* shadow_queue, int* shadow_count, int nee_capacity,
    bool useLuminanceOutput, bool enableNEE,
    float clampDirect, float clampIndirect,
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid, float photonScale,
    bool captureMis = false,
    float* cryptoObjectRanks = nullptr, float* cryptoMaterialRanks = nullptr,
    int cryptoDepth = 0)
{
    return shadePathSlotImpl<Deferred, HasPrincipled, HasTexture, HasPhotons, HasDispersion,
                             HasLightPassAOVs, HasProgram, HasNormalPerturb>(
        idx, state, hitBufs, tlas, instances, blas, bvhNodes, prims, tris, spheres,
        motionVerts, materials, lights, numLights, totalLightPower, dedLights, numDed,
        lightTree, max_depth, nee_f, nee_i, shadow_queue, shadow_count, nee_capacity,
        useLuminanceOutput, enableNEE, clampDirect, clampIndirect,
        photonGrid, hasPhotonGrid, photonScale, captureMis,
        cryptoObjectRanks, cryptoMaterialRanks, cryptoDepth);
}

template<bool HasPrincipled, bool HasTexture, bool HasPhotons, bool HasDispersion,
         bool HasLightPassAOVs = false,  // pkg178 D4; pkg186 texture; pkg184 photons; pkg189 dispersion; pkg198 S2 pass axis
         bool HasProgram = false,   // pkg219b — per-texel op-VM axis
         bool HasNormalPerturb = false>  // pkg223 — tangent-space normal-map axis
__global__ void stageShadeBucketedKernel(
    // pkg300: __grid_constant__ lets the out-of-line shadePathSlot take these ~2 KB
    // by const reference straight from kernel-parameter space. Without it the
    // kernel copied them to the local stack before every call (27 % of shade
    // stall samples, .astroray_plan/docs/pkg300-shade-counter-attribution.md).
    __grid_constant__ const GPUWavefrontState state,
    __grid_constant__ const GPUWavefrontHitBuffers hitBufs,
    const int* shade_queues, const int* shade_counts, int capacity,
    int* queue_out, int* count_out,
    float* nee_f, int* nee_i, int* shadow_queue, int* shadow_count,
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
    int               max_depth,
    bool              useLuminanceOutput,
    bool              enableNEE,
    float             clampDirect, float clampIndirect,  // pkg157
    astroray::photon::gpu::GPhotonGrid photonGrid, bool hasPhotonGrid,
    float             photonScale,
    float* cryptoObjectRanks, float* cryptoMaterialRanks, int cryptoDepth)  // pkg159
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    int bucket = i / capacity;
    int pos    = i - bucket * capacity;
    if (bucket >= G_WF_NUM_MAT_TYPES) return;
    if (pos >= shade_counts[bucket]) return;
    int idx = shade_queues[bucket * capacity + pos];
    // pkg186: texture data comes from the __constant__ c_wfTexBinding symbol, NOT
    // kernel params — keeps the untextured <false,false> signature at its
    // pre-pkg186 footprint (see c_wfTexBinding note above).
    bool alive = shadePathSlot<true, HasPrincipled, HasTexture, HasPhotons, HasDispersion, HasLightPassAOVs, HasProgram, HasNormalPerturb>(idx, state, hitBufs, tlas, instances, blas,
                               bvhNodes, prims, tris, spheres, motionVerts,
                               materials, lights, numLights,
                               totalLightPower, dedLights, numDed,
                               lightTree, max_depth,
                               nee_f, nee_i, shadow_queue, shadow_count,
                               capacity, useLuminanceOutput, enableNEE,
                               clampDirect, clampIndirect,
                               photonGrid, hasPhotonGrid, photonScale,
                               /*captureMis=*/false,  // pkg159: explicit so the
                               // crypto args below bind to the right params
                               cryptoObjectRanks, cryptoMaterialRanks,
                               cryptoDepth);
    if (alive) {
        int slot = atomicAdd(count_out, 1);
        queue_out[slot] = idx;
    }
}
}  // namespace astroray::wavefront

namespace astroray::wavefront {

// ---------------------------------------------------------------------------
// Build-speed split (tooling/build-speed): stageShadeBucketedKernel is compiled
// in 12 separate translation units (src/gpu/wavefront/stage_shade_part<k>.cu):
// HasPrincipled=false parts 0..3 hold all 16 (HasDispersion x LightPassAOVs x
// Program x NormalPerturb) variants of one (T,Ph) pair; the ~2x heavier
// HasPrincipled=true parts 4..11 are split by HasDispersion (8 variants each). nvcc runs one core per TU, so one giant TU
// was the whole build's critical path. The kernel body, its template axes and
// every register/stack invariant documented above are unchanged.
// ---------------------------------------------------------------------------
struct StageShadeArgs {
    GPUWavefrontState* state; GPUWavefrontHitBuffers* hitBufs;
    const int* shade_queues; const int* shade_counts; int capacity;
    int* queue_out; int* count_out;
    float* nee_f; int* nee_i; int* shadow_queue; int* shadow_count;
    const GTLASNode* tlas; const GInstance* instances; const GBLAS* blas;
    const GBVHNode* bvhNodes; const GPrimitive* prims; const GTriangle* tris;
    const GSphere* spheres; const GVec3* motionVerts; const ::GMaterial* materials;
    const ::GLight* lights; int numLights; float totalLightPower;
    const GDedicatedLight* dedLights; int numDed;
    GLightTreeView lightTree;
    int max_depth; bool useLuminanceOutput; bool enableNEE;
    float clampDirect; float clampIndirect;
    astroray::photon::gpu::GPhotonGrid photonGrid; bool hasPhotonGrid;
    float photonScale;
    float* cryptoObjectRanks; float* cryptoMaterialRanks; int cryptoDepth;
};

template<bool P, bool T, bool Ph, bool D, bool LP, bool PR, bool NP>
inline const void* shadeKptr() {
    return (const void*)stageShadeBucketedKernel<P,T,Ph,D,LP,PR,NP>;
}

template<bool P, bool T, bool Ph, bool D, bool LP, bool PR, bool NP>
inline void shadeLaunch(int blocks, int threads, const StageShadeArgs& a) {
    stageShadeBucketedKernel<P,T,Ph,D,LP,PR,NP><<<blocks, threads>>>(
        *a.state, *a.hitBufs, a.shade_queues, a.shade_counts, a.capacity,
        a.queue_out, a.count_out,
        a.nee_f, a.nee_i, a.shadow_queue, a.shadow_count,
        a.tlas, a.instances, a.blas,
        a.bvhNodes, a.prims, a.tris, a.spheres, a.motionVerts, a.materials,
        a.lights, a.numLights, a.totalLightPower,
        a.dedLights, a.numDed, a.lightTree, a.max_depth,
        a.useLuminanceOutput, a.enableNEE,
        a.clampDirect, a.clampIndirect,
        a.photonGrid, a.hasPhotonGrid, a.photonScale,
        a.cryptoObjectRanks, a.cryptoMaterialRanks, a.cryptoDepth);
}

// Runtime selection of the (LP, Program, NormalPerturb) axes for one fixed
// (P,T,Ph,D) - same nesting the pre-split launcher used (pkg198/219b/223).
#define ASTRORAY_SHADE_SELECT(P,T,Ph,D,LP,PR,NP,FN,...) \
    (NP ? (LP ? (PR ? FN<P,T,Ph,D,true ,true ,true >(__VA_ARGS__) \
                    : FN<P,T,Ph,D,true ,false,true >(__VA_ARGS__)) \
              : (PR ? FN<P,T,Ph,D,false,true ,true >(__VA_ARGS__) \
                    : FN<P,T,Ph,D,false,false,true >(__VA_ARGS__))) \
        : (LP ? (PR ? FN<P,T,Ph,D,true ,true ,false>(__VA_ARGS__) \
                    : FN<P,T,Ph,D,true ,false,false>(__VA_ARGS__)) \
              : (PR ? FN<P,T,Ph,D,false,true ,false>(__VA_ARGS__) \
                    : FN<P,T,Ph,D,false,false,false>(__VA_ARGS__))))


// One part TU = one (P,T,Ph) triple. Defines the two host entry points the
// dispatcher in stage_advance.cu calls.
#define ASTRORAY_SHADE_SELECT_STMT(P,T,Ph,D,LP,PR,NP,FN,...) \
    do { if (NP) { \
            if (LP) { if (PR) FN<P,T,Ph,D,true ,true ,true >(__VA_ARGS__); \
                      else    FN<P,T,Ph,D,true ,false,true >(__VA_ARGS__); } \
            else    { if (PR) FN<P,T,Ph,D,false,true ,true >(__VA_ARGS__); \
                      else    FN<P,T,Ph,D,false,false,true >(__VA_ARGS__); } \
        } else { \
            if (LP) { if (PR) FN<P,T,Ph,D,true ,true ,false>(__VA_ARGS__); \
                      else    FN<P,T,Ph,D,true ,false,false>(__VA_ARGS__); } \
            else    { if (PR) FN<P,T,Ph,D,false,true ,false>(__VA_ARGS__); \
                      else    FN<P,T,Ph,D,false,false,false>(__VA_ARGS__); } \
        } } while (0)
// DMODE: 0 = both HasDispersion values in this TU; 1 = HasDispersion=false only;
// 2 = true only. Selected by PREPROCESSOR pasting (not `if constexpr`, which does not
// suppress instantiation outside a template) so a D-split part never instantiates the
// other half. The dispatcher in stage_advance.cu never asks a D-split part for it.
#define ASTRORAY_SHADE_KPTR_D0(P,T,Ph,D,lp,prog,np) \
    ((D) ? ASTRORAY_SHADE_SELECT(P,T,Ph,true ,lp,prog,np,shadeKptr) \
         : ASTRORAY_SHADE_SELECT(P,T,Ph,false,lp,prog,np,shadeKptr))
#define ASTRORAY_SHADE_KPTR_D1(P,T,Ph,D,lp,prog,np) ASTRORAY_SHADE_SELECT(P,T,Ph,false,lp,prog,np,shadeKptr)
#define ASTRORAY_SHADE_KPTR_D2(P,T,Ph,D,lp,prog,np) ASTRORAY_SHADE_SELECT(P,T,Ph,true ,lp,prog,np,shadeKptr)
#define ASTRORAY_SHADE_LAUNCH_D0(P,T,Ph,D,lp,prog,np,blocks,threads,a) \
    do { if (D) ASTRORAY_SHADE_SELECT_STMT(P,T,Ph,true ,lp,prog,np,shadeLaunch,blocks,threads,a); \
         else   ASTRORAY_SHADE_SELECT_STMT(P,T,Ph,false,lp,prog,np,shadeLaunch,blocks,threads,a); } while (0)
#define ASTRORAY_SHADE_LAUNCH_D1(P,T,Ph,D,lp,prog,np,blocks,threads,a) ASTRORAY_SHADE_SELECT_STMT(P,T,Ph,false,lp,prog,np,shadeLaunch,blocks,threads,a)
#define ASTRORAY_SHADE_LAUNCH_D2(P,T,Ph,D,lp,prog,np,blocks,threads,a) ASTRORAY_SHADE_SELECT_STMT(P,T,Ph,true ,lp,prog,np,shadeLaunch,blocks,threads,a)
#define ASTRORAY_DEFINE_SHADE_PART(K,P,T,Ph,DMODE) \
    namespace astroray::wavefront { \
    const void* stageShadePartKernelPtr_##K(bool D, bool lp, bool prog, bool np) { \
        return ASTRORAY_SHADE_KPTR_D##DMODE(P,T,Ph,D,lp,prog,np); \
    } \
    void stageShadePartLaunch_##K(bool D, bool lp, bool prog, bool np, \
                                  int blocks, int threads, const StageShadeArgs& a) { \
        ASTRORAY_SHADE_LAUNCH_D##DMODE(P,T,Ph,D,lp,prog,np,blocks,threads,a); \
    } \
    }

}  // namespace astroray::wavefront

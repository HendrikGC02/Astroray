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

#include "astroray/gpu_wavefront_state.h"
#include "astroray/gpu_types.h"
#include "astroray/shader_vm.h"  // pkg219b — op-VM program + svm_eval
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
__constant__ GWavefrontGuideBinding c_wfGuideBinding;

// pkg201 Stage 2 (Finding F, transparent film) — bounce-0 background-miss coverage
// accumulator, published ONCE per frame (setWavefrontMissCoverage), read by
// intersectPathSlot. For each primary-ray sample (bounce 0) that misses to the
// background, atomicAdd 1.0 into c_wfMissCoverage[pixel]; the driver then derives
// per-pixel alpha = clamp(1 - miss/samples, 0, 1) for transparent film. Null (the
// default — ReSTIR/snapshot drivers, and every non-transparent render) skips the
// add entirely → byte-identical, and it lives in the intersect stage so the
// REG-254 stageShadeBucketedKernel is untouched (the pkg197 guide-AOV precedent).
__constant__ float* c_wfMissCoverage = nullptr;

// pkg199 Stage 1 — homogeneous world-volume medium (Beer-Lambert absorption).
// Published once per frame by cuda_wavefront_render (setWavefrontWorldVolume),
// read by intersectPathSlot (free-flight + lamp-MIS) and stageShadowKernel (NEE)
// at RUNTIME behind `if (c_worldVolume.hasVolume)`. Kept out of the
// REG-254-saturated stageShadeBucketedKernel entirely (which is therefore
// byte-identical) — the pkg197 guide-AOV precedent. Default-zero (hasVolume==0)
// so the snapshot/ReSTIR drivers that never publish it render as vacuum.
__constant__ GWorldVolume c_worldVolume;

// pkg198 Stage 2 — light-path pass binding in constant memory (see
// GWavefrontLightPassBinding in gpu_types.h). Set once per frame by
// setWavefrontLightPassBinding; the shade/intersect kernels read it ONLY inside
// `if constexpr (HasLightPassAOVs)` (keeping the fleet <…,false> specializations
// byte-identical — the REGISTER PROBE result, PR #620), while the non-register-gated
// shadow/volume/regen kernels read it behind a runtime `passAccum != nullptr` guard.
// Declared here (before intersectPathSlotT) because both the intersect and shade
// kernels reference it, exactly like c_wfGuideBinding / c_worldVolume above.
__constant__ GWavefrontLightPassBinding c_wfLpBinding;

// pkg201 Stage 3 (Finding A) — Cycles per-type bounce limits (index 0=diffuse,
// 1=glossy, 2=transmission; -1 = unlimited). Published once per frame by
// cuda_wavefront_render (setWavefrontBounceLimits). shadePathSlot reads it only
// when a limit is set (≥0) — the all-unlimited default (this static initializer,
// used by every render that does not set per-type bounces AND by the
// snapshot/ReSTIR drivers that never publish) makes the per-type block a no-op,
// so the fleet stageShadeBucketedKernel stays byte-identical (register-probe
// gate). Counters ride the GPUWavefrontState.per_type_bounce SoA field, not this
// symbol, mirroring the c_wfTexBinding side-table pattern (pkg186/pkg223).
__constant__ int c_wfBounceLimit[3] = { -1, -1, -1 };

// pkg201 Stage 3 (Finding E) — native caustic toggles (index 0=reflective,
// 1=refractive; 1=allow, 0=cull). Published once per frame by
// cuda_wavefront_render (setWavefrontCausticGate). Both-allow (this static
// default, and every render that does not turn a toggle off) makes shadePathSlot
// skip the caustic-cull block entirely → the fleet kernel stays byte-identical.
__constant__ int c_wfCausticGate[2] = { 1, 1 };

// pkg224 — progressive (hash-Owen Sobol') sampler opt-in. Published once per
// frame by cuda_wavefront_render (setWavefrontSamplerMode). 0 = PCG32 white
// noise (this static default, and every render that leaves the sampler on
// "white" plus the snapshot/ReSTIR drivers that never publish) → the shade
// kernel's WavefrontRNG::Uniform() takes the untouched PCG32 path, byte-identical
// to pre-pkg224 (register-probe gate). 1 = progressive Sobol' (opt-in). This is
// a plain runtime flag (NOT a template axis), the pkg201-S3/pkg186 pattern.
__constant__ int c_wfSamplerMode = 0;

// pkg224 — Sobol' direction-vector table in __constant__ memory (8 KB). Filled
// from the host constexpr kSobolMatrices32 by setWavefrontSamplerMode(true)
// (only when the progressive sampler is enabled); the byte-identical PCG32
// default never touches it. Read by SobolDirect() in the shade + init kernels.
__constant__ uint32_t c_sobolMatrices[kSobolNumDims][kSobolMatrixSize];

// pkg131 — zero-knob adaptive sampling binding, published once per round by
// cuda_wavefront_render (setWavefrontAdaptiveBinding). enabled=0 (the default)
// leaves stageRegenKernel on the byte-identical flat-pool mapping.
__constant__ GWavefrontAdaptiveBinding c_wfAdaptive = { nullptr, nullptr, nullptr, 0, 0, 0 };

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

// Device twin of the CPU Material::isGlossy() (raytracer.h:455) — base Material is
// false; Metal (plugins/materials/metal.cpp) and Principled/Disney
// (plugins/materials/principled.cpp) override to true. Used to split the
// reflection-lobe category for a non-delta, non-transmitted first bounce (diffuse
// vs glossy). CRITICAL: scene_upload.cu lowers EVERY material that produces a valid
// closure graph to GMAT_CLOSURE_GRAPH (line 112) — so a Metal is uploaded as a
// GCLOSURE_GGX_CONDUCTOR closure and a Principled as GCLOSURE_PRINCIPLED, NOT as
// GMAT_METAL/GMAT_DISNEY. Checking only those two types misses the metal (its
// glossy indirect leaks into diffuse_indirect — the pkg198-s2 parity failure). So
// also scan the closure graph: a conductor or principled closure ⇒ glossy; a
// diffuse/dielectric-transmission/thin-glass closure ⇒ not glossy (matching the CPU
// Lambertian/Dielectric isGlossy()==false). Behind `if constexpr(HasLightPassAOVs)`
// at the one call site, so the fleet <…,false> shade kernel never compiles it.
__device__ __forceinline__ bool gpu_material_is_glossy(const ::GMaterial& m) {
    if (m.type == GMAT_METAL || m.type == GMAT_DISNEY) return true;
    if (m.type == GMAT_CLOSURE_GRAPH) {
        for (int i = 0; i < (int)m.closureCount; ++i) {
            GClosureType t = m.closures[i].type;
            if (t == GCLOSURE_GGX_CONDUCTOR || t == GCLOSURE_PRINCIPLED) return true;
        }
    }
    return false;
}

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

// pkg199 Stage 2 — Henyey-Greenstein phase function (HG 1941; PBRT-v3 PhaseHG,
// src/core/medium.cpp, BSD). cosTheta = dot(wo, wi), wo pointing back along the
// incoming ray. Normalised over the sphere (integrates to 1); Inv4Pi = 1/(4π).
// Device twin of Renderer::phaseHG — same sign convention for CPU↔GPU parity.
__device__ inline float gpu_phaseHG(float cosTheta, float g)
{
    float denom = 1.f + g * g + 2.f * g * cosTheta;
    denom = fmaxf(denom, 1e-6f);
    return (0.25f / M_PI_F) * (1.f - g * g) / (denom * sqrtf(denom));
}

// pkg199 Stage 2 — importance-sample the HG phase function (PBRT-v3
// HenyeyGreenstein::Sample_p, BSD). `wo` points back along the incoming ray
// (= -ray.direction). Returns the sampled continuation direction; outPdf is the
// phase value (HG is perfectly importance-sampled, pdf == value → throughput
// factor value/pdf = 1). g>0 forward-scatters (peak at wi = -wo). Device twin of
// Renderer::sampleHG; gpu_buildONB gives the orthonormal frame (z-axis = wo).
__device__ inline GVec3 gpu_sampleHG(const GVec3& wo, float g, float u1, float u2,
                                     float& outPdf)
{
    float cosTheta;
    if (fabsf(g) < 1e-3f) {
        cosTheta = 1.f - 2.f * u1;
    } else {
        float sqrTerm = (1.f - g * g) / (1.f + g - 2.f * g * u1);
        cosTheta = -(1.f + g * g - sqrTerm * sqrTerm) / (2.f * g);
    }
    cosTheta = fmaxf(-1.f, fminf(1.f, cosTheta));
    float sinTheta = sqrtf(fmaxf(0.f, 1.f - cosTheta * cosTheta));
    float phi = 2.f * M_PI_F * u2;
    GVec3 v1, v2;
    gpu_buildONB(wo, v1, v2);
    GVec3 wi = v1 * (sinTheta * cosf(phi)) + v2 * (sinTheta * sinf(phi)) + wo * cosTheta;
    outPdf = gpu_phaseHG(cosTheta, g);
    return wi.normalized();
}

// pkg199 Stage 2 — dimension-salt base for the free-flight sampler. Far above any
// dimension the shade/volume WavefrontRNG stream reaches (0..~depth·draws), so the
// free-flight draws are decorrelated from all shading draws by construction.
static constexpr uint32_t G_WF_VOL_DIM_SALT = 0xF0000000u;

// pkg199 Stage 2 — OBJECT-FREE counter-based free-flight uniform. Reuses the exact
// published keying of WavefrontRNG::GenerateForDimension (PBRT-v4 MixBits =
// MurmurHash3 finalizer, src/pbrt/util/hash.h; -> PCG32 SetSequence -> PCG32 XSH-RR
// output, imneme/pcg-c-basic Apache-2.0) — a counter-based RNG in the Salmon et al.
// 2011 ("Parallel Random Numbers", Random123) sense — but computed inline so
// intersectPathSlot holds NO persistent WavefrontRNG object and does NO
// rng_dimension SoA round-trip (Option 3: keeps the intersect decision block
// register-light so the kernel stays <=128 regs / 2 blocks/SM at 256 threads). Keyed
// on (pixel, sample, seed, dimSalt); the salt varies per bounce and per draw so
// every free-flight event is independent, and is disjoint from the shade stream.
// CPU<->GPU free-flight streams are INDEPENDENT (parity gate is per-channel
// mean-ratio, not sample-matched). See the research note.
__device__ inline float gpu_freeflightUniform(uint32_t pixel, uint32_t sample,
                                              uint64_t seed, uint32_t dimSalt)
{
    uint64_t seq_index = (static_cast<uint64_t>(pixel) * 65536ULL + sample) << 32 | dimSalt;
    uint64_t stream = astroray::MixBits(seq_index);
    uint64_t inc   = (stream << 1) | 1;
    uint64_t state = 0;
    state = state * 6364136223846793005ULL + inc;   // PCG32 SetSequence, advance 1
    state += seed;
    state = state * 6364136223846793005ULL + inc;   // advance 2
    uint32_t xorshifted = static_cast<uint32_t>(((state >> 18u) ^ state) >> 27u);
    uint32_t rot        = static_cast<uint32_t>(state >> 59u);
    int32_t  rot_signed = static_cast<int32_t>(rot);
    uint32_t u = (xorshifted >> rot) | (xorshifted << ((-rot_signed) & 31));
    constexpr float kOneMinusEpsilon = 0x1.fffffep-1f;
    return fminf(u * 0x1p-32f, kOneMinusEpsilon);
}

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
template<bool HasWorldScatter, bool HasLightPassAOVs = false>  // pkg199 scatter; pkg198 S2 pass axis
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
    GLightTreeView    lightTree)
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
    bool hit = gpu_tlas_hit(tlas, instances, blas, bvhNodes, prims, tris, spheres,
                            ray, 0.001f, 1e30f, rec, motionVerts);

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
    const bool mediumScatters = HasWorldScatter &&
                                c_worldVolume.hasVolume &&
                                c_worldVolume.density > 0.f &&
                                c_worldVolume.scatter > 0.f;
    if constexpr (HasWorldScatter) if (mediumScatters) {
        float surfaceT = hit ? rec.t : 1e30f;
        float termT = surfaceT;
        if (bounce > 0 && numDed > 0) {
            float lampT, lampScale;
            int lampIdx = gpu_dedicated_intersect_closest(
                dedLights, numDed, ray.origin, ray.direction, 0.001f, surfaceT,
                &lampT, &lampScale);
            if (lampIdx >= 0) termT = lampT;
        }
        // Object-free counter-based free-flight draws (Option 3): no WavefrontRNG
        // object held, no rng_dimension round-trip — keeps this kernel register-
        // light. Salt varies per bounce (·2) and per draw (+0/+1), disjoint from the
        // shade stream; shade/volume read the UNTOUCHED rng_dimension (as Stage-1).
        uint32_t rpix = state.rng_pixel[idx];
        uint32_t rsmp = state.rng_sample[idx];
        uint64_t rsd  = state.rng_seed[idx];
        uint32_t salt = G_WF_VOL_DIM_SALT + (uint32_t)bounce * 2u;
        GSampledSpectrum sigmaT = gpu_worldSigmaT(lambdas);
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
            state.throughput_0[idx] = throughput.v[0];
            state.throughput_1[idx] = throughput.v[1];
            state.throughput_2[idx] = throughput.v[2];
            state.throughput_3[idx] = throughput.v[3];
            return -2;  // scattered → the wrapper enqueues to the volume queue
        } else {
            // Reached the terminating event (surface / lamp / env): throughput *=
            // Tr(termT)/pdf, pdf = avg(Tr). Replaces the Stage-1 role-1 multiply
            // (gated off below); the role-3 lamp Tr is likewise gated off since
            // this Tr already covers the camera→lamp segment.
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
            // fall through to lamp-MIS / env / role-1(gated) / emission.
        }
    }

    // pkg181: dedicated-light visibility to BSDF rays (Cycles lights_intersect
    // parity) — device twin of production pathTraceSpectral. Lamps are invisible
    // to camera rays (bounce == 0); a lamp closer than the surface terminates the
    // path. Placed in the INTERSECT stage (this kernel), NOT the REG:254-saturated
    // shade stage (memory wavefront-shade-kernels-register-saturated). The
    // snapshot capture moment is unaffected: this kernel writes no PostIntersect
    // snapshot; the lamp hit terminates before the hit-record is parked. Emission
    // + MIS mirror the emissive-Hittable block below (wB = 1 after specular; the
    // power heuristic otherwise; naive mode = enableNEE false takes specular only).
    if (bounce > 0 && numDed > 0) {
        float surfaceT = hit ? rec.t : 1e30f;
        float lampT, lampScale;
        int lampIdx = gpu_dedicated_intersect_closest(
            dedLights, numDed, ray.origin, ray.direction, 0.001f, surfaceT,
            &lampT, &lampScale);
        if (lampIdx >= 0) {
            // pkg218: a directly-visible dedicated light (area/distant disc hit
            // by a BSDF-continuation ray) reads the baked device SPD for non-RGB
            // emission modes, same substitution as the NEE paths above/below
            // (gpu_nee.cuh gpu_nee_resolve, stageShadowKernel). This is the
            // INTERSECT stage per the pkg181 comment above (not the REG:254
            // shade kernel), so the extra branch is not register-critical.
            int profIdx = dedLights[lampIdx].emissionProfileIndex;
            GSampledSpectrum Le;
            if (profIdx >= 0) {
                for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                    Le.v[i] = gpu_emission_profile(profIdx, lambdas.lambda[i]) * lampScale;
            } else {
                for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                    Le.v[i] = gpu_rgbSpectrumAt(dedLights[lampIdx].emissionRGB,
                                                lambdas.lambda[i], GSPEC_RGB_ILLUMINANT)
                              * lampScale;
            }
            if (Le.maxValue() > 0.f) {
                // pkg199 Stage 1 (role 3): the lamp is closer than the surface,
                // so throughput is not yet segment-attenuated; attenuate the
                // lamp emission over the camera→lamp segment (lampT). Mirrors the
                // CPU dedicated-lamp block (throughput·lampEmission·Tr(lh.t)).
                // pkg199 Stage 2: in scatter mode the free-flight estimator already
                // applied Tr(termT=lampT)/pdf to throughput, so do NOT re-attenuate.
                if (c_worldVolume.hasVolume && !mediumScatters)
                    Le *= gpu_worldTransmittanceMW(lampT, lambdas);
                GSampledSpectrum contrib(0.f);
                if (bounce == 0 || wasSpecular) {
                    contrib = throughput * Le;                 // w_B = 1
                } else if (enableNEE) {
                    float lp = gpu_dedicated_reconstruct_pdf(
                        dedLights, numDed, totalLightPower, ray.origin, ray.direction);
                    float wB = gpu_mw_powerHeuristic(state.path_bsdf_pdf[idx], lp);
                    contrib = throughput * Le * wB;
                }
                // naive mode (enableNEE == false, non-specular): no NEE leg to
                // complement, so nothing is added — mirrors the emissive block.
                GSampledSpectrum lampContrib = gpu_clampContribMW(
                    contrib, lambdas, bounce,
                    clampDirect, clampIndirect, useLuminanceOutput);
                color += lampContrib;
                // pkg198 Stage 2: a lamp hit by a continuation ray is indirect light
                // (bounce > 0), folded into firstCat's INDIRECT pass (CPU lampPass =
                // (firstCat<0?0:firstCat)*3+1).
                if constexpr (HasLightPassAOVs) {
                    unsigned char cat = c_wfLpBinding.firstCat[idx];
                    int lampPass = (cat == G_LP_CAT_UNSET ? 0 : (int)cat) * 3 + 1;
                    lpAccumulate(idx, lampPass, lampContrib);
                }
            }
            state.color_0[idx] = color.v[0];
            state.color_1[idx] = color.v[1];
            state.color_2[idx] = color.v[2];
            state.color_3[idx] = color.v[3];
            state.path_alive[idx] = 0;
            return -1;   // path terminates on the lamp
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
            // pkg157: clamp by bounce depth (Cycles film_clamp_light split);
            // see gpu_clampContribMW (gpu_spectral_tables.h).
            GSampledSpectrum envContrib = gpu_clampContribMW(
                throughput * envSpec, lambdas, bounce,
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

    const ::GMaterial& mat = materials[rec.materialId];

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
        if (bounce == 0 || wasSpecular) {
            // pkg157: emissive-hit direct term, same clamp split as above.
            // Camera / post-specular ray: no NEE leg competes (w_B = 1).
            GSampledSpectrum emitContrib = gpu_clampContribMW(
                throughput * Le, lambdas, bounce,
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
            float lp = gpu_reconstruct_light_pdf(
                rec, ray.origin, ray.direction,
                lights, numLights, totalLightPower,
                prims, tris, spheres, lightTree);
            float wB = gpu_mw_powerHeuristic(bsdfPdfPrev, lp);
            GSampledSpectrum contrib = throughput * Le;
            contrib *= wB;
            GSampledSpectrum emitContrib = gpu_clampContribMW(
                contrib, lambdas, bounce,
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
    return (int)mat.type;
}

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
__constant__ GWavefrontTextureBinding c_wfTexBinding;

// pkg219b — op-VM program binding in constant memory (see GWavefrontProgramBinding
// in astroray/shader_vm.h). Set once per frame by setWavefrontProgramBinding; read
// only inside `if constexpr (HasProgram)`. The <false> fleet kernel never reads it.
__constant__ GWavefrontProgramBinding c_wfProgBinding;

// pkg219d — scalar BSDF-parameter op-VM override storage. Only the
// <HasProgram=true> shade specialization instantiates a full GMaterial copy to
// hold the per-hit-substituted roughness/metallic/transmission/ior;
// GScalarOverride<false> is an EMPTY struct (zero stack), so the fleet
// <HasProgram=false> shade kernel allocates nothing and stays byte-identical.
template<bool> struct GScalarOverride {};
template<> struct GScalarOverride<true> { ::GMaterial mat; };

// pkg219d — fetch a scalar program's OWN source texel at the hit UV. Mirrors the
// base-colour triangle-UV recompute (Ericson §3.4) + Mapping in shadePathSlot's
// HasTexture block, but for the scalar program's own image (matScalarTexId, a
// DIFFERENT image than the base colour). Returns false for non-triangle / UV-less
// hits (the override is then skipped, exactly like the base-colour path). Reads
// c_wfTexBinding (published this frame); only ever called from <HasProgram=true>.
__device__ __forceinline__ bool gpu_scalarProgSourceTexel(
    const GHitRecord& rec, const GPrimitive* prims, const GTriangle* tris,
    int texId, GVec3& outTexel)
{
    if (!(rec.primId >= 0 && prims[rec.primId].type == GPRIM_TRIANGLE)) return false;
    const GTriangle& ttri = tris[prims[rec.primId].index];
    if (!ttri.hasUV) return false;
    GVec3 e1 = ttri.v1 - ttri.v0, e2 = ttri.v2 - ttri.v0;
    GVec3 ep = rec.point - ttri.v0;
    float d00 = e1.dot(e1), d01 = e1.dot(e2), d11 = e2.dot(e2);
    float d20 = ep.dot(e1), d21 = ep.dot(e2);
    float denom = d00 * d11 - d01 * d01;
    if (fabsf(denom) <= 1e-20f) return false;
    float b1 = (d11 * d20 - d01 * d21) / denom;
    float b2 = (d00 * d21 - d01 * d20) / denom;
    float b0 = 1.0f - b1 - b2;
    float uu = b0*ttri.uv0.x + b1*ttri.uv1.x + b2*ttri.uv2.x;
    float vv = b0*ttri.uv0.y + b1*ttri.uv1.y + b2*ttri.uv2.y;
    const GImageTexture& tdesc = c_wfTexBinding.textures[texId];
    if (tdesc.hasMapping) {
        const float* m = tdesc.mapping;
        float mu = m[0]*uu + m[1]*vv + m[3];
        float mv = m[4]*uu + m[5]*vv + m[7];
        uu = mu; vv = mv;
    }
    outTexel = gpu_sampleImageTexture(tdesc, c_wfTexBinding.texelBuf, uu, vv);
    return true;
}

// pkg219d — apply one op-VM scalar result to the LOCAL GMaterial copy. Overwrites
// EVERY representation the closure dispatch may read: the top-level field (plain
// lambertian/metal + the GCLOSURE_DIFFUSE path, which reads parent.roughness), the
// native-Principled block (gpu_principled_* fast path), and every closure lobe
// (gpu_closure_as_material reads closure.{roughness,metallic,ior,transmission}).
// Clamps MUST match the CPU DisneyPlugin::substituted() and its constructor.
// NOTE: closure WEIGHTS were baked at upload from the ORIGINAL metallic/transmission,
// so metallic/transmission programs shift the per-lobe fields but not the diffuse/
// specular/transmission MIX on GPU — exact CPU↔GPU parity holds for roughness and
// ior (which never change lobe selection); metallic/transmission are a documented
// closure-graph approximation (same class as other GPU closure-graph cuts).
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
template<bool Deferred, bool HasPrincipled, bool HasTexture = false, bool HasPhotons = false,
         bool HasDispersion = false, bool HasLightPassAOVs = false,  // pkg198 S2 pass axis
         bool HasProgram = false,   // pkg219b — per-texel op-VM axis
         bool HasNormalPerturb = false>  // pkg223 — tangent-space normal-map axis
__device__ bool shadePathSlot(
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
    // uploaded active-layer UVs when present (scene_upload sets hasUV only on
    // anisotropic-Principled triangles). Behind `if constexpr (HasPrincipled)` so
    // the non-principled <false> shade kernel compiles this out entirely, and
    // behind the per-triangle `hasUV` runtime gate so non-aniso principled scenes
    // pay nothing. Computed here (not the intersect stage) to avoid a per-path
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
            if (utri.hasUV) {
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
            if (ntri.hasUV) {
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
            if (btri.hasUV) {
                GVec3 bT; float bSign;
                if (gpu_pr_uvAlignedTangent(btri.v0, btri.v1, btri.v2,
                                            btri.uv0, btri.uv1, btri.uv2,
                                            rec.normal, bT, bSign)) {
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
                        GVec3 dPdx = bT * eps, dPdy = Bt * eps;
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
        if (c_wfProgBinding.matScalarProgId && c_wfProgBinding.matScalarTexId) {
            const int base = rec.materialId * astroray::svm::VM_SCALAR_SLOTS;
            bool anyOverride = false;
            for (int slot = 0; slot < astroray::svm::VM_SCALAR_SLOTS; ++slot) {
                int sProg = c_wfProgBinding.matScalarProgId[base + slot];
                int sTex  = c_wfProgBinding.matScalarTexId[base + slot];
                if (sProg < 0 || sTex < 0) continue;
                GVec3 srcTexel;
                if (!gpu_scalarProgSourceTexel(rec, prims, tris, sTex, srcTexel))
                    continue;  // non-triangle / UV-less hit → skip (mirrors base colour)
                GVec3 vmIn[astroray::svm::VM_MAX_TEX];
                for (int t = 0; t < astroray::svm::VM_MAX_TEX; ++t) vmIn[t] = srcTexel;
                float v = astroray::svm::svm_eval(
                    c_wfProgBinding.programs[sProg], vmIn).x;
                if (!anyOverride) {
                    matScalarOv.mat = materials[rec.materialId];
                    anyOverride = true;
                }
                gpu_applyScalarOverride(matScalarOv.mat, slot, v);
            }
            if (anyOverride) matPtr = &matScalarOv.mat;
        }
    }
    const ::GMaterial& mat = *matPtr;

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
        if (texId >= 0) {
            const GImageTexture& tdesc = c_wfTexBinding.textures[texId];
            GVec3 texColor;
            bool  haveTex = false;
            if (tdesc.depth > 1) {
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
                GVec3 g;
                g.x = tdesc.genSize.x > 1e-6f
                    ? (rec.point.x - tdesc.genMin.x) / tdesc.genSize.x : 0.0f;
                g.y = tdesc.genSize.y > 1e-6f
                    ? (rec.point.y - tdesc.genMin.y) / tdesc.genSize.y : 0.0f;
                g.z = tdesc.genSize.z > 1e-6f
                    ? (rec.point.z - tdesc.genMin.z) / tdesc.genSize.z : 0.0f;
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
                        for (int t = 1; t < astroray::svm::VM_MAX_TEX; ++t) vmIn[t] = texColor;
                        texColor = astroray::svm::svm_eval(
                            c_wfProgBinding.programs[progId], vmIn);
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
                        nee_i[ 1 * nee_capacity + idx] = s.isSphere;
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
            if (mat.emissionIntensity <= 0.0f) {
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

// ---------------------------------------------------------------------------
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
    float             clampDirect, float clampIndirect)  // pkg157
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
    s.isSphere   = nee_i[1 * nee_capacity + idx];
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
    GNEEOcclusion occ = gpu_nee_occlude(
        s, tlas, instances, blas, bvhNodes, prims, tris, spheres,
        time, motionVerts);
    if (occ.occluded) return;

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
            for (int k = 0; k < G_SPECTRUM_SAMPLES; ++k)
                L_spec[k] = gpu_rgbSpectrumAt(s.dedEmissionRGB, lambdas.lambda[k],
                                              GSPEC_RGB_ILLUMINANT);
        }
    } else {
        bool lightFront = s.isSphere ? (occ.frontFace != 0) : true;
        L_spec = gpu_material_emitted_spectral(
            materials[s.lightMatId], lightFront, lambdas);
    }
    if (L_spec.maxValue() <= 0.f) return;

    GSampledSpectrum contrib;
    contrib.v[0] = nee_f[ 7 * nee_capacity + idx] * L_spec.v[0];
    contrib.v[1] = nee_f[ 8 * nee_capacity + idx] * L_spec.v[1];
    contrib.v[2] = nee_f[ 9 * nee_capacity + idx] * L_spec.v[2];
    contrib.v[3] = nee_f[10 * nee_capacity + idx] * L_spec.v[3];
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
        if (fc == 3) {
            // pkg204: volume in-scatter direct/indirect split (closes the pkg198
            // Stage-2 limitation). The volume-scatter kernel parked int lane 4 =
            // +(bounce+1) for a first-interaction in-scatter NEE (CPU
            // firstInteraction => PASS_VOLUME_DIRECT) and -(bounce+1) for a deeper
            // scatter. Route DIRECT only when positive AND its bounce matches this
            // NEE's own parked bounce (lane 3) -- a surface-after-fog NEE (firstCat
            // locked to 3, lane 4 stale from an EARLIER scatter's bounce a<b) fails
            // the match and correctly stays PASS_VOLUME_INDIRECT. Sum-to-beauty is
            // preserved bit-for-bit: the split only re-buckets the same quantity.
            int volEnc = nee_i[4 * nee_capacity + idx];
            bool volDirect = (volEnc > 0) && (volEnc - 1 == bounce);
            passIdx = volDirect ? (3 * 3 + 0)    // PASS_VOLUME_DIRECT (9)
                                : (3 * 3 + 1);   // PASS_VOLUME_INDIRECT (10)
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
template<bool HasWorldScatter, bool HasLightPassAOVs = false>   // pkg199 scatter; pkg198 S2 pass axis
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
    int* vol_queue, int* vol_count)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= *count_in) return;
    int idx = queue_in[i];
    // N+7 part 4: dead-slot guard. Part-3 flat queues are guaranteed-alive
    // (no-op there); the regeneration driver iterates a dense identity
    // queue where exhausted slots stay dead.
    if (state.path_alive[idx] == 0) return;
    int matType = intersectPathSlotT<HasWorldScatter, HasLightPassAOVs>(
                                    idx, state, hitBufs, tlas, instances, blas,
                                    bvhNodes, prims, tris, spheres, motionVerts,
                                    materials, envMap, backgroundColor,
                                    hasBackgroundColor, worldMaxBounces,
                                    useLuminanceOutput, enableNEE,
                                    clampDirect, clampIndirect,
                                    lights, numLights, totalLightPower,
                                    dedLights, numDed, lightTree);  // pkg120+pkg181
    if (matType == -2) {   // pkg199 Stage 2: scattered → volume-scatter queue
        int vslot = atomicAdd(vol_count, 1);
        vol_queue[vslot] = idx;
        return;
    }
    if (matType < 0) return;
    if (matType >= G_WF_NUM_MAT_TYPES) matType = G_WF_NUM_MAT_TYPES - 1;
    int slot = atomicAdd(&shade_counts[matType], 1);
    shade_queues[matType * capacity + slot] = idx;
}

template<bool HasPrincipled, bool HasTexture, bool HasPhotons, bool HasDispersion,
         bool HasLightPassAOVs = false,  // pkg178 D4; pkg186 texture; pkg184 photons; pkg189 dispersion; pkg198 S2 pass axis
         bool HasProgram = false,   // pkg219b — per-texel op-VM axis
         bool HasNormalPerturb = false>  // pkg223 — tangent-space normal-map axis
__global__ void stageShadeBucketedKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
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
    bool has_light_pass_aovs)             // pkg198 Stage 2: picks the pass-AOV axis
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
        d_vol_queue, d_vol_count
    {
        // pkg198 Stage 2: the second axis picks the pass-AOV specialization. The
        // fleet (no scatter, no passes) launches <false,false> — REG 127, byte-
        // identical Stage-1. All four instantiations are referenced so they land in
        // the cubin for the cuobjdump register report (intersect<false,false> must
        // stay 127/616).
        const int sel = (has_world_scatter ? 2 : 0) | (has_light_pass_aovs ? 1 : 0);
        const void* kptr =
            sel == 3 ? (const void*)stageIntersectQueuedKernel<true, true>  :
            sel == 2 ? (const void*)stageIntersectQueuedKernel<true, false> :
            sel == 1 ? (const void*)stageIntersectQueuedKernel<false, true> :
                       (const void*)stageIntersectQueuedKernel<false, false>;
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_intersect_queued_n7", kptr, blocks, threads);
        switch (sel) {
            case 3: stageIntersectQueuedKernel<true, true> <<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break;
            case 2: stageIntersectQueuedKernel<true, false><<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break;
            case 1: stageIntersectQueuedKernel<false, true> <<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break;
            default:stageIntersectQueuedKernel<false, false><<<blocks, threads>>>(ASTRORAY_PKG199_INTERSECT_ARGS); break;
        }
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
// (slots intersectPathSlot routed via its -2 return), performs the phase-sampled
// NEE-through-medium (parked into the SAME nee_f/nee_i lanes + shadow queue the
// surface NEE uses, so stageShadowKernel resolves it unchanged — geomDist role-2
// Tr + clamp), and emits the HG phase-sampled continuation ray from the scatter
// point, requeuing the survivor for the next bounce. The REG-254 shade kernel is
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
    // pkg204: capture whether THIS scatter is the first interaction (CPU
    // `firstInteraction = firstCat < 0`) BEFORE the lock, so the deferred medium
    // NEE below can be attributed to PASS_VOLUME_DIRECT vs PASS_VOLUME_INDIRECT.
    bool lpVolumeFirst = false;
    if (c_wfLpBinding.passAccum != nullptr) {
        lpVolumeFirst = (c_wfLpBinding.firstCat[idx] == G_LP_CAT_UNSET);
        if (lpVolumeFirst) c_wfLpBinding.firstCat[idx] = 3;
    }

    // Reconstruct: ray_origin == scatter point P (intersect wrote it), and
    // ray_direction == incoming direction (woMedium = -direction), per the pinned
    // snapshot semantics. throughput already carries Tr·σ_s/pdf (applied in intersect).
    GVec3 P     = GVec3(state.ray_origin_x[idx], state.ray_origin_y[idx],
                        state.ray_origin_z[idx]);
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

    // ---- Medium NEE (phase / light MIS), parked for the shadow stage ----
    // Mirrors the surface NEE park (stage_advance shade lines): the "f" is the HG
    // phase value; scale = wt/lightPdf with the MIS between lightPdf and the phase
    // pdf (== phase value). The shadow kernel multiplies lanes 7-10 by L_spec and
    // applies Tr(geomDist) + clamp, so parked lanes stay UNCLAMPED like surface NEE.
    if (enableNEE && (numLights + numDed) > 0 && totalLightPower > 0.f) {
        GHitRecord mrec{};
        mrec.point   = P;
        mrec.normal  = woMedium;   // arbitrary; only the (disabled) light-tree path reads it
        mrec.isDelta = false;
        GNEESample s = gpu_nee_sample(mrec, prims, tris, spheres,
                                      lights, numLights, totalLightPower,
                                      dedLights, numDed, lightTree, &rng);
        if (s.valid) {
            float ph = gpu_phaseHG(woMedium.dot(s.wi), g);   // phase value == pdf
            if (ph > 0.f) {
                float a2 = s.lightPdf * s.lightPdf;
                float b2 = ph * ph;
                float wt = s.isDeltaLight ? 1.f : a2 / (a2 + b2 + 1e-8f);
                float scale = s.lightPdf > 1e-8f ? wt / s.lightPdf : 0.f;
                if (s.isDedicated) scale *= s.dedGeoScale;
                nee_f[ 0 * nee_capacity + idx] = s.origin.x;
                nee_f[ 1 * nee_capacity + idx] = s.origin.y;
                nee_f[ 2 * nee_capacity + idx] = s.origin.z;
                nee_f[ 3 * nee_capacity + idx] = s.wi.x;
                nee_f[ 4 * nee_capacity + idx] = s.wi.y;
                nee_f[ 5 * nee_capacity + idx] = s.wi.z;
                nee_f[ 6 * nee_capacity + idx] = s.maxDist;
                nee_f[ 7 * nee_capacity + idx] = throughput.v[0] * ph * scale;
                nee_f[ 8 * nee_capacity + idx] = throughput.v[1] * ph * scale;
                nee_f[ 9 * nee_capacity + idx] = throughput.v[2] * ph * scale;
                nee_f[10 * nee_capacity + idx] = throughput.v[3] * ph * scale;
                nee_f[11 * nee_capacity + idx] = s.dedEmissionRGB.x;
                nee_f[12 * nee_capacity + idx] = s.dedEmissionRGB.y;
                nee_f[13 * nee_capacity + idx] = s.dedEmissionRGB.z;
                nee_f[14 * nee_capacity + idx] = s.geomDist;
                nee_i[ 0 * nee_capacity + idx] = s.lightMatId;
                nee_i[ 1 * nee_capacity + idx] = s.isSphere;
                nee_i[ 2 * nee_capacity + idx] = s.isDedicated;
                nee_i[ 3 * nee_capacity + idx] = bounce;
                nee_i[ 5 * nee_capacity + idx] = s.dedEmissionProfileIndex;  // pkg218
                // pkg204: volume direct/indirect encoding (see G_WF_NEE_I_LANES).
                // +(bounce+1) for a first-interaction in-scatter (=> VOLUME_DIRECT),
                // -(bounce+1) for a deeper scatter (=> VOLUME_INDIRECT). The shadow
                // kernel bounce-matches this against lane 3 so a later surface-after-
                // fog NEE (stale lane 4 from an earlier bounce) can't false-DIRECT.
                nee_i[ 4 * nee_capacity + idx] =
                    lpVolumeFirst ? (bounce + 1) : -(bounce + 1);
                int qslot = atomicAdd(shadow_count, 1);
                shadow_queue[qslot] = idx;
            }
        }
    }

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
    int threads = 256;
    int blocks  = (int)((total + threads - 1) / threads);
    {
        // pkg178 Stage-3b D4: select the HasPrincipled specialization off the
        // host scene flag. The <false,*> instantiation carries zero
        // gpu_principled_* codegen (restores main's ~4456 B stage-shade
        // footprint); the <true,*> instantiation is byte-identical to today's
        // principled kernel. pkg186 adds the orthogonal HasTexture axis: the
        // <*,false> instantiation carries ZERO texture codegen (the fleet's
        // untextured scenes), so stageShadeBucketedKernel<false,false> must stay
        // register/stack-identical to the pre-pkg186 <false> kernel — the
        // acceptance check is a cuobjdump on that symbol (native sm_120). All four
        // are referenced below so they appear in the cubin for the register report.
        // pkg186: the texture arrays are NOT in this arg list — they live in the
        // __constant__ c_wfTexBinding symbol (setWavefrontTextureBinding, once per
        // frame), which is what keeps the untextured <false,false> signature at its
        // pre-pkg186 REG/STACK footprint (signature params cost +24 B stack).
        #define ASTRORAY_PKG186_SHADE_ARGS \
                state, hitBufs, d_shade_queues, d_shade_counts, capacity, \
                d_queue_out, d_count_out, \
                d_nee_f, d_nee_i, d_shadow_queue, d_shadow_count, \
                d_tlas, d_instances, d_blas, \
                d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials, \
                d_lights, num_lights, total_light_power, \
                d_dedLights, num_ded, lightTree, max_depth, \
                useLuminanceOutput, enableNEE, \
                clampDirect, clampIndirect, \
                photonGrid, hasPhotonGrid, photonScale, \
                d_cryptoObjectRanks, d_cryptoMaterialRanks, cryptoDepth
        // pkg184: hasPhotonGrid selects the <*,*,true> instantiation, which is the
        // ONLY one carrying the photonGridGatherKnn codegen. The fleet's non-photon
        // scenes launch <*,*,false>, whose ptxas footprint drops back below the
        // pre-pkg184 kernel (acceptance = cuobjdump on the <false,false,false>
        // symbol, native sm_120). All 8 are referenced so they land in the cubin.
        // pkg189: hasDispersion adds a 4th orthogonal axis. It selects the ONLY
        // instantiations carrying the hero-λ collapse SoA write-back; the fleet's
        // non-dispersive scenes launch <*,*,*,false>, byte-identical to the
        // pre-pkg189 <*,*,*> kernels (acceptance = cuobjdump on the
        // <false,false,false,false> symbol vs a same-pipeline main baseline). The
        // 4-bit selector picks one of the 16 instantiations; all 16 are referenced
        // so they land in the cubin for the register report.
        const bool hasPhotons = hasPhotonGrid;
        const int sel = (hasPrincipled ? 8 : 0) | (hasTexture ? 4 : 0)
                      | (hasPhotons ? 2 : 0) | (hasDispersion ? 1 : 0);
        // pkg198 Stage 2: the 5th axis (HasLightPassAOVs) is selected at RUNTIME
        // inside each case via `hasLightPassAOVs`, so the 16-way P/T/Ph/D switch
        // stays legible while both LP specializations of each combo land in the
        // cubin. The fleet path (hasLightPassAOVs==false) reaches the exact same
        // <…,false> instantiations as before → byte-identical 254/3352/1700.
        // pkg219b: the 6th axis (HasProgram) is selected at RUNTIME here too,
        // nested under HasLightPassAOVs, so the P/T/Ph/D switch stays legible and
        // all 4 (LP × Program) specializations of each combo land in the cubin.
        // The fleet path (hasProgram==false) reaches the same <…,false>
        // instantiations as before → byte-identical register/stack.
        // pkg223: the 7th axis (HasNormalPerturb) nests OUTSIDE the pkg198/pkg219b
        // LP×Program runtime selection. The false-NP branch reaches the EXACT same
        // <…,false> instantiations as before (explicit 7th `false` == the 6-arg
        // default) → the fleet stays byte-identical; only hasNormalPerturb scenes
        // take the <…,true> kernels carrying the normal-map codegen.
        #define ASTRORAY_PKG198_KPTR(P,T,Ph,D) \
            (hasNormalPerturb \
              ? (hasLightPassAOVs \
                   ? (hasProgram ? (const void*)stageShadeBucketedKernel<P,T,Ph,D,true ,true ,true > \
                                 : (const void*)stageShadeBucketedKernel<P,T,Ph,D,true ,false,true >) \
                   : (hasProgram ? (const void*)stageShadeBucketedKernel<P,T,Ph,D,false,true ,true > \
                                 : (const void*)stageShadeBucketedKernel<P,T,Ph,D,false,false,true >)) \
              : (hasLightPassAOVs \
                   ? (hasProgram ? (const void*)stageShadeBucketedKernel<P,T,Ph,D,true ,true ,false> \
                                 : (const void*)stageShadeBucketedKernel<P,T,Ph,D,true ,false,false>) \
                   : (hasProgram ? (const void*)stageShadeBucketedKernel<P,T,Ph,D,false,true ,false> \
                                 : (const void*)stageShadeBucketedKernel<P,T,Ph,D,false,false,false>)))
        const void* kptr = nullptr;
        switch (sel) {
            case  0: kptr = ASTRORAY_PKG198_KPTR(false,false,false,false); break;
            case  1: kptr = ASTRORAY_PKG198_KPTR(false,false,false,true ); break;
            case  2: kptr = ASTRORAY_PKG198_KPTR(false,false,true ,false); break;
            case  3: kptr = ASTRORAY_PKG198_KPTR(false,false,true ,true ); break;
            case  4: kptr = ASTRORAY_PKG198_KPTR(false,true ,false,false); break;
            case  5: kptr = ASTRORAY_PKG198_KPTR(false,true ,false,true ); break;
            case  6: kptr = ASTRORAY_PKG198_KPTR(false,true ,true ,false); break;
            case  7: kptr = ASTRORAY_PKG198_KPTR(false,true ,true ,true ); break;
            case  8: kptr = ASTRORAY_PKG198_KPTR(true ,false,false,false); break;
            case  9: kptr = ASTRORAY_PKG198_KPTR(true ,false,false,true ); break;
            case 10: kptr = ASTRORAY_PKG198_KPTR(true ,false,true ,false); break;
            case 11: kptr = ASTRORAY_PKG198_KPTR(true ,false,true ,true ); break;
            case 12: kptr = ASTRORAY_PKG198_KPTR(true ,true ,false,false); break;
            case 13: kptr = ASTRORAY_PKG198_KPTR(true ,true ,false,true ); break;
            case 14: kptr = ASTRORAY_PKG198_KPTR(true ,true ,true ,false); break;
            case 15: kptr = ASTRORAY_PKG198_KPTR(true ,true ,true ,true ); break;
        }
        #undef ASTRORAY_PKG198_KPTR
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_shade_bucketed_n7", kptr, blocks, threads);
        // pkg223: mirror the KPTR nesting — hasNormalPerturb selects the <…,true>
        // normal-map kernels; the else-branch is the pre-pkg223 fleet path.
        #define ASTRORAY_PKG223_LP_PROG(P,T,Ph,D,NP) \
                do { if (hasLightPassAOVs) { \
                    if (hasProgram) \
                        stageShadeBucketedKernel<P,T,Ph,D,true ,true ,NP><<<blocks, threads>>>(ASTRORAY_PKG186_SHADE_ARGS); \
                    else \
                        stageShadeBucketedKernel<P,T,Ph,D,true ,false,NP><<<blocks, threads>>>(ASTRORAY_PKG186_SHADE_ARGS); \
                } else { \
                    if (hasProgram) \
                        stageShadeBucketedKernel<P,T,Ph,D,false,true ,NP><<<blocks, threads>>>(ASTRORAY_PKG186_SHADE_ARGS); \
                    else \
                        stageShadeBucketedKernel<P,T,Ph,D,false,false,NP><<<blocks, threads>>>(ASTRORAY_PKG186_SHADE_ARGS); \
                } } while (0)
        #define ASTRORAY_PKG198_LAUNCH(P,T,Ph,D) \
                do { if (hasNormalPerturb) ASTRORAY_PKG223_LP_PROG(P,T,Ph,D,true ); \
                     else                  ASTRORAY_PKG223_LP_PROG(P,T,Ph,D,false); } while (0)
        switch (sel) {
            case  0: ASTRORAY_PKG198_LAUNCH(false,false,false,false); break;
            case  1: ASTRORAY_PKG198_LAUNCH(false,false,false,true ); break;
            case  2: ASTRORAY_PKG198_LAUNCH(false,false,true ,false); break;
            case  3: ASTRORAY_PKG198_LAUNCH(false,false,true ,true ); break;
            case  4: ASTRORAY_PKG198_LAUNCH(false,true ,false,false); break;
            case  5: ASTRORAY_PKG198_LAUNCH(false,true ,false,true ); break;
            case  6: ASTRORAY_PKG198_LAUNCH(false,true ,true ,false); break;
            case  7: ASTRORAY_PKG198_LAUNCH(false,true ,true ,true ); break;
            case  8: ASTRORAY_PKG198_LAUNCH(true ,false,false,false); break;
            case  9: ASTRORAY_PKG198_LAUNCH(true ,false,false,true ); break;
            case 10: ASTRORAY_PKG198_LAUNCH(true ,false,true ,false); break;
            case 11: ASTRORAY_PKG198_LAUNCH(true ,false,true ,true ); break;
            case 12: ASTRORAY_PKG198_LAUNCH(true ,true ,false,false); break;
            case 13: ASTRORAY_PKG198_LAUNCH(true ,true ,false,true ); break;
            case 14: ASTRORAY_PKG198_LAUNCH(true ,true ,true ,false); break;
            case 15: ASTRORAY_PKG198_LAUNCH(true ,true ,true ,true ); break;
        }
        #undef ASTRORAY_PKG198_LAUNCH
        #undef ASTRORAY_PKG223_LP_PROG
        #undef ASTRORAY_PKG186_SHADE_ARGS
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
        // as the even-sample sum). Beauty luminance only (photon-caustic energy is
        // added to accum below but not here → conservative convergence in those
        // rare scenes). Zeroing color_* below is the double-add guard, shared.
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
        pixel  = w % numPixels;
        sample = w / numPixels;
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
    float             clampDirect, float clampIndirect)  // pkg157
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
            d_tlas, d_instances, d_blas,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_motionVerts, d_materials,
            useLuminanceOutput, clampDirect, clampIndirect);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_shadow launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
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

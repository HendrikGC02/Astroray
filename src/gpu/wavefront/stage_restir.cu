// stage_restir.cu — pkg55-C6: ReSTIR reservoir SoA + reuse stages on GPU wavefront
//
// Implements ReSTIR-DI on the GPU wavefront following the plan §5:
//   1. Initial RIS stage — draw numCandidates light samples, reservoir update
//   2. Temporal reuse stage — merge previous frame's reservoir (validity-gated)
//   3. Spatial reuse stage — merge spatial neighbours from previous frame
//   4. Resolve stage — finalize weight, shadow ray, accumulate contribution
//
// References:
//   - Bitterli et al. 2020 (ReSTIR DI), DOI 10.1145/3386569.3392481
//   - DQLin/ReSTIR_PT (BSD-3-Clause, NVIDIA), reservoir/reuse structure
//   - pkg55 Phase C plan §5 (one-generator rule, double-buffered SoA layout)
//   - CPU reference: plugins/integrators/restir_di.cpp (mirrored)
//
// pkg55-C6a scope (this session): Initial RIS + resolve (temporal/spatial in C6b).

#include "astroray/gpu_wavefront_state.h"
#include "astroray/gpu_types.h"
#include "astroray/restir/reservoir.h"
#include "astroray/restir/light_sample.h"
#include <cuda_runtime.h>
#include <curand_kernel.h>

// Device-side WavefrontRNG uniform draw (ADL dispatch for the templated
// Reservoir). The CPU side has rng_uniform(std::mt19937&) in the header;
// this is the GPU twin. Mirrors stage_advance.cu:60-62 (PCG32 draw).
__device__ inline float rng_uniform(astroray::wavefront::WavefrontRNG& rng) {
    return rng.uniformFloat();  // WavefrontRNG::uniformFloat defined elsewhere
}

namespace astroray::wavefront {

// Forward decl of WavefrontRNG (defined in the GPU wavefront headers, not
// duplicated here to avoid include-order issues).
struct WavefrontRNG;

// Device-side ReSTIRCandidate helper (mirrors light_sample.h but device-callable).
// The CPU side uses Vec3 (not device-callable); this uses GVec3.
struct GReSTIRCandidate {
    GVec3  position;
    GVec3  normal;
    GVec3  emission;  // RGB
    float  pdf;
    float  distance;

    __device__ GReSTIRCandidate()
        : position{0,0,0}, normal{0,0,1}, emission{0,0,0}, pdf(0), distance(0) {}

    __device__ bool isValid() const {
        return pdf > 0.0f && isfinite(pdf);
    }

    // Target function: RGB luminance (wavelength-independent, matches CPU).
    __device__ float targetLuminanceRGB() const {
        return 0.2126f * emission.x + 0.7152f * emission.y + 0.0722f * emission.z;
    }

    // Construct from a light sample (mirrors ReSTIRCandidate::fromLightSample).
    // This is a placeholder — the real implementation samples lights via
    // gpu_nee_sample or the existing light sampler. For C6a, we'll start with
    // a simple stub that returns a zero candidate (no lights sampled yet).
    __device__ static GReSTIRCandidate fromLightSample(/* TODO: light sample args */) {
        GReSTIRCandidate c;
        // Stub for C6a: no light sampling wired yet. C6b will fill this.
        return c;
    }
};

// ---------------------------------------------------------------------------
// Initial RIS stage (Algorithm 1, Bitterli 2020)
// ---------------------------------------------------------------------------
//
// For each pixel, draw numCandidates light samples and feed into a reservoir.
// Writes the finalized reservoir to current_res_* SoA.
//
// NOTE (C6a scope): This is a skeleton. The full implementation needs:
//   - Light sampling via gpu_nee_sample or light tree pick
//   - Proper GReSTIRCandidate construction from light samples
//   - Integration with the wavefront driver (called after primary hit)
//
// C6a delivers the SoA layout + kernel structure; light sampling is the next step.

__global__ void stageRestirInitialRISKernel(
    GPUWavefrontState state,
    int numCandidates,
    int numPixels)
{
    int pixelIdx = blockIdx.x * blockDim.x + threadIdx.x;
    if (pixelIdx >= numPixels) return;

    // Local reservoir (GPU instantiation of Reservoir<GReSTIRCandidate, WavefrontRNG>).
    using ResType = ::astroray::restir::Reservoir<GReSTIRCandidate, WavefrontRNG>;
    ResType res;
    res.reset();

    // Reconstruct per-pixel RNG from the path slot (assuming slot = pixelIdx at
    // bounce 0; this is a simplification — the driver passes the mapping).
    // TODO C6b: thread the correct pixel→slot mapping from the driver.
    WavefrontRNG rng;
    rng.pixel     = state.rng_pixel[pixelIdx];
    rng.sample    = state.rng_sample[pixelIdx];
    rng.dimension = state.rng_dimension[pixelIdx];
    rng.seed      = state.rng_seed[pixelIdx];

    // --- Initial sampling (Algorithm 1) ---
    // For C6a: stub loop (no lights sampled). C6b wires light_tree or light list.
    for (int i = 0; i < numCandidates; ++i) {
        GReSTIRCandidate cand = GReSTIRCandidate::fromLightSample(/* TODO */);
        if (cand.pdf <= 0.0f || !isfinite(cand.pdf)) continue;
        float pHat = cand.targetLuminanceRGB();
        res.update(cand, pHat / cand.pdf, rng);
    }

    // M-cap (Bitterli §5.2): cap at 20×M to prevent history build-up.
    // TODO C6b: make mCap configurable via driver param.
    int effectiveMCap = 20 * numCandidates;
    res.M = min(res.M, effectiveMCap);

    // Write reservoir SoA (current frame).
    // NOTE: GReSTIRCandidate.position/normal/emission are GVec3 (3 floats).
    state.res_y_pos_x[pixelIdx]      = res.y.position.x;
    state.res_y_pos_y[pixelIdx]      = res.y.position.y;
    state.res_y_pos_z[pixelIdx]      = res.y.position.z;
    state.res_y_normal_x[pixelIdx]   = res.y.normal.x;
    state.res_y_normal_y[pixelIdx]   = res.y.normal.y;
    state.res_y_normal_z[pixelIdx]   = res.y.normal.z;
    state.res_y_emission_x[pixelIdx] = res.y.emission.x;
    state.res_y_emission_y[pixelIdx] = res.y.emission.y;
    state.res_y_emission_z[pixelIdx] = res.y.emission.z;
    state.res_y_pdf[pixelIdx]        = res.y.pdf;
    state.res_y_distance[pixelIdx]   = res.y.distance;
    state.res_w_sum[pixelIdx]        = res.w_sum;
    state.res_M[pixelIdx]            = res.M;
    state.res_W[pixelIdx]            = res.W;

    // Write back RNG state (dimension counter advanced by uniform draws).
    state.rng_dimension[pixelIdx] = rng.dimension;
}

void launchStageRestirInitialRIS(
    GPUWavefrontState& state,
    int numCandidates,
    int numPixels)
{
    int threadsPerBlock = 256;
    int numBlocks = (numPixels + threadsPerBlock - 1) / threadsPerBlock;
    stageRestirInitialRISKernel<<<numBlocks, threadsPerBlock>>>(
        state, numCandidates, numPixels);
    cudaDeviceSynchronize();  // TODO: async in production
}

// ---------------------------------------------------------------------------
// Resolve stage — finalize weight, shadow ray, accumulate
// ---------------------------------------------------------------------------
//
// For each pixel with a valid reservoir (W > 0, y.isValid()), cast a shadow
// ray to the selected light sample. If unoccluded, evaluate BSDF and accumulate
// the weighted contribution to state.color.
//
// C6a scope: skeleton only (no BVH occlusion test or BSDF eval wired yet).

__global__ void stageRestirResolveKernel(
    GPUWavefrontState state,
    int numPixels,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials)
{
    int pixelIdx = blockIdx.x * blockDim.x + threadIdx.x;
    if (pixelIdx >= numPixels) return;

    // Read reservoir from SoA.
    GReSTIRCandidate y;
    y.position.x = state.res_y_pos_x[pixelIdx];
    y.position.y = state.res_y_pos_y[pixelIdx];
    y.position.z = state.res_y_pos_z[pixelIdx];
    y.normal.x   = state.res_y_normal_x[pixelIdx];
    y.normal.y   = state.res_y_normal_y[pixelIdx];
    y.normal.z   = state.res_y_normal_z[pixelIdx];
    y.emission.x = state.res_y_emission_x[pixelIdx];
    y.emission.y = state.res_y_emission_y[pixelIdx];
    y.emission.z = state.res_y_emission_z[pixelIdx];
    y.pdf        = state.res_y_pdf[pixelIdx];
    y.distance   = state.res_y_distance[pixelIdx];

    float W = state.res_W[pixelIdx];

    // Guard: skip if reservoir is empty or invalid.
    if (W <= 0.0f || !y.isValid()) return;

    // Finalize weight: W = w_sum / (pHat(y) * M).
    // NOTE: The CPU integrator calls finalizeWeight AFTER reuse. For C6a (no
    // reuse yet), we finalize here. C6b will move finalization after reuse.
    float pHatY = y.targetLuminanceRGB();
    int M = state.res_M[pixelIdx];
    float w_sum = state.res_w_sum[pixelIdx];
    if (M > 0 && pHatY > 0.0f) {
        W = w_sum / (pHatY * static_cast<float>(M));
    } else {
        W = 0.0f;
    }
    state.res_W[pixelIdx] = W;

    if (W <= 0.0f) return;

    // TODO C6b: Recompute direction from shading point (read from hitBufs),
    // cast shadow ray via gpu_bvh_occluded, eval BSDF, accumulate to color.
    // For C6a: stub (no accumulation).
}

void launchStageRestirResolve(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    int numPixels,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials)
{
    int threadsPerBlock = 256;
    int numBlocks = (numPixels + threadsPerBlock - 1) / threadsPerBlock;
    stageRestirResolveKernel<<<numBlocks, threadsPerBlock>>>(
        state, numPixels, d_bvhNodes, d_prims, d_tris, d_spheres, d_materials);
    cudaDeviceSynchronize();  // TODO: async in production
}

// ---------------------------------------------------------------------------
// Temporal reuse stage (Algorithm 2, Bitterli 2020) — DEFERRED to C6b
// ---------------------------------------------------------------------------
//
// For each pixel, read previous frame's reservoir (validity-gated) and merge
// into current. Reads from state_prev (separate device pointer set), writes
// to state_current.
//
// C6b will implement this; C6a ships the SoA layout + RIS + resolve structure.

// void launchStageRestirTemporalReuse(...) { /* C6b */ }

// ---------------------------------------------------------------------------
// Spatial reuse stage (Algorithm 3, Bitterli 2020) — DEFERRED to C6b
// ---------------------------------------------------------------------------
//
// For each pixel, sample N random neighbours from previous frame's buffer,
// merge valid neighbours into current reservoir.
//
// C6b will implement this.

// void launchStageRestirSpatialReuse(...) { /* C6b */ }

} // namespace astroray::wavefront

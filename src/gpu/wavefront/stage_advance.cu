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
#include "astroray/gpu_materials.h"
#include "astroray/gpu_bvh.h"
#include "astroray/gpu_env_spectral.cuh"
#include "astroray/sampling/wavefront_rng_device.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdio>
#include <stdexcept>

// Cross-TU device functions from multiwavelength_kernel.cu (non-inline,
// linked via -rdc=true — the same pattern gpu_materials.h uses for
// gpu_sampleD65 / gpu_jhEvalSpectrum).
__device__ GSampledSpectrum sampleDirectSpectralMW(
    const GHitRecord& rec, const GVec3& wo,
    const GSampledWavelengths& lambdas,
    const GTLASNode*  tlas,
    const GInstance*  instances,
    const GBLAS*      blas,
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial*  materials,
    const ::GLight*     lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    float             rayTime,
    const GVec3*      motionVerts,
    curandState*      rng);

// Non-inline XYZ wrapper exported by multiwavelength_kernel.cu (Session N+6)
// — spectrumToXYZ itself is TU-local inline over the constant CMF tables.
__device__ GVec3 gpu_spectrum_to_xyz(
    const GSampledSpectrum& s, const GSampledWavelengths& wl);

namespace astroray::wavefront {

namespace {

constexpr int kRRDepth = 3;  // mirrors CPU path_kernel.cpp kRRDepth

}  // namespace

// ---------------------------------------------------------------------------
// N+7 part 2: the one-bounce advance body, shared by the dense kernel
// (stageAdvanceKernel) and the queued kernel (stageAdvanceQueuedKernel) --
// one generator of the per-bounce math (design decision #9); the queue is
// purely a scheduling change (Laine 2013 sec. 4 compaction; Cycles X uses
// the same dense-active-queue structure in its integrator queues).
// Returns true when the path survives into the next bounce.
__device__ bool advancePathSlot(
    int idx,
    GPUWavefrontState& state,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth)
{
    const int bounce = state.bounce[idx];

    // ---- Reconstruct live path state from SoA (already-normalized ray
    // direction restored verbatim — the Phase A.1 ulp rule).
    GRay ray;
    ray.origin = GVec3(state.ray_origin_x[idx], state.ray_origin_y[idx],
                       state.ray_origin_z[idx]);
    ray.direction = GVec3(state.ray_direction_x[idx], state.ray_direction_y[idx],
                          state.ray_direction_z[idx]);

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

    // ---- Intersect (CPU: bvh->hit; ray direction NOT renormalized).
    GHitRecord rec;
    bool hit = gpu_bvh_hit(bvhNodes, prims, tris, spheres,
                           ray, 0.001f, 1e30f, rec, /*motionVerts=*/nullptr);

    if (!hit) {
        // ---- Env-map miss (CPU path_kernel: worldMaxBounces gate; the
        // shared helper mirrors EnvironmentMap::evalSpectral).
        if (bounce <= worldMaxBounces) {
            GVec3 dir = ray.direction.normalized();
            GSampledSpectrum envSpec = gpu_env_miss_spectral(
                envMap, backgroundColor, hasBackgroundColor, dir, lambdas);
            color += throughput * envSpec;
            state.color_0[idx] = color.v[0];
            state.color_1[idx] = color.v[1];
            state.color_2[idx] = color.v[2];
            state.color_3[idx] = color.v[3];
        }
        state.path_alive[idx] = 0;
        state.rng_dimension[idx] = rng.dimension();
        return false;
    }

    const ::GMaterial& mat = materials[rec.materialId];

    // ---- Emission (gated on camera ray or post-specular bounce; path ends).
    GSampledSpectrum Le = gpu_material_emitted_spectral(mat, rec.frontFace, lambdas);
    if (Le.maxValue() > 0.f) {
        if (bounce == 0 || wasSpecular) {
            color += throughput * Le;
            state.color_0[idx] = color.v[0];
            state.color_1[idx] = color.v[1];
            state.color_2[idx] = color.v[2];
            state.color_3[idx] = color.v[3];
        }
        state.path_alive[idx] = 0;
        state.rng_dimension[idx] = rng.dimension();
        return false;
    }

    GVec3 wo = (ray.direction * -1.0f).normalized();

    // ---- NEE (skipped on delta lobes). CPU draws light_seed -> mt19937;
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
    }

    // ---- Russian roulette on luminance of throughput's XYZ (bounce > 3).
    if (bounce > kRRDepth) {
        GVec3 thrXYZ = gpu_spectrum_to_xyz(throughput, lambdas);
        float p = fminf(0.95f, fmaxf(0.0f, thrXYZ.y));
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

    // ---- BSDF sampling. CPU: bsdf_seed -> mt19937 -> Material::sampleSpectral.
    // GPU twin: same drawn dimension -> local curandState -> the unmodified
    // megakernel material dispatch (all 7 GMAT types + closure graphs).
    uint32_t bsdf_seed = rng.UniformUInt32();
    curandState bsdf_state;
    curand_init((unsigned long long)bsdf_seed, 0, 0, &bsdf_state);
    GBSDFSample bss = gpu_material_sample_spectral(mat, rec, wo, lambdas, &bsdf_state);
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
    throughput *= bss.fSpectral * (1.0f / (bss.pdf + 0.001f));

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

    int next_bounce = bounce + 1;
    state.bounce[idx] = next_bounce;
    if (next_bounce >= max_depth) {
        state.path_alive[idx] = 0;
        return false;
    }
    return true;
}

__global__ void stageAdvanceKernel(
    GPUWavefrontState state,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= state.num_active) return;
    if (state.path_alive[idx] == 0) return;
    advancePathSlot(idx, state, bvhNodes, prims, tris, spheres, materials,
                    lights, numLights, totalLightPower, lightTree, envMap,
                    backgroundColor, hasBackgroundColor, worldMaxBounces,
                    max_depth);
}

// ---------------------------------------------------------------------------
// N+7 part 2: queued advance + compaction.
//
// queue_in holds the slot indices of paths alive at this bounce, densely
// packed; *count_in is its length (device-side -- the host never reads it,
// preserving the part-1 zero-sync driver). Survivors append their slot to
// queue_out via atomicAdd on *count_out. Thread blocks beyond the active
// count retire immediately, so later bounces only pay for live paths
// (Laine 2013 sec. 4: compaction keeps warps dense as paths die).
// ---------------------------------------------------------------------------
__global__ void stageAdvanceQueuedKernel(
    GPUWavefrontState state,
    const int* queue_in, const int* count_in,
    int* queue_out, int* count_out,
    const GBVHNode*   bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const ::GMaterial* materials,
    const ::GLight*    lights, int numLights, float totalLightPower,
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= *count_in) return;
    int idx = queue_in[i];
    bool alive = advancePathSlot(idx, state, bvhNodes, prims, tris, spheres,
                                 materials, lights, numLights, totalLightPower,
                                 lightTree, envMap, backgroundColor,
                                 hasBackgroundColor, worldMaxBounces, max_depth);
    if (alive) {
        int slot = atomicAdd(count_out, 1);
        queue_out[slot] = idx;
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
// pkg55-B' Session N+7: device-side per-sample XYZ accumulation.
//
// The N+6 driver downloaded 12 SoA arrays per SAMPLE round and accumulated
// XYZ on the host — measured at ~185 ms host overhead per 256x64spp render
// (vs ~115 ms of kernel work). This kernel replaces all of that with one
// device-side pass per sample round: radiance -> XYZ (same cross-TU
// gpu_spectrum_to_xyz the RR stage uses, so the CMF integration is the one
// generator) -> the CPU driver's lum>20 firefly clamp -> += into a float3
// accumulator (one slot per pixel; the N+6/N+7 driver maps slot==pixel).
// The final image is downloaded ONCE per render.
//
// Mirrors src/cpu/wavefront/cpu_wavefront_driver.cpp accumulation exactly
// (float accumulation, clamp BEFORE accumulate, /samples + exposure + sRGB
// stay host-side at the single final conversion).
// ---------------------------------------------------------------------------
__global__ void stageAccumulateXYZKernel(
    GPUWavefrontState state,
    float* accum_xyz)   // 3 floats per slot
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= state.num_active) return;

    GSampledSpectrum rad;
    rad.v[0] = state.color_0[idx];
    rad.v[1] = state.color_1[idx];
    rad.v[2] = state.color_2[idx];
    rad.v[3] = state.color_3[idx];

    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[idx];
    lambdas.lambda[1] = state.lambda_1[idx];
    lambdas.lambda[2] = state.lambda_2[idx];
    lambdas.lambda[3] = state.lambda_3[idx];
    lambdas.pdf[0] = state.lambda_pdf_0[idx];
    lambdas.pdf[1] = state.lambda_pdf_1[idx];
    lambdas.pdf[2] = state.lambda_pdf_2[idx];
    lambdas.pdf[3] = state.lambda_pdf_3[idx];

    GVec3 xyz = gpu_spectrum_to_xyz(rad, lambdas);

    // Per-sample firefly clamp on XYZ.Y (mirrors the CPU wavefront driver).
    float lum = xyz.y;
    if (lum > 20.0f) {
        xyz.x *= (20.0f / lum);
        xyz.y = 20.0f;
        xyz.z *= (20.0f / lum);
    }

    accum_xyz[idx * 3 + 0] += xyz.x;
    accum_xyz[idx * 3 + 1] += xyz.y;
    accum_xyz[idx * 3 + 2] += xyz.z;
}

void launchStageAccumulateXYZ(
    GPUWavefrontState& state,
    float* d_accum_xyz)
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_accumulate_n7",
            (const void*)stageAccumulateXYZKernel, blocks, threads);
        stageAccumulateXYZKernel<<<blocks, threads>>>(state, d_accum_xyz);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_accumulate launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

void launchStageAdvance(
    GPUWavefrontState& state,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const ::GMaterial* d_materials,
    const ::GLight*    d_lights, int num_lights, float total_light_power,
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth,
    bool              sync)
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_advance_n6",
            (const void*)stageAdvanceKernel, blocks, threads);
        stageAdvanceKernel<<<blocks, threads>>>(
            state, d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
            d_lights, num_lights, total_light_power, lightTree,
            envMap, backgroundColor, hasBackgroundColor,
            worldMaxBounces, max_depth);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_advance launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        // pkg55-B' N+7: the render driver passes sync=false and synchronizes
        // ONCE per render (the N+6 per-launch sync was measured at ~185 ms of
        // host overhead per 256^2x64spp render). Same-stream launches are
        // serialized by CUDA, so correctness is unchanged; runtime errors
        // surface at the driver's final sync. Snapshot-harness callers keep
        // the default sync=true (per-stage error localization).
        if (sync) {
            cudaError_t syncErr = cudaDeviceSynchronize();
            if (syncErr != cudaSuccess) {
                std::fprintf(stderr, "stage_advance runtime error: %s\n",
                             cudaGetErrorString(syncErr));
                throw std::runtime_error(cudaGetErrorString(syncErr));
            }
        }
    }
}


void launchStageAdvanceQueued(
    GPUWavefrontState& state,
    const int* d_queue_in, const int* d_count_in,
    int* d_queue_out, int* d_count_out,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const ::GMaterial* d_materials,
    const ::GLight*    d_lights, int num_lights, float total_light_power,
    GLightTreeView    lightTree,
    GEnvMap           envMap,
    GVec3             backgroundColor, bool hasBackgroundColor,
    int               worldMaxBounces,
    int               max_depth)
{
    if (state.num_active <= 0) return;
    // Grid covers the worst case (all paths alive); the kernel early-outs
    // past *d_count_in, so retired blocks cost only launch overhead. The
    // host never reads the device counters (zero-sync driver).
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_advance_queued_n7",
            (const void*)stageAdvanceQueuedKernel, blocks, threads);
        stageAdvanceQueuedKernel<<<blocks, threads>>>(
            state, d_queue_in, d_count_in, d_queue_out, d_count_out,
            d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
            d_lights, num_lights, total_light_power, lightTree,
            envMap, backgroundColor, hasBackgroundColor,
            worldMaxBounces, max_depth);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_advance_queued launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
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

}  // namespace astroray::wavefront

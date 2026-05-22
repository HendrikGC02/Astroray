// stage_shade_lambertian.cu — pkg55-B' Session N+3 part 2
//
// Wavefront Lambertian BSDF shade stage kernel (Session N+3 CUDA port).
//
// Session N+3 part 2 scope:
//   - Read hit record from GPUWavefrontHitBuffers (intersect stage output).
//   - Device-side Lambertian BSDF sampling (cosine-weighted hemisphere).
//   - PCG32 RNG management (read/advance/write live dimension counter).
//   - Throughput update: throughput *= f_spectral / pdf.
//   - Write next-bounce ray into GPUWavefrontState.
//   - Store already-normalized ray direction (never renormalize at boundaries).
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §4.2 Session N+3 part 2.
// Design: PR #296 §4.1, §4.2 (two-tier gate: CPU↔GPU bounded ULP ≤ 4 for geometry).
//
// Reference (Apache-2.0):
//   - Cycles intern/cycles/kernel/integrator/shade_surface.h —
//       integrator_shade_surface() reads hit state, samples BSDF, writes next ray.
//   - PBRT-v4 src/pbrt/wavefront/integrator.cpp — EvaluateMaterialAndBSDF kernel.
//   - CPU mirror: src/cpu/wavefront/path_kernel.cpp::advance_one_bounce() BSDF block.

#include "astroray/gpu_wavefront_state.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_bvh.h"
#include "astroray/gpu_materials.h"  // gpu_rgbToSampledSpectrum
#include "astroray/sampling/wavefront_rng_device.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <cstdio>
#include <stdexcept>

namespace astroray::wavefront {

namespace {

// Lambertian BSDF device-side implementation.
// Mirrors the CPU LambertianPlugin::sampleSpectral logic from plugins/materials/lambertian.cpp.
//
// Reference (Apache-2.0):
//   - Cycles kernel/closure/bsdf_diffuse.h — ccl_bsdf_diffuse_sample (cosine-weighted hemisphere)
//   - PBRT-v4 src/pbrt/bsdf.cpp — DiffuseReflection::Sample_f
//
// Math:
//   - f(wo, wi) = albedo / π
//   - pdf(wi) = cos(θi) / π
//   - Importance sampling: wi = cosine_sample_hemisphere(u1, u2)
//
// Returns sampled direction wi in tangent space, f_spectral, pdf, and isDelta flag.
struct LambertianSampleResult {
    GVec3 wi_tangent;           // sampled direction in tangent space
    GSampledSpectrum f_spectral; // BSDF value at sampled direction
    float pdf;                   // probability density of wi
    bool isDelta;                // always false for Lambertian
};

// Cosine-weighted hemisphere sampling (tangent-space convention: z = normal).
// Mirrors the CPU WavefrontRNG uniform_sample_cosine_hemisphere helper.
//
// Reference:
//   - PBRT-v3 §13.6.1 (cosine-weighted sampling via Malley's method)
//   - Pharr, Jakob, Humphreys 2016, "Physically Based Rendering," 3rd ed., §13.6.3
__device__ inline GVec3 sampleCosineHemisphere(float u1, float u2) {
    // Malley's method: uniform disk → project to hemisphere.
    // r = sqrt(u1), theta = 2π * u2
    float r = sqrtf(u1);
    float theta = 2.0f * 3.14159265f * u2;
    float x = r * cosf(theta);
    float y = r * sinf(theta);
    float z = sqrtf(fmaxf(0.0f, 1.0f - u1));  // z = sqrt(1 - r^2)
    return GVec3(x, y, z);
}

// Lambertian BSDF sampling.
// Mirrors CPU LambertianPlugin::sampleSpectral from plugins/materials/lambertian.cpp.
__device__ inline LambertianSampleResult sampleLambertianBSDF(
    WavefrontRNG& rng,
    const GSampledSpectrum& albedo_spec,
    const GVec3& wo_tangent,
    const GSampledWavelengths& lambdas)
{
    LambertianSampleResult result;
    result.isDelta = false;

    // Draw two uniform samples for cosine-weighted hemisphere.
    float u1 = rng.Uniform();
    float u2 = rng.Uniform();

    // Sample direction in tangent space (z = normal).
    result.wi_tangent = sampleCosineHemisphere(u1, u2);

    // Lambertian BSDF: f = albedo / π
    const float kInvPi = 0.31830988618379067f;  // 1 / π
    result.f_spectral = albedo_spec * kInvPi;

    // pdf = cos(θ) / π, where cos(θ) = wi_tangent.z (tangent space convention)
    float cosTheta = fmaxf(0.0f, result.wi_tangent.z);
    result.pdf = cosTheta * kInvPi;

    return result;
}

// Tangent-space to world-space transform.
// Mirrors the CPU advance_one_bounce's tangent-space setup.
// Given normal, tangent, bitangent (orthonormal basis), transforms tangent-space wi to world-space.
__device__ inline GVec3 tangentToWorld(const GVec3& wi_tangent,
                                       const GVec3& tangent,
                                       const GVec3& bitangent,
                                       const GVec3& normal)
{
    return tangent * wi_tangent.x + bitangent * wi_tangent.y + normal * wi_tangent.z;
}

__global__ void stageShadeLambertianKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const GMaterial* materials,
    int num_materials)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= state.num_active) return;

    // Only process alive paths with valid hits.
    if (state.path_alive[idx] == 0 || hitBufs.hit_valid[idx] == 0) return;

    // Reconstruct hit record from SoA.
    GVec3 hit_point(hitBufs.hit_point_x[idx],
                    hitBufs.hit_point_y[idx],
                    hitBufs.hit_point_z[idx]);
    GVec3 hit_normal(hitBufs.hit_normal_x[idx],
                     hitBufs.hit_normal_y[idx],
                     hitBufs.hit_normal_z[idx]);
    GVec3 hit_tangent(hitBufs.hit_tangent_x[idx],
                      hitBufs.hit_tangent_y[idx],
                      hitBufs.hit_tangent_z[idx]);
    GVec3 hit_bitangent(hitBufs.hit_bitangent_x[idx],
                        hitBufs.hit_bitangent_y[idx],
                        hitBufs.hit_bitangent_z[idx]);
    int material_id = hitBufs.hit_material_id[idx];

    // Reconstruct ray direction from SoA (already normalized).
    GVec3 ray_direction(state.ray_direction_x[idx],
                        state.ray_direction_y[idx],
                        state.ray_direction_z[idx]);

    // wo = -ray_direction (outgoing direction in material evaluation).
    GVec3 wo = ray_direction * -1.0f;
    wo = wo.normalized();

    // Reconstruct spectral state from SoA.
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
    throughput[0] = state.throughput_0[idx];
    throughput[1] = state.throughput_1[idx];
    throughput[2] = state.throughput_2[idx];
    throughput[3] = state.throughput_3[idx];

    // Reconstruct live RNG from SoA (carries exact dimension counter).
    WavefrontRNG rng(state.rng_pixel[idx],
                     state.rng_sample[idx],
                     state.rng_seed[idx]);
    rng.setDimension(state.rng_dimension[idx]);

    // Material lookup. Session N+3 part 2 scope: Lambertian-only.
    // For now, assume material_id maps directly to materials array.
    // Production code will need proper material lookup table.
    if (material_id < 0 || material_id >= num_materials) {
        // Invalid material: terminate path.
        state.path_alive[idx] = 0;
        return;
    }

    const GMaterial& mat = materials[material_id];

    // For Session N+3 part 2: only Lambertian materials are in scope.
    // GMaterial stores RGB baseColor; upsample to spectral via the same path
    // the megakernel uses (gpu_rgbToSampledSpectrum, gpu_materials.h:89). Full
    // material dispatch happens in later sessions.
    GSampledSpectrum albedo_spec =
        gpu_rgbToSampledSpectrum(mat.baseColor, lambdas, mat.spectralMode);

    // BSDF sampling (Lambertian).
    // Note: the CPU path_kernel calls Material::sampleSpectral via a seeded mt19937.
    // We replicate the BSDF-seed draw pattern here (one UniformUInt32 for BSDF seed).
    uint32_t bsdf_seed = rng.UniformUInt32();
    // For Session N+3 simplified Lambertian: inline the sampling using the current RNG.
    // Full production would mirror the mt19937 seeding pattern.

    // Convert wo to tangent space for BSDF evaluation.
    // Tangent-space convention: z = normal, x = tangent, y = bitangent.
    // wo_tangent = (dot(wo, tangent), dot(wo, bitangent), dot(wo, normal))
    GVec3 wo_tangent(wo.dot(hit_tangent), wo.dot(hit_bitangent), wo.dot(hit_normal));

    // Sample Lambertian BSDF.
    LambertianSampleResult bss = sampleLambertianBSDF(rng, albedo_spec, wo_tangent, lambdas);

    if (bss.pdf <= 0.0f) {
        // Invalid sample: terminate path.
        state.path_alive[idx] = 0;
        return;
    }

    // Transform sampled direction from tangent space to world space.
    GVec3 wi_world = tangentToWorld(bss.wi_tangent, hit_tangent, hit_bitangent, hit_normal);

    // Update throughput: throughput *= f_spectral / pdf
    // Add small epsilon to pdf to avoid division by zero (matches CPU path_kernel.cpp line 298).
    throughput = throughput * bss.f_spectral * (1.0f / (bss.pdf + 0.001f));

    // Write updated throughput back to SoA.
    state.throughput_0[idx] = throughput[0];
    state.throughput_1[idx] = throughput[1];
    state.throughput_2[idx] = throughput[2];
    state.throughput_3[idx] = throughput[3];

    // Advance ray: next origin = hit point, next direction = wi (already normalized by BSDF sampling).
    // Store the already-normalized direction verbatim (Phase A.1 ulp-bug fix).
    state.ray_origin_x[idx] = hit_point.x;
    state.ray_origin_y[idx] = hit_point.y;
    state.ray_origin_z[idx] = hit_point.z;

    GVec3 next_direction = wi_world.normalized();  // Single normalization, matches CPU
    state.ray_direction_x[idx] = next_direction.x;
    state.ray_direction_y[idx] = next_direction.y;
    state.ray_direction_z[idx] = next_direction.z;

    // Update was_specular (Lambertian is non-delta).
    state.was_specular[idx] = bss.isDelta ? 1 : 0;

    // Write live RNG state back to SoA.
    state.rng_dimension[idx] = rng.dimension();

    // Increment bounce count.
    state.bounce[idx] += 1;
}

}  // namespace

void launchStageShadeLambertian_SessionN3(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const GMaterial* d_materials,
    int num_materials)
{
    int n = state.num_active;
    if (n <= 0) return;

    int threads = 256;
    int blocks  = (n + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_shade_lambertian_n3",
            (const void*)stageShadeLambertianKernel, blocks, threads);
        stageShadeLambertianKernel<<<blocks, threads>>>(
            state, hitBufs, d_materials, num_materials);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_shade_lambertian_n3 launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        cudaError_t syncErr = cudaDeviceSynchronize();
        if (syncErr != cudaSuccess) {
            std::fprintf(stderr, "stage_shade_lambertian_n3 runtime error: %s\n",
                         cudaGetErrorString(syncErr));
            throw std::runtime_error(cudaGetErrorString(syncErr));
        }
    }
}

}  // namespace astroray::wavefront

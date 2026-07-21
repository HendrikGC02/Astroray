// stage_light_sample.cu — pkg55-B' Session N+4
//
// Wavefront Next Event Estimation (NEE) stage kernel.
//
// Session N+4 scope:
//   - Sample one area light using uniform random selection.
//   - Trace shadow ray (BVH any-hit test).
//   - Compute MIS weight (power heuristic) comparing light PDF vs BSDF PDF.
//   - Accumulate NEE contribution to path color if unoccluded.
//   - Skip NEE on delta BSDFs (Lambertian is always non-delta, so this
//     is inactive in Session N+4 Lambertian-only scope).
//
// This kernel runs AFTER stage_shade (which computed the next-bounce ray)
// and BEFORE stage_russian_roulette. It reads hit record + throughput from
// the shade stage output and accumulates radiance into `color`.
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §4.2 Session N+4.
// Design: PR #296 §4.2 (two-tier gate: CPU↔GPU bounded p99.9 for transcendentals).
//
// Reference (Apache-2.0):
//   - Cycles intern/cycles/kernel/integrator/shade_light.h —
//       integrator_shade_light() implements NEE with shadow ray + MIS.
//   - PBRT-v4 src/pbrt/wavefront/integrator.cpp — DirectLighting kernel.
//   - CPU mirror: src/cpu/wavefront/path_kernel.cpp::advance_one_bounce()
//       lines 229-273 (area-light NEE block).

#include "astroray/gpu_wavefront_state.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_bvh.h"
#include "astroray/gpu_materials.h"
#include "astroray/sampling/wavefront_rng_device.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <cstdio>
#include <stdexcept>

namespace astroray::wavefront {

namespace {

// Light sampling result (device-side).
// Mirrors CPU LightSample from raytracer.h.
struct GLightSample {
    GVec3 position;               // sampled point on light
    GVec3 normal;                 // light surface normal
    float distance;               // distance from shading point to light
    float pdf;                    // probability density of this sample
    GSampledSpectrum emission;    // emitted radiance at sampled wavelengths
};

// Sample one area light uniformly.
// Mirrors CPU LightCollection::sample() logic from lights.h / lights.cpp.
//
// For Session N+4 (Lambertian-only Cornell), the light collection has exactly
// one area light (the Cornell box ceiling light). We sample it uniformly over
// its surface.
//
// Args:
//   rng: WavefrontRNG (consumes dimensions for light selection + surface u/v).
//   shading_point: surface point being shaded (from hit record).
//   shading_normal: surface normal at shading point.
//   lambdas: wavelengths to sample.
//   d_lights: device pointer to area light data (uploaded by scene_upload).
//   num_lights: total number of area lights.
//
// Returns:
//   GLightSample with position, normal, pdf, distance, emission.
//   If no lights or pdf == 0, returns pdf=0 (caller must guard).
//
// NOTE: This is a SIMPLIFIED light sampler for Session N+4. It assumes:
//   - All lights are diffuse area lights (no point/directional/env lights).
//   - Uniform light selection (pdf = 1 / num_lights).
//   - Uniform surface sampling within the selected light.
//
// A production implementation would:
//   - Use power-based light selection (not uniform).
//   - Support env maps, point lights, directional lights.
//   - Handle light importance sampling (solid angle, not area).
//
// This simplified version mirrors the CPU path_kernel.cpp NEE block for
// Lambertian-only Cornell, which has exactly 1 area light.
__device__ GLightSample sampleAreaLight(
    WavefrontRNG& rng,
    const GVec3& shading_point,
    const GVec3& shading_normal,
    const GSampledWavelengths& lambdas,
    const ::GAreaLight* d_lights,
    int num_lights)
{
    GLightSample result;
    result.pdf = 0.0f;
    result.distance = 0.0f;
    result.position = GVec3(0, 0, 0);
    result.normal = GVec3(0, 0, 1);
    result.emission = GSampledSpectrum(0.0f);

    if (num_lights == 0) return result;

    // Uniform light selection. For Session N+4 (1 light), this is deterministic.
    int light_idx = 0;
    if (num_lights > 1) {
        float u_light = rng.Uniform();
        light_idx = (int)(u_light * num_lights);
        if (light_idx >= num_lights) light_idx = num_lights - 1;
    }

    const ::GAreaLight& light = d_lights[light_idx];

    // Sample two uniform coordinates on the light surface.
    float u1 = rng.Uniform();
    float u2 = rng.Uniform();

    // Compute sampled position and normal on the light triangle.
    // For a single-triangle area light (Cornell ceiling), interpolate
    // barycentrically. For multi-triangle lights, this would select a
    // triangle first (weighted by area), then sample within it.
    //
    // Session N+4 ASSUMES the area light is a single triangle and samples
    // it uniformly. The CPU LightCollection::sample() uses the same
    // barycentric sampling for single-triangle lights.
    //
    // Barycentric coordinates: (w, u, v) = (1 - sqrt(u1), sqrt(u1) * (1 - u2), sqrt(u1) * u2)
    // This is uniform area sampling on a triangle (Pharr et al. §13.6.4).
    float sqrt_u1 = sqrtf(u1);
    float w = 1.0f - sqrt_u1;
    float u = sqrt_u1 * (1.0f - u2);
    float v = sqrt_u1 * u2;

    // Interpolate position: p = w*v0 + u*v1 + v*v2
    result.position = light.v0 * w + light.v1 * u + light.v2 * v;

    // Interpolate normal (assuming flat shading for Session N+4).
    // Production would interpolate per-vertex normals if available.
    result.normal = light.normal;

    // Distance from shading point to sampled light point.
    GVec3 to_light = result.position - shading_point;
    result.distance = to_light.length();

    // PDF: uniform area sampling → pdf = 1 / (light_area * num_lights).
    // Light area = 0.5 * ||(v1 - v0) × (v2 - v0)||.
    GVec3 e1 = light.v1 - light.v0;
    GVec3 e2 = light.v2 - light.v0;
    float area = 0.5f * e1.cross(e2).length();
    result.pdf = (area > 0.0f) ? (1.0f / (area * num_lights)) : 0.0f;

    // Emitted radiance: convert light RGB emission to spectral.
    // Mirrors CPU LightSample::emission_spec = RGBUnboundedSpectrum(emission).sample(lambdas)
    // (pkg142 Defect 4: no-D65 lift, matches Cycles' RGB-native light scaling).
    result.emission = gpu_rgbToSampledSpectrum(light.emission, lambdas, GSPEC_RGB_UNBOUNDED);

    return result;
}

// BVH shadow ray any-hit test.
// Returns true if an occluder was hit before reaching the light.
//
// Mirrors CPU BVH::hit() with tmax clamped to light distance.
// For Session N+4, we use a simplified any-hit traversal (terminate on
// first hit within [tmin, tmax]).
//
// Production would:
//   - Skip transparent/alpha-tested geometry.
//   - Handle infinite lights (no occlusion test).
//   - Use dedicated any-hit BVH traversal (faster than closest-hit).
__device__ bool traceShadowRay(
    const GVec3& origin,
    const GVec3& direction,
    float tmin,
    float tmax,
    const GBVHNode* d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle* d_tris,
    const GSphere* d_spheres)
{
    // Simplified any-hit traversal: reuse gpu_bvh_hit() and check if t < tmax.
    // This is not optimal (we only need any-hit, not closest-hit), but it
    // avoids duplicating the BVH traversal code in Session N+4.
    //
    // Session N+5+ would add a dedicated gpu_bvh_any_hit() function for
    // shadow rays (terminates on first hit, no material/normal computation).
    GHitRecord shadow_hit;
    GRay shadow_ray;
    shadow_ray.origin = origin;
    shadow_ray.direction = direction;  // assume normalized by caller
    bool hit = gpu_bvh_hit(d_bvhNodes, d_prims, d_tris, d_spheres,
                            shadow_ray, tmin, tmax, shadow_hit);

    // If we hit something within [tmin, tmax], the shadow ray is occluded.
    // NOTE: The CPU version checks `!(shadow.hitObject && shadow.hitObject->isInfiniteLight())`.
    // For Session N+4 (no infinite lights), any hit is an occlusion.
    return hit;
}

// NEE kernel: for each active path, sample one area light, trace shadow ray,
// compute MIS weight, and accumulate radiance.
//
// Reads:
//   - state: path ray_origin/ray_direction/throughput/lambdas/rng from shade stage.
//   - hitBufs: hit record from intersect stage (hit_point, hit_normal, hit_material_id).
//   - d_materials: material array (to evaluate BSDF at light direction).
//   - d_lights: area light array.
//
// Writes:
//   - state.color: accumulated NEE contribution (if unoccluded).
//   - state.rng_dimension: advanced RNG dimension (consumed 2-3 dims for light sampling).
//
// Skips NEE if:
//   - path_alive == 0 (path already terminated).
//   - hit_is_delta == 1 (delta BSDF, NEE is zero — N/A for Lambertian).
//   - num_lights == 0 (no lights in scene).
__global__ void stageLightSampleKernel(
    GPUWavefrontState state,
    GPUWavefrontHitBuffers hitBufs,
    const ::GMaterial* d_materials,
    int num_materials,
    const ::GAreaLight* d_lights,
    int num_lights,
    const GBVHNode* d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle* d_tris,
    const GSphere* d_spheres)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= state.num_active) return;

    // Skip if path is dead or if no lights.
    if (state.path_alive[i] == 0) return;
    if (num_lights == 0) return;

    // Skip if hit is invalid (should have been terminated in shade stage).
    if (hitBufs.hit_valid[i] == 0) return;

    // Skip if BSDF is delta (no NEE contribution). For Lambertian, always non-delta.
    if (hitBufs.hit_is_delta[i] == 1) return;

    // Reconstruct hit record and path state.
    GVec3 hit_point(hitBufs.hit_point_x[i], hitBufs.hit_point_y[i], hitBufs.hit_point_z[i]);
    GVec3 hit_normal(hitBufs.hit_normal_x[i], hitBufs.hit_normal_y[i], hitBufs.hit_normal_z[i]);
    int material_id = hitBufs.hit_material_id[i];

    if (material_id < 0 || material_id >= num_materials) return;

    // Reconstruct RNG (3-arg ctor + setDimension; mirrors stage_init.cu).
    WavefrontRNG rng(state.rng_pixel[i], state.rng_sample[i], state.rng_seed[i]);
    rng.setDimension(state.rng_dimension[i]);

    // Reconstruct wavelengths.
    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[i];
    lambdas.lambda[1] = state.lambda_1[i];
    lambdas.lambda[2] = state.lambda_2[i];
    lambdas.lambda[3] = state.lambda_3[i];
    lambdas.pdf[0] = state.lambda_pdf_0[i];
    lambdas.pdf[1] = state.lambda_pdf_1[i];
    lambdas.pdf[2] = state.lambda_pdf_2[i];
    lambdas.pdf[3] = state.lambda_pdf_3[i];

    // Reconstruct throughput (default-construct + assign by index; no 4-arg ctor).
    GSampledSpectrum throughput;
    throughput[0] = state.throughput_0[i];
    throughput[1] = state.throughput_1[i];
    throughput[2] = state.throughput_2[i];
    throughput[3] = state.throughput_3[i];

    // Sample one area light.
    GLightSample ls = sampleAreaLight(rng, hit_point, hit_normal, lambdas,
                                       d_lights, num_lights);

    if (ls.pdf <= 0.0f) {
        // Invalid light sample; update RNG dimension and return.
        state.rng_dimension[i] = rng.dimension();
        return;
    }

    // Direction to light.
    GVec3 wi = (ls.position - hit_point).normalized();

    // Trace shadow ray. Use tmin = 0.001 to avoid self-intersection,
    // tmax = distance - 0.001 to avoid hitting the light geometry itself.
    float tmin = 0.001f;
    float tmax = ls.distance - 0.001f;
    bool occluded = traceShadowRay(hit_point, wi, tmin, tmax,
                                    d_bvhNodes, d_prims, d_tris, d_spheres);

    if (!occluded) {
        // Evaluate BSDF at light direction.
        // For Lambertian: f = albedo / π.
        // We need to call the material's evalSpectral function.
        //
        // Session N+4 NOTE: We don't have a device-side evalSpectral virtual
        // dispatch yet. For Lambertian-only scope, we can inline the BSDF eval.
        // A future session will add full material dispatch.
        //
        // Lambertian BSDF: f(wo, wi) = albedo / π.
        // albedo is stored in the material's base_color.
        const ::GMaterial& mat = d_materials[material_id];
        GSampledSpectrum albedo_spec = gpu_rgbToSampledSpectrum(mat.baseColor, lambdas, mat.spectralMode);
        const float kInvPi = 0.31830988618379067f;  // 1 / π
        GSampledSpectrum f_spec = albedo_spec * kInvPi;

        // BSDF PDF at light direction (for MIS).
        // Lambertian pdf = cos(θ) / π, where cos(θ) = dot(hit_normal, wi).
        float cosTheta = fmaxf(0.0f, hit_normal.dot(wi));
        float bsdfPdf = cosTheta * kInvPi;

        // MIS weight: power heuristic (balance heuristic alternative).
        // w = (light_pdf^2) / (light_pdf^2 + bsdf_pdf^2).
        // Mirrors CPU line 244-245.
        float a = ls.pdf;
        float b = bsdfPdf;
        float wt = (a * a) / (a * a + b * b + 1e-8f);

        // NEE contribution: f * L * (wt / pdf).
        // Mirrors CPU line 246.
        GSampledSpectrum L_spec = ls.emission;
        GSampledSpectrum nee_contribution = f_spec * L_spec * (wt / (ls.pdf + 0.001f));

        // Accumulate to path color: color += throughput * nee_contribution.
        GSampledSpectrum color_update = throughput * nee_contribution;
        state.color_0[i] += color_update[0];
        state.color_1[i] += color_update[1];
        state.color_2[i] += color_update[2];
        state.color_3[i] += color_update[3];
    }

    // Update RNG dimension (consumed 2-3 dimensions for light sampling).
    state.rng_dimension[i] = rng.dimension();
}

}  // anonymous namespace

// Host-side launcher for stage_light_sample.
void launchStageLightSample_SessionN4(
    GPUWavefrontState& state,
    GPUWavefrontHitBuffers& hitBufs,
    const ::GMaterial* d_materials,
    int num_materials,
    const ::GAreaLight* d_lights,
    int num_lights,
    const GBVHNode* d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle* d_tris,
    const GSphere* d_spheres)
{
    if (state.num_active == 0) return;

    const int kThreadsPerBlock = 256;
    int numBlocks = (state.num_active + kThreadsPerBlock - 1) / kThreadsPerBlock;

    stageLightSampleKernel<<<numBlocks, kThreadsPerBlock>>>(
        state, hitBufs,
        d_materials, num_materials,
        d_lights, num_lights,
        d_bvhNodes, d_prims, d_tris, d_spheres
    );

    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        throw std::runtime_error(
            std::string("launchStageLightSample_SessionN4 kernel launch failed: ") +
            cudaGetErrorString(err)
        );
    }
}

}  // namespace astroray::wavefront

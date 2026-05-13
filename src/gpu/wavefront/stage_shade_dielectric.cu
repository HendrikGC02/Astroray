// stage_shade_dielectric.cu — pkg55 Phase B
//
// Shade kernel for GMAT_DIELECTRIC surfaces. Implements perfect Fresnel
// reflection/refraction (Snell's law + TIR). Dielectric is always delta,
// so no NEE shadow ray is emitted.
//
// Architecture: Cycles intern/cycles/kernel/integrator/shade_surface.h (Apache-2.0)
//
// BSDF implementation: mirrors Astroray megakernel gpu_dielectric_sample
//   (include/astroray/gpu_materials.h lines 257-288). Fresnel + Snell's law
//   are undergraduate textbook (trivial per CLAUDE.md §6).

#include "astroray/integrator_state_soa.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdio>

namespace astroray::wavefront {

namespace {

__global__ void shadeDielectricKernel(
    const float4*  hit_point,
    const float4*  hit_normal,
    const float4*  hit_tangent,
    const float4*  hit_bitangent,
    const int*     hit_mat,
    const uint8_t* hit_flags,
    const int*     pixel_index,
    const int*     depth,
    const float4*  ray_direction_in,
    const float4*  lambda_in,
    const float4*  lambda_pdf_in,
    const float4*  throughput_in,
    const float4*  throughput_sp_in,
    const uint8_t* path_alive,
    float4*  ray_origin_out,
    float4*  ray_direction_out,
    float4*  throughput_out,
    float4*  throughput_sp_out,
    float*   pdf_out,
    uint8_t* was_specular_out,
    int*     depth_out,
    curandState* rng_state,
    const GMaterial* materials,
    int num_active,
    int maxDepth)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= num_active) return;
    if (path_alive[idx] == 0) return;

    // Material-type guard: only process GMAT_DIELECTRIC
    const GMaterial& mat = materials[hit_mat[idx]];
    if (mat.type != GMAT_DIELECTRIC) return;

    GHitRecord rec;
    rec.point = GVec3(hit_point[idx].x, hit_point[idx].y, hit_point[idx].z);
    rec.normal = GVec3(hit_normal[idx].x, hit_normal[idx].y, hit_normal[idx].z);
    rec.tangent = GVec3(hit_tangent[idx].x, hit_tangent[idx].y, hit_tangent[idx].z);
    rec.bitangent = GVec3(hit_bitangent[idx].x, hit_bitangent[idx].y, hit_bitangent[idx].z);
    rec.materialId = hit_mat[idx];
    rec.frontFace = (hit_flags[idx] & 0x1) != 0;
    rec.isDelta = (hit_flags[idx] & 0x2) != 0;

    GVec3 wo = -GVec3(ray_direction_in[idx].x, ray_direction_in[idx].y, ray_direction_in[idx].z).normalized();

    GSampledWavelengths lambdas;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        lambdas.lambda[i] = reinterpret_cast<const float*>(&lambda_in[idx])[i];
        lambdas.pdf[i] = reinterpret_cast<const float*>(&lambda_pdf_in[idx])[i];
    }

    GVec3 throughput(throughput_in[idx].x, throughput_in[idx].y, throughput_in[idx].z);
    GSampledSpectrum throughputSpectral;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        throughputSpectral[i] = reinterpret_cast<const float*>(&throughput_sp_in[idx])[i];
    }

    curandState localRng = rng_state[idx];
    GBSDFSample bs = gpu_material_sample_spectral(mat, rec, wo, lambdas, &localRng);
    rng_state[idx] = localRng;

    if (bs.pdf <= 0.f) {
        depth_out[idx] = maxDepth + 1;
        return;
    }

    throughput *= bs.f / (bs.pdf + 0.001f);
    throughputSpectral *= bs.fSpectral * (1.f / (bs.pdf + 0.001f));

    float maxC = throughput.maxComponent();
    if (maxC > 10.f) throughput *= 10.f / maxC;
    float maxS = throughputSpectral.maxValue();
    if (maxS > 10.f) throughputSpectral *= 10.f / maxS;

    ray_origin_out[idx] = make_float4(rec.point.x, rec.point.y, rec.point.z, 0.f);
    ray_direction_out[idx] = make_float4(bs.wi.x, bs.wi.y, bs.wi.z, 0.f);
    throughput_out[idx] = make_float4(throughput.x, throughput.y, throughput.z, 0.f);

    float4 tspec;
    reinterpret_cast<float*>(&tspec)[0] = throughputSpectral[0];
    reinterpret_cast<float*>(&tspec)[1] = throughputSpectral[1];
    reinterpret_cast<float*>(&tspec)[2] = throughputSpectral[2];
    reinterpret_cast<float*>(&tspec)[3] = throughputSpectral[3];
    throughput_sp_out[idx] = tspec;

    pdf_out[idx] = bs.pdf;
    was_specular_out[idx] = 1;  // dielectric is always delta
    depth_out[idx] = depth[idx] + 1;

    // No NEE for delta materials
}

}  // namespace

void launchShadeDielectric(
    IntegratorStateSoA& state,
    const GMaterial* d_mats,
    int maxDepth)
{
    int n = state.num_active;
    if (n <= 0) return;

    int threads = 256;
    int blocks = (n + threads - 1) / threads;

    shadeDielectricKernel<<<blocks, threads>>>(
        reinterpret_cast<const float4*>(state.hit_point),
        reinterpret_cast<const float4*>(state.hit_normal),
        reinterpret_cast<const float4*>(state.hit_tangent),
        reinterpret_cast<const float4*>(state.hit_bitangent),
        state.hit_mat,
        state.hit_flags,
        state.pixel_index,
        state.depth,
        reinterpret_cast<const float4*>(state.ray_direction),
        reinterpret_cast<const float4*>(state.lambda),
        reinterpret_cast<const float4*>(state.lambda_pdf),
        reinterpret_cast<const float4*>(state.throughput),
        reinterpret_cast<const float4*>(state.throughput_sp),
        state.path_alive,
        reinterpret_cast<float4*>(state.ray_origin),
        reinterpret_cast<float4*>(state.ray_direction),
        reinterpret_cast<float4*>(state.throughput),
        reinterpret_cast<float4*>(state.throughput_sp),
        state.pdf,
        state.was_specular,
        state.depth,
        reinterpret_cast<curandState*>(state.rng_state),
        d_mats,
        state.num_active,
        maxDepth);

    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        std::fprintf(stderr, "shade_dielectric launch error: %s\n",
                     cudaGetErrorString(err));
    }
    cudaDeviceSynchronize();
}

}  // namespace astroray::wavefront

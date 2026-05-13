// stage_shade_diffuse_light.cu — pkg55 Phase B
//
// Shade kernel for GMAT_DIFFUSE_LIGHT surfaces (area lights). Accumulates
// emission and terminates the path (lights don't scatter).
//
// Architecture: Cycles intern/cycles/kernel/integrator/shade_surface.h (Apache-2.0)
//
// Implementation: matches the megakernel's "if (emitted != GVec3(0.f)) ... break"
//   pattern (path_trace_kernel.cu lines 289-297). Emission accumulation is
//   trivial (no citation needed per CLAUDE.md §6).

#include "astroray/integrator_state_soa.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <cstdio>

namespace astroray::wavefront {

namespace {

__global__ void shadeDiffuseLightKernel(
    const float4*  hit_point,
    const float4*  hit_normal,
    const int*     hit_mat,
    const uint8_t* hit_flags,
    const int*     depth,
    const float4*  lambda_in,
    const float4*  throughput_in,
    const float4*  throughput_sp_in,
    const uint8_t* path_alive,
    const uint8_t* was_specular,
    float4*  accum_rgb,
    uint8_t* path_alive_out,
    int*     depth_out,
    const GMaterial* materials,
    int num_active,
    int maxDepth)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= num_active) return;
    if (path_alive[idx] == 0) return;

    // Material-type guard: only process GMAT_DIFFUSE_LIGHT
    const GMaterial& mat = materials[hit_mat[idx]];
    if (mat.type != GMAT_DIFFUSE_LIGHT) return;
    bool frontFace = (hit_flags[idx] & 0x1) != 0;

    GVec3 emitted = gpu_material_emitted(mat, frontFace);
    GSampledWavelengths lambdas;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        lambdas.lambda[i] = reinterpret_cast<const float*>(&lambda_in[idx])[i];
    }
    GSampledSpectrum emittedSpectral = gpu_material_emitted_spectral(mat, frontFace, lambdas);

    // Only accumulate emission on first bounce or after specular bounce
    // (matches megakernel line 292: "if (bounce == 0 || wasSpecular)")
    if (depth[idx] == 0 || was_specular[idx] != 0) {
        GVec3 throughput(throughput_in[idx].x, throughput_in[idx].y, throughput_in[idx].z);
        GSampledSpectrum throughputSpectral;
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
            throughputSpectral[i] = reinterpret_cast<const float*>(&throughput_sp_in[idx])[i];
        }

        GVec3 contribution = throughput * emitted;
        // For spectral: convert spectral emission to RGB for accumulation
        // (full spectral accumulation is Phase C; Phase B accumulates RGB)
        float4 current_accum = accum_rgb[idx];
        current_accum.x += contribution.x;
        current_accum.y += contribution.y;
        current_accum.z += contribution.z;
        accum_rgb[idx] = current_accum;
    }

    // Terminate path (lights don't scatter)
    depth_out[idx] = maxDepth + 1;
    path_alive_out[idx] = 0;
}

}  // namespace

void launchShadeDiffuseLight(
    IntegratorStateSoA& state,
    const GMaterial* d_mats)
{
    int n = state.num_active;
    if (n <= 0) return;

    int threads = 256;
    int blocks = (n + threads - 1) / threads;

    shadeDiffuseLightKernel<<<blocks, threads>>>(
        reinterpret_cast<const float4*>(state.hit_point),
        reinterpret_cast<const float4*>(state.hit_normal),
        state.hit_mat,
        state.hit_flags,
        state.depth,
        reinterpret_cast<const float4*>(state.lambda),
        reinterpret_cast<const float4*>(state.throughput),
        reinterpret_cast<const float4*>(state.throughput_sp),
        state.path_alive,
        state.was_specular,
        reinterpret_cast<float4*>(state.accum_rgb),
        state.path_alive,
        state.depth,
        d_mats,
        state.num_active,
        999);  // maxDepth placeholder

    cudaError_t err = cudaGetLastError();
    if (err != cudaSuccess) {
        std::fprintf(stderr, "shade_diffuse_light launch error: %s\n",
                     cudaGetErrorString(err));
    }
    cudaDeviceSynchronize();
}

}  // namespace astroray::wavefront

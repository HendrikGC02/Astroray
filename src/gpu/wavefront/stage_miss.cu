// stage_miss.cu — pkg55 Phase B
//
// Miss stage: handles rays that escaped the scene (hit_t < 0). Accumulates
// environment map or background color radiance. Only accumulates if this is
// the first bounce or the previous bounce was specular (matches megakernel
// "bounce == 0 || wasSpecular" guard, line 279-283).
//
// Architecture: Cycles (blender/cycles @ c9227ff, Apache-2.0)
//   intern/cycles/kernel/integrator/shade_background.h — environment lookup
//   + accumulation for escaped rays.
//
// Environment sampling: gpu_envmap_lookup is shared with the megakernel
//   (src/gpu/gpu_bvh.h). Trivial sky-gradient fallback (no citation needed).

#include "astroray/integrator_state_soa.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <cstdio>

namespace astroray::wavefront {

namespace {

__global__ void missKernel(
    const float*   hit_t,
    const float4*  ray_direction,
    const float4*  lambda,
    const float4*  throughput,
    const float4*  throughput_sp,
    const uint8_t* path_alive,
    const uint8_t* was_specular,
    float4*  accum_rgb,
    uint8_t* path_alive_out,
    const GEnvMap  envMap,
    GVec3          backgroundColor,
    bool           hasBackgroundColor,
    int            num_active)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= num_active) return;
    if (path_alive[idx] == 0) return;

    // Check if this path missed (hit_t < 0)
    if (hit_t[idx] >= 0.f) return;

    // Reconstruct ray direction
    GVec3 dir(ray_direction[idx].x, ray_direction[idx].y, ray_direction[idx].z);
    dir = dir.normalized();

    // Sample environment / background
    GVec3 envColor(0.f);
    if (envMap.loaded) {
        envColor = gpu_envmap_lookup(envMap, dir);
    } else if (hasBackgroundColor) {
        envColor = backgroundColor;
    } else {
        // Default sky gradient (megakernel fallback, line 275-277)
        float t = 0.5f * (dir.y + 1.f);
        envColor = GVec3(1.f)*(1.f-t) + GVec3(0.5f, 0.7f, 1.f)*t;
        envColor *= 0.2f;
    }

    // Accumulate only if first bounce or after specular (megakernel line 279-280)
    if (was_specular[idx] != 0) {
        GVec3 tp(throughput[idx].x, throughput[idx].y, throughput[idx].z);
        GVec3 radiance = tp * envColor;

        float4 current_accum = accum_rgb[idx];
        current_accum.x += radiance.x;
        current_accum.y += radiance.y;
        current_accum.z += radiance.z;
        accum_rgb[idx] = current_accum;
    }

    // Terminate path (nothing more to trace)
    path_alive_out[idx] = 0;
}

}  // namespace

void launchStageMiss(
    IntegratorStateSoA& state,
    const GEnvMap& envMap,
    GVec3 backgroundColor, bool hasBackgroundColor)
{
    int n = state.num_active;
    if (n <= 0) return;

    int threads = 256;
    int blocks = (n + threads - 1) / threads;

    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_miss",
            (const void*)missKernel, blocks, threads);
        missKernel<<<blocks, threads>>>(
            state.hit_t,
            reinterpret_cast<const float4*>(state.ray_direction),
            reinterpret_cast<const float4*>(state.lambda),
            reinterpret_cast<const float4*>(state.throughput),
            reinterpret_cast<const float4*>(state.throughput_sp),
            state.path_alive,
            state.was_specular,
            reinterpret_cast<float4*>(state.accum_rgb),
            state.path_alive,
            envMap, backgroundColor, hasBackgroundColor,
            n);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_miss launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        cudaDeviceSynchronize();
    }
}

}  // namespace astroray::wavefront

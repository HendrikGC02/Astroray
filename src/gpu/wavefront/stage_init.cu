// stage_init.cu — pkg55 Phase A.1
//
// Wavefront primary-ray init stage. One thread per pixel slot; reads
// rng_state[slot], generates the same camera ray the AoS megakernel
// (path_trace_kernel.cu) would generate for sample 0 of that pixel,
// writes ray_origin / ray_direction / pixel_index / depth into the SoA.
//
// The whole point of using gpu_generateCameraRay() (defined in
// gpu_materials.h) here is that the AoS megakernel is a verbatim
// inline of the same math. Sharing the helper at minimum guarantees
// the two paths cannot drift; bit-identity follows by construction
// once we feed the same (px, py, &localRng) inputs in the same order.
//
// Reference (Apache-2.0):
//   - intern/cycles/kernel/integrator/init_from_camera.h —
//       integrator_init_from_camera() does exactly this: pulls rng,
//       samples lens + film, writes ray_P/ray_D into the SoA state.
//   - mmp/pbrt-v4 src/pbrt/wavefront/camera.cpp —
//       GenerateCameraRays() launches one thread per pixel and
//       enqueues a RayWorkItem with (origin, dir, pixelIndex).

#include "astroray/integrator_state_soa.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdio>
#include <stdexcept>

namespace astroray::wavefront {

namespace {

__global__ void stageInitKernel(
    // Decomposed SoA pointers (typed).
    float4*      ray_origin,
    float4*      ray_direction,
    int*         pixel_index,
    int*         sample_index,
    int*         depth,
    float*       pdf,
    float4*      throughput,
    curandState* rng_state,
    GCameraParams cam,
    int width, int height)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    int total = width * height;
    if (idx >= total) return;

    int px = idx % width;
    int py = idx / width;

    // Pull RNG by slot id == pixel id, exactly like the megakernel:
    //   path_trace_kernel.cu:368  curandState localRng = rngStates[pixelIdx];
    curandState localRng = rng_state[idx];

    // Camera ray. gpu_generateCameraRay() is the textbook inline of
    // path_trace_kernel.cu:372-380 — same UV math, same lens disk
    // sampling, same curand_uniform call order. Sharing the helper
    // here is what makes the AoS↔SoA hit-position parity bit-identical.
    GRay ray = gpu_generateCameraRay(cam, px, py, &localRng);

    // Persist advanced rng. Phase A.1 only does primary-ray init, so
    // 4 curand_uniform draws have been consumed (2 for jitter UV, 2
    // for the lens disk). The parity verifier uses a separate snapshot
    // buffer to recover the pre-advance state.
    rng_state[idx] = localRng;

    // SoA writes. float4 padding: w=0 documented in
    // include/astroray/integrator_state_soa.h.
    ray_origin[idx]    = make_float4(ray.origin.x,    ray.origin.y,    ray.origin.z,    0.f);
    ray_direction[idx] = make_float4(ray.direction.x, ray.direction.y, ray.direction.z, 0.f);
    throughput[idx]    = make_float4(1.f, 1.f, 1.f, 0.f);

    pixel_index[idx]  = idx;
    sample_index[idx] = 0;
    depth[idx]        = 0;
    pdf[idx]          = 1.f;
}

}  // namespace

void launchStageInit(
    IntegratorStateSoA& state,
    const GCameraParams& cam,
    int width, int height)
{
    int total = width * height;
    if (total <= 0 || state.capacity < total) {
        throw std::runtime_error(
            "wavefront::launchStageInit — SoA capacity smaller than pixel count");
    }
    int threads = 256;
    int blocks  = (total + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_init",
            (const void*)stageInitKernel, blocks, threads);
        stageInitKernel<<<blocks, threads>>>(
            reinterpret_cast<float4*>(state.ray_origin),
            reinterpret_cast<float4*>(state.ray_direction),
            state.pixel_index,
            state.sample_index,
            state.depth,
            state.pdf,
            reinterpret_cast<float4*>(state.throughput),
            reinterpret_cast<curandState*>(state.rng_state),
            cam, width, height);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_init launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        // pkg85-B: async runtime errors must not be silently discarded.
        cudaError_t syncErr = cudaDeviceSynchronize();
        if (syncErr != cudaSuccess) {
            std::fprintf(stderr, "stage_init runtime error: %s\n",
                         cudaGetErrorString(syncErr));
            throw std::runtime_error(cudaGetErrorString(syncErr));
        }
    }
    state.num_active = total;
}

}  // namespace astroray::wavefront

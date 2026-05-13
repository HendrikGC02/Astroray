// stage_terminate.cu — pkg55 Phase B
//
// Terminate stage: Russian roulette path termination, depth check, and final
// path state management. Runs at the end of each bounce iteration to prune
// low-contribution paths and mark exhausted paths as dead.
//
// Architecture: Cycles (blender/cycles @ c9227ff, Apache-2.0)
//   intern/cycles/kernel/integrator/path_state.h — Russian roulette +
//   path_flag termination logic.
//
// Russian roulette: standard Monte Carlo technique (Veach 1997 thesis §10.4).
//   Undergraduate-level MC (trivial per CLAUDE.md §6).

#include "astroray/integrator_state_soa.h"
#include "astroray/gpu_types.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdio>

namespace astroray::wavefront {

namespace {

__global__ void terminateKernel(
    const int*     depth,
    const float4*  throughput,
    uint8_t* path_alive,
    float4*  throughput_out,
    curandState* rng_state,
    int maxDepth,
    int rrDepth,
    int num_active)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= num_active) return;
    if (path_alive[idx] == 0) return;

    // Max depth termination
    if (depth[idx] >= maxDepth) {
        path_alive[idx] = 0;
        return;
    }

    // Russian roulette after rrDepth bounces (megakernel line 309-313)
    if (depth[idx] > rrDepth) {
        GVec3 tp(throughput[idx].x, throughput[idx].y, throughput[idx].z);
        float p = fminf(0.95f, luminance(tp));
        curandState localRng = rng_state[idx];
        float xi = curand_uniform(&localRng);
        rng_state[idx] = localRng;

        if (xi > p) {
            // Terminate path
            path_alive[idx] = 0;
        } else {
            // Continue with boosted throughput
            tp /= p;
            throughput_out[idx] = make_float4(tp.x, tp.y, tp.z, 0.f);
        }
    }
}

}  // namespace

void launchStageTerminate(IntegratorStateSoA& state, int maxDepth)
{
    int n = state.num_active;
    if (n <= 0) return;

    const int rrDepth = 3;  // matches megakernel (path_trace_kernel.cu line 257)

    int threads = 256;
    int blocks = (n + threads - 1) / threads;

    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_terminate",
            (const void*)terminateKernel, blocks, threads);
        terminateKernel<<<blocks, threads>>>(
            state.depth,
            reinterpret_cast<const float4*>(state.throughput),
            state.path_alive,
            reinterpret_cast<float4*>(state.throughput),
            reinterpret_cast<curandState*>(state.rng_state),
            maxDepth, rrDepth, n);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_terminate launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
        cudaDeviceSynchronize();
    }
}

}  // namespace astroray::wavefront

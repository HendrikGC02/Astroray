// queue_dispatch.cu — pkg55 Phase A.1
//
// Host-side allocation / free / dispatch for the wavefront SoA buffers
// declared in include/astroray/integrator_state_soa.h. The pkg55 spec
// names this queue_dispatch.cpp, but it has to allocate curandState
// arrays (sizeof needs curand_kernel.h) so it lives as a .cu. No other
// behavioural difference.
//
// Phase A.1 dispatch sequence (called from cuda_renderer.cu under the
// ASTRORAY_WAVEFRONT_INTERSECT build flag + ASTRORAY_WAVEFRONT_INTERSECT_PARITY
// env var):
//
//     1. Snapshot rng_state (cudaMemcpy d→d).
//     2. launchStageInit()       — reads rng, writes ray + advances rng.
//     3. launchStageIntersect()  — reads ray, writes hit_t/prim/mat.
//     4. launchIntersectParity() — re-traces from snapshot, traps on
//                                  mismatch.
//     5. Restore rng_state from snapshot so the AoS megakernel runs
//        bit-identically to the no-flag build.
//
// Reference (Apache-2.0):
//   - intern/cycles/integrator/path_trace_work_gpu.cpp::alloc_integrator_soa()
//   - mmp/pbrt-v4 src/pbrt/wavefront/integrator.cpp::WavefrontPathIntegrator
//     allocator pattern.

#include "astroray/integrator_state_soa.h"
#include "astroray/gpu_types.h"

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>

namespace astroray::wavefront {

namespace {

template<typename T>
static bool devAlloc(T** p, size_t n) {
    *p = nullptr;
    if (n == 0) return true;
    cudaError_t e = cudaMalloc(reinterpret_cast<void**>(p), n * sizeof(T));
    if (e != cudaSuccess) {
        std::fprintf(stderr, "[wavefront] cudaMalloc(%zu*%zu) failed: %s\n",
                     n, sizeof(T), cudaGetErrorString(e));
        return false;
    }
    return true;
}

static int concurrentPathsFactor() {
    // Cycles convention: CYCLES_CONCURRENT_STATES_FACTOR (default 16).
    // pkg55 spec §"Phase A — Key design decisions" point 1.
    const char* v = std::getenv("ASTRORAY_CONCURRENT_PATHS_FACTOR");
    if (!v || !v[0]) return 16;
    int n = std::atoi(v);
    return (n > 0) ? n : 16;
}

}  // namespace

bool allocateSoAState(IntegratorStateSoA& s, int capacity) {
    if (capacity <= 0) return false;

    // Phase A.1 only runs one slot per pixel (no compaction yet, see
    // pkg55 spec §"Phase A — Key design decisions" point 3). Reserve
    // headroom so Phase B's compaction can stretch into it without a
    // re-allocation: capacity * factor, factor configurable.
    int factor = concurrentPathsFactor();
    long long total = (long long)capacity * (long long)factor;
    if (total > (long long)INT32_MAX) total = (long long)INT32_MAX;
    int cap = (int)total;

    bool ok = true;
    ok &= devAlloc(reinterpret_cast<float4**>      (&s.ray_origin),    (size_t)cap);
    ok &= devAlloc(reinterpret_cast<float4**>      (&s.ray_direction), (size_t)cap);
    ok &= devAlloc(reinterpret_cast<float4**>      (&s.throughput),    (size_t)cap);
    ok &= devAlloc(&s.pdf,          (size_t)cap);
    ok &= devAlloc(&s.pixel_index,  (size_t)cap);
    ok &= devAlloc(&s.sample_index, (size_t)cap);
    ok &= devAlloc(&s.depth,        (size_t)cap);
    ok &= devAlloc(&s.hit_t,        (size_t)cap);
    ok &= devAlloc(&s.hit_prim,     (size_t)cap);
    ok &= devAlloc(&s.hit_mat,      (size_t)cap);
    ok &= devAlloc(&s.sort_key,     (size_t)cap);
    ok &= devAlloc(reinterpret_cast<curandState**>(&s.rng_state), (size_t)cap);

    if (!ok) {
        freeSoAState(s);
        return false;
    }
    s.capacity   = cap;
    s.num_active = 0;
    return true;
}

void freeSoAState(IntegratorStateSoA& s) {
    auto F = [](void*& p) { if (p) { cudaFree(p); p = nullptr; } };
    F(s.ray_origin);
    F(s.ray_direction);
    F(s.throughput);
    F(reinterpret_cast<void*&>(s.pdf));
    F(reinterpret_cast<void*&>(s.pixel_index));
    F(reinterpret_cast<void*&>(s.sample_index));
    F(reinterpret_cast<void*&>(s.depth));
    F(reinterpret_cast<void*&>(s.hit_t));
    F(reinterpret_cast<void*&>(s.hit_prim));
    F(reinterpret_cast<void*&>(s.hit_mat));
    F(reinterpret_cast<void*&>(s.sort_key));
    F(s.rng_state);
    s.capacity   = 0;
    s.num_active = 0;
    // pkg85-B: swallow any latent cudaFree error so it doesn't contaminate
    // the next CUDA call in production or the next test in the sweep.
    cudaGetLastError();
}

}  // namespace astroray::wavefront

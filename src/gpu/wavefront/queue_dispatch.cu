// queue_dispatch.cu — pkg55 Phases A.1 + B
//
// Host-side allocation / free for the wavefront SoA buffers.
// Phase A.1 allocates the minimal intersect-parity set.
// Phase B (ASTRORAY_WAVEFRONT_SHADE) additionally allocates shade geometry,
// spectral state, accumulation, and NEE shadow fields.
//
// References (Apache-2.0):
//   - intern/cycles/integrator/path_trace_work_gpu.cpp::alloc_integrator_soa()
//   - mmp/pbrt-v4 src/pbrt/wavefront/integrator.cpp WavefrontPathIntegrator
//     allocator pattern.

#include "astroray/integrator_state_soa.h"
#include "astroray/gpu_types.h"

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

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
    const char* v = std::getenv("ASTRORAY_CONCURRENT_PATHS_FACTOR");
    if (!v || !v[0]) return 16;
    int n = std::atoi(v);
    return (n > 0) ? n : 16;
}

}  // namespace

bool allocateSoAState(IntegratorStateSoA& s, int capacity) {
    if (capacity <= 0) return false;

    int factor = concurrentPathsFactor();
    long long total = (long long)capacity * (long long)factor;
    if (total > (long long)INT32_MAX) total = (long long)INT32_MAX;
    int cap = (int)total;

    bool ok = true;

    // --- Phase A.1 fields ---
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

#ifdef ASTRORAY_WAVEFRONT_SHADE
    // --- Phase B: shade geometry ---
    ok &= devAlloc(reinterpret_cast<float4**>(&s.hit_point),     (size_t)cap);
    ok &= devAlloc(reinterpret_cast<float4**>(&s.hit_normal),    (size_t)cap);
    ok &= devAlloc(reinterpret_cast<float4**>(&s.hit_tangent),   (size_t)cap);
    ok &= devAlloc(reinterpret_cast<float4**>(&s.hit_bitangent), (size_t)cap);
    ok &= devAlloc(&s.hit_flags,    (size_t)cap);
    ok &= devAlloc(&s.path_alive,   (size_t)cap);
    ok &= devAlloc(&s.was_specular, (size_t)cap);

    // --- Phase B: spectral ---
    ok &= devAlloc(reinterpret_cast<float4**>(&s.lambda),        (size_t)cap);
    ok &= devAlloc(reinterpret_cast<float4**>(&s.lambda_pdf),    (size_t)cap);
    ok &= devAlloc(reinterpret_cast<float4**>(&s.throughput_sp), (size_t)cap);

    // Accumulation buffer: one slot per path (indexed by slot, not pixel),
    // matching the shade kernels which write accum_rgb[idx] directly.
    // writeAccumulated maps slot→pixel via pixel_index[].
    ok &= devAlloc(reinterpret_cast<float4**>(&s.accum_rgb),     (size_t)cap);

    // --- Phase B: NEE shadow queue ---
    ok &= devAlloc(reinterpret_cast<float4**>(&s.nee_contrib),   (size_t)cap);
    ok &= devAlloc(reinterpret_cast<float4**>(&s.shadow_origin), (size_t)cap);
    ok &= devAlloc(reinterpret_cast<float4**>(&s.shadow_dir),    (size_t)cap);
    ok &= devAlloc(&s.shadow_tmax, (size_t)cap);
    ok &= devAlloc(&s.nee_active,  (size_t)cap);
#endif  // ASTRORAY_WAVEFRONT_SHADE

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
    // Phase A.1
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
    // Phase B
    F(s.hit_point);
    F(s.hit_normal);
    F(s.hit_tangent);
    F(s.hit_bitangent);
    F(reinterpret_cast<void*&>(s.hit_flags));
    F(reinterpret_cast<void*&>(s.path_alive));
    F(reinterpret_cast<void*&>(s.was_specular));
    F(s.lambda);
    F(s.lambda_pdf);
    F(s.throughput_sp);
    F(s.accum_rgb);
    F(s.nee_contrib);
    F(s.shadow_origin);
    F(s.shadow_dir);
    F(reinterpret_cast<void*&>(s.shadow_tmax));
    F(reinterpret_cast<void*&>(s.nee_active));
    s.capacity   = 0;
    s.num_active = 0;
}

}  // namespace astroray::wavefront

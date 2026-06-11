// wavefront_state.cu — pkg55-B' Session N+3
//
// GPU SoA state allocation/free for GPUWavefrontState (spectral + PCG32).
//
// This REPLACES the Phase A.1 queue_dispatch.cu (which allocated curandState + RGB).
// Session N+3 allocates WavefrontRNG (4 POD members) + spectral state
// (GSampledWavelengths + GSampledSpectrum) to match the CPU wavefront baseline.
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §4.2 Session N+3.

#include "astroray/gpu_wavefront_state.h"
#include <cuda_runtime.h>
#include <cstdio>

namespace astroray::wavefront {

bool allocateGPUWavefrontState(GPUWavefrontState& s, int capacity) {
    if (capacity <= 0) {
        std::fprintf(stderr, "allocateGPUWavefrontState: capacity %d invalid\n", capacity);
        return false;
    }

    s.capacity = capacity;
    s.num_active = 0;

    // Allocate all SoA arrays. Error handling: if any allocation fails,
    // free what we allocated so far and return false.
    #define ALLOC_CHECK(ptr, size) \
        if (cudaMalloc(&(ptr), (size)) != cudaSuccess) { \
            std::fprintf(stderr, "allocateGPUWavefrontState: cudaMalloc failed for " #ptr "\n"); \
            freeGPUWavefrontState(s); \
            return false; \
        }

    // Identity.
    ALLOC_CHECK(s.pixel_index,  capacity * sizeof(int));
    ALLOC_CHECK(s.sample_index, capacity * sizeof(int));
    ALLOC_CHECK(s.bounce,       capacity * sizeof(int));

    // WavefrontRNG state (4 POD members).
    ALLOC_CHECK(s.rng_pixel,     capacity * sizeof(uint32_t));
    ALLOC_CHECK(s.rng_sample,    capacity * sizeof(uint32_t));
    ALLOC_CHECK(s.rng_dimension, capacity * sizeof(uint32_t));
    ALLOC_CHECK(s.rng_seed,      capacity * sizeof(uint64_t));

    // Ray state.
    ALLOC_CHECK(s.ray_origin_x,    capacity * sizeof(float));
    ALLOC_CHECK(s.ray_origin_y,    capacity * sizeof(float));
    ALLOC_CHECK(s.ray_origin_z,    capacity * sizeof(float));
    ALLOC_CHECK(s.ray_direction_x, capacity * sizeof(float));
    ALLOC_CHECK(s.ray_direction_y, capacity * sizeof(float));
    ALLOC_CHECK(s.ray_direction_z, capacity * sizeof(float));

    // Spectral state (GSampledWavelengths = 8 floats).
    ALLOC_CHECK(s.lambda_0,     capacity * sizeof(float));
    ALLOC_CHECK(s.lambda_1,     capacity * sizeof(float));
    ALLOC_CHECK(s.lambda_2,     capacity * sizeof(float));
    ALLOC_CHECK(s.lambda_3,     capacity * sizeof(float));
    ALLOC_CHECK(s.lambda_pdf_0, capacity * sizeof(float));
    ALLOC_CHECK(s.lambda_pdf_1, capacity * sizeof(float));
    ALLOC_CHECK(s.lambda_pdf_2, capacity * sizeof(float));
    ALLOC_CHECK(s.lambda_pdf_3, capacity * sizeof(float));

    // GSampledSpectrum throughput = 4 floats.
    ALLOC_CHECK(s.throughput_0, capacity * sizeof(float));
    ALLOC_CHECK(s.throughput_1, capacity * sizeof(float));
    ALLOC_CHECK(s.throughput_2, capacity * sizeof(float));
    ALLOC_CHECK(s.throughput_3, capacity * sizeof(float));

    // GSampledSpectrum color = 4 floats.
    ALLOC_CHECK(s.color_0, capacity * sizeof(float));
    ALLOC_CHECK(s.color_1, capacity * sizeof(float));
    ALLOC_CHECK(s.color_2, capacity * sizeof(float));
    ALLOC_CHECK(s.color_3, capacity * sizeof(float));

    // Path-continuation flags.
    ALLOC_CHECK(s.was_specular, capacity * sizeof(int));
    ALLOC_CHECK(s.path_alive,   capacity * sizeof(int));

    #undef ALLOC_CHECK

    return true;
}

void freeGPUWavefrontState(GPUWavefrontState& s) {
    // cudaFree accepts nullptr gracefully; no need to guard each pointer.
    cudaFree(s.pixel_index);
    cudaFree(s.sample_index);
    cudaFree(s.bounce);

    cudaFree(s.rng_pixel);
    cudaFree(s.rng_sample);
    cudaFree(s.rng_dimension);
    cudaFree(s.rng_seed);

    cudaFree(s.ray_origin_x);
    cudaFree(s.ray_origin_y);
    cudaFree(s.ray_origin_z);
    cudaFree(s.ray_direction_x);
    cudaFree(s.ray_direction_y);
    cudaFree(s.ray_direction_z);

    cudaFree(s.lambda_0);
    cudaFree(s.lambda_1);
    cudaFree(s.lambda_2);
    cudaFree(s.lambda_3);
    cudaFree(s.lambda_pdf_0);
    cudaFree(s.lambda_pdf_1);
    cudaFree(s.lambda_pdf_2);
    cudaFree(s.lambda_pdf_3);

    cudaFree(s.throughput_0);
    cudaFree(s.throughput_1);
    cudaFree(s.throughput_2);
    cudaFree(s.throughput_3);

    cudaFree(s.color_0);
    cudaFree(s.color_1);
    cudaFree(s.color_2);
    cudaFree(s.color_3);

    cudaFree(s.was_specular);
    cudaFree(s.path_alive);

    // Zero out all pointers.
    s = GPUWavefrontState{};
}

// Session N+3 part 2: Hit buffer allocation.
bool allocateGPUWavefrontHitBuffers(GPUWavefrontHitBuffers& hb, int capacity) {
    if (capacity <= 0) {
        std::fprintf(stderr, "allocateGPUWavefrontHitBuffers: capacity %d invalid\n", capacity);
        return false;
    }

    #define ALLOC_CHECK(ptr, size) \
        if (cudaMalloc(&(ptr), (size)) != cudaSuccess) { \
            std::fprintf(stderr, "allocateGPUWavefrontHitBuffers: cudaMalloc failed for " #ptr "\n"); \
            freeGPUWavefrontHitBuffers(hb); \
            return false; \
        }

    ALLOC_CHECK(hb.hit_t,          capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_point_x,    capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_point_y,    capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_point_z,    capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_normal_x,   capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_normal_y,   capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_normal_z,   capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_tangent_x,  capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_tangent_y,  capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_tangent_z,  capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_bitangent_x, capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_bitangent_y, capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_bitangent_z, capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_material_id, capacity * sizeof(int));
    ALLOC_CHECK(hb.hit_prim_id,     capacity * sizeof(int));
    ALLOC_CHECK(hb.hit_front_face,  capacity * sizeof(int));
    ALLOC_CHECK(hb.hit_is_delta,    capacity * sizeof(int));
    ALLOC_CHECK(hb.hit_valid,       capacity * sizeof(int));

    #undef ALLOC_CHECK

    return true;
}

void freeGPUWavefrontHitBuffers(GPUWavefrontHitBuffers& hb) {
    cudaFree(hb.hit_t);
    cudaFree(hb.hit_point_x);
    cudaFree(hb.hit_point_y);
    cudaFree(hb.hit_point_z);
    cudaFree(hb.hit_normal_x);
    cudaFree(hb.hit_normal_y);
    cudaFree(hb.hit_normal_z);
    cudaFree(hb.hit_tangent_x);
    cudaFree(hb.hit_tangent_y);
    cudaFree(hb.hit_tangent_z);
    cudaFree(hb.hit_bitangent_x);
    cudaFree(hb.hit_bitangent_y);
    cudaFree(hb.hit_bitangent_z);
    cudaFree(hb.hit_material_id);
    cudaFree(hb.hit_prim_id);
    cudaFree(hb.hit_front_face);
    cudaFree(hb.hit_is_delta);
    cudaFree(hb.hit_valid);

    hb = GPUWavefrontHitBuffers{};
}

}  // namespace astroray::wavefront

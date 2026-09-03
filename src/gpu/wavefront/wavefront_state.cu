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
    ALLOC_CHECK(s.path_time,       capacity * sizeof(float));  // pkg55-C4

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

    // pkg55-C2 MIS audit instrumentation (see gpu_wavefront_state.h). Additive
    // per-path scalars; written by shadePathSlot's NEE branch, read only by the
    // PostNEE_MIS snapshot. Never read by accumulation -> renders bit-identical.
    ALLOC_CHECK(s.path_light_pdf,  capacity * sizeof(float));
    ALLOC_CHECK(s.path_mis_pdf,    capacity * sizeof(float));
    ALLOC_CHECK(s.path_mis_weight, capacity * sizeof(float));
    ALLOC_CHECK(s.path_bsdf_pdf,   capacity * sizeof(float));  // pkg120

    // pkg55-C5 / pkg113: photon caustic XYZ contribution (see gpu_wavefront_state.h).
    // Written by shadePathSlot at bounce==0 when hasPhotonGrid, read by stageRegenKernel
    // to add to accum_xyz. Zero for paths that don't hit photons.
    ALLOC_CHECK(s.photon_xyz_x, capacity * sizeof(float));
    ALLOC_CHECK(s.photon_xyz_y, capacity * sizeof(float));
    ALLOC_CHECK(s.photon_xyz_z, capacity * sizeof(float));

    // pkg201 Stage 3 (Finding A) — packed per-type bounce counters.
    ALLOC_CHECK(s.per_type_bounce, capacity * sizeof(uint32_t));
    // pkg201 Stage 3 (Finding E) — sticky diffuse-ancestor flag.
    ALLOC_CHECK(s.had_diffuse_ancestor, capacity * sizeof(int));

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
    cudaFree(s.path_time);  // pkg55-C4

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

    cudaFree(s.path_light_pdf);
    cudaFree(s.path_mis_pdf);
    cudaFree(s.path_mis_weight);
    cudaFree(s.path_bsdf_pdf);  // pkg120

    cudaFree(s.photon_xyz_x);  // pkg55-C5
    cudaFree(s.photon_xyz_y);
    cudaFree(s.photon_xyz_z);

    cudaFree(s.per_type_bounce);       // pkg201 Stage 3 (A)
    cudaFree(s.had_diffuse_ancestor);  // pkg201 Stage 3 (E)
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
    // pkg225 Stage 4 — hair strand-tangent + azimuthal-v hand-off lanes.
    ALLOC_CHECK(hb.hit_uv_tangent_x, capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_uv_tangent_y, capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_uv_tangent_z, capacity * sizeof(float));
    ALLOC_CHECK(hb.hit_hair_v,       capacity * sizeof(float));

    #undef ALLOC_CHECK

    return true;
}

// ---------------------------------------------------------------------------
// pkg55-C6b / pkg24: ReSTIR reservoir SoA (per-pixel, double-buffered).
// ---------------------------------------------------------------------------
bool allocateGPUReservoirSoA(GPUReservoirSoA& r, int numPixels) {
    if (numPixels <= 0) {
        std::fprintf(stderr, "allocateGPUReservoirSoA: numPixels %d invalid\n", numPixels);
        return false;
    }
    r.numPixels = numPixels;

    #define ALLOC_CHECK(ptr, size) \
        if (cudaMalloc(&(ptr), (size)) != cudaSuccess) { \
            std::fprintf(stderr, "allocateGPUReservoirSoA: cudaMalloc failed for " #ptr "\n"); \
            freeGPUReservoirSoA(r); \
            return false; \
        }

    const size_t nf = size_t(numPixels) * sizeof(float);
    const size_t ni = size_t(numPixels) * sizeof(int);

    ALLOC_CHECK(r.res_y_pos_x,      nf);
    ALLOC_CHECK(r.res_y_pos_y,      nf);
    ALLOC_CHECK(r.res_y_pos_z,      nf);
    ALLOC_CHECK(r.res_y_normal_x,   nf);
    ALLOC_CHECK(r.res_y_normal_y,   nf);
    ALLOC_CHECK(r.res_y_normal_z,   nf);
    ALLOC_CHECK(r.res_y_emission_x, nf);
    ALLOC_CHECK(r.res_y_emission_y, nf);
    ALLOC_CHECK(r.res_y_emission_z, nf);
    ALLOC_CHECK(r.res_y_pdf,        nf);
    ALLOC_CHECK(r.res_y_distance,   nf);
    ALLOC_CHECK(r.res_w_sum,        nf);
    ALLOC_CHECK(r.res_M,            ni);
    ALLOC_CHECK(r.res_W,            nf);
    ALLOC_CHECK(r.meta_normal_x,    nf);
    ALLOC_CHECK(r.meta_normal_y,    nf);
    ALLOC_CHECK(r.meta_normal_z,    nf);
    ALLOC_CHECK(r.meta_depth,       nf);
    ALLOC_CHECK(r.meta_valid,       ni);

    #undef ALLOC_CHECK

    clearGPUReservoirSoA(r);
    return true;
}

void clearGPUReservoirSoA(GPUReservoirSoA& r) {
    if (r.numPixels <= 0) return;
    const size_t nf = size_t(r.numPixels) * sizeof(float);
    const size_t ni = size_t(r.numPixels) * sizeof(int);
    // Zero == the CPU Reservoir{}/PixelHistory{} default (y=0, w_sum=0, M=0,
    // W=0; meta_valid=0). meta_normal default (0,0,1) is not reproduced by a
    // memset, but a pixel with meta_valid=0 is never read by isTemporallyValid.
    cudaMemset(r.res_y_pos_x,      0, nf);
    cudaMemset(r.res_y_pos_y,      0, nf);
    cudaMemset(r.res_y_pos_z,      0, nf);
    cudaMemset(r.res_y_normal_x,   0, nf);
    cudaMemset(r.res_y_normal_y,   0, nf);
    cudaMemset(r.res_y_normal_z,   0, nf);
    cudaMemset(r.res_y_emission_x, 0, nf);
    cudaMemset(r.res_y_emission_y, 0, nf);
    cudaMemset(r.res_y_emission_z, 0, nf);
    cudaMemset(r.res_y_pdf,        0, nf);
    cudaMemset(r.res_y_distance,   0, nf);
    cudaMemset(r.res_w_sum,        0, nf);
    cudaMemset(r.res_M,            0, ni);
    cudaMemset(r.res_W,            0, nf);
    cudaMemset(r.meta_normal_x,    0, nf);
    cudaMemset(r.meta_normal_y,    0, nf);
    cudaMemset(r.meta_normal_z,    0, nf);
    cudaMemset(r.meta_depth,       0, nf);
    cudaMemset(r.meta_valid,       0, ni);
}

void freeGPUReservoirSoA(GPUReservoirSoA& r) {
    cudaFree(r.res_y_pos_x);
    cudaFree(r.res_y_pos_y);
    cudaFree(r.res_y_pos_z);
    cudaFree(r.res_y_normal_x);
    cudaFree(r.res_y_normal_y);
    cudaFree(r.res_y_normal_z);
    cudaFree(r.res_y_emission_x);
    cudaFree(r.res_y_emission_y);
    cudaFree(r.res_y_emission_z);
    cudaFree(r.res_y_pdf);
    cudaFree(r.res_y_distance);
    cudaFree(r.res_w_sum);
    cudaFree(r.res_M);
    cudaFree(r.res_W);
    cudaFree(r.meta_normal_x);
    cudaFree(r.meta_normal_y);
    cudaFree(r.meta_normal_z);
    cudaFree(r.meta_depth);
    cudaFree(r.meta_valid);
    r = GPUReservoirSoA{};
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
    cudaFree(hb.hit_uv_tangent_x);  // pkg225 Stage 4
    cudaFree(hb.hit_uv_tangent_y);
    cudaFree(hb.hit_uv_tangent_z);
    cudaFree(hb.hit_hair_v);

    hb = GPUWavefrontHitBuffers{};
}

}  // namespace astroray::wavefront

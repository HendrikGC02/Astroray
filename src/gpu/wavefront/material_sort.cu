// material_sort.cu — pkg55 Phase B
//
// CUB DeviceRadixSort on sort_key[] after stage_intersect_full. Dead paths
// (key=0) sort to the front; live paths are grouped by materialId.
// Shade kernels iterate over the sorted array and filter by hit_mat type.
//
// Sort key encoding (from stage_intersect_full.cu):
//   bit 31  = alive (1=live, 0=dead)
//   bits 0-23 = materialId
// Ascending CUB sort → dead (0) first, live sorted by materialId.
//
// References (Apache-2.0):
//   - Laine, Karras, Aila 2013 §4 (HPG, DOI 10.1145/2492045.2492060):
//     sort-by-material for warp coherence.
//   - Cycles intern/cycles/kernel/integrator/shade_surface.h: per-material
//     dispatch after sort.
//   - CUB DeviceRadixSort (BSD-3-Clause, NVIDIA/cub):
//     https://nvlabs.github.io/cub/structcub_1_1_device_radix_sort.html

#include "astroray/integrator_state_soa.h"
#include "astroray/gpu_types.h"

#include <cuda_runtime.h>
#include <cub/cub.cuh>
#include <cstdio>

namespace astroray::wavefront {

// ---------------------------------------------------------------------------
// sortScratchBytes — query CUB for required temp buffer size.
// Pass d_temp=nullptr to get the size; then allocate and pass to sortByMaterial.
// ---------------------------------------------------------------------------
size_t sortScratchBytes(int n) {
    if (n <= 0) return 0;
    size_t needed = 0;
    cub::DeviceRadixSort::SortKeys(
        nullptr, needed,
        static_cast<uint32_t*>(nullptr),
        static_cast<uint32_t*>(nullptr),
        n);
    return needed;
}

// ---------------------------------------------------------------------------
// sortByMaterial — in-place radix sort on state.sort_key[0..n-1].
// Requires a caller-allocated scratch buffer of size >= sortScratchBytes(n).
// Uses a temporary device buffer for the sort output, then copies back.
// ---------------------------------------------------------------------------
void sortByMaterial(IntegratorStateSoA& state, void* d_temp, size_t temp_bytes) {
    int n = state.num_active;
    if (n <= 0) return;

    // CUB SortKeys needs separate in/out arrays.
    uint32_t* d_keys_out = nullptr;
    cudaError_t e = cudaMalloc(&d_keys_out, (size_t)n * sizeof(uint32_t));
    if (e != cudaSuccess) {
        std::fprintf(stderr, "[material_sort] temp alloc failed: %s\n",
                     cudaGetErrorString(e));
        return;
    }

    e = cub::DeviceRadixSort::SortKeys(
        d_temp, temp_bytes,
        state.sort_key, d_keys_out,
        n);
    if (e != cudaSuccess) {
        std::fprintf(stderr, "[material_sort] CUB sort failed: %s\n",
                     cudaGetErrorString(e));
        cudaFree(d_keys_out);
        return;
    }

    // Copy sorted result back (keys only; SoA fields accessed via indirection
    // through hit_mat — each shade kernel filters by d_mats[hit_mat[i]].type).
    e = cudaMemcpy(state.sort_key, d_keys_out,
                   (size_t)n * sizeof(uint32_t), cudaMemcpyDeviceToDevice);
    cudaFree(d_keys_out);
    if (e != cudaSuccess) {
        std::fprintf(stderr, "[material_sort] memcpy back failed: %s\n",
                     cudaGetErrorString(e));
    }
}

}  // namespace astroray::wavefront

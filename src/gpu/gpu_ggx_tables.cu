// gpu_ggx_tables.cu — pkg152.
//
// Definitions for the reflection-lobe (metal / dielectric-specular / sheen /
// clearcoat) multi-scatter tables declared in
// include/astroray/gpu_ggx_tables.cuh. Uploads the same host-side data
// astroray::DisneyEnergyCompensationTables loads from
// data/disney_compensation/{ggx,sheen,clearcoat}_E*.bin (Cycles
// shader.tables, Apache-2.0) into device global memory, mirroring the
// pkg151 gpu_glass_tables.cu upload pattern exactly.

#include "astroray/gpu_ggx_tables.cuh"
#include "astroray/energy_compensation.h"

#include <cuda_runtime.h>
#include <cstddef>
#include <cstdio>
#include <stdexcept>

__device__ const float* g_ggxE       = nullptr;
__device__ const float* g_ggxEavg    = nullptr;
__device__ const float* g_sheenE     = nullptr;
__device__ const float* g_clearcoatE = nullptr;

// Host-side ownership of the device allocations; freed only on process exit
// (read-only tables, re-uploading would be wasteful) — same lifetime policy
// as gpu_glass_tables.cu's s_ggxGlass*Dev.
static float* s_ggxEDev       = nullptr;
static float* s_ggxEavgDev    = nullptr;
static float* s_sheenEDev     = nullptr;
static float* s_clearcoatEDev = nullptr;

static void uploadOneTable(const float* host, int count, float** devPtr,
                            const float** symbolPtr, const char* name) {
    size_t bytes = size_t(count) * sizeof(float);
    cudaError_t e = cudaMalloc(reinterpret_cast<void**>(devPtr), bytes);
    if (e == cudaSuccess) {
        e = cudaMemcpy(*devPtr, host, bytes, cudaMemcpyHostToDevice);
    }
    if (e == cudaSuccess) {
        e = cudaMemcpyToSymbol(*symbolPtr, devPtr, sizeof(float*));
    }
    if (e != cudaSuccess) {
        fprintf(stderr, "uploadGgxTables (%s) failed: %s\n",
                name, cudaGetErrorString(e));
        throw std::runtime_error(cudaGetErrorString(e));
    }
}

void uploadGgxTables() {
    static bool uploaded = false;
    if (uploaded) return;

    const auto& tables = astroray::DisneyEnergyCompensationTables::instance();
    if (!tables.loaded()) {
        // Mirrors the CPU-side graceful no-op: leave the device pointers
        // null; gpu_ggxCompensationFactor/gpu_ggxDirectionalAlbedo return
        // identity (1.0 / Fview passthrough) if these pointers are null,
        // matching CPU disney.cpp's `tables.loaded()` guard.
        return;
    }

    constexpr int kGgxSize2D       = G_GGX_TABLE_SIZE * G_GGX_TABLE_SIZE;
    constexpr int kGgxSize1D       = G_GGX_TABLE_SIZE;
    constexpr int kSheenSize2D     = G_SHEEN_TABLE_SIZE * G_SHEEN_TABLE_SIZE;
    constexpr int kClearcoatSize1D = G_CLEARCOAT_TABLE_SIZE;

    uploadOneTable(tables.ggxEData(), kGgxSize2D, &s_ggxEDev,
                   &g_ggxE, "ggxE");
    uploadOneTable(tables.ggxEavgData(), kGgxSize1D, &s_ggxEavgDev,
                   &g_ggxEavg, "ggxEavg");
    uploadOneTable(tables.sheenEData(), kSheenSize2D, &s_sheenEDev,
                   &g_sheenE, "sheenE");
    uploadOneTable(tables.clearcoatEData(), kClearcoatSize1D, &s_clearcoatEDev,
                   &g_clearcoatE, "clearcoatE");

    uploaded = true;
}

// gpu_glass_tables.cu — pkg151.
//
// Definitions for the glass (rough dielectric transmission) multi-scatter
// tables declared in include/astroray/gpu_glass_tables.cuh. Uploads the same
// host-side data astroray::DisneyEnergyCompensationTables loads from
// data/disney_compensation/ggx_glass_{E,Eavg,inv_E,inv_Eavg}.bin (Cycles
// shader.tables, Apache-2.0) into device global memory, mirroring the
// Jakob-Hanika LUT upload pattern in src/gpu/gpu_spectral_tables.cu.

#include "astroray/gpu_glass_tables.cuh"
#include "astroray/energy_compensation.h"

#include <cuda_runtime.h>
#include <cstddef>
#include <cstdio>
#include <stdexcept>

__device__ const float* g_ggxGlassE       = nullptr;
__device__ const float* g_ggxGlassEavg    = nullptr;
__device__ const float* g_ggxGlassInvE    = nullptr;
__device__ const float* g_ggxGlassInvEavg = nullptr;

// Host-side ownership of the device allocations; freed only on process exit
// (read-only tables, re-uploading would be wasteful) — same lifetime policy
// as s_jhLutScaleDev/s_jhLutCoeffsDev.
static float* s_ggxGlassEDev       = nullptr;
static float* s_ggxGlassEavgDev    = nullptr;
static float* s_ggxGlassInvEDev    = nullptr;
static float* s_ggxGlassInvEavgDev = nullptr;

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
        fprintf(stderr, "uploadGgxGlassTables (%s) failed: %s\n",
                name, cudaGetErrorString(e));
        throw std::runtime_error(cudaGetErrorString(e));
    }
}

void uploadGgxGlassTables() {
    static bool uploaded = false;
    if (uploaded) return;

    const auto& tables = astroray::DisneyEnergyCompensationTables::instance();
    if (!tables.loaded()) {
        // Mirrors the CPU-side graceful no-op: leave the device pointers
        // null; gpu_ggxGlassCompensationFactor is never called if the caller
        // guards on the same "tables not loaded" condition. CPU disney.cpp
        // guards via tables.loaded(); the GPU mirror below guards
        // analogously in gpu_disney_roughTransmissionEval.
        return;
    }

    constexpr int kSize3D = G_GLASS_TABLE_SIZE * G_GLASS_TABLE_SIZE * G_GLASS_TABLE_SIZE;
    constexpr int kSize2D = G_GLASS_TABLE_SIZE * G_GLASS_TABLE_SIZE;

    uploadOneTable(tables.ggxGlassEData(), kSize3D, &s_ggxGlassEDev,
                   &g_ggxGlassE, "ggxGlassE");
    uploadOneTable(tables.ggxGlassEavgData(), kSize2D, &s_ggxGlassEavgDev,
                   &g_ggxGlassEavg, "ggxGlassEavg");
    uploadOneTable(tables.ggxGlassInvEData(), kSize3D, &s_ggxGlassInvEDev,
                   &g_ggxGlassInvE, "ggxGlassInvE");
    uploadOneTable(tables.ggxGlassInvEavgData(), kSize2D, &s_ggxGlassInvEavgDev,
                   &g_ggxGlassInvEavg, "ggxGlassInvEavg");

    uploaded = true;
}

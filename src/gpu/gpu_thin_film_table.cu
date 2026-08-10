// gpu_thin_film_table.cu — pkg178 Stage 4 PR-3.
//
// Definition + one-time upload for the thin-film CIE sensitivity table declared
// in include/astroray/gpu_thin_film_table.cuh. Copies the Rec.709-baked
// astroray::thinfilm::kThinFilmCieTable ([512][6], thin_film_cie_table.h) into
// device global memory, mirroring the pkg152 gpu_ggx_tables.cu upload pattern
// exactly (same data/citations: Cycles table_thin_film_cmf, Apache-2.0;
// Belcour & Barla 2017).

#include "astroray/gpu_thin_film_table.cuh"
#include "astroray/thin_film_cie_table.h"

#include <cuda_runtime.h>
#include <cstddef>
#include <cstdio>
#include <stdexcept>

__device__ const float* g_thinFilmCie = nullptr;

// Host-side ownership of the device allocation; freed only on process exit
// (read-only table, re-uploading would be wasteful) — same lifetime policy as
// gpu_ggx_tables.cu's s_ggxEDev.
static float* s_thinFilmCieDev = nullptr;

void uploadThinFilmTable() {
    static bool uploaded = false;
    if (uploaded) return;

    constexpr int kCount = astroray::thinfilm::kThinFilmTableSize * 6;  // 512*6
    const size_t bytes = size_t(kCount) * sizeof(float);
    // kThinFilmCieTable is [512][6] contiguous — flatten row-major.
    const float* host = &astroray::thinfilm::kThinFilmCieTable[0][0];

    cudaError_t e = cudaMalloc(reinterpret_cast<void**>(&s_thinFilmCieDev), bytes);
    if (e == cudaSuccess) {
        e = cudaMemcpy(s_thinFilmCieDev, host, bytes, cudaMemcpyHostToDevice);
    }
    if (e == cudaSuccess) {
        e = cudaMemcpyToSymbol(g_thinFilmCie, &s_thinFilmCieDev, sizeof(float*));
    }
    if (e != cudaSuccess) {
        fprintf(stderr, "uploadThinFilmTable failed: %s\n", cudaGetErrorString(e));
        throw std::runtime_error(cudaGetErrorString(e));
    }

    uploaded = true;
}

// photon_store.cu — pkg113 Phase 1 — GPU photon STORE + query.
//
// Uniform spatial hash grid over photons (pbrt-v3 sppm.cpp, BSD-2-Clause) with a
// device-side fixed-radius gather (Jensen 2000 §3.1 Eq. 8). STORE + QUERY only —
// no emission/bounce (Phase 2), no integrator gather wiring (Phase 3).
//
// See include/astroray/gpu_photon_store.h for the store decision + citations and
// .astroray_plan/docs/pkg113-gpu-photon-store-research.md for the reference math.
//
// The grid is BUILT ON THE GPU: a counting pass (atomicAdd into per-bucket
// counts) + a prefix sum (host scan of the small hashSize array) + a scatter
// pass (atomic cursor per bucket) produce the CSR layout. This mirrors the
// standard parallel uniform-grid build (pbrt-v4 wavefront SPPM does the same
// count/scan/scatter); for Phase 1 the prefix scan over the hashSize-length
// array runs on the host (hashSize ~ numPhotons, trivially small for the
// parity-harness sizes).

#include "astroray/gpu_photon_store.h"
#include "astroray/gpu_types.h"

#include <cuda_runtime.h>

#include <algorithm>
#include <cstdio>
#include <stdexcept>
#include <vector>

#define APH_CUDA_CHECK(call) do {                                           \
    cudaError_t _e = (call);                                                \
    if (_e != cudaSuccess) {                                                \
        std::fprintf(stderr, "CUDA error at %s:%d: %s\n",                  \
                __FILE__, __LINE__, cudaGetErrorString(_e));                \
        throw std::runtime_error(cudaGetErrorString(_e));                   \
    }                                                                       \
} while(0)

namespace astroray {
namespace photon {
namespace gpu {

namespace {

// Counting pass: each photon hashes its cell and atomically bumps the bucket
// count. pbrt-v3 sppm.cpp does the equivalent under its grid mutex; on the GPU
// we use atomicAdd (the canonical parallel counting-sort histogram).
__global__ void kCountPhotons(const GPhoton* photons, int numPhotons,
                              GAABB bounds, int gridX, int gridY, int gridZ,
                              int hashSize, int* cellCount) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= numPhotons) return;
    int res[3] = {gridX, gridY, gridZ};
    int cell[3];
    photonToGrid(photons[i].position, bounds, res, cell);
    unsigned int h = photonHash(cell[0], cell[1], cell[2], hashSize);
    atomicAdd(&cellCount[h], 1);
}

// Scatter pass: each photon writes its index into photonIndex[] at the bucket's
// running cursor (cellStart[h] + atomic offset), and the parallel
// photonCellId[] entry records its flattened cell id (so the gather can reject
// hash-collided foreign photons). Counting-sort scatter.
__global__ void kScatterPhotons(const GPhoton* photons, int numPhotons,
                                GAABB bounds, int gridX, int gridY, int gridZ,
                                int hashSize, const int* cellStart,
                                int* cellCursor, int* photonIndex,
                                int* photonCellId) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= numPhotons) return;
    int res[3] = {gridX, gridY, gridZ};
    int cell[3];
    photonToGrid(photons[i].position, bounds, res, cell);
    unsigned int h = photonHash(cell[0], cell[1], cell[2], hashSize);
    int slot = atomicAdd(&cellCursor[h], 1);
    int dst = cellStart[h] + slot;
    photonIndex[dst] = i;
    photonCellId[dst] = photonCellFlatten(cell[0], cell[1], cell[2], res);
}

// Query kernel: one thread per query point. Calls the shared device gather
// helper (the same code a Phase-3 integrator kernel will call) and writes the
// density estimate + neighbor indices + count back to global memory.
__global__ void kQuery(GPhotonGrid grid, const GVec3* queries, int numQueries,
                       int maxNeighbors, GVec3* outE, int* outIdx,
                       int* outFound, int* outWritten) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= numQueries) return;
    GVec3 e;
    int found = 0;
    int written = photonGridGather(grid, queries[i], e,
                                   outIdx + (size_t)i * maxNeighbors,
                                   maxNeighbors, found);
    outE[i] = e;
    outFound[i] = found;
    outWritten[i] = written;
}

}  // namespace

std::vector<PhotonStoreQueryResult> cuda_photon_store_query(
    const std::vector<GPhoton>& photons,
    const std::vector<GVec3>&   queries,
    float                       radius,
    int                         maxNeighborsPerQuery) {

    const int n = static_cast<int>(photons.size());
    const int nq = static_cast<int>(queries.size());
    std::vector<PhotonStoreQueryResult> results(nq);
    if (n == 0 || nq == 0 || radius <= 0.f) {
        for (auto& r : results) { r.irradiance = GVec3(0.f); r.foundCount = 0; }
        return results;
    }
    const int maxOut = std::max(1, maxNeighborsPerQuery);

    // --- Grid AABB: photon extent padded by one radius so the 3x3x3 neighbor
    // sweep around any query point inside the padded box stays in range. pbrt
    // pads the visible-point grid bounds by maxRadius the same way. ---
    GVec3 mn = photons[0].position, mx = photons[0].position;
    for (int i = 1; i < n; ++i) {
        mn = gvec3_min(mn, photons[i].position);
        mx = gvec3_max(mx, photons[i].position);
    }
    GVec3 pad(radius);
    GAABB bounds; bounds.min = mn - pad; bounds.max = mx + pad;

    // --- gridRes from the AABB diagonal and radius (pbrt-v3 sppm.cpp). ---
    GVec3 diag = bounds.max - bounds.min;
    float maxDiag = diag.maxComponent();
    int baseGridRes = std::max(1, static_cast<int>(maxDiag / radius));
    int gridRes[3];
    for (int i = 0; i < 3; ++i)
        gridRes[i] = std::max(static_cast<int>(baseGridRes * diag[i] / maxDiag), 1);
    const int hashSize = n;  // pbrt uses hashSize = number of items in the grid

    // --- Upload photons + queries. ---
    GPhoton* d_photons = nullptr;
    GVec3*   d_queries = nullptr;
    APH_CUDA_CHECK(cudaMalloc(&d_photons, (size_t)n * sizeof(GPhoton)));
    APH_CUDA_CHECK(cudaMemcpy(d_photons, photons.data(),
                              (size_t)n * sizeof(GPhoton), cudaMemcpyHostToDevice));
    APH_CUDA_CHECK(cudaMalloc(&d_queries, (size_t)nq * sizeof(GVec3)));
    APH_CUDA_CHECK(cudaMemcpy(d_queries, queries.data(),
                              (size_t)nq * sizeof(GVec3), cudaMemcpyHostToDevice));

    // --- Grid CSR buffers. ---
    int* d_cellCount  = nullptr;
    int* d_cellStart  = nullptr;
    int* d_cellCursor = nullptr;
    int* d_photonIndex = nullptr;
    int* d_photonCellId = nullptr;
    APH_CUDA_CHECK(cudaMalloc(&d_cellCount,  (size_t)hashSize * sizeof(int)));
    APH_CUDA_CHECK(cudaMalloc(&d_cellStart,  (size_t)hashSize * sizeof(int)));
    APH_CUDA_CHECK(cudaMalloc(&d_cellCursor, (size_t)hashSize * sizeof(int)));
    APH_CUDA_CHECK(cudaMalloc(&d_photonIndex, (size_t)n * sizeof(int)));
    APH_CUDA_CHECK(cudaMalloc(&d_photonCellId, (size_t)n * sizeof(int)));
    APH_CUDA_CHECK(cudaMemset(d_cellCount, 0, (size_t)hashSize * sizeof(int)));

    const int TPB = 256;
    const int photonBlocks = (n + TPB - 1) / TPB;

    // --- Count pass. ---
    kCountPhotons<<<photonBlocks, TPB>>>(d_photons, n, bounds,
                                         gridRes[0], gridRes[1], gridRes[2],
                                         hashSize, d_cellCount);
    APH_CUDA_CHECK(cudaGetLastError());

    // --- Exclusive prefix sum over the hashSize counts (host scan — hashSize
    // is tiny for the harness; a device scan is a Phase-3 perf concern). ---
    std::vector<int> h_count(hashSize);
    APH_CUDA_CHECK(cudaMemcpy(h_count.data(), d_cellCount,
                              (size_t)hashSize * sizeof(int), cudaMemcpyDeviceToHost));
    std::vector<int> h_start(hashSize);
    int acc = 0;
    for (int i = 0; i < hashSize; ++i) { h_start[i] = acc; acc += h_count[i]; }
    APH_CUDA_CHECK(cudaMemcpy(d_cellStart, h_start.data(),
                              (size_t)hashSize * sizeof(int), cudaMemcpyHostToDevice));
    APH_CUDA_CHECK(cudaMemset(d_cellCursor, 0, (size_t)hashSize * sizeof(int)));

    // --- Scatter pass. ---
    kScatterPhotons<<<photonBlocks, TPB>>>(d_photons, n, bounds,
                                           gridRes[0], gridRes[1], gridRes[2],
                                           hashSize, d_cellStart, d_cellCursor,
                                           d_photonIndex, d_photonCellId);
    APH_CUDA_CHECK(cudaGetLastError());

    // --- Assemble the device grid view + query buffers. ---
    GPhotonGrid grid;
    grid.photons      = d_photons;
    grid.cellStart    = d_cellStart;
    grid.cellCount    = d_cellCount;
    grid.photonIndex  = d_photonIndex;
    grid.photonCellId = d_photonCellId;
    grid.bounds       = bounds;
    grid.gridRes[0] = gridRes[0]; grid.gridRes[1] = gridRes[1]; grid.gridRes[2] = gridRes[2];
    grid.hashSize    = hashSize;
    grid.numPhotons  = n;
    grid.radius      = radius;

    GVec3* d_outE = nullptr;
    int* d_outIdx = nullptr;
    int* d_outFound = nullptr;
    int* d_outWritten = nullptr;
    APH_CUDA_CHECK(cudaMalloc(&d_outE, (size_t)nq * sizeof(GVec3)));
    APH_CUDA_CHECK(cudaMalloc(&d_outIdx, (size_t)nq * maxOut * sizeof(int)));
    APH_CUDA_CHECK(cudaMalloc(&d_outFound, (size_t)nq * sizeof(int)));
    APH_CUDA_CHECK(cudaMalloc(&d_outWritten, (size_t)nq * sizeof(int)));

    const int queryBlocks = (nq + TPB - 1) / TPB;
    kQuery<<<queryBlocks, TPB>>>(grid, d_queries, nq, maxOut,
                                 d_outE, d_outIdx, d_outFound, d_outWritten);
    APH_CUDA_CHECK(cudaGetLastError());
    APH_CUDA_CHECK(cudaDeviceSynchronize());

    // --- Download results. ---
    std::vector<GVec3> h_outE(nq);
    std::vector<int>   h_outIdx((size_t)nq * maxOut);
    std::vector<int>   h_outFound(nq);
    std::vector<int>   h_outWritten(nq);
    APH_CUDA_CHECK(cudaMemcpy(h_outE.data(), d_outE,
                              (size_t)nq * sizeof(GVec3), cudaMemcpyDeviceToHost));
    APH_CUDA_CHECK(cudaMemcpy(h_outIdx.data(), d_outIdx,
                              (size_t)nq * maxOut * sizeof(int), cudaMemcpyDeviceToHost));
    APH_CUDA_CHECK(cudaMemcpy(h_outFound.data(), d_outFound,
                              (size_t)nq * sizeof(int), cudaMemcpyDeviceToHost));
    APH_CUDA_CHECK(cudaMemcpy(h_outWritten.data(), d_outWritten,
                              (size_t)nq * sizeof(int), cudaMemcpyDeviceToHost));

    for (int i = 0; i < nq; ++i) {
        PhotonStoreQueryResult& r = results[i];
        r.irradiance = h_outE[i];
        r.foundCount = h_outFound[i];
        int w = h_outWritten[i];
        r.neighborIdx.assign(h_outIdx.begin() + (size_t)i * maxOut,
                             h_outIdx.begin() + (size_t)i * maxOut + w);
        std::sort(r.neighborIdx.begin(), r.neighborIdx.end());
    }

    // --- Cleanup. ---
    cudaFree(d_photons); cudaFree(d_queries);
    cudaFree(d_cellCount); cudaFree(d_cellStart); cudaFree(d_cellCursor);
    cudaFree(d_photonIndex); cudaFree(d_photonCellId);
    cudaFree(d_outE); cudaFree(d_outIdx); cudaFree(d_outFound); cudaFree(d_outWritten);

    return results;
}

}  // namespace gpu
}  // namespace photon
}  // namespace astroray

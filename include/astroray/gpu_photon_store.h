#pragma once
// pkg113 Phase 1 — GPU photon STORE + query (uniform spatial hash grid).
//
// The GPU counterpart of the CPU world-space photon store in
// include/astroray/photon/photon_map.h. Phase 1 implements STORAGE + QUERY only
// (NOT GPU emission/bounce — Phase 2 — NOT integrator gather wiring — Phase 3).
//
// Store decision (owner 2026-05-30; packages/pkg113-gpu-photon-map-caustics.md
// Decisions §2, cpu-gpu-parity-status.md Decisions §2): a **uniform spatial hash
// grid** (pbrt SPPM style), NOT a CUDA kd-tree. The hash grid is far friendlier
// to GPU parallelism than the CPU balanced kd-tree, and the photon-map gate is
// SSIM/energy parity (stochastic), not bit-exact.
//
// Citations (CLAUDE.md §6; see .astroray_plan/docs/pkg113-gpu-photon-store-research.md):
//   Jensen, "A Practical Guide to Global Illumination using Photon Maps",
//     SIGGRAPH 2000 Course 8 — §3.1 Eq. 8 irradiance density estimate.
//   pbrt-v3 src/integrators/sppm.cpp (BSD-2-Clause) — ToGrid / hash /
//     gridRes-from-diagonal; we mirror the hash-grid build math verbatim and
//     drop the progressive radius reduction (fixed radius, single pass — the
//     same non-progressive simplification the CPU chain already takes).
//   Teschner et al. 2003, "Optimized Spatial Hashing for Collision Detection of
//     Deformable Objects" — the three large primes used by pbrt's hash().
//
// This header is included by both .cu files (nvcc) and pure C++ translation
// units (the pybind binding in blender_module.cpp). The device-side query is in
// an `#ifdef __CUDACC__` block so the kernel-callable helpers only compile under
// nvcc; the host-callable build/query entry point is declared unconditionally.

#include "astroray/gpu_types.h"   // GVec3, GAABB

#include <cstdint>
#include <vector>

namespace astroray {
namespace photon {
namespace gpu {

// Device photon record. Mirrors astroray::photon::Photon (photon_map.h:39):
// world-space position, CIE-weighted flux (power), incoming direction, and the
// sampled wavelength. 44 bytes; POD so it cudaMemcpy's directly.
struct GPhoton {
    GVec3 position;      // world-space deposit point
    GVec3 power;         // CIE-weighted flux (XYZ packed into GVec3.x/y/z)
    GVec3 incidentDir;   // unit dir the photon arrived along (Phase-2 BSDF eval)
    float lambda;        // sampled wavelength (nm) — diagnostics
};

// Device-resident uniform hash grid over the uploaded photons. Built by
// buildPhotonGrid (host launches the build); read by the device query helpers.
// The grid stores photon INDICES bucketed by a CSR layout so a query touches
// only the photons in the 3x3x3 cell neighborhood of the query point.
//
// Layout (all device pointers):
//   cellStart[h], cellCount[h]  — CSR offsets into photonIndex[] for bucket h
//   photonIndex[]               — photon indices grouped by bucket
//   photonCellId[]              — the flattened cell id of each photonIndex[]
//                                 entry, parallel to it (see the de-dup note in
//                                 photonGridGather)
//   photons[]                   — the uploaded GPhoton array
struct GPhotonGrid {
    const GPhoton* photons;       // device ptr, numPhotons entries
    const int*     cellStart;     // device ptr, hashSize entries
    const int*     cellCount;     // device ptr, hashSize entries
    const int*     photonIndex;   // device ptr, numPhotons entries
    const int*     photonCellId;  // device ptr, numPhotons entries (parallel)
    GAABB          bounds;        // grid AABB (photon extent, padded by radius)
    int            gridRes[3];    // per-axis cell counts
    int            hashSize;      // number of hash buckets
    int            numPhotons;
    float          radius;        // fixed gather radius the grid was built for
};

// Flatten a 3-int grid cell to a single id, used to disambiguate hash
// collisions in the gather (two distinct cells can hash to the same bucket).
#ifdef __CUDACC__
__host__ __device__
#endif
inline int photonCellFlatten(int cx, int cy, int cz, const int gridRes[3]) {
    return (cz * gridRes[1] + cy) * gridRes[0] + cx;
}

// ---------------------------------------------------------------------------
// pbrt-v3 sppm.cpp hash-grid math (host+device). The host build and the device
// query MUST agree bit-for-bit on bucket assignment, so these are shared
// inline helpers in gpu_types.h-style HD form.
// ---------------------------------------------------------------------------
#ifdef __CUDACC__
#  define APH_HD __host__ __device__
#else
#  define APH_HD
#endif

// pbrt-v3 sppm.cpp ToGrid(): world point -> integer grid cell (clamped to the
// grid). Returns false (and still clamps) when p is outside the grid AABB.
APH_HD inline bool photonToGrid(const GVec3& p, const GAABB& b,
                                const int gridRes[3], int outCell[3]) {
    bool inBounds = true;
    GVec3 ext = b.max - b.min;
    for (int i = 0; i < 3; ++i) {
        float e = ext[i];
        float pg = (e > 0.f) ? (p[i] - b.min[i]) / e : 0.f;  // Bounds3::Offset
        int c = static_cast<int>(gridRes[i] * pg);
        inBounds = inBounds && (c >= 0 && c < gridRes[i]);
        if (c < 0) c = 0;
        if (c > gridRes[i] - 1) c = gridRes[i] - 1;
        outCell[i] = c;
    }
    return inBounds;
}

// pbrt-v3 sppm.cpp hash(): integer grid cell -> bucket index. Primes from
// Teschner 2003 (the same constants pbrt uses). The (unsigned) cast + %hashSize
// matches pbrt; negative coords cannot occur after photonToGrid clamps to
// [0, gridRes-1].
APH_HD inline unsigned int photonHash(int x, int y, int z, int hashSize) {
    return static_cast<unsigned int>(
               (x * 73856093) ^ (y * 19349663) ^ (z * 83492791)) %
           static_cast<unsigned int>(hashSize);
}

#ifdef __CUDACC__
// Device-side fixed-radius gather, callable from any kernel. Iterates the
// 3x3x3 cell neighborhood of q, accumulates the Jensen 2000 §3.1 Eq. 8
// fixed-radius irradiance estimate E = (1/(pi r^2)) * sum power, and optionally
// records the in-radius photon indices (up to maxOut) so a parity harness can
// assert the exact neighbor set. Returns the number of photons within radius.
//
// outIdx may be nullptr (estimate-only). foundCount is the true in-radius count
// (may exceed maxOut; outIdx is then truncated, but E uses all of them).
__device__ inline int photonGridGather(const GPhotonGrid& g, const GVec3& q,
                                        GVec3& outE,
                                        int* outIdx, int maxOut,
                                        int& foundCount) {
    outE = GVec3(0.f);
    foundCount = 0;
    int written = 0;
    const float r2 = g.radius * g.radius;
    int base[3];
    photonToGrid(q, g.bounds, g.gridRes, base);
    for (int dz = -1; dz <= 1; ++dz)
    for (int dy = -1; dy <= 1; ++dy)
    for (int dx = -1; dx <= 1; ++dx) {
        int cx = base[0] + dx, cy = base[1] + dy, cz = base[2] + dz;
        if (cx < 0 || cy < 0 || cz < 0 ||
            cx >= g.gridRes[0] || cy >= g.gridRes[1] || cz >= g.gridRes[2])
            continue;
        // Hash collisions: two distinct cells can map to the same bucket, and
        // the 27-cell sweep can visit two such cells. Gate each photon on its
        // OWN flattened cell id matching the cell we are currently visiting —
        // this both rejects collided foreign photons AND guarantees a photon is
        // counted at most once (it is only accepted when we visit its true
        // cell, and each of the 27 cells is visited exactly once).
        int wantCell = photonCellFlatten(cx, cy, cz, g.gridRes);
        unsigned int h = photonHash(cx, cy, cz, g.hashSize);
        int start = g.cellStart[h];
        int count = g.cellCount[h];
        for (int s = 0; s < count; ++s) {
            if (g.photonCellId[start + s] != wantCell) continue;
            int pi = g.photonIndex[start + s];
            const GPhoton& ph = g.photons[pi];
            GVec3 d = ph.position - q;
            if (d.length2() >= r2) continue;
            foundCount++;
            outE += ph.power;
            if (outIdx && written < maxOut) outIdx[written++] = pi;
        }
    }
    // Jensen 2000 §3.1 Eq. 8 disk-area density factor (fixed radius, no cone
    // filter for the Phase-1 parity harness; matches the numpy oracle exactly).
    if (g.radius > 0.f) {
        float norm = 3.14159265358979323846f * r2;
        outE = outE / norm;
    }
    return written;
}

// pkg113 Phase-3: ADAPTIVE k-NN + Jensen cone-filter irradiance estimate — the device twin
// of the CPU photon_map.h estimateIrradiance() (l.89-108), for the caustic gather in the
// integrators. Unlike photonGridGather (fixed radius, for the Phase-1 parity harness), this
// uses the k-th-nearest distance AT THE QUERY POINT as the effective radius, so it shrinks in
// the dense focal core -> a SHARP caustic peak that matches the CPU. The fixed-radius estimate
// over-smooths the core (flat peak), which mis-calibrates causticScale and inflates the
// receiver ROI. `g.radius` is the calibrated 1.5*median(kth) cap (CPU maxRadius); the 27-cell
// neighbourhood (cell size ~ g.radius) contains every photon within it. Returns E (XYZ);
// foundCount = number of in-radius neighbours.
__device__ inline GVec3 photonGridGatherKnn(const GPhotonGrid& g, const GVec3& q,
                                            int K, float kf, int& foundCount) {
    foundCount = 0;
    const int KMAX = 64;
    int kk = (K < KMAX) ? K : KMAX;
    float bestD2[KMAX];   // the K smallest squared distances
    int   bestIx[KMAX];   // parallel photon indices
    int cnt = 0;
    const float maxR2 = g.radius * g.radius;
    int base[3];
    photonToGrid(q, g.bounds, g.gridRes, base);
    for (int dz = -1; dz <= 1; ++dz)
    for (int dy = -1; dy <= 1; ++dy)
    for (int dx = -1; dx <= 1; ++dx) {
        int cx = base[0] + dx, cy = base[1] + dy, cz = base[2] + dz;
        if (cx < 0 || cy < 0 || cz < 0 ||
            cx >= g.gridRes[0] || cy >= g.gridRes[1] || cz >= g.gridRes[2]) continue;
        int wantCell = photonCellFlatten(cx, cy, cz, g.gridRes);
        unsigned int h = photonHash(cx, cy, cz, g.hashSize);
        int start = g.cellStart[h], count = g.cellCount[h];
        for (int s = 0; s < count; ++s) {
            if (g.photonCellId[start + s] != wantCell) continue;
            int pi = g.photonIndex[start + s];
            float d2 = (g.photons[pi].position - q).length2();
            if (d2 >= maxR2) continue;
            ++foundCount;
            if (cnt < kk) {
                bestD2[cnt] = d2; bestIx[cnt] = pi; ++cnt;
            } else {
                int mi = 0; float mv = bestD2[0];
                for (int t = 1; t < kk; ++t) if (bestD2[t] > mv) { mv = bestD2[t]; mi = t; }
                if (d2 < mv) { bestD2[mi] = d2; bestIx[mi] = pi; }
            }
        }
    }
    if (cnt == 0) return GVec3(0.f);
    float r2 = bestD2[0];                       // adaptive radius^2 = the farthest kept
    for (int t = 1; t < cnt; ++t) if (bestD2[t] > r2) r2 = bestD2[t];
    if (r2 <= 0.f) return GVec3(0.f);
    float r = sqrtf(r2);
    GVec3 sum(0.f);
    for (int t = 0; t < cnt; ++t) {
        float w = 1.0f - sqrtf(bestD2[t]) / (kf * r);   // Jensen cone weight (>= 0)
        sum = sum + g.photons[bestIx[t]].power * w;
    }
    float norm = (1.0f - 2.0f / (3.0f * kf)) * 3.14159265358979323846f * r2;
    if (norm <= 0.f) return GVec3(0.f);
    return sum / norm;
}
#endif  // __CUDACC__

#undef APH_HD

// ---------------------------------------------------------------------------
// Host-callable Phase-1 parity entry point (defined in src/gpu/photon_store.cu).
// Mirrors the cuda_wavefront_snapshot_* host-callable pattern
// (src/gpu/wavefront/gpu_wavefront_snapshot.h) so the pybind binding in
// blender_module.cpp can reach it under #ifdef ASTRORAY_CUDA_ENABLED.
//
// Uploads `photons`, builds the hash grid on the GPU for `radius`, runs a
// fixed-radius gather at each query point, and downloads the per-query density
// estimate + in-radius neighbor index sets. Used ONLY by
// tests/test_gpu_photon_store.py to gate the store against a numpy oracle.
// ---------------------------------------------------------------------------

// One query result. neighborIdx holds the in-radius photon indices (sorted
// ascending by the host so the test can set-compare against numpy), foundCount
// is the true in-radius count (== neighborIdx.size() unless truncated).
struct PhotonStoreQueryResult {
    GVec3            irradiance;   // Jensen Eq. 8 fixed-radius estimate
    std::vector<int> neighborIdx; // in-radius photon indices, sorted ascending
    int              foundCount;
};

// Build the grid on the GPU and gather at each query point. radius is the fixed
// gather radius; maxNeighborsPerQuery caps the index readback per query (the
// estimate always uses ALL in-radius photons). Returns one result per query.
std::vector<PhotonStoreQueryResult> cuda_photon_store_query(
    const std::vector<GPhoton>& photons,
    const std::vector<GVec3>&   queries,
    float                       radius,
    int                         maxNeighborsPerQuery);

}  // namespace gpu
}  // namespace photon
}  // namespace astroray

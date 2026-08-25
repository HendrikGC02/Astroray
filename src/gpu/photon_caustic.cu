// photon_caustic.cu — pkg113 Phase 3 — scene-driven GPU photon-caustic pre-pass.
//
// The capstone: a once-per-frame forward photon trace through the UPLOADED
// scene's caustic-caster glass (via the device BVH), depositing per-λ CIE flux
// onto receivers, then a RESIDENT hash grid built from those deposits + a
// calibrated gather radius/scale. The path-trace megakernel (path_trace_kernel.cu)
// then gathers this grid at receiver hits.
//
// This is the device twin of the CPU pkg111 pre-pass
// (plugins/integrators/spectral_path_tracer.cpp::buildPhotonMap, l.339-514): the
// emission/bounce loop mirrors the general BVH loop (l.422-475), the deposit is
// the per-λ CIE flux (l.464-470), and the radius/scale calibration mirrors
// l.481-513. Refraction/Fresnel/Sellmeier/CMF helpers are reused verbatim from
// the Phase-2 device kernel (photon_emission.cu).
//
// Citations (CLAUDE.md §6; .astroray_plan/docs/pkg113-phase3-gather-wiring-research.md):
//   Jensen 1996/2000 (photon map + §3.1 Eq. 8); Arvo 1986 (forward transport);
//   Schlick 1994 (Fresnel); Sellmeier 1871 (n(λ), via gpu_dispersion.cuh);
//   CIE 1964 10° CMF (data/spectra/cie_cmf.inc); pbrt-v3 sppm.cpp hash grid
//   (BSD-2-Clause). Build = count/scan/scatter (same as photon_store.cu).

#include "astroray/gpu_photon_caustic.h"
#include "astroray/gpu_photon_store.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_bvh.h"            // gpu_bvh_hit (device scene traversal)
#include "astroray/gpu_dispersion.cuh"   // gpu_sellmeier_ior

#include <cuda_runtime.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <vector>

#define APC_CUDA_CHECK(call) do {                                           \
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

// --- CIE 1964 10° CMF table (same data the CPU cieCmf1964_10deg reads, and the
// same table Phase-2 photon_emission.cu bakes). Kept TU-local so the two .cu
// files don't collide on the __constant__ symbol names. -------------------------
namespace cmf_baked {
#include "data/spectra/cie_cmf.inc"
}  // namespace cmf_baked

__constant__ float g_pcCmfX[cmf_baked::kCieCmfCount];
__constant__ float g_pcCmfY[cmf_baked::kCieCmfCount];
__constant__ float g_pcCmfZ[cmf_baked::kCieCmfCount];

void uploadCausticCmf() {
    static bool uploaded = false;
    if (uploaded) return;
    APC_CUDA_CHECK(cudaMemcpyToSymbol(g_pcCmfX, cmf_baked::kCieCmfX,
                                      sizeof(cmf_baked::kCieCmfX)));
    APC_CUDA_CHECK(cudaMemcpyToSymbol(g_pcCmfY, cmf_baked::kCieCmfY,
                                      sizeof(cmf_baked::kCieCmfY)));
    APC_CUDA_CHECK(cudaMemcpyToSymbol(g_pcCmfZ, cmf_baked::kCieCmfZ,
                                      sizeof(cmf_baked::kCieCmfZ)));
    uploaded = true;
}

// Device CMF lookup — exact port of src/spectrum.cpp::sampleTable, identical to
// photon_emission.cu pe_cieCmf (1 nm linear interp over [360,830], clamped).
__device__ inline GVec3 pc_cieCmf(float lambda) {
    const float lmin = 360.0f, step = 1.0f;
    const int count = 471;
    float idx = (lambda - lmin) / step;
    int i = static_cast<int>(idx);
    if (i < 0)        return GVec3(g_pcCmfX[0], g_pcCmfY[0], g_pcCmfZ[0]);
    if (i >= count - 1) return GVec3(g_pcCmfX[count-1], g_pcCmfY[count-1], g_pcCmfZ[count-1]);
    float t = idx - static_cast<float>(i);
    return GVec3(g_pcCmfX[i]*(1.f-t) + g_pcCmfX[i+1]*t,
                 g_pcCmfY[i]*(1.f-t) + g_pcCmfY[i+1]*t,
                 g_pcCmfZ[i]*(1.f-t) + g_pcCmfZ[i+1]*t);
}

// Snell refraction (CPU light_tracer_caustic.cpp:183-189 / photon_emission.cu).
__device__ inline bool pc_refract(const GVec3& d, const GVec3& n, float eta, GVec3& out) {
    float cosi = -d.dot(n);
    float s2 = eta * eta * (1.0f - cosi * cosi);
    if (s2 >= 1.0f) return false;          // TIR
    out = (d * eta + n * (eta * cosi - sqrtf(1.0f - s2))).normalized();
    return true;
}

// Schlick-Fresnel TRANSMITTANCE 1 - F (CPU :190-194 / photon_emission.cu).
__device__ inline float pc_fresnelT(float cosi, float ior) {
    float f0 = (1.0f - ior) / (1.0f + ior); f0 *= f0;
    float fr = f0 + (1.0f - f0) * powf(fmaxf(0.0f, 1.0f - fabsf(cosi)), 5.0f);
    return 1.0f - fr;
}

// Deterministic per-cell hash jitter (same as photon_emission.cu pe_jitter): the
// forward trace draws λ + aperture-position from this so the trace is fully
// reproducible (no curand state to manage in a pre-pass).
__device__ inline float pc_jitter(unsigned int cell, unsigned int salt) {
    unsigned int h = cell * 0x9E3779B1u + salt * 0x85EBCA77u;
    h ^= h >> 15; h *= 0x2C1B3C6Du; h ^= h >> 12; h *= 0x297A2D39u; h ^= h >> 15;
    return (h & 0x00FFFFFFu) * (1.0f / 16777216.0f);   // [0,1)
}

// pkg221: light-SPD CDF in constant memory (uploaded from aim.spdCdf when the
// dominant light carries a usable SPD). 341 entries, 380..720 nm at 1 nm.
__constant__ float g_spdCdf[341];

// Device inverse-CDF sample — BYTE-MIRRORS the host photonSpdInverseCdf
// (include/astroray/photon_spd.h): binary-search the smallest k with cdf[k] >= u,
// then linearly interpolate within the [k-1,k] bin. Same math both backends so the
// caustic spectra match statistically.
__device__ inline float pc_spdInverseCdf(float u) {
    const int K = 341;
    const float lmin = 380.0f;
    int lo = 0, hi = K - 1;
    while (lo < hi) {
        int mid = (lo + hi) >> 1;
        if (g_spdCdf[mid] < u) lo = mid + 1; else hi = mid;
    }
    int k = lo;
    float cLo = (k > 0) ? g_spdCdf[k - 1] : 0.0f;
    float cHi = g_spdCdf[k];
    float t = (cHi > cLo) ? (u - cLo) / (cHi - cLo) : 0.0f;
    float lambda = lmin + (float)(k - 1) + t;
    if (lambda < lmin) lambda = lmin;
    return lambda;
}

// Is this material a transmissive caustic caster glass? The test scenes use
// create_material("dielectric", ...) → GMAT_DIELECTRIC. A closure-graph glass
// (GMAT_CLOSURE_GRAPH) is transmissive when it carries a dielectric-transmission
// closure. Mirrors the CPU rec.material->isTransmissive() gate.
__device__ inline bool pc_isTransmissive(const GMaterial& m) {
    if (m.type == GMAT_DIELECTRIC || m.type == GMAT_THIN_GLASS) return true;
    if (m.type == GMAT_CLOSURE_GRAPH) {
        if (m.transmission > 0.0f) return true;
        for (int i = 0; i < m.closureCount; ++i)
            if (m.closures[i].type == GCLOSURE_DIELECTRIC_TRANSMISSION ||
                m.closures[i].type == GCLOSURE_THIN_GLASS)
                return true;
    }
    return false;
}

// Per-λ IOR for a glass material (CPU rec.material->iorAt(lambda)). Sellmeier when
// the upload flagged dispersion (gpu_dispersion.cuh), else the flat ior.
__device__ inline float pc_iorAt(const GMaterial& m, float lambda) {
    float ior = m.isDispersive ? gpu_sellmeier_ior(m.dispersion, lambda) : m.ior;
    if (ior <= 1.0f) ior = 1.5f;   // CPU general-loop fallback (l.296/438)
    return ior;
}

// --- Forward photon emission + bounce through the FULL scene BVH ----------------
// One thread per aperture cell. Mirrors the CPU general BVH loop
// (spectral_path_tracer.cpp:424-475): seed a collimated photon at the aperture,
// march it through the scene refracting at transmissive hits (enter/exit by the
// geometric-normal sign, Schlick transmittance accumulation, TIR reflect), and
// deposit per-λ CIE flux · cosθ on the first diffuse (non-emissive,
// non-transmissive) hit AFTER passing a caster. A cell that never deposits writes
// power 0 (the host compacts survivors, like the CPU `photons` vector).
__global__ void kEmitSceneCaustic(
    const GBVHNode*  bvhNodes,
    const GPrimitive* prims,
    const GTriangle*  tris,
    const GSphere*    spheres,
    const GMaterial*  materials,
    GVec3 sunDir, GVec3 apOrigin, GVec3 apU, GVec3 apV, float apRadius,
    int apertureN, float lambdaMin, float lambdaMax, int maxDepth,
    unsigned int seed, int spdValid, float spdIntegral, GPhoton* out)
{
    int gx = blockIdx.x * blockDim.x + threadIdx.x;
    int gy = blockIdx.y * blockDim.y + threadIdx.y;
    if (gx >= apertureN || gy >= apertureN) return;
    int cell = gy * apertureN + gx;
    out[cell].position    = GVec3(0.f);
    out[cell].power       = GVec3(0.f);   // default: dropped
    out[cell].incidentDir = GVec3(0.f);
    out[cell].lambda      = 0.f;

    // Independent per-cell uniform λ (CPU: λ = lmin + (lmax-lmin)·u01). pkg220:
    // XOR the per-iteration `seed` into the salt so each progressive iteration
    // draws an independent λ + aperture position for this cell (decorrelated
    // photon map per iteration → the caustic averages down). The pc_jitter hash
    // is unchanged; XOR-ing the seed into distinct salts (1,2,101) keeps them
    // distinct and well-mixed while the pre-pass stays stateless (no curand).
    // pkg221: importance-sample λ ∝ the light SPD when a valid CDF was uploaded;
    // else the pkg220 uniform draw. Same u either way (one jitter draw).
    float uLam = pc_jitter(cell, 101u ^ seed);
    float lambda = spdValid ? pc_spdInverseCdf(uLam)
                            : lambdaMin + (lambdaMax - lambdaMin) * uLam;

    // Jittered lattice point on the aperture disc → a collimated entry ray
    // (CPU :426-428: ra,rb ∈ [-crad,crad]; here jittered into [-apRadius,apRadius]).
    float jx = (gx + pc_jitter(cell, 1u ^ seed)) / float(apertureN);
    float jy = (gy + pc_jitter(cell, 2u ^ seed)) / float(apertureN);
    float a2 = (jx * 2.0f - 1.0f) * apRadius;
    float b2 = (jy * 2.0f - 1.0f) * apRadius;
    GVec3 o = apOrigin + apU * a2 + apV * b2;
    GVec3 d = sunDir;

    float tr = 1.0f;
    bool passedCaster = false;
    const float eps = 1e-3f;

    for (int bounce = 0; bounce < maxDepth; ++bounce) {
        GHitRecord rec;
        if (!gpu_bvh_hit(bvhNodes, prims, tris, spheres,
                         GRay(o, d), eps, 1e30f, rec))
            break;
        const GMaterial& mat = materials[rec.materialId];
        // Emissive surface: the CPU loop breaks (isEmissive()). emissionIntensity>0
        // flags the diffuse-light material on upload.
        if (mat.emissionIntensity > 0.0f) break;

        if (pc_isTransmissive(mat)) {
            float ior = pc_iorAt(mat, lambda);
            // gpu_bvh_hit gives the ORIENTED normal + frontFace; recover the
            // geometric outward normal (CPU rec.normal semantics, l.297).
            GVec3 ng = rec.frontFace ? rec.normal : -rec.normal;
            GVec3 nf; float eta;
            if (d.dot(ng) < 0.0f) { nf = ng;        eta = 1.0f / ior; }  // entering
            else                  { nf = ng * -1.0f; eta = ior; }         // exiting
            GVec3 nd;
            if (pc_refract(d, nf, eta, nd)) {
                tr *= pc_fresnelT(d.dot(nf), ior);
                d = nd;
            } else {
                d = (d - nf * (2.0f * d.dot(nf))).normalized();           // TIR
            }
            passedCaster = true;
            o = rec.point + d * eps;
            continue;
        }

        // Diffuse receiver: deposit only on an L S+ D path (CPU :461).
        if (passedCaster && tr > 0.0f) {
            // Lambert cosine (pkg111 addition, CPU :463): flux density ∝ cosθ.
            float cosTheta = fabsf(rec.normal.dot(d));
            GVec3 cmf = pc_cieCmf(lambda);
            // pkg221: with λ importance-sampled ∝ SPD (pdf = S/I), the S/p weight
            // collapses to the constant I = spdIntegral; uniform λ keeps weight 1.
            float wS = spdValid ? spdIntegral : 1.0f;
            out[cell].position    = rec.point;
            out[cell].incidentDir = d;
            out[cell].power       = GVec3(cmf.x * tr * cosTheta * wS,
                                          cmf.y * tr * cosTheta * wS,
                                          cmf.z * tr * cosTheta * wS);
            out[cell].lambda      = lambda;
        }
        break;
    }
}

// --- Hash-grid build kernels (identical math to photon_store.cu) ----------------
__global__ void kCount(const GPhoton* photons, int n, GAABB bounds,
                       int gx, int gy, int gz, int hashSize, int* cellCount) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    int res[3] = {gx, gy, gz}; int cell[3];
    photonToGrid(photons[i].position, bounds, res, cell);
    unsigned int h = photonHash(cell[0], cell[1], cell[2], hashSize);
    atomicAdd(&cellCount[h], 1);
}

__global__ void kScatter(const GPhoton* photons, int n, GAABB bounds,
                         int gx, int gy, int gz, int hashSize,
                         const int* cellStart, int* cellCursor,
                         int* photonIndex, int* photonCellId) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    int res[3] = {gx, gy, gz}; int cell[3];
    photonToGrid(photons[i].position, bounds, res, cell);
    unsigned int h = photonHash(cell[0], cell[1], cell[2], hashSize);
    int slot = atomicAdd(&cellCursor[h], 1);
    int dst = cellStart[h] + slot;
    photonIndex[dst] = i;
    photonCellId[dst] = photonCellFlatten(cell[0], cell[1], cell[2], res);
}

// --- Calibration gather: estimate irradiance Y at a subsample of photons, so the
// host can fix causticScale = boost/(π·peak_95). Mirrors the CPU peak sweep
// (spectral_path_tracer.cpp:500-509). ---
__global__ void kPeakGather(GPhotonGrid grid, int subStride, int subCount,
                            float* outPeakY) {
    int j = blockIdx.x * blockDim.x + threadIdx.x;
    if (j >= subCount) return;
    int pi = j * subStride;
    if (pi >= grid.numPhotons) { outPeakY[j] = 0.f; return; }
    int found = 0;
    GVec3 e = photonGridGatherKnn(grid, grid.photons[pi].position, 50, 1.1f, found);
    outPeakY[j] = e.y;   // adaptive k-NN cone estimate — same as the megakernel gather
}

// pkg113 Phase-3: per-photon k-th-nearest distance over the 27-cell neighborhood, so the
// host can set the gather radius = 1.5 * median(kth) — the EXACT CPU calibration
// (spectral_path_tracer.cpp:481-494). The CPU kNN is LOCAL/density-adaptive: in a focused
// caustic the median k-th-nearest is dominated by the dense focal CORE (small radius). The
// previous global-AABB mean-spacing instead used the whole-region (low) mean density, which
// over-estimated the radius -> over-diffusion -> peak95 too small -> causticScale exploded
// (~433x ROI energy). Run this on a grid built with a GENEROUS provisional radius so the 27
// cells contain >= K neighbours for the median (sparse-tail photons land above the median
// and do not affect it).
__global__ void kKthNearest(GPhotonGrid grid, int subStride, int subCount, int K,
                            float* outKth) {
    int j = blockIdx.x * blockDim.x + threadIdx.x;
    if (j >= subCount) return;
    int pi = j * subStride;
    if (pi >= grid.numPhotons) { outKth[j] = 0.f; return; }
    const int KMAX = 64;
    float best[KMAX];                 // the K smallest squared distances seen so far
    int kk = (K < KMAX) ? K : KMAX;
    int cnt = 0;
    GVec3 q = grid.photons[pi].position;
    int base[3];
    photonToGrid(q, grid.bounds, grid.gridRes, base);
    for (int dz = -1; dz <= 1; ++dz)
    for (int dy = -1; dy <= 1; ++dy)
    for (int dx = -1; dx <= 1; ++dx) {
        int cx = base[0] + dx, cy = base[1] + dy, cz = base[2] + dz;
        if (cx < 0 || cy < 0 || cz < 0 ||
            cx >= grid.gridRes[0] || cy >= grid.gridRes[1] || cz >= grid.gridRes[2]) continue;
        int wantCell = photonCellFlatten(cx, cy, cz, grid.gridRes);
        unsigned int h = photonHash(cx, cy, cz, grid.hashSize);
        int start = grid.cellStart[h], count = grid.cellCount[h];
        for (int s = 0; s < count; ++s) {
            if (grid.photonCellId[start + s] != wantCell) continue;
            int npi = grid.photonIndex[start + s];
            if (npi == pi) continue;          // exclude self
            float d2 = (grid.photons[npi].position - q).length2();
            if (cnt < kk) {
                best[cnt++] = d2;
            } else {
                int mi = 0; float mv = best[0];
                for (int t = 1; t < kk; ++t) if (best[t] > mv) { mv = best[t]; mi = t; }
                if (d2 < mv) best[mi] = d2;
            }
        }
    }
    if (cnt == 0) { outKth[j] = 0.f; return; }
    float kth2 = best[0];                       // k-th nearest dist^2 = max of the K smallest
    for (int t = 1; t < cnt; ++t) if (best[t] > kth2) kth2 = best[t];
    outKth[j] = sqrtf(kth2);
}

// RAII holder for the resident device CSR buffers + deposit array. The result's
// opaque `owner` points at one of these; cuda_photon_caustic_free deletes it.
struct CausticGridOwner {
    GPhoton* d_photons     = nullptr;
    int*     d_cellStart   = nullptr;
    int*     d_cellCount   = nullptr;
    int*     d_photonIndex = nullptr;
    int*     d_photonCellId = nullptr;
    ~CausticGridOwner() {
        if (d_photons)      cudaFree(d_photons);
        if (d_cellStart)    cudaFree(d_cellStart);
        if (d_cellCount)    cudaFree(d_cellCount);
        if (d_photonIndex)  cudaFree(d_photonIndex);
        if (d_photonCellId) cudaFree(d_photonCellId);
        cudaGetLastError();   // swallow latent cleanup errors
    }
};

}  // namespace

GPhotonCausticResult cuda_photon_caustic_build(
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials,
    const PhotonCausticAim& aim)
{
    GPhotonCausticResult result;
    result.scale = 1.0f; result.numPhotons = 0; result.ready = false;
    result.owner = nullptr;
    result.grid = GPhotonGrid{};
    if (!aim.valid || aim.photonCount <= 0 || !d_bvhNodes) return result;

    uploadCausticCmf();

    // --- Aperture frame around the sun direction (CPU :364-368). ---
    GVec3 sunDir = aim.sunDir.normalized();
    GVec3 a = (fabsf(sunDir.x) < 0.9f) ? GVec3(1, 0, 0) : GVec3(0, 1, 0);
    GVec3 apU = (a - sunDir * a.dot(sunDir)).normalized();
    GVec3 apV = sunDir.cross(apU);

    // apertureN² photons (round the requested count up to a square lattice).
    int apertureN = static_cast<int>(std::sqrt((double)aim.photonCount) + 0.5);
    if (apertureN < 1) apertureN = 1;
    const int nCells = apertureN * apertureN;

    // pkg221: upload the host-built light-SPD CDF to constant memory for the
    // importance-sampling inverse-CDF in the emit kernel (only when valid).
    if (aim.spdValid)
        APC_CUDA_CHECK(cudaMemcpyToSymbol(g_spdCdf, aim.spdCdf, sizeof(aim.spdCdf)));

    // --- Emit: forward-trace photons through the scene; survivors carry power>0. ---
    GPhoton* d_emit = nullptr;
    APC_CUDA_CHECK(cudaMalloc(&d_emit, (size_t)nCells * sizeof(GPhoton)));
    {
        dim3 block(16, 16);
        dim3 grid((apertureN + block.x - 1) / block.x,
                  (apertureN + block.y - 1) / block.y);
        kEmitSceneCaustic<<<grid, block>>>(
            d_bvhNodes, d_prims, d_tris, d_spheres, d_materials,
            sunDir, aim.apertureOrigin, apU, apV, aim.apertureRadius,
            apertureN, aim.lambdaMin, aim.lambdaMax, aim.maxDepth,
            aim.seed, aim.spdValid ? 1 : 0, aim.spdIntegral,   // pkg221: SPD IS
            d_emit);   // pkg220: per-iteration jitter decorrelation seed
        APC_CUDA_CHECK(cudaGetLastError());
        APC_CUDA_CHECK(cudaDeviceSynchronize());
    }

    // Compact survivors on the host (mirrors the CPU `photons` vector). The
    // photon set is modest (aperture lattice), so a host compaction is fine.
    std::vector<GPhoton> emitHost(nCells);
    APC_CUDA_CHECK(cudaMemcpy(emitHost.data(), d_emit,
                              (size_t)nCells * sizeof(GPhoton),
                              cudaMemcpyDeviceToHost));
    cudaFree(d_emit);

    std::vector<GPhoton> photons;
    photons.reserve(nCells);
    for (const auto& p : emitHost)
        if (p.power.y > 0.f) photons.push_back(p);

    const int n = static_cast<int>(photons.size());
    if (n < 16) return result;   // CPU bails below 16 photons too

    // --- Deposit AABB (over ALL deposits; the grid bounds must bucket every photon). ---
    GVec3 mn = photons[0].position, mx = photons[0].position;
    for (int i = 1; i < n; ++i) {
        mn = gvec3_min(mn, photons[i].position);
        mx = gvec3_max(mx, photons[i].position);
    }
    // Provisional radius (global in-plane mean-spacing): NOT the final gather radius — only
    // a generous seed so the provisional grid's 27-cell neighbourhood contains >= K
    // neighbours for the k-NN pass below. The CPU-faithful LOCAL radius is computed from the
    // per-photon median k-th-nearest distance (kKthNearest), exactly like the CPU.
    GVec3 ext = mx - mn;
    float dims[3] = {ext.x, ext.y, ext.z};
    std::sort(dims, dims + 3);
    float area0 = std::max(dims[1], 1e-4f) * std::max(dims[2], 1e-4f);
    const int K = 50;
    float provRadius = 1.5f * std::sqrt((float)K / 3.14159265358979323846f) *
                       std::sqrt(area0 / std::max(n, 1));
    if (provRadius <= 0.f) return result;

    // --- Upload deposits + alloc the (radius-independent-size) CSR buffers once. ---
    CausticGridOwner* owner = new CausticGridOwner();
    APC_CUDA_CHECK(cudaMalloc(&owner->d_photons, (size_t)n * sizeof(GPhoton)));
    APC_CUDA_CHECK(cudaMemcpy(owner->d_photons, photons.data(),
                              (size_t)n * sizeof(GPhoton), cudaMemcpyHostToDevice));
    const int hashSize = n;   // pbrt convention
    APC_CUDA_CHECK(cudaMalloc(&owner->d_cellCount,   (size_t)hashSize * sizeof(int)));
    APC_CUDA_CHECK(cudaMalloc(&owner->d_cellStart,   (size_t)hashSize * sizeof(int)));
    APC_CUDA_CHECK(cudaMalloc(&owner->d_photonIndex,  (size_t)n * sizeof(int)));
    APC_CUDA_CHECK(cudaMalloc(&owner->d_photonCellId, (size_t)n * sizeof(int)));
    int* d_cellCursor = nullptr;
    APC_CUDA_CHECK(cudaMalloc(&d_cellCursor, (size_t)hashSize * sizeof(int)));
    const int TPB = 256;
    const int pblocks = (n + TPB - 1) / TPB;

    // buildGrid(radius): (re)derive bounds/gridRes from `radius`, run count/scan/scatter into
    // the owner CSR buffers (reused across the two passes), return the grid view.
    auto buildGrid = [&](float radius) -> GPhotonGrid {
        GVec3 pad(radius);
        GAABB bounds; bounds.min = mn - pad; bounds.max = mx + pad;
        GVec3 diag = bounds.max - bounds.min;
        float maxDiag = diag.maxComponent();
        int baseRes = std::max(1, static_cast<int>(maxDiag / radius));
        int gridRes[3];
        for (int i = 0; i < 3; ++i)
            gridRes[i] = std::max(static_cast<int>(baseRes * diag[i] / maxDiag), 1);
        APC_CUDA_CHECK(cudaMemset(owner->d_cellCount, 0, (size_t)hashSize * sizeof(int)));
        kCount<<<pblocks, TPB>>>(owner->d_photons, n, bounds,
                                 gridRes[0], gridRes[1], gridRes[2],
                                 hashSize, owner->d_cellCount);
        APC_CUDA_CHECK(cudaGetLastError());
        std::vector<int> h_count(hashSize);
        APC_CUDA_CHECK(cudaMemcpy(h_count.data(), owner->d_cellCount,
                                  (size_t)hashSize * sizeof(int), cudaMemcpyDeviceToHost));
        std::vector<int> h_start(hashSize);
        int acc = 0;
        for (int i = 0; i < hashSize; ++i) { h_start[i] = acc; acc += h_count[i]; }
        APC_CUDA_CHECK(cudaMemcpy(owner->d_cellStart, h_start.data(),
                                  (size_t)hashSize * sizeof(int), cudaMemcpyHostToDevice));
        APC_CUDA_CHECK(cudaMemset(d_cellCursor, 0, (size_t)hashSize * sizeof(int)));
        kScatter<<<pblocks, TPB>>>(owner->d_photons, n, bounds,
                                   gridRes[0], gridRes[1], gridRes[2], hashSize,
                                   owner->d_cellStart, d_cellCursor,
                                   owner->d_photonIndex, owner->d_photonCellId);
        APC_CUDA_CHECK(cudaGetLastError());
        APC_CUDA_CHECK(cudaDeviceSynchronize());
        GPhotonGrid g;
        g.photons      = owner->d_photons;
        g.cellStart    = owner->d_cellStart;
        g.cellCount    = owner->d_cellCount;
        g.photonIndex  = owner->d_photonIndex;
        g.photonCellId = owner->d_photonCellId;
        g.bounds       = bounds;
        g.gridRes[0] = gridRes[0]; g.gridRes[1] = gridRes[1]; g.gridRes[2] = gridRes[2];
        g.hashSize    = hashSize;
        g.numPhotons  = n;
        g.radius      = radius;
        return g;
    };

    // --- Pass 1: provisional grid -> per-photon k-th-nearest -> CPU median radius. ---
    GPhotonGrid gridProv = buildGrid(provRadius);
    const int S = std::min(n, 4096);
    const int subStride = std::max(1, n / S);
    const int subCount = (n + subStride - 1) / subStride;
    float* d_kth = nullptr;
    APC_CUDA_CHECK(cudaMalloc(&d_kth, (size_t)subCount * sizeof(float)));
    {
        int blocks = (subCount + TPB - 1) / TPB;
        kKthNearest<<<blocks, TPB>>>(gridProv, subStride, subCount, K, d_kth);
        APC_CUDA_CHECK(cudaGetLastError());
        APC_CUDA_CHECK(cudaDeviceSynchronize());
    }
    std::vector<float> kth(subCount);
    APC_CUDA_CHECK(cudaMemcpy(kth.data(), d_kth,
                              (size_t)subCount * sizeof(float), cudaMemcpyDeviceToHost));
    cudaFree(d_kth);
    std::vector<float> kthnz; kthnz.reserve(subCount);
    for (float v : kth) if (v > 0.f) kthnz.push_back(v);
    if (kthnz.empty()) { cudaFree(d_cellCursor); delete owner; return result; }
    std::sort(kthnz.begin(), kthnz.end());
    // CPU spectral_path_tracer.cpp:494 — radius = 1.5 * median(k-th-nearest).
    float radius = 1.5f * kthnz[kthnz.size() / 2];
    if (radius <= 0.f) { cudaFree(d_cellCursor); delete owner; return result; }

    // --- Pass 2: rebuild the grid at the calibrated (tight) radius for the real gather. ---
    GPhotonGrid grid = buildGrid(radius);
    cudaFree(d_cellCursor);

    // --- Calibrate causticScale = boost/(π·peak_95) over the same photon subsample
    // (CPU :500-513). The 1/π folds the Lambertian L = (albedo/π)·E. Reuses S/subStride/
    // subCount from the k-NN pass above. ---
    float* d_peak = nullptr;
    APC_CUDA_CHECK(cudaMalloc(&d_peak, (size_t)subCount * sizeof(float)));
    {
        int blocks = (subCount + TPB - 1) / TPB;
        kPeakGather<<<blocks, TPB>>>(grid, subStride, subCount, d_peak);
        APC_CUDA_CHECK(cudaGetLastError());
        APC_CUDA_CHECK(cudaDeviceSynchronize());
    }
    std::vector<float> peaks(subCount);
    APC_CUDA_CHECK(cudaMemcpy(peaks.data(), d_peak,
                              (size_t)subCount * sizeof(float), cudaMemcpyDeviceToHost));
    cudaFree(d_peak);

    std::vector<float> nz;
    nz.reserve(subCount);
    for (float p : peaks) if (p > 0.f) nz.push_back(p);
    if (nz.empty()) { delete owner; return result; }
    std::sort(nz.begin(), nz.end());
    float peak95 = nz[static_cast<size_t>(nz.size() * 0.95f)];
    if (peak95 <= 0.f) { delete owner; return result; }

    const float pi = 3.14159265358979323846f;
    result.scale      = aim.boost / (pi * peak95);
    result.grid       = grid;
    result.numPhotons = n;
    result.owner      = owner;
    result.ready      = true;

    if (std::getenv("CAUSTIC_DBG")) {
        GVec3 c(0.f, 0.f, 0.f); float wsum = 0.f;
        for (const auto& p : photons) { c = c + p.position * p.power.y; wsum += p.power.y; }
        c = c * (1.0f / std::max(wsum, 1e-12f));
        float rms = 0.f;
        for (const auto& p : photons) {
            GVec3 d = p.position - c;
            rms += p.power.y * (d.x * d.x + d.z * d.z);
        }
        rms = std::sqrt(rms / std::max(wsum, 1e-12f));
        GVec3 e = mx - mn;
        std::fprintf(stderr,
            "[CAUSTIC_DBG] n=%d depositExt=(%.3f,%.3f,%.3f) centroidXZ=(%.3f,%.3f) "
            "rmsXZ=%.4f provRadius=%.5f knnRadius=%.5f peak95=%.5f scale=%.5f totalY=%.4f\n",
            n, e.x, e.y, e.z, c.x, c.z, rms, provRadius, radius, peak95, result.scale, wsum);
    }
    return result;
}

void cuda_photon_caustic_free(GPhotonCausticResult& result) {
    if (result.owner) {
        delete static_cast<CausticGridOwner*>(result.owner);
        result.owner = nullptr;
    }
    result.ready = false;
    result.numPhotons = 0;
}

}  // namespace gpu
}  // namespace photon
}  // namespace astroray

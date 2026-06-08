// photon_emission.cu — pkg113 Phase 2 — GPU photon EMISSION + BOUNCE → deposit.
//
// Device port of the GENERAL deterministic-refraction path of the CPU forward
// light tracer (plugins/integrators/light_tracer_caustic.cpp, lines 276-326):
// trace collimated-sun photons through a glass caster (Snell + Schlick-Fresnel +
// enter/exit from the geometric-normal sign + per-λ Sellmeier iorAt + TIR) and
// deposit the surviving per-λ CIE flux as GPhoton records on the receiver plane.
// The Phase-1 store (gpu_photon_store.h) ingests these GPhotons. EMISSION +
// BOUNCE only — no integrator gather (Phase 3). Flat-prism stays CPU (see
// gpu_photon_emit.h header / the research note).
//
// Self-contained single-glass-sphere trace (no full BVH) — the parity harness
// isolates the refraction/deposit MATH against a numpy float64 oracle; the
// integrator scene-upload path is exercised in Phase 3. The aperture is a
// deterministic jittered lattice (NOT curand) so the oracle reproduces the exact
// entry samples and the comparison isolates the math from Monte-Carlo noise.
//
// Citations (CLAUDE.md §6; .astroray_plan/docs/pkg113-phase2-photon-emission-research.md):
//   Arvo 1986 (forward light transport); Jensen 1996 (diffuse photon deposit);
//   Schlick 1994 (Fresnel approx); Sellmeier 1871 (n(λ) — reused via
//   gpu_dispersion.cuh); CIE 1964 10° CMF (data/spectra/cie_cmf.inc).

#include "astroray/gpu_photon_emit.h"
#include "astroray/gpu_photon_store.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_dispersion.cuh"   // gpu_sellmeier_ior (pkg64-gpu Sellmeier)

#include <cuda_runtime.h>

#include <cstdio>
#include <stdexcept>
#include <vector>

#define APE_CUDA_CHECK(call) do {                                           \
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

// --- CIE 1964 10° CMF table (same data the CPU cieCmf1964_10deg reads) -------
// Mirrors multiwavelength_kernel.cu:163-165; the .inc declares
// `static constexpr float kCieCmfX[471] = {...}` plus the range constants. We
// keep the table in a translation-unit-local namespace and copy it to constant
// memory once. The device lookup linearly interpolates the 1 nm grid exactly
// like src/spectrum.cpp::sampleTable, so the GPU per-λ deposit weight matches
// the CPU one to float precision.
namespace cmf_baked {
#include "data/spectra/cie_cmf.inc"
}  // namespace cmf_baked

__constant__ float g_emitCmfX[cmf_baked::kCieCmfCount];
__constant__ float g_emitCmfY[cmf_baked::kCieCmfCount];
__constant__ float g_emitCmfZ[cmf_baked::kCieCmfCount];

void uploadEmitCmf() {
    static bool uploaded = false;
    if (uploaded) return;
    APE_CUDA_CHECK(cudaMemcpyToSymbol(g_emitCmfX, cmf_baked::kCieCmfX,
                                      sizeof(cmf_baked::kCieCmfX)));
    APE_CUDA_CHECK(cudaMemcpyToSymbol(g_emitCmfY, cmf_baked::kCieCmfY,
                                      sizeof(cmf_baked::kCieCmfY)));
    APE_CUDA_CHECK(cudaMemcpyToSymbol(g_emitCmfZ, cmf_baked::kCieCmfZ,
                                      sizeof(cmf_baked::kCieCmfZ)));
    uploaded = true;
}

// Device CMF lookup: 1 nm linear interpolation over [360,830] nm, clamped at the
// ends. Exact port of src/spectrum.cpp::sampleTable (l.40-46).
__device__ inline GVec3 pe_cieCmf(float lambda) {
    const float lmin = 360.0f, step = 1.0f;
    const int count = 471;
    float idx = (lambda - lmin) / step;
    int i = static_cast<int>(idx);
    if (i < 0) {   // below the table -> first sample (CPU clamps via i=0,t=0)
        return GVec3(g_emitCmfX[0], g_emitCmfY[0], g_emitCmfZ[0]);
    }
    if (i >= count - 1) {
        return GVec3(g_emitCmfX[count - 1], g_emitCmfY[count - 1], g_emitCmfZ[count - 1]);
    }
    float t = idx - static_cast<float>(i);
    return GVec3(g_emitCmfX[i] * (1.0f - t) + g_emitCmfX[i + 1] * t,
                 g_emitCmfY[i] * (1.0f - t) + g_emitCmfY[i + 1] * t,
                 g_emitCmfZ[i] * (1.0f - t) + g_emitCmfZ[i + 1] * t);
}

// --- Refraction / Fresnel (identical to light_tracer_caustic.cpp:183-194) ----

// Snell refraction (vector form). d is the unit incident direction, n the
// surface normal oriented against d, eta the relative IOR (n_from/n_to). Returns
// false on total internal reflection. CPU: light_tracer_caustic.cpp:183-189.
__device__ inline bool pe_refract(const GVec3& d, const GVec3& n, float eta, GVec3& out) {
    float cosi = -d.dot(n);
    float s2 = eta * eta * (1.0f - cosi * cosi);
    if (s2 >= 1.0f) return false;          // TIR
    out = (d * eta + n * (eta * cosi - sqrtf(1.0f - s2))).normalized();
    return true;
}

// Schlick-Fresnel TRANSMITTANCE 1 - F. CPU: light_tracer_caustic.cpp:190-194.
__device__ inline float pe_fresnelT(float cosi, float ior) {
    float f0 = (1.0f - ior) / (1.0f + ior); f0 *= f0;
    float fr = f0 + (1.0f - f0) * powf(fmaxf(0.0f, 1.0f - fabsf(cosi)), 5.0f);
    return 1.0f - fr;
}

// --- Single-sphere intersection ----------------------------------------------
// Nearest forward (t > tMin) intersection of (o,d) with the glass sphere. Fills
// the GEOMETRIC outward normal (point - center)/radius (NOT oriented against d —
// the bounce decides enter/exit from d.dot(ng), exactly like the CPU general
// loop uses rec.normal = the geometric outward normal, l.297). Returns t or -1.
__device__ inline float pe_sphereHit(const GVec3& center, float radius,
                                     const GVec3& o, const GVec3& d, float tMin,
                                     GVec3& ngOut) {
    GVec3 oc = o - center;
    float a = d.length2();
    float hb = oc.dot(d);
    float c = oc.length2() - radius * radius;
    float disc = hb * hb - a * c;
    if (disc < 0.0f) return -1.0f;
    float sq = sqrtf(disc);
    float root = (-hb - sq) / a;
    if (root < tMin) {
        root = (-hb + sq) / a;
        if (root < tMin) return -1.0f;
    }
    GVec3 p = o + d * root;
    ngOut = (p - center) * (1.0f / radius);   // geometric outward normal
    return root;
}

// --- Deterministic jittered aperture lattice ---------------------------------
// A van-der-Corput-free, dependency-free stratified jitter from a small integer
// hash, so the host oracle reproduces the SAME entry sample for cell (i,j). This
// replaces the CPU's std::mt19937 u01() draws with a fixed per-cell jitter; the
// parity test passes the IDENTICAL lattice to the numpy oracle (the same tactic
// sms_attempt_device.cuh uses: inject the same samples both sides).
__device__ inline float pe_jitter(unsigned int cell, unsigned int salt) {
    unsigned int h = cell * 0x9E3779B1u + salt * 0x85EBCA77u;
    h ^= h >> 15; h *= 0x2C1B3C6Du; h ^= h >> 12; h *= 0x297A2D39u; h ^= h >> 15;
    return (h & 0x00FFFFFFu) * (1.0f / 16777216.0f);   // [0,1)
}

// --- Emission + bounce kernel ------------------------------------------------
// One thread per aperture cell (apertureN x apertureN). Mirrors the CPU general
// loop (light_tracer_caustic.cpp:282-326): sample a wavelength, seed a photon at
// the aperture, march it through the sphere refracting (or reflecting on TIR)
// accumulating the Schlick transmittance, and deposit on the receiver plane.
// A cell that misses / TIRs out / never reaches the receiver writes a power of 0
// (the host compacts the survivors, mirroring the CPU `photons` vector).
__global__ void kEmitPhotons(GVec3 center, float radius, GDispersion disp,
                             float flatIor, int isDispersive,
                             GVec3 sunDir, GVec3 apOrigin, GVec3 apU, GVec3 apV,
                             float apRadius, float receiverY,
                             int apertureN, float lambdaMin, float lambdaMax,
                             int maxDepth, PhotonEmitDeposit* out) {
    int gx = blockIdx.x * blockDim.x + threadIdx.x;
    int gy = blockIdx.y * blockDim.y + threadIdx.y;
    if (gx >= apertureN || gy >= apertureN) return;
    int cell = gy * apertureN + gx;
    out[cell].power = GVec3(0.f);   // default: dropped
    out[cell].position = GVec3(0.f);
    out[cell].lambda = 0.f;

    // Wavelength: an independent per-cell uniform draw (CPU: λ = lmin +
    // (lmax-lmin)*u01, an independent uniform per photon). pe_jitter is a
    // deterministic per-cell hash so the host oracle reproduces the SAME λ; it
    // is decorrelated from the aperture-position jitters (different salt), so
    // wavelength does not track entry position.
    float uLam = pe_jitter(cell, 101u);
    float lambda = lambdaMin + (lambdaMax - lambdaMin) * uLam;

    float ior = isDispersive ? gpu_sellmeier_ior(disp, lambda) : flatIor;
    if (ior <= 1.0f) ior = 1.5f;   // CPU general loop fallback (l.296)

    // Jittered lattice point on the aperture disc -> a collimated entry ray.
    float jx = (gx + pe_jitter(cell, 1u)) / float(apertureN);   // [0,1)
    float jy = (gy + pe_jitter(cell, 2u)) / float(apertureN);
    float a2 = (jx * 2.0f - 1.0f) * apRadius;
    float b2 = (jy * 2.0f - 1.0f) * apRadius;
    GVec3 o = apOrigin + apU * a2 + apV * b2;
    GVec3 d = sunDir;

    float tr = 1.0f;
    bool passedCaster = false;
    const float eps = 1e-3f;

    for (int bounce = 0; bounce < maxDepth; ++bounce) {
        GVec3 ng;
        float t = pe_sphereHit(center, radius, o, d, eps, ng);
        if (t < 0.0f) {
            // Missed the glass. If we already passed through it, test the
            // receiver plane; else this photon never interacts -> dropped.
            if (!passedCaster) return;
            break;
        }
        // Hit point along the CURRENT (pre-bounce) direction (CPU rec.point).
        GVec3 hitPoint = o + d * t;
        // Transmissive hit: enter/exit from the geometric-normal sign
        // (CPU l.297-303). d.dot(ng) < 0 => entering (eta = 1/ior), else exiting.
        GVec3 nf; float eta;
        if (d.dot(ng) < 0.0f) { nf = ng;        eta = 1.0f / ior; }
        else                  { nf = ng * -1.0f; eta = ior; }
        GVec3 nd;
        if (pe_refract(d, nf, eta, nd)) {
            tr *= pe_fresnelT(d.dot(nf), ior);
            d = nd;
        } else {
            // TIR -> mirror reflect (CPU l.303).
            d = (d - nf * (2.0f * d.dot(nf))).normalized();
        }
        passedCaster = true;
        // Advance from the hit point along the NEW direction (CPU l.310:
        // o = rec.point + d*eps).
        o = hitPoint + d * eps;
    }

    // The structural CPU loop computes the receiver deposit when, after passing
    // the caster, the next BVH hit is a diffuse upward-facing surface. Here the
    // only non-glass surface is the receiver plane (normal +y); intersect it.
    if (!passedCaster || tr <= 0.0f) return;
    if (d.y >= -1e-6f) return;                   // not heading down toward the receiver
    float tPlane = (receiverY - o.y) / d.y;
    if (tPlane <= eps) return;
    GVec3 hit = o + d * tPlane;

    GVec3 cmf = pe_cieCmf(lambda);
    out[cell].position = hit;
    out[cell].power = GVec3(cmf.x * tr, cmf.y * tr, cmf.z * tr);
    out[cell].lambda = lambda;
}

}  // namespace

std::vector<PhotonEmitDeposit> cuda_photon_emit_sphere(
    const PhotonEmitSphereScene& scene) {

    const int n = scene.apertureN * scene.apertureN;
    std::vector<PhotonEmitDeposit> result;
    if (scene.apertureN <= 0 || scene.sphereRadius <= 0.f) return result;

    uploadEmitCmf();

    // Aperture frame around the sun direction (CPU l.219-222).
    GVec3 sunDir = scene.sunDir.normalized();
    GVec3 a = (fabsf(sunDir.x) < 0.9f) ? GVec3(1, 0, 0) : GVec3(0, 1, 0);
    GVec3 apU = (a - sunDir * a.dot(sunDir)).normalized();
    GVec3 apV = sunDir.cross(apU);

    PhotonEmitDeposit* d_out = nullptr;
    APE_CUDA_CHECK(cudaMalloc(&d_out, (size_t)n * sizeof(PhotonEmitDeposit)));

    dim3 block(16, 16);
    dim3 grid((scene.apertureN + block.x - 1) / block.x,
              (scene.apertureN + block.y - 1) / block.y);
    kEmitPhotons<<<grid, block>>>(
        scene.sphereCenter, scene.sphereRadius, scene.dispersion,
        scene.flatIor, scene.isDispersive ? 1 : 0,
        sunDir, scene.apertureCenter, apU, apV,
        scene.apertureRadius, scene.receiverY,
        scene.apertureN, scene.lambdaMin, scene.lambdaMax,
        scene.maxDepth, d_out);
    APE_CUDA_CHECK(cudaGetLastError());
    APE_CUDA_CHECK(cudaDeviceSynchronize());

    std::vector<PhotonEmitDeposit> host(n);
    APE_CUDA_CHECK(cudaMemcpy(host.data(), d_out,
                              (size_t)n * sizeof(PhotonEmitDeposit),
                              cudaMemcpyDeviceToHost));
    cudaFree(d_out);

    // Compact survivors (power.y > 0), mirroring the CPU `photons` vector.
    result.reserve(n);
    for (const auto& dpt : host)
        if (dpt.power.y > 0.f) result.push_back(dpt);
    return result;
}

}  // namespace gpu
}  // namespace photon
}  // namespace astroray

// pkg269 — GPU wavefront heterogeneous (bounded grid / homogeneous) volume stage.
//
// The ONLY wavefront TU that includes the vendored NanoVDB header (Apache-2.0,
// Museth 2021; CMake scopes external/nanovdb to this file like grid_medium.cpp).
// Three rdc-linked pieces:
//   * gpu_gridVolumeTrack          — hero-wavelength spectral-MIS free flight
//                                    (device twin of volume_transport.h
//                                    spectralTrack; pbrt-v4 VolPathIntegrator,
//                                    Apache-2.0; Kutz 2017; research note
//                                    pkg270-spectral-tracking-volume-emission-research.md),
//                                    called from intersectPathSlotT<...,HasGridVolume=true>
//                                    (stage_advance.cu) — the fleet <false> kernels
//                                    never reference it.
//   * gpu_gridVolumeTransmittance  — per-λ ratio tracking (Novák 2014; pbrt-v4
//                                    SampleLd), called from stageShadowKernel behind
//                                    the runtime `c_wfGridVolume.count > 0` gate.
//   * stageVolumeHeteroScatterKernel — the dedicated scatter stage (pkg199
//                                    stageVolumeScatterKernel pattern): medium NEE
//                                    parked into the shared nee lanes + HG
//                                    continuation with the MEDIUM's g. The REG-254
//                                    stageShadeBucketedKernel is never touched.
// Media/grids arrive through the __constant__ side table c_wfGridVolume
// (stage_advance.cu; memory shade-axis-side-table-avoids-spill), which also
// carries the per-path r_u / medium-id lanes (kept out of GPUWavefrontState so no
// fleet kernel's by-value parameter block grows).

#include <nanovdb/NanoVDB.h>

#include "astroray/gpu_wavefront_state.h"
#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"
#include "astroray/sampling/wavefront_rng_device.h"
#include "../profile.h"
#include "../gpu_spectral_tables.h"

#include <cuda_runtime.h>
#include <curand_kernel.h>
#include <cstdint>
#include <cstdio>
#include <stdexcept>

// Per-path PCG32 uniform for gpu_nee.cuh — the same ADL shim stage_advance.cu
// defines (WavefrontRNG lives in namespace astroray).
namespace astroray {
__device__ inline float gpu_rng_uniform(WavefrontRNG* rng) {
    return rng->Uniform();
}
}  // namespace astroray
using astroray::gpu_rng_uniform;
#include "../gpu_nee.cuh"

// Non-inline XYZ wrapper exported by multiwavelength_kernel.cu.
__device__ GVec3 gpu_spectrum_to_xyz(const GSampledSpectrum& s, const GSampledWavelengths& wl);

namespace astroray::wavefront {

// Included INSIDE the namespace, exactly as stage_advance.cu does, so the
// rdc-linked gpu_gridVolume* symbols have the same qualified names in both TUs.
#include "../gpu_volume_phase.cuh"

// Defined in stage_advance.cu (namespace astroray::wavefront; published once per
// frame by setWavefrontGridVolumeBinding / setWavefrontLightPassBinding).
extern __constant__ GWavefrontGridVolumeBinding c_wfGridVolume;
extern __constant__ GWavefrontLightPassBinding  c_wfLpBinding;

namespace {

// Mirrors stage_advance.cu (TU-local there): unset light-path category.
constexpr unsigned char G_LP_CAT_UNSET = 0xFFu;

// D · voxel density at a world point (homogeneous => D). Nearest voxel via the
// NanoVDB accessor — mirrors GridMedium::densityWorld (nearest, not trilinear,
// so the majorant bounds the sampled σ_t exactly).
__device__ inline float gridDensityAt(const GGridMedium& m, const GVec3& p)
{
    if (!m.heterogeneous) return m.densityScale;
    const float* M = m.worldToIndex;
    float ix = M[0] * p.x + M[1] * p.y + M[2]  * p.z + M[3];
    float iy = M[4] * p.x + M[5] * p.y + M[6]  * p.z + M[7];
    float iz = M[8] * p.x + M[9] * p.y + M[10] * p.z + M[11];
    const nanovdb::FloatGrid* g = reinterpret_cast<const nanovdb::FloatGrid*>(m.grid);
    nanovdb::Coord c(__float2int_rn(ix), __float2int_rn(iy), __float2int_rn(iz));
    return m.densityScale * g->tree().getValue(c);
}

// Per-wavelength Cycles coefficients at grid density 1 (device twin of
// principledSpectralCoeffs: JH albedo upsample of the two reflectance-like
// socket colours, then the svm_node_principled_volume formula per λ).
__device__ inline void gridCoeffs(const GGridMedium& m, const GSampledWavelengths& wl,
                                  GSampledSpectrum& sUnit, GSampledSpectrum& aUnit)
{
    GSampledSpectrum c  = gpu_rgbToSampledSpectrum(GVec3(m.colorR, m.colorG, m.colorB),
                                                   wl, GSPEC_RGB_ALBEDO);
    GSampledSpectrum ab = gpu_rgbToSampledSpectrum(GVec3(m.absR, m.absG, m.absB),
                                                   wl, GSPEC_RGB_ALBEDO);
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
        float s = fminf(fmaxf(c.v[i], 0.f), 1.f);
        float a = fmaxf(1.f - s, 0.f) *
                  fmaxf(1.f - sqrtf(fminf(fmaxf(ab.v[i], 0.f), 1.f)), 0.f);
        sUnit.v[i] = s;
        aUnit.v[i] = a;
    }
}

__device__ inline float gridExtinctionMajorant(const GGridMedium& m)
{
    return m.densityScale * m.maxDensity + 1e-8f;
}

}  // namespace

// ---------------------------------------------------------------------------
// Free flight (device twin of astroray::volume::spectralTrack). λ-independent
// majorant σ̄ (exact: s+a <= 1 per λ), so every pbrt T_maj/T_maj[0] factor is 1:
//   emission += beta·Le/(σ̄·avg(r_u)) at every tentative collision,
//   absorb  with pA = σ_a[0]/σ̄ (terminate),
//   scatter with pS = σ_s[0]/σ̄ (beta, r_u *= σ_s/σ_s[0]),
//   null    otherwise            (beta, r_u *= σ_n/σ_n[0]).
// Escaping applies no factor (delta-track survival IS the transmittance).
// Constant emission only on the GPU (blackbody needs the CPU Planck
// normalisation table — pkg270 follow-up); in a GRID medium it is gated on
// density(p) > 0 exactly like the CPU (Cycles bounds-mesh approximation).
// ---------------------------------------------------------------------------
__device__ int gpu_gridVolumeTrack(int mi, const GVec3& o, const GVec3& d,
                                   float tMin, float tMax,
                                   const GSampledWavelengths& wl,
                                   GSampledSpectrum& beta, GSampledSpectrum& r_u,
                                   GSampledSpectrum& emission, float& tOut,
                                   uint32_t rpix, uint32_t rsmp, uint64_t rsd,
                                   uint32_t salt)
{
    const GGridMedium& m = c_wfGridVolume.media[mi];
    GSampledSpectrum sUnit, aUnit;
    gridCoeffs(m, wl, sUnit, aUnit);
    const float sigBar = fmaxf(gridExtinctionMajorant(m), m.emissionFloor + 1e-8f);
    const bool emissive = m.emissionStrength > 0.f;
    GSampledSpectrum Le(0.f);
    if (emissive)
        Le = gpu_rgbToSampledSpectrum(GVec3(m.emisR, m.emisG, m.emisB), wl,
                                      GSPEC_RGB_ILLUMINANT) * m.emissionStrength;
    uint32_t draw = 0;
    float t = tMin;
    for (;;) {
        float xi = gpu_freeflightUniform(rpix, rsmp, rsd, salt + draw++);
        t -= __logf(fmaxf(1e-20f, 1.f - xi)) / sigBar;
        if (t >= tMax) return 0;
        GVec3 p = o + d * t;
        float dens = gridDensityAt(m, p);
        GSampledSpectrum sigS = sUnit * dens;
        GSampledSpectrum sigA = aUnit * dens;
        GSampledSpectrum sigN;
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
            sigN.v[i] = fmaxf(sigBar - sigS.v[i] - sigA.v[i], 0.f);
        if (emissive && (!m.heterogeneous || dens > 0.f)) {
            float w = 1.f / (sigBar * gpu_heroAverage(r_u, wl));
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                emission.v[i] += beta.v[i] * Le.v[i] * w;
        }
        float pAbsorb  = sigA.v[0] / sigBar;
        float pScatter = sigS.v[0] / sigBar;
        float um = gpu_freeflightUniform(rpix, rsmp, rsd, salt + draw++);
        if (um < pAbsorb) {
            beta = GSampledSpectrum(0.f);
            tOut = t;
            return 1;
        } else if (um < pAbsorb + pScatter) {
            float inv = 1.f / sigS.v[0];
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
                float r = sigS.v[i] * inv;
                beta.v[i] *= r; r_u.v[i] *= r;
            }
            tOut = t;
            return 2;
        } else {
            if (sigN.v[0] <= 0.f) {   // pdf 0 for the null branch: pbrt zeroes beta
                beta = GSampledSpectrum(0.f);
                tOut = t;
                return 1;
            }
            float inv = 1.f / sigN.v[0];
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
                float r = sigN.v[i] * inv;
                beta.v[i] *= r; r_u.v[i] *= r;
            }
        }
    }
}

// Per-λ ratio-tracking transmittance (device twin of
// ratioTrackingTransmittanceSpectral): Tr(λ) *= σ_n(λ)/σ̄ at tentative
// collisions shared by all lanes; RR on the max lane below 0.05.
__device__ GSampledSpectrum gpu_gridVolumeTransmittance(int mi, const GVec3& o,
                                                        const GVec3& d, float tMin,
                                                        float tMax,
                                                        const GSampledWavelengths& wl,
                                                        uint32_t rpix, uint32_t rsmp,
                                                        uint64_t rsd, uint32_t salt)
{
    const GGridMedium& m = c_wfGridVolume.media[mi];
    GSampledSpectrum sUnit, aUnit;
    gridCoeffs(m, wl, sUnit, aUnit);
    const float sigBar = gridExtinctionMajorant(m);
    GSampledSpectrum Tr(1.f);
    uint32_t draw = 0;
    float t = tMin;
    for (;;) {
        float xi = gpu_freeflightUniform(rpix, rsmp, rsd, salt + draw++);
        t -= __logf(fmaxf(1e-20f, 1.f - xi)) / sigBar;
        if (t >= tMax) break;
        GVec3 p = o + d * t;
        float dens = gridDensityAt(m, p);
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
            Tr.v[i] *= fmaxf(sigBar - dens * (sUnit.v[i] + aUnit.v[i]), 0.f) / sigBar;
        float mx = Tr.maxValue();
        if (mx < 0.05f) {
            if (gpu_freeflightUniform(rpix, rsmp, rsd, salt + draw++) > mx)
                return GSampledSpectrum(0.f);
            Tr = Tr * (1.f / fmaxf(mx, 1e-20f));
        }
    }
    return Tr;
}

// ---------------------------------------------------------------------------
// Dedicated heterogeneous-medium scatter stage (pkg199 stageVolumeScatterKernel
// pattern, medium g from the side table). Scheduled between the volume-scatter
// stage and shade. Drains the grid queue (slots intersectPathSlot routed via its
// -3 return), parks the phase-sampled medium NEE into the SAME nee_f/nee_i lanes +
// shadow queue the surface NEE uses (stageShadowKernel then applies the grid
// ratio-tracking transmittance + clamp), and emits the HG continuation ray from
// the scatter point, requeuing the survivor. Device twin of the CPU
// pathTraceSpectral bounded-medium scatter branch.
// ---------------------------------------------------------------------------
__global__ void stageVolumeHeteroScatterKernel(
    GPUWavefrontState state,
    const int* grid_queue, const int* grid_count,
    int* queue_out, int* count_out,
    float* nee_f, int* nee_i, int* shadow_queue, int* shadow_count, int nee_capacity,
    const GPrimitive* prims, const GTriangle* tris, const GSphere* spheres,
    const ::GLight* lights, int numLights, float totalLightPower,
    const GDedicatedLight* dedLights, int numDed,
    GLightTreeView lightTree,
    int max_depth,
    bool useLuminanceOutput,
    bool enableNEE)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= *grid_count) return;
    int idx = grid_queue[i];
    if (state.path_alive[idx] == 0) return;
    const int bounce = state.bounce[idx];
    int mid = c_wfGridVolume.mediumId[idx];
    if (mid < 0 || mid >= c_wfGridVolume.count) { state.path_alive[idx] = 0; return; }
    const float g = c_wfGridVolume.media[mid].g;

    // pkg198/pkg204: first-interaction lock to the VOLUME category (CPU:
    // firstInteraction => firstCat = 3) and DIRECT/INDIRECT attribution.
    bool lpVolumeFirst = false;
    if (c_wfLpBinding.passAccum != nullptr) {
        lpVolumeFirst = (c_wfLpBinding.firstCat[idx] == G_LP_CAT_UNSET);
        if (lpVolumeFirst) c_wfLpBinding.firstCat[idx] = 3;
    }

    GVec3 P     = GVec3(state.ray_origin_x[idx], state.ray_origin_y[idx],
                        state.ray_origin_z[idx]);
    GVec3 inDir = GVec3(state.ray_direction_x[idx], state.ray_direction_y[idx],
                        state.ray_direction_z[idx]);
    GVec3 woMedium = (inDir * -1.f).normalized();

    GSampledWavelengths lambdas;
    lambdas.lambda[0] = state.lambda_0[idx]; lambdas.lambda[1] = state.lambda_1[idx];
    lambdas.lambda[2] = state.lambda_2[idx]; lambdas.lambda[3] = state.lambda_3[idx];
    lambdas.pdf[0] = state.lambda_pdf_0[idx]; lambdas.pdf[1] = state.lambda_pdf_1[idx];
    lambdas.pdf[2] = state.lambda_pdf_2[idx]; lambdas.pdf[3] = state.lambda_pdf_3[idx];

    GSampledSpectrum throughput;
    throughput.v[0] = state.throughput_0[idx]; throughput.v[1] = state.throughput_1[idx];
    throughput.v[2] = state.throughput_2[idx]; throughput.v[3] = state.throughput_3[idx];

    WavefrontRNG rng(state.rng_pixel[idx], state.rng_sample[idx], state.rng_seed[idx]);
    rng.setDimension(state.rng_dimension[idx]);

    // ---- Medium NEE (phase / light MIS), parked for the shadow stage ----
    if (enableNEE && (numLights + numDed) > 0 && totalLightPower > 0.f) {
        GHitRecord mrec{};
        mrec.point   = P;
        mrec.normal  = woMedium;
        mrec.isDelta = false;
        GNEESample s = gpu_nee_sample(mrec, prims, tris, spheres,
                                      lights, numLights, totalLightPower,
                                      dedLights, numDed, lightTree, &rng);
        if (s.valid) {
            float ph = gpu_phaseHG(woMedium.dot(s.wi), g);
            if (ph > 0.f) {
                float a2 = s.lightPdf * s.lightPdf;
                float b2 = ph * ph;
                float wt = s.isDeltaLight ? 1.f : a2 / (a2 + b2 + 1e-8f);
                float scale = s.lightPdf > 1e-8f ? wt / s.lightPdf : 0.f;
                if (s.isDedicated) scale *= s.dedGeoScale;
                nee_f[ 0 * nee_capacity + idx] = s.origin.x;
                nee_f[ 1 * nee_capacity + idx] = s.origin.y;
                nee_f[ 2 * nee_capacity + idx] = s.origin.z;
                nee_f[ 3 * nee_capacity + idx] = s.wi.x;
                nee_f[ 4 * nee_capacity + idx] = s.wi.y;
                nee_f[ 5 * nee_capacity + idx] = s.wi.z;
                nee_f[ 6 * nee_capacity + idx] = s.maxDist;
                nee_f[ 7 * nee_capacity + idx] = throughput.v[0] * ph * scale;
                nee_f[ 8 * nee_capacity + idx] = throughput.v[1] * ph * scale;
                nee_f[ 9 * nee_capacity + idx] = throughput.v[2] * ph * scale;
                nee_f[10 * nee_capacity + idx] = throughput.v[3] * ph * scale;
                nee_f[11 * nee_capacity + idx] = s.dedEmissionRGB.x;
                nee_f[12 * nee_capacity + idx] = s.dedEmissionRGB.y;
                nee_f[13 * nee_capacity + idx] = s.dedEmissionRGB.z;
                nee_f[14 * nee_capacity + idx] = s.geomDist;
                nee_i[ 0 * nee_capacity + idx] = s.lightMatId;
                nee_i[ 1 * nee_capacity + idx] = s.isSphere;
                nee_i[ 2 * nee_capacity + idx] = s.isDedicated;
                nee_i[ 3 * nee_capacity + idx] = bounce;
                nee_i[ 5 * nee_capacity + idx] = s.dedEmissionProfileIndex;
                nee_i[ 4 * nee_capacity + idx] =
                    lpVolumeFirst ? (bounce + 1) : -(bounce + 1);
                int qslot = atomicAdd(shadow_count, 1);
                shadow_queue[qslot] = idx;
            }
        }
    }

    // ---- HG phase-sampled continuation from P (throughput *= phase/pdf = 1) ----
    float phasePdf;
    GVec3 wiCont = gpu_sampleHG(woMedium, g, rng.Uniform(), rng.Uniform(), phasePdf);

    if (bounce > 3) {
        float p;
        if (useLuminanceOutput) {
            float L = 0.f;
            for (int k = 0; k < G_SPECTRUM_SAMPLES; ++k) L += throughput.v[k];
            p = fminf(0.95f, fmaxf(0.f, L / float(G_SPECTRUM_SAMPLES)));
        } else {
            GVec3 xyz = gpu_spectrum_to_xyz(throughput, lambdas);
            p = fminf(0.95f, fmaxf(0.f, xyz.y));
        }
        if (rng.Uniform() > p) {
            state.path_alive[idx] = 0;
            state.rng_dimension[idx] = rng.dimension();
            return;
        }
        if (p > 0.f) for (int k = 0; k < G_SPECTRUM_SAMPLES; ++k) throughput.v[k] *= (1.f / p);
    }

    state.ray_direction_x[idx] = wiCont.x;
    state.ray_direction_y[idx] = wiCont.y;
    state.ray_direction_z[idx] = wiCont.z;
    state.throughput_0[idx] = throughput.v[0];
    state.throughput_1[idx] = throughput.v[1];
    state.throughput_2[idx] = throughput.v[2];
    state.throughput_3[idx] = throughput.v[3];
    state.was_specular[idx]  = 0;
    state.env_nee_sampled_prev[idx] = 0;
    state.path_bsdf_pdf[idx] = phasePdf;
    state.rng_dimension[idx] = rng.dimension();
    int next_bounce = bounce + 1;
    state.bounce[idx] = next_bounce;
    if (next_bounce >= max_depth) { state.path_alive[idx] = 0; return; }
    int slot = atomicAdd(count_out, 1);
    queue_out[slot] = idx;
}

void launchStageVolumeHeteroScatter(
    GPUWavefrontState& state,
    const int* d_grid_queue, const int* d_grid_count,
    int* d_queue_out, int* d_count_out,
    float* d_nee_f, int* d_nee_i, int* d_shadow_queue, int* d_shadow_count,
    int nee_capacity,
    const GPrimitive* d_prims, const GTriangle* d_tris, const GSphere* d_spheres,
    const ::GLight* d_lights, int num_lights, float total_light_power,
    const GDedicatedLight* d_dedLights, int num_ded,
    GLightTreeView lightTree,
    int max_depth, bool useLuminanceOutput, bool enableNEE)
{
    if (state.num_active <= 0) return;
    int threads = 256;
    int blocks  = (state.num_active + threads - 1) / threads;
    {
        astroray::gpu_profile::ScopedTimer _t(
            "wavefront_stage_volume_hetero_scatter",
            (const void*)stageVolumeHeteroScatterKernel, blocks, threads);
        stageVolumeHeteroScatterKernel<<<blocks, threads>>>(
            state, d_grid_queue, d_grid_count, d_queue_out, d_count_out,
            d_nee_f, d_nee_i, d_shadow_queue, d_shadow_count, nee_capacity,
            d_prims, d_tris, d_spheres,
            d_lights, num_lights, total_light_power,
            d_dedLights, num_ded, lightTree,
            max_depth, useLuminanceOutput, enableNEE);
        cudaError_t err = cudaGetLastError();
        if (err != cudaSuccess) {
            std::fprintf(stderr, "stage_volume_hetero_scatter launch error: %s\n",
                         cudaGetErrorString(err));
            throw std::runtime_error(cudaGetErrorString(err));
        }
    }
}

}  // namespace astroray::wavefront

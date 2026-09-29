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

// #929: counter-based stream for the volume-segment direct light, which runs in
// the intersect stage (no WavefrontRNG / rng_dimension round-trip there). Found
// by ADL from the gpu_nee.cuh templates.
struct GSegRng {
    uint32_t rpix, rsmp;
    uint64_t rsd;
    uint32_t salt, draw;
};
__device__ inline float gpu_rng_uniform(GSegRng* r)
{
    return gpu_freeflightUniform(r->rpix, r->rsmp, r->rsd,
                                 r->salt + (r->draw++ & G_WF_SEG_DRAW_MASK));
}

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

// #828 — nearest-voxel temperature grid value at a world point (0 outside).
// Device twin of GridMedium::temperatureWorld: the density grid's world->index
// affine, std::lround-style rounding (lroundf), the dense block's own origin.
__device__ inline float gridTemperatureAt(const GGridMedium& m, const GVec3& p)
{
    const float* M = m.worldToIndex;
    float ix = M[0] * p.x + M[1] * p.y + M[2]  * p.z + M[3];
    float iy = M[4] * p.x + M[5] * p.y + M[6]  * p.z + M[7];
    float iz = M[8] * p.x + M[9] * p.y + M[10] * p.z + M[11];
    int x = (int)lroundf(ix) - m.tempBboxMin[0];
    int y = (int)lroundf(iy) - m.tempBboxMin[1];
    int z = (int)lroundf(iz) - m.tempBboxMin[2];
    if (x < 0 || y < 0 || z < 0 || x >= m.tempDim[0] || y >= m.tempDim[1] || z >= m.tempDim[2])
        return 0.f;
    return m.tempGrid[((size_t)z * m.tempDim[1] + y) * m.tempDim[0] + x];
}

// #828 — blackbody emission per unit length at temperature T (device twin of
// VolumeEmission::evalBlackbody): Cycles σ_SB·1e-6/π·mix(1,T⁴,I) × tint(λ) ×
// normalised Planck(λ,T) — the SAME bbNormalizedPlanck formula and table the
// CPU uses (include/astroray/volume/blackbody_lut.h).
__device__ inline GSampledSpectrum gridBlackbody(const GGridMedium& m, float T,
                                                 const GSampledWavelengths& wl)
{
    GSampledSpectrum s(0.f);
    float T2 = T * T;
    const float sigma = 5.670373e-8f * 1e-6f / M_PI_F;
    float intensity = sigma * ((1.f - m.blackbodyIntensity) + m.blackbodyIntensity * T2 * T2);
    if (!(intensity > 0.f)) return s;
    GSampledSpectrum tint(1.f);
    if (!m.bbTintIsWhite)
        tint = gpu_rgbToSampledSpectrum(GVec3(m.bbTintR, m.bbTintG, m.bbTintB), wl,
                                        GSPEC_RGB_ALBEDO);
    const float* lut = g_bbLogLum;   // ABI-3: hoisted out of the lane loop
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
        s.v[i] = astroray::volume::bbNormalizedPlanck(wl.lambda[i], T, lut)
                 * intensity * tint.v[i];
    return s;
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
// Emission = constant (Emission Strength × Color) + #828 blackbody, gated like
// the CPU BoundedMedium::emissionAt: in a GRID medium the constant term (and a
// grid-less blackbody) needs density(p) > 0 (Cycles bounds-mesh approximation);
// with a temperature grid T = Temperature × grid(p).
// pkg271 noScatter: scatter collisions absorb (volume_bounces exhausted).
// ---------------------------------------------------------------------------
__device__ int gpu_gridVolumeTrack(int mi, const GVec3& o, const GVec3& d,
                                   float tMin, float tMax,
                                   const GSampledWavelengths& wl,
                                   GSampledSpectrum& beta, GSampledSpectrum& r_u,
                                   GSampledSpectrum& emission, float& tOut,
                                   uint32_t rpix, uint32_t rsmp, uint64_t rsd,
                                   uint32_t salt, uint32_t& draw, bool noScatter)
{
    const GGridMedium& m = c_wfGridVolume.media[mi];
    GSampledSpectrum sUnit, aUnit;
    gridCoeffs(m, wl, sUnit, aUnit);
    const float sigBar = fmaxf(gridExtinctionMajorant(m), m.emissionFloor + 1e-8f);
    const bool hasConst = m.emissionStrength > 0.f;
    const bool hasBB = m.blackbodyIntensity > 0.f;
    GSampledSpectrum Le(0.f);
    if (hasConst)
        Le = gpu_rgbToSampledSpectrum(GVec3(m.emisR, m.emisG, m.emisB), wl,
                                      GSPEC_RGB_ILLUMINANT) * m.emissionStrength;
    float t = tMin;
    for (;;) {
        float xi = gpu_freeflightUniform(rpix, rsmp, rsd, salt + (draw++ & G_WF_GRID_DRAW_MASK));
        t -= __logf(fmaxf(1e-20f, 1.f - xi)) / sigBar;
        if (t >= tMax) return 0;
        GVec3 p = o + d * t;
        float dens = gridDensityAt(m, p);
        GSampledSpectrum sigS = sUnit * dens;
        GSampledSpectrum sigA = aUnit * dens;
        GSampledSpectrum sigN;
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
            sigN.v[i] = fmaxf(sigBar - sigS.v[i] - sigA.v[i], 0.f);
        if (hasConst || hasBB) {
            const bool inActive = !m.heterogeneous || dens > 0.f;
            GSampledSpectrum e(0.f);
            if (hasConst && inActive) e = Le;
            if (hasBB) {
                float T = m.tempGrid ? m.temperature * gridTemperatureAt(m, p)
                                     : (inActive ? m.temperature : 0.f);
                if (T > 0.f) e += gridBlackbody(m, T, wl);
            }
            if (e.maxValue() > 0.f) {
                float w = 1.f / (sigBar * gpu_heroAverage(r_u, wl));
                for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                    emission.v[i] += beta.v[i] * e.v[i] * w;
            }
        }
        // #929 (CPU #925 twin): absorption as a weight (Cycles shade_volume.h). A
        // real collision (pdf σ_t[0]/σ̄) scatters with beta *= σ_s/σ_t[0],
        // r_u *= σ_t/σ_t[0]; noScatter keeps the analog termination.
        float pReal = (sigA.v[0] + sigS.v[0]) / sigBar;
        float um = gpu_freeflightUniform(rpix, rsmp, rsd, salt + (draw++ & G_WF_GRID_DRAW_MASK));
        if (um < pReal) {
            if (noScatter || !(sigS.maxValue() > 0.f)) {
                beta = GSampledSpectrum(0.f);
                tOut = t;
                return 1;
            }
            float inv = 1.f / (sigS.v[0] + sigA.v[0]);
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
                beta.v[i] *= sigS.v[i] * inv;
                r_u.v[i] *= (sigS.v[i] + sigA.v[i]) * inv;
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

// #842 — free flight where the media in `mask` (>= 2) overlap on [tMin,tMax]
// (device twin of astroray::volume::spectralTrackOverlap). σ̄ = Σ σ̄_k; the
// coefficients and emission add (Cycles volume stack); each medium's scattering
// is its own collision type, `which` = the medium a scatter uses. Coefficients
// are recomputed per collision (no per-medium arrays: overlap is rare and this
// keeps the intersect kernel's stack flat).
__device__ int gpu_gridVolumeTrackOverlap(uint32_t mask, const GVec3& o, const GVec3& d,
                                          float tMin, float tMax,
                                          const GSampledWavelengths& wl,
                                          GSampledSpectrum& beta, GSampledSpectrum& r_u,
                                          GSampledSpectrum& emission, float& tOut, int& which,
                                          uint32_t rpix, uint32_t rsmp, uint64_t rsd,
                                          uint32_t salt, uint32_t& draw, bool noScatter)
{
    float sigBar = 0.f;
    for (int k = 0; k < c_wfGridVolume.count; ++k)
        if (mask & (1u << k)) {
            const GGridMedium& m = c_wfGridVolume.media[k];
            sigBar += fmaxf(gridExtinctionMajorant(m), m.emissionFloor + 1e-8f);
        }
    float t = tMin;
    for (;;) {
        float xi = gpu_freeflightUniform(rpix, rsmp, rsd, salt + (draw++ & G_WF_GRID_DRAW_MASK));
        t -= __logf(fmaxf(1e-20f, 1.f - xi)) / sigBar;
        if (t >= tMax) return 0;
        GVec3 p = o + d * t;
        GSampledSpectrum sigS(0.f), sigA(0.f), e(0.f);
        for (int k = 0; k < c_wfGridVolume.count; ++k) {
            if (!(mask & (1u << k))) continue;
            const GGridMedium& m = c_wfGridVolume.media[k];
            GSampledSpectrum sUnit, aUnit;
            gridCoeffs(m, wl, sUnit, aUnit);
            float dens = gridDensityAt(m, p);
            sigS += sUnit * dens;
            sigA += aUnit * dens;
            const bool inActive = !m.heterogeneous || dens > 0.f;
            if (m.emissionStrength > 0.f && inActive)
                e += gpu_rgbToSampledSpectrum(GVec3(m.emisR, m.emisG, m.emisB), wl,
                                              GSPEC_RGB_ILLUMINANT) * m.emissionStrength;
            if (m.blackbodyIntensity > 0.f) {
                float T = m.tempGrid ? m.temperature * gridTemperatureAt(m, p)
                                     : (inActive ? m.temperature : 0.f);
                if (T > 0.f) e += gridBlackbody(m, T, wl);
            }
        }
        if (e.maxValue() > 0.f) {
            float w = 1.f / (sigBar * gpu_heroAverage(r_u, wl));
            for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
                emission.v[i] += beta.v[i] * e.v[i] * w;
        }
        // #929 (CPU #925 twin): absorption as a weight. A real collision with
        // medium k has pdf σ_t,k[0]/σ̄; beta *= σ_s,k/σ_t,k[0], r_u *= σ_t,k/σ_t,k[0].
        float um = gpu_freeflightUniform(rpix, rsmp, rsd, salt + (draw++ & G_WF_GRID_DRAW_MASK));
        if (noScatter) {
            if (um < (sigS.v[0] + sigA.v[0]) / sigBar) {
                beta = GSampledSpectrum(0.f);
                tOut = t;
                return 1;
            }
        } else {
            float cum = 0.f;
            for (int k = 0; k < c_wfGridVolume.count; ++k) {
                if (!(mask & (1u << k))) continue;
                const GGridMedium& m = c_wfGridVolume.media[k];
                GSampledSpectrum sUnit, aUnit;
                gridCoeffs(m, wl, sUnit, aUnit);
                const float dens = gridDensityAt(m, p);
                GSampledSpectrum sk = sUnit * dens;
                GSampledSpectrum tk = (sUnit + aUnit) * dens;
                if (tk.v[0] <= 0.f) continue;
                cum += tk.v[0] / sigBar;
                if (um < cum) {
                    if (!(sk.maxValue() > 0.f)) {
                        beta = GSampledSpectrum(0.f);
                        tOut = t;
                        return 1;
                    }
                    float inv = 1.f / tk.v[0];
                    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) {
                        beta.v[i] *= sk.v[i] * inv;
                        r_u.v[i] *= tk.v[i] * inv;
                    }
                    tOut = t;
                    which = k;
                    return 2;
                }
            }
        }
        GSampledSpectrum sigN;
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
            sigN.v[i] = fmaxf(sigBar - sigS.v[i] - sigA.v[i], 0.f);
        if (sigN.v[0] <= 0.f) {
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
    GSampledSpectrum Tr(1.f);
    if (!m.heterogeneous) {   // #929 (CPU #925 twin): exact Beer-Lambert
        const float len = fmaxf(tMax - tMin, 0.f);
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
            Tr.v[i] = __expf(-m.densityScale * (sUnit.v[i] + aUnit.v[i]) * len);
        return Tr;
    }
    const float sigBar = gridExtinctionMajorant(m);
    uint32_t draw = 0;
    float t = tMin;
    for (;;) {
        float xi = gpu_freeflightUniform(rpix, rsmp, rsd,
                                         salt + (draw++ & G_WF_GRIDSHADOW_DRAW_MASK));
        t -= __logf(fmaxf(1e-20f, 1.f - xi)) / sigBar;
        if (t >= tMax) break;
        GVec3 p = o + d * t;
        float dens = gridDensityAt(m, p);
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
            Tr.v[i] *= fmaxf(sigBar - dens * (sUnit.v[i] + aUnit.v[i]), 0.f) / sigBar;
        float mx = Tr.maxValue();
        if (mx < 0.05f) {
            if (gpu_freeflightUniform(rpix, rsmp, rsd,
                                      salt + (draw++ & G_WF_GRIDSHADOW_DRAW_MASK)) > mx)
                return GSampledSpectrum(0.f);
            Tr = Tr * (1.f / fmaxf(mx, 1e-20f));
        }
    }
    return Tr;
}

// ---------------------------------------------------------------------------
// #929 — per-segment volume direct light (GPU twin of the CPU #925 estimator).
// Source: Kulla & Fajardo, "Importance Sampling Techniques for Path Tracing in
// Participating Media", EGSR 2012, DOI:10.1111/j.1467-8659.2012.03145.x.
// Reference impl: Blender Cycles src/kernel/integrator/shade_volume.h
// (integrate_volume_sample_direct_light, volume_valid_direct_ray_segment,
// volume_direct_scatter_mis, integrate_volume_direct_light), Apache-2.0.
// CPU twin (mirrored line for line): include/raytracer.h segmentDirectLight /
// boundedSegmentDirect, volume_transport.h sampleSegmentDirect,
// src/lights/{spot,area}_light.cpp clipLitSegment. Research:
// .astroray_plan/docs/issue925-volume-segment-direct-light-research.md.
// ---------------------------------------------------------------------------
namespace {

// SpotLight::clipLitSegment twin (double, as on the CPU): conservative cone
// (outer angle + 1e-3, apex pulled back by r/sin θ so it contains the lamp).
__device__ bool segClipSpot(const GDedicatedLight& L, const GVec3& o, const GVec3& d,
                            float& t0, float& t1)
{
    const double th = (double)acosf(fminf(fmaxf(L.cosOuter, -1.f), 1.f)) + 1e-3;
    if (th >= 1.55) return true;
    const double kInf = 1e300;
    const double sinT = sin(th), cosT = cos(th), c2 = cosT * cosT;
    const double ax = L.axis.x, ay = L.axis.y, az = L.axis.z;
    const double pull = (double)L.radius / sinT;
    const double cox = (double)o.x - ((double)L.position.x - ax * pull);
    const double coy = (double)o.y - ((double)L.position.y - ay * pull);
    const double coz = (double)o.z - ((double)L.position.z - az * pull);
    const double dx = d.x, dy = d.y, dz = d.z;
    const double dv = dx * ax + dy * ay + dz * az;
    const double cv = cox * ax + coy * ay + coz * az;
    double lo = t0, hi = t1;
    if (fabs(dv) < 1e-12) {                       // positive nappe only
        if (cv < 0.0) return false;
    } else if (dv > 0.0) {
        lo = fmax(lo, -cv / dv);
    } else {
        hi = fmin(hi, -cv / dv);
    }
    if (!(lo <= hi)) return false;
    // Inside the double cone: (cv + t dv)^2 - cos^2 |co + t d|^2 >= 0.
    const double qa = dv * dv - c2;
    const double qb = 2.0 * (cv * dv - c2 * (cox * dx + coy * dy + coz * dz));
    const double qc = cv * cv - c2 * (cox * cox + coy * coy + coz * coz);
    double p0[2], p1[2];
    int n = 0;
    if (fabs(qa) < 1e-12) {
        if (fabs(qb) < 1e-18) { if (qc < 0.0) return false; p0[n] = -kInf; p1[n++] = kInf; }
        else if (qb > 0.0) { p0[n] = -qc / qb; p1[n++] = kInf; }
        else { p0[n] = -kInf; p1[n++] = -qc / qb; }
    } else {
        const double disc = qb * qb - 4.0 * qa * qc;
        if (disc < 0.0) {
            if (qa < 0.0) return false;
            p0[n] = -kInf; p1[n++] = kInf;
        } else {
            const double sq = sqrt(disc);
            double r1 = (-qb - sq) / (2.0 * qa), r2 = (-qb + sq) / (2.0 * qa);
            if (r1 > r2) { const double tmp = r1; r1 = r2; r2 = tmp; }
            if (qa > 0.0) {
                p0[n] = -kInf; p1[n++] = r1;
                p0[n] = r2;    p1[n++] = kInf;
            } else {
                p0[n] = r1; p1[n++] = r2;
            }
        }
    }
    // Within the half-space the cone is convex: hull of what survives.
    double nlo = kInf, nhi = -kInf;
    for (int k = 0; k < n; ++k) {
        const double pad = 1e-4 * (1.0 + fmin(fabs(p0[k]), fabs(p1[k])));
        const double s = fmax(lo, p0[k] - pad), e = fmin(hi, p1[k] + pad);
        if (s <= e) { nlo = fmin(nlo, s); nhi = fmax(nhi, e); }
    }
    if (!(nlo <= nhi)) return false;
    t0 = (float)nlo;
    t1 = (float)nhi;
    return true;
}

// AreaLight::clipLitSegment twin: one-sided emitter lights the half-space in
// front of its plane (d.axis = area normal).
__device__ bool segClipArea(const GDedicatedLight& L, const GVec3& o, const GVec3& d,
                            float& t0, float& t1)
{
    const float s0 = (o - L.position).dot(L.axis);
    const float dn = d.dot(L.axis);
    if (fabsf(dn) < 1e-12f) return s0 > 0.f;
    const float tp = -s0 / dn;
    if (dn > 0.f) t0 = fmaxf(t0, tp);
    else t1 = fminf(t1, tp);
    return t0 < t1;
}

// Lane-mixture truncated-exponential pdf on [a, a+L] (sampleSegmentDirect).
__device__ float segPdfDist(float t, float a, float L, bool finite,
                            const GSampledSpectrum& rate, const int* valid, int nValid)
{
    if (nValid == 0) return 0.f;
    float s = 0.f;
    for (int k = 0; k < nValid; ++k) {
        const float r = rate.v[valid[k]];
        if (r <= 1e-12f) { s += 1.f / L; continue; }
        const float norm = finite ? -expm1f(-r * L) : 1.f;
        s += r * __expf(-r * (t - a)) / norm;
    }
    return s / float(nValid);
}

struct GSegDistance { float t, w; };

// volume::sampleSegmentDirect twin: one distance on [a,b] (b >= 1e18 = open),
// equiangular about `anchor` (K&F 2012 Eq. 6-7) vs the per-λ exponential
// mixture, each with probability 1/2, w = 2·pc/(pc²+po²) (power heuristic / pdf).
__device__ GSegDistance segSampleDistance(const GVec3& o, const GVec3& d, float a, float b,
                                          bool hasAnchor, const GVec3& anchor,
                                          const GSampledSpectrum& rate, GSegRng& rng)
{
    GSegDistance out{0.f, 0.f};
    const bool finite = b < 1e18f;
    const float L = finite ? b - a : 1e30f;
    if (!(L > 0.f)) return out;
    int valid[G_SPECTRUM_SAMPLES];
    int nValid = 0;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i)
        if (rate.v[i] > 1e-12f || finite) valid[nValid++] = i;
    const float tc = (anchor - o).dot(d);
    const float D = fmaxf((anchor - (o + d * tc)).length(), 1e-4f);
    const float thA = atan2f(a - tc, D);
    const float thB = finite ? atan2f(b - tc, D) : 1.5707962f;
    const bool eqOk = hasAnchor && thB - thA > 1e-7f;
    const bool distOk = nValid > 0;
    if (!eqOk && !distOk) return out;
    const bool both = eqOk && distOk;
    const bool pickEq = both ? (gpu_rng_uniform(&rng) >= 0.5f) : eqOk;
    float t;
    if (pickEq) {
        const float th = thA + gpu_rng_uniform(&rng) * (thB - thA);
        t = tc + D * tanf(th);
    } else {
        const int c = valid[min(int(gpu_rng_uniform(&rng) * nValid), nValid - 1)];
        const float r = rate.v[c], xi = gpu_rng_uniform(&rng);
        if (r <= 1e-12f) t = a + xi * L;
        else t = a - log1pf(-xi * (finite ? -expm1f(-r * L) : 1.f)) / r;
    }
    if (!(t >= a && t <= b) || !isfinite(t)) return out;
    auto pdfEq = [&](float tt) {
        if (!eqOk || tt < a || tt > b) return 0.f;
        const float dt = tt - tc;
        return D / ((thB - thA) * (D * D + dt * dt));
    };
    const float pc = pickEq ? pdfEq(t) : segPdfDist(t, a, L, finite, rate, valid, nValid);
    if (!(pc > 0.f)) return out;
    out.t = t;
    if (both) {
        const float po = pickEq ? segPdfDist(t, a, L, finite, rate, valid, nValid) : pdfEq(t);
        out.w = 2.f * pc / (pc * pc + po * po);
    } else {
        out.w = 1.f / pc;
    }
    return out;
}

__device__ inline bool segInsideAabb(const GGridMedium& m, const GVec3& P)
{
    return !(P.x < m.aabbMin[0] || P.x > m.aabbMax[0] || P.y < m.aabbMin[1] ||
             P.y > m.aabbMax[1] || P.z < m.aabbMin[2] || P.z > m.aabbMax[2]);
}

}  // namespace

__device__ void gpu_volumeSegmentDirect(
    int idx, int bounce, int kind, const GVec3& o, const GVec3& d, float a, float b,
    GSampledSpectrum rate, const GSampledSpectrum& throughput,
    const GSampledWavelengths& wl, float fogAlbedo, float fogG,
    const GPrimitive* prims, const GTriangle* tris, const GSphere* spheres,
    const GLight* lights, int numLights, float totalLightPower,
    const GDedicatedLight* dedLights, int numDed, const GLightTreeView& lightTree,
    uint32_t rpix, uint32_t rsmp, uint64_t rsd)
{
    const int cap = c_wfGridVolume.segCapacity;
    if (cap <= 0 || (numLights + numDed) <= 0 || !(totalLightPower > 0.f)) return;
    if (kind == 0) {
        // boundedSegmentDirect: hull of the media on [a,b]; distance rate =
        // Σ_k per-λ σ_t majorant (exact for one homogeneous medium).
        float lo = 3.4e38f, hi = 0.f;
        rate = GSampledSpectrum(0.f);
        for (int k = 0; k < c_wfGridVolume.count; ++k) {
            const GGridMedium& m = c_wfGridVolume.media[k];
            float t0, t1;
            if (!gpu_gridAabbOverlap(m, o, d, a, b, t0, t1)) continue;
            lo = fminf(lo, t0);
            hi = fmaxf(hi, t1);
            GSampledSpectrum sU, aU;
            gridCoeffs(m, wl, sU, aU);
            rate += (sU + aU) * (m.densityScale * m.maxDensity);
        }
        if (!(hi > lo)) return;
        a = lo;
        b = hi;
    }
    GSegRng rng{rpix, rsmp, rsd, gpu_segSalt(bounce, kind), 0u};
    float mr = 0.f;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) mr += rate.v[i];
    mr /= float(G_SPECTRUM_SAMPLES);
    // CPU refPoint: clipped midpoint, or one mean free path past `a` if open.
    auto refPoint = [&](float lo, float hi) {
        const float tr = (hi < 1e18f) ? 0.5f * (lo + hi) : lo + (mr > 0.f ? 1.f / mr : 0.f);
        return o + d * tr;
    };
    // Power sampler: pick once, clip to the lamp's lit region, re-sample the
    // SAME light for the anchor and at P. Light tree: fresh picks (CPU note).
    const bool same = !lightTree.enabled;
    int li = 0, dj = -1;
    float selPdf = 0.f;
    GNEESample anc;
    if (same) {
        selPdf = gpu_power_light_pick(gpu_rng_uniform(&rng), lights, numLights,
                                      totalLightPower, dedLights, numDed, li, dj);
        if (!(selPdf > 0.f)) return;
        if (dj >= 0) {
            const GDedicatedLight& L = dedLights[dj];
            if (L.kind == GDED_SPOT && !segClipSpot(L, o, d, a, b)) return;
            if (L.kind == GDED_AREA && !segClipArea(L, o, d, a, b)) return;
        }
        // pkg294: area-uniform anchor on an area lamp (Cycles area_light_eval<true>).
        anc = gpu_nee_sample_light(refPoint(a, b), li, dj, selPdf, prims, tris, spheres,
                                   lights, dedLights, &rng, /*segAnchor=*/true);
    } else {
        GHitRecord r{};
        r.point = refPoint(a, b);
        r.normal = GVec3(0.f, 0.f, 0.f);
        r.isDelta = false;
        anc = gpu_nee_sample(r, prims, tris, spheres, lights, numLights, totalLightPower,
                             dedLights, numDed, lightTree, &rng, /*segAnchor=*/true);
    }
    const bool hasAnchor = anc.valid && anc.lightPdf > 0.f && anc.geomDist > 0.f &&
                           anc.geomDist < 1e18f;
    const GVec3 anchor = hasAnchor ? anc.origin + anc.wi * anc.geomDist : o;
    const GSegDistance ds = segSampleDistance(o, d, a, b, hasAnchor, anchor, rate, rng);
    if (!(ds.w > 0.f)) return;
    const GVec3 P = o + d * ds.t;

    // Medium at P: component count + Tr from the segment start to t.
    GSampledSpectrum TrP(1.f);
    int n = 0;
    if (kind == 1) {
        n = 1;
        for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) TrP.v[i] = __expf(-rate.v[i] * ds.t);
    } else {
        for (int k = 0; k < c_wfGridVolume.count; ++k) {
            const GGridMedium& m = c_wfGridVolume.media[k];
            if (segInsideAabb(m, P) && gridDensityAt(m, P) > 0.f) ++n;
        }
        if (n > 0)
            for (int k = 0; k < c_wfGridVolume.count; ++k) {
                float s0, s1;
                if (gpu_gridAabbOverlap(c_wfGridVolume.media[k], o, d, 0.001f, ds.t, s0, s1))
                    TrP *= gpu_gridVolumeTransmittance(k, o, d, s0, s1, wl, rpix, rsmp, rsd,
                                                       gpu_segSalt(bounce, 2 + k));
            }
    }
    if (n <= 0 || !(TrP.maxValue() > 0.f)) return;

    GNEESample s;
    if (same) {
        s = gpu_nee_sample_light(P, li, dj, selPdf, prims, tris, spheres, lights, dedLights, &rng);
    } else {
        GHitRecord r{};
        r.point = P;
        r.normal = GVec3(0.f, 0.f, 0.f);
        r.isDelta = false;
        s = gpu_nee_sample(r, prims, tris, spheres, lights, numLights, totalLightPower,
                           dedLights, numDed, lightTree, &rng);
    }
    if (!s.valid || !(s.lightPdf > 1e-8f)) return;
    // Each phase component MIS'd against its own HG pdf (the complement of the
    // lamp-hit weight after a phase-sampled continuation from that medium).
    const GVec3 wo = d * -1.f;
    const float lp2 = s.lightPdf * s.lightPdf;
    GSampledSpectrum sum(0.f);
    if (kind == 1) {
        const float ph = gpu_phaseHG(wo.dot(s.wi), fogG);
        const float w = s.isDeltaLight ? 1.f : lp2 / (lp2 + ph * ph + 1e-8f);
        sum = rate * (fogAlbedo * ph * w);
    } else {
        for (int k = 0; k < c_wfGridVolume.count; ++k) {
            const GGridMedium& m = c_wfGridVolume.media[k];
            if (!segInsideAabb(m, P)) continue;
            const float dens = gridDensityAt(m, P);
            if (dens <= 0.f) continue;
            GSampledSpectrum sU, aU;
            gridCoeffs(m, wl, sU, aU);
            const float ph = gpu_phaseHG(wo.dot(s.wi), m.g);
            const float w = s.isDeltaLight ? 1.f : lp2 / (lp2 + ph * ph + 1e-8f);
            sum += sU * (dens * ph * w);
        }
    }
    if (!(sum.maxValue() > 0.f)) return;
    float scale = ds.w / s.lightPdf;
    if (s.isDedicated) scale *= s.dedGeoScale;
    const GSampledSpectrum c = throughput * sum * TrP * scale;

    // Park into segment block `kind` (standard NEE lane layout).
    float* f = c_wfGridVolume.segNeeF + (size_t)kind * G_WF_NEE_F_LANES * cap;
    int*   q = c_wfGridVolume.segNeeI + (size_t)kind * G_WF_NEE_I_LANES * cap;
    f[ 0 * cap + idx] = s.origin.x;
    f[ 1 * cap + idx] = s.origin.y;
    f[ 2 * cap + idx] = s.origin.z;
    f[ 3 * cap + idx] = s.wi.x;
    f[ 4 * cap + idx] = s.wi.y;
    f[ 5 * cap + idx] = s.wi.z;
    f[ 6 * cap + idx] = s.maxDist;
    f[ 7 * cap + idx] = c.v[0];
    f[ 8 * cap + idx] = c.v[1];
    f[ 9 * cap + idx] = c.v[2];
    f[10 * cap + idx] = c.v[3];
    f[11 * cap + idx] = s.dedEmissionRGB.x;
    f[12 * cap + idx] = s.dedEmissionRGB.y;
    f[13 * cap + idx] = s.dedEmissionRGB.z;
    f[14 * cap + idx] = s.geomDist;
    q[0 * cap + idx] = s.lightMatId;
    q[1 * cap + idx] = s.isSphere | (s.lightBack << 1);   // bit 1: triangle back face
    q[2 * cap + idx] = s.isDedicated;
    q[3 * cap + idx] = bounce;
    // CPU pass: firstCat < 0 ? PASS_VOLUME_DIRECT : PASS_VOLUME_INDIRECT.
    const bool unlocked = c_wfLpBinding.passAccum == nullptr ||
                          c_wfLpBinding.firstCat[idx] == G_LP_CAT_UNSET;
    q[4 * cap + idx] = unlocked ? (bounce + 1) : -(bounce + 1);
    q[5 * cap + idx] = s.dedEmissionProfileIndex;
    const int slot = atomicAdd(&c_wfGridVolume.segShadowCount[kind], 1);
    c_wfGridVolume.segShadowQueue[kind * cap + slot] = idx;
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

    // pkg198: first-interaction lock to the VOLUME category (CPU:
    // firstInteraction => firstCat = 3).
    if (c_wfLpBinding.passAccum != nullptr &&
        c_wfLpBinding.firstCat[idx] == G_LP_CAT_UNSET)
        c_wfLpBinding.firstCat[idx] = 3;

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

    // #929: no NEE at this vertex — direct light is the per-segment sample the
    // intersect stage parked (gpu_volumeSegmentDirect); this vertex only
    // continues (its lamp-hit MIS is the complement). The nee/light parameters
    // are unused since #929.

    // pkg271 — Cycles volume_bounce (+1 at this scatter); past the cap the
    // continuation is terminate-after (intersect reads the per_type_bounce flag).
    gpu_countVolumeBounce(state.per_type_bounce, idx, c_wfGridVolume.volumeBounceCap);

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
    state.path_mis_nx[idx] = 0.f;  // #851: medium vertex, zero MIS normal
    state.path_mis_ny[idx] = 0.f;
    state.path_mis_nz[idx] = 0.f;
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

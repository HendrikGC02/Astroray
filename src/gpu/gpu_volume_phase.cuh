// pkg269 — shared device volume helpers: the Henyey–Greenstein phase function
// and the object-free counter-based free-flight uniform. MOVED VERBATIM out of
// src/gpu/wavefront/stage_advance.cu (pkg199 Stage 2) so the dedicated
// heterogeneous-volume stage TU (stage_volume_hetero.cu) can share them without
// duplicating code; stage_advance.cu includes this header at the original site.
// Byte-identical codegen: same inline definitions, same translation-unit view.
#pragma once

#include <cstdint>
#include <cuda_runtime.h>

#include "astroray/gpu_types.h"
#include "astroray/gpu_materials.h"                  // gpu_buildONB
#include "astroray/sampling/wavefront_rng_device.h"  // astroray::MixBits

#ifndef M_PI_F
#define M_PI_F 3.14159265358979323846f
#endif

// pkg199 Stage 2 — Henyey-Greenstein phase function (HG 1941; PBRT-v3 PhaseHG,
// src/core/medium.cpp, BSD). cosTheta = dot(wo, wi), wo pointing back along the
// incoming ray. Normalised over the sphere (integrates to 1); Inv4Pi = 1/(4π).
// Device twin of Renderer::phaseHG — same sign convention for CPU↔GPU parity.
__device__ inline float gpu_phaseHG(float cosTheta, float g)
{
    float denom = 1.f + g * g + 2.f * g * cosTheta;
    denom = fmaxf(denom, 1e-6f);
    return (0.25f / M_PI_F) * (1.f - g * g) / (denom * sqrtf(denom));
}

// pkg199 Stage 2 — importance-sample the HG phase function (PBRT-v3
// HenyeyGreenstein::Sample_p, BSD). `wo` points back along the incoming ray
// (= -ray.direction). Returns the sampled continuation direction; outPdf is the
// phase value (HG is perfectly importance-sampled, pdf == value → throughput
// factor value/pdf = 1). g>0 forward-scatters (peak at wi = -wo). Device twin of
// Renderer::sampleHG; gpu_buildONB gives the orthonormal frame (z-axis = wo).
__device__ inline GVec3 gpu_sampleHG(const GVec3& wo, float g, float u1, float u2,
                                     float& outPdf)
{
    float cosTheta;
    if (fabsf(g) < 1e-3f) {
        cosTheta = 1.f - 2.f * u1;
    } else {
        float sqrTerm = (1.f - g * g) / (1.f + g - 2.f * g * u1);
        cosTheta = -(1.f + g * g - sqrTerm * sqrTerm) / (2.f * g);
    }
    cosTheta = fmaxf(-1.f, fminf(1.f, cosTheta));
    float sinTheta = sqrtf(fmaxf(0.f, 1.f - cosTheta * cosTheta));
    float phi = 2.f * M_PI_F * u2;
    GVec3 v1, v2;
    gpu_buildONB(wo, v1, v2);
    GVec3 wi = v1 * (sinTheta * cosf(phi)) + v2 * (sinTheta * sinf(phi)) + wo * cosTheta;
    outPdf = gpu_phaseHG(cosTheta, g);
    return wi.normalized();
}

// pkg199 Stage 2 — dimension-salt base for the free-flight sampler. Far above any
// dimension the shade/volume WavefrontRNG stream reaches (0..~depth·draws), so the
// free-flight draws are decorrelated from all shading draws by construction.
static constexpr uint32_t G_WF_VOL_DIM_SALT = 0xF0000000u;
// pkg269 — disjoint salt bases for the heterogeneous-medium tracker (intersect
// stage) and the grid ratio-tracking transmittance (shadow stage). Each consumes
// `salt + draw` for an unbounded number of draws per event; the per-bounce stride
// (4096) and the per-medium stride (1024, shadow) keep events disjoint.
static constexpr uint32_t G_WF_GRID_DIM_SALT       = 0xE0000000u;
static constexpr uint32_t G_WF_GRIDSHADOW_DIM_SALT = 0xD0000000u;

// pkg199 Stage 2 — OBJECT-FREE counter-based free-flight uniform. Reuses the exact
// published keying of WavefrontRNG::GenerateForDimension (PBRT-v4 MixBits =
// MurmurHash3 finalizer, src/pbrt/util/hash.h; -> PCG32 SetSequence -> PCG32 XSH-RR
// output, imneme/pcg-c-basic Apache-2.0) — a counter-based RNG in the Salmon et al.
// 2011 ("Parallel Random Numbers", Random123) sense — but computed inline so
// intersectPathSlot holds NO persistent WavefrontRNG object and does NO
// rng_dimension SoA round-trip (Option 3: keeps the intersect decision block
// register-light so the kernel stays <=128 regs / 2 blocks/SM at 256 threads). Keyed
// on (pixel, sample, seed, dimSalt); the salt varies per bounce and per draw so
// every free-flight event is independent, and is disjoint from the shade stream.
// CPU<->GPU free-flight streams are INDEPENDENT (parity gate is per-channel
// mean-ratio, not sample-matched). See the research note.
__device__ inline float gpu_freeflightUniform(uint32_t pixel, uint32_t sample,
                                              uint64_t seed, uint32_t dimSalt)
{
    uint64_t seq_index = (static_cast<uint64_t>(pixel) * 65536ULL + sample) << 32 | dimSalt;
    uint64_t stream = astroray::MixBits(seq_index);
    uint64_t inc   = (stream << 1) | 1;
    uint64_t state = 0;
    state = state * 6364136223846793005ULL + inc;   // PCG32 SetSequence, advance 1
    state += seed;
    state = state * 6364136223846793005ULL + inc;   // advance 2
    uint32_t xorshifted = static_cast<uint32_t>(((state >> 18u) ^ state) >> 27u);
    uint32_t rot        = static_cast<uint32_t>(state >> 59u);
    int32_t  rot_signed = static_cast<int32_t>(rot);
    uint32_t u = (xorshifted >> rot) | (xorshifted << ((-rot_signed) & 31));
    constexpr float kOneMinusEpsilon = 0x1.fffffep-1f;
    return fminf(u * 0x1p-32f, kOneMinusEpsilon);
}

// pkg269 — ray (o, unit d) vs a bounded medium's world AABB, clipped to
// [tMin, tMax]. Device twin of astroray::volume::intersectAABB.
__device__ inline bool gpu_gridAabbOverlap(const GGridMedium& m, const GVec3& o,
                                           const GVec3& d, float tMin, float tMax,
                                           float& t0, float& t1)
{
    t0 = tMin; t1 = tMax;
    const float oa[3] = {o.x, o.y, o.z};
    const float da[3] = {d.x, d.y, d.z};
    for (int a = 0; a < 3; ++a) {
        if (fabsf(da[a]) < 1e-12f) {
            if (oa[a] < m.aabbMin[a] || oa[a] > m.aabbMax[a]) return false;
        } else {
            float inv = 1.f / da[a];
            float tn = (m.aabbMin[a] - oa[a]) * inv;
            float tf = (m.aabbMax[a] - oa[a]) * inv;
            if (tn > tf) { float tmp = tn; tn = tf; tf = tmp; }
            t0 = fmaxf(t0, tn);
            t1 = fminf(t1, tf);
            if (t0 > t1) return false;
        }
    }
    return true;
}

// pkg269 — balance-heuristic denominator over the four hero choices (lane 0 only
// once dispersion collapsed the quad: secondary pdfs == 0). Device twin of
// astroray::volume::heroAverage.
__device__ inline float gpu_heroAverage(const GSampledSpectrum& r,
                                        const GSampledWavelengths& wl)
{
    bool terminated = true;
    for (int i = 1; i < G_SPECTRUM_SAMPLES; ++i) if (wl.pdf[i] != 0.f) terminated = false;
    if (terminated) return r.v[0];
    float s = 0.f;
    for (int i = 0; i < G_SPECTRUM_SAMPLES; ++i) s += r.v[i];
    return s / float(G_SPECTRUM_SAMPLES);
}

// pkg269 — rdc-linked entry points of the heterogeneous-volume TU
// (stage_volume_hetero.cu, the only TU that includes NanoVDB.h).
// gpu_gridVolumeTrack: hero-wavelength spectral-MIS free flight over
// [tMin,tMax] in medium `mi` (device twin of astroray::volume::spectralTrack).
// Returns 0 = escaped, 1 = absorbed (beta zeroed), 2 = scattered at tOut.
// `emission` accumulates the constant-emission contribution (already divided by
// avg(r_u)); `salt` seeds the counter-based draws (salt + draw index).
__device__ int gpu_gridVolumeTrack(int mi, const GVec3& o, const GVec3& d,
                                   float tMin, float tMax,
                                   const GSampledWavelengths& wl,
                                   GSampledSpectrum& beta, GSampledSpectrum& r_u,
                                   GSampledSpectrum& emission, float& tOut,
                                   uint32_t rpix, uint32_t rsmp, uint64_t rsd,
                                   uint32_t salt);
// Per-λ ratio-tracking transmittance over [tMin,tMax] in medium `mi` (device twin
// of astroray::volume::ratioTrackingTransmittanceSpectral).
__device__ GSampledSpectrum gpu_gridVolumeTransmittance(int mi, const GVec3& o,
                                                        const GVec3& d, float tMin,
                                                        float tMax,
                                                        const GSampledWavelengths& wl,
                                                        uint32_t rpix, uint32_t rsmp,
                                                        uint64_t rsd, uint32_t salt);

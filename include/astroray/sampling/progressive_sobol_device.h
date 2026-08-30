// SPDX-License-Identifier: Apache-2.0
// Copyright 2024 Hendrik Grimm-Baur
//
// Progressive (low-discrepancy) sampler for the GPU wavefront -- hash-based
// Owen-scrambled Sobol'. Opt-in alternative to the PCG32 WavefrontRNG white
// noise; unblocks pkg131 (adaptive sampling) by giving every prefix of N
// per-pixel samples the "progressive" (well-distributed) property.
//
// References:
// - Brent Burley, "Practical Hash-based Owen Scrambling," Journal of Computer
//   Graphics Techniques (JCGT) 9(4), 2020.
//   https://jcgt.org/published/0009/04/01/paper.pdf
// - pbrt-v4 src/pbrt/util/lowdiscrepancy.h & math.h (Apache-2.0):
//   FastOwenScrambler, the direct Sobol' construction, ReverseBits32.
//   https://github.com/mmp/pbrt-v4
// - Sobol' direction vectors: sobol_matrices.h (Joe & Kuo 2008, via SciPy;
//   verified byte-exact against scipy.stats.qmc.Sobol in the pkg224 test).
//
// This is the __host__/__device__ mirror (single implementation used by both
// the CUDA shade kernel and the host unit-test binding, so the two cannot
// drift). See wavefront_rng_device.h for the calling convention it slots into.
//
// pkg224 -- progressive-sampler primitive; forks (a) hash-Owen Sobol',
// (b) opt-in __constant__ runtime flag, (c) GPU-only first (owner-confirmed
// 2026-08-29). Off by default (c_wfSamplerMode == 0) -> byte-identical to the
// PCG32 fleet.

#ifndef ASTRORAY_SAMPLING_PROGRESSIVE_SOBOL_DEVICE_H
#define ASTRORAY_SAMPLING_PROGRESSIVE_SOBOL_DEVICE_H

#include <cstdint>

#include "astroray/sampling/sobol_matrices.h"

#ifdef __CUDACC__
#  define PS_HD __host__ __device__
// Device-side Sobol' direction-vector table. A namespace-scope constexpr array
// is host-only (not addressable in device code), so the shade kernel reads this
// __constant__ mirror instead. Defined once in src/gpu/wavefront/stage_advance.cu
// and filled from the host kSobolMatrices32 via cudaMemcpyToSymbol by
// setWavefrontSamplerMode(true) (only when the progressive sampler is enabled,
// so the byte-identical default path uploads nothing).
namespace astroray { namespace wavefront {
extern __constant__ uint32_t c_sobolMatrices[kSobolNumDims][kSobolMatrixSize];
} }  // namespace astroray::wavefront
#else
#  define PS_HD
#endif

namespace astroray {

// ReverseBits32 -- pbrt-v4 src/pbrt/util/math.h (Apache-2.0).
PS_HD inline uint32_t ReverseBits32(uint32_t n) {
    n = (n << 16) | (n >> 16);
    n = ((n & 0x00ff00ffu) << 8) | ((n & 0xff00ff00u) >> 8);
    n = ((n & 0x0f0f0f0fu) << 4) | ((n & 0xf0f0f0f0u) >> 4);
    n = ((n & 0x33333333u) << 2) | ((n & 0xccccccccu) >> 2);
    n = ((n & 0x55555555u) << 1) | ((n & 0xaaaaaaaau) >> 1);
    return n;
}

// HashHP -- "Hash Prospector" 32-bit integer hash (Cycles util/hash.h
// hash_hp_uint, Apache-2.0). Well-randomizes a seed before it is fed to the
// Owen scrambler (Burley 2020 requires a well-mixed scramble seed).
PS_HD inline uint32_t HashHP(uint32_t i) {
    i ^= i >> 16;
    i *= 0x21f0aaadu;
    i ^= i >> 15;
    i *= 0xd35a2d97u;
    i ^= i >> 15;
    return i ^ 0xe6fe3bebu;  // maps input 0 to a nonzero output
}

// FastOwenScramble -- base-2 nested-uniform Owen scramble of a 32-bit value.
// pbrt-v4 FastOwenScrambler (src/pbrt/util/lowdiscrepancy.h) == Cycles
// nested_uniform_scramble(reversed_bit_owen) (kernel/sample/util.h), both
// Apache-2.0. Approximates exact 32-level Owen scrambling with a fixed sequence
// of reversible integer ops (no 32-iteration bit loop -- the shape that fits
// the REG:254-pinned shade kernel). The inner reversed_bit_owen is the
// higher-quality Laine-Karras variant (psychopath.io better-lk-hash).
PS_HD inline uint32_t FastOwenScramble(uint32_t v, uint32_t seed) {
    v = ReverseBits32(v);
    v ^= v * 0x3d20adeau;
    v += seed;
    v *= (seed >> 16) | 1u;
    v ^= v * 0x05526c56u;
    v ^= v * 0x53a22864u;
    return ReverseBits32(v);
}

// SobolDirect -- direct Sobol' construction (pbrt-v4 lowdiscrepancy.h): XOR the
// direction vectors selected by the set bits of the sample index. `dim` must be
// < kSobolNumDims (ProgressiveSobolSample guarantees this before calling).
PS_HD inline uint32_t SobolDirect(uint32_t sample_index, uint32_t dim) {
    uint32_t v = 0u;
#ifdef __CUDA_ARCH__
    const uint32_t* col = wavefront::c_sobolMatrices[dim];  // __constant__ mirror
#else
    const uint32_t* col = kSobolMatrices32[dim];            // host constexpr
#endif
    // At most 32 iterations (j in [0, kSobolMatrixSize)); bits j >= 30 have a
    // zero direction vector so they contribute nothing.
    for (uint32_t a = sample_index, j = 0u; a != 0u; a >>= 1, ++j) {
        if (a & 1u) v ^= col[j];
    }
    return v;
}

// ProgressiveSobolSample -- shuffled, Owen-scrambled Sobol' draw in [0, 1).
// Stateless pure function of (pixel, sample, dimension, scene_seed) -- exactly
// the tuple WavefrontRNG already carries, so it drops in with no new per-path
// state. Precondition: dimension < kSobolNumDims (the caller falls back to PCG
// for deeper dims).
//
// Two Owen scrambles (Burley 2020 "shuffled" Sobol', Cycles sobol_burley):
//   1. The sample INDEX is Owen-scrambled with a PER-PIXEL seed. This shuffles
//      which prefix of the sequence each pixel draws -- it is what decorrelates
//      neighbouring pixels (so noise is not spatially structured) while
//      PRESERVING the progressive property (an Owen-scrambled index prefix is
//      still a (t,m,s)-net). All dimensions share this one shuffled index, so a
//      pixel's dims 0,1,... remain a jointly-stratified Sobol' point.
//   2. The Sobol' DIGITS are Owen-scrambled with a per-(pixel,dimension) seed,
//      randomizing the point coordinates without breaking stratification.
PS_HD inline float ProgressiveSobolSample(uint32_t pixel, uint32_t sample,
                                          uint32_t dimension, uint64_t scene_seed) {
    // Per-pixel scramble seed (fold both halves of the 64-bit scene seed in).
    uint32_t pix_seed = HashHP(pixel ^ static_cast<uint32_t>(scene_seed) ^
                               static_cast<uint32_t>(scene_seed >> 32));
    // (1) shuffle the index per pixel; (2) look up multi-dimensional Sobol';
    // (3) scramble the digits per (pixel, dimension). The XOR constants are the
    // Cycles sobol_burley decorrelation constants for the index vs digit passes.
    uint32_t shuffled = FastOwenScramble(sample, pix_seed ^ 0xbff95bfeu);
    uint32_t sob = SobolDirect(shuffled, dimension);
    uint32_t scr = FastOwenScramble(sob,
                                    (pix_seed ^ HashHP(dimension)) ^ 0x635c77bdu);
    constexpr float kOneMinusEpsilon = 0x1.fffffep-1f;  // 1 - FLT_EPSILON
    float f = scr * 0x1p-32f;                            // 2^-32
#ifdef __CUDA_ARCH__
    return fminf(f, kOneMinusEpsilon);
#else
    return (f < kOneMinusEpsilon) ? f : kOneMinusEpsilon;
#endif
}

#ifdef __CUDACC__
// Device entry used by WavefrontRNG::Uniform(). __noinline__ so the Sobol' body
// (direction-table read + Owen scramble) stays in its own frame and does NOT
// inflate the REG:254-pinned shade kernel: the runtime branch in Uniform()
// reaches it only when c_wfSamplerMode != 0, so on the byte-identical fleet
// off-path the register allocator sees a not-taken call, not an inlined body.
// The pkg224 register-probe gate is what confirms this holds.
__device__ __noinline__ inline float ProgressiveSobolSampleDevice(
    uint32_t pixel, uint32_t sample, uint32_t dimension, uint64_t scene_seed) {
    return ProgressiveSobolSample(pixel, sample, dimension, scene_seed);
}
#endif

}  // namespace astroray

// pkg224 -- opt-in runtime flag. Published once per frame by
// cuda_wavefront_render (setWavefrontSamplerMode); 0 = PCG32 white noise (the
// byte-identical fleet default), 1 = progressive Sobol'. Defined in
// src/gpu/wavefront/stage_advance.cu next to c_wfBounceLimit/c_wfCausticGate.
// Declared here (device pass only) so WavefrontRNG::Uniform() can gate on it.
#ifdef __CUDACC__
namespace astroray { namespace wavefront {
extern __constant__ int c_wfSamplerMode;
} }  // namespace astroray::wavefront
#endif

#endif  // ASTRORAY_SAMPLING_PROGRESSIVE_SOBOL_DEVICE_H

// SPDX-License-Identifier: Apache-2.0
// Copyright 2024 Hendrik Grimm-Baur
//
// pkg305 (pkg297 slice 1) -- shuffled, Owen-scrambled Sobol' sampler with
// padding ("Sobol-Burley"). One __host__ __device__ implementation shared by the
// CPU tile loop (raytracer.h) and the GPU wavefront init stage (stage_init.cu).
//
// Each 1D/2D dimension SET gets its own index shuffle (padding), so different
// sets are decorrelated while the components inside a set are jointly
// stratified. Only Sobol' dims 0-1 are used here (2D sets); pkg297 adds 3D/4D.
//
// Port of Blender Cycles (Apache-2.0):
//   src/kernel/sample/sobol_burley.h  sobol_burley, sobol_burley_sample_1D/2D
//   src/kernel/sample/util.h          reversed_bit_owen
//   src/kernel/tables.h               sobol_burley_table[4][32]
//   src/util/hash.h                   hash_hp_uint (== astroray::HashHP),
//                                     uint_to_float_excl
// Paper: Brent Burley, "Practical Hash-based Owen Scrambling", JCGT 9(4), 2020.
// Notes: .astroray_plan/docs/pkg305-camera-group-research.md

#ifndef ASTRORAY_SAMPLING_SOBOL_BURLEY_H
#define ASTRORAY_SAMPLING_SOBOL_BURLEY_H

#include <cstdint>

#include "astroray/sampling/progressive_sobol_device.h"  // HashHP, ReverseBits32, PS_HD

#if !defined(__CUDA_ARCH__) && defined(_MSC_VER) && !defined(__clang__)
#  include <intrin.h>
#endif

// Cycles kernel/tables.h sobol_burley_table: bit-reversed Sobol' direction
// numbers, rows = dims 0..3, column j = index bit j. The first 30 entries of each
// row equal ReverseBits32(kSobolMatrices32[d][j]); bits 30-31 (reachable with the
// full 0xFFFFFFFF index mask) are only in this 32-bit table.
#define ASTRORAY_SOBOL_BURLEY_TABLE_INIT                                          \
    {{0x00000001u, 0x00000002u, 0x00000004u, 0x00000008u, 0x00000010u,             \
      0x00000020u, 0x00000040u, 0x00000080u, 0x00000100u, 0x00000200u,             \
      0x00000400u, 0x00000800u, 0x00001000u, 0x00002000u, 0x00004000u,             \
      0x00008000u, 0x00010000u, 0x00020000u, 0x00040000u, 0x00080000u,             \
      0x00100000u, 0x00200000u, 0x00400000u, 0x00800000u, 0x01000000u,             \
      0x02000000u, 0x04000000u, 0x08000000u, 0x10000000u, 0x20000000u,             \
      0x40000000u, 0x80000000u},                                                   \
     {0x00000001u, 0x00000003u, 0x00000005u, 0x0000000fu, 0x00000011u,             \
      0x00000033u, 0x00000055u, 0x000000ffu, 0x00000101u, 0x00000303u,             \
      0x00000505u, 0x00000f0fu, 0x00001111u, 0x00003333u, 0x00005555u,             \
      0x0000ffffu, 0x00010001u, 0x00030003u, 0x00050005u, 0x000f000fu,             \
      0x00110011u, 0x00330033u, 0x00550055u, 0x00ff00ffu, 0x01010101u,             \
      0x03030303u, 0x05050505u, 0x0f0f0f0fu, 0x11111111u, 0x33333333u,             \
      0x55555555u, 0xffffffffu},                                                   \
     {0x00000001u, 0x00000003u, 0x00000006u, 0x00000009u, 0x00000017u,             \
      0x0000003au, 0x00000071u, 0x000000a3u, 0x00000116u, 0x00000339u,             \
      0x00000677u, 0x000009aau, 0x00001601u, 0x00003903u, 0x00007706u,             \
      0x0000aa09u, 0x00010117u, 0x0003033au, 0x00060671u, 0x000909a3u,             \
      0x00171616u, 0x003a3939u, 0x00717777u, 0x00a3aaaau, 0x01170001u,             \
      0x033a0003u, 0x06710006u, 0x09a30009u, 0x16160017u, 0x3939003au,             \
      0x77770071u, 0xaaaa00a3u},                                                   \
     {0x00000001u, 0x00000003u, 0x00000004u, 0x0000000au, 0x0000001fu,             \
      0x0000002eu, 0x00000045u, 0x000000c9u, 0x0000011bu, 0x000002a4u,             \
      0x0000079au, 0x00000b67u, 0x0000101eu, 0x0000302du, 0x00004041u,             \
      0x0000a0c3u, 0x0001f104u, 0x0002e28au, 0x000457dfu, 0x000c9baeu,             \
      0x0011a105u, 0x002a7289u, 0x0079e7dbu, 0x00b6dba4u, 0x0100011au,             \
      0x030002a7u, 0x0400079eu, 0x0a000b6du, 0x1f001001u, 0x2e003003u,             \
      0x45004004u, 0xc900a00au}}

namespace astroray {
namespace sobol_burley {

inline constexpr uint32_t kTable[4][32] = ASTRORAY_SOBOL_BURLEY_TABLE_INIT;

#ifdef __CUDACC__
// Device mirror (a namespace-scope constexpr array is not addressable in device
// code). Defined once, statically initialised from the same literal, in
// src/gpu/wavefront/stage_init.cu (-rdc), so no host upload is needed.
extern __constant__ uint32_t c_table[4][32];
#endif

PS_HD inline uint32_t tableEntry(uint32_t dim, uint32_t j) {
#ifdef __CUDA_ARCH__
    return c_table[dim][j];
#else
    return kTable[dim][j];
#endif
}

// x != 0 at every call site.
PS_HD inline uint32_t countLeadingZeros(uint32_t x) {
#if defined(__CUDA_ARCH__)
    return static_cast<uint32_t>(__clz(static_cast<int>(x)));
#elif defined(__GNUC__) || defined(__clang__)
    return static_cast<uint32_t>(__builtin_clz(x));
#elif defined(_MSC_VER)
    unsigned long idx;
    _BitScanReverse(&idx, x);
    return 31u - static_cast<uint32_t>(idx);
#else
    uint32_t n = 0;
    while (!(x & 0x80000000u)) { x <<= 1; ++n; }
    return n;
#endif
}

// Cycles reversed_bit_owen: base-2 Owen scramble of a reversed-bit integer
// (Laine-Karras-style hash, psychopath.io "building a better LK hash"). Same ops
// as the inner body of pkg224 FastOwenScramble.
PS_HD inline uint32_t reversedBitOwen(uint32_t n, uint32_t seed) {
    n ^= n * 0x3d20adeau;
    n += seed;
    n *= (seed >> 16) | 1u;
    n ^= n * 0x05526c56u;
    n ^= n * 0x53a22864u;
    return n;
}

// Cycles uint_to_float_excl: [0, 2^32) -> [0, 1) (divide by 4294967808 so the
// largest input stays below 1.0f).
PS_HD inline float uintToFloatExcl(uint32_t n) {
    return static_cast<float>(n) * (1.0f / 4294967808.0f);
}

// Cycles sobol_burley(): one Owen-scrambled Sobol' coordinate. revBitIndex is
// the (shuffled, masked) sample index in reversed-bit order.
PS_HD inline float sobolBurley(uint32_t revBitIndex, uint32_t dim, uint32_t scrambleSeed) {
    uint32_t result = 0u;
    if (dim == 0u) {
        // Dimension 0 is van der Corput: the reversed index itself.
        result = ReverseBits32(revBitIndex);
    } else {
        uint32_t i = 0u;
        while (revBitIndex != 0u) {
            const uint32_t j = countLeadingZeros(revBitIndex);
            result ^= tableEntry(dim, i + j);
            i += j + 1u;
            // Two shifts: `<<= j + 1` overflows the shift at j == 31.
            revBitIndex <<= j;
            revBitIndex <<= 1;
        }
    }
    result = ReverseBits32(reversedBitOwen(result, scrambleSeed));
    return uintToFloatExcl(result);
}

// Cycles sobol_burley_sample_1D. `mask` is Cycles' shuffled_index_mask (in the
// reversed-bit domain, see indexMask()).
PS_HD inline float sample1D(uint32_t index, uint32_t dimension, uint32_t seed, uint32_t mask) {
    seed ^= HashHP(dimension);
    index = reversedBitOwen(ReverseBits32(index), seed ^ 0xbff95bfeu);
    index &= mask;
    return sobolBurley(index, 0u, seed ^ 0x635c77bdu);
}

// Cycles sobol_burley_sample_2D; the two components are jointly stratified.
PS_HD inline void sample2D(uint32_t index, uint32_t dimensionSet, uint32_t seed, uint32_t mask,
                           float& u0, float& u1) {
    seed ^= HashHP(dimensionSet);
    index = reversedBitOwen(ReverseBits32(index), seed ^ 0xf8ade99au);
    index &= mask;
    u0 = sobolBurley(index, 0u, seed ^ 0xe0aaaf76u);
    u1 = sobolBurley(index, 1u, seed ^ 0x94964d4eu);
}

// Cycles scene/integrator.cpp: sobol_index_mask =
// reverse_integer_bits(next_power_of_two(N - 1) - 1). maxSamples <= 0 (unbounded,
// progressive chunks) returns the full mask.
PS_HD inline uint32_t indexMask(int maxSamples) {
    if (maxSamples <= 0) return 0xFFFFFFFFu;
    const uint32_t x = static_cast<uint32_t>(maxSamples - 1);
    // Cycles next_power_of_two(x): x == 0 ? 1 : 1 << (32 - clz(x)).
    const uint32_t clz = (x == 0u) ? 32u : countLeadingZeros(x);
    const uint32_t np2 = (x == 0u) ? 1u : (clz == 0u ? 0u : (1u << (32u - clz)));
    return ReverseBits32(np2 - 1u);
}

// Per-pixel sequence seed (pkg297 spec; pkg224 ProgressiveSobolSample keying).
PS_HD inline uint32_t pixelSeed(uint32_t pixel, uint64_t seed) {
    return HashHP(pixel ^ static_cast<uint32_t>(seed) ^ static_cast<uint32_t>(seed >> 32));
}

}  // namespace sobol_burley
}  // namespace astroray

#endif  // ASTRORAY_SAMPLING_SOBOL_BURLEY_H

// SPDX-License-Identifier: Apache-2.0
// Copyright 2024 Hendrik Grimm-Baur
//
// WavefrontRNG — CUDA __device__ port of PCG32 counter-based RNG.
//
// pkg55-B' Session N+3 — CUDA port of wavefront_rng.h for bit-comparable
// threshold measurement. The CPU and GPU PCG32 streams must match for the
// two-tier gate (spec §4.2).
//
// References:
// - Melissa E. O'Neill, "PCG: A Family of Simple Fast Space-Efficient
//   Statistically Good Algorithms for Random Number Generation,"
//   Harvey Mudd College Technical Report HMC-CS-2014-0905, 2014.
//   https://www.pcg-random.org/paper.html
// - imneme/pcg-c-basic (Apache-2.0): https://github.com/imneme/pcg-c-basic
//   Implementation mirrors pcg_basic.c:pcg32_random_r.
// - PBRT-v4 src/pbrt/util/rng.h (Apache-2.0): SetSequence keying pattern.
//   https://github.com/mmp/pbrt-v4
//
// This is the __device__ mirror of include/astroray/sampling/wavefront_rng.h.
// The arithmetic is byte-identical; the #ifdef branches handle CUDA intrinsics
// vs host <cmath>.

#ifndef ASTRORAY_SAMPLING_WAVEFRONT_RNG_DEVICE_H
#define ASTRORAY_SAMPLING_WAVEFRONT_RNG_DEVICE_H

#include <cstdint>

#ifdef __CUDACC__
#  define WF_RNG_HD __host__ __device__
#else
#  define WF_RNG_HD
#endif

namespace astroray {

// MixBits — MurmurHash3 finalizer for stream hashing (PBRT-v4 src/pbrt/util/hash.h).
WF_RNG_HD inline uint64_t MixBits(uint64_t v) {
    v ^= (v >> 31);
    v *= 0x7fb5d329728ea185ULL;
    v ^= (v >> 27);
    v *= 0x81dadef4bc2dd44dULL;
    v ^= (v >> 33);
    return v;
}

// WavefrontRNG — PCG32 generator keyed by (pixel, sample, dimension).
//
// Usage (CUDA __device__ code):
//   WavefrontRNG rng(pixel_index, sample_index, scene_seed);
//   float u = rng.Uniform();  // draws from dimension 0, auto-increments
//   float v = rng.Uniform();  // draws from dimension 1, auto-increments
//
// Design:
// - State: pixel/sample/dimension counters + scene_seed (4 POD uint32_t/uint64_t).
// - Keying: PBRT-v4 pattern — MixBits((pixel * max_samples + sample) << 32 | dim).
// - Each Uniform() call increments internal dimension counter and re-keys PCG32.
// - Output: PCG-XSH-RR (xor-shift-high, random-rotate).
//
// Byte-identical to the host wavefront_rng.h.
//
class WavefrontRNG {
public:
    // Construct RNG for a specific (pixel, sample) path.
    //
    // Parameters:
    //   pixel_index   — flat pixel index (y * width + x).
    //   sample_index  — per-pixel sample index (0..spp-1).
    //   scene_seed    — global seed (typically 0 or user-provided).
    //
    // The dimension counter starts at 0 and increments with each Uniform() call.
    WF_RNG_HD WavefrontRNG(uint32_t pixel_index, uint32_t sample_index, uint64_t scene_seed = 0)
        : pixel_(pixel_index), sample_(sample_index), dimension_(0), seed_(scene_seed) {
    }

    // Generate uniform float in [0, 1).
    // Increments internal dimension counter with each call.
    WF_RNG_HD float Uniform() {
        uint32_t u = UniformUInt32();
        // Convert to float: multiply by 2^-32, then clamp to [0, 1).
        // PBRT-v4 uses OneMinusEpsilon clamping; we match that.
        constexpr float kOneMinusEpsilon = 0x1.fffffep-1f;  // 1 - FLT_EPSILON
        float f = u * 0x1p-32f;  // 2^-32
#ifdef __CUDA_ARCH__
        return fminf(f, kOneMinusEpsilon);
#else
        return (f < kOneMinusEpsilon) ? f : kOneMinusEpsilon;
#endif
    }

    // Generate uniform uint32_t (full range).
    // Increments internal dimension counter with each call.
    WF_RNG_HD uint32_t UniformUInt32() {
        uint32_t dim = dimension_++;
        return GenerateForDimension(dim);
    }

    // Accessors for SoA serialization (Session N+3 — CPU wavefront pattern).
    WF_RNG_HD uint32_t pixel()     const { return pixel_; }
    WF_RNG_HD uint32_t sample()    const { return sample_; }
    WF_RNG_HD uint32_t dimension() const { return dimension_; }
    WF_RNG_HD uint64_t seed()      const { return seed_; }

    // Resume an RNG at an exact stream position (the carried dimension).
    WF_RNG_HD void setDimension(uint32_t dim) { dimension_ = dim; }

private:
    uint32_t pixel_;
    uint32_t sample_;
    uint32_t dimension_;
    uint64_t seed_;

    // Generate a sample for a specific dimension without mutating dimension counter.
    WF_RNG_HD uint32_t GenerateForDimension(uint32_t dim) const {
        // PBRT-v4 keying: stream = MixBits((pixel * max_samples + sample) << 32 | dim).
        // We assume max_samples ≤ 2^16 (65536 spp). For typical oracle usage at
        // 64-256 spp, this encoding is safe.
        uint64_t seq_index = (static_cast<uint64_t>(pixel_) * 65536ULL + sample_) << 32 | dim;
        uint64_t stream = MixBits(seq_index);

        // PCG32 initialization (PBRT-v4 SetSequence protocol):
        // 1. inc = (stream << 1) | 1  — ensure oddness (PCG requirement).
        // 2. state = 0; advance(); state += scene_seed; advance().
        uint64_t state = 0;
        uint64_t inc = (stream << 1) | 1;

        state = state * 6364136223846793005ULL + inc;  // First advance
        state += seed_;
        state = state * 6364136223846793005ULL + inc;  // Second advance

        // Generate one output from the initialized state.
        return PCG32Output(state);
    }

    // PCG32 output permutation (XSH-RR).
    // From imneme/pcg-c-basic pcg_basic.c:pcg32_random_r.
    WF_RNG_HD static uint32_t PCG32Output(uint64_t state) {
        uint32_t xorshifted = static_cast<uint32_t>(((state >> 18u) ^ state) >> 27u);
        uint32_t rot = static_cast<uint32_t>(state >> 59u);
        // Right-rotate xorshifted by rot bits.
        // The (-rot) & 31 idiom is a standard way to compute (32 - rot) & 31 for rotation.
        int32_t rot_signed = static_cast<int32_t>(rot);
        return (xorshifted >> rot) | (xorshifted << ((-rot_signed) & 31));
    }
};

}  // namespace astroray

#endif  // ASTRORAY_SAMPLING_WAVEFRONT_RNG_DEVICE_H

// src/neural_cache.h — NeuralCache helper class (pkg26).
// Compiled only when ASTRORAY_TINY_CUDA_NN=ON.
//
// Wraps a tiny-cuda-nn 16-in / 16-out FullyFusedMLP with an Adam optimizer
// for per-frame query/train. The caller owns feature encoding and target
// computation; this class only does GPU inference and training steps.
//
// Input feature layout (pkg26 spec §Key design decisions):
//   [0-2]  world-space position (xyz), normalized to [0,1] scene AABB
//   [3-4]  view direction (spherical θ/π, φ/2π)
//   [5-6]  surface normal  (spherical θ/π, φ/2π)
//   [7]    surface roughness
//   [8-10] diffuse albedo (R, G, B)
//   [11-15] padding zeros
//
// Output: 16 floats. Slots 0-2 = R, G, B indirect radiance; 3-15 discarded.
// FullyFusedMLP requires output width to be a multiple of 16.
#pragma once

#include "raytracer.h"   // Vec3
#include <vector>
#include <memory>
#include <cstdint>

class NeuralCache {
public:
    static constexpr uint32_t N_IN        = 16;
    static constexpr uint32_t N_OUT       = 16;
    static constexpr uint32_t BATCH_ALIGN = 256;  // tcnn BATCH_SIZE_GRANULARITY in master

    NeuralCache();
    ~NeuralCache();

    // Batch inference. n must be a multiple of BATCH_ALIGN.
    // inputs: interleaved [n × N_IN], i.e. inputs[i * N_IN + f] = feature f of sample i.
    // Returns RGB indirect radiance for each sample (clamped to >= 0).
    std::vector<Vec3> query(uint32_t n, const std::vector<float>& inputs);

    // One training step (forward + backward + Adam update).
    // inputs:      interleaved [n × N_IN]
    // targets_rgb: interleaved [n × 3]  (R, G, B only; padded to N_OUT=16 internally)
    // n must be a multiple of BATCH_ALIGN.
    void trainStep(uint32_t n,
                   const std::vector<float>& inputs,
                   const std::vector<float>& targets_rgb);

    // Round n up to the nearest BATCH_ALIGN multiple.
    static uint32_t roundUp(uint32_t n) {
        return ((n + BATCH_ALIGN - 1) / BATCH_ALIGN) * BATCH_ALIGN;
    }

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

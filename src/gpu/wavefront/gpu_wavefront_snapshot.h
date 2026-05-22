// gpu_wavefront_snapshot.h — pkg55-B' Session N+3
//
// GPU wavefront snapshot helper for CPU↔GPU per-stage diff harness.
//
// This function mirrors the CPU cpu_wavefront_render's snapshot emission
// pattern but for the GPU stage_init kernel. It allocates GPU buffers, runs
// stage_init, downloads the PostInit snapshot, and returns it as a flat
// vector matching the CPU WavefrontSnapshot schema (one row per path).
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §4.2 Session N+3.
// Design: PR #296 §4.1 (two-tier gate: CPU↔GPU bounded, not exact).

#ifndef ASTRORAY_GPU_WAVEFRONT_SNAPSHOT_H
#define ASTRORAY_GPU_WAVEFRONT_SNAPSHOT_H

#include "astroray/gpu_types.h"
#include "raytracer.h"
#include <vector>
#include <cstdint>

namespace astroray {
namespace wavefront {

// cuda_wavefront_snapshot_post_init — Run GPU stage_init and download PostInit snapshot.
//
// Args:
//   cam: camera (CPU-side).
//   width, height: pixel dimensions.
//   seed: global RNG seed.
//
// Returns:
//   Flat vector of PostInit snapshot fields, one row per pixel (width*height paths).
//   Row format (mirrors CPU WavefrontSnapshot PostInit fields):
//     [0..2]:   ray_origin (x,y,z)
//     [3..5]:   ray_direction (x,y,z)
//     [6..9]:   lambdas (4 floats)
//     [10..13]: throughput (4 floats)
//     [14..15]: pixel_index, sample_index
//     [16]:     bounce
//     [17..20]: rng state (pixel, sample, dimension, seed_lo, seed_hi) — 5 elements total
//
//   Total: 22 floats/ints per path.
//
// This function exists solely for the Session N+3 threshold measurement harness.
// It is NOT a production API — production GPU wavefront stages write directly to
// SoA buffers and never download to CPU.
std::vector<float> cuda_wavefront_snapshot_post_init(
    const Camera& cam,
    int width, int height,
    uint64_t seed);

}  // namespace wavefront
}  // namespace astroray

#endif  // ASTRORAY_GPU_WAVEFRONT_SNAPSHOT_H

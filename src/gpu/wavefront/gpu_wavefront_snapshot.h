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

// cuda_wavefront_snapshot_post_intersect — Run GPU stage_init + stage_intersect,
// download PostIntersect snapshot.
//
// Returns:
//   Flat vector of PostIntersect snapshot fields, one row per pixel.
//   Row format (mirrors CPU WavefrontSnapshot PostIntersect fields):
//     [0..2]:   ray_origin (x,y,z)
//     [3..5]:   ray_direction (x,y,z)
//     [6..9]:   lambdas (4 floats)
//     [10..13]: throughput (4 floats)
//     [14]:     hit_valid (0 or 1)
//     [15]:     hit_t
//     [16..18]: hit_point (x,y,z)
//     [19..21]: hit_normal (x,y,z)
//     [22]:     hit_material_id
//
//   Total: 23 floats/ints per path.
std::vector<float> cuda_wavefront_snapshot_post_intersect(
    Renderer& renderer,
    const Camera& cam,
    int width, int height,
    uint64_t seed);

// cuda_wavefront_snapshot_post_shade — Run GPU stage_init + stage_intersect +
// stage_shade_lambertian, download PostShade snapshot.
//
// Returns:
//   Flat vector of PostShade snapshot fields, one row per pixel.
//   Row format (mirrors CPU WavefrontSnapshot PostShade fields):
//     [0..2]:   ray_origin (next bounce origin)
//     [3..5]:   ray_direction (next bounce direction)
//     [6..9]:   throughput (4 floats, updated by BSDF)
//     [10..13]: lambdas (4 floats)
//     [14]:     bsdf_pdf
//     [15]:     bsdf_is_delta (0 or 1)
//
//   Total: 16 floats/ints per path.
std::vector<float> cuda_wavefront_snapshot_post_shade(
    Renderer& renderer,
    const Camera& cam,
    int width, int height,
    uint64_t seed);

// cuda_wavefront_snapshot_post_light_sample — Run GPU stage_init + stage_intersect +
// stage_shade_lambertian + stage_light_sample, download PostLightSample snapshot.
//
// Returns:
//   Flat vector of PostLightSample snapshot fields, one row per pixel.
//   Row format (mirrors CPU WavefrontSnapshot PostLightSample fields):
//     [0..2]:   ray_origin (x,y,z)
//     [3..5]:   ray_direction (x,y,z)
//     [6..9]:   throughput (4 floats)
//     [10..13]: lambdas (4 floats)
//     [14..17]: nee_contribution (4 floats)
//     [18]:     nee_light_pdf
//     [19]:     nee_bsdf_pdf_at_dir
//     [20]:     nee_mis_weight
//
//   Total: 21 floats/ints per path.
std::vector<float> cuda_wavefront_snapshot_post_light_sample(
    Renderer& renderer,
    const Camera& cam,
    int width, int height,
    uint64_t seed);

// cuda_wavefront_snapshot_post_rr — Run GPU stage_init + stage_intersect +
// stage_shade_lambertian + stage_light_sample + stage_russian_roulette,
// download PostRR snapshot.
//
// Returns:
//   Flat vector of PostRR snapshot fields, one row per pixel.
//   Row format (mirrors CPU WavefrontSnapshot PostRR fields):
//     [0..2]:   ray_origin (x,y,z)
//     [3..5]:   ray_direction (x,y,z)
//     [6..9]:   throughput (4 floats, scaled by 1/p if survived)
//     [10..13]: lambdas (4 floats)
//     [14]:     rr_prob (continuation probability)
//     [15]:     rr_survived (0 or 1)
//
//   Total: 16 floats/ints per path.
std::vector<float> cuda_wavefront_snapshot_post_rr(
    Renderer& renderer,
    const Camera& cam,
    int width, int height,
    uint64_t seed);

// pkg55-B' Session N+6: end-to-end GPU wavefront render. Runs init +
// max_depth advance rounds per sample and returns the linear-sRGB image
// (height*width*3 floats), accumulated host-side exactly like the CPU
// wavefront driver. Unlocks the final-image gate.
std::vector<float> cuda_wavefront_render(
    Renderer& renderer,
    const Camera& cam,
    int width, int height,
    int samples, int max_depth,
    uint64_t seed);

}  // namespace wavefront
}  // namespace astroray

#endif  // ASTRORAY_GPU_WAVEFRONT_SNAPSHOT_H

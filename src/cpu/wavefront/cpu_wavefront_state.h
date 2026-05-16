// pkg55 Phase B' Session 2c/3/4/5 — CPU wavefront SoA state layout.
//
// Cite: Laine, Karras, Aila 2013 §4 "Megakernels Considered Harmful" (HPG).
//       Cycles intern/cycles/kernel/integrator/state.h (Apache-2.0).
//       PBRT-v4 src/pbrt/wavefront/workitems.soa (Apache-2.0).
//
// This is the CPU mirror of Phase A.1's GPU `IntegratorStateSoA`. Session 5
// scope is Lambertian + metal + dielectric + disney + area lights (growing oracle).
//
// Session 2c/3/4/5 — the SoA is a pure CARRIER for the shared kernel's PathState
// (path_kernel.h). It serializes the LIVE per-path state between the
// host-side stage iterations and reconstructs it byte-exactly:
//
//   - The WavefrontRNG is carried as its four POD members
//     (pixel/sample/dimension/seed). Reconstructing WavefrontRNG from those
//     yields the IDENTICAL object — same auto-incrementing stream the
//     oracle consumes. No fresh-RNG construction, no hand-counted replay.
//   - The full HitRecord is carried per slot (it has std::vector members;
//     stored by value in a std::vector<HitRecord>). Shade NEVER re-traces
//     the BVH — intersect writes the hit, shade consumes it.
//   - ray_direction is the ALREADY-NORMALIZED direction; restored verbatim,
//     never renormalized at the stage boundary (Phase A.1 ulp-bug fix).
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Phase B'".
// Design: .astroray_plan/docs/pkg55-B-cpu-reference-design.md §9, §11.

#ifndef ASTRORAY_CPU_WAVEFRONT_STATE_H
#define ASTRORAY_CPU_WAVEFRONT_STATE_H

#include "path_kernel.h"  // PathState (also pulls in raytracer.h: HitRecord, Vec3)
#include <vector>
#include <cstdint>

namespace astroray {
namespace cpu_wavefront {

// CPUWavefrontState — SoA carrier for in-flight path slots.
//
// Each slot serializes one shared-kernel PathState plus its companion
// HitRecord. pack_from()/unpack_to() round-trip a PathState byte-exactly
// (the RNG is POD counter state; ray_direction is the already-normalized
// vector; spectral carriers are plain floats).
struct CPUWavefrontState {
    int max_paths;
    int num_active;

    // Identity.
    std::vector<int> pixel_index;
    std::vector<int> sample_index;
    std::vector<int> bounce;

    // Live WavefrontRNG state (the auto-incrementing stream, carried slot
    // to slot — no reconstruction, no replay).
    std::vector<uint32_t> rng_pixel;
    std::vector<uint32_t> rng_sample;
    std::vector<uint32_t> rng_dimension;
    std::vector<uint64_t> rng_seed;

    // Ray state. ray_direction_* is ALREADY normalized; restored verbatim.
    std::vector<float> ray_origin_x;
    std::vector<float> ray_origin_y;
    std::vector<float> ray_origin_z;
    std::vector<float> ray_direction_x;
    std::vector<float> ray_direction_y;
    std::vector<float> ray_direction_z;

    // Per-path spectral carriers (kSpectrumSamples = 4).
    std::vector<float> throughput_0;
    std::vector<float> throughput_1;
    std::vector<float> throughput_2;
    std::vector<float> throughput_3;
    std::vector<float> lambda_0;
    std::vector<float> lambda_1;
    std::vector<float> lambda_2;
    std::vector<float> lambda_3;
    std::vector<float> lambda_pdf_0;
    std::vector<float> lambda_pdf_1;
    std::vector<float> lambda_pdf_2;
    std::vector<float> lambda_pdf_3;

    // Radiance accumulator.
    std::vector<float> color_0;
    std::vector<float> color_1;
    std::vector<float> color_2;
    std::vector<float> color_3;

    // Path-continuation flags.
    std::vector<int> was_specular;  // 0/1
    std::vector<int> path_alive;    // 0 = terminated, 1 = active

    // Carried hit identity (post-intersect -> shade). Full HitRecord so
    // shade never re-traces. >32 bytes / has std::vector members → kept in
    // a std::vector<HitRecord>, accessed by reference (MinGW large-struct
    // rule: never passed by value across a TU boundary).
    std::vector<HitRecord> hit;
    std::vector<int>       hit_valid;  // 0 = miss

    explicit CPUWavefrontState(int max_paths_)
        : max_paths(max_paths_), num_active(0) {
        pixel_index.resize(max_paths);
        sample_index.resize(max_paths);
        bounce.resize(max_paths);

        rng_pixel.resize(max_paths);
        rng_sample.resize(max_paths);
        rng_dimension.resize(max_paths);
        rng_seed.resize(max_paths);

        ray_origin_x.resize(max_paths);
        ray_origin_y.resize(max_paths);
        ray_origin_z.resize(max_paths);
        ray_direction_x.resize(max_paths);
        ray_direction_y.resize(max_paths);
        ray_direction_z.resize(max_paths);

        throughput_0.resize(max_paths);
        throughput_1.resize(max_paths);
        throughput_2.resize(max_paths);
        throughput_3.resize(max_paths);
        lambda_0.resize(max_paths);
        lambda_1.resize(max_paths);
        lambda_2.resize(max_paths);
        lambda_3.resize(max_paths);
        lambda_pdf_0.resize(max_paths);
        lambda_pdf_1.resize(max_paths);
        lambda_pdf_2.resize(max_paths);
        lambda_pdf_3.resize(max_paths);

        color_0.resize(max_paths);
        color_1.resize(max_paths);
        color_2.resize(max_paths);
        color_3.resize(max_paths);

        was_specular.resize(max_paths);
        path_alive.resize(max_paths);

        hit.resize(max_paths);
        hit_valid.resize(max_paths);
    }

    // Serialize a PathState into slot `i` (byte-exact round-trip).
    void pack_from(int i, const PathState& ps);

    // Reconstruct the PathState carried in slot `i` (byte-exact).
    PathState unpack_to(int i) const;
};

}  // namespace cpu_wavefront
}  // namespace astroray

#endif  // ASTRORAY_CPU_WAVEFRONT_STATE_H

// pkg55 Phase B' Session 2c/3/4/5/6/7/8 — Shared per-bounce path kernel.
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Sessions 2c/3/4/5/6/7/8".
// Design: .astroray_plan/docs/pkg55-B-cpu-reference-design.md §2, §3, §6, §9.
//
// THE shared kernel. There is EXACTLY ONE generator of the per-bounce
// arithmetic sequence (intersect -> shade(Lambertian/metal/dielectric/disney/thin_glass/diffuse_light/closure_graph) -> NEE -> RR ->
// BSDF sample -> ray advance). Both reference_pt_wavefront AND
// cpu_wavefront_driver call init_path()/advance_one_bounce() from THIS
// file. Bit-identity between the two is therefore by construction — same
// compiled function, same inputs (carried live, never reconstructed),
// same outputs. It is a theorem, not a measurement.
//
// Convergent recommendation of two independent senior reviews
// (architect PR #296 + Codex, 2026-05-15): a single shared kernel +
// carried live state, not two transcriptions with a tolerance gate.
//
// Cite: Laine, Karras, Aila 2013 §3 (wavefront decomposition) — HPG 2013
//         "Megakernels Considered Harmful".
//       Cycles intern/cycles/kernel/integrator/shade_surface.h (Apache-2.0)
//         — per-bounce shade kernel structure.
//       PBRT-v4 src/pbrt/wavefront/integrator.cpp (Apache-2.0)
//         — wavefront stage decomposition over a shared path body.
//       O'Neill 2014 (PCG32) + PBRT-v4 SetSequence — WavefrontRNG keying.
//       Production Renderer::pathTraceSpectral (raytracer.h) — the exact
//         Lambertian-Cornell per-bounce math this kernel mirrors.

#ifndef ASTRORAY_CPU_WAVEFRONT_PATH_KERNEL_H
#define ASTRORAY_CPU_WAVEFRONT_PATH_KERNEL_H

// PathState carries Vec3 members + an inline ctor, so the full Vec3 / Ray /
// HitRecord definitions must be visible here (they live inline in
// raytracer.h — there is no standalone math header). Renderer / Camera are
// referenced by reference only and resolve from the same include.
#include "raytracer.h"
#include "wavefront_snapshot.h"
#include "astroray/spectrum.h"
#include "astroray/sampling/wavefront_rng.h"

namespace astroray {
namespace cpu_wavefront {

// PathState — the LIVE per-path state carried bounce-to-bounce.
//
// This is the single source of truth for a path's evolving state. Both the
// oracle and the wavefront driver carry an instance of this and hand it to
// advance_one_bounce(). Nothing here is reconstructed or replayed:
//
//   - rng: the LIVE WavefrontRNG. Its internal dimension counter is the one
//     auto-incrementing stream the path consumes (filter -> lens -> lambda
//     -> per-bounce NEE/RR/BSDF). The wavefront serializes the four POD
//     members of WavefrontRNG into SoA between stages and reconstructs the
//     SAME object (same dimension_) — there is no fresh-RNG reconstruction
//     and no hand-counted dimension replay.
//
//   - ray_origin / ray_direction: stored as a raw point + an ALREADY-
//     NORMALIZED direction. We never wrap these back into Ray(o, d) at a
//     stage boundary, because Ray's constructor re-normalizes d (a second
//     normalize of an already-unit vector is a ulp-level perturbation —
//     this is the Phase A.1 ulp bug; re-applied here as: store/restore the
//     normalized direction directly, never renormalize at boundaries).
//
//   - throughput / lambdas / color: spectral carriers + radiance
//     accumulator, all live.
//
//   - wasSpecular / alive: path-continuation flags, live.
struct PathState {
    WavefrontRNG rng;

    Vec3 ray_origin;
    Vec3 ray_direction;       // ALREADY normalized; never renormalize.

    SampledSpectrum throughput;
    SampledWavelengths lambdas;
    SampledSpectrum color;    // radiance accumulator

    bool wasSpecular;
    bool alive;
    // pkg120: BSDF pdf of the current continuation ray (written after the BSDF
    // sample, read at the next bounce's emissive-hit for two-sided MIS). Live
    // state carried across advance_one_bounce calls, mirroring wasSpecular.
    float bsdfPdfPrev;

    int pixel_index;
    int sample_index;
    int bounce;

    PathState(uint32_t pixel, uint32_t sample, uint64_t seed)
        : rng(pixel, sample, seed),
          ray_origin(0, 0, 0),
          ray_direction(0, 0, 1),
          throughput(1.0f),
          lambdas(),
          color(0.0f),
          wasSpecular(true),
          alive(true),
          bsdfPdfPrev(0.0f),
          pixel_index(static_cast<int>(pixel)),
          sample_index(static_cast<int>(sample)),
          bounce(0) {}
};

// init_path — primary ray generation + lambda sampling for one path.
//
// EXACT RNG draw order (the single generator of init outputs):
//   1. filter u  (rng.Uniform() - 0.5f)
//   2. filter v  (rng.Uniform() - 0.5f)
//   3. lens      (mt19937 seeded from rng.UniformUInt32(), -> Camera::getRay)
//   4. lambda    (rng.Uniform())
//
// Each Uniform() draw consumes exactly one PCG32 dimension; this mirrors GPU
// stage_init.cu byte-for-byte. (Was std::uniform_real_distribution<float>
// pre-2026-05-23, which libstdc++ implements with 2 uint32 draws per float,
// causing 8.7M-ULP CPU↔GPU drift at PostInit.)
//
// Populates ps.ray_origin / ps.ray_direction (direction already normalized
// by Camera::getRay) and ps.lambdas. Emits the PostInit snapshot.
//
// Both reference_pt_wavefront's per-sample loop and stage_init call THIS.
void init_path(PathState& ps, const Camera& cam, int x, int y,
                int width, int height, SnapshotSink* sink);

// advance_one_bounce — THE shared per-bounce body.
//
// The exact arithmetic sequence of reference_pt_wavefront::tracePathSpectral's
// loop body, verbatim:
//   intersect (BVH::hit) -> PostIntersect snapshot
//   -> emission (gated on bounce==0 || wasSpecular) -> terminate-on-light
//   -> NEE (area light, MIS power heuristic) -> PostLightSample snapshot
//   -> Russian roulette (bounce > rrDepth) -> PostRR snapshot
//   -> BSDF sample -> PostShade snapshot
//   -> ray advance (store normalized bss.wi directly; NO Ray() reconstruction)
//   -> throughput clamp.
//
// `hit` is an out/scratch HitRecord owned by the caller (it holds std::vector
// members; per the MinGW large-struct rule it is passed by reference, never
// by value across the TU boundary). The caller's wavefront keeps one HitRecord
// per slot so the hit identity is carried, never re-traced.
//
// Returns true if the path continues to the next bounce, false if it
// terminated (miss / hit light / RR death / degenerate BSDF / depth cap).
// On termination ps.alive is set false.
//
// Both reference_pt_wavefront's bounce loop and the wavefront driver call
// THIS — there is exactly one generator of these per-bounce outputs.
bool advance_one_bounce(PathState& ps, HitRecord& hit,
                        Renderer& renderer, int max_depth,
                        SnapshotSink* sink);

}  // namespace cpu_wavefront
}  // namespace astroray

#endif  // ASTRORAY_CPU_WAVEFRONT_PATH_KERNEL_H

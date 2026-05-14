// pkg55 Phase B' Session 2b — Production-side reference path tracer.
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Phase B'".
// Design: .astroray_plan/docs/pkg55-B-cpu-reference-design.md §2, §3, §6.
//
// Independent transcription of production Renderer::pathTraceSpectral with
// tile-shared RNG (mt19937(baseSeed + tileIdx)). This is the trip-wire
// oracle: bit-exact RGB equality vs Renderer.render at fixed seed detects
// unintended production drift.
//
// Session 2 scope: Lambertian + area lights + Cornell only. Asserts on
// unsupported materials (metal, dielectric, disney, thin_glass, etc.).
//
// Cite: production include/raytracer.h:2055-2205 (pathTraceSpectral),
//       include/raytracer.h:2460-2580 (tile loop + RNG seeding).

#ifndef ASTRORAY_CPU_WAVEFRONT_REFERENCE_PT_PRODUCTION_H
#define ASTRORAY_CPU_WAVEFRONT_REFERENCE_PT_PRODUCTION_H

#include "wavefront_snapshot.h"
#include <vector>
#include <cstdint>

// Forward declarations (caller includes raytracer.h).
class Renderer;
class Camera;

namespace astroray {
namespace cpu_wavefront {

struct ReferencePTResult {
    std::vector<float> rgb;  // width*height*3, row-major, sRGB
    std::vector<WavefrontSnapshot> snapshots;  // optional
};

// Render with tile-shared RNG, mirroring production Renderer::render tile loop.
// RNG seeding: mt19937(baseSeed + tileIdx) where tileIdx = tileY*tilesX + tileX.
// Tile size = 16x16 (hardcoded to match production).
// Single-threaded (no #pragma omp) for deterministic CI.
//
// If record_snapshots=true, emits WavefrontSnapshot at 5 stage boundaries
// (PostInit, PostIntersect, PostShade, PostLightSample, PostRR) for the
// per-stage diff harness.
//
// Session 2 enforcement: aborts on any material not in {lambertian, light}.
ReferencePTResult reference_pt_production_render(
    Renderer& renderer,
    const Camera& cam,
    int samples,
    int max_depth,
    uint64_t seed,
    bool record_snapshots = false);

}  // namespace cpu_wavefront
}  // namespace astroray

#endif  // ASTRORAY_CPU_WAVEFRONT_REFERENCE_PT_PRODUCTION_H

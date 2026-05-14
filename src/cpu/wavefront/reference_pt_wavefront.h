// pkg55 Phase B' Session 2b — Wavefront-side reference path tracer.
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Phase B'".
// Design: .astroray_plan/docs/pkg55-B-cpu-reference-design.md §2, §3, §6.
//
// Independent transcription of production Renderer::pathTraceSpectral with
// per-path RNG (mt19937(FNV-1a-32(pixel_index, sample_index, 0))). This is
// the diff oracle for the CPU wavefront: element-by-element SoA equality at
// 1 spp validates the wavefront implementation.
//
// Session 2 scope: Lambertian + area lights + Cornell only. Asserts on
// unsupported materials (metal, dielectric, disney, thin_glass, etc.).
//
// Cite: production include/raytracer.h:2055-2205 (pathTraceSpectral),
//       Laine 2013 §3 (per-path RNG keying),
//       Phase A.1 GPU convention (hash(pixel, sample, offset)).

#ifndef ASTRORAY_CPU_WAVEFRONT_REFERENCE_PT_WAVEFRONT_H
#define ASTRORAY_CPU_WAVEFRONT_REFERENCE_PT_WAVEFRONT_H

#include "wavefront_snapshot.h"
#include <vector>
#include <cstdint>

// Forward declarations (caller includes raytracer.h).
class Renderer;
class Camera;

namespace astroray {
namespace cpu_wavefront {

// Result struct matches reference_pt_production.
struct ReferencePTResult;

// Render with per-path RNG, keyed by hash(pixel_index, sample_index, 0).
// FNV-1a-32 hash over three uint32 inputs. RNG offset = 0 for integrator-frontend
// draws (filter, lens, lambda), matching Phase A.1 GPU convention.
//
// If record_snapshots=true, emits WavefrontSnapshot at 5 stage boundaries
// (PostInit, PostIntersect, PostShade, PostLightSample, PostRR) for the
// per-stage diff harness.
//
// Session 2 enforcement: aborts on any material not in {lambertian, light}.
ReferencePTResult reference_pt_wavefront_render(
    Renderer& renderer,
    const Camera& cam,
    int samples,
    int max_depth,
    uint64_t seed,  // used as XOR mask on hash output (0 = no mask)
    bool record_snapshots = false);

}  // namespace cpu_wavefront
}  // namespace astroray

#endif  // ASTRORAY_CPU_WAVEFRONT_REFERENCE_PT_WAVEFRONT_H

// pkg55 Phase B' Session 2c — CPU wavefront driver (callable entry point).
//
// Cite: Laine 2013 §3 (wavefront decomposition).
//       PBRT-v4 src/pbrt/wavefront/integrator.cpp (Apache-2.0).
//       Cycles device/cuda/queue.cpp (Apache-2.0, dispatch loop pattern).
//
// Spec: .astroray_plan/packages/pkg55-wavefront-soa-refactor.md §"Phase B'".
// Design: .astroray_plan/docs/pkg55-B-cpu-reference-design.md §5.

#ifndef ASTRORAY_CPU_WAVEFRONT_DRIVER_H
#define ASTRORAY_CPU_WAVEFRONT_DRIVER_H

#include "wavefront_snapshot.h"
#include "raytracer.h"
#include <vector>
#include <cstdint>

namespace astroray {
namespace cpu_wavefront {

// cpu_wavefront_render — Callable CPU wavefront driver.
//
// Signature mirrors reference_pt_wavefront_render (design doc §3).
//
// Args:
//   renderer: scene + BVH + lights (must have built acceleration structure).
//   cam: camera.
//   samples: samples per pixel.
//   max_depth: bounce limit.
//   seed: global RNG seed (0 = deterministic from pixel/sample only).
//   sink: optional snapshot sink (nullptr = no snapshots).
//
// Returns:
//   RGB image (HEIGHT, WIDTH, 3) in linear sRGB.
std::vector<float> cpu_wavefront_render(
    Renderer& renderer,
    const Camera& cam,
    int samples,
    int max_depth,
    uint64_t seed,
    SnapshotSink* sink = nullptr);

}  // namespace cpu_wavefront
}  // namespace astroray

#endif  // ASTRORAY_CPU_WAVEFRONT_DRIVER_H

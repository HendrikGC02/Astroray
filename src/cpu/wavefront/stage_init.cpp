// pkg55 Phase B' Session 2c — CPU wavefront stage: primary ray init.
//
// Thin wavefront stage: for every pixel/sample slot, run the SHARED
// init_path() kernel (path_kernel.cpp) and serialize the resulting
// PathState into the SoA. The init arithmetic + RNG draw order + PostInit
// snapshot all live in the shared kernel — this file only loops + packs.
//
// Cite: Laine 2013 §3 (wavefront decomposition);
//       Cycles intern/cycles/kernel/integrator/init_from_camera.h (Apache-2.0).

#include "raytracer.h"
#include "cpu_wavefront_state.h"
#include "path_kernel.h"

namespace astroray {
namespace cpu_wavefront {

void stage_init(
        CPUWavefrontState& state,
        Renderer& /*renderer*/,
        const Camera& cam,
        int width, int height, int samples,
        uint64_t seed,
        SnapshotSink* sink) {
    state.num_active = width * height * samples;

    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            int pixel_idx = y * width + x;
            for (int s = 0; s < samples; ++s) {
                int slot = pixel_idx * samples + s;

                // THE shared init kernel — same function the oracle calls.
                PathState ps(static_cast<uint32_t>(pixel_idx),
                             static_cast<uint32_t>(s), seed);
                init_path(ps, cam, x, y, width, height, sink);

                state.pack_from(slot, ps);
            }
        }
    }
}

}  // namespace cpu_wavefront
}  // namespace astroray

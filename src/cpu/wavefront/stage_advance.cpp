// pkg55 Phase B' Session 2c — CPU wavefront stage: advance one bounce.
//
// Thin wavefront stage: for every ALIVE slot, deserialize the carried
// PathState (including the LIVE WavefrontRNG stream position and the
// already-normalized ray direction and the carried HitRecord), call the
// SHARED advance_one_bounce() kernel ONCE, then serialize the updated
// PathState back into the SoA.
//
// advance_one_bounce (path_kernel.cpp) is the SINGLE generator of the
// per-bounce arithmetic: intersect -> shade(Lambertian) -> NEE -> RR ->
// BSDF sample -> ray advance, emitting the PostIntersect / PostLightSample
// / PostRR / PostShade snapshots. reference_pt_wavefront calls the EXACT
// SAME function per bounce. There is no second transcription, no fresh-RNG
// reconstruction, no hand-counted dimension replay, no BVH re-trace in a
// separate shade pass — bit-identity is therefore by construction.
//
// This file supersedes the pre-shared-kernel stage_intersect.cpp +
// stage_shade_lambertian.cpp split (those re-traced the BVH in shade and
// rebuilt a fresh RNG with a brittle dimension replay — the dominant
// divergence both senior reviews identified). See the spec NOTE.
//
// Cite: Laine 2013 §3 (wavefront decomposition);
//       Cycles intern/cycles/kernel/integrator/shade_surface.h (Apache-2.0);
//       PBRT-v4 src/pbrt/wavefront/integrator.cpp (Apache-2.0).

#include "raytracer.h"
#include "cpu_wavefront_state.h"
#include "path_kernel.h"

namespace astroray {
namespace cpu_wavefront {

void stage_advance(
        CPUWavefrontState& state,
        Renderer& renderer,
        int max_depth,
        SnapshotSink* sink) {
    for (int slot = 0; slot < state.num_active; ++slot) {
        if (!state.path_alive[slot]) continue;

        // Deserialize the carried live PathState (RNG stream position +
        // already-normalized direction + spectral carriers + flags).
        PathState ps = state.unpack_to(slot);

        // The carried per-slot HitRecord (has std::vector members; bound by
        // reference, never copied across a TU boundary — MinGW large-struct
        // rule). advance_one_bounce writes the fresh hit here; nothing
        // re-traces the BVH in a separate pass.
        HitRecord& rec = state.hit[slot];

        // THE shared per-bounce kernel — same function the oracle calls.
        bool cont = advance_one_bounce(ps, rec, renderer, max_depth, sink);
        state.hit_valid[slot] = (rec.material != nullptr) ? 1 : 0;
        (void)cont;  // ps.alive carries the same signal; packed below.

        // Serialize the updated live PathState back.
        state.pack_from(slot, ps);
    }
}

}  // namespace cpu_wavefront
}  // namespace astroray

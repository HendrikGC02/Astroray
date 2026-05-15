// pkg55 Phase B' Session 2b/2c — Wavefront-side reference path tracer.
//
// pkg92 — PCG32 counter-based RNG keyed by (pixel, sample, dimension).
// Session 2c — refactored onto the SHARED per-bounce kernel
//   (path_kernel.{h,cpp}). This file no longer contains a transcription of
//   the per-bounce math; it just drives init_path() + advance_one_bounce()
//   over every pixel/sample. The CPU wavefront driver calls the SAME two
//   functions. Bit-identity between them is therefore by construction.
//
// The per-sample post-processing (firefly suppression, film exposure,
// XYZ->linear-sRGB, finiteOrZero) is the ~470x spectral-PDF fix from
// Session 2b and is preserved verbatim — Codex (2026-05-15) traced the
// stable per-channel mean ratios to this missing matrix multiply.
//
// Cite: O'Neill 2014 (PCG32), PBRT-v4 SetSequence pattern (Apache-2.0),
//       Laine 2013 §3 (per-path keying for wavefront path tracers),
//       Cycles intern/cycles/kernel/random.h (rng convention, Apache-2.0),
//       production Renderer::pathTraceSpectral (per-bounce loop logic).

#include "reference_pt_wavefront.h"
#include "reference_pt_production.h"  // for ReferencePTResult
#include "path_kernel.h"              // THE shared kernel
#include "raytracer.h"
#include "astroray/spectrum.h"

namespace astroray {
namespace cpu_wavefront {

ReferencePTResult reference_pt_wavefront_render(
        Renderer& renderer,
        const Camera& cam,
        int samples,
        int max_depth,
        uint64_t seed,
        bool record_snapshots) {
    ReferencePTResult result;
    result.rgb.resize(static_cast<size_t>(cam.width) * cam.height * 3, 0.0f);

    VectorSink snapSink;
    SnapshotSink* sink = record_snapshots ? &snapSink : nullptr;

    for (int y = 0; y < cam.height; ++y) {
        for (int x = 0; x < cam.width; ++x) {
            int pixel_index = y * cam.width + x;
            Vec3 colorXYZ(0);

            for (int s = 0; s < samples; ++s) {
                // The single shared kernel owns the live PathState (RNG,
                // ray, throughput, lambdas, radiance accumulator, flags).
                PathState ps(static_cast<uint32_t>(pixel_index),
                             static_cast<uint32_t>(s), seed);

                // Init: filter -> lens -> lambda + PostInit snapshot.
                init_path(ps, cam, x, y, cam.width, cam.height, sink);

                // Per-bounce loop — EXACTLY the shared kernel, called per
                // bounce. No second transcription of the per-bounce math.
                HitRecord rec;
                for (int bounce = 0; bounce < max_depth; ++bounce) {
                    if (!advance_one_bounce(ps, rec, renderer, max_depth, sink)) {
                        break;
                    }
                }

                SampledSpectrum rad = ps.color;
                XYZ xyz = rad.toXYZ(ps.lambdas);

                // Per-sample firefly suppression.
                float lum = xyz.Y;
                if (lum > 20.0f) {
                    xyz.X *= (20.0f / lum);
                    xyz.Y = 20.0f;
                    xyz.Z *= (20.0f / lum);
                }

                colorXYZ += Vec3(xyz.X, xyz.Y, xyz.Z);
            }

            colorXYZ = colorXYZ / float(samples);

            // pkg55-B' Session 2b — equivalence-test parity fix (KEEP):
            // mirror reference_pt_production's post-processing exactly so
            // both oracles output in the same color space (linear sRGB).
            // Codex (2026-05-15) caught that this block was the missing
            // matrix multiply behind the ~470x stable per-channel ratios.
            // 1. Film exposure multiplication (XYZ space).
            colorXYZ *= renderer.getFilmExposure();

            // 2. XYZ -> linear sRGB conversion.
            Vec3 colorSRGB = xyzToLinearSRGB(colorXYZ);

            // 3. finiteOrZero clamping (apply_gamma=False path).
            colorSRGB.x = std::max(Renderer::finiteOrZero(colorSRGB.x), 0.0f);
            colorSRGB.y = std::max(Renderer::finiteOrZero(colorSRGB.y), 0.0f);
            colorSRGB.z = std::max(Renderer::finiteOrZero(colorSRGB.z), 0.0f);

            int idx = pixel_index * 3;
            result.rgb[idx + 0] = colorSRGB.x;
            result.rgb[idx + 1] = colorSRGB.y;
            result.rgb[idx + 2] = colorSRGB.z;
        }
    }

    if (record_snapshots) {
        result.snapshots = snapSink.snapshots();
    }

    return result;
}

}  // namespace cpu_wavefront
}  // namespace astroray

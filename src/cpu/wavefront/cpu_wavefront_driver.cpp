// pkg55 Phase B' Session 2c — CPU wavefront driver.
//
// Laine 2013 §3 wavefront decomposition: stages operate over a queue of
// in-flight path slots. Session 2c stages:
//
//   stage_init      — per slot: shared init_path(); serialize PathState->SoA.
//   stage_advance   — per ALIVE slot: deserialize SoA->PathState, call the
//                     SHARED advance_one_bounce() ONCE, serialize back.
//                     advance_one_bounce internally does
//                     intersect -> shade(Lambertian) -> NEE -> RR -> BSDF
//                     -> ray-advance and emits all 4 in-loop snapshots
//                     (PostIntersect/PostLightSample/PostRR/PostShade).
//
// There is exactly ONE generator of the per-bounce arithmetic
// (path_kernel.cpp::advance_one_bounce) — both this driver AND
// reference_pt_wavefront call it. Bit-identity of the snapshot streams is
// therefore by construction, not by measured tolerance.
//
// Cite: Laine 2013 §3 (wavefront decomposition);
//       PBRT-v4 src/pbrt/wavefront/integrator.cpp (Apache-2.0);
//       reference_pt_wavefront.cpp (post-processing pipeline).

#include "raytracer.h"
#include "cpu_wavefront_driver.h"
#include "cpu_wavefront_state.h"
#include "path_kernel.h"
#include "astroray/spectrum.h"
#include <algorithm>

namespace astroray {
namespace cpu_wavefront {

// Forward decls for stage kernels (defined in stage_init.cpp / stage_advance.cpp).
void stage_init(CPUWavefrontState& state, Renderer& renderer, const Camera& cam,
                int width, int height, int samples, uint64_t seed, SnapshotSink* sink);
void stage_advance(CPUWavefrontState& state, Renderer& renderer,
                   int max_depth, SnapshotSink* sink);

std::vector<float> cpu_wavefront_render(
        Renderer& renderer,
        const Camera& cam,
        int samples,
        int max_depth,
        uint64_t seed,
        SnapshotSink* sink) {
    int width  = cam.width;
    int height = cam.height;
    int total_paths = width * height * samples;

    std::vector<float> rgb(static_cast<size_t>(width) * height * 3, 0.0f);

    CPUWavefrontState state(total_paths);

    // Stage 1: Init (primary rays + lambda sampling + PostInit snapshot).
    stage_init(state, renderer, cam, width, height, samples, seed, sink);

    // Wavefront loop: advance every alive path one bounce per iteration
    // until all paths terminate. Each iteration is the SHARED per-bounce
    // kernel applied across the queue.
    for (int iter = 0; iter < max_depth; ++iter) {
        int num_alive = 0;
        for (int i = 0; i < state.num_active; ++i) {
            if (state.path_alive[i]) num_alive++;
        }
        if (num_alive == 0) break;

        stage_advance(state, renderer, max_depth, sink);
    }

    // Accumulate to framebuffer — mirrors reference_pt_wavefront's
    // per-sample post-processing exactly (firefly suppression, film
    // exposure, XYZ->linear-sRGB, finiteOrZero). KEEP: this is the
    // Session 2b ~470x spectral-PDF parity fix.
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            int pixel_idx = y * width + x;
            Vec3 colorXYZ(0);

            for (int s = 0; s < samples; ++s) {
                int slot = pixel_idx * samples + s;
                SampledSpectrum rad(std::array<float, 4>{
                    state.color_0[slot], state.color_1[slot],
                    state.color_2[slot], state.color_3[slot]});
                SampledWavelengths lambdas = SampledWavelengths::fromLambdas(
                    std::array<float, 4>{state.lambda_0[slot], state.lambda_1[slot],
                                         state.lambda_2[slot], state.lambda_3[slot]},
                    std::array<float, 4>{state.lambda_pdf_0[slot], state.lambda_pdf_1[slot],
                                         state.lambda_pdf_2[slot], state.lambda_pdf_3[slot]});
                XYZ xyz = rad.toXYZ(lambdas);

                float lum = xyz.Y;
                if (lum > 20.0f) {
                    xyz.X *= (20.0f / lum);
                    xyz.Y = 20.0f;
                    xyz.Z *= (20.0f / lum);
                }

                colorXYZ += Vec3(xyz.X, xyz.Y, xyz.Z);
            }

            colorXYZ = colorXYZ / float(samples);

            colorXYZ *= renderer.getFilmExposure();
            Vec3 colorSRGB = xyzToLinearSRGB(colorXYZ);
            colorSRGB.x = std::max(Renderer::finiteOrZero(colorSRGB.x), 0.0f);
            colorSRGB.y = std::max(Renderer::finiteOrZero(colorSRGB.y), 0.0f);
            colorSRGB.z = std::max(Renderer::finiteOrZero(colorSRGB.z), 0.0f);

            int idx = pixel_idx * 3;
            rgb[idx + 0] = colorSRGB.x;
            rgb[idx + 1] = colorSRGB.y;
            rgb[idx + 2] = colorSRGB.z;
        }
    }

    return rgb;
}

}  // namespace cpu_wavefront
}  // namespace astroray

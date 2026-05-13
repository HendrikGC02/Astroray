// wavefront_render_loop.cu — pkg55 Phase B
//
// Host-side bounce loop that sequences all Phase B wavefront stages:
//   init → for each bounce:
//     intersect_full → sort → shade×7 → shadow → miss → terminate
//   → writeAccumulated
//
// Called from cuda_renderer.cu for the "wavefront_path_tracer" integrator.
//
// References (Apache-2.0):
//   - Cycles intern/cycles/integrator/path_trace_work_gpu.cpp — render loop
//   - PBRT-v4 src/pbrt/wavefront/integrator.cpp WavefrontPathIntegrator::Render

#include "astroray/integrator_state_soa.h"
#include "astroray/gpu_types.h"
#include "../profile.h"

#include <cuda_runtime.h>
#include <cstdio>
#include <cstring>

namespace astroray::wavefront {

void wavefrontRenderSample(
    IntegratorStateSoA& state,
    float* d_framebuffer,
    int width, int height,
    int samplesPerPixel, int maxDepth,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials,
    const GLight*     d_lights, int numLights, float totalLightPower,
    const GEnvMap&    envMap,
    const GCameraParams& cam,
    GVec3 backgroundColor, bool hasBackgroundColor,
    void* d_sortScratch, size_t sortScratchBytes_)
{
    int totalPixels = width * height;
    if (totalPixels <= 0) return;

    // Zero the accumulation buffer before the first sample batch.
    // Phase B: accum_rgb is per-path-slot (allocated at capacity size).
    if (state.accum_rgb) {
        cudaMemset(state.accum_rgb, 0,
                   (size_t)state.capacity * sizeof(float) * 4);
    }

    // Each spp iteration: initialise new rays and bounce them.
    for (int spp = 0; spp < samplesPerPixel; ++spp) {

        // --- Stage: init ---
        // Generates camera rays for all pixels; writes ray SoA + rng state.
        // num_active = totalPixels after init.
        launchStageInit(state, cam, width, height);

        // Zero per-path accum_rgb for this sample's paths
        if (state.accum_rgb && state.num_active > 0) {
            cudaMemset(state.accum_rgb, 0,
                       (size_t)state.num_active * sizeof(float) * 4);
        }

        // --- Bounce loop ---
        for (int bounce = 0; bounce < maxDepth; ++bounce) {

            // Count live paths; exit early if none
            bool anyAlive = (state.num_active > 0);
            if (!anyAlive) break;

            // Stage: intersect_full (init spectral only on bounce 0)
            if (bounce == 0) {
                launchStageIntersectFull(state, d_bvhNodes, d_prims, d_tris, d_spheres);
            } else {
                launchStageIntersectFullBounce(state, d_bvhNodes, d_prims, d_tris, d_spheres);
            }

            // Stage: sort by material (dead paths sort to front at key=0)
            if (d_sortScratch && sortScratchBytes_ > 0) {
                sortByMaterial(state, d_sortScratch, sortScratchBytes_);
            }

            // Stage: shade — one kernel per material type.
            // Each kernel filters its own material type via hit_mat check.
            launchShadeLambertian(state, d_materials,
                d_lights, numLights, totalLightPower,
                d_prims, d_tris, d_spheres,
                envMap, backgroundColor, hasBackgroundColor,
                d_bvhNodes, maxDepth);

            launchShadeMetal(state, d_materials,
                d_lights, numLights, totalLightPower,
                d_prims, d_tris, d_spheres,
                envMap, backgroundColor, hasBackgroundColor,
                d_bvhNodes, maxDepth);

            launchShadeDielectric(state, d_materials, maxDepth);

            launchShadeDiffuseLight(state, d_materials);

            launchShadeDisney(state, d_materials,
                d_lights, numLights, totalLightPower,
                d_prims, d_tris, d_spheres,
                envMap, backgroundColor, hasBackgroundColor,
                d_bvhNodes, maxDepth);

            launchShadeThinGlass(state, d_materials, maxDepth);

            launchShadeClosureGraph(state, d_materials,
                d_lights, numLights, totalLightPower,
                d_prims, d_tris, d_spheres,
                envMap, backgroundColor, hasBackgroundColor,
                d_bvhNodes, maxDepth);

            // Stage: shadow — any-hit test for NEE shadow rays
            launchStageShadow(state, d_bvhNodes, d_prims, d_tris, d_spheres);

            // Stage: miss — background/env for escaped rays
            launchStageMiss(state, envMap, backgroundColor, hasBackgroundColor);

            // Stage: terminate — Russian roulette + depth check
            launchStageTerminate(state, maxDepth);

        }  // bounce loop

        // After all bounces: write accum_rgb slots to framebuffer pixels.
        // Frame buffer is zeroed by CUDARenderer between samples; we add.
        launchWriteAccumulated(state, d_framebuffer, 1, totalPixels);

    }  // spp loop
}

}  // namespace astroray::wavefront

// pkg64-gpu Phase 1 probe harness — minimal probe that verifies
// GSphere.isCausticCaster survives the CPU→GPU scene upload round-trip.
//
// Invoked via the ASTRORAY_PKG64_GPU_SMS_PROBE env-var hook in
// cuda_renderer.cu::render(). This is NOT a production code path — it
// exists solely so /verify can assert Phase 1 acceptance gate #2 (caster
// flag crosses the upload boundary).
//
// Gate #1 (device/CPU SMS rel-err ≤ 1e-3) requires running the full SMS
// Newton solve on both sides, which needs BVH traversal, material eval, and
// light sampling. That's /verify-deferred (the Phase 1 *core* — device
// header + flag plumbing — has landed; the full probe harness is a follow-up).

#include "astroray/gpu_types.h"
#include "astroray/manifold/sms_attempt.h"   // CPU gatherSphereCasters
#include "raytracer.h"

#include <cstdio>
#include <cstdlib>
#include <vector>

// Host-side probe that reads back the uploaded d_spheres array and checks
// whether the first flagged CPU caster has its isCausticCaster flag set on
// the device side.
void launchPkg64SmsProbe(
    const Renderer& hostRenderer,
    const GBVHNode*   /*d_bvhNodes*/,
    const GPrimitive* /*d_prims*/,
    const GTriangle*  /*d_tris*/,
    const GSphere*    d_spheres,
    const GMaterial*  /*d_materials*/,
    const GLight*     /*d_lights*/,
    int               /*numLights*/)
{
    // Gather CPU-side casters (requireFlag=true → only flagged objects).
    std::vector<astroray::manifold::SMSCaster> casters;
    astroray::manifold::gatherSphereCasters(hostRenderer, casters, true);

    int caster_flag_crossed = 0;
    if (!casters.empty()) {
        const auto& C_cpu = casters[0];
        // Read back the device sphere array (BK7 acceptance scene has ≤10 spheres).
        std::vector<GSphere> host_spheres(10);
        cudaError_t err = cudaMemcpy(host_spheres.data(), d_spheres,
                                     host_spheres.size() * sizeof(GSphere),
                                     cudaMemcpyDeviceToHost);
        if (err != cudaSuccess) {
            std::fprintf(stderr,
                "[pkg64-gpu] sms attempt probe: cudaMemcpy spheres failed: %s\n",
                cudaGetErrorString(err));
        } else {
            // Find the sphere matching C_cpu.center/radius.
            for (size_t i = 0; i < host_spheres.size(); ++i) {
                const GSphere& gs = host_spheres[i];
                float dx = gs.center.x - static_cast<float>(C_cpu.center.x);
                float dy = gs.center.y - static_cast<float>(C_cpu.center.y);
                float dz = gs.center.z - static_cast<float>(C_cpu.center.z);
                float dr = gs.radius - C_cpu.radius;
                if (dx*dx + dy*dy + dz*dz < 1e-4f && dr*dr < 1e-6f) {
                    // Found the caster sphere in d_spheres[i]. Check its flag.
                    caster_flag_crossed = gs.isCausticCaster ? 1 : 0;
                    break;
                }
            }
        }
    }

    // Emit the structured probe line to stderr. Gate #1 (rel-err) is /verify-deferred;
    // this minimal probe only asserts gate #2 (caster flag round-trip).
    // The test will skip gate #1 until the full probe harness lands.
    std::fprintf(stderr,
        "[pkg64-gpu] sms attempt probe: ok=0 fhero=0 fhero_cpu=0 "
        "caster_flag_crossed=%d\n", caster_flag_crossed);
}

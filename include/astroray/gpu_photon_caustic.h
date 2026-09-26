#pragma once
// pkg113 Phase 3 — scene-driven GPU photon-caustic PRE-PASS + persistent grid.
//
// This is the capstone that wires the Phase-1 store (gpu_photon_store.h) and the
// Phase-2 emission math (photon_emission.cu) into the GPU integrator. It runs a
// once-per-frame forward photon trace through the UPLOADED scene's caustic-caster
// glass (using the device BVH), deposits per-λ CIE flux onto receivers, builds a
// RESIDENT hash grid from the deposits, and calibrates the gather radius + the
// Lambertian brightness scale — exactly mirroring the CPU pkg111 pre-pass in
// plugins/integrators/spectral_path_tracer.cpp::buildPhotonMap (l.339-514).
//
// The path-trace megakernel then calls photonGridGather() (gpu_photon_store.h) at
// the first non-emissive hit and adds `albedo · E · scale` to the radiance — the
// device twin of spectral_path_tracer.cpp::sampleFull (l.207-221).
//
// Citations (CLAUDE.md §6; see
// .astroray_plan/docs/pkg113-phase3-gather-wiring-research.md):
//   Jensen 1996/2000 (photon map + §3.1 Eq. 8 density estimate);
//   Arvo 1986 (forward light transport); Schlick 1994 (Fresnel approx);
//   Sellmeier 1871 (n(λ), reused via gpu_dispersion.cuh); CIE 1931 2° CMF;
//   pbrt-v3 sppm.cpp hash grid (BSD-2-Clause); the CPU pkg111 wiring above.
//
// Pure-C++-safe: the host-callable build/free entry points and the result POD
// are declared unconditionally so cuda_renderer.cu (and only it) calls them; the
// device GPhotonGrid view is from gpu_photon_store.h (already #ifdef-guarded).

#include "astroray/gpu_photon_store.h"   // GPhoton, GPhotonGrid
#include "astroray/gpu_types.h"          // GVec3, GBVHNode, GPrimitive, ...
#include "astroray/photon_emitter.h"     // PhotonEmitter, PhotonLight (pkg286/287)

#include <vector>

namespace astroray {
namespace photon {
namespace gpu {

// Host-side aim for the forward photon trace, built in gpu_wavefront_snapshot.cu
// from the same CPU Renderer the CPU integrator reads (photon_lights.h). pkg286:
// photons carry physical flux (no peak calibration); pkg287: one emitter per
// dedicated lamp (point/spot/distant/area), each launched with its own share of
// photonCount, SPD CDF and RNG stream. Host-only (holds std::vector); passed by
// const& (memory/mingw_large_struct_byval).
struct PhotonCausticAim {
    std::vector<PhotonLight> lights;  // emitters + SPD CDF (+ host IES table)
    int   photonCount;     // total forward photons, split over lights
    float lambdaMin;       // 380 nm
    float lambdaMax;       // 720 nm
    int   maxDepth;        // refraction-bounce cap (CPU maxDepth_)
    float boost;           // artistic multiplier on the physical caustic (default 1.2)
    bool  valid;           // false → no casters / no emitting lamps → skip the pre-pass
    // pkg220: per-iteration decorrelation seed for the photon jitter (#909: a
    // fresh seed per photon round); the aim geometry stays deterministic.
    unsigned int seed;
};

// A RESIDENT device photon grid + gather scale. Built by
// cuda_photon_caustic_build, read by the megakernel (the GPhotonGrid `grid` view
// is passed by value to the kernel; `scale` = boost/π, the Lambertian 1/π on a
// physical irradiance estimate, pkg286). freed by cuda_photon_caustic_free. The opaque `owner` pointer
// holds the device CSR buffers + deposit array so they stay alive for the render.
struct GPhotonCausticResult {
    GPhotonGrid grid;        // device view handed to the megakernel (by value)
    float       scale;       // boost/π (pkg286)
    int         numPhotons;  // deposits that survived the trace
    bool        ready;       // false → grid empty / not enough photons → no gather
    void*       owner;       // opaque RAII handle (device buffers); free via _free
};

// Run the forward photon trace through the uploaded scene's caustic-caster glass,
// build a resident hash grid, and calibrate the gather radius. Returns a result
// whose `.grid` view + `.scale` the megakernel uses, and whose `.owner` must be
// passed to cuda_photon_caustic_free after the render. `aim.valid==false` (or no
// surviving deposits) yields `ready==false` and a null owner (nothing to free).
//
// The device scene pointers are the SAME arrays the path-trace kernel traverses
// (impl->d_bvhNodes etc. in cuda_renderer.cu), so the photon trace and the camera
// pass see one identical scene.
GPhotonCausticResult cuda_photon_caustic_build(
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres,
    const GMaterial*  d_materials,
    const PhotonCausticAim& aim);

// Release the resident device buffers held by a result's owner handle. Safe to
// call with a null/`ready==false` result (no-op).
void cuda_photon_caustic_free(GPhotonCausticResult& result);

}  // namespace gpu
}  // namespace photon
}  // namespace astroray

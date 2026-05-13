// integrator_state_soa.h — pkg55 Phases A.1 + B
//
// SoA path-state buffers for the wavefront GPU pipeline.
//
// Phase A.1 (-DASTRORAY_WAVEFRONT_INTERSECT=ON):
//   primary-ray init + closest-hit intersect parity check only.
//   AoS megakernel is unchanged and remains the production default.
//
// Phase B (-DASTRORAY_WAVEFRONT_SHADE=ON, implies INTERSECT):
//   full per-material shade queue dispatch + pixel accumulation.
//   Introduces wavefront_path_tracer integrator alongside the megakernel.
//   The AoS megakernel stays live through Phase B; Phase C removes it.
//
// References (Apache-2.0; cited per-file):
//   - intern/cycles/kernel/integrator/state.h  — Cycles IntegratorState
//     SoA field set + naming (ray_P, ray_D, throughput, path_flag, rng_hash).
//   - intern/cycles/kernel/integrator/shade_surface.h — shade dispatch.
//   - mmp/pbrt-v4 src/pbrt/wavefront/workitems.soa — SOA<RayWorkItem> layout.
//   - Laine, Karras, Aila 2013 §4 (HPG, DOI 10.1145/2492045.2492060):
//     SoA per-ray state in global memory between stages for coherent warps.
//
// Alignment: vec3 fields as float4 (w=0), 16-byte coalesced loads everywhere.

#ifndef ASTRORAY_INTEGRATOR_STATE_SOA_H
#define ASTRORAY_INTEGRATOR_STATE_SOA_H

#include <cstddef>
#include <cstdint>
#include "astroray/gpu_types.h"

namespace astroray::wavefront {

// ---------------------------------------------------------------------------
// IntegratorStateSoA — flat device pointer arrays, one per per-path field.
//
// Phase A.1 fields (written by stage_init / stage_intersect):
//   ray_origin[i]     — float4 (w=0)
//   ray_direction[i]  — float4 (w=0)
//   throughput[i]     — float4 RGB (w=0)
//   pdf[i]            — last-event PDF (float), used for MIS
//   pixel_index[i]    — flat pixel id == RNG slot id (int)
//   sample_index[i]   — sample counter within pixel (int)
//   depth[i]          — bounce count (int)
//   hit_t[i]          — closest-hit distance; <0 = miss (float)
//   hit_prim[i]       — primId; -1 = miss (int)
//   hit_mat[i]        — materialId; -1 = miss (int)
//   sort_key[i]       — (alive<<31 | mat_type<<4) for CUB radix sort (uint32)
//   rng_state[i]      — curandState (void*)
//
// Phase B additions (written by stage_intersect_full + shade kernels):
//   hit_point[i]      — float4 (w=0)
//   hit_normal[i]     — float4 (w=0)
//   hit_tangent[i]    — float4 (w=0)
//   hit_bitangent[i]  — float4 (w=0)
//   hit_flags[i]      — uint8: bit0=frontFace, bit1=isDelta
//   path_alive[i]     — uint8: 1=active, 0=terminated
//   was_specular[i]   — uint8: last bounce was delta (MIS flag)
//   lambda[i]         — float4: GSampledWavelengths.lambda[4]
//   lambda_pdf[i]     — float4: GSampledWavelengths.pdf[4]
//   throughput_sp[i]  — float4: GSampledSpectrum.v[4]
//   accum_rgb[i]      — float4: accumulated radiance RGB + sample count (w)
//   nee_contrib[i]    — float4: NEE radiance to add if shadow unoccluded (RGB, w=0)
//   shadow_origin[i]  — float4: shadow ray origin (w=0)
//   shadow_dir[i]     — float4: shadow ray direction (w=0)
//   shadow_tmax[i]    — float: shadow ray tmax
//   nee_active[i]     — uint8: 1 if shadow ray queued
//
// POD struct; copy by value into kernels is safe.
struct IntegratorStateSoA {
    // --- Phase A.1 ---
    void*     ray_origin    = nullptr;  // float4*
    void*     ray_direction = nullptr;  // float4*
    void*     throughput    = nullptr;  // float4* (RGB, w=0)
    float*    pdf           = nullptr;
    int*      pixel_index   = nullptr;
    int*      sample_index  = nullptr;
    int*      depth         = nullptr;
    float*    hit_t         = nullptr;
    int*      hit_prim      = nullptr;
    int*      hit_mat       = nullptr;
    uint32_t* sort_key      = nullptr;
    void*     rng_state     = nullptr;  // curandState*

    // --- Phase B: shade geometry ---
    void*    hit_point      = nullptr;  // float4*
    void*    hit_normal     = nullptr;  // float4*
    void*    hit_tangent    = nullptr;  // float4*
    void*    hit_bitangent  = nullptr;  // float4*
    uint8_t* hit_flags      = nullptr;  // bit0=frontFace bit1=isDelta
    uint8_t* path_alive     = nullptr;
    uint8_t* was_specular   = nullptr;

    // --- Phase B: spectral ---
    void*    lambda         = nullptr;  // float4* (wavelengths)
    void*    lambda_pdf     = nullptr;  // float4* (wavelength pdfs)
    void*    throughput_sp  = nullptr;  // float4* (spectral throughput)

    // --- Phase B: accumulation ---
    void*    accum_rgb      = nullptr;  // float4* (R,G,B,sample_count)

    // --- Phase B: NEE shadow queue ---
    void*    nee_contrib    = nullptr;  // float4* (RGB, w=0)
    void*    shadow_origin  = nullptr;  // float4*
    void*    shadow_dir     = nullptr;  // float4*
    float*   shadow_tmax    = nullptr;
    uint8_t* nee_active     = nullptr;

    // Sizing.
    int capacity   = 0;
    int num_active = 0;
};

// Allocate / free all device buffers.
bool allocateSoAState(IntegratorStateSoA& s, int capacity);
void freeSoAState    (IntegratorStateSoA& s);

// ---------------------------------------------------------------------------
// Phase A.1 launchers
// ---------------------------------------------------------------------------

void launchStageInit(
    IntegratorStateSoA& state,
    const GCameraParams& cam,
    int width, int height);

void launchStageIntersect(
    IntegratorStateSoA& state,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres);

int launchIntersectParity(
    const IntegratorStateSoA& state,
    const void*       rng_snapshot,
    const GCameraParams& cam,
    int width, int height,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres);

// ---------------------------------------------------------------------------
// Phase B launchers
// ---------------------------------------------------------------------------

// Extended intersect: Phase A.1 BVH traversal + unpack full GHitRecord into
// Phase B geometry fields (hit_point/normal/tangent/bitangent/hit_flags).
// Writes Phase B sort_key: (alive<<31 | mat_type<<4).
// Defined in stage_intersect_full.cu.
void launchStageIntersectFull(
    IntegratorStateSoA& state,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres);

// CUB DeviceRadixSort on sort_key: dead paths (key=0) sort first, then
// material buckets in material_type order. Call sortScratchBytes first
// with d_temp=nullptr to size the scratch buffer.
// Defined in material_sort.cu.
size_t sortScratchBytes(int n);
void   sortByMaterial  (IntegratorStateSoA& state, void* d_temp, size_t temp_bytes);

// Per-material shade kernels. Each processes all active slots whose
// GMaterialType matches. Reads: ray_direction, hit geometry, d_mats[hit_mat].
// Writes: ray_direction (next bounce), shadow_* (NEE queue), nee_contrib,
// accum_rgb (emission term), throughput (updated), hit_flags, was_specular,
// path_alive.
// Reference: Cycles intern/cycles/kernel/integrator/shade_surface.h (Apache-2.0).
void launchShadeLambertian(
    IntegratorStateSoA& state, const GMaterial* d_mats,
    const GLight* d_lights, int numLights, float totalLightPower,
    const GPrimitive* d_prims, const GTriangle* d_tris, const GSphere* d_spheres,
    const GEnvMap& envMap, GVec3 bgColor, bool hasBg,
    const GBVHNode* d_bvhNodes, int maxDepth);
void launchShadeMetal(
    IntegratorStateSoA& state, const GMaterial* d_mats,
    const GLight* d_lights, int numLights, float totalLightPower,
    const GPrimitive* d_prims, const GTriangle* d_tris, const GSphere* d_spheres,
    const GEnvMap& envMap, GVec3 bgColor, bool hasBg,
    const GBVHNode* d_bvhNodes, int maxDepth);
void launchShadeDielectric(
    IntegratorStateSoA& state, const GMaterial* d_mats, int maxDepth);
void launchShadeDiffuseLight(
    IntegratorStateSoA& state, const GMaterial* d_mats);
void launchShadeDisney(
    IntegratorStateSoA& state, const GMaterial* d_mats,
    const GLight* d_lights, int numLights, float totalLightPower,
    const GPrimitive* d_prims, const GTriangle* d_tris, const GSphere* d_spheres,
    const GEnvMap& envMap, GVec3 bgColor, bool hasBg,
    const GBVHNode* d_bvhNodes, int maxDepth);
void launchShadeThinGlass(
    IntegratorStateSoA& state, const GMaterial* d_mats, int maxDepth);
void launchShadeClosureGraph(
    IntegratorStateSoA& state, const GMaterial* d_mats,
    const GLight* d_lights, int numLights, float totalLightPower,
    const GPrimitive* d_prims, const GTriangle* d_tris, const GSphere* d_spheres,
    const GEnvMap& envMap, GVec3 bgColor, bool hasBg,
    const GBVHNode* d_bvhNodes, int maxDepth);

// Shadow stage: any-hit BVH test; adds nee_contrib to accum_rgb when clear.
void launchStageShadow(
    IntegratorStateSoA& state,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres);

// Miss stage: adds env/bg radiance to accum_rgb for escaped rays (hit_t<0).
void launchStageMiss(
    IntegratorStateSoA& state,
    const GEnvMap& envMap,
    GVec3 backgroundColor, bool hasBackgroundColor);

// Terminate stage: Russian roulette; marks dead paths; preps next bounce.
void launchStageTerminate(IntegratorStateSoA& state, int maxDepth);

// Write accumulated RGB to framebuffer (spp-normalised).
void launchWriteAccumulated(
    const IntegratorStateSoA& state,
    float* d_framebuffer,
    int samplesPerPixel, int totalPixels);

// Full wavefront render loop:
//   init → for bounce in [0, maxDepth):
//     intersect_full → sort → shade×7 → shadow → miss → terminate
//   → writeAccumulated
// Defined in wavefront_render_loop.cu.
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
    void* d_sortScratch, size_t sortScratchBytes);

}  // namespace astroray::wavefront

#endif  // ASTRORAY_INTEGRATOR_STATE_SOA_H

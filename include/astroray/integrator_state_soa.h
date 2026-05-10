// integrator_state_soa.h — pkg55 Phase A.1
//
// SoA path-state buffers for the wavefront GPU pipeline. One field per
// per-path datum, each laid out as a flat device array indexed by the
// per-path slot id. Only allocated / referenced when the build is
// configured with -DASTRORAY_WAVEFRONT_INTERSECT=ON; the AoS megakernel
// in path_trace_kernel.cu remains the production default and is bit-
// identical with this header absent.
//
// Field selection follows the canonical wavefront layouts cited below.
// We mirror the *minimum* set required for primary-ray init + closest-
// hit intersect (Phase A.1 scope): origin/direction/throughput/pdf/depth
// /pixel/RNG plus the closest-hit record. Shade / shadow / NEE state is
// added in Phase B; emission accumulation in Phase C.
//
// References (Apache-2.0; cite, do not blindly mirror):
//   - intern/cycles/kernel/integrator/state.h
//     (Cycles' IntegratorState — defines the SoA field set per stage,
//      tagged by integrator_state_template.h. Field-name parity below
//      is intentional: ray_P/ray_D/throughput/path_flag/rng_hash.)
//   - mmp/pbrt-v4 src/pbrt/wavefront/workitems.soa
//     (PBRT-v4's SOA<RayWorkItem>/SOA<HitAreaLightWorkItem> layout —
//      same pattern: one global pointer per scalar field, addressed by
//      a single workitem index.)
//   - Laine, Karras, Aila 2013 §4 "Wavefront Path Tracing" (HPG 2013,
//     DOI 10.1145/2492045.2492060): SoA per-ray state in global memory
//     between stages is the layout that makes split-kernel coherent.
//
// Padding / alignment notes:
//   - vec3-style fields stored as float4 (w=0). Cycles state.h uses
//     `packed_float3` with explicit pad; PBRT uses float arrays. Either
//     works; float4 gives unconditional 16-byte aligned coalesced loads
//     on every CC and avoids the 12-byte struct-pitch trap.
//   - Allocation count: see pkg55 spec §"Phase A — Key design decisions"
//     point 1. ASTRORAY_CONCURRENT_PATHS_FACTOR (env, default 16) follows
//     Cycles' CYCLES_CONCURRENT_STATES_FACTOR convention.

#ifndef ASTRORAY_INTEGRATOR_STATE_SOA_H
#define ASTRORAY_INTEGRATOR_STATE_SOA_H

#include <cstddef>
#include <cstdint>

// GCameraParams / GBVHNode / GPrimitive / GTriangle / GSphere live at
// global scope in gpu_types.h. Including the header here keeps the
// launcher signatures in this header bound to the same types
// gpu_bvh_hit() expects.
#include "astroray/gpu_types.h"

namespace astroray::wavefront {

// ---------------------------------------------------------------------------
// IntegratorStateSoA — flat per-path device pointer arrays.
//
// All pointers are device addresses. `capacity` is the maximum number of
// concurrent in-flight paths the buffers can hold (see allocateSoAState()
// for the sizing rule). For Phase A.1 the wavefront pipeline runs one
// stage at a time over [0, num_active) without compaction; capacity is
// therefore exactly the pixel count for the parity smoke-test launches.
//
// Field meanings (per path slot i):
//   ray_origin[i]    — primary ray origin    (float4, w=0; 16-byte aligned)
//   ray_direction[i] — primary ray direction (float4, w=0; not normalized
//                      — matches GRay ctor behaviour from gpu_types.h)
//   throughput[i]    — RGB throughput so far (float4, w=0)
//   pdf[i]           — last sampling PDF
//   pixel_index[i]   — flat pixel index (px + py*width); also doubles as
//                      the per-pixel rng slot id, so RNG keying matches
//                      the AoS megakernel exactly (rngStates[pixelIdx]).
//   sample_index[i]  — sample-within-pixel counter (0 in Phase A.1)
//   depth[i]         — current bounce count (0 after init)
//   hit_t[i]         — closest-hit distance from stage_intersect; <0 if miss
//   hit_prim[i]      — primId from gpu_bvh_hit; -1 if miss
//   hit_mat[i]       — materialId from gpu_bvh_hit; -1 if miss
//   sort_key[i]      — packed (material_type<<24 | path_alive<<23 | ...)
//                      for Phase B's CUB radix sort. Phase A.1 only writes
//                      hit_mat into the low bits as a placeholder.
//   rng_state[i]     — per-path curandState. Phase A.1 keeps a 1:1 map
//                      with the megakernel's d_rngStates array (Cycles
//                      `rng_pixel`+`rng_offset` convention; pkg55 spec
//                      §A key design decision 4).
//
// The struct is POD; copy by value into kernels.
struct IntegratorStateSoA {
    // float4 device pointers (16-byte aligned; w-channel unused).
    void* ray_origin     = nullptr;  // float4*
    void* ray_direction  = nullptr;  // float4*
    void* throughput     = nullptr;  // float4*

    // Scalar device arrays.
    float* pdf           = nullptr;
    int*   pixel_index   = nullptr;
    int*   sample_index  = nullptr;
    int*   depth         = nullptr;

    // Hit record (closest-hit), written by stage_intersect.
    float* hit_t         = nullptr;
    int*   hit_prim      = nullptr;
    int*   hit_mat       = nullptr;
    uint32_t* sort_key   = nullptr;

    // RNG. Pointer to curandState, but typed as void* so this header
    // does not pull in <curand_kernel.h>.
    void*  rng_state     = nullptr;  // curandState*

    // Sizing.
    int    capacity      = 0;        // total slot count
    int    num_active    = 0;        // [0, capacity); written by host
};

// Allocation / free helpers, defined in src/gpu/wavefront/queue_dispatch.cpp.
// `capacity` should be width*height for the Phase A.1 1:1 pixel-to-slot
// parity launch path. Returns true on success.
bool  allocateSoAState (IntegratorStateSoA& s, int capacity);
void  freeSoAState     (IntegratorStateSoA& s);

// Phase A.1 launchers. Defined in stage_init.cu / stage_intersect.cu.
// They are no-ops in builds without -DASTRORAY_WAVEFRONT_INTERSECT=ON,
// because nothing references this header outside the wavefront sources.

// stage_init: writes ray_origin/ray_direction/pixel_index/depth/etc.
// for slot i, advancing the per-pixel curandState exactly as the AoS
// megakernel's first sample-iteration would.
void launchStageInit(
    IntegratorStateSoA& state,
    const GCameraParams& cam,
    int width, int height);

// stage_intersect: reads ray_origin/direction, runs gpu_bvh_hit, writes
// hit_t/hit_prim/hit_mat/sort_key.
void launchStageIntersect(
    IntegratorStateSoA& state,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres);

// Parity verifier — re-runs the AoS-equivalent reference path for each
// slot using a *snapshot* of the pre-init RNG, calls gpu_bvh_hit, and
// compares to (hit_t, hit_prim, hit_mat) written by stage_intersect.
// On mismatch: printf the diverging values, then __trap(). Returns
// number of mismatches found (always 0 on success; non-zero means
// __trap fired and we never get here, but kept for diagnostic use in
// non-trap builds).
//
// `rng_snapshot` is a device pointer to a curandState buffer of the
// same length as state.rng_state, captured before stage_init advanced
// it. Pass nullptr to skip parity (used for benchmark-only launches).
int launchIntersectParity(
    const IntegratorStateSoA& state,
    const void*       rng_snapshot,        // curandState*
    const GCameraParams& cam,
    int width, int height,
    const GBVHNode*   d_bvhNodes,
    const GPrimitive* d_prims,
    const GTriangle*  d_tris,
    const GSphere*    d_spheres);

}  // namespace astroray::wavefront

#endif  // ASTRORAY_INTEGRATOR_STATE_SOA_H

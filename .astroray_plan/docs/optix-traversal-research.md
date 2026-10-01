# OptiX hardware traversal (pkg299) — research note

## Sources (licence-compatible)

- **NVIDIA OptiX SDK 9.1.0 samples** (BSD-3-Clause, `SDK/optixRaycasting`,
  `SDK/optixTriangle`): the "rays from a CUDA buffer, hits to a CUDA buffer"
  pattern (`__raygen__from_buffer` / `__closesthit__buffer_hit` /
  `__miss__buffer_miss`), module/program-group/pipeline/SBT creation, and
  `optixAccelBuild` + compaction. Local copy:
  `C:\ProgramData\NVIDIA Corporation\OptiX SDK 9.1.0\SDK\`.
- **NVIDIA OptiX 9.1 Programming Guide** (`doc/OptiX_Programming_Guide_9.1.0.pdf`):
  - §Ray flags (p.147–148): `OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT` "causes the
    very first hit ... to abort further traversal ... useful for shadow rays";
    `OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT` still runs the miss program.
  - §Triangle build inputs: triangles whose vertices are NaN are inactive
    (unintersectable) and may be removed; primitive indices keep input order.
  - `optixDeviceContextGetProperty(OPTIX_DEVICE_PROPERTY_RTCORE_VERSION)`: 0 =
    no RT cores.
- **pbrt-v4** `src/pbrt/gpu/optix/optix.cu`, `src/pbrt/gpu/aggregate.cpp`
  (Apache-2.0): OptiX used for traversal only inside a CUDA wavefront — the
  raygen reads the ray queue by launch index, closest-hit writes the
  intersection, shadow rays set "unoccluded" in the miss program.
- **Cycles** `intern/cycles/kernel/device/optix/kernel.cu` (Apache-2.0): IAS over
  per-object GAS; shadow rays use terminate-on-first-hit.

## Design as implemented (Phase 0 + 1)

- The OptiX programs only traverse. Closest-hit writes (t, primitive index,
  barycentrics b1/b2, instance id) to a per-slot side buffer; the existing CUDA
  intersect kernel (`intersectPathSlotT<..., HwHits=true>`) rebuilds the
  `GHitRecord` with the same code the software BVH uses after its own
  Möller–Trumbore test (`gpu_triangle_fill_rec`, `gpu_instance_rec_to_world`),
  so shading sees identical record semantics.
- Shadow rays: `TERMINATE_ON_FIRST_HIT | DISABLE_CLOSESTHIT | DISABLE_ANYHIT`,
  payload initialised to "occluded", miss clears it. `tmin = 0.001`,
  `tmax = maxDist` lane exactly as `gpu_nee_occlude` (1e30 sentinel for env /
  distant rays is an occlusion extent, never a distance).
- GAS primitive index == global `prims[]` index (single level) or BLAS-local
  index (instanced); non-triangle prims (GPRIM_SKIP) are NaN triangles.
- Barycentric convention: `optixGetTriangleBarycentrics()` returns (b1, b2)
  with P = (1-b1-b2)·v0 + b1·v1 + b2·v2 — the same (u, v) Möller–Trumbore
  yields, so normal interpolation is unchanged.

## Edge semantics (watertight vs Möller–Trumbore)

RT-core triangle tests are watertight (Woop, Benthin, Wald 2013, "Watertight
Ray/Triangle Intersection", JCGT 2(1)): a ray through a shared edge hits exactly
one of the two triangles. The software Möller–Trumbore test (`gpu_triangle_hit`)
is not watertight — rays through an edge or vertex can miss both triangles
(cracks) or hit both — and it rejects |det| < 1e-6 (an absolute epsilon on
e1·(d×e2), which scales with triangle area, so it also drops rays against
very small or grazing triangles). Fixed-ray A/B mismatches are therefore
expected at edges and on sub-millimetre / grazing triangles; the hardware
answer is the geometrically correct one.

## Eligibility (Phases 0–1)

Hardware traversal runs only for scenes whose geometry is all triangles with no
deformation motion: no spheres, no curves, no motion vertices. Everything else,
and `ASTRORAY_GPU_TRAVERSAL=software`, uses the software BVH unchanged. The
transparent-shadow walk (`HasAlphaShadow`) stays on the software BVH in Phase 1.

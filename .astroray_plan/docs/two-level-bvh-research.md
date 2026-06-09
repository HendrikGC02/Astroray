# Two-level BVH (TLAS over per-mesh BLAS) — Research (pkg114)

CLAUDE.md §6 gate for pkg114. Cite-first; this note precedes code.
Cross-verified against PBRT-v4, Cycles, and Embree/OptiX (research workflow
`wf_52dd8c37-b5a`, 2026-06-10).

## Paper / canonical references

1. **PBRT-v4 (object instancing).** Pharr, Jakob, Humphreys, *Physically Based
   Rendering: From Theory to Implementation*, 4th ed. (2023), Ch.7 §7.1.2
   (`TransformedPrimitive` / `AnimatedPrimitive`) and §6.1.4 (ray-`t` invariance
   under a transform). Online: https://pbr-book.org/4ed/Primitives_and_Intersection_Acceleration/Primitive_Interface_and_Geometric_Primitives
2. **Embree.** Wald, Woop, Benthin, Johnson, Ernst, "Embree: A Kernel Framework
   for Efficient CPU Ray Tracing", *ACM TOG* 33(4):143 (SIGGRAPH 2014).
   DOI: 10.1145/2601097.2601199. Two-level instanced BVH; `rtcSetGeometryTransform`
   takes a 3×4 local→world per instance.
3. **NVIDIA OptiX Programming Guide** — `OptixInstance` (object→world 3×4
   row-major), IAS-over-GAS (instance accel over geometry accel),
   `optixTransformNormalFromObjectToWorldSpace` (inverse-transpose).
4. **GPU traversal basis.** Aila & Laine, "Understanding the Efficiency of Ray
   Traversal on GPUs", HPG 2009 (the stack-loop our `gpu_bvh_hit` already mirrors).

## Reference implementations (all license-clean for MIT)

| Source | License | Files we mirror |
|---|---|---|
| **pbrt-v4** `github.com/mmp/pbrt-v4` | **Apache-2.0** (SPDX per-file; `LICENSE.txt`) | `src/pbrt/cpu/primitive.cpp` `TransformedPrimitive::Intersect/IntersectP/Bounds`; `src/pbrt/util/transform.h` `Transform::ApplyInverse(const Ray&, Float*)` + `operator()` for Point/Vector/Normal; `src/pbrt/cpu/aggregates.cpp` `LinearBVHNode` + `flattenBVH` |
| **Cycles** `github.com/blender/cycles` | **Apache-2.0** | `src/bvh/bvh2.cpp` `pack_instances`; `src/kernel/bvh/bvh.h` + `traversal.h` (`bvh_instance_push`/`pop`); `src/kernel/geom/object.h` `object_fetch_transform(OBJECT_INVERSE_TRANSFORM)`; `src/util/transform.h` `transform_point`/`transform_direction`/`transform_direction_transposed` |
| **Embree / OptiX** | **Apache-2.0** (Embree) / NVIDIA docs (OptiX) | the IAS/GAS + 3×4-instance + inverse-transpose-normal concept |

> **Cycles deep-dive appendix.** A detailed Cycles-specific porting reference
> (exact `bvh2.cpp::pack_instances` concatenation/offset logic, the
> `object_node` BLAS-root encoding, `bvh_instance_push`/`pop`,
> `object_fetch_transform`, the `Transform` 4×3 layout) lives in
> `pkg114-cycles-twolevel-bvh-research.md` — consult it when implementing
> increment 2's real multi-instance traversal.

> **License correction.** The pkg114 spec assumed pbrt is BSD-3-Clause. That was
> true for **pbrt-v3**; **pbrt-v4 is Apache-2.0**. Apache-2.0 is on CLAUDE.md §6's
> allow-list and is compatible with Astroray's MIT. Apache obligations when
> porting: preserve copyright/attribution, state the changes made. Cycles is also
> Apache-2.0. Both are fine; cite as Apache-2.0.

## What we reproduce

A two-level acceleration structure:

- **BLAS** (bottom level): one BVH per unique mesh datablock, built once over the
  mesh's **object-local** triangles. Reuses Astroray's existing `BVHAccel`
  (`include/raytracer.h:1114`) and the GPU `GBVHNode` layout (`gpu_types.h:221`),
  which is byte-for-byte PBRT-v4's `alignas(32) LinearBVHNode` (24 B bounds +
  union offset + `uint16 nPrimitives` + `uint8 axis` + pad = 32 B).
- **TLAS** (top level): a BVH over per-instance **world-space AABBs**, whose
  leaves index an instance list. The TLAS reuses the **same** `GBVHNode` layout
  (PBRT: "the TLAS is just another BVH"). `GTLASNode = GBVHNode`.
- **`GInstance`**: a `(BLAS ref, 4×4 worldFromObject M, 4×4 objectFromWorld Minv,
  instanceId)` record. Both M and Minv are precomputed **host-side** (pbrt's
  `ApplyInverse` and Cycles' `object_fetch_transform` both read a precomputed
  inverse — never invert per-ray on device).

### The core device math (identical across all three references)

At a TLAS instance node, transform the **world** ray into **BLAS-local** space:

```
o_local = Minv · o_world          (point: full 4×4 + homogeneous w-divide, incl. translation)
d_local = Minv_3x3 · d_world       (vector: upper 3×3, NO translation, *** NOT renormalized ***)
```

Because `o_world + t·d_world = M·(o_local + t·d_local)`, the **same `t`** satisfies
both spaces ⇒ **local `t` == world `t`**. Therefore:

- The global `tMax` is seeded into every BLAS traversal **unchanged** and shrinks
  on each closer hit — one shared cutoff across both levels (Cycles "modern push";
  PBRT copies `tMax` back by reference). The returned `tHit` is **never rescaled**.
- This only holds if `d_local` is **not renormalized**. The classic alternative
  (normalize `d_local`, then scale `t` by `len(Minv·d_world)` on push/pop) is
  mathematically equivalent but adds a multiply per push/pop and is the documented
  #1 instancing footgun — we reject it.

On a hit, transform the local interaction **back to world**:

```
point_world  = M · point_local                  (or exactly o_world + tHit·d_world)
normal_world = normalize( (Minv_3x3)^T · normal_local )   *** inverse-transpose, renormalize ***
tangent_world= normalize( M_3x3 · tangent_local )         (vectors use M, not Minv^T)
frontFace    = dot(d_world, normal_world) < 0              (recomputed in WORLD space)
```

- **Inverse-transpose for normals** is load-bearing: under non-uniform scale, a
  normal transformed by M shears off the surface. (pbrt `Transform::operator()(Normal3)`
  reads `mInv` transposed; OptiX `optixTransformNormalFromObjectToWorldSpace`.)
- **frontFace recomputed in world space** (not copied from local winding) so a
  negative-determinant (mirror) instance, which flips winding, gets the correct
  front/back — this is the same bug class as Astroray's prior refraction
  frontFace bug (memory `refraction-frontface-bug`).

### Per-instance world AABB (TLAS build)
Transform the **8 corners** of the BLAS root AABB by M and take their bound
(Embree/OptiX convention).

### Complexity / the win
N instances of an M-triangle mesh: **build** O(M log M + N log N), **memory**
O(M + N) — vs flattened O(N·M). (PBRT Moana: ~4 GB instanced vs ~516 GB flattened;
vertices never copied per instance.)

## Astroray-specific decisions (differences from the references)

1. **`GRay` ctor renormalizes (`gpu_types.h:193`).** None of the references have
   this. The local ray must carry the **un-normalized** `d_local`, so we
   **default-construct `GRay` and field-assign** `origin`/`direction` — exactly
   the in-repo precedent the wavefront stages already use and document
   (`src/gpu/wavefront/stage_intersect.cu:58`). This touches **none** of
   `gpu_bvh_hit` / `GAABB::hit` / `gpu_triangle_hit` — they already treat
   `ray.direction` as the vector `t` is measured against, with no unit assumption
   (Möller–Trumbore `t` is in units of `|d|`; the slab test uses `1/d` and is
   scale-consistent).
2. **BLAS-local node offsets.** `gpu_bvh_hit` uses `curr+1` / `secondChildOffset`
   as indices into the array **base** it is handed. So each BLAS is flattened
   **independently starting at node 0** (its `secondChildOffset`s are BLAS-local),
   and the TLAS traversal hands `gpu_bvh_hit` the pointer `blasNodes + blas.nodeOffset`
   as the base. Invariant: never feed `gpu_bvh_hit` a concatenated multi-BLAS node
   array with global offsets. (Asserted host-side.)
3. **`primId` remap keeps a single global `prims[]` index space.** Inside a BLAS,
   `gpu_bvh_hit` sets `lrec.primId = leafOffset + i` (BLAS-local); the TLAS wrapper
   rewrites `rec.primId = blas.primOffset + lrec.primId` into the shared global
   `prims[]`. Cryptomatte's `prims[rec.primId]` and NEE's `prims[l.primitiveIndex]`
   keep working unchanged. `GPRIM_SKIP` index-alignment (`scene_upload.cu:343`) is
   preserved **within** each BLAS.
4. **Per-instance object identity** (two instances of one mesh need distinct
   Cryptomatte IDs) needs `int instanceId` added to `GHitRecord`; resolved via
   `instances[rec.instanceId].objectHash`. **Deferred to increment 2** (increment
   1 has a single identity instance whose prim hashes equal today's, so it stays
   identical with **no** `GHitRecord`/Cryptomatte change).
5. **PBRT's sub-epsilon `dt` origin nudge** (`ApplyInverse` float-error bound) is
   dropped for the first cut; non-degenerate transforms don't need it.

## What we deliberately do NOT take
- Cycles' negated-leaf node-sign encoding and `ENTRYPOINT_SENTINEL` stack scheme —
  Astroray's `gpu_bvh_hit` already has a clean `nPrimitives>0`-leaf + explicit
  `stack[64]` loop; we keep it and add a sibling `gpu_tlas_hit`.
- The classic normalize-and-scale-`t` push/pop (rejected above).
- Motion-blur / `AnimatedPrimitive` time interpolation (out of scope; pkg88).
- An any-hit/shadow fast path (`gpu_tlas_any_hit`) — Astroray reuses closest-hit
  for shadow rays today; matching that keeps the diff minimal. Perf follow-up.

## Integration plan in Astroray (incremental, RTX-verified per increment)

- **Increment 1 — structs + `gpu_tlas_hit` + identity-passthrough parity probe.**
  Add `GMat4`, `GBLAS`, `GInstance`, `GTLASNode` alias (`gpu_types.h`); add
  `gpu_tlas_hit` (`include/astroray/gpu_bvh.h`); a host helper that synthesizes a
  single identity BLAS+instance+TLAS from a `SceneUploadResult`; a **device dual-trace
  parity probe** (mirrors `src/gpu/wavefront/intersect_parity.cu`) that asserts
  `gpu_tlas_hit`(identity) ≡ `gpu_bvh_hit` over the camera rays of a real scene
  (fp-exact on `t`/`primId`/`materialId`/`frontFace`/`point`; ≤1e-6 on `normal`,
  since identity inverse-transpose + renormalize can drift ≤1 ulp). **Touches no
  production kernel** ⇒ zero render risk. Test: `tests/test_tlas_blas_parity.py`.
  Verify on RTX.
- **Increment 2 — multi-instance + real transforms.** Host mesh/instance API
  (`register_mesh` → BLAS once; `add_instance(meshId, 4×4)`), add `GHitRecord.instanceId`,
  route the production megakernel(s) through `gpu_tlas_hit`, host unit-test
  `GMat4` xform helpers vs a numpy reference, **full-render pixel parity** of N
  transformed instances vs the flattened/baked-world-space scene (per-channel
  mean-ratio gate, per memory `ssim-wrong-gate-for-independent-rng`), and a visual
  check of a rotated + **non-uniform-scaled** + a **mirror-scaled** instance
  (proves inverse-transpose + frontFace-recompute). RTX `/verify`.
- **Increment 3 — memory/build win + depsgraph refit.** BLAS cache across frames;
  Blender transform-only edit → **TLAS-only** rebuild (pkg56 §4.1 deferral; the
  `_renderer_object_id_map` + `update_object_transform` hook,
  `module/blender_module.cpp`); measure device geometry ≈ 1× mesh for N instances.

## Deferred / follow-up (fundamental fork surfaced to owner)
- **Multi-instance emissive/area-light NEE.** `GLight.primitiveIndex`
  (`scene_upload.cu:366`) and `GAreaLight` world-baked verts assume one global prim
  list with world-space emitters; they are not instancing-aware. Increments 1–3
  keep the single-instance/identity emitter path pixel-identical; **instanced
  *emissive* geometry is a separate package** (per-instance emitter power,
  transformed area, MIS re-keying to an (instance,prim) join). File a follow-up
  before shipping instanced emitters. (Owner-flagged; non-blocking for pkg114's
  acceptance, which is about instanced *geometry* + transform-edit budget +
  pixel parity.)

## Open questions
- None blocking. The above emissive-instancing fork is deferred by design, not a
  prerequisite.

# pkg298 research note: BVH cache, parallel build, path-pool floor (2026-09-30)

Sources for the algorithms pkg298 changed (CLAUDE.md §6).

## Parallel binned-SAH build

- Paper: I. Wald, "On fast Construction of SAH-based Bounding Volume
  Hierarchies", IEEE RT 2007. Binned SAH (12 buckets here, unchanged).
- Reference: pbrt-v4 `src/pbrt/cpu/aggregates.cpp`, `BVHAggregate::buildRecursive`
  (Apache-2.0). It builds the two children of large nodes in parallel and
  bins large nodes with a parallel reduction.
- Difference from pbrt-v4: pbrt-v4 places leaf primitives with an atomic
  offset, so primitive order depends on thread timing. pkg298 needs a tree that
  is node-for-node identical to the old serial build, so:
  - a leaf's primitives are `info[start, end)`. In the serial build, depth-first
    leaf order already equalled range order, so the offset was always `start`;
  - large-node reductions run over 64 fixed chunks, merged in chunk order. AABB
    merge is min/max and bucket counts are integers, so the result is exact;
  - OpenMP 2.0 only: MSVC `/openmp` has no tasks. The top levels are split on
    the calling thread. Ranges of ≤ 16384 primitives become jobs for one
    `parallel for schedule(dynamic)`. Build nodes live in per-job arenas.
- Split logic (`splitNode`) is shared by the serial and parallel paths, so the
  SAH and bucket decisions cannot drift apart.

## BVH cache

- Pattern: the #801 device-scene cache (`cuda_wavefront_invalidate_scene`) and
  Cycles' `Geometry::need_update_rebuild` / BVH refit-or-rebuild split
  (`intern/cycles/scene/geometry.cpp`, Apache-2.0).
- The CPU BVH depends only on `Renderer::scene`. The dirty flag is set by
  `addObject`, `clear` and `getSceneMutable()`. `getSceneMutable()` is the only
  mutable access, so a new in-place geometry edit cannot bypass the flag.
- Material rebinds read the scene through `getScene()` and keep the BVH.
  Dedicated lights, instances (the pkg114 TLAS is built on upload) and the
  camera are not part of the BVH.

## Path-pool floor

- Cycles `CUDADeviceQueue::num_concurrent_states` (`intern/cycles/device/cuda/queue.cpp`,
  Apache-2.0): `max(SMs * maxThreadsPerSM, 65536) * 16` states, independent of
  resolution. This gives 1.72 M on the RTX 5070 Ti (70 SMs × 1536).
- Astroray clamps the pool to the render's total work, so a 1-spp viewport
  chunk keeps `width*height` slots. The wavefront regen maps a work index to
  `(pixel = w % numPixels, sample = w / numPixels)`, so pool size never changes
  which samples run. Only the float atomic accumulation order changes.

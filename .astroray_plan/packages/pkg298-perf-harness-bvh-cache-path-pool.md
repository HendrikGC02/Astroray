# pkg298 — Perf baseline vs Cycles, BVH rebuild cache, path-pool floor

**Pillar:** 3
**Track:** A
**Status:** done — PR #984, 2026-09-29: CPU heavy repeat render 1.03 s -> 0.017 s, first BVH build 1.0 s -> 0.26 s, parallel BVH identical to serial; GPU repeat render 0.71 s (gate 0.3 s) and GPU 1e-6 image match not met, device-scene cache follow-up #981
**Estimated effort:** 3 sessions (~9 h): Phase 0 1, Phase 1 1, Phase 2 1
**Depends on:** pkg55, pkg114

---

## Goal

Before this package:
- Astroray has no repeatable speed comparison against Cycles.
- Every `render()` call rebuilds the full CPU BVH on one thread. That costs 1.7 s on
  CPU and 2.6 s on GPU per call at 2 M triangles.
- The GPU path pool is `width*height`, so low resolutions under-fill the GPU.

After this package:
- `benchmarks/wavefront_baseline.py` measures a simple and a 2 M-triangle Cornell on
  Astroray GPU and on Cycles OptiX, using identical geometry.
- Repeat renders of unchanged geometry skip the BVH build.
- The first build is multi-threaded.
- The path pool has a floor that is independent of resolution.

---

## Context

This is Phase P0 of `.astroray_plan/docs/research-performance-2026-09-29.md`, and
highest-scoring item #1 there. The research harness showed Astroray is 3.4× slower
than Cycles OptiX on a 12-triangle Cornell and 6.6× slower on 2 M triangles. Every
later speed package (pkg299, pkg300) gates on the instrument this package creates.

The BVH tax hits every viewport geometry edit, every animation frame and every
repeated F12. The work is perf-only and correctness-frozen: images must not change.

---

## Evidence

- 2026-09-29, RTX 5070 Ti, 1024², 256 spp, depth 8, same `.npy` geometry:

  | Scene | Astroray | Cycles OptiX | Cycles CUDA |
  |---|---|---|---|
  | Simple | 16.5 s | 4.9 s | 4.9 s |
  | 2 M tris | 35.1 s | 5.3 s | 12.8 s |

- 2026-09-29: fixed per-call cost at 16², 1 spp on the 2 M-triangle scene. CPU
  1.71 / 1.71 / 1.90 s; GPU 2.85 / 2.61 / 2.58 s. Repeats do not get cheaper.
- 2026-09-29: `module/blender_module.cpp:2390` calls `renderer.buildAcceleration()`
  whenever `!skipUpload`. `include/raytracer.h:4618` constructs a new `BVHAccel`
  every time.
- 2026-09-29: Cornell 256² gives 13.4 Msamples/s against 16.3 Msamples/s at 1024².
  The pool is `width*height` (`src/gpu/wavefront/gpu_wavefront_snapshot.cu:1179`).

---

## Reference

- Design doc: `.astroray_plan/docs/research-performance-2026-09-29.md §1, §4 P0`
- Cycles state sizing: `intern/cycles/integrator/path_trace_work_gpu.cpp`
  (`num_concurrent_states` by device capability; Apache-2.0).
- Parallel binned SAH: Wald, "On fast Construction of SAH-based Bounding Volume
  Hierarchies", RT 2007. Reference implementation: pbrt-v4 `src/pbrt/cpu/aggregates.cpp`
  `BVHAggregate::buildRecursive` (parallel subtree build, Apache-2.0).
- Memory: `gpu-perf-ab-clock-drift` (burn-in + min-of-N),
  `wavefront-reuploads-scene-every-render-call` (#801, the analogous upload cache).

---

## Prerequisites

- [ ] Main builds, and the RTX `pytest -m gpu` sweep is green on the base SHA.
- [ ] Blender 5.2 is installed locally, for the Cycles leg.
- [ ] Read `.astroray_plan/docs/lane-rules.md`. The lead runs CUDA builds.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/wavefront/cycles_leg.py` | Blender-side script: builds a mesh from the shared `.npy`, renders Cycles OptiX/CUDA, prints JSON timings |
| `tests/test_pkg298_bvh_cache.py` | CPU-only: repeat `render()` skips the rebuild; any geometry or light mutation still rebuilds; images are bit-identical |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/wavefront_baseline.py` | Add the `simple_cornell` / `heavy_cornell` procedural scenes (shared `.npy`), `--cycles` leg, wall-clock + per-kernel records, burn-in + min-of-N |
| `include/raytracer.h` | `bvhDirty_` flag: `buildAcceleration()` reuses the existing BVH when clean. `setSampler` still runs when lights change. Parallel binned-SAH top levels |
| `module/blender_module.cpp` | Set `bvhDirty_` at every site that calls `invalidateWavefrontScene()` or mutates `scene` |
| `src/gpu/wavefront/gpu_wavefront_snapshot.cu` | `total_paths = max(width*height, kMinPaths)`. `kMinPaths` is derived from the SM count (Cycles-style), and the queue capacity follows it |
| `scripts/README.md` | Register the Cycles leg under the existing baseline-harness row |

### Key design decisions

#### Phase 0: instrument

- Extend the canonical harness (CLAUDE.md §5b); do not fork it.
- Geometry: the generator in the research doc appendix, written deterministically to
  `.npy`, so both engines read identical triangles.
- Record, per engine, the first-call and warm wall time.
- For Astroray, also record `buildAcceleration` time, flatten/upload time and summed
  kernel time, using timers behind `ASTRORAY_PROFILE`.
- This phase confirms or refutes the BVH attribution before Phase 1 changes code.

#### Phase 1: BVH cache

- The dirty flag mirrors the #801 upload-cache invalidation sites.
- A missed site is a correctness bug: the scene would render stale geometry. So the
  test enumerates every mutating binding (`add_*`, `clear`, transform, and instance
  edits) and asserts a rebuild after each.
- `lights.setSampler(...)` stays unconditional. It is cheap and has its own
  correctness history (the empty light-tree bug).

#### Phase 2: parallel build and pool floor

- Parallel build: an OpenMP task per subtree, below a primitive-count threshold. The
  split decisions must be identical to the serial build: same SAH, same buckets,
  deterministic partition. The acceptance check is a node-for-node identical tree.
- Pool floor: larger pools change nothing about sampling (regen is work-indexed), but
  the pool-dependent memory must fit. Log the allocation.

---

## Acceptance criteria

- [ ] The harness prints Astroray and Cycles OptiX times for both scenes in one
      command, and the JSON is committed under `benchmarks/wavefront/`.
- [ ] Heavy scene, second `render()` at 16², 1 spp: **≤ 0.15 s on CPU and ≤ 0.3 s on
      GPU**, down from 1.7 / 2.6 s.
- [ ] Heavy first-call BVH build: **≤ 0.5 s** with OMP 8, down from ~1.7 s.
- [ ] The parallel-built BVH is node-for-node identical to the serial build (test).
- [ ] Heavy 1024², 256 spp GPU: **≤ 32 s** (from 35.1 s), min-of-3 after burn-in.
- [ ] Simple Cornell at 256² reaches ≥ 95 % of its 1024² Msamples/s.
- [ ] Fixed-seed images are bit-identical before and after, on CPU and GPU.
- [ ] Full RTX `pytest -m gpu` sweep and CPU suite are green.

---

## Non-goals

- Do not change BVH quality (no SBVH, no wide nodes). That is pkg299's territory.
- Do not touch any shade, intersect or shadow kernel code.
- Do not add a GPU BVH builder.

---

## Progress

- [x] Phase 0: harness, Cycles leg, attribution timers
- [x] Phase 1: BVH dirty-flag cache + mutation-site test
- [x] Phase 2: parallel build + path-pool floor

---

## Lessons

*(Fill in after the package is done.)*

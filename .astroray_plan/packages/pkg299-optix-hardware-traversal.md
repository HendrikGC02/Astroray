# pkg299 — OptiX hardware traversal for the wavefront intersect and shadow stages

**Pillar:** 3
**Track:** A
**Status:** in-progress — Phases 0-1 done (PR #1008, 2026-10-01: OptiX 9.1 default on for triangle-only scenes, heavy 2M-tri Cornell 23.05 s -> 13.74 s, 1.68x; watertight triangles PR #1010 cut software-vs-OptiX disagreements 217 -> 1); Phase 2 (spheres, curves, motion) and #1001 follow-ups open; #1001 item 2 (instance transform edits rebuild only the IAS, every GAS kept) implemented on branch batch-h1/issue1001-ias, pending hardware gates
**Estimated effort:** 6 sessions (~18 h): Phase 0 1, Phase 1 2, Phase 2 2, Phase 3 1
**Depends on:** pkg298, pkg114, pkg225, pkg88

---

## Goal

Before this package, GPU rays traverse a host-built binary SAH BVH in software
(`gpu_bvh_hit` and `gpu_bvh_occluded` in `include/astroray/gpu_bvh.h`). The traversal
kernels use 148 to 223 registers, and the RTX RT cores sit idle.

After this package, on RTX devices:

- the wavefront's closest-hit and shadow stages call OptiX 9.1 `optixTrace` against a
  device-built GAS/IAS, and write the **existing** hit buffers;
- shading, queues and path state are unchanged;
- the software BVH path remains as the fallback, and serves as the A/B reference.

---

## Context

This is the research doc's item #2 and roadmap phase P1. On the 2 M-triangle Cornell,
intersect plus shadow take 60 % of GPU kernel time. The same machine measured Cycles
OptiX at 2.4× faster than Cycles CUDA on that scene.

This follows the pbrt-v4 pattern: OptiX for traversal only, CUDA wavefront kernels
for everything else. It keeps the register-saturated shade kernel untouched.

Building the GAS on the device also removes the CPU BVH build from the GPU render path.
The OptiX SDK dependency already exists, optionally, for the denoiser (pkg70).

---

## Evidence

- 2026-09-29, profile at 512², 64 spp, 2 M tris: intersect 44 %, shadow 16 %,
  shade 35 %, regen 5.5 %.
- 2026-09-29, 1024², 256 spp, 2 M tris: Astroray 35.1 s, Cycles OptiX 5.3 s,
  Cycles CUDA 12.8 s. On the 12-triangle scene both Cycles backends take 4.9 s.
- 2026-09-29: the OptiX SDK 9.1.0 is installed at
  `C:\ProgramData\NVIDIA Corporation\OptiX SDK 9.1.0`, driver 616.56.
  `cmake/FindOptiX.cmake` messages mention 8.x.
- 2026-09-29: `cuobjdump` reports `stageIntersectQueuedKernel` variants at 148 to
  223 registers and 600 to 1960 B of stack.

---

## Reference

- Design doc: `.astroray_plan/docs/research-performance-2026-09-29.md §3 item 2, §4 P1`
- pbrt-v4 `src/pbrt/gpu/aggregate.cpp`, `optix.cu` (Apache-2.0). This is the canonical
  "OptiX traversal inside a CUDA wavefront" design: raygen reads the ray queue,
  closest-hit writes the intersection queue, and any-hit/miss handle shadow rays.
- Cycles `intern/cycles/device/optix/device_impl.cpp`, `kernel/device/optix/kernel.cu`
  (Apache-2.0): IAS over GAS, custom primitives, curves, motion.
- NVIDIA OptiX 9.1 Programming Guide:
  - `optixAccelBuild`;
  - `OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT` for shadows;
  - `OptixBuiltinISOptions` (curves, spheres, LSS on Blackwell).
- `.astroray_plan/docs/two-level-bvh-research.md` (pkg114 IAS mapping).
- Invoke `cite-algorithm` for the watertight-vs-Möller-Trumbore edge semantics note.

---

## Prerequisites

- [ ] pkg298 harness landed. All gates below use it.
- [ ] `FindOptiX.cmake` accepts 9.x. The lead confirms the SDK path in the build env.
- [ ] Read `lane-rules.md`. The lead runs CUDA builds; no concurrent nvcc.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `src/gpu/optix/optix_accel.cu` | GAS per mesh (triangles), IAS over instances with pkg114 transforms, refit on transform-only edits, compaction |
| `src/gpu/optix/optix_trace_programs.cu` | Raygen (reads the wavefront queue), closest-hit/any-hit/miss programs; compiled to OptiX-IR as its own TU |
| `src/gpu/optix/optix_pipeline.cpp` | Module/pipeline/SBT creation, context sharing with the denoiser, disk cache |
| `tests/test_pkg299_optix_traversal.py` | Hit-buffer A/B vs the software BVH on fixed rays; MC-band equivalence on corpus v2; fallback path when OptiX is unavailable |

### Files to modify

| File | What changes |
|---|---|
| `cmake/FindOptiX.cmake` | Accept the 9.x SDK; drop the 8.x-only messages |
| `CMakeLists.txt` | OptiX-IR/PTX compile step for `src/gpu/optix/*.cu` (separate TU, not `-rdc` linked into `stage_advance.cu`) |
| `src/gpu/wavefront/gpu_wavefront_snapshot.cu` | Select the OptiX or software intersect/shadow stage per device; build or refit the accel instead of the host BVH flatten when OptiX is active |
| `module/blender_module.cpp` | GPU path skips `buildAcceleration()` when OptiX builds the accel (the CPU oracle still builds its own) |
| `include/astroray/gpu_wavefront_state.h` | No layout change. The hit buffers are the contract; document it |

### Key design decisions

#### Phase 0: triangles, closest hit only

- Scope: triangle GAS plus the flat IAS, replacing only `stageIntersectQueuedKernel`.
- The raygen reads `queue[i]` and the SoA ray. The closest-hit writes the same
  hit-buffer fields as `gpu_bvh_hit`: t, prim id, barycentrics, instance id.
- Shading-point reconstruction stays in the existing CUDA code, so shade sees no
  difference.
- Gate: fixed-ray A/B vs software hits agrees on ≥ 99.99 % of rays. The residual must
  be explained by edge watertightness.

#### Phase 1: shadow rays

- `stageShadowKernel` and `stageEnvShadowKernel` move to `optixTrace` with
  `TERMINATE_ON_FIRST_HIT | DISABLE_CLOSESTHIT`.
- The shadow ray's `tmax` follows the current semantics exactly (memory
  `occlusion-sentinel-as-distance-class-of-bug`).
- Segment-NEE shadow (#925/#929) goes the same way.

#### Phase 2: non-triangle primitives

- Analytic spheres: the OptiX built-in sphere, or a custom IS reusing `gpu_sphere_hit`.
- Curves (pkg225): the OptiX built-in curves (cubic B-spline / linear). Use LSS on
  Blackwell only where the curve basis matches; otherwise use a custom IS that calls
  `gpu_curve_intersect`.
- Motion blur (pkg88): OptiX motion GAS/IAS, or a custom-IS fallback for
  deformation.
- **Fork (owner):** full coverage before default-on, or default-on for
  triangle-only scenes after Phase 1. The latter matches Cycles' own staging.

#### Phase 3: default on

- OptiX becomes the default when the device has RT cores and the accel builds. The
  software path stays behind `ASTRORAY_GPU_TRAVERSAL=software` for A/B, and for
  non-RTX devices.

#### Invariants

- Traversal is wavelength-independent, so spectral paths are unaffected.
- The CPU oracle is untouched. CPU/GPU parity is gated by the existing pkg284 bands.
- No new live state is added to shade.

---

## Acceptance criteria

- [ ] Heavy Cornell (pkg298 harness) 1024², 256 spp: **≤ 16 s** (from 35.1 s,
      ≥ 2.2×), min-of-3 after burn-in.
- [ ] Simple Cornell within ±5 % of the pre-change time.
- [ ] Heavy scene, GPU first-call time-to-first-sample drops by ≥ 1.5 s, because the
      CPU BVH build is off the GPU path.
- [ ] Fixed-ray A/B hit agreement ≥ 99.99 %, with mismatches listed and explained.
- [ ] pkg284 corpus-v2 5-seed bands green on GPU with OptiX on, and on software
      fallback.
- [ ] `ASTRORAY_GPU_TRAVERSAL=software` reproduces pre-change images bit-identically.
- [ ] Full RTX `pytest -m gpu` sweep and CPU suite green. Before/after renders of the
      showcase scenes are inspected visually by the lead.

---

## Non-goals

- Do not move shading into OptiX closest-hit programs (no megakernel; SER is a
  separate bet).
- Do not change the CPU BVH or CPU traversal.
- Do not add opacity micromaps, alpha in traversal, or cluster accels. Those are
  follow-ups after default-on.

---

## Progress

- [x] Phase 0: triangle GAS + closest-hit stage, fixed-ray A/B
- [x] Phase 1: shadow and env-shadow stages (segment-NEE shadows too; transparent-shadow walk stays software, #1001)
- [ ] Phase 2: spheres, curves, motion
- [ ] Phase 3: default on + fallback switch — default on for triangle-only scenes and `ASTRORAY_GPU_TRAVERSAL=software` landed with Phase 1 (owner 2026-09-29); TTFS (CPU BVH off the GPU path) and IAS refit open in #1001

---

## Lessons

- Phase 0/1 (2026-09-30): the fixed-ray A/B on the 2M-triangle Cornell found a software bug, not an OptiX one. Möller–Trumbore's absolute `|det| < 1e-6` drops small or grazing triangles (217/1M closest-hit rays, 0.6 % of shadow rays leak), filed as #1000. The mesh Cornell agrees 100 %.
- OptiX's accel build/free churn exposed an uninitialised pkg269 queue counter (`d_gridCount`): the first bounded-media render faulted. Allocation patterns change when a new GPU allocator user arrives, so run the full `-m gpu` sweep, not only the package tests.

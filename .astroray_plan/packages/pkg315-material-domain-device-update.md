# pkg315 — Material-domain device update: a material edit skips the geometry re-flatten (#1067)

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 1 session (~3 h) + one lead CUDA build and one gate (a) re-measure
**Depends on:** pkg291, pkg278

---

## Goal

Before: every viewport material edit calls `invalidateWavefrontScene()`, so the next GPU render runs a full
`buildSceneArrays` (host flatten ~32 ms at 100k triangles), re-uploads every buffer and rebuilds the OptiX accel.
`rebind_material` also scans all primitives with `dynamic_cast` (~6 ms). The 100k material cell is the slowest
gate (a) cell (p95 101.4 ms in the pkg291 table, pooled gate p95 102.1 ms on 2026-10-05).
After: a material-only edit invalidates only the material domain. The render rebuilds and uploads the material
arrays and keeps nodes, primitives, triangles, BLAS/IAS and the OptiX accel. Engine-side 100k material edit
(rebind + next render) < 10 ms.

---

## Context

Gate (a) row of the Stage 0 exit gate, and viewport responsiveness (co-equal product goal). #1068 removed the dead
legacy upload (−33 ms engine-side); the remaining cost is the host flatten, which hashing buffers cannot remove.
Cycles splits the same way: `ShaderManager::device_update` runs without `GeometryManager::device_update` when only
shaders changed. Host-only change: no kernel edits.

---

## Evidence

- 2026-10-05 (#1067, RTX 5070 Ti, `ASTRORAY_PROFILE`): 100k material edit: `rebind_material` ~6 ms; next render
  ~40 ms vs 3.6 ms on a cached scene; flatten ~32 ms, sceneUpload ~4 ms, OptiX accel rebuild ~2 ms.
- 2026-10-03 (`viewport-gate-a-table-2026-10.md`): 100k material worker ON p95 101.4 ms, worker OFF 137.2 ms.

---

## Reference

- Issue #1067 (proposal and guard list).
- Cycles `intern/cycles/scene/scene.cpp` `Scene::device_update` ordering and `ShaderManager::need_update` vs
  `GeometryManager::need_update` (Apache-2.0): the split being mirrored.
- `.astroray_plan/docs/viewport-gate-a-table-2026-10.md` (gate (a) method and cells).

---

## Prerequisites

- [ ] #1068 is on main (dead legacy upload removed).
- [ ] The lead's post-#1068 gate (a) re-measure is recorded (per-cell p95), so the gain is attributable.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg315_material_domain_update.py` | Byte-identity of material-domain vs full re-flatten renders (GPU) + guard fallbacks + timing probe |

### Files to modify

| File | What changes |
|---|---|
| `src/gpu/wavefront/gpu_wavefront_snapshot.cu` | `cuda_wavefront_invalidate_materials()`; the cached-scene path rebuilds/uploads only material-domain arrays when only that flag is set |
| `src/gpu/wavefront/gpu_wavefront_snapshot.h` | Declare the new invalidation entry point |
| `src/gpu/scene_upload.cu` | Factor the material-domain array build out of `buildSceneArrays` so both paths share one producer |
| `include/astroray/gpu_scene_upload.h` | Declaration of the factored material-domain builder |
| `module/blender_module.cpp` | Material-only edits (`rebind_material`, material uploaders) call the material invalidation; geometry-affecting edits keep the full one; material→holders index replaces the per-edit primitive scan |

### Key design decisions

- **Material domain** = GMaterial, textures/texels/matTexId, normal/bump bindings, programs/scalar/progInput/procs,
  closure-graph arrays, lightPathSwitch, the `has*` flags and the spectral profile table. Everything else is geometry.
- **Guards (fall back to the full re-flatten):** material slot ordering changes; per-triangle material-dependent
  data changes (UV upload gate `hasUV`, emission flat prims, `triGenerated` / `triObjectLocal`); emissive status
  changes (light list); hair or volume routing changes. A guard that cannot be evaluated cheaply falls back.
- One producer: the full path and the material path call the same factored builder, so they cannot diverge.
- No kernel change; shade/intersect REG and STACK must be unchanged (cuobjdump by the lead).

---

## Acceptance criteria

- [ ] GPU render after each of {colour, texture swap, program-bearing material, normal map} edit is byte-identical
      between the material-domain path and a forced full re-flatten (same seed).
- [ ] Each guard case (slot reorder, emissive toggle, UV-gate flip, hair material) takes the full path (test asserts
      the path taken via a debug counter, not timing).
- [ ] Engine-side 100k material edit (rebind + next render) < 10 ms, min of 5, RTX 5070 Ti.
- [ ] Gate (a) re-measured in Blender (`blender_driver.py --mode gate_a`): pooled p95 ≤ 100 ms; per-cell table recorded.
- [ ] Full CPU + GPU suites green; cuobjdump REG/STACK unchanged for all kernels.

---

## Non-goals

- Do not hash geometry buffers or add partial geometry uploads (the flatten dominates; #1067).
- Do not change the gate (a) instrument or thresholds.
- Do not touch transform edits (pkg291 / #1001 item 2).

---

## Progress

- [ ] Material-domain builder factored; full path byte-identical to main.
- [ ] Material invalidation + guards wired.
- [ ] Timing probe + byte-identity tests.
- [ ] Lead: build, GPU suite, gate (a) re-measure.

---

## Lessons

*(Fill in after the package is done.)*

# pkg291 — Viewport gate (a) closeout: worker-flip crash, in-place transforms, real-navigation table (#879, #875, #855, #721)

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~6 h): 1 crash + transforms (addon/engine), 1 measurement table on the isolated GUI
**Depends on:** pkg266, pkg241

---

## Goal

Before: flipping `ASTRORAY_VIEWPORT_WORKER` live and toggling Rendered shading
crashes Blender in `nvcuda64.dll` on the 100k scene (#879) — the exact step 3 of
the owner try-out (#858); object moves still full-sync (~130 ms, #875); the
storm row has no post-#849 number (#855); #721 is still open because gate (a)
has never been measured as "event → first CORRECT presented frame p95/p99,
cancel ack, stale-frame exclusion, both pinned scenes × camera/material/
transform edits, real Blender session". After: the flip cannot crash (worker
start/stop owns a single CUDA context lifecycle), object moves update in
place via a per-object triangle range + delta transform + BVH refit, and the
gate (a) table is measured worker ON and OFF on `v2_viewport.blend` with the
owner try-out unblocked.

---

## Context

Gate (a) is the only exit-gate row that is RED for a product reason the
owner feels daily (viewport). #858's default flip is the owner's call; this
package removes the crash that would make the try-out unfair and produces the
numbers the decision needs. Viewport performance is a co-equal product goal
(CLAUDE.md §5c).

---

## Evidence

- 2026-09-24 (#879): crash reproduces on main 0dd98e18, isolated Blender 5.2, GPU, 100k scene; workaround = set the env var before launch.
- 2026-09-24 (#855): full re-sync per material edit 125–132 ms (metal_sweep, 100k); #849 landed in-place material/light re-sync (#882).
- 2026-09-13 (pkg266 §9): settle tick-gap p95 13.5/15.0 ms, present-rate 1.0, cancel p99 47/71 ms PASS; storm 159/175 ms; default reverted to opt-in 2026-09-14.
- 2026-09-07 (#721): camera events ~155 ms each; refinement 1.3 Hz (pre-pkg241).

---

## Reference

- `blender_addon/exporter.py` (`_ViewportSpikeWorker`, `view_update`/`view_draw`, `update_object_transform`), `module/blender_module.cpp` (render cancellation, GIL release).
- CUDA Runtime API: primary context per device is process-wide; a context used from a second thread must not be destroyed by the first (`cudaDeviceReset` from any thread invalidates it). The worker thread must not call `cudaDeviceReset`/module unload while the main thread has a stream in flight; use `cudaStreamSynchronize` + a stop-acknowledged handshake.
- Blender `RenderEngine.view_draw` threading contract (Blender manual `render/render_engine`): draw runs on the main thread; engine-side threads must be joined in `__del__`/`view_update` teardown.
- `.astroray_plan/docs/stage-plan-2026-09-22.md` §gate (a) row; pkg266 §9 driver; `benchmarks/viewport_parity/blender_driver.py`.
- Memory: `viewport-gate-table-misses-real-navigation`, `viewport-edit-verification-needs-pre-edit-frame`, `blender-52-mcp-bridge` (isolated 9877 instance).

---

## Prerequisites

- [ ] pkg284 `v2_viewport.blend` exists (or use `metal_sweep.blend` + the procedural 100k grid as today).
- [ ] Isolated Blender 5.2 on 9877 with a staged addon; the owner's live Blender untouched.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg291_worker_lifecycle.py` | bpy-free: start worker → stop → start on the same engine instance; stop while a render is in flight; teardown with a queued present. Asserts one CUDA context, no `cudaErrorInvalidValue`/illegal address in the engine log, no leaked thread. |
| `tests/test_pkg291_transform_inplace.py` | Move a mesh object: engine `update_object_transform` on a triangle range gives byte-identical vertices/normals/Generated coords to a full re-export; BVH refit bounds enclose the moved range; wall time < 10 ms for 100k tris. |
| `.astroray_plan/docs/viewport-gate-a-table-2026-10.md` | The measured table (event type × scene × worker ON/OFF: p50/p95/p99 event→first correct frame, cancel ack, stale-frame count) plus the #721 close decision. |

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/exporter.py` | Worker start/stop: single owner of the render thread; live env-var flip re-read only at `view_update` when no render is in flight; stop = cancel → join → release before the synchronous path resumes; `update_object_transform` per-object range + delta transform. |
| `module/blender_module.cpp` | `update_object_transform(object_id, matrix)` binding for a triangle range (positions, normals, Generated/Object coords) + `refit_bvh(range)`; device-side twin uploads the range only. |
| `include/raytracer.h` | `Renderer::refitObject(range, delta)`; BVH refit for a node subtree (no rebuild). |
| `src/gpu/scene_upload.cu` | Partial vertex/normal upload for the range; TLAS/BLAS refit where instanced (pkg114). |
| `benchmarks/viewport_parity/blender_driver.py` | Add `--ui-pattern navigate` (real region-view orbit via `view3d.rotate`/`view3d.move` operators) and a `transform` pattern; stale-frame exclusion per pkg266 §9. |

### Key design decisions

- **Crash first, transforms second, table last.** The table is invalid if step 3 of #858 crashes.
- **One CUDA context, one owner.** The worker never resets the device; the synchronous path never tears down while the worker exists. If the root cause is instead a stream used from two threads, serialise on the engine's stream handle (document which after the debugger session).
- **Transforms:** meshes keep world-space vertices (today's layout); delta = M_new · M_old⁻¹ applied to the object's range; normals by the inverse-transpose; BVH refit only (rebuild on non-rigid/scale changes over 10 %).
- **The table is measured, not modelled**: real Blender session, both scenes, worker ON and OFF, five repetitions; numbers go into the doc verbatim.
- **Default flip is not made here** (owner, #858); the doc ends with the recommendation and the try-out checklist re-pointed at this build.

---

## Acceptance criteria

- [ ] #879 reproduction (isolated GUI, 100k, flip + shading toggle ×10) no longer crashes; lifecycle test green.
- [ ] Object move on 100k: in-place path < 20 ms p95 event→present (was ~130 ms full sync); transform test green.
- [ ] Gate (a) table doc complete with p95/p99 per row; #721 closed or re-scoped on the table with numbers.
- [ ] Full suite + GPU sweep green; addon packaged file list unchanged or updated (memory `addon-packaging-file-list`).

---

## Non-goals

- No default flip (#858 owner).
- No orbit-noise work (#856), no worker changes beyond lifecycle.
- No instanced-mesh transforms beyond what pkg114's TLAS refit already provides.

---

## Progress

- [ ] #879 root cause + lifecycle fix + test.
- [ ] #875 in-place transform + refit + test.
- [ ] Table doc + #721/#855 disposition.

---

## Lessons

*(Fill in after the package is done.)*

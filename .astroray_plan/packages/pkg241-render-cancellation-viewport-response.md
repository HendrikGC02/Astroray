# pkg241 — Cooperative render cancellation and viewport-response contract

**Pillar:** 5
**Track:** A
**Status:** open — Phase 0 recorder + measurements + design delivered (PR #733, 2026-09-07: GPU edit→present p95 426 ms metal_sweep / 165 ms 100k-tri, material ~2× camera, F12 cancel floor 483–1107 ms GPU); Phase 1 awaits owner decision — Terra 2026-09-07 BLOCK as written (present-first blit + interactive-resolution budget before cancellation code)
**Estimated effort:** TBD
**Depends on:** pkg52, pkg81, pkg147, pkg191, pkg192, pkg196, pkg232, pkg236

---

## Goal

Before: `test_break()` results are discarded and `renderer.render(...)` has no
cancellation channel, so the viewport cannot promptly acknowledge a
cancel/restart request and can keep producing stale frames. After: a
cooperative render-cancellation and viewport-response contract — the viewport
acknowledges a cancel/restart request promptly, stops producing stale frames,
and returns to a consistent session state without mixed accumulation or leaked
resources. Camera and material edits must produce the correct new frame
without stale results or mixed accumulation. Ordinary completion must be
unchanged.

---

## Context

This package depends on the landed pkg52/81/191/192/196 viewport machinery and
pkg147 OpenMP/GIL safeguards; coordinate real Blender tests with DONE pkg236's
(#711) isolated-profile contract. DONE pkg232 (#705) owns delegate subprocess
cleanup only. It serves Pillar 5 (Blender/DCC viewport response).

---

## Evidence

Static call-path evidence only — NOT measured latency:

- `blender_addon/__init__.py:1210` — `if self.test_break(): return False`;
  the full render continues at `:1276` regardless of the break result.
- `module/blender_module.cpp:2220-2227` — the `std::function<void(float)>`
  progress callback discards the Python return value; `renderer.render(...)`
  at `:2227` has no cancellation channel.
- `include/raytracer.h:4183` — `if (progress) progress(float(++tilesCompleted)
  / totalTiles);` — progress is a void fire-and-forget after each tile.
- GPU dispatch `module/blender_module.cpp:2171` — no cancellation or progress
  argument.
- `blender_addon/exporter.py:611` — blocking `renderer.render(...)` from
  `render_viewport_frame` (`:541`), reached from `view_draw` (`:724`) and
  `view_update` (`:651`).

None of the above is a measured responsiveness number; Phase 0 must produce
those before renderer or session behavior changes. Bounded measurement-only
extensions to the existing harness are part of Phase 0 after architectural
review; the interactive driver currently needs completion to record real UI
events. Native stage averages alone do not establish event/cancel percentiles.

### Phase 0 measurements (2026-09-07, PR #733)

Recorded through the live GUI Blender 5.2 `mcp` bridge with a finished
`benchmarks/viewport_parity/blender_driver.py --mode interactive` (a
`bpy.app.timers` + `SpaceView3D` POST_PIXEL draw-handler recorder that wraps
`view_update`/`view_draw`/`render_viewport_frame`). Two pinned scenes
(2 220-tri metal_sweep; ~100k-tri procedural `pkg241_grid_100k.blend`), CPU and
GPU (`device_mode`) separately, camera (±1° view_rotation) and material
(Principled Base Color toggle) event classes, GPU 3×50 events/class, CPU
bounded (slow oracle). Full JSON + summary:
`benchmarks/viewport_parity/results/2026-09-07-phase0/`.

Lead's prior baseline (smaller viewport, recorded per handoff): idle progressive
refinement ~1.3 Hz (6 redraws / 4.46 s); orbit ~155 ms blocking/camera event,
~6.4 redraws/s. The in-process `benchmarks/viewport_parity/2026-09-03.json`
bypasses the Blender present path and is NOT a substitute.

**Pinned budgets (GPU, from lead/Terra):** edit→present p95 ≤ 100 ms /
p99 ≤ 150 ms; cancel-ack p95 ≤ 200 ms / p99 ≤ 300 ms. Measured values against
these are in the results JSON and `pkg241-cancellation-design-2026-09-07.md`.
Key structural results (region-size dependent — the recorder logs region px):
engine-entry latency ~1 ms (event routing is not the bottleneck); edit→present
is render-bound; material edits cost ~2× a camera edit (view_update renders an
un-presented chunk, then view_draw renders again before blitting); CPU is
10–15× slower/frame; the cancel full-stop floor equals one `render()` call
because the native progress-callback return value is discarded
(`blender_module.cpp:2220`) and the viewport passes `None` as the callback.

**Measured headline (edit→present, full region resolution, p50/p95/p99 ms):**
metal_sweep GPU camera 396.8/425.6/454.2 (n=150), material 809.1/882.0/957.0
(n=150); big-scene GPU camera 162.1/165.0/169.5 (n=150), material
1350.8/1378.5/1404.8 (n=145). CPU (slow oracle, deadline-capped): metal_sweep
camera 11613/12446/13257 (n=19), material 22370/22672/22803 (n=22); big camera
1743/1757/1758 (n=25), material 14150/14333/14367 (n=24). Cancel full-stop floor
(F12 render wall-time): metal_sweep GPU 1107 ms / CPU 148 511 ms; big GPU 483 ms
/ CPU 16 148 ms. GPU edit→present exceeds the p95 ≤ 100 ms budget because it is
render-bound (engine entry ~1 ms), so meeting that budget needs render-time work
beyond pkg241's cancellation scope (design-doc Open Question 1). The CPU
≥30-event floor was not reachable within a bounded wall budget: the socket-driven
live-GUI bridge adds ~20 s/event of fixed overhead (idle-window timer
throttling), so CPU counts are the capped maxima — GPU (the product gate) carries
the full n=150.


## Reference

Coverage specs: [pkg52](pkg52-persistent-viewport-session.md),
[pkg81](pkg81-viewport-interactivity-parity.md),
[pkg191](pkg191-viewport-gpu-progressive-refinement.md),
[pkg192](pkg192-viewport-navigation-interactivity.md),
[pkg196](pkg196-viewport-reduced-res-navigation.md),
[pkg147](pkg147-addon-cpu-render-hang.md),
[pkg232](pkg232-delegate-timeout-process-tree.md),
[pkg236](pkg236-hermetic-blender-smoke.md).

---

## Prerequisites

- [ ] TBD

---

## Specification

### Files to create

None.

### Files to modify

| File | What changes |
|---|---|
| `blender_addon/__init__.py` | The `test_break()` result at `:1210` must reach the render; the full render currently continues at `:1276` regardless of the break result. |
| `module/blender_module.cpp` | The `std::function<void(float)>` progress callback at `:2220-2227` discards the Python return value; `renderer.render(...)` at `:2227` needs a cancellation channel; GPU dispatch at `:2171` has no cancellation or progress argument. |
| `include/raytracer.h` | `progress` at `:4183` is a void fire-and-forget after each tile. |
| `blender_addon/exporter.py` | Blocking `renderer.render(...)` at `:611` from `render_viewport_frame` (`:541`), reached from `view_draw` (`:724`) and `view_update` (`:651`). |
| `benchmarks/viewport_parity/run.py` | Reuse and extend the existing viewport stage recorder; extend canonical harnesses rather than fork. |

### Key design decisions

Phase 0 (mandatory, before behavior changes): measure, SEPARATELY, matched CPU
and GPU camera/material UI-event latency, render-update/presentation latency,
and cancellation acknowledgement/completion latency; pin exact numeric budgets
plus the workload/settings/measurement protocol. The detailed architect pass
then picks the safe session/GIL/Blender-API/CUDA-ownership design; this spec
does NOT prescribe background threads. Phase 1 implements the approved bounded
cancellation/restart/stale-result contract; Phase 2 verifies its native and
Blender lifecycle behavior. Reuse `benchmarks/viewport_parity/run.py` and the
existing viewport stage recorder; extend canonical harnesses rather than fork.

#### Owner scope decisions

The owner handoff milestone also requires faithful mapped textures. Preserve
landed pkg230b affine image/program behavior across edits and cancellation.
New procedural-coordinate fidelity belongs to OPEN pkg242; direct-image
normal/bump provenance belongs to OPEN pkg245. Resolve those scopes through
their own architecture and PRs instead of hiding texture changes in pkg241 or
the parallel pkg240 CI-throughput package. All implementation gates remain
UNRUN.

---

## Acceptance criteria

All implementation gates UNRUN:

- [x] Phase 0 budgets pinned: p50/p95/p99 on an expensive scene for UI-event,
      render-update, and cancellation acknowledgement/completion, CPU and GPU,
      with the exact workload/settings/protocol recorded. Budgets: GPU
      edit→present p95 ≤ 100 ms / p99 ≤ 150 ms; cancel-ack p95 ≤ 200 ms /
      p99 ≤ 300 ms. Measured 2026-09-07 (see Evidence + results JSON + design
      doc); protocol recorded in `blender_driver.py --mode interactive`.
- [ ] F12 cancel, camera and material changes, scene replacement, shutdown/restart, and
      partial-failure paths behave per the contract.
- [ ] No mixed accumulation across cancel/restart; no leaked
      sessions/threads/resources.
- [ ] Ordinary completion path unchanged (bit-compatible where applicable).
- [ ] Isolated Blender CPU and native GPU visual evidence saved and
      Astra-reviewed.
- [ ] Caller/binding/ABI review for any native signature change; fresh native
      build identity if touched; GPU lock; at most two isolated implementation
      worktrees; independent Claude sign-off.

---

## Non-goals

- No transport-math changes.
- No forced GPU preemption guarantees.
- No silently changing the requested backend.
- Risk: GIL/thread ownership.
- Risk: partial CUDA state at cancellation boundaries.
- Risk: Blender API re-entrancy in `view_update`/`view_draw`.

---

## Progress

- [x] 2026-09-07 — Phase 0 recorder + measurements + cancellation design landed (PR #733); Terra review posted on the PR (BLOCK as written: present-first + interactive-resolution budget first).
- [ ] 2026-09-07 — Phase 1a (owner order steps 1+2) implemented, addon Python only (`blender_addon/exporter.py`); step 3 (bool-returning cancellation callback + completion metadata) deferred to a later PR.
  - **Present-first (step 1):** `view_update` caches its scene-edit chunk and flags it present-pending; the next `view_draw` blits that fresh texture before scheduling the next refinement chunk — removes the material double-render (was: `view_update` render + a second `view_draw` render before first present). Stale-guarded: never present-first after a camera/settings change.
  - **Interactive-resolution budget (step 2):** on the expensive profile (estimated full-res render > `VIEWPORT_INTERACTIVE_BUDGET_MS`=100 ms, measured from the last render's wall time scaled by divisor²), a fresh edit starts coarse at `VIEWPORT_START_RES_DIVISOR`=4 and refines one rung toward full res per settled frame (4→2→1). Extends the pkg196 nav divisor rather than forking a parallel ladder; camera nav keeps its divisor-2 floor and bumps to the budget divisor when expensive. Cheap scenes (below the threshold) render full res immediately — ordinary path unchanged.
  - **Unit coverage:** `tests/test_pkg241_present_first_budget.py` (7 tests: budget engages only above the measured threshold; expensive edit starts coarse; refine 4→2→1; present-first blits without an extra render; no stale present after a camera change). pkg196/pkg191/viewport-session suites green; the pkg52 progressive-preview test updated to the present-first sequence (first still-frame `view_draw` now presents the pending chunk before scheduling the next render — refinement to the sample target unchanged, one extra `view_draw`).
  - **GPU before/after measurement:** PENDING — deferred while the lead-owned CUDA addon-rebuild-install holds the GPU (no GPU contention). Numbers to be appended here + `benchmarks/viewport_parity/results/2026-09-07-phase1/`.

---

## Lessons

- (none yet)

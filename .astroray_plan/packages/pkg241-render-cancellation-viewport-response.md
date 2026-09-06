# pkg241 — Cooperative render cancellation and viewport-response contract

**Pillar:** 5 (Blender/DCC viewport response)
**Track:** A
**Status:** OPEN — Phase 0 recorder + measurements + design delivered
(PR pending, 2026-09-07); Phase 1 code awaits owner/Terra approval of the design
**Estimated effort:** TBD at architect review
**Depends on:** landed pkg52/81/191/192/196 viewport machinery and pkg147
OpenMP/GIL safeguards; coordinate real Blender tests with DONE pkg236's (#711)
isolated-profile contract. DONE pkg232 (#705) owns delegate subprocess cleanup only.

Coverage specs: [pkg52](pkg52-persistent-viewport-session.md),
[pkg81](pkg81-viewport-interactivity-parity.md),
[pkg191](pkg191-viewport-gpu-progressive-refinement.md),
[pkg192](pkg192-viewport-navigation-interactivity.md),
[pkg196](pkg196-viewport-reduced-res-navigation.md),
[pkg147](pkg147-addon-cpu-render-hang.md),
[pkg232](pkg232-delegate-timeout-process-tree.md),
[pkg236](pkg236-hermetic-blender-smoke.md).

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

### Phase 0 measurements (2026-09-07, PR pending)

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

## Goal

A cooperative render-cancellation and viewport-response contract: the viewport
must acknowledge a cancel/restart request promptly, stop producing stale
frames, and return to a consistent session state without mixed accumulation or
leaked resources. Camera and material edits must produce the correct new frame
without stale results or mixed accumulation. Ordinary completion must be unchanged.

## Scoped direction

Phase 0 (mandatory, before behavior changes): measure, SEPARATELY, matched CPU
and GPU camera/material UI-event latency, render-update/presentation latency, and cancellation
acknowledgement/completion latency; pin exact numeric budgets plus the
workload/settings/measurement protocol. The detailed architect pass then picks
the safe session/GIL/Blender-API/CUDA-ownership design; this spec does NOT
prescribe background threads. Phase 1 implements the approved bounded
cancellation/restart/stale-result contract; Phase 2 verifies its native and
Blender lifecycle behavior. Reuse `benchmarks/viewport_parity/run.py` and the
existing viewport stage recorder; extend canonical harnesses rather than fork.

## Acceptance — implementation gates UNRUN (Phase 0 gate met 2026-09-07)

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

## Risks

GIL/thread ownership; partial CUDA state at cancellation boundaries; Blender API
re-entrancy in `view_update`/`view_draw`.

## Non-goals

No transport-math changes; no forced GPU preemption guarantees; no silently
changing the requested backend.

The owner handoff milestone also requires faithful mapped textures. Preserve
landed pkg230b affine image/program behavior across edits and cancellation.
New procedural-coordinate fidelity belongs to OPEN pkg242; direct-image
normal/bump provenance belongs to OPEN pkg245. Resolve those scopes through
their own architecture and PRs instead of hiding texture changes in pkg241 or
the parallel pkg240 CI-throughput package. All implementation gates remain UNRUN.

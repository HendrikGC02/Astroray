# pkg241 — Cooperative render cancellation and viewport-response contract

**Pillar:** 5
**Track:** A
**Status:** in-progress — Phase 1b code delivered (native + addon cooperative cancellation, PR pending 2026-09-08: bool-returning progress callback honoured by the CPU tile loop and the GPU wavefront host loop, `Renderer.last_render_info()` completion metadata, viewport cancel-flag + accumulation reset, effective F12 `test_break` cancel; GIL released around the CPU render so OpenMP-worker callbacks don't deadlock; native+addon tests 5+4 pass on the rebuilt sm_120 .pyd; bridge cancel-ack + Phase 2 UI-latency measurement pending). Phase 1a delivered (PR #739, 2026-09-07: present-first + interactive-resolution budget, addon Python only; matched GPU A/B — material p95 −6× metal_sweep 964→155 ms / big 1495→224 ms, big camera p95 169→64 ms meets ≤100 ms budget, renders_before_present=1 on all 600 events; metal_sweep camera 107.6→30.4 ms p50 after correcting a CAMERA-view recorder artifact — exporter divisor logic was correct, the pkg196 divisor-2 nav floor is unit-locked, and the recorder now forces PERSP for camera runs). Phase 0 recorder + measurements + design landed (PR #733).
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


### Phase 1a matched before/after A/B (2026-09-07)

Same live GUI Blender 5.2 session, GPU (RTX 5070 Ti), 3×50 events/class, 5
warmup discarded, matched viewport region per scene (metal_sweep 2112×829, big
2100×1221 — both legs share region and session state). "before" = `origin/main`
`exporter.py` (hash 84be48c, no interactive-resolution budget); "after" = this
branch (hash 3b175fb). Addon reloaded over the bridge between legs (fresh module
re-import verified by hash). Full JSON + summaries:
`benchmarks/viewport_parity/results/2026-09-07-phase1/` (`*-before-matched*`,
`*-after-matched*`).

**edit→present (ms), p50 / p95 / p99, and interactive-resolution divisor engaged
(start_divisor distribution), and renders-before-present (stale-frame guard):**

| scene | class | before p50/p95/p99 | after p50/p95/p99 | before div | after div | rbp before→after |
|---|---|---|---|---|---|---|
| metal_sweep | camera   | 107.6 / 429.9 / 441.0 | 30.4 / 32.0 / 33.5 †| 1:34,2:116 | 4:150 | 1 → 1 |
| metal_sweep | material | 942.9 / 964.0 / 1005.5 | 153.3 / 154.6 / 156.4 | 1:150 | 4:150 | 2 → 1 |
| big         | camera   | 165.3 / 169.3 / 173.3 | 61.3 / 63.5 / 69.9  | 2:150 | 4:150 | 1 → 1 |
| big         | material | 1388.7 / 1495.3 / 1538.2 (n=141, trunc) | 220.6 / 223.6 / 224.8 | 1:150 | 4:150 | 2 → 1 |

† metal_sweep camera "after" re-measured 2026-09-07 (label `phase1d`,
`benchmarks/viewport_parity/results/2026-09-07-phase1/2026-09-07-phase1d.json`)
after the recorder fix below. The original phase-1a "after" reading for this row
(411.2 / 431.6 / 436.9, start_divisor 1:150) was a **measurement artifact**, not
a code regression — see the corrected note below.

Headline: **material edits improve ~6× at p95** (metal 964→155 ms, big
1495→224 ms) — present-first removes the view_update+view_draw double-render
(`renders_before_present` collapses 2→1 on every material event). **big-scene
camera improves 2.7× at p95 (169→64 ms) and now meets the p95 ≤ 100 ms budget**
via the coarse start divisor (4). **metal_sweep camera improves 3.5× at p50
(107.6→30.4 ms)** — the budget raises the nav divisor to 4 for this full-res-
over-budget scene. `renders_before_present == 1` on all 600 "after" events (both
scenes × both classes × 150) — no stale frame is ever blitted.

**Corrected diagnosis (2026-09-07, label `phase1d`).** The phase-1a "after"
metal_sweep camera reading (411.2 / 431.6 / 436.9 ms, start_divisor stuck at 1)
was **a recorder measurement artifact, not a code regression**. Root cause: the
camera event simulates viewport navigation by nudging `rv3d.view_rotation`, which
only moves the view matrix in free-perspective (PERSP) view. `metal_sweep.blend`
is saved in **CAMERA** view; the driver re-opens the .blend each run
(`wm.open_mainfile`), so the metal_sweep "after" leg ran in CAMERA view where the
nudge is inert. With the view matrix never changing, `_camera_state_hash` never
changes, `camera_changed` is always False, so (a) the nav/budget divisor branch
is never entered (start_divisor stays 1) and (b) `skip_upload` (which requires
`camera_changed`) is never set, so every frame pays a full BVH re-upload (~300 ms)
on top of the ~110 ms render — the 411 ms figure. The PERSP "before" leg and both
big-scene legs (the procedural `pkg241_grid_100k.blend` saves in PERSP) were
unaffected, which is why only this one row looked anomalous. Diagnosis was
confirmed live over the bridge: probing `rv3d.view_perspective` returned
`'CAMERA'`, and instrumented `view_draw` showed `camera_changed == False` on all
events with `res_divisor == 1` and inner `render()` ≈ 110 ms vs whole-frame
≈ 414 ms (the ~300 ms upload delta). **Exporter divisor logic was correct all
along** (`max(VIEWPORT_NAV_RES_DIVISOR, _budget_start_divisor())` — the pkg196
divisor-2 floor that the budget may only raise; unit-locked, see below). **Fix:**
`benchmarks/viewport_parity/blender_recorder.py` now forces `view_perspective =
'PERSP'` for camera-class runs and calls `rv3d.update()` after each nudge so the
view matrix recompute is deterministic. Re-measured (recorder fixed, live GUI
Blender 5.2, GPU, 3×50, 5 warmup, region 2112×829): metal_sweep camera
**30.4 / 32.0 / 33.5 ms**, start_divisor 4:150, rbp 1:150 — no regression, a 3.5×
p50 improvement over the PERSP `before` leg.

**Visual proof (big scene, through the bridge):**
`test_results/2026-09-07-pkg241-p1/big_mid_orbit_reduced.png` (mid-orbit coarse
present, divisor 4, overlay "Viewport 1/1024 spp") and `big_settled_full.png`
(settled, divisor 1, overlay "22/1024 spp"). The spp/divisor progression
confirms the coarse-first present refines up to full res; the framebuffer is
non-stale and non-garbage. (The big scene is a synthetic 100k-tri latency-stress
grid that renders dark, so the pair demonstrates the divisor/spp mechanism rather
than a rich image.)

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

#### Phase 2 — decouple the UI from the viewport render (owner, 2026-09-07 evening)

Owner observation after Phase 1a: with Astroray the Blender UI runs at the
viewport render's frame rate (panels, sliders and menus stall while a chunk
renders), whereas Cycles keeps the UI responsive because its viewport session
renders on its own thread and `view_draw` only blits the latest result.
Phase 1a/1b reduce the per-chunk cost but leave `view_update`/`view_draw`
synchronous in the main thread, so the coupling remains. Phase 2 is the
architecture that removes it: the render runs off the Blender main thread
(native worker thread owning the CUDA context or a CPU render session; the
GIL released for the whole chunk), `view_draw` becomes a non-blocking blit of
the last completed chunk plus a `tag_redraw`, and the Phase 1b cancellation
callback becomes the thread's stop signal. Risks already listed in Non-goals
(GIL/thread ownership, partial CUDA state, `view_update`/`view_draw`
re-entrancy) apply in full; the pkg147 OpenMP/GIL safeguards and the
`mingw_openmp_blender_deadlock` memory are the constraints. The measurable
target is a new recorder metric, UI event latency during an active render
(p95 ≤ 33 ms, i.e. the UI holds 30 fps while a chunk renders), added as
`blender_driver.py --mode ui_latency` (a `bpy.app.timers` ticker at a 5 ms
interval measures its own invocation-gap p50/p95/p99/max plus the fraction of
wall time blocked) in Phase 2's own measurement step before any threading
change. **Measured 2026-09-08** (GPU, isolated Blender profile, OpenMP-off
CUDA build of this branch's HEAD, 3 reps × 10 s post-warmup per config,
metal_sweep + `pkg241_grid_100k.blend`, astroray-gpu vs Cycles/OPTIX):
Astroray tick-gap p95 179.5 ms (metal_sweep) / 274.2 ms (big) — both far over
the 33 ms budget, ~95–97% of wall time blocked; Cycles tick-gap p95 9.6 ms
(metal_sweep) / 8.1 ms (big) — near the 5 ms tick floor, confirming the
decoupled reference the owner described. Full table + protocol: Progress
"Phase 2 measurement" below and
`benchmarks/viewport_parity/results/2026-09-08-phase2/`. Sequence: Phase 1b
(cancel + completion metadata) → **Phase 2 measurement (DONE)** → Phase 2
design review (Opus 4.8 architect + Terra) → implementation.

---

## Acceptance criteria

All implementation gates UNRUN:

- [x] Phase 0 budgets pinned: p50/p95/p99 on an expensive scene for UI-event,
      render-update, and cancellation acknowledgement/completion, CPU and GPU,
      with the exact workload/settings/protocol recorded. Budgets: GPU
      edit→present p95 ≤ 100 ms / p99 ≤ 150 ms; cancel-ack p95 ≤ 200 ms /
      p99 ≤ 300 ms. Measured 2026-09-07 (see Evidence + results JSON + design
      doc); protocol recorded in `blender_driver.py --mode interactive`.
      Phase 1a (2026-09-07) brings **big-scene camera within the p95 ≤ 100 ms
      budget** (matched A/B: 64 ms, was 169 ms) and cuts material p95 ~6×; see
      the Phase 1a matched A/B in Evidence. metal_sweep camera 107.6→30.4 ms p50
      (phase1d re-measure; both scenes' camera p95 ≤ 100 ms budget).
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
- [ ] 2026-09-08 05:15 — Phase 2 design pass done: `pkg241-phase2-offthread-design-2026-09-08.md` (Opus 4.8 architect; A2 = addon-owned worker thread driving the existing binding, GPU path releasing the GIL, `view_draw` blit-only). Codex Terra: **BLOCK as written** — `skip_upload` premise wrong (wavefront re-uploads every render; single-render-thread global `WfContext`), worker must never touch `bpy`/GPUTexture/redraw, needs a process-wide GPU arbiter + generation-tagged non-blocking handoff, acknowledged worker exit before release, wider GIL release, denoise as settled-only. Lead decision (doc §7): revise the doc per Terra 1–6, then a minimal real-Blender A2 spike is the first implementation task; no threading code before that spike passes. Phase 2 measurement itself: PR #750.

- [x] 2026-09-08 — Phase 2 measurement: UI event latency while a viewport
      chunk renders. New `blender_recorder.py _install_ui_latency` +
      `blender_driver.py --mode ui_latency`: a `bpy.app.timers` ticker
      registered at `tick_s`=5 ms records the wall-clock gap between its own
      consecutive invocations while continuously dispatching the next
      camera/material edit + `tag_redraw()` from inside the same callback —
      the main thread is therefore never idle (always either running the
      ticker or blocked inside the redraw/render it just triggered), which
      avoids the Phase 0 idle-window timer-throttling artifact structurally
      rather than via OS input injection. Cross-checked two ways: (1) the
      POST_PIXEL draw-handler present-timestamp stream, recorded throughout,
      confirms the viewport kept refining rather than idling; (2) on
      Astroray, `Exporter.render_viewport_frame` is wrapped the same way
      `_install()` wraps it, giving a `render_time_fraction` (time inside
      render / wall time) that should track `blocked_time_fraction_from_ticks`
      (derived purely from tick gaps, so it applies to Cycles too, which has
      no Python `view_update`/`view_draw` hook to wrap) — confirmed below.
      Protocol: isolated Blender 5.2 profile per pkg236 (GUI, `mcp` bridge,
      port 9877 — never the owner's live profile/port 9876), OpenMP-off CUDA
      addon built from this worktree HEAD (`dist/astroray/astroray.cp313-win_amd64.pyd`,
      md5 `a49dd8739e9adef5198a0ba3acdd1ba8`, built 2026-09-08 03:09, confirmed
      byte-identical to the module the live isolated Blender had loaded at
      measurement time), 3 reps × 10 s measured (post 2 s warmup discard) per
      (scene, engine), region size logged per config.

      | scene | tris | region | engine | gpu | n_ticks | p50 ms | p95 ms | p99 ms | max ms | blocked_frac | render_frac | budget (≤33ms p95) |
      |---|---|---|---|---|---|---|---|---|---|---|---|---|
      | metal_sweep | 2220 | 2112×829 | astroray | astroray-gpu | 275 | 157.82 | 179.48 | 194.42 | 208.31 | 0.9548 | 0.444 | FAIL |
      | metal_sweep | 2220 | 2112×829 | cycles | OPTIX×3 | 4398 | 6.53 | 9.62 | 11.06 | 15.43 | 0.2673 | 0.0 (no hook) | PASS |
      | big (`pkg241_grid_100k.blend`) | 101920 | 2100×1221 | astroray | astroray-gpu | 188 | 232.62 | 274.21 | 283.41 | 284.83 | 0.9693 | 0.7451 | FAIL |
      | big (`pkg241_grid_100k.blend`) | 101920 | 2100×1221 | cycles | OPTIX×3 | 4578 | 6.52 | 8.13 | 9.4 | 11.07 | 0.2372 | 0.0 (no hook) | PASS |

      Reading: Astroray's tick-gap p95 (179–274 ms) is 5–8× the 33 ms budget,
      with 95–97% of wall time main-thread-blocked, and the render-time
      fraction (44–75%) tracks the blocked fraction closely enough (same
      order, same direction across scenes: bigger scene → both fractions
      rise) to confirm the tick gaps are real render blocking, not a
      timer-throttling artifact — this makes the owner's complaint
      quantitative: with Astroray the UI genuinely runs at the render's own
      pace. Cycles holds p95 within ~2× the 5 ms tick interval on both scenes
      (8–10 ms), with `blocked_frac` well under Astroray's and a large,
      steadily growing present count, demonstrating the decoupled reference
      — Cycles' native viewport session renders off the main thread, so
      `view_draw` only blits. Cycles' `render_frac`=0 is expected (no Python
      `render_viewport_frame` hook exists to wrap on that engine), not a
      measurement gap. Full JSON + summary:
      `benchmarks/viewport_parity/results/2026-09-08-phase2/`.
      Not separately re-measured this pass (unchanged from Phase 1a/1b,
      no new evidence needed): CPU legs, and the cancel-ack numbers already
      landed under the Phase 1b entry below.
- [ ] 2026-09-08 — Phase 1b (cooperative cancellation) code implemented; PR pending.
  - **Native callback returns bool.** `Renderer::render`'s progress callback is
    now `std::function<bool(float)>` (`include/raytracer.h`): the OpenMP tile loop
    sets a shared `std::atomic<bool> cancelled` on a `false` return and skips the
    remaining tiles (OpenMP for-loops cannot `break`), returning a partial
    framebuffer with the completed tiles correctly normalised. Null callback =>
    never set => byte-identical to the pre-pkg241 path (verified: two `progress=None`
    renders on a fixed seed are `array_equal`, and an always-True callback matches
    `None` exactly).
  - **GPU host-side cancel hook.** `cuda_wavefront_render` gains a
    `std::function<bool()> cancelRequested = nullptr` (default null = bit-identical),
    polled between wavefront passes on the host; on cancel it breaks the pass/round
    loops and returns the last host-accumulated (partial) frame. No device-side
    preemption. All call sites updated (`module/blender_module.cpp:2184`, prewarm
    `:2773`, module-level `m.def` `:4924` use the default; `apps/main.cpp` and the
    restir variant are unaffected).
  - **Completion metadata.** `Renderer.last_render_info()` returns
    `{cancelled, tiles_completed, total_tiles}` (GPU tiles are 0/0; cancel state
    from the host hook). Smallest binding surface chosen over per-sample counts.
  - **Addon.** `exporter.render_viewport_frame` passes a real
    `not _viewport_cancel_requested` callback (was `None`); `view_draw` requests a
    cancel on a substantive camera / settings change; `_consume_viewport_cancel`
    drops the cancelled chunk's partial accumulation before the next chunk (no mixed
    accumulation, decision key = existing `render_key`). F12 `test_break()` now
    actually stops the render and the partial framebuffer is written to the render
    result like Cycles (`__init__.py`).
  - **GIL fix (deviation from design doc §5).** The design doc assumed the per-tile
    callback runs on the main thread and re-acquires reentrantly. Under OpenMP the
    callback runs on WORKER threads, so holding the GIL through `render()` deadlocks
    (workers block on the GIL the main thread holds at the OpenMP barrier). Fixed by
    releasing the GIL around the CPU render (`py::gil_scoped_release`) — the standard
    pybind11+OpenMP pattern, matching Cycles. The addon .pyd is built OpenMP-OFF so
    there the single main thread runs the callback (reentrant no-op). Reproduced the
    deadlock (faulthandler: 7 worker threads + main stuck in `render()`), then
    verified fixed (callback render completes in 0.12 s).
  - **Tests.** `tests/test_pkg241_cancellation.py` (5: CPU cancel→partial buffer +
    stops within N+thread-slack tiles; `None` byte-identical; non-bool return =
    continue; GPU cancel stops between passes; GPU null hook == always-continue) all
    pass on the rebuilt sm_120 worktree .pyd. `tests/test_pkg241_cancellation_addon.py`
    (4: real callback wired + polarity; request/consume resets accumulation;
    render_viewport_frame consumes a pending cancel; settings change requests cancel)
    pass. pkg196/pkg191/pkg52/present-first viewport suites green (38).
  - **GPU cancel-ack measured (in-process, RTX 5070 Ti, rebuilt sm_120 .pyd, 64 spp,
    depth 6).** Time from cancel-request (first host poll) to `render()` return:
    metal-like (2k tris, 512×512) **p50 3.9 / p95 4.1 / p99 4.1 ms** vs a 176 ms
    full-render floor (~44×); big-like (100k tris, 700×700) **p50 7.5 / p95 8.6 /
    p99 8.7 ms** vs a 491 ms floor (~57×). Both p95/p99 are far under the cancel-ack
    budget (p95 ≤ 200 / p99 ≤ 300 ms) — cancellation returns within one wavefront pass.
    `last_render_info().cancelled == True`, 1 host poll.
  - **Why in-process, not the live bridge:** the Phase-0 bridge cancel probe
    (`blender_cancel_probe.py`) documents that `test_break`/`update_progress` are RNA
    methods that cannot be monkeypatched from Python, so it can only time a *full* F12
    render (the floor) — it cannot inject a mid-render cancel over the socket. And in
    the synchronous model a chunk is atomic on the main thread, so a *viewport*
    per-chunk cancel cannot be triggered mid-chunk by a Blender event (no event loop
    runs during the blocking render). The cancel plumbing therefore lands now for F12
    (which polls OS ESC state during the render → now stops within one tile/pass
    instead of the full-render floor) and as the Phase 2 off-thread stop signal; the
    in-process measurement above is the honest, budget-relevant cancel-ack number.
  - **Still pending (recommend folding into the Phase 2 measurement pass):** the live
    GUI edit→present non-regression re-confirm and the new Phase 2 UI-latency-during-
    render recorder metric (Part B) — both need an OpenMP-OFF worktree addon build +
    the GUI bridge; in the synchronous model UI-latency-during-render ≈ chunk render
    time (far above the 33 ms target), which is exactly the Phase 2 motivation.
- [ ] 2026-09-07 evening — owner: UI still coupled to the viewport render
      frame rate (Cycles decouples them); recorded as Phase 2 under Key
      design decisions and as a comment on issue #721. Next: Phase 1b, then
      the Phase 2 UI-latency measurement.
- [ ] 2026-09-07 08:30 — owner chose Terra's order for Phase 1: present-first blit, then an interactive-resolution budget, then the cancellation callback with completion metadata (all in pkg241); Phase 1a dispatched.
- [x] 2026-09-07 — Phase 0 recorder + measurements + cancellation design landed (PR #733); Terra review posted on the PR (BLOCK as written: present-first + interactive-resolution budget first).
- [ ] 2026-09-07 — Phase 1a (owner order steps 1+2) implemented, addon Python only (`blender_addon/exporter.py`); step 3 (bool-returning cancellation callback + completion metadata) deferred to a later PR.
  - **Present-first (step 1):** `view_update` caches its scene-edit chunk and flags it present-pending; the next `view_draw` blits that fresh texture before scheduling the next refinement chunk — removes the material double-render (was: `view_update` render + a second `view_draw` render before first present). Stale-guarded: never present-first after a camera/settings change.
  - **Interactive-resolution budget (step 2):** on the expensive profile (estimated full-res render > `VIEWPORT_INTERACTIVE_BUDGET_MS`=100 ms, measured from the last render's wall time scaled by divisor²), a fresh edit starts coarse at `VIEWPORT_START_RES_DIVISOR`=4 and refines one rung toward full res per settled frame (4→2→1). Extends the pkg196 nav divisor rather than forking a parallel ladder; camera nav keeps its divisor-2 floor and bumps to the budget divisor when expensive. Cheap scenes (below the threshold) render full res immediately — ordinary path unchanged.
  - **Unit coverage:** `tests/test_pkg241_present_first_budget.py` (10 tests: budget engages only above the measured threshold; expensive edit starts coarse; refine 4→2→1; present-first blits without an extra render; no stale present after a camera change; and the pkg241-p1d camera-nav divisor floor — cheap-scene camera nav renders at the pkg196 divisor-2 floor, the budget raises it to 4 on the expensive profile, and it settles back to full res). pkg196/pkg191/viewport-session suites green; the pkg52 progressive-preview test updated to the present-first sequence (first still-frame `view_draw` now presents the pending chunk before scheduling the next render — refinement to the sample target unchanged, one extra `view_draw`).
  - **GPU before/after measurement:** DONE (matched same-session A/B, see Evidence "Phase 1a matched before/after A/B"). Material p95 −6× (metal_sweep 964→155 ms, big 1495→224 ms); big-scene camera p95 169→64 ms (now ≤ 100 ms budget); `renders_before_present == 1` on all 600 "after" events (double-render removed). metal_sweep camera did not improve (render-bound; coarse divisor did not latch for the cheap scene) — surfaced as a deviation for a lead call on an unconditional pkg196 divisor-2 floor. Results: `benchmarks/viewport_parity/results/2026-09-07-phase1/`; visual pair: `test_results/2026-09-07-pkg241-p1/big_{mid_orbit_reduced,settled_full}.png`.

---

## Lessons

- (none yet)

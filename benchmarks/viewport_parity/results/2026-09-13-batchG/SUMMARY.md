# pkg266 Viewport Phase 2.3 — §9 gate table (Batch G, 2026-09-13)

**Hardware:** RTX 5070 Ti, idle GPU under the MAIN orchestrator lock (no nvcc/
cicc/ptxas/ninja concurrent). **Blender:** isolated 5.2 profile on port 9877
(never the owner's 9876). **Addon:** CUDA OpenMP-OFF, built + installed from this
worktree (`build_blender_addon.py --backend cuda --install`). **Instrument:**
Terra-4 generation-tagged lifeline (adaptive settle). **Reps:** 2 x 10 s
post-warmup per config. **Settled target pinned to 64 spp** (§9) by the
ui_latency recorder.

## Root cause of the Batch B present-rate=0 (two bugs, both fixed)

Batch B (2026-09-12) showed worker-ON tick-gap PASS but present-rate UNGRADEABLE
(completed=0 / presented=0 while the device rendered 285/248 chunks). Root-caused
to TWO independent causes:

1. **Spurious-view_update over-cancel.** `_worker_view_update` called
   `worker.request()` on EVERY invocation, but Blender re-fires `view_update`
   during a settle span (depsgraph re-eval on the worker's own `tag_redraw`) with
   an empty / selection-only `depsgraph.updates`. Each `request()` bumped
   `desired_generation` + set the cancel event, so no render reached its
   uncancelled `render_end` -> no `terminal_publication`. Fix: mirror the
   synchronous path's early-return on a no-domain dispatch via a cache-free
   `_depsgraph_has_image_changing_update` peek. Regression:
   `test_pkg266_present_rate_settle.py` (FAILS pre-fix with completed==0).

2. **Orphaned worker holds the process-global admission token.** The Exporter
   holds `self.engine` (strong) and `_LIVE_VIEWPORT_SESSIONS` holds the Exporter
   (strong), so a superseded RenderEngine is pinned alive -- `engine.__del__` /
   `Exporter.__del__` never fire. The orphan's worker kept rendering and HELD the
   token; the live worker could never acquire it, stayed IDLE, never committed.
   Confirmed in the GUI: two distinct worker instances -- the publish-worker
   (orphan, cancel never set, 300+ chunks) id != the request-worker (live, IDLE,
   37 requests, 0 commits). Fix: `_reap_dead_viewport_sessions()` drains sessions
   whose RenderEngine Blender has freed (`as_pointer()` -> `ReferenceError`),
   releasing the orphan's token; called from `_ensure_worker` + each
   `_worker_view_draw`; skips the current session and any live sibling viewport
   (S3.5 multi-viewport preserved). Plus `CustomRaytracerRenderEngine.__del__`
   drains on a genuine engine free.

A third, measurement-level cause: the scenes ship `preview_samples=1024`, so a
generation needs ~30 s to reach `render_end` -- longer than the adaptive settle
cap, so it never terminalised. S9 pins a fixed settled target (64 spp); the
recorder now sets it across `bpy.data.scenes`. This is the S9 measurement target,
not a relaxation of the terminal predicate (the worker still marks terminal only
at full target).

## Gate table

`present_rate` is UNGRADEABLE under the continuous storm by design (an edit every
tick never lets a generation become the latest-desired at its own `render_end`).

| config | scene | engine | tick p95 (ms) | completed | present_rate | cancel_pump p99 (ms) | frame_age p95 (ms) | mailbox | CUDA err | chunk_spp p50/max | samples/s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **settle** | metal_sweep | astroray ON | **13.52** | 2 | **1.0** | 47.3 | 13.3 | 1 | 0 | 32/64 | 14.8 |
| **settle** | big | astroray ON | **15.02** | 3 | **1.0** | 71.1 | 15.1 | 1 | 0 | 26/64 | 14.8 |
| settle | metal_sweep | astroray OFF | 92.34 | - | - | - | - | - | - | - | - |
| settle | big | astroray OFF | 140.16 | - | - | - | - | - | - | - | - |
| settle | metal_sweep | cycles | 6.66 | - | - | - | - | - | - | - | - |
| settle | big | cycles | 6.61 | - | - | - | - | - | - | - | - |
| storm | metal_sweep | astroray ON | 159.2 | 0 | UNGRADEABLE | 54.9 | 12.7 | 1 | 0 | 8/21 | 1.1 |
| storm | big | astroray ON | 175.37 | 1 | 1.0 | 60.1 | 6.6 | 1 | 0 | 30/64 | 4.6 |
| storm | metal_sweep | astroray OFF | 229.75 | - | - | - | - | - | - | - | - |
| storm | big | astroray OFF | 211.46 | - | - | - | - | - | - | - | - |

### Gate verdict (realistic settle cadence -- both scenes)

| gate | budget | metal_sweep | big | verdict |
|---|---|---|---|---|
| tick-gap p95 | <= 33 ms | 13.52 | 15.02 | **PASS** |
| present-rate gradeable | >= 1 terminal/span | yes | yes | **PASS** |
| present-rate | >= 0.9 x completed | 1.0 | 1.0 | **PASS** |
| cancel p99 (cancel_request->idle_drain) | <= 300 ms | 47.3 | 71.1 | **PASS** |
| frame age | >= 0 | 13.3 | 15.1 | **PASS** |
| mailbox depth | <= 1 | 1 | 1 | **PASS** |
| CUDA errors | 0 | 0 | 0 | **PASS** |

All settle gates PASS on both scenes -- the Batch B present-rate=0 is resolved
(now gradeable, 1.0). Worker ON cuts the realistic settle tick-gap from 92.3 /
140.2 ms (synchronous) to 13.5 / 15.0 ms (Cycles reference 6.6 ms).

### Storm residual (explained)

Continuous-storm tick-gap p95 is 159 / 175 ms (FAIL the 33 ms budget). Cause: the
main-thread commit cost (commit p95 = 153 / 116 ms) -- under an edit every 5 ms
nearly every tick runs a `sync_viewport_scene` commit (~150 ms on these scenes).
This is the coalesced-commit residual the design flags (the coalesced dirty-domain
replay reduces but does not eliminate the full-sync path); it is NOT the render
blocking the UI (render_frac = 0 on the worker rows). The storm is the
pathological stress variant; the realistic settle cadence passes.

## Worker-default decision: stays opt-in

Per the acceptance rule (flip `ASTRORAY_VIEWPORT_WORKER` ON only if every S9 gate
passes on both scenes), the continuous-storm tick-gap p95 (159 / 175 ms) fails the
33 ms budget, so the default stays opt-in. Failing rows = the storm rows above
(main-thread commit ~150 ms/edit). The realistic settle cadence passes all gates
decisively (present-rate gradeable 1.0, tick-gap 13-15 ms). Recommendation: flip
ON in a follow-up once the commit-cost residual is reduced, or accept the storm as
pathological and flip now -- an owner/lead call.

## Artifacts

- JSON + per-config summaries: `workerON-settle-phase0.json`,
  `workerON-storm-phase0.json`, `workerOFF-settle-phase0.json`,
  `workerOFF-storm-phase0.json` (+ `*-summary.md`) in this directory.
- Pre-fix confirmation (installed addon == origin/main, worker ON settle):
  completed=0 / present_rate UNGRADEABLE while n_render_device=12 -- reproduced the
  Batch B symptom in the GUI before the fix.

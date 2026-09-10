# pkg266 — Viewport Phase 2.3: cancellation-bounded GPU dispatch, coalesced dirty-domain commit, global admission token

**Pillar:** 5
**Track:** A
**Status:** in-progress — native bounded dispatch + global admission token + coalesced dirty-domain commit landed on `feat/pkg266-viewport-p23-bounded-dispatch` (2026-09-10); GPU build + Terra-4 GUI re-measure in the same lane (lead flips to done on the gate table)
**Estimated effort:** 3 sessions (~10 h; one native change in the wavefront dispatch under the GPU lock, addon commit restructure, GUI re-measure on port 9877)
**Depends on:** pkg241, pkg131, pkg56

---

## Goal

Before: with the A2 worker (`ASTRORAY_VIEWPORT_WORKER=1`, still opt-in) the
main thread is decoupled from the render (present wiring fixed, realistic-settle
tick-gap p95 25–40 ms), but two gates fail for architectural reasons measured in
P2.2: cancel p99 is 262 ms (metal_sweep) / 485 ms (big) against a 300 ms budget
because the worker finishes its in-flight wavefront pass before reporting idle,
and the continuous edit-storm tick-gap p95 is 70–206 ms because every deferred
edit falls back to a full `sync_viewport_scene` on the main thread. The
admission token is per-worker, not process-global (the P2.2 scene-switch CUDA
corruption was its first symptom; fixed by a `load_pre` drain, §13a). After:
the GPU render is dispatched in cancellation-bounded units (a cancel poll
between bounded wavefront sub-passes, interactive-resolution first pass), the
main-thread commit replays a coalesced dirty-domain mask (materials / lights /
transforms under the token, full sync only for geometry/unknown changes), one
process-global admission token owns every renderer mutation, and the §9 gates
are re-measured with the Terra-4 instrument on an idle GPU: tick-gap p95 ≤ 33 ms
(settle and storm), cancel p99 ≤ 300 ms, present-rate gradeable, frame age ≥ 0.

---

## Context

Owner priority since 2026-09-07: the Blender UI must not run at the render's
frame rate (issue #721, north-star gate (a)). P2.2 proved the A2 model and left
exactly these residuals; Codex Terra (review 4) judged the cancel latency
architectural ("reducing the Python-side chunk does not bound a long wavefront
pass") and the commit cost bounded-fixable. Both lanes that measured P2.2 wrote
the same P2.3 list. Serves Pillar 5.

---

## Evidence

- 2026-09-09 (PR #777, clean pre-fix run, RTX 5070 Ti, idle GPU): worker ON realistic settle tick-gap p95 32.4–39.5 ms (metal_sweep) / 30.9 ms (big); continuous storm 206 / 70 ms; cancel p99 262 / 485 ms; present wiring PASS both scenes; mailbox ≤ 1; 0 CUDA errors.
- 2026-09-09 (PR #777, post-fix Terra-4 instrument): metal_sweep realistic-settle p95 fails both reps; present-rate UNGRADEABLE (0 eligible terminal generations under the ticker); frame age ≥ 0 verified; buffer identity PASS.
- 2026-09-09 (PR #777 §13a): scene switch with the worker ON poisoned the CUDA context 3/3 (per-worker token never serialised across sessions); fixed by `stop_all_viewport_sessions()` on `load_pre` + `atexit`.
- 2026-09-08 (design §3.1, Terra review 1): the wavefront re-uploads scene arrays and rewrites `__constant__` bindings every render; `WfContext` is "single render thread assumed" (`gpu_wavefront_snapshot.cu:988`).

---

## Reference

- Design: `.astroray_plan/docs/pkg241-phase2-offthread-design-2026-09-08.md` §3.2–3.6 (snapshot/commit, token, lifecycle), §9 (gates + instrument), §12 (P2.2 scope), §13 (Terra review 4 + resolutions), §13a (scene-switch root cause).
- Code: `blender_addon/exporter.py` (`_ViewportSpikeWorker`, `_worker_commit_and_submit`, `scene_full` path ~L1679, `stop_all_viewport_sessions`), `src/gpu/wavefront/gpu_wavefront_snapshot.cu` (between-pass host cancel hook from pkg241 Phase 1b, `WfContext`), `benchmarks/viewport_parity/blender_driver.py` / `blender_recorder.py` (Terra-4 instrument), `benchmarks/viewport_parity/results/2026-09-09-phase2-p22/SUMMARY.md`.
- Specs: pkg241 (Phases 0–2.2), pkg131 (adaptive/progressive legs the sub-pass dispatch must respect), pkg56 (incremental viewport sync).
- Memories: `gpu-lock-lanes-overwrite-lock-file`, `cuda_verifier_concurrency`, `wavefront-shade-kernels-register-saturated`.

---

## Prerequisites

- [ ] PR #777 merged (P2.2 + Terra-4 fixes + scene-switch drain).
- [ ] Build passes on main; `.pyd` newer than HEAD; GPU lock held for every RTX number (poll `acquire_lock`, never write the lock file).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg266_bounded_dispatch.py` | In-process: a cancel raised mid-render is acknowledged within one sub-pass (bounded by the sub-pass budget, not by the full pass); byte-identity of the full-resolution result with sub-pass dispatch on vs off at equal spp. |
| `tests/test_pkg266_dirty_domain_commit.py` | In-process with `bpy` stubbed: N material edits during a busy worker coalesce into one materials-only replay under the token; a geometry edit still forces the full sync; no commit runs while the worker is not idle. |
| `benchmarks/viewport_parity/results/2026-09-09-phase2-p23/SUMMARY.md` | The re-measured §9 gate table (idle GPU, Terra-4 instrument, both scenes, worker ON/OFF, settle + storm). |

### Files to modify

| File | What changes |
|---|---|
| `src/gpu/wavefront/gpu_wavefront_snapshot.cu` | Cancellation-bounded dispatch: the wavefront pass is launched in bounded work units (tile / sub-pass / spp slice) with the host cancel poll between units; an interactive first unit at reduced resolution (pkg241 Phase 1a budget) so the first present is fast. `stageShadeBucketedKernel` REG 254 must hold; no per-unit re-upload of scene arrays. |
| `module/blender_module.cpp` | Expose the sub-pass budget (ms or spp) on the render call; `last_render_info()` reports units launched / cancelled-at-unit. |
| `blender_addon/exporter.py` | Process-global admission token (§3.5) replacing the per-worker lock; coalesced dirty-domain mask recorded on the main thread (`view_update` cache diff) and replayed as materials / lights / transforms upload ops under the token after idle; full `sync_viewport_scene` only for geometry/unknown; F12 acquires the global token. |
| `benchmarks/viewport_parity/blender_driver.py` | Settle mode: guarantee ≥ 1 eligible terminal generation per idle span (the ticker must let one generation finish) so present-rate is gradeable; record cancelled-at-unit. |
| `.astroray_plan/docs/pkg241-phase2-offthread-design-2026-09-08.md` | §14 P2.3 design delta + results. |
| `.astroray_plan/packages/pkg241-render-cancellation-viewport-response.md` | Progress: residual gates owned here. |

### Key design decisions

- **Bound the cancel at the dispatch, not in Python.** Terra review 4: a smaller Python chunk cannot bound a long wavefront pass; the poll must sit between bounded GPU work units. Keep the units large enough that the pkg81 bench frame time stays within +5 %.
- **Coalesce, then replay.** The main thread only records what changed; the replay of safe domains happens under the token when the worker is idle. Geometry and anything not classified stays on the full sync — never guess.
- **One token.** The scene-switch bug was the per-worker token; the global token (design §3.5) is the fix class, and F12 uses the same token (owner: F12 pauses the viewport).
- **Measure on an idle GPU with the Terra-4 instrument.** No number is quoted while any CUDA build or other Blender runs (memory `gpu-lock-lanes-overwrite-lock-file`); both scenes, worker ON/OFF, settle + storm, ≥ 2 reps.
- **Flag stays opt-in** until every §9 gate passes on both scenes; the default flip is its own line in Progress with the numbers.

---

## Acceptance criteria

- [ ] Cancel p99 ≤ 300 ms on both scenes (continuous storm, generation-paired `cancel_request → idle_drain`).
- [ ] Tick-gap p95 ≤ 33 ms on both scenes for the realistic settle cadence, and ≤ 33 ms or an explained residual for the storm.
- [ ] Present-rate gradeable (≥ 1 terminal generation per idle span) and ≥ 0.9 × completed; frame age ≥ 0; mailbox ≤ 1; 0 CUDA errors; comparator ±5 % / max-abs ≤ 2e-2 vs the synchronous path.
- [ ] pkg81 bench frame time within +5 % with sub-pass dispatch on; REG 254 held.
- [ ] Both new test files green; pkg241 suites green; scene-switch test green.
- [ ] cpp-abi-guard MERGE (native change) and one Codex Terra call on the diff.

---

## Non-goals

- No A1 (native session thread) — A2 stands (design §12).
- No denoise inside the interactive loop (owner: settled-only).
- No change to the default `ASTRORAY_VIEWPORT_WORKER` value without the gate table.

---

## Progress

- [ ] 2026-09-09 — filed by the lead at the P2.2 closeout; not started.
- [~] 2026-09-10 — implementation landed on `feat/pkg266-viewport-p23-bounded-dispatch`:
  - **Native bounded dispatch** (`gpu_wavefront_snapshot.{h,cu}`, `blender_module.cpp`):
    `sub_pass_budget` on `render()` — the GPU driver calls `cudaDeviceSynchronize()`
    + polls the cancel hook every N wavefront passes, so an in-flight chunk stops
    within one bounded unit instead of after the whole async launch backlog drains
    (P2.2 cancel-p99 root cause). A host sync does not change device execution, so
    `budget>0` is numerically identical to `budget=0` (byte-identical fleet path
    when the callback is null / budget 0). `last_render_info()` reports
    `units_launched` / `cancelled_at_unit`.
  - **Process-global admission token + F12 gate** (`exporter.py`, `__init__.py`):
    the per-worker `threading.Lock` is replaced by one module-level
    `_GLOBAL_ADMISSION_TOKEN` shared by every viewport worker; F12 raises a
    process-wide pause gate, drains all viewports, and owns the token across its
    own renderer construction/render (§3.5).
  - **Coalesced dirty-domain commit** (`exporter.py`): `apply_depsgraph_updates`
    split into a pure classifier + dispatch; edits arriving while the worker is
    busy record a coalesced dirty-domain mask from the live depsgraph and replay
    the safe material/light/env/transform uploaders under the token at idle —
    geometry/instancing/unknown still full-sync (§13 item 2).
  - **Terra-4 instrument** (`blender_driver.py`, `blender_recorder.py`): adaptive
    settle (idle span waits for a terminal publication → present-rate gradeable)
    + cancelled-at-unit reporting.
  - Tests: `test_pkg266_bounded_dispatch.py` (GPU), `test_pkg266_dirty_domain_commit.py`
    (bpy-free, 9 passed); pkg241/pkg56/pkg114/pkg116/pkg96 bpy-free suites 86 passed.
  - GPU build + Terra-4 GUI re-measure (both scenes, worker ON/OFF, settle+storm)
    in progress under the GPU lock; §9 gate table + worker-default decision to
    land in the SUMMARY before the lead flips this to done.

---

## Lessons

- (none yet)

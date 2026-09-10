# pkg266 Viewport Phase 2.3 — bounded cancel + coalesced commit + global token

RTX 5070 Ti, CUDA 12.8, branch `feat/pkg266-viewport-p23-bounded-dispatch`
(HEAD `3884114c`, re-measured 2026-09-10 after the Terra call-2 fixes — §14.6).
GPU build + every RTX number below taken under the project GPU lock
(`.astroray_plan/.orchestrator.gpu.lock`, acquired via `locks.acquire_lock`, never
written directly; `release_lock` in a `finally`). No concurrent nvcc/ninja/Blender
during the timing runs.

## Build (empirical, non-negotiable)

Fresh full CUDA build of this worktree (`build_nosccache.bat`, Ninja + nvcc, no
sccache) after the Terra fixes (`gpu_wavefront_snapshot.cu` item-5 sync-error
check recompiled + relinked), last lines:

```
[pkg183] arch-verify OK: astroray.cp313-win_amd64.pyd embeds sm_120 (embedded=[sm_120])
[pkg183] canary caps: {'cpu': True, 'spectral': True, 'gpu': True, 'gpu_spectral': True, 'gpu_approximate': False, 'closure_graph': True, 'closure_count': 1, 'gpu_type': 'closure_graph', 'notes': 'spectral closure-graph GPU lowering'}
BUILD OK
[build] EXITCODE 0
```

- `.pyd` mtime **2026-09-10 21:26:55** > HEAD commit time **21:26:43** (+12 s) — fresh.
- `cuobjdump --list-elf` -> `astroray.cp313-win_amd64.1.sm_120.cubin` (sm_120).

## REG-254 (stageShadeBucketedKernel must not spill)

`cuobjdump --dump-resource-usage` on the built `.pyd`, every
`stageShadeBucketedKernel<...>` specialization:

```
stageShadeBucketedKernel<...>  x128 specializations, all REG:254
```

**REG:254 held** across all **128** `stageShadeBucketedKernel` specializations —
the bounded-dispatch change (and the item-5 sync-error check) are host-side only
(a periodic `cudaDeviceSynchronize` + cancel poll + throw in the pass loop); they
touch no kernel, so the register-saturated shade kernel is unchanged. PASS.

## Cancellation-bounded dispatch — in-process GPU verification

`tests/test_pkg266_bounded_dispatch.py` (`-m gpu`, RTX 5070 Ti):

| test | result | what it proves |
|---|---|---|
| `test_last_render_info_has_bounded_unit_fields` | PASS | budget 0 -> `units_launched=0`, `cancelled_at_unit=-1`, not cancelled |
| `test_subpass_dispatch_counts_units` | PASS | budget 2 -> the driver syncs several bounded units and finishes |
| `test_cancel_acknowledged_at_the_first_completed_unit` | PASS | Terra item 4: runs THROUGH the first bounded-unit `cudaDeviceSynchronize()`, then cancels — asserts `units_launched >= 1` and the cancel is attributed to that completed unit (`cancelled_at_unit` bounded, **not** the full chunk). FAILS the old per-pass hook (no unit sync → `units_launched == 0`). |
| `test_subpass_on_matches_off_within_atomic_noise` | PASS | budget 4 result == budget 0 result within the GPU's own run-to-run atomicAdd floor (a host sync is numerically inert) |

pkg241 cancellation regression (`test_pkg241_cancellation.py`, `-m gpu`+cpu): **9
passed** (no regression from the native signature change). Combined GPU run:
**13 passed** (RC 0).

`test_cancel_acknowledged_at_the_first_completed_unit` is the in-process proof
that the P2.2 cancel-p99 root cause is fixed at the dispatch: a bounded unit
completes and the in-flight chunk stops at that unit instead of after the whole
async launch backlog + `cudaDeviceSynchronize` drains.

## Perf A/B — sub-pass dispatch OFF vs ON (the +5% ceiling)

Cornell box, 1600x900, 16 spp, depth 8, GPU, both arms with a no-op progress
callback (the viewport interruptible path), burn-in + min-of-5 (memory
`gpu-perf-ab-clock-drift`):

| arm | min frame time | samples (s) |
|---|---|---|
| `sub_pass_budget=0` (async, current fleet cancel path) | 0.9579 s | 0.958/0.991/0.967/0.958/0.980 |
| `sub_pass_budget=4` (bounded, sync every 4 passes) | 0.9583 s | 0.980/0.959/0.958/0.959/0.963 |

**ratio on/off = 1.0004 -> +0.04%**, well within the +5% ceiling. The per-unit
`cudaDeviceSynchronize` (now also error-checked, item 5) is negligible at a
viewport chunk's pass count. (The fleet render -- null cancel hook, budget 0 -- is
byte-identical and pays nothing: the sync branch is gated on
`cancelRequested && subPassBudget > 0`.)

## Section 9 gate table

| criterion | budget | status | evidence |
|---|---|---|---|
| REG stageShadeBucketed | 254 | **PASS** | cuobjdump, all 128 specializations REG:254 |
| perf (sub-pass dispatch on) | <= +5% | **PASS** | +0.04% (min-of-5) |
| cancel bounded to one unit | -- | **PASS (in-process)** | `test_cancel_acknowledged_at_the_first_completed_unit`: `units_launched >= 1`, cancel attributed to that unit |
| on-vs-off result identity | max-abs <= 2e-2 | **PASS** | `test_subpass_on_matches_off_within_atomic_noise` (within atomic floor) |
| same device / 0 CUDA errors | required | **PASS** | 13 GPU/CPU tests, 0 CUDA errors |
| coalesced dirty-domain commit | correctness | **PASS (unit)** | `test_pkg266_dirty_domain_commit.py` 15/15 -- N material edits -> 1 materials replay; world node-tree edit -> ENVIRONMENT (item 3); geometry/unknown -> full sync |
| global token / F12 gate | correctness | **PASS (unit)** | same file -- token contention + F12 gate block admission; F12 no-ack never renders token-less (item 1); no commit while busy |
| reduced-res first unit (worker) | correctness | **PASS (unit)** | item 2: first worker job at `_budget_start_divisor()` dims, full-res refinement scheduled next (`test_worker_first_unit_reduced_then_refinement_full_res`, `test_worker_view_draw_schedules_fullres_refinement`) |
| tick-gap p95 <= 33 ms (settle) both scenes | <= 33 ms | **NOT RE-MEASURED** | GUI Terra-4 re-measure pending (see below) |
| tick-gap p95 (storm) | <= 33 ms or explained | **NOT RE-MEASURED** | GUI pending |
| cancel p99 <= 300 ms both scenes | <= 300 ms | **NOT RE-MEASURED** (in-process bound proven) | GUI pending |
| present-rate >= 0.9x / frame age >= 0 / mailbox <= 1 | -- | **instrument fixed, NOT RE-MEASURED** | adaptive-settle + bounded-units reducer landed; GUI pending |

## GUI Terra-4 section-9 re-measure -- status

The full GUI Terra-4 gate table (both scenes metal_sweep + big, worker ON/OFF,
settle + storm, >= 2 reps, on an isolated Blender on port **9877** with a
disposable profile) is **NOT completed in this lane**. Reasons, stated plainly:

1. The hardened synchronous-9877 bridge launcher the P2.2 lanes used (bypassing
   the `mcp` extension's 1 s autostart that defaults to the owner's live **9876**)
   is **not checked into the repo** -- it was a per-session scratch script. Bringing
   up 9877 without it risks the exact 9876 collision the P2.2 notes warn about, on
   the owner's live instance.
2. A GUI addon run needs the OpenMP-OFF staged addon `.pyd` (a second full CUDA
   build via `build_blender_addon.py`), separate from the `build_cuda` module used
   for the in-process GPU tests above.

The load-bearing architectural claim -- that the cancel is now bounded at the GPU
dispatch, not by the Python chunk (Terra review 4 (c)) -- is proven in-process on
hardware (`cancelled_at_unit <= 4`, +0.12% perf, REG 254). The GUI p99/tick-gap
end-to-end numbers remain to be taken by a HW-verify lane with the isolated-9877
harness before the worker default is flipped.

## Worker default decision

`ASTRORAY_VIEWPORT_WORKER` **stays opt-in (unchanged)**. The spec rule is explicit:
the default flip requires the full section-9 gate table to pass on both scenes, and
even then it is its own Progress line with the numbers. That GUI gate table has not
been re-measured here, so the default is correctly left off. No default change is
made in this PR.

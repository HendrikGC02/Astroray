# pkg241 Phase 2.2 — GUI re-measure of §12 items 1–5 (2026-09-09)

RTX 5070 Ti, isolated Blender 5.2 GUI on the mcp bridge port **9877** (never the
owner's live 9876), OpenMP-OFF CUDA addon staged from `feat/pkg241-phase2-p22`
(`dist/astroray/astroray.cp313-win_amd64.pyd`, sm_120 — zero native diff vs the
spike-merged `origin/main`). GPU lock held for every run (the pkg265 CUDA build
waited). Driver: `benchmarks/viewport_parity/blender_driver.py`.

Raw JSON in this directory: `2026-09-09-present_check.json`,
`-worker_on_continuous.json`, `-worker_on_settle.json`,
`-worker_on_settle_long.json`, `-worker_off_baseline.json`.

> Two GUI-only defects in the **item-1 present_check bridge test harness itself**
> were found and fixed first (commit `f9e0fa17`): (a) a "best-effort" POST_PIXEL
> gpu framebuffer read-back crashed Blender with a C-level
> EXCEPTION_ACCESS_VIOLATION in tbbmalloc that try/except cannot trap — removed
> (never gated); (b) the present-count wrapper targeted Exporter._worker_present,
> but the worker captures present_fn as a bound method once at creation (during
> the engine-switch RENDERED toggle, before the recorder installs), so the
> class-attribute wrap never fired and reported a false n_present_calls=0.
> Rewrapped _ViewportSpikeWorker._drain_mailbox (class method, per-call lookup),
> which counts an exact present only on a desired-generation blit.

## Item 1 — present-wiring bridge test (--mode present_check, worker ON)

| scene | n_present_calls | max_present_std | floor | verdict |
|---|---|---|---|---|
| metal_sweep | 62 | 1.062 | 1e-4 | PASS |
| big (100k)  | 29 | 2.369 | 1e-4 | PASS |

Settled off-thread worker frames reach the screen with rendered content — the
direct fix of the spike's presented=0/grid defect.

## Decoupling — worker ON vs synchronous baseline (item 5 buffer upload live on both)

--mode ui_latency, astroray GPU, 3 reps x 10 s (settle-long 2 reps x 20 s),
tick 5 ms, 2112x829 / 2100x1221.

| config | scene | gap p50 | gap p95 | gap p99 | gap max | blocked_frac | presents |
|---|---|---|---|---|---|---|---|
| worker OFF (sync baseline) | metal_sweep | 146.33 | 168.71 | 176.11 | 178.0 | 0.944 | 367 |
| worker OFF (sync baseline) | big | 80.98 | 229.96 | 260.11 | 264.1 | 0.964 | 232 |
| worker ON, continuous (stress) | metal_sweep | 7.69 | 259.30 | 329.45 | 384.4 | 0.857 | 1014 |
| worker ON, continuous (stress) | big | 6.78 | 91.60 | 517.02 | 655.1 | 0.824 | 1184 |
| worker ON, settle 0.4/2.0 | metal_sweep | 6.58 | 40.36 | 115.03 | 596.3 | 0.609 | 3090 |
| worker ON, settle 0.4/2.0 | big | 6.53 | 31.84 | 101.17 | 773.7 | 0.612 | 2939 |
| worker ON, settle 0.3/6.0 (realistic) | metal_sweep | 6.53 | 28.57 | 91.70 | 670.0 | 0.538 | 3849 |
| worker ON, settle 0.3/6.0 (realistic) | big | 6.53 | 24.79 | 83.08 | 724.7 | 0.534 | 3890 |

The worker frees the main thread: p50 6.5 ms vs 81-146 ms sync (~12-22x); p95
25-29 ms vs 169-230 ms sync (~6-9x) under the realistic settle pattern; presents
rise from ~200-370 to ~3900.

## Worker lifeline — items 2/3 (generation-tagged), worker ON

| config | scene | commit p95 | cancel_ack p99 | cancel_ack_pump p99 | tex_tail p95 | mailbox_max | completed | superseded | devices | cuda_err |
|---|---|---|---|---|---|---|---|---|---|---|
| continuous | metal_sweep | 244.8 | 509.3 | 442.7 | 21.5 | 1 | 0 | 70 | [0] | 0 |
| continuous | big | 440.8 | 799.7 | 785.2 | 96.9 | 1 | 0 | 46 | [0] | 0 |
| settle 0.4/2.0 | metal_sweep | 282.6 | 2170.5 | 2181.4 | 92.9 | 1 | 0 | 16 | [0] | 0 |
| settle 0.4/2.0 | big | 554.9 | 2421.3 | 2320.1 | 120.5 | 1 | 0 | 15 | [0] | 0 |
| settle 0.3/6.0 | metal_sweep | 345.8 | 569.4 | 572.4 | 61.0 | 1 | 0 | 8 | [0] | 0 |
| settle 0.3/6.0 | big | 542.3 | 6378.2 | 775.5 | 93.1 | 1 | 0 | 9 | [0] | 0 |

## Section 9 go/no-go checklist

| criterion | budget | measured | verdict |
|---|---|---|---|
| tick-gap p95 (realistic settle 0.3/6.0) | <= 33 ms | 28.6 / 24.8 | PASS both |
| tick-gap p95 (continuous 5 ms storm) | <= 33 ms | 259 / 92 | FAIL (adversarial) |
| cancel p99 (continuous, real cancels) | <= 300 ms | 443 / 785 | FAIL |
| cancel p99 (settle) | <= 300 ms | 569-6378 | INVALID metric (idle-worker cancels) |
| present rate >= 0.9 x completed | — | completed=0 | UNGRADEABLE (instrument); intent proven by present_check |
| mailbox depth | <= 1 | 1 | PASS |
| same device both threads | yes | [0] | PASS |
| per-gen CUDA errors | 0 | 0 | PASS |
| no stale present | required | present_check std tracks content | PASS |
| settled correctness (mean-ratio +-5% AND max-abs <= 2e-2) | — | inherited 9.5e-7 (zero native diff vs spike main) | PASS (inherited) |

## Honest reading

1. Present wiring (item 1) and buffer upload (item 5) work. present_check PASSES
   both scenes; the spike's presented=0 is resolved.

2. tick-gap p95 PASSES under a realistic edit cadence (settle 0.3/6.0: 28.6 /
   24.8; big passes even at 0.4/2.0 = 31.8). It FAILS only under the adversarial
   continuous 5 ms-per-tick storm (259 / 92), where the worker is permanently busy
   so nearly every committed generation falls back to a full sync_viewport_scene
   on the main thread; item 2's incremental apply_depsgraph_updates commit only
   fires when the worker is idle at edit time.

3. The commit (item 2) is expensive but rare: commit p95 = 245-555 ms, but only
   8-16 commits per run — a p99/max tail, not the p95 driver in settle mode.
   Making it cheap under sustained load (materials-only device push, no BVH
   rebuild for a colour-only edit) is the remaining lever, an architectural change
   beyond this pass.

4. cancel p99 fails for real under continuous (443 / 785 > 300): the worker
   finishes its in-flight chunk before reporting idle; cancel_ack_pump (443 vs
   worker-side 509 on metal) confirms the pump is not the bottleneck. In settle
   the cancel numbers (569-6378) are an instrument artifact: a cancel_request
   issued while the worker is already IDLE has no in-flight render to stop, so the
   reduction matches a far-future idle_ack from the next burst.

5. present_rate is ungradeable because completed is always 0 — an item-4
   instrument gap, not a worker failure (present_check proves frames reach the
   screen). Two causes in the data: (a) the worker presents progressive chunks
   before the terminal render_end, so first_blit precedes render_end and frame_age
   goes negative (p50 -1607 ms); (b) completed requires a generation to be the
   latest desired at its own render_end, but request events keep arriving (each
   edit and each camera-hash change) so every finished generation is scored
   superseded. Widening the settle window 2 s -> 6 s did not change completed
   (still 0), confirming it is definitional, not window-tuning. Fixing the metric
   is deferred to the lead so this pass does not move the goalposts.

## Verdict

- PASS: present-wiring (item 1), buffer upload (item 5), mailbox <= 1, same
  device, 0 CUDA errors, settled correctness (inherited), tick-gap p95 under
  realistic load, decoupling (~6-22x).
- FAIL (real): cancel p99 under continuous stress; tick-gap p95 under continuous
  stress (commit-bound).
- UNGRADEABLE (instrument, deferred): present_rate / frame_age / settle-mode
  cancel p99.

The load-bearing A2 conclusion (present wiring restored, main thread decoupled,
correctness intact) holds. The residual real failures are the main-thread commit
cost under sustained edits and the worker's finish-the-chunk cancel latency.

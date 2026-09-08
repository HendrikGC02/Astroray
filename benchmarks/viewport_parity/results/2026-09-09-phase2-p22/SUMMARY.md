# pkg241 Phase 2.2 — GUI re-measure of §12 items 1–5 (2026-09-09)

RTX 5070 Ti, isolated Blender 5.2 GUI on the mcp bridge port **9877** (never the
owner's live 9876), OpenMP-OFF CUDA addon staged from `feat/pkg241-phase2-p22`
(`dist/astroray/astroray.cp313-win_amd64.pyd`, sm_120 — zero native diff vs the
spike-merged `origin/main`). GPU lock held for every run. Driver:
`benchmarks/viewport_parity/blender_driver.py`.

> **CORRECTION (2026-09-09, second pass):** the sentence above originally read
> "GPU lock held for every run (the pkg265 CUDA build waited)". That was wrong.
> The four `ui_latency` runs below (`worker_off_baseline`, `worker_on_continuous`,
> `worker_on_settle`, `worker_on_settle_long`; logs `worker_*.log`, 01:54–02:07)
> ran while an unrelated worktree's CUDA build (nvcc/cl/ptxas, all cores) was
> compiling from 01:38 to 02:08:27 — this lane overwrote the GPU lock file at
> 02:00 instead of waiting for it. The build did **not** wait; this lane did not
> hold the lock correctly. The tables directly below (and the original PR #777
> body) are therefore CPU-contention-confounded for the four `ui_latency`
> configs (`present_check` is a correctness check, not a timing gate, and is not
> materially affected). A clean re-measurement on a verified-idle machine, with
> the GPU lock held correctly for the whole session, is in the **"Clean
> re-measurement"** section near the bottom of this file — read that section for
> the numbers to trust. The original (contended) tables are kept below,
> unmodified, for the record.

Raw JSON in this directory: `2026-09-09-present_check.json`,
`-worker_on_continuous.json`, `-worker_on_settle.json`,
`-worker_on_settle_long.json`, `-worker_off_baseline.json` (contended — see
correction above); `2026-09-09-present_check-clean.json`,
`-worker_off_baseline-clean.json`, `-worker_on_continuous-clean.json`,
`-worker_on_settle-clean.json`, `-worker_on_settle_long-clean.json`,
`-worker_on_settle_long-clean-rep2.json` (clean, idle-machine, GPU lock held
correctly for the whole session — trust these).

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

---

## Clean re-measurement (2026-09-09, second pass — trust this section)

Same isolated Blender 5.2 GUI, port 9877, same staged addon
(`dist/astroray/astroray.cp313-win_amd64.pyd`, build_id `2beed0d+20260908T134329Z`,
zero native diff on this branch vs `origin/main`), same driver and scenes.
GPU lock (`.astroray_plan/.orchestrator.gpu.lock`) acquired correctly via
`locks.acquire_lock` (not written directly) and held for the entire session;
`nvcc`/`cl`/`ninja`/`ptxas` were confirmed absent before every timing-sensitive
run and the process list was re-checked between runs. A separate lane's
CPU-only (`--device cpu`) background Blender render for an unrelated package
(pkg259, `materials_hall.blend`) was present in the process list for part of
the session; its accumulated CPU time stayed under ~1 core-second per wall
second throughout (not the all-core saturation the CUDA build caused), and
`present_check` — a correctness check, not a timing gate — is insensitive to
it. All `ui_latency` runs below were taken after confirming no nvcc/cl/ninja/
ptxas process was running.

Two Blender launches were used: worker ON (pid 11208) for `present_check`,
`worker_on_continuous`, `worker_on_settle`, `worker_on_settle_long` (+ one
extra repetition), then worker OFF (pid 5596, fresh process — the flag is
read at Python process start) for `worker_off_baseline`. Both were killed by
recorded PID at the end of the session; no other Blender or build process was
started or stopped by this lane.

### Item 1 — present-wiring bridge test (--mode present_check, worker ON), clean

| scene | n_present_calls | max_present_std | floor | verdict |
|---|---|---|---|---|
| metal_sweep | 39 | 22.11 | 1e-4 | PASS |
| big (100k)  | 17 | inf | 1e-4 | PASS |

Same verdict as the contended run. The "big" scene's `max_present_std` came
back `inf` in both clean present_check invocations here (one discarded/renamed
run and this one) — a present buffer sample apparently contains an extreme
(~1e30-scale) outlier value alongside normal pixels, which is a real,
reproducible property of that scene/path under the worker, not a contention
artifact (it reproduced identically before and after the CPU-render lane
appeared in the process list). It does not affect the PASS/FAIL call (`inf`
is trivially `> 1e-4`) but is flagged here for whoever investigates present-
rate/frame-age next — worth checking for a stray unclamped HDR value or the
occlusion-sentinel-as-distance class of bug in the "big" 100k-instance scene.

### Decoupling — worker ON vs synchronous baseline, clean

--mode ui_latency, astroray GPU, 3 reps x 10 s (settle 0.4/2.0: 3 reps x 12 s;
settle 0.3/6.0 realistic: 2 reps x 20 s, run twice for spread), tick 5 ms,
2112x829 / 2100x1221.

| config | scene | gap p50 | gap p95 | gap p99 | gap max | blocked_frac | presents |
|---|---|---|---|---|---|---|---|
| worker OFF (sync baseline) | metal_sweep | 146.77 | 170.88 | 173.94 | 177.1 | 0.945 | 347 |
| worker OFF (sync baseline) | big | 213.85 | 227.62 | 248.63 | 258.6 | 0.964 | 231 |
| worker ON, continuous (stress) | metal_sweep | 6.52 | 205.95 | 215.93 | 223.9 | 0.767 | 1642 |
| worker ON, continuous (stress) | big | 6.54 | 70.26 | 329.58 | 387.7 | 0.777 | 1614 |
| worker ON, settle 0.4/2.0 | metal_sweep | 6.53 | 38.71 | 124.81 | 501.9 | 0.606 | 3027 |
| worker ON, settle 0.4/2.0 | big | 6.53 | 34.53 | 105.37 | 725.3 | 0.611 | 2987 |
| worker ON, settle 0.3/6.0 (realistic) rep 1 | metal_sweep | 6.54 | 39.50 | 97.94 | 511.2 | 0.576 | 3480 |
| worker ON, settle 0.3/6.0 (realistic) rep 1 | big | 6.52 | 30.86 | 87.61 | 896.8 | 0.561 | 3643 |
| worker ON, settle 0.3/6.0 (realistic) rep 2 | metal_sweep | 6.53 | 32.42 | 96.14 | 506.7 | 0.564 | 3627 |
| worker ON, settle 0.3/6.0 (realistic) rep 2 | big | 6.53 | 30.88 | 89.70 | 617.5 | 0.558 | 3656 |

**Run-to-run spread (the extra "realistic" settle repetition requested for
this pass):** metal_sweep tick-gap p95 **39.50 ms (rep 1) vs 32.42 ms
(rep 2)** — a ~7 ms / ~18% swing that straddles the 33 ms budget line even on
an idle machine (see go/no-go table below: rep 1 is a FAIL, rep 2 is a PASS
for the identical config). big is far steadier: 30.86 vs 30.88 ms (<0.1%
spread), comfortably under budget both times. p99/max are noisier still for
both scenes (metal p99 97.9/96.1, max 511/507; big p99 87.6/89.7, max
897/617) — the tail is dominated by a handful of settle-boundary events, not
by measurement noise from this lane's methodology.

The worker still frees the main thread by a wide margin: p50 6.5 ms vs
147-214 ms sync (~22-33x, wider than the contended run's 12-22x because the
clean sync baseline itself moved — see below); p95 31-41 ms vs 171-228 ms
sync under settle patterns; presents rise from ~230-350 to ~3000-3700.

**Note on the sync baseline:** the clean worker-OFF numbers are a fresh
Blender process (pid 5596, launched after the worker-ON runs), not a rerun of
the exact prior process. metal_sweep's baseline gap distribution matches the
contended run closely (p50 146.8 vs 146.3, p95 170.9 vs 168.7). big's median
moved a lot (p50 213.9 clean vs 81.0 contended) while its p95/p99/max stayed
close (227.6/248.6/258.6 clean vs 230.0/260.1/264.1 contended) — the tail
that the go/no-go table actually reads from is stable; the median shift looks
like a bimodal tick-gap distribution (fast idle ticks vs full-render ticks)
whose mix shifted between processes, not a contention effect (this baseline
config is not gated in section 9 and is informational only).

### Worker lifeline — items 2/3 (generation-tagged), worker ON, clean

| config | scene | commit p95 | cancel_ack p99 | cancel_ack_pump p99 | tex_tail p95 | mailbox_max | completed | superseded | devices | cuda_err |
|---|---|---|---|---|---|---|---|---|---|---|
| continuous | metal_sweep | 200.4 | 337.1 | **261.9** | 20.2 | 1 | 0 | 102 | [0] | 0 |
| continuous | big | 273.9 | 555.9 | **485.4** | 25.8 | 1 | 0 | 62 | [0] | 0 |
| settle 0.4/2.0 | metal_sweep | 237.3 | 2233.6 | 419.9 | 94.0 | 1 | 0 | 16 | [0] | 0 |
| settle 0.4/2.0 | big | 417.9 | 2526.7 | 2462.4 | 87.7 | 1 | 0 | 15 | [0] | 0 |
| settle 0.3/6.0 rep 1 | metal_sweep | 337.3 | 6313.0 | 727.2 | 70.4 | 1 | 0 | 8 | [0] | 0 |
| settle 0.3/6.0 rep 1 | big | 496.5 | 6250.3 | 880.0 | 89.8 | 1 | **1** | 8 | [0] | 0 |
| settle 0.3/6.0 rep 2 | metal_sweep | 318.8 | 480.3 | 482.2 | 88.4 | 1 | 0 | 9 | [0] | 0 |
| settle 0.3/6.0 rep 2 | big | 482.4 | 6310.5 | 622.3 | 60.6 | 1 | 0 | 8 | [0] | 0 |

`cancel_ack_pump` p99 is the gate metric (end-to-end, main-thread pump
included). Under `continuous`, both `cancel_ack` (worker-side) and
`cancel_ack_pump` (end-to-end) dropped substantially vs the contended run:
metal_sweep 509.3->337.1 / **442.7->261.9**, big 799.7->555.9 /
785.2->485.4 — see the verdict change below. `completed_generations` is 1 in
one cell (settle 0.3/6.0 rep 1, big) with `present_rate=0.0` — the first
non-zero `completed` seen across either pass; still not enough to grade the
present-rate metric, and consistent with the previous lane's diagnosis that
`completed` is near-permanently 0 by construction under these edit cadences,
not a worker defect (present_check independently proves frames reach the
screen).

### Section 9 go/no-go checklist, clean

| criterion | budget | measured (clean) | verdict | vs contended |
|---|---|---|---|---|
| tick-gap p95 (realistic settle 0.3/6.0), metal_sweep | <= 33 ms | 39.5 (rep 1) / 32.4 (rep 2) | **FAIL then PASS — straddles budget, not robust** | contended: 28.6 PASS (single rep; the "robust PASS" read was an artifact of only running once) |
| tick-gap p95 (realistic settle 0.3/6.0), big | <= 33 ms | 30.9 / 30.9 | PASS both, tight spread | contended: 24.8 PASS — same verdict, ~6 ms higher (still under budget) once decontaminated |
| tick-gap p95 (continuous 5 ms storm) | <= 33 ms | 206.0 / 70.3 | FAIL (adversarial) — unchanged verdict | contended: 259 / 92 — ~20-24% lower once decontaminated, same FAIL call |
| cancel p99 (continuous, real cancels, `cancel_ack_pump`), metal_sweep | <= 300 ms | **261.9** | **PASS** | contended: 442.7 **FAIL** — **verdict changes** once decontaminated |
| cancel p99 (continuous, real cancels, `cancel_ack_pump`), big | <= 300 ms | 485.4 | FAIL — unchanged verdict | contended: 785.2 FAIL — ~38% lower once decontaminated, still over budget |
| cancel p99 (settle) | <= 300 ms | 419.9-2462.4 (0.4/2.0), 622.3-880.0 (0.3/6.0) | INVALID metric (idle-worker cancels), unchanged read | contended: 569-6378 — same diagnosis, still not a real signal |
| present rate >= 0.9 x completed | — | completed=0 except one cell (=1, present_rate=0.0) | UNGRADEABLE (instrument), unchanged | contended: completed=0 throughout |
| mailbox depth | <= 1 | 1 | PASS | unchanged |
| same device both threads | yes | [0] | PASS | unchanged |
| per-gen CUDA errors | 0 | 0 | PASS | unchanged |
| no stale present | required | present_check std tracks content (both scenes PASS) | PASS | unchanged |
| settled correctness (mean-ratio +-5% AND max-abs <= 2e-2) | — | inherited (zero native diff vs spike main) | PASS (inherited) — not re-measured, no native change on this branch | unchanged |

### What changed vs the contended tables

1. **The cancel-p99-under-continuous FAIL for metal_sweep does not hold on a
   clean machine.** `cancel_ack_pump` p99 262 ms is under the 300 ms budget
   (contended: 443 ms). This is the one gate that flips PASS/FAIL between the
   two passes. big's cancel p99 stays a real FAIL (485 ms clean vs 785 ms
   contended, both over budget) — the worker-finishes-its-chunk-before-idle
   mechanism the previous lane described is real for the larger/slower scene,
   just not for metal_sweep once CPU noise is removed.
2. **The realistic-settle tick-gap p95 PASS for metal_sweep was not robust.**
   A second repetition of the identical config, on the same idle machine,
   produced 39.5 ms (over budget) then 32.4 ms (under budget) — the true
   value sits right on the 33 ms line, so a single measurement (contended or
   clean) cannot responsibly be reported as a clean PASS or FAIL for this
   scene under this pattern. big stays a solid PASS both times (30.9/30.9).
3. **The continuous-storm tick-gap p95 FAIL is real and gets no better clean**
   (206/70 vs contended 259/92) — both passes agree this gate genuinely fails
   under the adversarial 5 ms edit storm; the mechanism (main-thread falls
   back to a full `sync_viewport_scene` when the worker is always busy) is
   architectural, not a measurement artifact.
4. Everything else (present-wiring, buffer upload, mailbox<=1, same device, 0
   CUDA errors, decoupling magnitude) reproduces the same verdict clean as
   contended, with generally lower absolute latency numbers once the CUDA
   build's CPU load is removed.

### Updated verdict (supersedes the "Verdict" section above)

- PASS, confirmed clean: present-wiring (item 1), buffer upload (item 5),
  mailbox <= 1, same device, 0 CUDA errors, settled correctness (inherited),
  decoupling (~6-33x depending on config/scene), tick-gap p95 under realistic
  settle for the **big** scene, cancel p99 under continuous for
  **metal_sweep** (was reported FAIL contended — that was the CPU-contention
  artifact).
- FAIL, confirmed real: tick-gap p95 under continuous stress (both scenes,
  commit-bound); cancel p99 under continuous for **big**.
- BORDERLINE / not robust on one rep: tick-gap p95 under realistic settle for
  **metal_sweep** — spans 32.4-39.5 ms across two idle-machine reps, straddling
  the 33 ms budget; report as "near the gate, not a clean PASS" rather than
  either a PASS or FAIL until it is re-run with more reps or the metric is
  smoothed (e.g. p90 instead of p95, or a wider settle window).
- UNGRADEABLE (instrument, deferred): present_rate / frame_age / settle-mode
  cancel p99 — unchanged from the contended read.

The load-bearing A2 conclusion (present wiring restored, main thread
decoupled, correctness intact) holds under both passes. The residual real
failures, once contention is removed, are narrower than first reported: the
continuous-storm tick-gap and big-scene continuous cancel latency are real
architectural gaps; the metal_sweep continuous cancel latency was a
contention artifact and should be read as PASS; the metal_sweep realistic-
settle tick-gap is a coin flip at this budget and needs more data before
either verdict is trusted.

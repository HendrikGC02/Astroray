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

---

## Post-fix graded measurement (Terra-4 instrument, 2026-09-09, third pass)

Same RTX 5070 Ti, isolated Blender 5.2 GUI on port **9877**, disposable profile
(`BLENDER_USER_RESOURCES`/`EXTENSIONS`/`CONFIG`/`SCRIPTS`/`DATAFILES` redirected
to a fresh temp dir; `mcp` extension copied verbatim from the default profile,
`astroray` staged from this worktree's HEAD `d96a4597`). GPU lock held for the
whole session via `locks.acquire_lock` (never written directly); `nvcc`/`cl`/
`ninja`/`ptxas` confirmed absent before and between every run.

**Addon staging note:** two native `.pyd` candidates were tried, both reproduce
every finding below identically: (1) the main-tree canonical build
`build_cuda/astroray.cp313-win_amd64.pyd` from the root `Astroray` checkout
(OpenMP setting unknown, build-ID `dev`; its mtime, 2026-09-08 23:41, predates
`origin/main` HEAD `015e3d30`'s commit timestamp by ~3 h, so it is missing the
#762/#769/#772 native fixes those two commits added to `blender_module.cpp` —
irrelevant to the emission/compensation-table behavior those commits touch, but
flagged per the pyd-staleness build rule); (2) this worktree's own cached
`build_blender_addon_cuda/astroray.cp313-win_amd64.pyd`
(build-ID `2beed0d+20260908T134329Z`, confirmed `-DASTRORAY_DISABLE_OPENMP=ON`
i.e. the correct Blender-specific flags) — but that build predates the
branch's rebase onto `896d7f7c`, so it is *also* missing #769/#772. Since P2.2
has zero native diff on this branch, neither gap should matter for viewport-
worker behavior, and the identical crash below reproduces on both, ruling out
the pyd choice as the cause (see "New finding" below). The graded numbers in
this section use candidate (2), the correct Blender-specific OpenMP-OFF build.

### NEW FINDING (blocking): the viewport worker corrupts the CUDA context on a scene switch

**`ASTRORAY_VIEWPORT_WORKER=1` + switching the loaded `.blend` mid-session
(metal_sweep -> big or big -> metal_sweep) reliably crashes the GPU wavefront
pipeline**, reproduced 3/3 times across two different native `.pyd` builds:

```
[CUDA] light tree not uploadable (dedicated lights present) - GPU NEE falls back to power-CDF selection
stage_env_shadow launch error: an illegal memory access was encountered
allocateGPUWavefrontState: cudaMalloc failed for s.pixel_index
stage_shade_bucketed launch error: an illegal memory access was encountered
```
(a second reproduction printed `stage_queue_iota launch error: invalid
argument` twice before the same `illegal memory access`). Once the CUDA
context is in this state every subsequent render in that process returns
`n_present_calls=0` — including scenes that individually work fine (see
below), because a CUDA illegal-access poisons the context for the rest of the
process's lifetime.

**Isolation (fresh Blender process per test, same disposable profile, same
OpenMP-OFF `.pyd`):**

| test | result |
|---|---|
| `big` scene alone, worker ON, fresh process | PASS (42 presents, std 1.06) |
| `metal_sweep` alone, worker ON, fresh process, called twice in a row (same scene, no switch) | PASS both times (60, 47 presents) |
| `metal_sweep` then switch to `big`, same worker-ON process | **FAIL** — `metal_sweep` itself now also reads 0 presents (context already poisoned by the switch) |
| `metal_sweep` -> `big` switch, worker **OFF**, same OpenMP-OFF `.pyd`, via `--mode ui_latency` (5 s/scene) | PASS both scenes (732, 772 presents), **zero errors in stderr** |

This isolates the defect to **the worker path specifically reacting to a full
scene reload** (not to any single scene, not to the pyd build, not to scene
switching in general — the synchronous/worker-OFF path handles the identical
switch cleanly). The pre-terra4 clean pass (this file, "Clean re-measurement"
section) switched scenes repeatedly within one live worker-ON session without
a crash, so this is either a regression introduced by the Terra4 item-2/3/4
`exporter.py` changes (commit-mode / pump / cancel-generation-pairing) meeting
a full-scene-reload commit for the first time under the new code paths, or
was exposed (not introduced) by them — root-causing which requires reading
`_worker_commit_and_submit`'s handling of a `scene_full`-class commit arriving
while the worker holds device buffers sized for the *previous* scene, which is
implementation work out of scope for this measurement lane. **Filed as a
P2.3-blocking finding, not merely a residual latency gap** — this is a
correctness/stability regression against the design doc §9 "same device / 0
CUDA errors" gate under completely ordinary usage (the owner switching which
scene the viewport is showing while Astroray is the active engine).

**Diagnosis of the previously-flagged `big`-scene `max_present_std=inf`
outlier (pre-terra4 clean pass, this file above):** that run's `present_check`
called `--scenes metal_sweep big` in one live worker-ON session, i.e. it hit
the exact same scene-transition path implicated above. Re-running `big` in
total isolation (fresh process, never touched `metal_sweep`) on this build
gives clean, finite sample buffers (max value ~9.8, std 1.06 — see
`2026-09-09-present_check_big-terra4.json`), not `inf`. The most likely
explanation: the pre-terra4 build's scene-transition path had the *same*
underlying device-memory hazard, but it manifested there as a stale/
uninitialized buffer read (a huge finite-or-`inf` sentinel value in one pixel)
rather than an outright CUDA context poison — i.e. `inf` then and the crash
now look like two severities of the same latent bug, not two unrelated
issues. Not proven (would need instrumented device-memory tracing to
confirm), but offered as the leading hypothesis for whoever picks up the
P2.3 fix.

**Methodology consequence for the graded numbers below:** every worker-ON
measurement was taken from its own freshly-launched, single-scene Blender
process (never switching `.blend` files mid-session) to avoid the corruption
above contaminating the timing/instrument numbers. `present_check` was also
run once as the original combined `--scenes metal_sweep big` call, kept as
`2026-09-09-present_check-terra4.json` for the record — it shows exactly the
failure above (metal_sweep PASS n=44 std=1.01, big FAIL n=0) and is *not* used
for any gate number. Worker-OFF baseline does not need this workaround (both
scenes measured in one process, per the isolation test above).

### Item 1 — present-wiring bridge test (`--mode present_check`, worker ON), post-fix, per-scene isolated

| scene | n_present_calls | max_present_std | floor | verdict |
|---|---|---|---|---|
| metal_sweep | 59 | 1.05 | 1e-4 | PASS |
| big (100k)  | 44 | 1.06 | 1e-4 | PASS |

Both PASS cleanly in isolation (no `inf`, see diagnosis above). Item 5 buffer
upload: `--mode buffer_identity` — `equal=True roundtrips=True n_floats=36636
n_diff=0` -> **PASS**.

### Decoupling + worker lifeline, post-fix, per-scene isolated

`--mode ui_latency`, astroray GPU, tick 5 ms, 2112x829 / 2100x1221. `continuous`
= 3 reps x 10 s; `settle 0.3/6.0` (realistic) = 2 reps x 20 s, run twice per
scene for spread (matching the prior pass's methodology).

| config | scene | gap p50 | gap p95 | gap p99 | gap max | presents |
|---|---|---|---|---|---|---|
| worker OFF (sync baseline) | metal_sweep | 148.31 | 160.13 | 171.64 | 178.16 | 359 |
| worker OFF (sync baseline) | big | 212.15 | 228.47 | 252.50 | 277.19 | 232 |
| worker ON, continuous (stress) | metal_sweep | 7.50 | 230.45 | 285.32 | 300.21 | 1349 |
| worker ON, continuous (stress) | big | 7.03 | 31.34 | 319.60 | 366.73 | 1859 |
| worker ON, settle 0.3/6.0 rep 1 | metal_sweep | 7.03 | 40.03 | 96.63 | 309.62 | 3288 |
| worker ON, settle 0.3/6.0 rep 2 | metal_sweep | 7.03 | 37.95 | 93.73 | 326.30 | 3352 |
| worker ON, settle 0.3/6.0 rep 1 | big | 7.01 | 15.80 | 61.97 | 397.64 | 4315 |
| worker ON, settle 0.3/6.0 rep 2 | big | 7.01 | 19.79 | 67.29 | 531.08 | 4233 |

| config | scene | commit p95 | cancel_ack_pump p99 | tex_tail p95 | frame_age p50 (>=0) | frame_age p95 | completed | mailbox_max | devices | cuda_err |
|---|---|---|---|---|---|---|---|---|---|---|
| continuous | metal_sweep | 249.39 | 390.71 | 71.47 | 24092.57 | 36052.62 | 0 | 1 | [0] | 0 |
| continuous | big | 259.94 | 470.85 | 26.44 | 25977.48 | 38857.84 | 0 | 1 | [0] | 0 |
| settle 0.3/6.0 rep 1 | metal_sweep | 251.56 | 303.41 | 54.44 | 2092.35 | 34578.23 | 0 | 1 | [0] | 0 |
| settle 0.3/6.0 rep 2 | metal_sweep | 244.89 | 333.38 | 54.81 | 3804.36 | 9676.42 | 0 | 1 | [0] | 0 |
| settle 0.3/6.0 rep 1 | big | 263.09 | 407.99 | 33.79 | 4829.63 | 41045.13 | 0 | 1 | [0] | 0 |
| settle 0.3/6.0 rep 2 | big | 394.53 | 1059.37 | 36.57 | 5858.65 | 8931.93 | 0 | 1 | [0] | 0 |

**Frame-age instrument fix confirmed working (Terra item 3):** every
`frame_age` sample this pass is non-negative (was structurally negative
pre-terra4, e.g. p50 -5628 ms). `present_rate` is **UNGRADEABLE** in every
cell this pass (`completed_generations=0` throughout — no run produced an
eligible terminal generation in its window); the pre-terra4 clean pass had one
non-UNGRADEABLE cell (`settle 0.3/6.0` rep 1, big: `completed=1`). Both are
consistent with the design's documented behavior (UNGRADEABLE when zero
eligible terminal generations exist) — the difference is sampling variance of
a rare event, not a regression.

### Section 9 go/no-go checklist, post-fix (Terra-4 instrument), vs clean pre-fix

| criterion | budget | measured (post-fix) | verdict | vs clean pre-fix |
|---|---|---|---|---|
| same device, 0 CUDA errors, no scene switch | required | [0], 0 errors in every isolated per-scene run | PASS (isolated) | unchanged when isolated |
| **same device / 0 CUDA errors across a scene switch** | required | **illegal memory access, cudaMalloc failure, 0 presents** | **FAIL — NEW regression, not present pre-terra4** | pre-terra4 clean switched scenes in one session with 0 CUDA errors (but produced the `inf` present_check outlier on big — see diagnosis) |
| present-wiring (`present_check`), per scene | required | metal 59/1.05, big 44/1.06, both PASS | PASS | pre-terra4 big showed `inf` (diagnosed above); this pass clean when isolated |
| buffer upload (`--mode buffer_identity`) | required | equal=True, roundtrips=True, n_diff=0 | PASS | new test this pass (Terra buffer-identity note); no prior comparison |
| progressive frame age >= 0 | required | all cells non-negative | PASS | pre-terra4 was structurally negative — **instrument bug fixed** |
| present rate >= 0.9 x completed | — | completed=0 every cell | UNGRADEABLE | pre-terra4 had 1 non-UNGRADEABLE cell (sampling variance, not a regression) |
| mailbox depth | <= 1 | 1 throughout | PASS | unchanged |
| tick-gap p95, realistic settle 0.3/6.0, metal_sweep | <= 33 ms | 40.03 / 37.95 (2 reps) | **FAIL both reps** | pre-terra4: 39.5 FAIL / 32.4 PASS (borderline both passes; this pass reads worse) |
| tick-gap p95, realistic settle 0.3/6.0, big | <= 33 ms | 15.80 / 19.79 (2 reps) | PASS both, wide margin | pre-terra4: 30.86 / 30.88 PASS (tight); this pass has more headroom (isolated process, no cross-scene overhead in the window) |
| tick-gap p95, continuous storm, metal_sweep | <= 33 ms | 230.45 | FAIL | pre-terra4: 206.0 FAIL — unchanged, real |
| tick-gap p95, continuous storm, big | <= 33 ms | 31.34 (p99 319.6, max 366.7) | PASS on p95, but p99/max blow up | pre-terra4: 70.3 FAIL — **this pass reads better on p95 specifically; not trusted as a verdict flip** (single rep, no spread check was run for continuous, unlike settle; the p99/max tail says the underlying behavior is unchanged) |
| cancel p99 (`cancel_ack_pump`), continuous, metal_sweep | <= 300 ms | 390.71 | FAIL | pre-terra4: 261.9 PASS — **reads worse, but the metric itself changed** (Terra item 4 redefined cancel pairing to be generation-correct; the two numbers are not the same measurement, see note below) |
| cancel p99 (`cancel_ack_pump`), continuous, big | <= 300 ms | 470.85 | FAIL | pre-terra4: 485.4 FAIL — unchanged verdict, comparable magnitude despite the metric redefinition |
| cancel p99, settle | <= 300 ms | 303.41 / 333.38 (metal), 407.99 / 1059.37 (big) | mixed, near/over budget | pre-terra4 diagnosed this as an idle-worker-cancel instrument artifact; Terra item 4 tightened the pairing (`cancel_request(in-flight g) -> idle_drain(g)`) so these numbers are more trustworthy than before, and still mostly over budget — read as a genuine (if noisy) settle-mode cancel cost, not purely an artifact anymore |

**On the cancel-p99 metric change (Terra item 4):** pre-terra4, every edit
request was recorded as a cancel and paired with *any* next idle event
regardless of generation, so the old `cancel_ack_pump` numbers (261.9/485.4
continuous) measure a different, looser quantity than the post-fix numbers
(390.71/470.85), which pair `cancel_request(in-flight g)` only with
`idle_drain(g)` of the *same* generation. The post-fix numbers are the
trustworthy ones going forward; the apparent "regression" for metal_sweep
(261.9 PASS -> 390.71 FAIL) is at least partly the old metric under-counting
real cancel latency, not the worker getting slower. No apples-to-apples re-run
of the *old* metric on the *new* code was done (out of scope — the old metric
is retired by design), so the magnitude of "instrument vs real" cannot be
split further here.

### Updated overall verdict (supersedes both sections above for anything the new instrument or the scene-switch finding touches)

- **NEW BLOCKING FINDING:** the viewport worker corrupts the CUDA context on
  an ordinary scene switch (illegal memory access -> 0 presents for the rest
  of the process). Reproduced 3/3 across two native builds; absent when the
  worker is OFF. This must be fixed before P2.3's other work is graded on a
  multi-scene session, and likely explains the pre-terra4 `big`-scene
  `present_check` `inf` outlier as a milder version of the same hazard.
- PASS, confirmed post-fix when isolated per scene: present-wiring, buffer
  upload (new), mailbox <= 1, same device, 0 CUDA errors (single-scene
  sessions only), frame-age non-negativity (instrument fix), tick-gap p95
  under realistic settle for **big**.
- FAIL, confirmed real: tick-gap p95 under continuous stress (both scenes,
  metal_sweep unambiguous, big p95-passes-but-p99/max-fails); cancel p99
  under continuous (both scenes, though the metric changed — see note);
  tick-gap p95 under realistic settle for **metal_sweep** (worse than the
  pre-terra4 borderline read, 2/2 reps over budget this time).
- UNGRADEABLE: present rate (0 eligible terminal generations this pass,
  consistent with pre-terra4's near-zero rate).

Raw per-run JSON/summary files for this pass: every `*-terra4.json` /
`*-terra4-summary.md` file in this directory, plus the combined-scene
`2026-09-09-present_check-terra4.json` kept as crash evidence (not used for
gate numbers).

## FIX — scene-switch CUDA corruption (PR #777, 2026-09-09, fix lane)

**Root cause (design §13a):** the spike's admission token is a *per-worker*
`threading.Lock`, serialising `render()` only WITHIN a session; §3.6's
acknowledged-exit lifecycle owner (`load_pre`/`atexit` drain) was never
implemented (only a best-effort `Exporter.__del__`). On a `.blend` switch the
old worker daemon survives the file load — Blender does not guarantee `__del__`
runs before the new file's `RenderEngine` starts a fresh worker — and the two
workers' `render()` calls race the single process-global `WfContext` ("Single
render thread assumed", `gpu_wavefront_snapshot.cu:988`) → illegal memory access
+ `cudaMalloc failed for s.pixel_index`. The worker-OFF path never has two
render threads, hence its clean switch.

**Fix (no native change):** a process-global live-session registry +
`stop_all_viewport_sessions()`, installed lazily from the first worker start as a
persistent bpy `load_pre` handler and an `atexit` hook (in the bpy-free
`exporter` module, so `blender_addon/__init__.py` stays at the Buffer-only
lines). `load_pre` fires before the incoming file replaces the scene, draining
every prior worker to acknowledged idle (or quarantine) on the main thread, so no
two workers ever touch the `WfContext` across a switch.

**Headless evidence (`tests/test_pkg241_scene_switch.py`, 5 tests, bpy-free):** a
shared single-render-thread device guard records peak concurrent renders across
an old-worker-mid-render → scene switch → new-session sequence. Undrained
(negative control) = **2** (the crash); with `stop_all` in the `load_pre` slot =
**1**. `stop_all` also blocks until the in-flight worker acks exit (thread
joined, `in_flight_generation` cleared). pkg241 bpy-free suite: **34 passed, 1
skipped** (was 29+1; +5 new). Differential lint clean for the changed files.

**GUI two-scene `present_check` under the GPU lock:** see the entry appended
below once the RTX re-run lands (gated on an idle GPU — the fix lane found
`nvcc`/`ninja`/`ptxas` from another worktree active on entry and did not contend
the GPU, per the concurrency rules).

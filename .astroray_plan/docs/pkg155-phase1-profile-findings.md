# pkg155 Phase 1 — GPU absolute slowdown: measured attribution

**Measured:** 2026-07-25 (overnight run), RTX 5070 Ti, main @ `473c25b`, CUDA 12.8.61,
`benchmarks/wavefront_baseline.py --spp 64 --max-depth 8`, cornell scenes, 256²,
1 warmup + 5 measured renders. Raw profile JSON archived alongside the overnight report.

This satisfies the spec's **profile-first contract** (pkg155 §Contract 1) and probes the
**shade stage first**, as the owner directed.

---

## 0. A correction to the spec's headline metric (read this first)

The pkg155 spec quotes the regression as `multiwavelength_megakernel` **mean ms/launch**
19.92 → 113.03. That framing cannot be reproduced or continued, for two reasons:

1. **The kernel no longer exists.** PR #524 deleted both megakernels. Nothing in the tree
   emits a `multiwavelength_megakernel` profile record anymore.
2. **ms/launch is not comparable across the two architectures.** A megakernel runs an
   entire path in *one* launch (count=6 for 6 renders). The wavefront runs many small
   launches (count≈2064 for the same 6 renders). Comparing per-launch means between them
   is a category error and will understate or overstate arbitrarily.

The metric that *is* comparable, and that reflects what the user actually waits on, is
**total GPU kernel time per render** (`sum_ms` over all kernels ÷ renders). All numbers
below use that. **The ~5× regression is real and survives the corrected metric** — this
correction changes the instrument, not the conclusion.

## 1. Confirmed: the absolute regression is ~5×

| Scene | Baseline 2026-05-17 @ `1a3c159` (megakernel) | Current 2026-07-25 @ `473c25b` (wavefront) | Factor |
|---|---|---|---|
| cornell_diffuse | 20.29 ms/render | 98.25 ms/render | **4.84×** |
| cornell_glass   | 21.87 ms/render | 122.69 ms/render | **5.61×** |

## 2. Attribution: the shade stage is the dominant term

| Stage | cornell_diffuse | cornell_glass | regs/thread | blocks/SM |
|---|---|---|---|---|
| `wavefront_stage_shade_bucketed_n7` | 258.49 ms (**43.8%**) | 385.67 ms (**52.4%**) | **221** | **1** |
| `wavefront_stage_intersect_queued_n7` | 116.78 ms (19.8%) | 128.16 ms (17.4%) | 128 | 2 |
| `wavefront_stage_regen_n7` | 111.85 ms (19.0%) | 118.03 ms (16.0%) | 102 | 2 |
| `wavefront_stage_shadow_n7` | 102.37 ms (17.4%) | 104.29 ms (14.2%) | 106 | 2 |

Shade is the single largest consumer in both scenes, and it grows with scene complexity
(43.8% → 52.4% going from diffuse to glass) while every other stage stays flat. It is also
**the only stage that fails to reach 2 blocks/SM.**

## 3. Root cause of the shade stage's occupancy loss (arithmetic, not conjecture)

At 256 threads/block against a 65,536-register file per SM:

| regs/thread | regs/block | blocks/SM |
|---|---|---|
| 221 (shade, today) | 56,576 | **1** |
| 128 | 32,768 | 2 |
| 106 (shadow) | 27,136 | 2 |
| 102 (regen) | 26,112 | 2 |

**The recovery target is ≤ 128 regs/thread** — the largest value that still fits two
256-thread blocks per SM. Shade is at 221, i.e. 93 registers over the line.

For reference, the 2026-05 megakernel achieved 2 blocks/SM at 125 regs. The spec's cited
"188 regs" was the *megakernel's* regrown count; the wavefront shade stage is materially
worse at 221.

Note also `shade` launches with `max_threads_per_block=256` and `launch_blocks=1792`,
where the other three stages use 512 threads and 256 blocks — so the block geometry
differs and any `__launch_bounds__` change must be evaluated against that, not assumed.

## 4. A dispersion signal worth a second look

`shade_bucketed` shows `min_ms=0.009` / `mean_ms=0.125` / `max_ms=3.296` — a ~26× spread
between mean and worst launch, far wider than the other stages
(e.g. shadow: 0.003 / 0.050 / 0.175). That tail is consistent with severe intra-bucket
divergence or a small number of very heavy buckets. Occupancy and divergence are separate
levers; fixing registers will not necessarily fix the tail. Measure them independently.

## 5. Recovery candidates (ranked by measured leverage, NOT yet validated)

1. **Get shade under 128 regs/thread.** Highest leverage by a wide margin — it is the only
   stage below 2 blocks/SM and it is ~half of all GPU time. Levers: `__launch_bounds__`,
   splitting the bucketed shade kernel per material class so each variant carries only its
   own live state, and auditing per-thread state that stays live across the whole kernel.
2. **Investigate the shade tail** (§4) separately from occupancy.
3. **Scene-gate always-on feature branches** in shade (spec §Contract 2's "recoverable
   cost"): the suspect merge window (#481/#484/#486/#489/#500/#490/#494/#515/#519/#518)
   landed almost entirely in shading, which is consistent with shade being the stage that
   blew its register budget while the other three stayed flat.

Every one of these must be measured on hardware before and after; CI is blind here.

## 6. Build-environment hazard found while measuring (affects all pkg155 comparisons)

Two CUDA toolkits are installed: **v12.6** and **v12.8** (12.8 installed 2026-04-25).
`CUDA_PATH` and `PATH` resolve to **12.8**, and `configure_and_build.bat` inherits that —
but `scripts/build/build_cuda_worktree.bat` **hardcodes `CUDA_PATH=...\v12.6`**. So a
build made through the worktree wrapper uses a different compiler than a build made in the
main checkout, and register allocation is compiler-version sensitive.

This does **not** invalidate §1–§3 (baseline and current were both measured in the main
checkout), but it is a live confound for any future bisect: **pin and record the nvcc
version at every bisect point**, exactly as pkg153's protocol pins the tables-loaded
checksum. Recommend aligning the wrapper to 12.8 as a separate, owner-approved change —
deliberately NOT done tonight, because changing the toolkit mid-investigation would
confound the very measurements this package depends on.

## 7. What Phase 2 should do

- Bisect the suspect merge window measuring **regs/thread of the shade stage** (cheap,
  deterministic, no timing noise) rather than wall-clock — the register count is the
  proximate cause of the occupancy loss and is a much sharper bisect signal.
- Record nvcc version + `tables-loaded` state at every point.
- Only then attempt recovery levers, re-measuring §1's ms/render after each.

## Provenance

Measured by the team-lead during the 2026-07-25 overnight run under the serialized GPU
lock. Harness: `benchmarks/wavefront_baseline.py` (unmodified). Baseline of record:
`benchmarks/wavefront/baseline.json` (2026-05-17 @ `1a3c159`, same GPU).

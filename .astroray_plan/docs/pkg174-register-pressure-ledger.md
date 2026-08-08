# pkg174 — wavefront register-pressure recovery: lever ledger

**Machine:** RTX 5070 Ti workstation. **Toolchain:** Ninja + CUDA 12.8 +
native `sm_120` SASS (the shipping config since `50b1d93`). **Base commit:**
`59ab6b9` (post-#541, post-restructure `origin/main`). **Session:**
2026-08-07 (overnight, substitute for the disabled orchestrator tick).

Every number below is a wall-time A/B on the pkg55 perf-gate scene
(`tests/wavefront_diff/test_pkg55_perf_gate.py`: `disney_contact_sheet`,
256×256, 1024 spp, depth 8, seed 424242, via `astroray.cuda_wavefront_render`).
REG/STACK from `cuobjdump --dump-resource-usage` on the linked `.pyd`.

## Measurement methodology (read before trusting any small delta)

The addendum's warning about clock state is real and load-bearing. Concretely,
this session observed the **same lever build** read **1.120 s** and **1.179 s**
minutes apart — a ~5% swing — purely from GPU boost-clock trajectory (the card
idles to P3/667 MHz between renders; the first timed renders after idle catch a
transient boost state). **A ~3% lever signal is inside that noise band.**

Clock locking (`nvidia-smi --lock-gpu-clocks`) is **not available** — the
current user lacks the permission ("current user does not have permission to
change clocks"). So the protocol used here to get a trustworthy comparator:

1. **Burn-in to steady state:** 15 warm renders before timing, which drives the
   card to a stable **2887 MHz / P0 / ~52–55 °C** equilibrium (matches the
   addendum's ~2895 MHz P0 boost state).
2. **min-of-N (N=10)** as the primary statistic — the best-boost point is the
   most reproducible across runs; median is reported alongside.
3. Both the baseline and each lever are measured **at the same 2887 MHz P0**
   equilibrium, verified with `nvidia-smi` immediately after each probe.

Under this protocol the baseline is tight to **±0.3%** (1.143–1.146), which is
what makes the lever verdicts below reliable.

> **Infra gap worth fixing:** without admin/clock-lock, sub-5% lever tuning on
> this box is unreliable and must lean on the burn-in-to-P0 + min-of-N crutch.
> Running the hardware-verifier/orchestrator elevated (or enabling persistence
> mode + a fixed application clock) would make fine perf work trustworthy and
> is a precondition for chasing the last few percent structurally.

## Baseline (fixed reference)

| Metric | Value |
| --- | --- |
| perf-gate min / median (10 runs @ 2887 MHz P0) | **1.145 / 1.147 s** |
| gate median-of-3 (the acceptance protocol) | 1.156 s (matches addendum exactly) |
| `stageShadeBucketedKernel` | REG:254  STACK:2576 |
| `stageAdvanceQueuedKernel` | REG:254  STACK:3168 |
| `stageShadeNeeMisKernel` | REG:254  STACK:3168 |
| `stageAdvanceKernel` | REG:254  STACK:3168 |
| `mean_img` (correctness fingerprint) | 0.27676 |

All four hot kernels are pinned at the **REG:254** architectural ceiling — any
added per-hit state spills, confirming the memory
`wavefront-shade-kernels-register-saturated`.

## Lever ledger

| # | Lever | REG (shade) | STACK (shade) | min / median | vs baseline | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | Baseline (no lever) | 254 | 2576 | 1.145 / 1.147 | — | reference |
| 1 | `__noinline__` fence on `gpu_rgbToSampledSpectrum` | 254 | **2656** | 1.176 / 1.178 | **+2.7% slower** | **REJECTED** |
| 2 | `__launch_bounds__(256, 2)` on `stageShadeBucketedKernel` | 254 | 2576 | 1.143 / 1.144 | within ±0.3% noise | **NULL (no effect)** |

**Lever 1 — `__noinline__` fence** (the uncommitted change inherited in the
worktree, citing Laine/Karras/Aila 2013). Genuine hypothesis: fence the
Jakob–Hanika upsample's live-range into its own callee frame to shrink the
megakernel live set. Measured: static spill went **up** (2576→2656) and steady
wall time went **up 2.7%**. Both signals agree — the fence costs more (call
overhead + arg marshalling across the boundary, hit 1–2× per shade) than the
live-range compression saves. The earlier "≈3% faster" reading was a pure
clock-drift artifact (baseline and lever caught at different transient boost
states); the steady-state A/B reverses it. Dropped, not committed.

**Lever 2 — `__launch_bounds__(256, 2)`** (force 2 blocks/SM → target ≤128
regs, trading spill for occupancy). Measured: ptxas produced **byte-identical**
codegen (REG:254, STACK:2576 unchanged) — the unreachable `minBlocks=2` hint
was silently ignored on `sm_120` (a real register cut to 128 would have spilled
STACK massively; it did not move at all). Perf flat within noise. No effect as
applied. Reverted.

## Conclusion & recommendation

- **The two low-risk micro-levers are exhausted:** noinline is net-negative,
  launch_bounds is inert. Neither moves REG off the 254 ceiling, which is the
  actual constraint.
- **The ≤1.0 s ceiling-restore is NOT met and was not reverted.** Per the
  spec's acceptance definition, reverting the temporary 1.5 s raise
  (`test_pkg55_perf_gate.py` `CEILING_S`) is only valid once the scene actually
  measures ≤1.0 s. It does not (1.145 s), so the raise **stays** — leaving it
  is correct, not a regression.
- **Reaching 1.0 s from 1.145 s needs ~13%**, which the addendum already
  calibrated as achievable only via the **structural stage-split lever** (Laine
  2013 "Megakernels Considered Harmful", already cited in pkg55) — bucketing
  the shade megakernel into per-material-family sub-kernels so the worst-case
  register footprint per kernel drops below 254 and occupancy rises.
- **That structural lever is supervised-worthy and was NOT attempted
  unattended**, deliberately: it is a kernel-architecture change on a
  correctness-frozen (bit-identity gated) serialization-point kernel, under the
  spec's own scope fence ("no new features into the shade stage while this is
  open"), for a target the addendum flags as "bounded by the occupancy cliff"
  (i.e. possibly not reachable even structurally). It should run in a
  supervised session with the bit-identity gates live and, ideally, with clock
  lock available so the per-sub-kernel A/B is trustworthy.

**Net for the settlement round:** pkg174 remains **in progress**. The micro-lever
avenue is closed with evidence; the ceiling raise correctly persists; the
structural stage-split is the remaining path and is routed to supervised work.

---

## Supervised session 2026-08-08 — stage-split executed + register attribution

**Base:** `pkg174-stage-split` off `origin/main` `b4a80d9`. Same machine /
toolchain / protocol (burn-in 15 → 2887 MHz P0, min-of-10). Fresh baseline
reproduced the pinned numbers exactly: shade REG:254 STACK:2576, perf min 1.1446 /
median 1.1458 s.

### Lever 3 — `template<bool Deferred>`, compile out the dead immediate-NEE branch — **KEEP (−1.1%)**

The design doc's cheapest suspect (#2). `shadePathSlot` is now
`template<bool Deferred>`; the immediate-NEE `else` (inline `gpu_nee_occlude`
shadow-ray BVH/TLAS traversal) is `if constexpr`'d out of the deferred
(bucketed + NeeMis) instantiations, where it is dead (`nee_f` always non-null).
`advancePathSlot` keeps it (`Deferred=false`).

| Metric | Baseline | Lever 3 |
| --- | --- | --- |
| `stageShadeBucketedKernel` REG / STACK | 254 / 2576 | 254 / **2256** |
| `stageShadeNeeMisKernel` STACK | 3168 | **2848** |
| perf min / median (2887 MHz P0, N=10) | 1.1446 / 1.1458 | **1.1318 / 1.1330** |

Clean separation (every Lever-3 run < baseline's minimum), so the −1.1% is real,
not clock drift. REG stays at the 254 ceiling (occupancy unchanged); the win is
the −320 B spill-traffic reduction. Bit-identity green
(`test_pkg55_cuda_threshold_gate`, `pkg89_dedicated_nee`, `gpu_wavefront_image`;
full `wavefront_diff` 29 passed); `mean_img` byte-identical. **Committed; this is
the shippable pkg174 change.**

### Register attribution — ncu blocked, stub-and-rebuild fallback

`ncu` unusable: `ERR_NVGPUCTRPERM` (no perf-counter permission — same missing
elevation as clock-lock). Targeted stub-and-rebuild on `stageShadeBucketedKernel`:

| Config | REG | STACK |
| --- | --- | --- |
| baseline (NEE on, BSDF on) | 254 | 2576 |
| NEE section OFF, BSDF on | 254 | 2064 |
| NEE on, BSDF sampler bypassed | 255 | 2320 |
| NEE OFF **and** BSDF bypassed | **95** | 584 |

**This corrects the stage-split design doc's headline.** The 254 ceiling is held
by **two independent ~160-register consumers** on a **~95-register irreducible
state-marshalling base**: the NEE light-sampling section and the BSDF material
union (`gpu_material_sample_spectral`, the *spectral* variant the earlier
experiments never isolated — its own note #3). **Either alone saturates 254**;
only removing both reaches 95. ptxas caps at 254 and spills the combined ~415-reg
want — which is why every single removal moves only STACK (spill), never REG, and
why Lever 3's dead-branch removal bought spill-traffic (−1.1%) but no occupancy.

### Why ≤1.0s is unreachable via stage-split (measured, not asserted)

- Extract NEE → shade keeps BSDF → still 254. Extract BSDF → shade keeps NEE →
  still 255. The extracted kernel itself carries the ~95 base + its ~160 work
  ≈ 254. A split trades one 254-kernel for two 254-kernels + extra path-state
  global round-trips = **net-negative** (Laine 2013 in reverse; the addendum's
  exact warning). **Exp3 was therefore NOT implemented — the measurement shows
  it cannot help.**
- Per-material specialization can't help this scene either: NEE (needed by every
  bucket) independently pins 254, and the perf-gate's heavy buckets
  (disney/glass/closure) have individually large samplers (>128, the 2-blocks/SM
  threshold). Filed as extensibility only —
  `pkg174-per-material-kernel-dispatch-design.md`.
- The only remaining lever is shrinking the **shared state** (fewer spectral
  samples / fewer kernel params), which is a correctness/precision change —
  **out of pkg174's PERF-ONLY, correctness-frozen scope.**

### Definition-of-done status

Scene measures **1.132 s** (Lever 3, best case) — still **> 1.0 s**. The
temporary 1.5 s ceiling in `test_pkg55_perf_gate.py` is therefore **NOT
reverted** (reverting is valid only at a true ≤1.0 s — spec acceptance). Held for
owner review with this evidence: the ≤1.0 s target is not reachable under the
package's PERF-ONLY + correctness-frozen constraints, and needs an owner decision
(accept the raised ceiling, or authorize a shared-state / precision change that
leaves PERF-ONLY scope).

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

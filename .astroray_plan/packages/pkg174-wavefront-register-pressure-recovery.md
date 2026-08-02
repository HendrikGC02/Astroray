# pkg174 — wavefront register-pressure recovery: restore the ≤1.0s perf ceiling WITH the #541 correctness fix in

**Pillar:** 3 (GPU wavefront performance)
**Track:** A (RTX-gated; every measurement is hardware)
**Status:** open — dispatchable in the SUPERVISED engine-settlement round, AFTER PR #541 (option A) lands. This is the companion package that option A creates: #541 ships the correctness fix v4 with a TEMPORARY raise of the wavefront perf ceiling; this package restores the ceiling and reverts the raise.
**Estimated effort:** M (kernel-architecture work, measured at every step; no correctness surface should move)
**Depends on:** PR #541 merged (option A — owner CONFIRMED 2026-08-03). Cross-links: **pkg155** (Phase 1 conviction: shade stage 221 regs/thread, 1 block/SM, sm_120 AOT ruled out with numbers — the register problem is intrinsic to the kernel, not a build artifact; its recovery target ≤128 regs is this package's inherited north star), **pkg168** (whose #541 fix is the per-hit state that tipped the stage over), **pkg172(A)** (the epsilon fix ships in the same supervised round; run this package's final perf measurement on a build containing BOTH).

## Origin (measured facts — do not re-derive)

From #541's blocked perf gate (2026-08-02, RTX 5070 Ti; levers and A/B data
recorded in **PR #541's comment thread** and preserved commit **`6ef2c11`**):

- `stageAdvance`/`stageShadeBucketed` sit at **REG:254** (the architectural
  ceiling) — ANY added per-hit state spills (~2KB local memory observed).
- Best-correct-form (#541 v4, the lean restructured diffuse-spectral path in
  `gpu_materials.h`) renders the perf-gate scene in **1.222s vs 0.843s main**
  — correct but over the 1.0s ceiling; that is why the ceiling was
  temporarily raised at merge rather than the fix weakened.
- Levers already identified in the thread (start here, measure each in
  isolation): `__noinline__` call boundaries to fence register live-ranges;
  `__launch_bounds__` tuning on the two stages; **stage splitting** (the
  shade stage doing too many material families in one kernel — bucketed
  sub-kernels shrink the worst-case register footprint, the Laine 2013
  wavefront argument the codebase already cites from pkg55).

## Contract

1. **Baseline first:** on post-#541 main, record REG counts, spill bytes,
   occupancy (blocks/SM), and the perf-gate scene median-of-3 — the numbers
   the acceptance gate is measured against. State the `.pyd` mtime.
2. **One lever per measurement.** Each candidate (noinline fencing, launch
   bounds, stage/bucket splitting, hoisting cold paths) gets an isolated
   A/B: REG + spill + wall time. No combined "big refactor" commit without
   the per-lever ledger — register work is notoriously non-monotonic.
3. **Correctness is frozen:** wavefront output must stay bit-identical to
   pre-change wavefront output on the standard bit-identity gates (1e-5 MC
   convention where atomically accumulated — memory: wavefront is not
   run-to-run bit-exact). This package moves PERF ONLY.
4. Cite Laine, Karras & Aila 2013 ("Megakernels Considered Harmful") for
   any stage-splitting design change (CLAUDE.md §6); the repo's pkg55 docs
   already carry the citation — extend, don't re-derive.

## Acceptance

- [ ] Perf-gate scene ≤ **1.0s** median-of-3 on RTX 5070 Ti **with the #541
      correctness fix present** (and pkg172(A)'s epsilon fix if already
      merged — measure on the real settlement-round main, not a curated
      branch).
- [ ] **The temporary ceiling raise from #541 is REVERTED in this package's
      PR** — the gate goes back to its pre-#541 bound. That revert is the
      definition of done; leaving the raised ceiling in place is a FAIL
      even if the measured time improves.
- [ ] REG/spill/occupancy ledger for every lever tried (including rejected
      ones) recorded in a research note under `.astroray_plan/docs/`.
- [ ] Bit-identity/parity gates green; no material-eval code moved in ways
      that change results (REG work only).

## Scope fence

- Not a general performance round: the target is the settlement-round
  ceiling restore, not the pkg155 ~5× absolute-slowdown arc (pkg155 Phase 2
  remains its own item; hand it your occupancy ledger as intel).
- No new features into the shade stage while this is open — the stage is a
  serialization point (`stage_advance.cu` rule in NEXT_STAGE_REPORT §4).

## Provenance

Filed by the architect 2026-08-03 under the owner's engine-settlement
directive: PR #541 fork **option A confirmed by the owner** (ship
correctness v4 + temporary ceiling raise + this package). The supervised
settlement round = #541-A + pkg172(A) + this package.

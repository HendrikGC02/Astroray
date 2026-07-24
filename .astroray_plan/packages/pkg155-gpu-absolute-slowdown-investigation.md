# pkg155 — GPU render path ~5× absolute slowdown since 2026-05 (investigation)

**Pillar:** 3 (GPU pipeline health)
**Track:** A (RTX-gated — CI has no GPU; only hardware timing can drive this)
**Status:** open — filed 2026-07-25 by the pkg55-C7 day arc (owner-approved as doc-only alongside the C7 PR; no implementation today)
**Estimated effort:** M (profiling + attribution) + unknown (recovery)
**Depends on:** none. Related: pkg153 (gate-integrity disposition), pkg55-C7 (perf-gate rescope — the C7 gate measures the WF/MK *ratio*, which this absolute regression does not move because both pipelines carry the same feature cost).

## Finding (measured 2026-07-25, RTX 5070 Ti, main @ e0185c8)

Re-running the exact Phase-A kernel-profile harness (`benchmarks/wavefront_baseline.py`,
`ASTRORAY_PROFILE=1`, cornell scenes, 256², 64 spp, md 8) against the pinned
Phase-A baseline (`benchmarks/wavefront/baseline.json`, measured 2026-05-17 @
`1a3c159`, same GPU):

| Metric | Phase-A pin (2026-05-17) | 2026-07-25 | Factor |
|---|---|---|---|
| `multiwavelength_megakernel` mean ms/launch, cornell_diffuse | 19.92 | 113.03 | **5.7×** |
| `multiwavelength_megakernel` mean ms/launch, cornell_glass | 21.51 | 134.60 | **6.3×** |
| registers/thread | 125 | **188** | past the 158-reg occupancy cliff documented in Phase A.0 |

The wavefront carries the same per-λ shading feature cost (it is not a
wavefront-vs-megakernel issue: the two pipelines agree to 0.3% in output and
~1.5× in speed). The whole GPU render path — the thing the user actually
waits on — got ~5× slower per sample between 2026-05 and 2026-07.

## Suspect window (all merges touching device shading/emission/traversal)

#481 (spectral-table extraction), #484 (MIS instrumentation — production
stores now gated off in C7), #486 (naive MW / non-visible bands), #489/#500
(light-energy audit + wattage→radiance re-derivation), #490 (TLAS), #494
(photon hooks), #515 (firefly clamp), #519 (rough-transmission multiscatter
LUTs), plus material-eval growth (Disney closure-graph routing #518, Sellmeier,
etc.). The 125→188 reg growth is the aggregate of these; the occupancy loss
(Phase-A: 2 blocks/SM at 125 regs) likely amplifies the raw instruction cost.

## Contract

1. Profile-first (Nsight or `ASTRORAY_PROFILE=1` bisect): attribute the ms and
   the register growth per merge arc — build 4-6 commits across the window and
   record ms/launch + regs/thread for each (cornell_diffuse is the cheap probe).
2. Distinguish "physically necessary cost" (correct light energy, spectral
   accuracy) from "recoverable cost" (register spills, dead per-thread state,
   always-on feature branches that could be compile-time or scene-gated).
3. Deliver: a written attribution table + a recovery plan (candidate levers:
   `__launch_bounds__` tuning back under the cliff, scene-gated feature
   branches, LUT/constant-memory layout, spilled-state diet). No gate changes.
4. Hardware evidence required for every claim (CI is blind here).

## Provenance

Filed from the pkg55-C7 Phase-0 investigation (see
`.astroray_plan/docs/pkg55-c7-day-arc-2026-07-25.md` §Phase-0 and the pinned
final megakernel record `benchmarks/wavefront/megakernel_final_2026-07-25.json`).
The C7 perf-gate rescope explicitly does NOT paper over this: the C7 gate is a
WF/MK ratio; this spec owns the absolute regression.

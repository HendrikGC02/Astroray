# Overnight standup — 2026-07-24 (running)

Follows `.astroray_plan/docs/standup/2026-07-23-overnight.md`. Architect's
2026-07-24 overnight #2 dispatch plan (`b166eba`) ran three parallel lanes:
**Lane A** (serial, owns `disney.cpp`) pkg151 → pkg149 → pkg150; **Lane B**
(parallel) pkg141 GPU near-delta Disney metal; **Lane C** (parallel) pkg147
addon CPU hang. This file is live — appended on each ship event, finalized
at last call.

## Shipped so far

| PR | What | Result |
|----|------|--------|
| [#518](https://github.com/HendrikGC02/Astroray/pull/518) | pkg141 (`d3a3640`) — GPU Disney-metal closure routing fix | The closure-graph metal lobe was falling into `MetalPlugin`'s perfect-mirror shortcut instead of `gpu_disney_eval`; a stale `/(4·NdotL·NdotV)` divide was also removed from `gpu_disney_eval`. Near-delta GPU/CPU parity 2.7-4.0× → 0.60-0.77×, inside the [0.4, 2.5] band. 4 xfail rows promoted to live tests. Residual 1.3-1.7× GPU dimness → new follow-up spec **pkg152**. HW verdict: nominal-FAIL/adjudicated-mergeable — the failing gates (wavefront_diff, perf, photon-caustic SSIM) reproduce bit-deterministically on unmodified main and contain no Disney metal; ownership transferred to **pkg153**. Spec flipped to `done` post-merge (`6c4833c`) under the new pr-merger spec-flip standing rule. |

## Major finding: genuine on-hardware regressions since 2026-06-11

**gate-failure-reviewer (`ce85ad7`):** the wavefront_diff ratio gates, the
perf gate, and the photon-caustic SSIM flake that PR #518's HW run hit are
**GENUINE on-hardware regressions** (R-channel +5-6% GPU drift, perf
1.41× → 0.90×) — NOT laptop-pinned thresholds as previously suspected.
Corroborated independently by the #519 verifier run (megakernel rough-glass
R 0.978, pre-existing, unmoved by pkg151's changes). Owned by new spec
**pkg153** with bisect discriminators back to 2026-06-11.

## pkg151 negative result — Lane A re-planned

**Pre-registered falsification:** pkg151's rough-transmission multi-scatter
compensation (Cycles-glass-table port, CPU+GPU) maxes out at **~1.03× at
ior=1.5** against a faithful Cycles port — this **falsifies the premise**
that multi-scatter closes pkg149's furnace deficit. Architect re-adjudicated
(`101900b`): Lane A is rewritten — new spec **pkg154** (H1: non-cancelling
exit eta², `(1/ior²)² = 0.198` ≈ the measured 0.217 floor) now precedes
pkg149, which **stays HELD**; **pkg150 is canceled for tonight**. New specs
filed: pkg152 (pkg141 residual dimness), pkg153 (main HW regressions),
pkg154 (furnace-deficit investigation).

## Open, held for owner (like #516 last night)

- **PR #519 (pkg151)** — groundwork merge adjudicated (`101900b`); HW PASS +
  CI green, but adds an unconditional CMakeLists source-list rule. HELD by
  pr-merger pending owner morning approval.
- **PR #520 (pkg147)** — addon CPU-hang root cause found: an OpenMP worker's
  `gil_scoped_acquire` deadlocks against the GIL-holding caller at the
  parallel barrier (the deployed addon `.pyd` was safe; a dev-build-in-
  addon-dir reproduces it). Structural guard deployed; independent
  cpp-abi-guard review in progress. Also touches CMakeLists — will hold for
  owner same as #519.

## In-flight (not yet shipped)

- **pkg154** — furnace-deficit investigation, on branch
  `pkg154-furnace-deficit-investigation` (`39a5ecf` — frontFace fix for
  `roughTransmissionEval`/`Pdf`, main-safe, measured; not yet a PR).

## Process fixes tonight

1. **Tracker-drift audit** (`07ac576`, 2026-07-25) — 30 spec `Status:` labels
   normalized to their true merged/adjudicated state; identified **pkg55-C7**
   as the next supervised-day-session item.
2. **Close-round drift gate** (`8c49bbb`) — `close-round` skill gained a
   Step 0 spec-status drift check as a tracker-audit follow-up.
3. **pr-merger spec-flip standing rule** — merged PRs now get their spec's
   `Status:` line flipped by the pr-merger as part of the merge, first
   applied at `6c4833c` (pkg141). Reduces DOCS-SCRIBE's per-PR spec-flip
   load going forward.
4. **Background-build stall workaround** — a background CUDA build stalled
   mid-run tonight; the team's workaround was to force builds to run in the
   foreground for the rest of the run (reported by team-lead, no dedicated
   commit yet).

## Action items for owner

1. **Decide PR #519's CMakeLists source-list addition** (pkg151 groundwork,
   HW PASS + CI green) — approve → `gh pr merge 519 --squash`.
2. **Decide PR #520's CMakeLists touch** (pkg147 OpenMP-deadlock guard) once
   the cpp-abi-guard review lands — same approve-and-squash path.
3. Pillar-4 specs (pkg45/46/48/49/50/51/107) relabeled `paused` tonight per
   the 2026-06-08 directive — no action needed, informational only.

<!-- in progress — will be finalized at last call -->

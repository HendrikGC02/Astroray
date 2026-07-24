# Overnight standup — 2026-07-24 (08:00 → 2026-07-25 morning)

Follows `.astroray_plan/docs/standup/2026-07-23-overnight.md`. Architect's
2026-07-24 overnight #2 dispatch plan (`b166eba`) ran three parallel lanes:
**Lane A** (serial, owns `disney.cpp`) pkg151 → pkg149 → pkg150; **Lane B**
(parallel) pkg141 GPU near-delta Disney metal; **Lane C** (parallel) pkg147
addon CPU hang. Lane A was re-planned mid-run (pkg151's negative result —
see below) to pkg151 → pkg154 → pkg149, with pkg150 canceled for the night.

## Shipped (2 code merges, chronological)

| PR | What | Result |
|----|------|--------|
| [#518](https://github.com/HendrikGC02/Astroray/pull/518) | pkg141 (`d3a3640`) — GPU Disney-metal closure routing fix | The closure-graph metal lobe was falling into `MetalPlugin`'s perfect-mirror shortcut instead of `gpu_disney_eval`; a stale `/(4·NdotL·NdotV)` divide was also removed from `gpu_disney_eval`. Near-delta GPU/CPU parity 2.7-4.0× → 0.60-0.77×, inside the [0.4, 2.5] band. 4 xfail rows promoted to live tests. Residual 1.3-1.7× GPU dimness → new follow-up spec **pkg152**. HW verdict: nominal-FAIL/adjudicated-mergeable — the failing gates (wavefront_diff, perf, photon-caustic SSIM) reproduce bit-deterministically on unmodified main and contain no Disney metal; ownership transferred to **pkg153**. Spec flipped to `done` post-merge (`6c4833c`) under the new pr-merger spec-flip standing rule. |
| [#521](https://github.com/HendrikGC02/Astroray/pull/521) | pkg154 (`319df39`) — rough-transmission furnace-deficit root cause, found + fixed | **Two convicted bugs**, both measured, not argued: (H1) `roughTransmissionEval`/`roughTransmissionPdf` derived enter/exit from `rec.normal.dot(wo) > 0`, but `rec.normal` is the front-facing (ray-oriented) shading normal — provably always `>=0` regardless of true enter/exit (measured 274,809/274,809 calls read `entering=true`, incl. the 61% that were genuine exit events), so `1/etap²` never cancelled over a round trip; same bug class already fixed in `dielectric.cpp` and `photon_caustic.cu`, never ported here. (H4, new) a closure-level `clamp(0,4)` on the transmission eval truncated the low-roughness estimator's legitimate heavy tail (`D_GTR2` unbounded as α→0) — same bug class as pkg123's metal-reflection clamp fix. Combined: CPU furnace 0.11–0.82 → **0.997–0.999** across roughness {0.05,0.1,0.3,0.6,1.0} on the pkg149+pkg151 stack. Docs-only PR (patch file, not a direct main edit — avoids a `disney.cpp` conflict with unmerged #519); pkg149 applies the patch on its own branch. Spec flipped to `done` post-merge (`bd1cc89`). |

## Major finding: genuine on-hardware regressions since 2026-06-11

**gate-failure-reviewer (`ce85ad7`):** the wavefront_diff ratio gates, the
perf gate, and the photon-caustic SSIM flake that PR #518's HW run hit are
**GENUINE on-hardware regressions** (R-channel +5-6% GPU drift, perf
1.41× → 0.90×) — NOT laptop-pinned thresholds as previously suspected.
**Corroborated twice tonight** within the #519 hardware-verifier's own run:
the megakernel rough-glass R ratio measured 0.977974 on the pkg151 PR branch
and 0.978025 on a direct A/B against unmodified main, back-to-back, same
machine/seed/spp — same drift, pre-existing, unmoved by pkg151's changes
(Δ≈0.00005). Owned by spec **pkg153** with bisect discriminators back to
2026-06-11; investigation was IN FLIGHT at finalize time.

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

## Open, held for owner (like #516 last night) — all-else-green, one command each

- **PR #519 (pkg151)** — groundwork merge adjudicated (`101900b`); HW PASS +
  CI green, but adds an unconditional CMakeLists source-list rule (one line,
  `src/gpu/gpu_glass_tables.cu`). HELD by pr-merger pending owner approval →
  `gh pr merge 519 --squash`.
- **PR #520 (pkg147)** — addon CPU-hang root cause found: an OpenMP worker's
  `gil_scoped_acquire` deadlocks against the GIL-holding caller at the
  parallel barrier (the deployed addon `.pyd` was safe; a dev-build-in-
  addon-dir reproduces it). Structural guard deployed, independent
  cpp-abi-guard review SIGNED OFF, headless-Blender smoke green, CI green.
  Also touches CMakeLists (an OpenMP-guard define) — HELD by pr-merger same
  as #519 → `gh pr merge 520 --squash` once approved.

## Draft / blocked

- **PR #522 (pkg149 stack, draft)** — CPU contract **FULLY MET**: rough-glass
  furnace 0.997–0.999 across the grid, transmission peak alignment 0.45°
  (gate <2°), the azimuth-swap root cause (`670e583`) closed. **GPU leg
  merge-blocked**: after the signed-off frontFace/TIR fix (`e0fe9d8`) the
  hardware-verifier re-measured the GPU furnace gate and found R=0.6/1.0
  recovered (0.896/1.0, up from 0.571/0.971) but **R=0.1/0.3 essentially
  unchanged** (0.130/0.283 vs gate [0.90, 1.06]) — HW FAIL recorded twice
  (`19d4e9f`, then `e0fe9d8`). A second, low-roughness-dominant GPU-only
  Disney defect remains, tracked as pkg152-adjacent; #522 stays draft until
  that's convicted and the GPU furnace gate re-passes. `test_chi2_disney_glass[0.3-45]`
  stays xfail, re-attributed solely to pkg150 (VNDF reflection-candidate
  masking) now that pkg149's own azimuth-swap root cause is closed.

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
4. **Background-build stall workaround** — the subagent background-task
   stall bug fired approximately 6 times tonight; the team's workaround was
   to force builds to run in the foreground for the rest of the run (agent
   memory updated: foreground-only rule).
5. **pr-merger stash-drop lane violation** — the pr-merger dropped a stash
   touching the live orchestrator ledger file; the content was verified
   identical before the drop (no data loss), but this crossed a lane
   boundary and is flagged so it isn't repeated.

## Next-run queue

Architect's last-call wind-down (`413bf81`): **pkg152 promoted to head the
next run's queue**, scope widened to the full GPU Disney-twin divergence
(metal residual dimness from #518 + the #522 low-roughness rough-transmission
furnace deficit — one shared instrumentation harness convicts both, with an
explicit split-clause if they prove unrelated). Ordered queue: **pkg152 →
#519/#520/#522 merge cascade (owner approvals first, stack order, #522
last) → pkg150 re-baseline → pkg153 bisect arc.** `NEXT_STAGE_REPORT.md`
carries the same banner. pkg149's spec `Status:` line reflects the #522
draft/blocked state; pkg152's spec carries the full `e0fe9d8` evidence
table and compounding-masking analysis.

## Action items for owner

1. **Approve PR #519** (pkg151 groundwork, one-line CMakeLists source add,
   HW PASS + CI green) → `gh pr merge 519 --squash`.
2. **Approve PR #520** (pkg147 OpenMP-guard CMakeLists define, ABI SIGN-OFF +
   headless-Blender smoke green + CI green) → `gh pr merge 520 --squash`.
3. **PR #522 (pkg149 stack)** rebases onto merged #519 next, but stays
   blocked on the GPU low-roughness defect (pkg152 arc) — this is the next
   run's top pickup, not an owner action tonight.
4. **Morning HTML report:** `test_results/overnight_report_2026-07-24/overnight_report.html`
   (being built as of finalize time).
5. **Task Scheduler orchestrator task** — re-enable at shutdown if scheduled
   ticks should resume.
6. Pillar-4 specs (pkg45/46/48/49/50/51/107) relabeled `paused` tonight per
   the 2026-06-08 directive — no action needed, informational only.

<!-- finalized -->

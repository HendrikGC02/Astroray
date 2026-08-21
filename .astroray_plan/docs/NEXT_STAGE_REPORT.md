# Astroray Next Stage Report

**Date:** 2026-08-21 (mid-round refresh — NOT a round closeout: PR #629 is
open/HW-FAIL and pkg206 is actively in progress. 6 PRs merged since the
2026-08-15 report, #624–#628, on top of the 2026-08-14 → 2026-08-15 round
below).
**Prepared by:** docs closeout pass (evidence: `git log`, `gh pr list`,
package spec Status lines).
**Scope:** 1 open PR (#629, sodium-vapor fix, HW FAIL — fix in progress on
branch `pkg214fix`), pkg206 re-dispatched in progress (branch
`pkg206impl*`). Full detail: `.astroray_plan/docs/STATUS.md` (top entry
"2026-08-19 → 2026-08-21"), `.astroray_plan/docs/ROADMAP.md` ("Current
sequencing" unchanged — no new owner directive since 2026-08-03).

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md).

**Still open from the prior report: a FRESH ARCHITECT-LED planning pass.**
The owner's 2026-08-15 request for the architect to plan ahead (review the
full open pool, sequence dependencies, size work) before dispatching more
implementers has not yet been acted on — the intervening work (pkg203-206,
pkg212-214) was picked up ad hoc. Treat §2 below as input to that planning
pass, not a queue to execute mechanically.

---

## 1. Current state (one screen)

- **The Integration Milestone stays fully closed** (unchanged). Work since
  the 2026-08-15 report closed pkg200's last filter honour row and the
  pkg198 volume-pass limitation, added a light-intensity UI control, and
  is mid-fix on a spectral-lamp regression.
- **Landed since the last report (6 PRs, #624–#628):** pkg203 (Cycles-
  accurate pixel-filter width→σ mapping, CPU+GPU, PR #624, closes pkg200's
  last filter HONEST-FAIL row), pkg204 (GPU wavefront volume-pass direct/
  indirect split, PR #625, closes the pkg198 Stage-2 limitation), pkg205
  (UnicodeEncodeError console-test hygiene, PR #626, test-only), pkg213
  (light intensity/Power slider exposed in the Astroray panel, PR #628,
  UI-surfacing only).
- **Open, HW FAIL — top priority pickup:** **pkg214** (PR #629, sodium-
  vapor emission fix). The D-doublet broadening (black→amber) works, but
  the shared `mat_ls` peak-normalisation mechanism regressed
  `mercury_vapor` ~4.5–8.6× too bright. A physics-correct energy-
  normalisation fix is IN PROGRESS on branch `pkg214fix` — **finish and
  re-verify this before picking up anything else that touches
  `build_spectral_profiles.py` or the spectral-lamp path** (overlaps
  pkg206's sampler work only at the "don't touch the same files
  concurrently" level, not logically).
- **In progress, released from hold:** **pkg206** (luminance-weighted
  hero-wavelength importance sampling). Its first attempt, PR #627, was
  CLOSED CI-red/biased — `test_flat_baseline_ssim` failed from a stacked
  realization-change + genuine achromatic-flat green-cast bias (companion
  wavelengths not divided by the importance density at their own λ). The
  owner released the bias-hold 2026-08-21; re-dispatched fresh on branch
  `pkg206impl*` with the triage's per-wavelength-pdf correction (spec's
  2026-08-21 triage section has the full root-cause + distinguishing
  diagnostic for the next attempt).
- **pkg200's honour matrix is now fully closed on its filter-related
  rows.** Of its original 13 HONEST-FAIL rows, pkg201 closed 3
  (`world_max_bounces`, `film_transparent`, `filter_width`) and pkg203
  closed the 4th (`pixel_filter_type`). Remaining rows: per-type bounce
  counts (Finding A), `filter_glossy` (Finding C), native caustic toggles
  (Finding E) — all register-hostile, deferred to pkg201 Stage 3; and
  `film_transparent_glass` (F-glass), reclassified as an unfiled new-
  feature follow-up.
- **Open, not blocking, carried forward:** pkg201 Stage 3 (per-type
  bounce counters + `filter_glossy` + native caustic toggles —
  register-hostile, probe-gated, register-contention window is clear),
  pkg131 (zero-knob adaptive sampling, wavefront leg, long-standing), the
  F-glass (`film_transparent_glass`) world-through-glass compositing
  follow-up (not yet filed), the CPU legacy-hittable delta-sun
  `isDelta`/MIS gap (pkg202's fix sidesteps it for the sun case only),
  the caustic-integrator/CPU-wavefront-reference world-volume gap (open
  since pkg199 Stage 1), the durable `GLoweredMaterial` by-value-copy fix
  (still prototyped, uncommitted, worktree `sad-maxwell-ff99d1`), pkg180
  (systemic-dim diagnosis, still open).
- **Still standing, unresolved — TOP STRATEGIC ITEM:** the **Pillar 4
  unpause decision** (pkg45/46/48/49/50/51 + pkg107, GR/astro science
  layer). No new owner directive since 2026-08-03; ROADMAP.md's PAUSED
  marker is unchanged. This has now stood unresolved across many round
  closeouts — surface it explicitly before any further
  Integration-Milestone-tail dispatch.
- **Environment:** RTX 5070 Ti workstation; Blender 5.1/5.2 installed
  locally (real-host checks mandatory for addon-facing PRs). Every landed
  PR this window was dual-gated (CI + independent RTX hardware
  verification); pkg214 (#629) is the one PR that came back HW FAIL and is
  mid-fix, not yet re-verified.

---

## 2. Deployable set (prioritized)

Grep `^\*\*Status:\*\*` in each spec before dispatch (memory
`orchestrator-next-stage-report-stale`) — this report can go stale. This
list is INPUT to the requested fresh architect planning pass, not a queue
to execute mechanically (see the owner request banner above).

**In-flight, finish before picking up anything new:**

1. **pkg214fix** — finish the physics-correct energy-normalisation fix on
   branch `pkg214fix` (PR #629 is HW FAIL, do not merge as-is). Re-verify
   sodium (amber, unchanged) AND mercury (back within its pre-fix MC-noise
   band) together before closing.
2. **pkg206** — luminance-weighted hero-wavelength importance sampling,
   re-dispatched on branch `pkg206impl*` with the per-wavelength-pdf
   correction from the 2026-08-21 triage. Re-verify the flat-baseline SSIM
   gate specifically (the prior attempt's failure mode) alongside the
   convergence-win and unbiasedness gates in the spec.

**Top candidate — needs an explicit owner decision, not a silent dispatch:**

3. **Pillar 4 unpause** (pkg45/46/48/49/50/51 + pkg107, GR/astro science
   layer). Unchanged across multiple rounds now — ROADMAP.md's PAUSED
   marker has stood since 2026-06-08; still no explicit go-ahead.
   **Surface this to the owner before dispatching any pkg45-tier work or
   further Integration-Milestone-tail items.**

**Integration-Milestone-tail / settings-honour closure, highest signal in
the open pool:**

4. **pkg201 Stage 3** — per-type bounce counters (Finding A),
   `filter_glossy` (Finding C), native caustic toggles (Finding E,
   reclassified from Stage 2). Register-hostile — MUST clear the
   up-front cuobjdump probe per item before any feature code (same
   discipline as pkg198/pkg199/pkg204). The register-contention window
   is clear — dispatchable, but size it as its own session (3
   register-hostile items, each may park independently).
5. **pkg131** — zero-knob adaptive sampling, wavefront leg. Long-standing
   open item, no new blockers.

**Hygiene / follow-up (not yet filed as a dedicated spec):**

6. **F-glass (`film_transparent_glass`) world-through-glass compositing**
   — reclassified out of pkg201 Stage 2 as a genuine new feature (glass
   must show the background through it, changing beauty RGB, not just an
   alpha copy-back). File a spec before dispatching.
7. **CPU legacy-hittable delta-sun `isDelta`/MIS gap** — pkg202's
   upload-time conversion sidesteps this for GPU sun rendering, but the
   underlying legacy non-dedicated-light MIS treatment (CPU side) is
   still unaddressed for other legacy hittable-light types. Diagnosis-
   first; confirm scope before filing.
8. **Caustic-integrator/CPU-wavefront-reference world-volume gap** — fog
   is invisible to the caustic integrator and the CPU wavefront reference
   (pkg199 Stage 1 documented non-goal, still open). One-liner candidate:
   either extend those two paths to read `c_worldVolume`, or document the
   limitation user-facing if extending is out of scope for now.
9. **Durable `GLoweredMaterial` by-value-copy fix** — re-apply the
    prototyped PR-2-based fix from worktree
    `.claude/worktrees/sad-maxwell-ff99d1` on settled main. File a
    dedicated spec if picked up (recurring-leak pattern is evidence
    enough for a CLAUDE.md §6-citable structural fix).

**Re-entered / long-tail pool (still genuinely low priority):**

10. **pkg180** — systemic Astroray-vs-Cycles dim, diagnosis-first, still
    open dispatchable.
11. **pkg173** — bounce-1 geometry-sampling parity (pkg172 effect (B));
    holds pkg156's 0.998 SSIM restoration clause.
12. **pkg153** — wavefront_diff remainder, gate-failure-reviewer
    disposition in flight.
13. **pkg155 Phase 2** — shade-stage register recovery (221 regs/thread →
    ≤128 target); opportunistic GPU-lock gap-filler, not compile-only.
14. **pkg128** — thin-film residual charter (standalone Glass/Metallic
    node cells + spectral showcase), rides the shared Belcour-Barla
    utility pkg178/pkg182 already built.
15. **pkg165** — verify-and-close. A focused confirm on pkg158's exact
    Step-0 scene at r ∈ {0.0, 0.3, 0.6, 0.9} closes the paperwork; every
    existing reading is already in-band. Trivial, non-urgent.

**Not this phase:** anything not explicitly named above; Pillar 4 stays
PAUSED until the owner go-ahead in item 1 above.

---

## 3. Drop-in prompt for the next session

**First: finish and re-verify the two in-flight items** (1–2) — pkg214fix
(mercury regression) and pkg206 (bias re-fix) both have work already
started; landing them is higher-value than starting anything new. **Then
get the owner's read on Pillar 4 unpause** (item 3) — a milestone-scale
sequencing decision, not a code dispatch, and it has now stood unresolved
across multiple rounds. **Then run the fresh architect-led planning pass
the owner requested 2026-08-15** — review the full open pool (this report
§2, STATUS.md, and any specs filed since), sequence dependencies, and size
sessions explicitly before dispatching, rather than picking items off this
list mechanically.

If the architect's plan confirms this pool as reasonable: **pkg201 Stage 3
(item 4)** is the next-highest-signal item after the in-flight pair, but
needs its own session (register-hostile, 3 independently-parkable
sub-items, probe-first per item). pkg131 (item 5) has no blockers if a
smaller pickup is wanted. Items 6–9 are hygiene/follow-up work that need a
spec filed before dispatch (F-glass compositing, the legacy-light MIS gap,
the caustic/fog gap, the `GLoweredMaterial` fix). Items 10–15 are the
long-tail pool, in roughly that priority order.

Rules that stay live from this round: **energy gates render LINEAR with an
upper bound** (pkg166); **state the `.pyd` mtime next to every probe A/B
number**; **verify `cuobjdump` resource-gate readings against the TRUE
compiled arch, not the CMakeCache line** (pkg183's `arch-verify` gate
catches this automatically); **mirror the CONDITION, not just the term, in
every CPU→GPU port**; **CPU/GPU material work is byte-mirrored in the same
PR, never split across sessions**; **any new lobe/closure/kernel axis that
touches the shade path must be measured against the
`template<bool HasPrincipled>` / `template<bool HasPhotons>` /
`template<bool HasWorldScatter>` / `template<bool HasLightPassAOVs>`
isolation boundaries**; **eval and pdf must use the SAME functional form
for the same NDF** (the pkg182 class of bug); **never trust a CSV/CLI
deliverable's own claimed numbers — re-run the documented command verbatim
and read the actual output**; **grep the spec for git-archaeology before
trusting an inherited premise** (pkg199's "the CPU already has this" claim
was false); **occlusion-sentinel distances (1e30) are not geometric
distances — never feed one into a Beer-Lambert/absorption term** (pkg199
Stage 1's HW-611 class of bug); **register-hostile work needs an up-front
cuobjdump probe before any feature code, per item if multiple items share
a spec** (pkg198/pkg199/pkg201-Stage-3 discipline). Cite per CLAUDE.md §6
(`/cite-algorithm`) for any new algorithm.

---

## 4. Coordination

- **One PR per package**, doc-only closeouts auto-merge on green CI
  (pr-reviewer doc-only rule). Source PRs need the independent-review
  SIGN-OFF/BLOCK gate (pkg98) before push.
- **`src/gpu/wavefront/stage_advance.cu` / `stage_init.cu` / the shade
  kernel are serialization points** for any GPU-lane package (pkg201
  Stage 3, pkg131, a Pillar-4 GPU package, etc.) — check for other
  in-flight touches before dispatching. The pkg198/pkg199 register-
  contention window that blocked pkg201 Stage 3 is now clear (both
  landed this round), but confirm no new contender has appeared.
- **CI is blind to GPU correctness** — never declare a round clean on CI
  green alone; run the full RTX hardware sweep at closeout (memory:
  `ci_has_no_gpu_runtime_blindspot`).
- **`apply_gamma=True` cannot detect energy GAIN** — render energy gates
  linear with floor+ceiling (memory:
  `gamma-furnace-cannot-detect-energy-gain`).
- **Addon-facing PRs need a real-Blender leg** — `dev_addon.ps1 -Smoke`
  (pkg175) is the standing mechanism; gate on the printed sentinel, not
  the exit code.
- **The GPU wavefront is NOT run-to-run bit-exact** (~1.19e-07–2e-7
  atomic floor) — gate at the 1e-5 Monte-Carlo convention, not exact
  equality.
- **Watch the shadow-`.pyd` trap** — verify `astroray.__file__` resolves
  to the canonical build output and check `.pyd` mtime vs HEAD (memory:
  `stale_pyd_locations`).
- **Watch the stale-CMakeCache CUDA-arch trap** — the cache line can lie;
  trust `cuobjdump --list-elf` on the linked `.pyd`, which pkg183's
  `arch-verify` gate now does automatically in all three build wrappers.
- **CLI/script deliverables need the documented command re-run verbatim,
  not the PR's own claimed numbers trusted.**
- **Grep `^Status:` (or `**Status:**`) in the spec before dispatching** —
  this report's §2 prose can go stale vs the spec header (memory:
  `orchestrator-next-stage-report-stale`).
- **Cite papers/reference repos per CLAUDE.md §6** for any new algorithm.
- **Cost routing (2026-08):** bounded grunt work (docs flips, lint fixes,
  report assembly, pre-review critique, well-specified gated
  implementation) routes to the `delegate` skill's open-weight tiers,
  evidence-verified, never trusted. Claude stays on architect/specs,
  cycles-parity, ABI reachability, gate-failure root-cause, merge
  decisions, and visual inspection.

---

## 5. After the round

- Flip landed spec `Status:` lines to `done (PR #N, date — headline
  numbers)`.
- Update STATUS.md (new round section + next pickup queue), ROADMAP.md
  (round-closeout entry; "Current sequencing" only changes on a new owner
  directive), and rewrite this report's §1/§2 for the next round.
- Run the RTX hardware sweep; record the full test-suite state.
- Do not bulk-promote flaky xfails on a lucky run.
- Open ONE doc PR (or direct doc-only commit per repo rule) for the
  closeout.

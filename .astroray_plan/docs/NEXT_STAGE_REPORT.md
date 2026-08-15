# Astroray Next Stage Report

**Date:** 2026-08-15 (round closeout — 9 PRs merged, #615–#623, on top of the
2026-08-13 → 2026-08-14 round below).
**Prepared by:** the architect (round closeout).
**Scope:** no open PRs at time of writing. Full detail:
`.astroray_plan/docs/STATUS.md` (top entry "2026-08-14 → 2026-08-15 (round
closeout...)"), `.astroray_plan/docs/ROADMAP.md` ("Current sequencing"
unchanged — no new owner directive this round, but see the owner request
below).

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md).

**OWNER REQUEST for next session: a FRESH ARCHITECT-LED run.** The owner
has asked that the next session start with the architect planning ahead
(reviewing the full open pool, sequencing dependencies, sizing work) before
dispatching implementers, rather than picking up ad hoc from this report's
tail pool. Treat §2 below as input to that planning pass, not a queue to
execute mechanically.

---

## 1. Current state (one screen)

- **The Integration Milestone stays fully closed** (unchanged this round).
  This round's work continues closing the milestone's self-generated
  follow-up pool: the pkg200 F12 pixel-honour matrix and its pkg201
  GPU-plumbing closures, plus GPU wavefront capability parity (full HG
  scattering/god-rays, light-path AOV passes) and a legacy-importer
  correctness fix.
- **Landed this round (9 PRs, #615–#623, no open PRs at closeout):**
  pkg190 follow-up (Object-coord bake guard, PR #615, HW PASS), pkg200
  (F12 pixel-honour matrix, PR #616, 8 PASS/13 HONEST-FAIL/2 NEEDS-VISUAL/2
  LIMITATION), pkg199 Stage 2 CPU (PR #617) + GPU (PR #619) — full HG
  scattering both backends, god-ray parity [1.0044, 0.9972, 0.9978],
  pkg201 Stage 1 (PR #618, world_max_bounces + use_light_tree honoured),
  pkg198 Stage 2 probe (PR #620, PROCEED) + full mirror (PR #622,
  sum-to-beauty exact — **pkg198 now COMPLETE**), pkg202 (legacy sun GPU
  fix, PR #621, 0.0→0.6333), pkg201 Stage 2 (PR #623, 2-of-6 rows shipped:
  transparent-film alpha — first implementation anywhere — and
  filter_width).
- **Zero HW FAIL cycles this round** — every landed code PR reported HW
  PASS on the first independent verification (contrast with the prior two
  rounds, which each had 2 FAIL→fix→PASS cycles). Two register-gate
  probes (pkg198 Stage 2, folded into pkg201's ordering discipline) both
  cleared PROCEED before implementation started.
- **pkg200's honour matrix is now the reference gap-list for the GPU
  wavefront's settings-honour work.** Of its 13 HONEST-FAIL rows, pkg201
  has closed 3 (`world_max_bounces`, `film_transparent`, `filter_width`)
  and reclassified 2 more with evidence (`pixel_filter_type` → pkg203 is
  a σ-mapping shortfall, not unwired; `caustics_reflective`/
  `caustics_refractive` → genuinely register-hostile, deferred to Stage
  3). **8 rows remain untouched**: the per-type bounce counts (Finding A),
  `filter_glossy` (Finding C), and `film_transparent_glass` (F-glass,
  reclassified as a new-feature follow-up, not a plumbing gap).
- **Specs filed this round, disposition:** **pkg203** (Cycles-accurate
  pixel-filter width→σ mapping, CPU+GPU parity) is filed and **now
  dispatchable** — its dependency (pkg201 Stage 2) merged this round.
- **Open, not blocking, carried forward:** pkg201 Stage 3 (per-type bounce
  counters + `filter_glossy` + native caustic toggles — register-hostile,
  probe-gated, ordering-locked behind pkg198/pkg199's register-contention
  window which is now clear since both landed), pkg203 (filter σ parity,
  open above), pkg131 (zero-knob adaptive sampling, wavefront leg,
  long-standing), the F-glass (`film_transparent_glass`) world-through-
  glass compositing follow-up (a genuine new feature, not yet filed),
  the CPU legacy-hittable delta-sun `isDelta`/MIS gap (pkg202's fix
  sidesteps it for the sun case via upload-time conversion, but the
  underlying legacy non-dedicated-light MIS treatment is unaddressed),
  pkg198's volume-pass direct/indirect split (documented limitation,
  deferred in #622), the caustic-integrator/CPU-wavefront-reference
  world-volume gap (still open from the pkg199 Stage 1 round), the
  durable `GLoweredMaterial` by-value-copy fix (still prototyped,
  uncommitted, worktree `sad-maxwell-ff99d1`), pkg180 (systemic-dim
  diagnosis, still open).
- **New hygiene item this round:** 3 pre-existing test failures throw
  `UnicodeEncodeError` printing π/✓/λ console artifacts under the default
  cp1252 Windows console encoding — a test-harness bug (force UTF-8
  stdout or drop the glyphs), not an engine defect. Cheap, low-priority,
  file before dispatching if picked up.
- **Still standing, unresolved — TOP STRATEGIC ITEM:** the **Pillar 4
  unpause decision** (pkg45/46/48/49/50/51 + pkg107, GR/astro science
  layer). No new owner directive this round; ROADMAP.md's PAUSED marker
  is unchanged. This has now stood unresolved across multiple round
  closeouts — surface it explicitly at the start of the next
  architect-led session, before any further Integration-Milestone-tail
  dispatch.
- **Environment:** RTX 5070 Ti workstation; Blender 5.1/5.2 installed
  locally (real-host checks mandatory for addon-facing PRs). Every code PR
  this round was dual-gated (CI + independent RTX hardware verification);
  zero PRs required a fix-and-re-verify cycle before merge.

---

## 2. Deployable set (prioritized)

Grep `^\*\*Status:\*\*` in each spec before dispatch (memory
`orchestrator-next-stage-report-stale`) — this report can go stale. This
list is INPUT to the requested fresh architect planning pass, not a queue
to execute mechanically (see the owner request banner above).

**Top candidate — needs an explicit owner decision, not a silent dispatch:**

1. **Pillar 4 unpause** (pkg45/46/48/49/50/51 + pkg107, GR/astro science
   layer). Unchanged across multiple rounds now — ROADMAP.md's PAUSED
   marker has stood since 2026-06-08; still no explicit go-ahead.
   **Surface this to the owner at the top of the next session, before
   dispatching any pkg45-tier work or further Integration-Milestone-tail
   items.**

**Integration-Milestone-tail / settings-honour closure, highest signal in
the open pool:**

2. **pkg203** — Cycles-accurate pixel-filter width→σ mapping, CPU+GPU
   parity. Dependency (pkg201 Stage 2) landed this round — dispatchable
   now. Closes pkg200's last filter-related HONEST-FAIL row. S–M, cite
   Cycles' `film.cpp` filter tables per CLAUDE.md §6 before writing code.
3. **pkg201 Stage 3** — per-type bounce counters (Finding A),
   `filter_glossy` (Finding C), native caustic toggles (Finding E,
   reclassified from Stage 2). Register-hostile — MUST clear the
   up-front cuobjdump probe per item before any feature code (same
   discipline as pkg198/pkg199). The register-contention window
   (pkg198 Stage 2, pkg199 Stage 2) that blocked this is now clear —
   dispatchable, but size it as its own session (3 register-hostile
   items, each may park independently).
4. **pkg131** — zero-knob adaptive sampling, wavefront leg. Long-standing
   open item, no new blockers.

**Hygiene / follow-up (not yet filed as a dedicated spec):**

5. **F-glass (`film_transparent_glass`) world-through-glass compositing**
   — reclassified out of pkg201 Stage 2 as a genuine new feature (glass
   must show the background through it, changing beauty RGB, not just an
   alpha copy-back). File a spec before dispatching.
6. **CPU legacy-hittable delta-sun `isDelta`/MIS gap** — pkg202's
   upload-time conversion sidesteps this for GPU sun rendering, but the
   underlying legacy non-dedicated-light MIS treatment (CPU side) is
   still unaddressed for other legacy hittable-light types. Diagnosis-
   first; confirm scope before filing.
7. **pkg198 volume-pass direct/indirect split** — documented limitation
   in #622 (in-scatter routed to `PASS_VOLUME_INDIRECT` only). Small,
   well-scoped follow-up if picked up.
8. **Caustic-integrator/CPU-wavefront-reference world-volume gap** — fog
   is invisible to the caustic integrator and the CPU wavefront reference
   (pkg199 Stage 1 documented non-goal, still open). One-liner candidate:
   either extend those two paths to read `c_worldVolume`, or document the
   limitation user-facing if extending is out of scope for now.
9. **3 UnicodeEncodeError console-artifact test failures** (cp1252 vs
   π/✓/λ in `print()`) — hygiene, not a regression. Cheap fix (force
   UTF-8 stdout or drop the glyphs), file before dispatching.
10. **Durable `GLoweredMaterial` by-value-copy fix** — re-apply the
    prototyped PR-2-based fix from worktree
    `.claude/worktrees/sad-maxwell-ff99d1` on settled main. File a
    dedicated spec if picked up (recurring-leak pattern is evidence
    enough for a CLAUDE.md §6-citable structural fix).

**Re-entered / long-tail pool (still genuinely low priority):**

11. **pkg180** — systemic Astroray-vs-Cycles dim, diagnosis-first, still
    open dispatchable.
12. **pkg173** — bounce-1 geometry-sampling parity (pkg172 effect (B));
    holds pkg156's 0.998 SSIM restoration clause.
13. **pkg153** — wavefront_diff remainder, gate-failure-reviewer
    disposition in flight.
14. **pkg155 Phase 2** — shade-stage register recovery (221 regs/thread →
    ≤128 target); opportunistic GPU-lock gap-filler, not compile-only.
15. **pkg128** — thin-film residual charter (standalone Glass/Metallic
    node cells + spectral showcase), rides the shared Belcour-Barla
    utility pkg178/pkg182 already built.
16. **pkg165** — verify-and-close. A focused confirm on pkg158's exact
    Step-0 scene at r ∈ {0.0, 0.3, 0.6, 0.9} closes the paperwork; every
    existing reading is already in-band. Trivial, non-urgent.

**Not this phase:** anything not explicitly named above; Pillar 4 stays
PAUSED until the owner go-ahead in item 1 above.

---

## 3. Drop-in prompt for the next session

**First: get the owner's read on Pillar 4 unpause** (item 1) — a
milestone-scale sequencing decision, not a code dispatch, and it has now
stood unresolved across multiple rounds. **Second: run the fresh
architect-led planning pass the owner requested** — review the full open
pool (this report §2, STATUS.md, and any specs filed since), sequence
dependencies, and size sessions explicitly before dispatching, rather than
picking items off this list mechanically.

If the architect's plan confirms this pool as reasonable: **pkg203 (item
2) is the standout quick pickup** — its blocker cleared this round, it's
S–M, and it closes the last filter-related pkg200 gap. **pkg201 Stage 3
(item 3)** is the next-highest-signal item but needs its own session
(register-hostile, 3 independently-parkable sub-items, probe-first per
item). pkg131 (item 4) has no blockers if a smaller pickup is wanted.
Items 5–10 are hygiene/follow-up work that need a spec filed before
dispatch (F-glass compositing, the legacy-light MIS gap, the volume-pass
split, the caustic/fog gap, the UnicodeEncodeError tests, the
`GLoweredMaterial` fix). Items 11–16 are the long-tail pool, in roughly
that priority order.

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

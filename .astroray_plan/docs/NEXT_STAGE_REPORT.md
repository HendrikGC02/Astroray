# Astroray Next Stage Report

**Date:** 2026-08-03 (§1/§2/§3 rewritten by the architect to encode the
owner's course-correction directive after the 2026-08-01→02 run: settlement
round → Integration Milestone → Pillar 4)
**Revision 2026-08-07 (hygiene run):** #541 status and pkg174 numbers
updated in place — #541 MERGED 2026-08-06 (`bbf2d8c`); pkg174 baseline is
1.156s on the new toolchain (see the pkg174 spec's 2026-08-07 addendum).
**Prepared by:** the architect (goal-capture, owner directive 2026-08-03).
**Scope:** the run closed at `31bd722` (11 PRs merged 2026-08-01/02; standups
`2026-08-01-overnight.md` + `2026-08-02-dayrun.md` are authoritative for the
detail). The correctness cascade is one supervised round from settled. **The
owner has re-sequenced what comes after it: rigorous Blender/DCC integration
is the next milestone, BEFORE Pillar 4 and ABOVE the sub-percent parity
tail.** ROADMAP.md "Current sequencing" carries the same directive.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

- **2026-08-01/02 run: 11 PRs merged.** 5 real defects fixed (pkg163
  colour-space seam, pkg120 naive-mode regression, pkg169's three
  transmission bugs, pkg170's opaque-Disney 2× gain, pkg168's diffuse
  upsample-shape bug), 2 convicted-not-yet-fixed (pkg172 effect (A),
  pkg173). pkg150/pkg158/pkg166 closed; pkg165–pkg173 filed; pkg129
  narrowed.
- **PR #541 (pkg168 Step 2) SHIPPED 2026-08-06 (`bbf2d8c`) — option A
  executed as decided** (correctness v4 + temporary ceiling raise
  1.0→1.5s). The register-pressure companion is **pkg174** (REG:254 on
  `stageAdvance`/`stageShadeBucketed`; acceptance = ≤1.0s WITH the fix in,
  then the ceiling raise reverts). **Baseline correction (2026-08-07,
  measured):** the current-toolchain baseline is **1.156s** — the old
  "1.222s vs 0.843s main" figures predate the Ninja/CUDA-12.8/native-sm_120
  switch and are not comparable; the pin's 0.705s is pre-feature-accretion
  history, not a target (see pkg174 spec addendum). pkg174 dispatched
  2026-08-07, in flight.
- **The owner's directive (2026-08-03), verbatim anchors:** first finish
  the last ~10% of the foundation (the supervised settlement round); then
  — before Pillar 4 — rigorous Blender integration: *"the purpose of
  mimicking Cycles was to be able to use as much of the existing options
  and settings in Blender as the steering wheel for this engine"* (the
  current ground-up addon UI is the wrong direction), and *"building the
  addon, installing, launching, and testing it for me is far too much
  work"* (the dev loop must become one command). Generalize: Blender is
  the first target, not the only one. The engine is nearly usable — the
  owner wants to USE it to verify it does what they want. **Integration
  IS the milestone.**
- **New milestone specs filed 2026-08-03:** pkg174 (register pressure),
  pkg175 (one-command dev loop), pkg176 (Blender-native steering wheel,
  staged, retires the custom UI), pkg177 (DCC-generalization tradeoff
  study — native plugin vs session layer vs Hydra delegate; research note
  `dcc-integration-research-2026-08.md`). pkg119 Phases B/C re-scoped as
  the milestone's verification layer; pkg88-D deferred below the
  milestone.
- **De-prioritized (owner-endorsed):** the sub-percent parity tail —
  pkg173 and the pkg153 remainder — sits below the Integration Milestone
  unless the paper requires bit-level parity. pkg153's reviewer finishes
  its disposition; no new fix packages spawn from it ahead of the
  milestone.
- **Environment:** RTX 5070 Ti workstation; Blender 5.1 installed locally
  (real-host checks are mandatory for addon-facing PRs — they caught
  pkg88-A/B where every mocked-`bpy` suite missed). Pillar 4 stays PAUSED
  until after the milestone.

---

## 2. Deployable set (prioritized — directive ordering 2026-08-03)

Grep `^Status:` in each spec before dispatch (memory
`orchestrator-next-stage-report-stale`).

**Phase (a) — supervised engine-settlement round (FIRST; one round, owner
present):**

1. ~~**PR #541 option A**~~ — **DONE 2026-08-06** (`bbf2d8c`; pkg168
   closed on merge). Owner decision recorded in the pkg168 spec; do not
   re-litigate the fork.
2. **pkg172 effect (A)** — the universal `f/(pdf+1e-3)` epsilon fix
   (guarded-pdf rejection form, pbrt-v4, cited) + impact sweep +
   coordinated re-pin batch, architect sign-off per pin. SUPERVISED —
   every diffuse bounce brightens ~0.63%; wrong package to run unattended.
3. **pkg174** — register-pressure recovery: restore the ≤1.0s ceiling with
   the #541 fix in, revert the temporary raise (the revert is the
   definition of done). Levers pre-identified in #541's thread.

**Phase (b) — Integration Milestone (immediately after settlement):**

4. **pkg175** — one-command dev loop (build→install→launch→smoke,
   headless-testable). First milestone package; everything else iterates
   through it. *(Branch `pkg175-dev-loop` was created 2026-08-03 but is
   stalled at 0 commits — resume or GC before re-dispatching.)*
5. **pkg177** — DCC-architecture tradeoff study. Parallel-safe with
   pkg175 (no code surface shared); produces the owner decision record.
   *(Same: branch `pkg177-dcc-arch-eval` stalled at 0 commits since
   2026-08-03.)*
6. **pkg176** — Blender-native steering wheel (staged: mapping table →
   settings plumbing → panel adoption → world/light/camera completion →
   custom-UI retirement). Stage 0's mapping table is an owner-review
   artifact.
7. **pkg119-B/C** — differential harness + graceful degradation, gating
   each pkg176 stage (re-scoped Status in the spec).

**Opportunistic / backlog (second-lane fillers only, never displacing the
milestone):** pkg165 (S diagnosis, feeds the parity-band decision), pkg129
narrowed (live-Cycles A/B), pkg167 (dielectric reflection multiscatter —
research note already on disk), pkg171 (CPU-only-integrator guard),
pkg88-D (wavefront motion, deferred), pkg155 Phase 2 (GPU-lock gap-filler).

**Explicitly below the milestone (owner-endorsed):** pkg173, pkg153
remainder — sub-percent parity tail; re-enter after the milestone or if
the paper demands bit-parity.

**Not this phase:** Pillar 4 (pkg45/46/48/49/50/51 + pkg107) — unpauses
AFTER the Integration Milestone, per the directive's sequencing (c).

**Standing decisions owed to the owner (carried):** project-wide GPU/CPU
parity-band tightening (pkg160/163/165/129 feed it); deleting dead
`stage_shade_metal.cu`; the two flaky xfails
(`test_pkg64_gpu_phase3_prism_psnr_floor`,
`test_disable_reflective_caustics_reduces_mirror_caustic_outliers`)
still want `strict=True`-or-retire; pkg177's architecture ratification
(new).

---

## 3. Drop-in prompt for the next session

The authoritative instructions live with the owner. In short: **run the
supervised settlement round first** — #541-A (decision recorded, just
execute), pkg172(A) with the architect-signed re-pin batch, pkg174 to
restore the perf ceiling and revert the raise. Do NOT dispatch pkg173 or
new pkg153 fixes — the parity tail is below the milestone now. **Then
pivot the pool to the Integration Milestone:** pkg175 first (one-command
dev loop; it is the iteration vehicle for everything after), pkg177 in
parallel (research/decision only, no code), pkg176 staged behind pkg175
with pkg119-B/C as its verification layer. Keep the framing the owner
gave: Blender's native Cycles-shaped settings are the steering wheel; the
custom ground-up UI is being retired, not extended — any new addon UI
work that isn't the single Astroray panel is scope creep against the
directive. Real-Blender verification is mandatory for every addon-facing
PR (pkg175's smoke gate makes it cheap). Rules that stay live from the
cascade: **energy gates render LINEAR with an upper bound** (pkg166);
**state the `.pyd` mtime next to every probe A/B number**; **mirror the
CONDITION, not just the term, in every CPU→GPU port**; **upsample the
ASSET, apply scalar transport factors outside the upsample**
(pkg163/pkg168 class rule); **expectations are RNG-stream-independent**.
Cite per CLAUDE.md §6 (`/cite-algorithm`) for any weight-formula change.

---

## 4. Coordination

- **One PR per package**, doc-only closeouts auto-merge on green CI
  (pr-reviewer doc-only rule). Source PRs need the independent-review
  SIGN-OFF/BLOCK gate (pkg98) before push.
- **`src/gpu/wavefront/stage_advance.cu` is a serialization point** — and
  pkg174 freezes the shade/advance stages entirely while open (REG work
  only; no features into those kernels).
- **CI is blind to GPU correctness** — never declare a round clean on CI
  green alone; run the full RTX hardware sweep at closeout (memory:
  `ci_has_no_gpu_runtime_blindspot`).
- **`apply_gamma=True` cannot detect energy GAIN** — render energy gates
  linear with floor+ceiling (memory:
  `gamma-furnace-cannot-detect-energy-gain`).
- **Addon-facing PRs need a real-Blender leg** — mocked-`bpy` suites have
  now missed multiple shipped-broken defects (pkg88-A/B); pkg175's smoke
  gate is the standing mechanism, `verify_pkg88b_blender.py` the pattern
  (gate on the printed sentinel, not the exit code).
- **Addon packaging:** new `blender_addon/*.py` files must enter
  `ADDON_FILES` in `build_blender_addon.py`; addon builds require
  `-DASTRORAY_DISABLE_OPENMP=ON` (memories: `addon-packaging-file-list`,
  `mingw_openmp_blender_deadlock`).
- **The GPU wavefront is NOT run-to-run bit-exact** (~1.19e-07–2e-7 atomic
  floor) — gate at the 1e-5 Monte-Carlo convention, not exact equality.
- **Watch the shadow-`.pyd` trap** — verify `astroray.__file__` resolves to
  `build_cuda/Release/` and check `.pyd` mtime vs HEAD (memory:
  `stale_pyd_locations`).
- **Grep `^Status:` (or `**Status:**`) in the spec before dispatching** —
  this report's §2 prose can go stale vs the spec header (memory:
  `orchestrator-next-stage-report-stale`).
- **Cite papers/reference repos per CLAUDE.md §6** for any new algorithm.

---

## 5. After the round

- Flip landed spec `Status:` lines to `done (PR #N, date — headline
  numbers)`.
- Update STATUS.md (new round section + next pickup queue), ROADMAP.md
  (round-closeout entry; the "Current sequencing" section only changes on
  a new owner directive), and rewrite this report's §1/§2 for the next
  round.
- Run the RTX hardware sweep; record the full test-suite state. After the
  settlement round specifically: confirm the perf ceiling raise is gone
  (pkg174's revert) and the pkg172(A) re-pin batch ledger is committed.
- Do not bulk-promote flaky xfails on a lucky run.
- Open ONE doc PR (or direct doc-only commit per repo rule) for the
  closeout.

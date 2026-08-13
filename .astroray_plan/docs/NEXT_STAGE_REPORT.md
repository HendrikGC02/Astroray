# Astroray Next Stage Report

**Date:** 2026-08-14 (round closeout — 8 PRs merged, #605–#612, on top of the
2026-08-13 post-closeout addendum).
**Prepared by:** the architect (round closeout).
**Scope:** no open PRs at time of writing. Full detail:
`.astroray_plan/docs/STATUS.md` (top entry "2026-08-13 → 2026-08-14 (round
closeout...)" and the matching "## Round closeout 2026-08-13 → 2026-08-14"
archival section), `.astroray_plan/docs/ROADMAP.md` ("Current sequencing"
unchanged — no new owner directive this round).

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

- **The Integration Milestone stays fully closed** (unchanged this round —
  see ROADMAP.md "Current sequencing"). This round's work sits downstream of
  it: viewport navigation performance (interactive at last), Principled
  spectral correctness (closing the pkg188 72% band-error finding), GPU
  wavefront capability parity (denoise-guide AOVs + `applyPasses` wired into
  the GPU route, world-volume fog, procedural textures), and camera-view
  overlay pixel-exactness.
- **Landed this round (8 PRs, #605–#612, no open PRs at closeout):**
  pkg192 (viewport nav interactivity Suspect A, PR #605, 5.97→8.44 fps),
  pkg196 (reduced-res nav Suspect B, PR #609, 8.36→18.52 fps p50, 3.1x
  combined with pkg192), pkg193 (camera-view overlay alignment, PR #607,
  223px→0.00px), pkg194 (Principled tinted-layer spectral-carry + thin-wall
  per-λ, PR #606, 72%→0% band error), pkg197 (GPU wavefront denoise-guide
  AOVs + `applyPasses` wired into the GPU route, PR #608, +8.0% edge-MSE),
  pkg199 Stage 1 (GPU wavefront world-volume Beer-Lambert absorption, PR
  #611, HW FAIL→fix→PASS), pkg190 (GPU procedural textures, PR #612, HW
  FAIL→fix→PASS, pkg119-B TRANSLATION-BUG 4→0), pkg195 Stage C (spectral
  node system remainder, PR #610 — **pkg195 is now FULLY COMPLETE across
  all three stages A+B+C**).
- **Two HW FAIL → fix → PASS cycles this round, both resolved same-PR
  before merge:** pkg199's sphere-light NEE leg used a 1e30 occlusion
  sentinel as the Beer-Lambert path length (saturated fog to black under a
  point/area light — fixed to the true geometric NEE distance, commit
  6e7bf6d); pkg190's `scripts/run_parity.py` didn't recognize the new
  `textured_plane` scene (silent no-op leg) and its EXR reader zeroed the
  green channel via an unconfigured `imageio` plugin (both fixed, commit
  b2b42eb, re-verified exact match to the original bypass measurement).
- **pkg119-B reclassification (pkg190):** the long-standing "5 residual
  TRANSLATION-BUGs" figure was stale/false. Fresh re-baseline on current
  main found the real set was 4 nodes (all procedural textures), all fixed
  by pkg190. pkg119-B is now **30 pass, TRANSLATION-BUG 0**.
- **Specs filed the prior round's addendum, disposition this round:**
  pkg196, pkg197, pkg199 Stage 1 all landed DONE above. **pkg198** (GPU
  wavefront light-path AOV passes, register-hostile, explicitly
  "probe-first, may park") remains **OPEN** — highest-signal item in the
  correctness/capability-parity pool.
- **Open, not blocking, carried forward:** pkg198 (GPU light-path AOV
  passes, probe-first), pkg199 Stage 2 (full HG scattering medium, XL,
  CPU-first — spec-only, filed this round), pkg131 (zero-knob adaptive
  sampling, wavefront leg), the pkg176-line deep per-setting F12
  pixel-honour matrix (deferred to a later addon HW session, no dedicated
  spec number), the durable `GLoweredMaterial` by-value-`GMaterial`-copy
  fix (still prototyped, uncommitted, worktree `sad-maxwell-ff99d1`),
  pkg180 (systemic-dim diagnosis, still open).
- **Two unfiled follow-up chips surfaced this round (not yet a spec):** the
  legacy non-dedicated `add_sun_light` GPU-dimness finding from the pkg194
  review (pkg89 Phase B's `add_sun_light_dedicated` does NOT reproduce it;
  diagnosis-first candidate); an Object-coordinate-mode guard for the
  pkg190 procedural bake (the 3D-voxel bake covers Generated-space nodes
  only, per spec scope — Object-coordinate procedural textures have no
  explicit GPU guard or documented fallback; could silently misrender if a
  scene hits that combination).
- **Pre-existing gap, documented not fixed (pkg199 review):** the caustic
  integrator (`pathTraceSpectralCaustic`) and the CPU wavefront reference do
  not read `c_worldVolume` — a caustic render through fog ignores the fog
  entirely. Recorded as a Stage-1 non-goal in the pkg199 spec; candidate for
  a follow-up spec, not filed.
- **Still standing, unresolved:** the Pillar 4 unpause decision (pkg45/46/
  48/49/50/51 + pkg107, GR/astro science layer) — no new owner directive
  this round; ROADMAP.md's PAUSED marker is unchanged. Surfaced again below
  as the top strategic (not code) item.
- **Environment:** RTX 5070 Ti workstation; Blender 5.1/5.2 installed
  locally (real-host checks mandatory for addon-facing PRs). Every code PR
  this round was dual-gated (CI + independent RTX hardware verification);
  two of eight PRs required a fix-and-re-verify cycle before merge.

---

## 2. Deployable set (prioritized)

Grep `^\*\*Status:\*\*` in each spec before dispatch (memory
`orchestrator-next-stage-report-stale`) — this report can go stale.

**Top candidate — needs an explicit owner decision, not a silent dispatch:**

1. **Pillar 4 unpause** (pkg45/46/48/49/50/51 + pkg107, GR/astro science
   layer). Unchanged since the last report — ROADMAP.md's PAUSED marker has
   stood since 2026-06-08; still no explicit go-ahead. **Surface this to
   the owner before dispatching any pkg45-tier work.**

**Correctness/capability-parity tier, highest signal in the open pool**
(pkg190/192/193/194/196/197/199-Stage-1 all landed this round; pkg195 is now
fully complete — re-ranked accordingly):

2. **pkg198** — GPU wavefront light-path AOV passes. Explicitly
   **probe-first, may park** per its own status line: the register-gate
   probe result decides whether this is dispatchable at all before any
   implementation work. Highest-priority open GPU-capability item; run the
   probe before committing to full implementation.
3. **pkg199 Stage 2** — full HG in-scatter / distance-sampling / NEE-
   through-medium volumetric scattering, CPU-first (XL). Delivers god-rays/
   light shafts; spec-only, filed this round. Estimate XL — size the
   dispatch accordingly, likely its own dedicated session rather than a
   quick pickup.
4. **pkg131** — zero-knob adaptive sampling, wavefront leg. Long-standing
   open item, no new blockers.

**Hygiene / follow-up (not yet filed as a dedicated spec):**

5. **The pkg176-line deep per-setting F12 pixel-honour matrix** — deferred
   from pkg176's Stage 4 closeout to "a later addon HW session." No
   dedicated spec number; file one before dispatching, or fold into a
   broader addon-parity pass.
6. **Legacy `add_sun_light` GPU-dimness finding** (surfaced in the pkg194
   review) — the non-dedicated light path shows a markedly dimmer/flatter
   GPU render vs an earlier informal comparison; `add_sun_light_dedicated`
   (pkg89 Phase B) does NOT reproduce it. Diagnosis-first, unmeasured;
   file a spec before dispatching (may be a measurement artifact — confirm
   on current main first, this repo has a history of stale-comparison false
   alarms in this exact shape).
7. **Object-coordinate-mode guard for the pkg190 procedural bake** — the
   3D-voxel bake covers Generated-space nodes only, per pkg190's spec
   scope; Object-coordinate-mode procedural textures have no explicit GPU
   guard or documented fallback. Low urgency (narrow combination) but a
   silent-wrong-render risk if hit; a guard + test is cheap, file it as a
   small follow-up.
8. **Caustic-integrator/CPU-wavefront-reference world-volume gap** — fog is
   invisible to the caustic integrator and the CPU wavefront reference
   (pkg199 Stage 1 documented non-goal). One-liner candidate: either extend
   those two paths to read `c_worldVolume`, or document the limitation
   user-facing (addon tooltip/panel note) if extending is out of scope for
   now.
9. **Durable `GLoweredMaterial` by-value-copy fix** — re-apply the
   prototyped PR-2-based fix from worktree
   `.claude/worktrees/sad-maxwell-ff99d1` on settled main. File a dedicated
   spec if picked up (recurring-leak pattern across pkg178 Stage 3 and PR
   #579 is evidence enough for a CLAUDE.md §6-citable structural fix).

**Re-entered / long-tail pool (still genuinely low priority):**

10. **pkg180** — systemic Astroray-vs-Cycles dim, diagnosis-first, still
    open dispatchable.
11. **pkg173** — bounce-1 geometry-sampling parity (pkg172 effect (B));
    holds pkg156's 0.998 SSIM restoration clause.
12. **pkg153** — wavefront_diff remainder, gate-failure-reviewer disposition
    in flight.
13. **pkg155 Phase 2** — shade-stage register recovery (221 regs/thread →
    ≤128 target); opportunistic GPU-lock gap-filler, not compile-only.
14. **pkg128** — thin-film residual charter (standalone Glass/Metallic node
    cells + spectral showcase), rides the shared Belcour-Barla utility
    pkg178/pkg182 already built.
15. **pkg165** — verify-and-close. A focused confirm on pkg158's exact
    Step-0 scene at r ∈ {0.0, 0.3, 0.6, 0.9} closes the paperwork; every
    existing reading is already in-band. Trivial, non-urgent.

**Not this phase:** anything not explicitly named above; Pillar 4 stays
PAUSED until the owner go-ahead in item 1 above.

---

## 3. Drop-in prompt for the next session

**First: get the owner's read on Pillar 4 unpause** (item 1) — a
milestone-scale sequencing decision, not a code dispatch. While that's
pending, **pkg198 (item 2) is the standout autonomous pickup** — run its
register-gate probe first (it may park itself); this is the highest-
priority GPU-capability item left in the correctness/parity pool now that
pkg190/192-197/199-Stage-1 have all landed and pkg195 is fully complete.
After that: pkg199 Stage 2 (item 3, XL — god-rays/light shafts, size its own
session) or pkg131 (item 4, smaller, no blockers) depending on available
session length. Items 5–9 are hygiene follow-ups that need a spec filed
before dispatch (the pkg176 F12 matrix, the `add_sun_light` GPU-dimness
diagnosis, the pkg190 Object-coordinate guard, the caustic/fog gap, and the
`GLoweredMaterial` fix). Items 10–15 are the long-tail pool, in roughly
that priority order.

Rules that stay live from this round: **energy gates render LINEAR with an
upper bound** (pkg166); **state the `.pyd` mtime next to every probe A/B
number**; **verify `cuobjdump` resource-gate readings against the TRUE
compiled arch, not the CMakeCache line** (pkg183's `arch-verify` gate
catches this automatically); **mirror the CONDITION, not just the term, in
every CPU→GPU port**; **CPU/GPU material work is byte-mirrored in the same
PR, never split across sessions**; **any new lobe/closure that touches the
shade path must be measured against the `template<bool HasPrincipled>` /
`template<bool HasPhotons>` isolation boundaries**; **eval and pdf must use
the SAME functional form for the same NDF** (the pkg182 class of bug);
**never trust a CSV/CLI deliverable's own claimed numbers — re-run the
documented command verbatim and read the actual output** (this round's
pkg190 hw-612 caught a routing-guard omission the PR's own numbers didn't
reveal, and a second EXR-reader defect that would have silently
nan-poisoned the ratio); **grep the spec for git-archaeology before
trusting an inherited premise** (pkg199's "the CPU already has this" claim
was false — the code had been dead since pkg14). Cite per CLAUDE.md §6
(`/cite-algorithm`) for any new algorithm.

---

## 4. Coordination

- **One PR per package**, doc-only closeouts auto-merge on green CI
  (pr-reviewer doc-only rule). Source PRs need the independent-review
  SIGN-OFF/BLOCK gate (pkg98) before push.
- **`src/gpu/wavefront/stage_advance.cu` is a serialization point** for any
  GPU-lane package (pkg198, pkg199 Stage 2, pkg131, a Pillar-4 GPU package,
  etc.) — check for other in-flight touches before dispatching.
- **CI is blind to GPU correctness** — never declare a round clean on CI
  green alone; run the full RTX hardware sweep at closeout (memory:
  `ci_has_no_gpu_runtime_blindspot`).
- **`apply_gamma=True` cannot detect energy GAIN** — render energy gates
  linear with floor+ceiling (memory:
  `gamma-furnace-cannot-detect-energy-gain`).
- **Addon-facing PRs need a real-Blender leg** — `dev_addon.ps1 -Smoke`
  (pkg175) is the standing mechanism; gate on the printed sentinel, not the
  exit code.
- **The GPU wavefront is NOT run-to-run bit-exact** (~1.19e-07–2e-7 atomic
  floor) — gate at the 1e-5 Monte-Carlo convention, not exact equality.
- **Watch the shadow-`.pyd` trap** — verify `astroray.__file__` resolves to
  the canonical build output and check `.pyd` mtime vs HEAD (memory:
  `stale_pyd_locations`).
- **Watch the stale-CMakeCache CUDA-arch trap** — the cache line can lie;
  trust `cuobjdump --list-elf` on the linked `.pyd`, which pkg183's
  `arch-verify` gate now does automatically in all three build wrappers.
- **CLI/script deliverables need the documented command re-run verbatim,
  not the PR's own claimed numbers trusted** — pkg190's hw-612 caught a
  routing-guard omission and an EXR-reader defect this way; both were
  invisible from the PR body alone.
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

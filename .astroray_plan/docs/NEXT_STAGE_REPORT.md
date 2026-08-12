# Astroray Next Stage Report

**Date:** 2026-08-13 (rewritten at round closeout — GPU capability restoration
+ Principled spectral correctness run, 2026-08-12 → 2026-08-13, 15 PRs merged
#585–#599).
**Prepared by:** the architect (round closeout).
**Scope:** the round closed with no open PRs. Full detail:
`.astroray_plan/docs/STATUS.md` (round-closeout section "2026-08-12 →
2026-08-13"), `.astroray_plan/docs/ROADMAP.md` (matching round-closeout
entry; "Current sequencing" unchanged — no new owner directive this round).

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

- **The Integration Milestone stays fully closed** (unchanged this round —
  see ROADMAP.md "Current sequencing"). This round's work sits downstream of
  it: GPU capability restoration (first GPU image textures, a viewport
  progressive-refinement correctness fix) and Principled BSDF spectral
  correctness follow-ups (per-λ conductor thin-film, dispersion, transmission
  colour/scalar separation), plus a build-integrity guard.
- **Landed this round:** pkg183 (build-integrity guard, PR #592), pkg185
  (GPU glass-caustic gate closed by a test-scene fix, PR #589), pkg186
  (first GPU image-texture support, PR #590), a pkg182 follow-up (per-λ
  conductor thin-film, PR #586), pkg187 (Principled BSDF dispersion,
  CPU-complete + GPU-wired, PR #593), pkg184 (`template<bool HasPhotons>`
  kernel isolation, PR #597), pkg191 (GPU viewport progressive refinement,
  PR #598), pkg188 (Principled transmission colour/scalar separation, PR
  #599). pkg175 flipped to `done` as a drift-gate fix (PR #547 had already
  merged 2026-08-07; its spec status had gone stale).
- **HEADLINE ENGINE FINDING (pkg195 design session, PR #596):**
  `multiwavelength_path_tracer` has **no light sampling** — every lamp-lit
  NIR/UV render is black end-to-end (measured mean 0.00034 vs sky, all
  profiles, even under a 5000K blackbody sun). The Spectral Profile node is
  a visible-band no-op by design; the IR/UV Response node is destructive
  (replaces the wired BSDF with grey, changing the *visible* render too).
  Sodium/mercury-vapor and CIE F2/F3 lamp SPDs already ship in
  `data/spectral_profiles/profiles.bin` and the engine-side
  `EmissionSpectrum::MeasuredSPD` parser exists — the addon just never sends
  anything but `blackbody`/`rgb`. Full inventory:
  `.astroray_plan/docs/spectral-node-system-design-2026-08.md`. **pkg195
  Phase 1 spec is filed (Stage A = the light-sampling fix, CPU-only, does
  NOT touch the wavefront GPU kernels) but not yet implemented — this is
  the single highest-signal correctness item in the open pool.**
- **A fleet-wide false-reading class was caught and fixed mid-round:** every
  local `build_cuda/` tree carried a stale cached
  `CMAKE_CUDA_ARCHITECTURES=52` CMakeCache entry (shadowed at configure time
  by CMakeLists' non-cache `set()`, so the actually-compiled kernels were
  correct sm_120 SASS all along, but `cuobjdump` reads against the cache-line
  arch produced phantom resource-gate numbers — worktree STACK 2640 vs the
  true sm_120 `<false>` baseline of STACK 3608). **pkg183** now ships an
  automatic artifact-ground-truth gate (`cuobjdump --list-elf`, exit 7)
  against this class going forward, but the root cause itself (CMakeLists,
  `configure_and_build.bat`, `build_blender_addon.py`'s hardcoded
  arch/Debug revert) is still open, queued as a separate infra PR.
- **Open, not blocking, carried forward:** pkg189 (GPU wavefront dispersion
  enablement — unblocks pkg187's GPU-visible leg and the pre-existing pkg64
  dielectric xfail, both share the same hero-λ-refraction no-op), pkg190
  (GPU procedural textures, needs a pkg119-B re-baseline first), pkg192/
  pkg193 (viewport-addon diagnosis-first specs from owner hands-on
  feedback: interactivity 3–5fps vs Cycles ~30fps, camera-view overlay
  misalignment), pkg194 (Principled tinted-layer spectral carry + thin-wall
  per-λ — priority raised by pkg188's QUANTIFIED ~72% band-error finding on
  coloured-tint-over-dark-base materials), the durable `GLoweredMaterial`
  by-value-`GMaterial`-copy fix (still prototyped, uncommitted, in worktree
  `.claude/worktrees/sad-maxwell-ff99d1`), pkg180 (systemic-dim diagnosis,
  still open dispatchable).
- **Still standing, unresolved:** the Pillar 4 unpause decision (pkg45/46/
  48/49/50/51 + pkg107, GR/astro science layer) — no new owner directive
  this round; ROADMAP.md's PAUSED marker is unchanged. Surfaced again below
  as the top strategic (not code) item.
- **Environment:** RTX 5070 Ti workstation; Blender 5.1/5.2 installed
  locally (real-host checks mandatory for addon-facing PRs). Every code PR
  this round was dual-gated (CI + independent RTX hardware verification);
  three hardware verifiers were serialized through the GPU lock overnight.

---

## 2. Deployable set (prioritized)

Grep `^\*\*Status:\*\*` in each spec before dispatch (memory
`orchestrator-next-stage-report-stale`) — this report can go stale.

**Top candidate — needs an explicit owner decision, not a silent dispatch:**

1. **Pillar 4 unpause** (pkg45/46/48/49/50/51 + pkg107, GR/astro science
   layer). Unchanged since the last report — ROADMAP.md's PAUSED marker has
   stood since 2026-06-08; still no explicit go-ahead. **Surface this to
   the owner before dispatching any pkg45-tier work.**

**Correctness-tier, highest signal in the open pool:**

2. **pkg195 Stage A** — give `MultiwavelengthPathTracer::pathTrace` spectral
   NEE over dedicated lights. Fixes a real, currently-shipping defect
   (every lamp-lit NIR/UV render is black); CPU-only, explicitly scoped to
   NOT touch the wavefront GPU kernels (REG:254 stays untouched). Do not
   scope-creep into Phases 2–4 (recorded in the design doc §5) — Stage A
   alone is the dispatchable unit.
3. **pkg189** — GPU wavefront dispersion enablement. Closes the pre-existing
   hero-λ-refraction no-op that both pkg187's Principled dispersion and the
   long-standing pkg64 dielectric xfail are blocked on; lights up two
   features at once.
4. **pkg194** — Principled tinted-layer spectral carry + thin-wall per-λ.
   Priority raised by pkg188's quantified ~72% band-error finding on
   coloured-tint-over-dark-base materials (0% for the common white-tint
   case, so this is a real-but-narrow defect, not a universal one).

**Hygiene / addon-facing (owner explicitly gave feedback on these):**

5. **pkg192** — viewport navigation interactivity (3–5fps vs Cycles' ~30fps)
   — diagnosis-first spec.
6. **pkg193** — camera-view overlay misalignment — diagnosis-first spec.
7. **pkg190** — GPU procedural textures (pkg186 slice 2) — **blocked on a
   pkg119-B re-baseline first**, do not dispatch before that re-baseline
   lands.
8. **Infra: CUDA-arch root-cause PR** — force `CMAKE_CUDA_ARCHITECTURES`
   from `ASTRORAY_CUDA_ARCHS` at the CMakeLists cache level (not a
   non-cache `set()`), and pass `ASTRORAY_CUDA_ARCHS` through
   `configure_and_build.bat` + fix `build_blender_addon.py`'s hardcoded
   arch/Debug revert. Closes the false-reading class pkg183 currently only
   detects after the fact.
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
pending, **pkg195 Stage A (item 2) is the standout autonomous pickup** — it
fixes a real, currently-shipping engine defect (lamp-lit NIR/UV renders are
black), is CPU-only, and does not touch the register-saturated wavefront GPU
kernels. After that: pkg189 (item 3, unblocks two features at once), then
pkg194 (item 4, quantified real defect). The addon-feedback items (5–6) and
pkg190 (7, gated on its own prerequisite) are next-best; the infra
root-cause PR (8) and the `GLoweredMaterial` fix (9) are hygiene debt that
unblocks clean baselines going forward. Items 10–15 are the long-tail pool,
in roughly that priority order.

Rules that stay live from this round: **energy gates render LINEAR with an
upper bound** (pkg166); **state the `.pyd` mtime next to every probe A/B
number**; **verify `cuobjdump` resource-gate readings against the TRUE
compiled arch, not the CMakeCache line** — the cache can be shadowed at
configure time by a non-cache `set()`, giving phantom Maxwell-PTX readings
that look like real register/stack deltas (this round's pkg183/pkg187
incident; pkg183's `arch-verify` gate now catches it automatically);
**mirror the CONDITION, not just the term, in every CPU→GPU port**;
**CPU/GPU material work is byte-mirrored in the same PR, never split across
sessions**; **any new lobe/closure that touches the shade path must be
measured against the `template<bool HasPrincipled>` isolation boundary**
(and now the `template<bool HasPhotons>` boundary pkg184 added — a naive
addition can reopen either regression class); **eval and pdf must use the
SAME functional form for the same NDF** (the pkg182 class of bug). Cite per
CLAUDE.md §6 (`/cite-algorithm`) for any new algorithm.

---

## 4. Coordination

- **One PR per package**, doc-only closeouts auto-merge on green CI
  (pr-reviewer doc-only rule). Source PRs need the independent-review
  SIGN-OFF/BLOCK gate (pkg98) before push.
- **`src/gpu/wavefront/stage_advance.cu` is a serialization point** for any
  GPU-lane package (pkg155 Phase 2, pkg189, a Pillar-4 GPU package, etc.) —
  check for other in-flight touches before dispatching.
- **CI is blind to GPU correctness** — never declare a round clean on CI
  green alone; run the full RTX hardware sweep at closeout (memory:
  `ci_has_no_gpu_runtime_blindspot`).
- **`apply_gamma=True` cannot detect energy GAIN** — render energy gates
  linear with floor+ceiling (memory:
  `gamma-furnace-cannot-detect-energy-gain`).
- **Addon-facing PRs need a real-Blender leg** — `dev_addon.ps1 -Smoke`
  (pkg175, now done) is the standing mechanism; gate on the printed
  sentinel, not the exit code.
- **The GPU wavefront is NOT run-to-run bit-exact** (~1.19e-07–2e-7 atomic
  floor) — gate at the 1e-5 Monte-Carlo convention, not exact equality.
- **Watch the shadow-`.pyd` trap** — verify `astroray.__file__` resolves to
  the canonical build output and check `.pyd` mtime vs HEAD (memory:
  `stale_pyd_locations`).
- **Watch the stale-CMakeCache CUDA-arch trap** — the cache line can lie;
  trust `cuobjdump --list-elf` on the linked `.pyd`, which pkg183's
  `arch-verify` gate now does automatically in all three build wrappers.
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

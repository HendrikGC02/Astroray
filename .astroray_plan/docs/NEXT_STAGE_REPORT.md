# Astroray Next Stage Report

**Date:** 2026-08-10 (rewritten at round closeout — Principled-BSDF completion
run, 2026-08-08 → 2026-08-10, 17 PRs merged #566–#582).
**Prepared by:** the architect (round closeout).
**Scope:** the round closed with no open PRs. Full detail:
`.astroray_plan/docs/STATUS.md` (round-closeout section "2026-08-08 →
2026-08-10"), `.astroray_plan/docs/ROADMAP.md` ("Current sequencing" +
matching round-closeout entry).

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md).

---

## 1. Current state (one screen)

- **The Integration Milestone's originally-scoped package set is DONE:**
  pkg175 (one-command dev loop, PR #547), pkg176 (Blender native steering
  wheel, Stages 0–4, PRs #555/#556/#561/#568), pkg177 (DCC-architecture
  decision, ratified, PR #546), pkg119 Phases B/C (differential harness +
  graceful degradation, PRs #550/#564).
- **The milestone's owner-requested extension is also DONE:** pkg178
  (native Cycles Principled BSDF, Stages 0–5, PRs #566–#581) — a faithful
  `"principled"` material plugin (core lobes, coat/sheen/anisotropy/
  approx-SSS/emission/alpha, thin film + thin wall per Belcour-Barla
  2017), CPU+GPU byte-mirrored, routed from the Blender addon. Two
  correctness prerequisites/side-findings this surfaced were fixed the
  same run: **pkg181** (dedicated-light BSDF visibility — the systemic
  ~12–20% Astroray-vs-Cycles dim + dark lamp reflections, PR #569) and
  **pkg182** (`ggxReflect` eval-D/pdf-D consistency — low-roughness
  Principled metallic/specular near-black, PR #582). **pkg179**
  (dielectric dead-sample "3× rate") was CLOSED by diagnosis — a
  measurement mislabel, owner ratified no-fix.
- **The settlement round's remaining item closed too:** pkg172 effect (A)
  — the pbrt-v4 guarded-pdf form removes the universal 0.628%/bounce
  `f/(pdf+1e-3)` energy loss CPU+GPU (PRs #551/#553/#576). Effect (B)
  stays pkg173's separate scope.
- **Per the owner's 2026-08-03 directive's own sequencing** — (a)
  settlement, (b) Integration Milestone, (c) *"only then Pillar 4
  unpause"* — **both (a) and (b) are now complete.** (c) is next in the
  directive's own order, but Pillar 4 has an explicit standing PAUSED
  marker in ROADMAP.md pending an owner go-ahead; this report surfaces it
  as the top candidate, not as an executed decision — **do not unpause
  unilaterally, confirm with the owner first.**
- **Two packages that were explicitly de-prioritized "below the
  Integration Milestone"** (pkg173 bounce-1 geometry-sampling parity,
  pkg153 wavefront_diff remainder) **re-enter the open pool now that the
  milestone is closed**, per their own spec text — still genuinely
  low-priority sub-percent tail, not urgent.
- **Open, not blocking, carried forward:** thin-film-vs-Cycles saturation
  parity verification (pkg178 follow-up: metal iridescence is an
  RGB-upsample approximation, less saturated than Cycles' per-λ); one
  coordinated pkg119-B/pkg129 harness band re-pin (reflecting pkg181 +
  Smith-G + pkg172(A) + thin-film + pkg182 together, all landed since the
  bands were last set); the durable `GLoweredMaterial`
  by-value-`GMaterial`-copy fix (recurring data-leak class hit and
  locally patched by both pkg178 Stage 3 and PR #579; prototyped in
  worktree `.claude/worktrees/sad-maxwell-ff99d1`, uncommitted, needs
  re-apply on settled main).
- **Environment:** RTX 5070 Ti workstation; Blender 5.1/5.2 installed
  locally (real-host checks mandatory for addon-facing PRs).

---

## 2. Deployable set (prioritized)

Grep `^Status:`/`**Status:**` in each spec before dispatch (memory
`orchestrator-next-stage-report-stale`) — this report can go stale.

**Top candidate — needs an explicit owner decision, not a silent
dispatch:**

1. **Pillar 4 unpause** (pkg45/46/48/49/50/51 + pkg107, GR/astro science
   layer). This is the directive's own next step now that (a)+(b) are
   complete, but ROADMAP.md's PAUSED marker has stood since 2026-06-08 and
   the directive didn't say "auto-unpause on milestone completion" in so
   many words — **surface this to the owner and get an explicit
   go/no-go before dispatching any pkg45-tier work.**

**Hygiene / closeout debt (small, unblocks clean baselines for everything
after it):**

2. **Coordinated pkg119-B/pkg129 harness band re-pin** — five landed
   packages (pkg181, pkg172(A) Smith-G-adjacent changes, thin-film,
   pkg182) have moved rendered energy/hue since these bands were last set;
   re-baseline once, with per-pin justification (pkg166 precedent),
   architect sign-off on the batch.
3. **pkg165** — verify-and-close. A focused confirm on pkg158's exact
   Step-0 scene at r ∈ {0.0, 0.3, 0.6, 0.9} closes the paperwork; every
   existing reading is already in-band. Trivial, non-urgent.
4. **Durable `GLoweredMaterial` by-value-copy fix** — re-apply the
   prototyped PR-2-based fix from worktree
   `.claude/worktrees/sad-maxwell-ff99d1` on settled main. No dedicated
   spec filed yet; file one if this is picked up (the recurring-leak
   pattern across pkg178 Stage 3 and PR #579 is evidence enough for a
   CLAUDE.md §6-citable structural fix, not another ad-hoc patch).

**Re-entered pool (was below the milestone, now open again — still
genuinely low priority):**

5. **pkg173** — bounce-1 geometry-sampling parity (pkg172 effect (B));
   holds pkg156's 0.998 SSIM restoration clause.
6. **pkg153** — wavefront_diff remainder, gate-failure-reviewer disposition
   in flight.
7. **pkg155 Phase 2** — shade-stage register recovery (221 regs/thread →
   ≤128 target); opportunistic GPU-lock gap-filler, not compile-only.
8. **pkg128** — thin-film residual charter (standalone Glass/Metallic node
   cells + spectral showcase), now unblocked: pkg178 Stage 4 already built
   and shipped the shared Belcour-Barla utility this package rides.

**Not this phase:** anything not explicitly named above; Pillar 4 stays
PAUSED until the owner go-ahead in item 1 above.

---

## 3. Drop-in prompt for the next session

**First: get the owner's read on Pillar 4 unpause** (item 1) — this is a
milestone-scale sequencing decision, not a code dispatch. While that's
pending, the hygiene/closeout items (2–4) are safe autonomous work: they
close paperwork and re-baseline bands that landed code has already moved,
without opening new scope. If the owner confirms Pillar 4, pkg45 is the
first pickup per the original Pillar-4 spec queue (pkg45–pkg51 + pkg107).
If the owner wants more polish before that, pkg173/pkg153/pkg155-Phase-2/
pkg128 (items 5–8) are the next-best backlog, in roughly that priority
order (correctness-tail > perf > material-completeness).

Rules that stay live from this round: **energy gates render LINEAR with an
upper bound** (pkg166); **state the `.pyd` mtime next to every probe A/B
number**; **mirror the CONDITION, not just the term, in every CPU→GPU
port**; **CPU/GPU material work is byte-mirrored in the same PR, never
split across sessions** (the pkg160→pkg163→pkg178 discipline); **any new
lobe/closure that touches the shade path must be measured against the
`template<bool HasPrincipled>` isolation boundary** — a naive addition can
reopen the +52% non-principled regression pkg178's D4 fix closed; **eval
and pdf must use the SAME functional form for the same NDF** (the pkg182
class of bug — check this explicitly whenever a new lobe's `eval`/`sample`
pair is written). Cite per CLAUDE.md §6 (`/cite-algorithm`) for any new
algorithm.

---

## 4. Coordination

- **One PR per package**, doc-only closeouts auto-merge on green CI
  (pr-reviewer doc-only rule). Source PRs need the independent-review
  SIGN-OFF/BLOCK gate (pkg98) before push.
- **`src/gpu/wavefront/stage_advance.cu` is a serialization point** for any
  GPU-lane package (pkg155 Phase 2, a Pillar-4 GPU package, etc.) — check
  for other in-flight touches before dispatching.
- **CI is blind to GPU correctness** — never declare a round clean on CI
  green alone; run the full RTX hardware sweep at closeout (memory:
  `ci_has_no_gpu_runtime_blindspot`).
- **`apply_gamma=True` cannot detect energy GAIN** — render energy gates
  linear with floor+ceiling (memory:
  `gamma-furnace-cannot-detect-energy-gain`).
- **Addon-facing PRs need a real-Blender leg** — `dev_addon.ps1 -Smoke`
  (pkg175) is the standing mechanism; gate on the printed sentinel, not
  the exit code.
- **The GPU wavefront is NOT run-to-run bit-exact** (~1.19e-07–2e-7 atomic
  floor) — gate at the 1e-5 Monte-Carlo convention, not exact equality.
- **Watch the shadow-`.pyd` trap** — verify `astroray.__file__` resolves to
  the canonical build output and check `.pyd` mtime vs HEAD (memory:
  `stale_pyd_locations`).
- **Grep `^Status:` (or `**Status:**`) in the spec before dispatching** —
  this report's §2 prose can go stale vs the spec header (memory:
  `orchestrator-next-stage-report-stale`).
- **Cite papers/reference repos per CLAUDE.md §6** for any new algorithm.
- **Cost routing (2026-08):** bounded grunt work (docs flips, lint fixes,
  report assembly, pre-review critique, well-specified gated
  implementation) routes to the `delegate` skill's open-weight tiers,
  evidence-verified, never trusted; Claude stays on architect/specs,
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

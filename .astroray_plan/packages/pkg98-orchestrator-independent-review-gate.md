# pkg98 — Orchestrator independent (different-model) review gate

**Pillar:** 5
**Track:** A (engine/Python + agent-prompt plumbing — no GPU, no physics, no CUDA)
**Codex-paste-ready:** yes
**Status:** ready
**Estimated effort:** ~½ day (~4 h)
**Depends on:** roadmap-orchestrator design spec (2026-05-16) — the engine/skill this extends; pkg97 (the sibling close-out-path change; no code overlap but same SKILL.md surface)

---

## Goal

**Before:** The orchestrator's two review surfaces are
single-model and structurally weak in exactly the way the pkg44
ADAF debug session (2026-05-17) exposed:

1. **On gate FAIL** the SKILL Step 2.2 / 2.5 dispatches
   `gate-failure-reviewer`, which produces a diagnosis and routes
   to a fresh `package-implementer`. There is **no requirement**
   that the proposed *fix* is independently signed off before it
   is pushed for re-gate. In the pkg44 #310 incident the RTX HW
   gate correctly caught a flat-render *symptom*
   (`shadow_fraction 0.0`); a camera-only first fix was drafted
   that did **not** address the real defect — an unimplemented
   `enable_adaf` wire in `addBlackHole` (memory
   `gr-emission-model-wiring-checklist`). It was an **ad-hoc,
   off-process, different-model (Codex) review** that caught the
   primary defect *before the bad fix was pushed*. Nothing in the
   orchestrator made that review happen — it was luck, not policy.

2. **Pre-merge**, the only check for a package whose pipeline has
   **no HW/render gate** (Track-A engine / orchestrator /
   blender-addon plumbing / docs-with-code) is GitHub CI plus the
   single-model `pr-reviewer` checklist. CI demonstrably misses
   integration/logic gaps: pkg44 shipped **19 green pytest tests
   + green CI** with all three scene-wiring steps broken because
   the unit tests called the physics via direct pybind helpers and
   never went through `add_black_hole`. For HW/render-gated
   packages this is covered — the empirical RTX visual gate is the
   real check. For non-HW-gated packages there is **no equivalent
   backstop**.

**After:**

1. On any CI **or** HW gate FAIL, before the proposed fix is
   pushed for re-gate, the orchestrator requires (a) a written
   root-cause analysis and (b) an **independent, different-model
   sign-off on the proposed fix**. No fix is pushed without a
   recorded sign-off. The sign-off may return **BLOCK**, and BLOCK
   is a real, expected, first-class outcome that stops the push —
   not a formality to be rubber-stamped.

2. Packages whose pipeline has **no HW/render gate** get one
   independent, different-model pre-merge code review before
   `pr-reviewer` is allowed to auto-merge. HW/render-gated
   packages are **explicitly excluded** — the empirical HW visual
   gate already covers them, and excluding them controls cost,
   latency, and rubber-stamp decay. Classification reuses the
   existing routing/Track metadata; no new taxonomy is invented.

This is engine/agent-prompt plumbing only — no GPU, no physics,
no CUDA — so it does not contend for the serialized hardware slot
and is safe to ship while hardware-gated packages are in flight.

---

## Context — why this matters now

The orchestrator is the project's autonomous advance engine. The
pkg44 #310 session is the empirical proof that its current review
posture has two holes a single model walks straight through:

- **A single model that wrote (or would write) the fix is not a
  reliable check on that fix.** The camera-only first fix looked
  plausible to the same lineage that proposed it; it took a
  *different model* (Codex) reading the diff adversarially to see
  the missing `enable_adaf` wire. This is the documented
  motivation in memory `gr-emission-model-wiring-checklist` and
  `ci_has_no_gpu_runtime_blindspot`.
- **Green CI is not integration coverage for non-HW-gated work.**
  The HW visual gate is the real backstop for render packages, but
  Track-A engine / orchestrator / addon-plumbing / docs-with-code
  packages have *no* HW gate by construction — so for those, CI is
  the only automated check, and pkg44 proved CI passes hollow on a
  never-wired scene path.

This package formalizes the *one* thing the pkg44 session proved
necessary — independent (different-model) review — at the *minimum*
scope that closes the two holes (CLAUDE.md §2/§3). It does **not**
add a universal every-PR review (see Hard non-goals — that would
re-introduce on HW-gated packages a check the empirical visual gate
already provides, doubling cost/latency and accelerating
rubber-stamp decay).

This is **not a substitute for integration tests.** Render/emission
packages must still carry the end-to-end scene assertions required
by memory `gr-emission-model-wiring-checklist` (central-dark-region
+ radial-falloff through `add_black_hole`, not a hollow
"renders some signal" check). Independent review is a second,
orthogonal line of defence — it catches what tests *and* CI miss;
it does not license shipping without the tests.

---

## Reference

### Internal

- [`.claude/skills/roadmap-orchestrator/SKILL.md`](../../.claude/skills/roadmap-orchestrator/SKILL.md)
  — Step 2.2 (fixers: `gate-failure-reviewer` then a `pkg-ship`
  CI-fix pass), Step 2.4 (merges via `pr-reviewer`), Step 2.5
  (`plan.hw_failed` → `gate-failure-reviewer`), Safety rails. The
  two invocation points this package gates.
- [`.astroray_plan/docs/2026-05-16-roadmap-orchestrator-design.md`](../docs/2026-05-16-roadmap-orchestrator-design.md)
  — §4 Step 2 (PR triage + dual gate; the CI-failing / HW-failed
  rows), §5 safety rails (the non-negotiable invariants this
  package extends), §6 state (the ledger this package records the
  artifact in).
- [`.claude/agents/gate-failure-reviewer.md`](../../.claude/agents/gate-failure-reviewer.md)
  — current mandate: diagnose + route to a fresh
  `package-implementer`; produces no fix sign-off. The agent this
  package upgrades.
- [`.claude/agents/pr-reviewer.md`](../../.claude/agents/pr-reviewer.md)
  — current single-model auto-merge checklist; the gate the
  pre-merge independent review is inserted *before*.
- `roadmap_orchestrator/` Python package — `state.py`
  (`record_action`, `record_hw_result`, ledger schema),
  `standup.py` (`upsert_standup` — the "Action items" / "CI under
  repair" sections this package writes the artifact reference
  into). *(Confirm exact module paths in Phase 0; the SKILL
  invokes `python -m roadmap_orchestrator.cli`.)*
- [`.astroray_plan/packages/pkg97-orchestrator-merged-worktree-autogc.md`](pkg97-orchestrator-merged-worktree-autogc.md)
  — sibling orchestrator-change spec; same SKILL.md / Safety-rails
  surface, no code overlap (pkg97 = close-out GC; pkg98 = review
  gate). If both are in flight, the SKILL.md edits are in
  different Steps (pkg97 Step 3, pkg98 Step 2) — rebase, do not
  merge-conflict-resolve blindly.
- Memory `gr-emission-model-wiring-checklist` — the pkg44 ADAF
  three-broken-wires incident; the **complementary integration-test
  requirement** this package explicitly does NOT replace.
- Memory `ci_has_no_gpu_runtime_blindspot` — why green CI alone is
  never sufficient for a render-path feature; the empirical HW
  visual gate is the only real check (hence the HW-gated exclusion).
- Memory `parallel_agent_worktree_contamination` — why review is a
  read-only diff inspection, never a worktree write.

### External (read for understanding only — no code mirrored)

- `gh pr view --json files,labels,headRefName` /
  `gh pr diff <n>` — the diff surface the independent reviewer
  inspects. Authoritative diff source; no working-tree mutation.

---

## Specification

### Phase 0 — locate the gate points (~½ h)

Read-only mapping. Identify exactly:

1. In `SKILL.md`, the two FAIL paths: Step 2.2 (`plan.fixers`
   `kind=="ci"` → `gate-failure-reviewer` then `pkg-ship` CI-fix)
   and Step 2.5 (`plan.hw_failed` → `gate-failure-reviewer`). These
   are where the root-cause + fix sign-off requirement is inserted
   **before any push**.
2. In `SKILL.md`, Step 2.4 (`plan.merges` → `pr-reviewer`). The
   independent pre-merge review is inserted **before**
   `pr-reviewer` is invoked, and only for non-HW-gated packages.
3. The package-classification signal: how a package's pipeline is
   already known to be HW-gated vs not. Reuse the existing
   routing/Track metadata — the package spec frontmatter `Track:`
   plus whether the package has a HW/render acceptance gate
   (the same signal the SKILL already uses to decide `plan.hw_dispatch`
   vs CI-only). Record the exact field/derivation in the PR
   description. **Do not invent a new taxonomy** — if the existing
   metadata does not cleanly separate the two, escalate as an open
   question in the PR rather than adding a new frontmatter key.

Record the file:line of each in the PR description. No behaviour
change in Phase 0.

### Phase 1 — upgrade the `gate-failure-reviewer` mandate (on-failure)

Amend `.claude/agents/gate-failure-reviewer.md` so that, in
addition to the existing diagnosis output, the agent's deliverable
on **any** CI or HW gate FAIL is a two-part artifact:

- **(a) Root-cause analysis** — written, naming the actual defect
  surface (not just "the symptom"), with the distinguishing
  evidence. The existing pkg73-pattern protocol stays; this makes
  the *written root cause* a required, recorded artifact, not just
  console output.
- **(b) Independent different-model sign-off on the proposed fix**
  — once a fix is drafted (by the routed `package-implementer`),
  before it is pushed for re-gate, a **different model** reviews
  the *proposed diff against the root cause* and returns one of:
  - `SIGN-OFF` — the diff demonstrably addresses the named root
    cause; reviewer states *which lines* close it.
  - `BLOCK` — the diff does not address the root cause, addresses
    only a symptom, or introduces a new defect. BLOCK is a real,
    expected outcome. On BLOCK the fix is **not pushed**; the
    SKILL re-routes to a fresh `package-implementer` with the
    BLOCK rationale attached.

Different-model requirement: the sign-off MUST be produced by a
different model lineage than the one that drafted the fix
(e.g. Codex via `codex:rescue`, or the Codex reviewer path). The
agent file states this explicitly and names the concrete
invocation. The reviewer prompt is **adversarial by mandate**: the
reviewer's job is to *independently verify the fix closes the named
root cause by reading the diff and the failing artifact itself* —
NOT to agree that it looks reasonable. The prompt MUST instruct:
"Assume the fix is wrong until the diff proves otherwise; cite the
exact lines that close the root cause or return BLOCK." (Rubber-stamp
decay countermeasure — see the dedicated subsection below.)

SKILL enforcement of "no push before sign-off": amend `SKILL.md`
Step 2.2 / 2.5 so the CI/HW-fix sub-flow is:
diagnose → draft fix → **independent sign-off** → (SIGN-OFF) push
& re-gate **or** (BLOCK) re-route, never push. The push step is
gated on a recorded `SIGN-OFF`; a missing or `BLOCK` verdict means
the fixer branch is **not** pushed this tick and a standup Action
item is written. This is a hard rail added to the Safety-rails
block: *"A gate-failure fix is never pushed for re-gate without a
recorded different-model SIGN-OFF; BLOCK halts the push."*

Artifact recording: the root-cause text + the sign-off verdict
(SIGN-OFF/BLOCK + the reviewing model + one-line rationale) are
recorded via the existing ledger action path
(`state.record_action(ledger, <pr>, "indep_review:SIGN-OFF"` /
`"indep_review:BLOCK")`) **and** surfaced in the standup
"CI under repair" / "Action items" section (PR number, root-cause
one-liner, verdict, reviewing model). No new persisted state file
— reuse the §6 ledger and the standup (design spec §6: ground
truth recomputed each tick).

### Phase 2 — independent pre-merge review for non-HW-gated packages only

Amend `SKILL.md` Step 2.4 (`plan.merges`): before invoking
`pr-reviewer` for a PR, classify the PR's package using the
Phase-0 signal:

- **HW/render-gated package** (has a HW/render acceptance gate;
  the empirical RTX visual gate is its real backstop):
  **NO** extra review. Proceed directly to `pr-reviewer` exactly
  as today. Excluded by design — the visual gate already covers
  it; adding a second review here only adds cost, latency, and
  rubber-stamp decay (memory `ci_has_no_gpu_runtime_blindspot`
  says the HW visual gate *is* the real check for these).
- **Non-HW-gated package** (Track-A engine / orchestrator /
  blender-addon plumbing / docs-with-code — pipeline has **no**
  HW/render gate; CI is the only automated check): dispatch one
  **independent different-model** code review of the PR diff
  against the package spec's acceptance criteria **before**
  `pr-reviewer`. Verdict is `SIGN-OFF` or `BLOCK`:
  - `SIGN-OFF` → proceed to `pr-reviewer` (which still runs its
    full single-model checklist; the independent review is
    *additive*, never a replacement for the §6 license fence or
    the acceptance-criteria check).
  - `BLOCK` → do **not** invoke `pr-reviewer`; write a standup
    Action item (PR number, the integration/logic gap named by
    the reviewer) and route a `gate-failure-reviewer` /
    fresh-implementer pass. The PR is not merged this tick.

Different-model requirement and adversarial prompt: same discipline
as Phase 1 — a different model lineage than the implementer that
wrote the PR; the prompt instructs the reviewer to **independently
verify each acceptance criterion is actually wired into the
shipped code path, not merely unit-tested via direct helpers**
(the exact pkg44 failure mode — cite memory
`gr-emission-model-wiring-checklist` in the reviewer prompt). The
reviewer must trace at least one acceptance criterion end-to-end
through the real entry point, not trust the PR body's "measured
numbers" claim at face value.

Classification precision: the package is HW-gated iff its pipeline
has a HW/render acceptance gate per the existing routing/Track
metadata identified in Phase 0 (the same signal the engine already
uses to decide `plan.hw_dispatch` vs CI-only). Docs-only PRs
(diff touches only `*.md` / `.astroray_plan/`) remain on the
existing `pr-reviewer` doc-only fast path **with** the independent
review applied only when the docs ship alongside code
("docs-with-code"); pure-docs PRs are non-HW-gated but trivially
low-risk and the existing doc-only fast path is preserved (no
independent review on pure-docs — keeps the gate minimal).

### Phase 2b — structure-aware HW-gate acceptance criteria (folded-in scope)

The pkg44 ADAF re-gate (PR #310 → merged commit `11644df`)
exposed a *third*, complementary hole: a structure-blind HW-gate
threshold passed a visually-inadequate render. After the
`enable_adaf` wire was fixed the HW gate measured
`shadow_fraction = 0.0015` and **auto-merged**, but visual
inspection showed only a tiny central shadow dot in an otherwise
uniform background-noise field — the structure pkg44-adaf.md L243
*requires* ("a quasi-spherical glow around the black hole … with
the shadow visible as a dark silhouette") was **not** met. A
`shadow_fraction > 0` check alone is too lenient: mere *presence*
of a dark region is not the spec's intended structure.

Scope (minimal, per-package — **not** a gate-rework): where a
package spec's acceptance criteria demand a specific render
*structure* (e.g. glow-type packages requiring a quasi-spherical /
radially-concentrated intensity profile, not just "a dark region
exists"), the per-package HW-gate acceptance criterion in the
verifier path MUST additionally assert that structure — e.g. a
radial intensity-profile / quasi-spherical-concentration check —
rather than a structure-blind presence-only threshold like bare
`shadow_fraction > ε`. This reuses the package's *existing*
acceptance criteria as the source of the required structure; it
adds **no** new gate framework, no new metric registry, and no
universal structural-gate mandate — only packages whose spec text
already demands structure get the structure-aware assertion, and
the assertion lives in that package's own acceptance criteria /
verifier path, not in the orchestrator.

This is the HW-gated-side analogue of pkg98's independent-review
theme: independent (different-model) review and structure-aware
per-package gate criteria are **complementary** defences against
the same CI/gate blindspot (memory
`ci_has_no_gpu_runtime_blindspot`). Independent review catches
what tests and CI miss on non-HW-gated work; a structure-aware
HW-gate criterion catches what a presence-only threshold rubber-
stamps on HW-gated work. Like independent review, it is **not a
substitute for integration tests** — the end-to-end scene
assertions required by memory `gr-emission-model-wiring-checklist`
(through `add_black_hole`, central-dark-region + radial-falloff)
remain mandatory; the structure-aware gate criterion is a second,
orthogonal line of defence on the empirical visual gate, not a
relaxation of it.

### Rubber-stamp decay — explicit countermeasures

A second model that habitually agrees is worthless. This package
hard-codes three countermeasures, stated in BOTH agent prompts:

1. **Adversarial framing is mandatory, not optional.** The prompt
   opens with "Assume the work is wrong until the diff proves
   otherwise." The reviewer must cite specific lines/files that
   close the root cause (Phase 1) or wire each acceptance criterion
   (Phase 2). "Looks reasonable" / "LGTM" without a line-level
   citation is itself a defect in the review and is treated as
   `BLOCK` (no positive verdict without evidence).
2. **BLOCK is a first-class, expected outcome.** The prompts state
   that BLOCK is the *correct* answer whenever the evidence is not
   conclusive — silence/uncertainty resolves to BLOCK, never to
   SIGN-OFF. A reviewer that never BLOCKs is a signal the gate has
   decayed; the standup surfaces the SIGN-OFF/BLOCK ratio so the
   owner can see decay.
3. **Independent verification, not agreement.** The reviewer must
   re-derive the claim from primary sources (the diff, the failing
   artifact, the spec acceptance criteria) — explicitly forbidden
   from accepting the implementer's narrative or the PR body's
   numbers as proof. Phase 2 reviewers must trace ≥1 criterion
   through the real entry point themselves.

### Files to modify

| File | Change |
|---|---|
| `.claude/agents/gate-failure-reviewer.md` | Add the required two-part deliverable (written root cause + independent different-model fix sign-off with SIGN-OFF/BLOCK); add the adversarial-prompt + BLOCK-is-first-class + independent-verification discipline; name the concrete different-model invocation. No change to the existing pkg73 diagnosis protocol — it is extended, not replaced. |
| `.claude/skills/roadmap-orchestrator/SKILL.md` | Step 2.2 / 2.5: insert "draft fix → independent sign-off → push only on SIGN-OFF; BLOCK halts push + Action item". Step 2.4: insert the non-HW-gated pre-merge independent review before `pr-reviewer` (HW-gated explicitly skips). Safety-rails block: add the two new hard rails. |
| `.claude/agents/pr-reviewer.md` | One sentence noting the independent pre-merge review runs *before* this checklist for non-HW-gated packages and is additive (does not replace the §6 license fence or acceptance check). No checklist logic change. |
| `tests/test_orchestrator_independent_review.py` *(new)* | Unit tests with mocked plan/ledger/`gh` outputs (no real review dispatch, no network) for every gate branch in Acceptance criteria below. |

### Acceptance criteria

- [ ] On a CI-fail PR: the flow requires a recorded different-model
      `SIGN-OFF` before the fixer branch is pushed; a `BLOCK`
      verdict provably prevents the push and writes an Action item
      (mocked: assert no push call issued on BLOCK).
- [ ] On a HW-fail PR (`plan.hw_failed`): same — root-cause
      artifact + sign-off recorded; BLOCK halts re-gate push.
- [ ] The recorded artifact (root-cause text + verdict + reviewing
      model) lands in the ledger via `record_action` AND in the
      standup "CI under repair"/"Action items" section.
- [ ] Non-HW-gated package PR: independent pre-merge review is
      dispatched before `pr-reviewer`; on `BLOCK`, `pr-reviewer`
      is provably **not** invoked and an Action item is written.
- [ ] HW/render-gated package PR: independent pre-merge review is
      provably **skipped**; `pr-reviewer` is invoked exactly as
      today (regression: HW-gated path unchanged).
- [ ] Pure-docs PR: existing `pr-reviewer` doc-only fast path
      preserved; no independent review dispatched.
- [ ] Different-model invariant: the sign-off/review dispatch
      provably targets a different model lineage than the
      fix/PR author (assert the invocation uses the Codex/
      different-model path, not a same-lineage agent).
- [ ] Structure-aware HW-gate (Phase 2b): for a package whose
      spec acceptance criteria demand a render *structure*, the
      per-package HW-gate criterion asserts that structure (e.g. a
      radial-profile / quasi-spherical-concentration check), not a
      structure-blind presence-only threshold; a render that
      reproduces the pkg44 #310 failure mode (`shadow_fraction`
      barely > 0 but no quasi-spherical glow per pkg44-adaf.md
      L243) provably does **not** PASS that criterion. No new gate
      framework introduced (assert: change is per-package
      acceptance-criteria text in the verifier path, not an
      orchestrator-wide gate change).
- [ ] `--dry-run` performs **zero** review dispatches and zero
      ledger/standup mutations (regression guard on design spec §5).
- [ ] Existing orchestrator test suite stays green
      (`pytest tests/test_orchestrator*.py`).
- [ ] Call-site sweep: any changed `state`/`standup` signature and
      the new test grepped repo-wide; SKILL.md + both agent files
      + `pr-reviewer.md` cross-references consistent.

### Hard non-goals

- **No universal every-PR independent review.** HW/render-gated
  packages are explicitly excluded — the empirical RTX visual gate
  is already their real backstop (memory
  `ci_has_no_gpu_runtime_blindspot`); a second review there only
  adds cost, latency, and accelerates rubber-stamp decay. The gate
  is scoped to exactly the two holes pkg44 proved: on-failure fix
  sign-off, and non-HW-gated pre-merge.
- **Not a substitute for integration tests.** Render/emission
  packages must still carry the end-to-end scene assertions
  required by memory `gr-emission-model-wiring-checklist`
  (through `add_black_hole`, central-dark-region + radial-falloff,
  not a hollow signal check). Independent review is an orthogonal
  second line of defence; it does not license shipping without
  those tests, and this package adds no such test-relaxation.
- **No new persisted state file.** Reuse the §6 ledger and the
  per-day standup. No new lock files, no new frontmatter key
  (classification reuses existing routing/Track metadata; if that
  metadata is insufficient, escalate — do not invent a taxonomy).
- **No change to the dual-gate merge rule.** Auto-merge still
  requires CI all-pass AND (for HW-gated) head-SHA-bound hardware
  `PASS`. The independent review is an *additional* pre-`pr-reviewer`
  gate for non-HW-gated packages, never a relaxation of the
  existing gates.
- **No change to the pkg73 diagnosis protocol** in
  `gate-failure-reviewer` beyond making the root cause a recorded
  artifact and adding the fix sign-off step.
- **No automatic override of any BLOCK or HW `FAIL`.** BLOCK and
  HW `FAIL` always halt and escalate to the owner — never
  auto-overridden (design spec §5).
- **No owner-side automation / scheduler change.** The gate lives
  inside the bounded tick, not a separate cron.

---

## Why this matters

The pkg44 #310 session is the empirical proof that a single model
— even a capable one — is not a reliable check on its own work, and
that green CI is not integration coverage for the project's
non-HW-gated half. The catch that prevented a bad fix from shipping
was *off-process luck* (an ad-hoc different-model review), not
policy. This package converts that luck into a permanent invariant
at the minimum scope that closes both holes: *"a gate-failure fix
is never pushed without an adversarial different-model SIGN-OFF,
and every non-HW-gated PR gets one independent different-model
review before merge — while HW-gated packages keep relying on the
empirical visual gate that already works for them."* It encodes,
in the agent prompts themselves, that BLOCK is the expected answer
under uncertainty — the structural defence against the
rubber-stamp decay that kills every review gate that forgets it.

---

## Lessons (filled in on completion)

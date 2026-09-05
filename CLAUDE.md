# CLAUDE.md

## Shell Conventions

- This project runs on Windows; default to PowerShell, not bash. Avoid bash/cmd.exe escaping by invoking build scripts directly.
- When writing PowerShell, avoid reserved automatic variables (`$input`, `$error`, `$host`, `$args`) and ensure UTF-8 for any unicode output.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## 5. Astroray Coordination

- Project status lives in `.astroray_plan/docs/STATUS.md`.
- Work packages live in `.astroray_plan/packages/`.
- Codex is supported alongside Claude Code and opencode (owner directive
  2026-09-05). Its project configuration, hooks, focused subagents, and skill
  bridge live in `.codex/` and `.agents/skills/`. Specs with legacy
  `Codex-paste-ready`/`Track: E` tags remain inert historical metadata and route
  to `package-implementer`, not a special legacy implementation flow.
- Shared repo invariants live in `AGENTS.md`; follow them in addition to this file.
- Keep Claude Code available as the last-line-of-defense judgment path. Codex
  may orchestrate or implement scoped work, and may dispatch bounded grunt,
  implementation, or pre-review work through the existing opencode delegation
  wrapper; it still verifies the resulting evidence rather than trusting it.
- **Cost routing (2026-08):** bounded grunt work (docs flips, lint fixes, report
  assembly, pre-review critique, well-specified gated implementation) goes to
  open-weight models via the `delegate` skill — evidence-verified, never
  trusted. Claude stays on last-line-of-defense judgment: architect/specs,
  cycles-parity, ABI reachability, gate-failure root-cause, merge decisions,
  visual inspection. Tier→model mapping: `.claude/skills/delegate/config/tiers.json`.

### 5c. Product direction, delivery, and visual proof

Astroray's near-term mission is a production-capable Blender/DCC renderer with
Cycles-compatible behavior where applicable and a fast interactive GPU viewport.
The RTX 5070 Ti is the primary hardware gate; CPU rendering remains a
first-class correctness oracle and fallback. Correctness and visual fidelity
outrank performance, while viewport performance is a co-equal product goal.

The eventual destination is research-grade astrophysical simulation and science
visualization: physically meaningful spectra, photon counts, and instrument-like
observables for scenes such as emission nebulae, HMXBs, and relativistic lensing.
Spectral, dispersion, infrared/band-aware, and robust light-transport work is
therefore foundational even while Pillar 4 itself is paused.

When documented gates and independent reviews pass, agents may commit, push,
open PRs, and merge autonomously through the shared workflow. For any visually
meaningful change, save representative render output and have Astra or Claude
inspect it qualitatively alongside numerical gates. Treat a numerical failure as
an investigation of both implementation and test/reference validity. File a
tightly scoped follow-up for valuable tangents (including tooling, benchmarks,
test throughput, project hygiene, hooks, skills, MCPs, or indexing) instead of
mixing it into an unrelated diff.

## 5b. No Duplicate Scripts — Check the Index First

**Before writing ANY new script (render harness, contact sheet, diagnostic,
build helper, verification driver): read `scripts/README.md` — the canonical
per-task index — and Grep `scripts/`, `benchmarks/`, `tools/` for existing
coverage.** The repo has accumulated five parallel "material contact sheet"
generators this way; that must not happen again.

- A canonical script exists → extend it (a flag, a preset entry), don't fork it.
- Genuinely new + reusable → add it AND register it in `scripts/README.md`
  in the same commit.
- One-off (single package verification / debugging) → delete it when the
  package closes; the PR and STATUS.md are the record.

## 6. No Invented Algorithms — Cite, Borrow, Verify

**For any non-trivial physics, sampling, or numerical algorithm: do not
invent when published solutions exist. Invoke the `cite-algorithm` skill
BEFORE writing code** — it walks through finding the canonical paper, a
license-compatible reference implementation, saving research notes to
`.astroray_plan/docs/`, and citing the source in the code itself. When in
doubt whether something is "trivial", treat it as non-trivial.

## Build & Verification

- Always work in the main checkout/worktree the user references; never silently switch to another worktree.
- **Before running any GPU verification:** (1) show the `.pyd` mtime vs `git log -1 --format=%cd HEAD`, (2) if `.pyd` is older, rebuild and re-import, (3) only then run the hardware test. Use `astroray.__file__` to verify a canonical build output is loaded (`build_cuda/` root under the NMake generator; `build_cuda/Release/` only for legacy multi-config builds), not a shadow at the repo root. See [[stale_pyd_locations]] in memory for the failure mode this catches.
- **Before you push:** list every function/class signature you changed in this branch, then Grep the entire repo for each name and show any call sites you did NOT update. Treat tests, mocks, and stubs as first-class call sites. Do this proactively before opening a PR, not reactively after CI fails.
- When CI fails despite the above, re-do the call-site sweep with the actual error context — usually the missed site is a non-obvious caller (test mock, Python binding, conftest helper).

## PR & Git Workflow

- For infrastructure/hook/skill changes that affect the main branch toolchain, commit directly to main (or ask first) — do NOT open a PR that leaves main broken until merge.
- After implementation, always run the full local test suite AND check for stale call sites before pushing.
- When resolving merge conflicts, explicitly state the conflict resolution before committing.

## Design & Co-design

- **When asked for design help, do NOT impose a fixed number of options or force a multiple-choice framing.** Present the actual tradeoff axes seen, and let the owner decide whether to narrow to N options.
- Surface real forks; don't manufacture artificial trichotomies (the "3 options" anti-pattern).
- If only one option is genuinely viable, say so plainly — don't pad with weaker alternatives just to look balanced.

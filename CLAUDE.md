# CLAUDE.md

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
- Codex-specific workflow notes live in `.astroray_plan/agents/codex.md`.
- Shared repo invariants live in `AGENTS.md`; follow them in addition to this file.
- Keep Claude Code on track-A/core work unless a task is explicitly scoped as a small local fix.

## 6. No Invented Algorithms — Cite, Borrow, Verify

**For any non-trivial physics, sampling, or numerical algorithm: cite the
paper or open-source reference, link the source file, and save research
notes to `.astroray_plan/docs/`. Do not invent algorithms when published
ones exist.**

This rule exists because:
- Cycles, Mitsuba, PBRT, LuxCore, RAPTOR, ipole, GYOTO, and the Blender
  Foundation have collectively spent decades solving the rendering and GR
  problems Astroray inherits. Re-deriving their solutions from scratch is
  expensive and almost always worse.
- The journal article that closes this project will cite real papers and
  point at the open-source repos we ported from. Hallucinated provenance
  will not pass review.
- The user's explicit instruction is: *"do real online searches… save
  code, math, concepts… implement it in the context of Astroray. None of
  that hallucination bullshit or trying to come up with your own
  solutions, because you will never beat what has been done."*

How this rule operates in practice:
- Use `WebSearch` and `WebFetch` to locate the canonical paper and a
  permissively-licensed reference implementation **before** writing code.
- Save findings to `.astroray_plan/docs/<topic>-research.md` with: paper
  title + DOI/arXiv ID, license of the reference repo, the specific files
  we will mirror, and the math we will reproduce.
- Cite the source in the C++/Python code itself ("Zeltner 2020 §4.2",
  "Cycles `kernel_path.h:trace_path()`").
- License compatibility is mandatory: Apache-2.0, BSD, MIT, MPL-2.0,
  GPLv2/v3 (only when consistent with our license), or public-domain. Stop
  and ask if the candidate is unclear.
- "Trivial" means: math from undergraduate textbooks, well-known formulas
  (Lambertian cosine, Schlick Fresnel approx, Halton sequences),
  language-level utilities. When in doubt, treat as non-trivial.

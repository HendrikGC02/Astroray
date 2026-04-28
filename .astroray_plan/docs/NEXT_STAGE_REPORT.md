# Astroray Next Stage Report

**Date:** 2026-04-28  
**Prepared by:** Codex  
**Scope:** repo orientation, Codex setup, next-stage planning, agent workflow,
local-model integration, and rendering/test-result review.

## Current State

Astroray is at a clean transition point:

- Pillar 1, plugin architecture, is done.
- Pillar 2, spectral core, is done.
- Pillar 3, light transport, is the next primary engineering pillar.
- Pillar 4, astrophysics platform, can start in parallel only where work is
  independent of ReSTIR/NRC transport decisions.
- Pillar 5, production polish, should continue opportunistically.

Live repo observations:

- Branch at orientation time: `main`, clean.
- GitHub PRs: none open.
- GitHub issues: five open production/Cycles-parity issues: #29, #30, #36,
  #38, #39.
- Tests collected locally on 2026-04-28: 227.
- Current full-suite baseline on 2026-04-28:
  `207 passed, 1 skipped, 19 xfailed`.
- The latest saved historical pytest log in `test_results/` is older
  (2026-04-15, 112 tests), so it should not be used as the current baseline.

## Setup Changes Made

- Added `.astroray_plan/agents/codex.md` so Codex has a first-class role beside
  Claude Code, Copilot, Cline, and Ralph.
- Added `.astroray_plan/docs/local-agent-integration.md` with a practical
  Ollama/LM Studio/Cline/Codex integration plan.
- Updated `AGENTS.md`, `CLAUDE.md`, README test count, and Copilot instructions
  to reflect the current plugin/spectral architecture.
- Corrected stale Copilot guidance that referenced removed architecture such as
  `src/renderer.cpp` and the deleted legacy RGB path tracer.

## Rendering And Test Findings

### 1. GR black-hole dispatch is the biggest visible correctness gap

The black-hole-only smoke render currently passes while producing a fully black
PNG. Two stronger GR tests are marked xfail with the reason:
`black hole GR dispatch not ported to pathTraceSpectral`.

Impact:

- Pillar 2's spectral path-tracer flip left GR rendering partially disconnected.
- The xfails are honest, but the passing smoke test is too weak.
- This should be fixed before Pillar 4 Kerr work, otherwise Kerr development
  will build on a broken integration point.

Recommended next work:

1. Create `pkg15-gr-spectral-dispatch.md`.
2. Port black-hole GR dispatch into the current `path_tracer` integrator path.
3. Strengthen `test_black_hole_creation` so it checks visible signal, not just
   finite pixels.
4. Un-xfail `test_black_hole_shadow_is_dark` and
   `test_black_hole_extreme_disk_remains_finite`.

Owner: Claude Code or Codex. This is not a Copilot task.

### 2. Spectral-vs-RGB A/B tests are stale after pkg14

Some tests still describe "RGB vs spectral" parity, but the legacy RGB path was
deleted and `path_tracer` is now the spectral-first default. At least one test
renders `path_tracer` twice and compares the images to each other.

Impact:

- The tests still catch determinism/noise problems, but no longer validate
  parity against an independent RGB implementation.
- Future agents may falsely believe an RGB reference path still exists.

Recommended next work:

1. Rename stale tests and comments from RGB-vs-spectral to deterministic
   spectral A/B where that is what they do.
2. Add explicit golden metric tests around important spectral conversions
   rather than relying on a deleted renderer path.
3. Keep saved diff PNGs where useful, but do not present them as RGB parity.

Owner: Codex or Ralph for comments/names; Claude Code for any assertion redesign.

### 3. Some test-result PNGs are intentionally black or binary, but the suite
needs an image-quality triage command

The PNG review found expected black images such as black-background tests and
diff images, plus area-light footprint images that are binary masks by design.
The suspicious part is not the presence of black files; it is that the repo has
no standard command to distinguish expected black outputs from accidental black
renders.

Recommended next work:

1. Add a small non-shipping script under `scripts/` that reports image
   dimensions, mean brightness, max value, and tiny file sizes for
   `test_results/*.png`.
2. Use the report in PR review, not as a hard CI gate at first.
3. Promote individual checks into pytest only after a pattern is confirmed.

Owner: Codex or Ralph.

## Next Engineering Stage

### Phase 0: Stabilize after the spectral flip

Do this before ReSTIR:

- Fix GR dispatch in the current spectral `path_tracer`.
- Clean stale RGB-vs-spectral test wording.
- Update package docs so pkg14 completion is reflected everywhere agents look.
- Add a render-output triage script.

### Phase 1: Scope Pillar 3 into small packages

Create concrete package files before coding:

- `pkg20-reservoir-core.md`: reservoir struct, invariants, tests.
- `pkg21-light-sample-abstraction.md`: direct-light sample representation
  usable by ReSTIR without changing material conventions.
- `pkg22-restir-initial-sampling.md`: initial candidate generation only.
- `pkg23-restir-temporal-spatial-design.md`: design and CPU/GPU boundary.
- `pkg25-tiny-cuda-nn-prototype.md`: local prototype only, no production code.

Do not begin with full temporal/spatial ReSTIR. Start with a reservoir unit and
a validation scene.

### Phase 2: Parallelize safely

- Claude Code: GR dispatch fix and ReSTIR design/implementation packages.
- Codex: package writing, PR review, CI triage, test cleanup, docs alignment.
- Copilot: only plugin-pattern issues with exact file scope.
- Cline/local model: tiny-cuda-nn build experiment and disposable prototypes.
- Ralph/local model: registry tests, doc cleanup, render-output statistics.

### Phase 3: Refresh GitHub issues

Current open issues are useful, but they are mostly production/Cycles-parity
work. They do not yet represent the next pillar. Create new Pillar 3 issues
from the packages above, label them by track, and assign only the narrow ones
to Copilot.

## Suggested Immediate Issues

1. #111 `fix: restore black-hole GR dispatch in spectral path_tracer`
   - Track: A/Codex
   - Blocks: Pillar 4
   - Non-goal: Kerr

2. #112 `test: remove stale RGB-vs-spectral assumptions after pkg14`
   - Track: Codex/Ralph
   - Scope: tests and comments only unless an assertion is wrong

3. #113 `chore: add render-output triage script for test_results PNGs`
   - Track: Codex/Ralph
   - Output: text report, no CI failure yet

4. #114 `plan: add pkg20-pkg23 Pillar 3 ReSTIR package specs`
   - Track: Codex/Claude Code
   - Output: package markdown files

5. #115 `proto: tiny-cuda-nn dummy inference branch`
   - Track: Cline/local model
   - Output: prototype branch notes, not a mergeable PR

## Local Model Recommendation

Use Ollama first, LM Studio second. As of the checked docs, Codex CLI supports
local/offline model runs through local Responses-compatible endpoints, and
Cline has first-class Ollama/LM Studio local model guidance. The practical
model target is `qwen3-coder:30b` if hardware allows; use smaller models only
for mechanical tasks.

Important caveat: local models are cost savers, not final authority. They should
draft and grind. Codex or Claude Code should review and integrate.

Sources:

- OpenAI Codex agent loop and local endpoint behavior:
  https://openai.com/index/unrolling-the-codex-agent-loop/
- Cline local model guidance:
  https://docs.cline.bot/running-models-locally/overview
- Ollama Cline integration:
  https://docs.ollama.com/integrations/cline
- Ollama Qwen3 Coder tags:
  https://ollama.com/library/qwen3-coder

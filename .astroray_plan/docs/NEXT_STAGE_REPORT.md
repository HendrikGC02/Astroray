# Astroray Next Stage Report

**Date:** 2026-04-29  
**Prepared by:** Codex  
**Scope:** reconcile the 2026-04-28 next-stage snapshot with the live repo,
verify Pillar 2 stability expectations, and line up the first Pillar 3 package
specs.

## Current State

Astroray is no longer at the "figure out what Phase 0 is" point.

- Pillar 1, plugin architecture, is complete.
- Pillar 2, spectral core, is complete.
- The main Phase 0 stabilization items from the previous report are already
  landed on `main`:
  - spectral black-hole GR dispatch restoration
  - render-output triage script
  - deterministic spectral test refresh
- Pillar 3 is now scoped through package specs `pkg20` to `pkg25`.

## What Changed Since The Previous Report

The 2026-04-28 report correctly identified the main post-pkg14 cleanup themes,
but several of its "next work" bullets are now historical:

1. GR dispatch restoration is no longer pending.
   - `STATUS.md` records PR #117 as merged.
   - Black-hole tests now include native spectral dispatch checks.

2. Render-output triage is no longer pending.
   - `scripts/render_output_triage.py` exists and is already tracked in
     `STATUS.md`.

3. ReSTIR package creation is no longer pending.
   - `pkg20` through `pkg24` already exist.
   - This pass adds `pkg25-tiny-cuda-nn-prototype.md` so the first NRC
     prototype step is also explicitly scoped.

## Remaining Stabilization Work

Pillar 2 is functionally complete, but there are still two useful cleanup
tracks before heavy Pillar 3 implementation starts:

1. Keep docs and test wording aligned with the spectral-first architecture.
   - Remove stale `path` / `pathTraceSpectral` language where it now refers to
     the canonical `path_tracer`.
   - Keep historical notes as historical notes, but avoid presenting them as
     current state.

2. Keep Windows verification reproducible.
   - On this workstation, the old `build/` cache points at a missing MinGW
     install.
   - The test bootstrap now supports `ASTRORAY_BUILD_DIR` and standard
     `build/Release` layouts so collection can succeed against a valid build.

## Verification Notes

Current local verification on 2026-04-29:

- `pytest --collect-only -q` succeeds with `229 tests collected` when pointed
  at a valid Windows build via `ASTRORAY_BUILD_DIR`.
- Full suite baseline on the fresh MSVC build:
  `211 passed, 1 skipped, 16 xfailed, 1 xpassed`.
- A fresh local MSVC build under `build_codex/Release` imports cleanly.
- The old repo `build/` directory remains a stale cache problem on this
  workstation, not a source-level regression.

## Pillar 3 Package State

Package specs now in repo:

- `pkg20-reservoir-core.md`
- `pkg21-light-sample-abstraction.md`
- `pkg22-restir-initial-sampling.md`
- `pkg23-restir-temporal-spatial-design.md`
- `pkg24-restir-validation.md`
- `pkg25-tiny-cuda-nn-prototype.md`

Recommended implementation order remains:

1. `pkg20` reservoir core
2. `pkg21` light-sample abstraction
3. `pkg22` initial sampling
4. `pkg23` temporal/spatial reuse design scaffolding
5. `pkg24` validation

`pkg25` stays explicitly separate because it is a prototype/feasibility track,
not a blocker for ReSTIR implementation.

## Suggested Next Work

### Track A / Claude Code

- Start implementation review for `pkg20-reservoir-core`.
- Keep PR #119 (`native-gr-spectrum`) moving if it is still the active GR
  follow-up.

### Track E / Codex

- Keep package specs, status docs, and test wording aligned.
- Triage Windows build/test friction when the canonical `build/` cache is stale.
- Review early ReSTIR PRs for invariants and acceptance-criteria drift.

### Track B / Copilot

- Restrict to narrow, pattern-matching work only after `pkg20`/`pkg21` design
  decisions are settled.
- Good candidates: focused tests, helper extraction, doc/comment cleanup.

### Track C / Local Prototype

- `pkg25` should happen only on the user's normal experiment machine, not in
  this current session/environment.
- No local-model or prototype agent work was used in this pass.

## Practical Conclusion

The repo is past "what should we do next?" and into "start Pillar 3 carefully."

The right near-term move is:

1. treat Pillar 2 as complete but keep docs/tests honest,
2. begin with `pkg20`,
3. keep `pkg25` as a separate feasibility lane,
4. avoid conflating stale workstation build caches with renderer regressions.

# pkg24 — ReSTIR Validation

**Pillar:** 3
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~6 h)
**Depends on:** pkg22, pkg23

---

## Goal

**Before:** ReSTIR DI has initial sampling and a temporal/spatial reuse
design, but no robust validation harness for bias, variance, or visual
regressions.

**After:** Astroray has focused ReSTIR validation scenes and tests that
compare `restir-di` against vanilla `path_tracer` using finite checks,
brightness/error tolerances, and saved render outputs for visual review.

---

## Context

ReSTIR can look better while being wrong. Validation must land before
aggressive reuse or CUDA optimization, otherwise later agents will not
know whether an image-quality improvement is unbiased, scene-specific,
or a test artifact.

---

## Reference

- Design doc: `.astroray_plan/docs/light-transport.md §Acceptance criteria`
- Previous packages: pkg22 initial sampling, pkg23 reuse design
- Existing render-output triage: `scripts/render_output_triage.py`

---

## Prerequisites

- [ ] pkg22 initial sampling is merged.
- [ ] pkg23 design note is merged or explicitly reviewed.
- [ ] Baseline path-tracer validation scenes are deterministic enough
      for tolerance-based comparisons.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_restir_validation.py` | ReSTIR-vs-path-tracer finite, brightness, and low-sample quality checks. |
| `tests/restir_helpers.py` | Shared many-light scene builders and image metric helpers if tests grow beyond one file. |
| `test_results/restir_*` | Generated PNGs/charts from tests; gitignored, used for visual QA. |

### Files to modify

| File | What changes |
|---|---|
| `scripts/render_output_triage.py` | Optional: add ReSTIR-specific labels or contact-sheet support if needed for review. |
| `.astroray_plan/docs/light-transport.md` | Record accepted validation scenes and metrics. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg24 active/done and surface the next Pillar 3 package. |

### Key design decisions

- Use metrics that tolerate Monte Carlo noise: mean luminance,
  center/edge comparisons, finite checks, and broad error thresholds.
- Save images for human review, but do not require pixel-perfect
  reference images in git.
- Prefer small deterministic scenes over one expensive showcase.
- This package is **Copilot-safe for test expansion** after Claude/Codex
  defines the first validation scene and thresholds.

---

## Acceptance criteria

- [ ] `restir-di` validation renders are finite and non-black.
- [ ] Low-sample `restir-di` output is not systematically darker than
      vanilla `path_tracer` on many-light scenes.
- [ ] A converged comparison test catches obvious bias without requiring
      impractically high sample counts.
- [ ] Render-output triage can be run after validation tests and does
      not flag the ReSTIR images as all-black or low-color-count unless
      the test intentionally creates a mask/difference image.
- [ ] Full pytest passes.

---

## Non-goals

- Do not implement new ReSTIR algorithm stages.
- Do not add CUDA optimization.
- Do not add heavyweight binary reference images to git.
- Do not claim production readiness solely from these tests.

---

## Progress

- [ ] Add many-light helper scene.
- [ ] Add finite/non-black validation.
- [ ] Add ReSTIR-vs-path-tracer comparison.
- [ ] Document accepted thresholds.

---

## Lessons

*(Fill in after the package is done.)*

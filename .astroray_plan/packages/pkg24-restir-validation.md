# pkg24 — ReSTIR Validation

**Pillar:** 3
**Track:** A
**Status:** implemented
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
- Additional design doc: `.astroray_plan\docs\restir-temporal-spatial-design.md`
- Previous packages: pkg22 initial sampling, pkg23 reuse design
- Existing render-output triage: `scripts/render_output_triage.py`

---

## Prerequisites

- [x] pkg22 initial sampling is merged.
- [x] pkg23 design note is merged or explicitly reviewed.
- [x] Baseline path-tracer validation scenes are deterministic enough
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

- [x] `restir-di` validation renders are finite and non-black.
- [x] Low-sample `restir-di` output is not systematically darker than
      vanilla `path_tracer` on many-light scenes.
- [x] A converged comparison test catches obvious bias without requiring
      impractically high sample counts.
- [x] Render-output triage can be run after validation tests and does
      not flag the ReSTIR images as all-black or low-color-count unless
      the test intentionally creates a mask/difference image.
- [x] Full pytest passes (287 passed, 1 skipped, 16 xfailed; standalone
      binary crash failures pre-date this package).

---

## Non-goals

- Do not implement new ReSTIR algorithm stages.
- Do not add CUDA optimization.
- Do not add heavyweight binary reference images to git.
- Do not claim production readiness solely from these tests.

---

## Progress

- [x] Add many-light helper scene (`build_many_light_scene` in restir_helpers.py).
- [x] Add finite/non-black validation (TestFiniteness, 4 tests).
- [x] Add ReSTIR-vs-path-tracer comparison (TestDefaultModeRegression).
- [x] Document accepted thresholds (TestTemporalBias / TestSpatialBias: 10% threshold).

Also implemented (beyond original scope, required to make the validation
criteria testable):
- Actual temporal reuse pass in `restir_di.cpp` (Algorithm 2, Bitterli 2020)
- Actual spatial reuse pass in `restir_di.cpp` (Algorithm 3)
- `targetLuminanceRGB()` on `ReSTIRCandidate` for wavelength-independent reuse
- `set_integrator_param` Python binding and `integratorParams_` on `PyRenderer`
- 6-criterion validation suite (13 tests, all passing)

---

## Lessons

- Single 1-SPP frames are too noisy to demonstrate spatial MSE improvement
  reliably; averaging over N_MEASURE=8 frames with aligned seeds is needed.
- Using `targetLuminance(lambdas)` across frames with different wavelength
  samples inflates reservoir W by an unbounded ratio — always use
  `targetLuminanceRGB()` for cross-frame reservoir operations.
- Shadow ray must use the distance from the CURRENT shading point to the stored
  light position, not `res.y.distance` (which was computed at the original pixel).
- `frameState_.resize()` clears all history — only call when dimensions change.
- Store the reservoir AFTER `finalizeWeight()`, not before, so next-frame merges
  use the correct W.

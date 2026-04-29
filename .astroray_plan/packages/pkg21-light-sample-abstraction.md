# pkg21 — ReSTIR Light Sample Abstraction

**Pillar:** 3
**Track:** A
**Status:** implemented
**Estimated effort:** 1 session (~3 h)
**Depends on:** pkg20

---

## Goal

**Before:** direct-light sampling is embedded in the spectral path
tracer's next-event-estimation loop and cannot be reused by ReSTIR
candidate generation.

**After:** direct-light candidates have a compact, renderer-agnostic
representation that can be evaluated by vanilla NEE and future ReSTIR
passes.

---

## Context

ReSTIR resamples light candidates, not arbitrary path vertices. The
candidate payload must include the sampled light, position/direction,
emission, PDFs, and enough metadata to re-evaluate a target function
later. This package extracts representation and evaluation helpers only;
the path tracer should still render the same images.

---

## Reference

- Design doc: `.astroray_plan/docs/light-transport.md §ReSTIR DI`
- Existing code: `include/raytracer.h` `LightSample`, `LightList`,
  `Renderer::pathTraceSpectral()`
- Depends on: `.astroray_plan/packages/pkg20-reservoir-core.md`

---

## Prerequisites

- [ ] pkg20 reservoir core is merged.
- [ ] Full pytest passes on `main`.
- [ ] A maintainer has confirmed the candidate payload fields before
      implementation begins.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/restir/light_sample.h` | ReSTIR candidate payload and helper functions for target luminance/validity. |
| `tests/test_restir_light_sample.py` | Tests for finite payloads, zero-PDF rejection, and target-weight behavior. |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | Optional: factor existing `LightSample` fields or add adapter helpers. Keep changes narrow. |
| `plugins/integrators/spectral_path_tracer.cpp` | Optional: use the helper for NEE weight evaluation only if it is behavior-preserving. |
| `CMakeLists.txt` | Add test helper target only if needed. |

### Key design decisions

- The abstraction should be spectral-aware: target weights derive from
  `SampledSpectrum.toXYZ(lambdas).Y` or an equivalent luminance helper.
- Keep visibility separate. Candidate creation/evaluation should not
  trace shadow rays in this package.
- Existing `LightSample` can remain; this package may add adapters
  instead of renaming core types.
- This package is **Copilot-safe with constraints**: source extraction
  and tests are mechanical, but Claude/Codex should review the target
  weight definition and any path-tracer touch.

---

## Acceptance criteria

- [x] ReSTIR candidate payload has documented fields and validity rules.
- [x] Zero/negative/NaN PDFs and non-finite emissions are rejected or
      sanitized consistently.
- [x] Spectral target-weight helper is covered by tests.
- [x] Existing path-tracer output remains unchanged within deterministic
      tolerance if any NEE helper is refactored.
- [x] No reservoir use, temporal reuse, spatial reuse, CUDA kernels, or
      new user-facing integrator is added.
- [x] Full pytest passes.

---

## Non-goals

- Do not implement ReSTIR initial sampling.
- Do not trace visibility or shadow rays inside candidate helpers.
- Do not add frame history.
- Do not change material or BSDF sampling behavior.

---

## Progress

- [x] Define candidate payload. (`include/astroray/restir/light_sample.h`)
- [x] Add target-weight/validity helpers. (`isValid()`, `targetLuminance()`, `fromLightSample()`)
- [x] Add focused tests. (`tests/test_restir_light_sample.py` — 22 tests, all pass)
- [ ] Optionally refactor NEE to use the helper with no visual change.

---

## Lessons

*(Fill in after the package is done.)*

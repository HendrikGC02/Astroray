# pkg20 — ReSTIR Reservoir Core

**Pillar:** 3
**Track:** A
**Status:** open
**Estimated effort:** 1 session (~3 h)
**Depends on:** pkg14

---

## Goal

**Before:** Astroray has direct-light sampling inside the spectral path
tracer, but no reusable reservoir type or tests for ReSTIR-style
weighted sample replacement.

**After:** the repo has a small, deterministic reservoir core with clear
invariants, unit tests, and no renderer integration. Later ReSTIR
packages can depend on this type without designing the math again.

---

## Context

ReSTIR DI depends on a correct reservoir update rule before any renderer
work is useful. This package deliberately avoids scene sampling,
visibility, temporal reuse, spatial reuse, and CUDA kernels. It creates
the smallest tested primitive: a weighted reservoir that can ingest
candidates and retain one representative sample with the right
probability and aggregate weights.

---

## Reference

- Design doc: `.astroray_plan/docs/light-transport.md §ReSTIR DI`
- Paper: Bitterli et al. 2020, "Spatiotemporal reservoir resampling for
  real-time ray tracing with dynamic direct lighting"
- RTXDI SDK: https://github.com/NVIDIA-RTX/RTXDI

---

## Prerequisites

- [ ] Pillar 2 is complete and `path_tracer` is spectral-first.
- [ ] Full pytest passes on `main`.
- [ ] ReSTIR package specs pkg20-pkg24 are merged or this package is
      reviewed against issue #114.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/restir/reservoir.h` | Header-only `Reservoir<T>` or concrete `LightReservoir` core with update, merge, reset, and invariant helpers. |
| `tests/test_restir_reservoir.py` | Statistical and deterministic tests for update/merge behavior through a minimal binding or compiled helper. |

### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | Add any tiny test helper target if Python cannot directly exercise the reservoir type. |
| `module/blender_module.cpp` | Only if needed to expose a private test helper; production API exposure is a non-goal. |

### Key design decisions

- The reservoir stores `w_sum`, `M`, final weight `W`, and a selected
  candidate. Names should match ReSTIR literature unless a stronger
  local convention exists.
- Randomness is injected by the caller as `std::mt19937&`; the reservoir
  does not own RNG state.
- Tests should favor deterministic seeded checks plus coarse
  distribution sanity, not brittle exact stochastic histograms.
- This package is **Copilot-safe** if the implementer is restricted to
  the two new files and test helper plumbing. Claude/Codex should review
  math and naming before merge.

---

## Acceptance criteria

- [ ] Reservoir reset/update/merge invariants are covered by tests.
- [ ] Zero, negative, NaN, and infinite candidate weights are handled
      deterministically and do not poison stored state.
- [ ] Seeded update sequences produce stable selected-candidate results.
- [ ] A simple weighted selection distribution test passes with a loose
      tolerance.
- [ ] No renderer, integrator, scene, CUDA, or Blender UI behavior
      changes.
- [ ] Full pytest passes.

---

## Non-goals

- Do not add a ReSTIR integrator.
- Do not sample scene lights.
- Do not add temporal or spatial reuse.
- Do not add CUDA kernels.
- Do not expose user-facing Python or Blender ReSTIR settings.

---

## Progress

- [ ] Add reservoir type.
- [ ] Add deterministic invariant tests.
- [ ] Add loose statistical selection test.
- [ ] Update status/changelog notes when merged.

---

## Lessons

*(Fill in after the package is done.)*

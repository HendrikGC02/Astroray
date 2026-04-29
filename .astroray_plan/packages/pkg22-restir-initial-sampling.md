# pkg22 — ReSTIR Initial Sampling

**Pillar:** 3
**Track:** A
**Status:** implemented
**Estimated effort:** 2 sessions (~6 h)
**Depends on:** pkg20, pkg21

---

## Goal

**Before:** Astroray has reservoirs and light-candidate helpers, but no
integrator path that uses them to generate per-pixel direct-light
reservoirs.

**After:** an opt-in `restir-di` prototype integrator performs initial
candidate generation for direct lighting and renders finite images.
There is no temporal or spatial reuse yet.

---

## Context

Initial sampling is the first image-producing ReSTIR package. It should
prove that the reservoir and candidate abstractions can replace the
vanilla direct-light NEE slot without pulling in history buffers or
neighbor reuse. The output may be noisier than final ReSTIR; correctness
and finite behavior matter more than speed.

---

## Reference

- Design doc: `.astroray_plan/docs/light-transport.md §Phase 3B`
- Existing integrators: `plugins/integrators/spectral_path_tracer.cpp`,
  `plugins/integrators/ambient_occlusion.cpp`
- Depends on: pkg20 reservoir core, pkg21 light sample abstraction

---

## Prerequisites

- [ ] pkg20 and pkg21 are merged.
- [ ] `integrator_registry_names()` and `set_integrator()` tests are
      green on `main`.
- [ ] A small many-light validation scene is available or scoped in this
      package.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/integrators/restir_di.cpp` | Registers `"restir-di"` and implements initial candidate generation only. |
| `tests/test_restir_initial_sampling.py` | Tests registration, finite rendering, deterministic seeded behavior, and simple brightness sanity. |

### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | Compile the new integrator plugin. |
| `include/astroray/restir/*.h` | Add helper functions only when needed by initial sampling. |
| `module/blender_module.cpp` | Add integrator registry exposure only if the generic registry path does not already surface it. |

### Key design decisions

- Keep the classic `path_tracer` unchanged. `restir-di` is opt-in and
  allowed to be prototype-quality.
- Candidate count should be a small fixed constant first, exposed as a
  parameter only after the algorithm is validated.
- No GPU-first work here. CPU implementation is acceptable for tests and
  algorithm validation.
- This package is **Claude/Codex-only for implementation** because it
  introduces the first image-producing ReSTIR path. Copilot can assist
  with tests after the design is in place.

---

## Acceptance criteria

- [x] `"restir-di"` appears in `integrator_registry_names()`.
- [x] A simple scene renders finite, non-black pixels through
      `set_integrator("restir-di")`.
- [x] Seeded renders are deterministic.
- [x] A scene with multiple small lights is not dramatically darker than
      vanilla `path_tracer` at the same samples.
- [x] No temporal reuse, spatial reuse, frame history, or CUDA kernels
      are added.
- [x] Full pytest passes.

---

## Non-goals

- Do not optimize performance.
- Do not add temporal or spatial reuse.
- Do not change the default integrator.
- Do not expose Blender UI controls beyond the existing integrator
  selection path.

---

## Progress

- [x] Add `restir-di` plugin skeleton. (`plugins/integrators/restir_di.cpp`)
- [x] Implement initial candidate generation. (RIS with N=4 candidates, `Reservoir<ReSTIRCandidate>`)
- [x] Add registration/render tests. (`tests/test_restir_initial_sampling.py` — 8 tests, all pass)
- [x] Add a small many-light validation scene or helper. (3-light floor scene in tests)

---

## Lessons

*(Fill in after the package is done.)*

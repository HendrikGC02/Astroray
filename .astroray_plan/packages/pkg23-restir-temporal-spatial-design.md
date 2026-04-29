# pkg23 — ReSTIR Temporal and Spatial Reuse Design

**Pillar:** 3
**Track:** A
**Status:** implemented
**Estimated effort:** 2 sessions (~6 h)
**Depends on:** pkg22

---

## Goal

**Before:** `restir-di` can generate initial direct-light reservoirs per
pixel, but each pixel/frame stands alone.

**After:** the repo has reviewed design scaffolding for temporal and
spatial reuse: frame buffers, reprojection inputs, neighbor selection,
bias guards, and CPU/GPU boundaries. Implementation may include a
minimal CPU spatial reuse pass if it stays small, but the main output is
a concrete design ready for pkg24 validation and later CUDA work.

---

## Context

Temporal and spatial reuse create most of ReSTIR's quality win, but they
also create most of its bias and state-management risk. This package
exists to prevent a large unreviewable jump from initial sampling to
full reuse. It should make history ownership and validation strategy
explicit before performance work begins.

---

## Reference

- Design doc: `.astroray_plan/docs/light-transport.md §ReSTIR DI`
- Previous package: `.astroray_plan/packages/pkg22-restir-initial-sampling.md`
- RTXDI SDK history/reservoir management patterns

---

## Prerequisites

- [x] pkg22 is merged and `restir-di` initial sampling renders finite
      images.
- [x] A target validation scene exists for direct-light reuse.
- [x] The project owner or maintainer confirms whether first reuse
      implementation should be CPU-only, CUDA-only, or staged.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `.astroray_plan/docs/restir-temporal-spatial-design.md` | Design note covering history buffers, reprojection data, spatial neighborhoods, validation gates, and GPU boundary. |
| `include/astroray/restir/frame_state.h` | Optional skeleton for frame-indexed reservoir/history ownership if implementation begins here. |
| `tests/test_restir_reuse_design.py` | Optional source/structure tests if skeleton types are added. |

### Files to modify

| File | What changes |
|---|---|
| `plugins/integrators/restir_di.cpp` | Optional minimal hook points for frame state; avoid shipping incomplete reuse behavior. |
| `.astroray_plan/docs/light-transport.md` | Link the detailed design note and update package names. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg23 active/done as appropriate. |

### Key design decisions

- Treat temporal reuse as a state-ownership problem first. Define how
  frame index, camera data, and previous reservoirs are invalidated.
- Treat spatial reuse as an algorithmic pass over existing reservoirs,
  not as another light-sampling path.
- Bias checks are part of the design, not deferred to "later."
- This package is **Claude/Codex-only**. It is too architecture-heavy
  for an unsupervised Copilot implementation, though Copilot can draft
  boilerplate once the design note is accepted.

---

## Acceptance criteria

- [x] Design note documents temporal inputs, invalidation rules,
      spatial neighborhood policy, target weight re-evaluation, and bias
      risks.
- [x] CPU/GPU split is explicit: what ships now, what moves to CUDA
      later, and what data layout must remain stable.
- [x] pkg24 validation plan is concrete enough for another agent to
      implement without redesigning.
- [x] If any code skeleton is added, it is covered by tests and does not
      alter current render output.
- [x] Full pytest passes.

---

## Non-goals

- Do not ship full temporal reuse without validation.
- Do not add CUDA kernels unless explicitly approved before starting.
- Do not change default rendering behavior.
- Do not optimize memory layout prematurely.

---

## Progress

- [x] Draft design note. (`.astroray_plan/docs/restir-temporal-spatial-design.md`)
- [x] Review CPU/GPU boundary.
- [x] Add optional frame-state skeleton. (`include/astroray/restir/frame_state.h`, `tests/test_restir_reuse_design.py`)
- [x] Update light-transport docs with accepted package sequence.

---

## Lessons

- Staging the frame-state skeleton as a separate header with no active render impact is the right pattern: it makes the design concrete and testable without changing render behavior, and pkg24 can enable the passes incrementally.
- The `FrameStateHelper` pybind11 binding (with `set_prev_pixel` writing directly to the previous buffer) makes temporal validity tests fast and direct without requiring a full render loop.
- `selectSpatialNeighbors` uses `std::mt19937` directly; passing a `seed` to the Python binding avoids state-sharing between test cases.

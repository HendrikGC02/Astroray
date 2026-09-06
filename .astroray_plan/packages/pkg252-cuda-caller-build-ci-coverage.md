# pkg252 — CUDA caller and target build coverage in CI

**Pillar:** 5
**Track:** A
**Status:** open — detailed architect review required before implementation
**Estimated effort:** S/M, confirm after trial
**Depends on:** pkg250

---

## Goal

Before: CI does not prove that a host C++ caller compiles under the
production CUDA/N3 configuration, nor that the complete CUDA standalone
target links — a full clean Windows CUDA ALL_BUILD on main f30bc5f failed
at apps/main.cpp:277 while existing CI success did not contradict that
local compiler failure. After: CI coverage is audited and a sufficient
CUDA-host compile/target-link gate is selected through measured
comparison, Astra and independent review, so that a deleted-call defect
like the pkg55-C7 survivor fails the proposed gate while repaired source
passes.

---

## Context

This package serves Pillar 5 (reliable delivery). Pkg250 repairs the
caller; this package owns prevention, and pkg250 provides the failure
evidence. A measured coverage proposal and architect review are required
before implementation. Coordinate workflow ownership with pkg240 so two
workers never edit the same workflow.

---

## Evidence

- A full clean Windows CUDA ALL_BUILD on main f30bc5f failed at
  apps/main.cpp:277: its CUDARenderer::render caller survived removal of
  that method in pkg55-C7.
- The CUDA CI job compiles individual .cu files; the host job builds
  without CUDA.
- Neither gate proves a host C++ caller compiles under the production
  CUDA/N3 configuration, nor that the complete CUDA standalone target
  links.
- Existing CI success therefore did not contradict this local compiler
  failure.

---

## Reference

- `test_results/rebuild-handoff-20260906/engine-cuda-full-build.log`
- `.github/workflows/ci.yml`

---

## Prerequisites

- [ ] TBD

---

## Specification

### Files to create

None.

### Files to modify

None.

### Key design decisions

- Audit effective macros, translation units and targets covered by each
  CI build. Record production N3-on, CUDA N3-off and CPU-only
  reachability, including standalone and binding callers. Do not count
  preprocessing-disabled code as compiled implementation coverage.
- Compare a bounded CUDA-host compile gate with an actual target-link
  gate using the existing CMake targets/scripts. Measure matched-revision
  added latency and cost; select sufficient coverage through Astra and
  independent review before workflow changes. Coordinate pkg240 so two
  workers never edit the same workflow.
- Preserve required check names/trust boundaries, docs-only routing,
  CUDA source coverage and honest failures. Test internal PR, push and
  fork behavior.
- Document remaining GPU/runtime limitations and retain actual
  RTX/Blender hardware and visual gates for releases. Keep cold build
  optimization in pkg231.

---

## Acceptance criteria

- [ ] Demonstrate that the original deleted-call defect fails the
      proposed gate, while repaired source passes.
- [ ] Add a relevant configuration/link failure probe if the selected
      gate claims link coverage.

---

## Non-goals

- No unconditional second full expensive CI build without measured
  justification.
- No blanket CI restructuring, reduced tests, threshold relaxation, new
  parallel build wrapper, or GPU render claim from syntax checks.
- No hardware runtime claim from CI.
- Filing does not change the owner's pkg241/240 priority or any
  astrophysics pause.

---

## Progress

- (none yet)

---

## Lessons

- (none yet)

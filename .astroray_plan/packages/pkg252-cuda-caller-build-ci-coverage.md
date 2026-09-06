# pkg252 — CUDA caller and target build coverage in CI

**Pillar:** 5 (reliable delivery)
**Track:** A
**Status:** OPEN — measured coverage proposal and architect review required
**Estimated effort:** S/M, confirm after trial
**Depends on:** pkg250 failure evidence; coordinate workflow ownership with pkg240

## Reproduced gap

A full clean Windows CUDA ALL_BUILD on main f30bc5f failed at apps/main.cpp:277:
its CUDARenderer::render caller survived removal of that method in pkg55-C7.
The CUDA CI job compiles individual .cu files; the host job builds without CUDA.
Neither gate proves a host C++ caller compiles under the production CUDA/N3
configuration, nor that the complete CUDA standalone target links. Existing CI
success therefore did not contradict this local compiler failure.

Evidence: test_results/rebuild-handoff-20260906/engine-cuda-full-build.log and
.github/workflows/ci.yml. Pkg250 repairs the caller; this package owns prevention.

## Scope and acceptance — UNRUN

- Audit effective macros, translation units and targets covered by each CI
  build. Record production N3-on, CUDA N3-off and CPU-only reachability, including
  standalone and binding callers. Do not count preprocessing-disabled code as
  compiled implementation coverage.
- Compare a bounded CUDA-host compile gate with an actual target-link gate using
  the existing CMake targets/scripts. Measure matched-revision added latency and
  cost; select sufficient coverage through Astra and independent review before
  workflow changes. Coordinate pkg240 so two workers never edit the same workflow.
- Demonstrate that the original deleted-call defect fails the proposed gate,
  while repaired source passes. Add a relevant configuration/link failure probe
  if the selected gate claims link coverage. No hardware runtime claim from CI.
- Preserve required check names/trust boundaries, docs-only routing, CUDA
  source coverage and honest failures. Test internal PR, push and fork behavior.
- Document remaining GPU/runtime limitations and retain actual RTX/Blender
  hardware and visual gates for releases. Keep cold build optimization in pkg231.

## Non-goals

No unconditional second full expensive CI build without measured justification,
no blanket CI restructuring, reduced tests, threshold relaxation, new parallel
build wrapper, or GPU render claim from syntax checks. Filing does not change
the owner's pkg241/240 priority or any astrophysics pause.

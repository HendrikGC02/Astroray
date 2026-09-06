# pkg250 — Standalone CUDA wavefront dispatch

**Pillar:** 5 (renderer verification and delivery tooling)
**Track:** A
**Status:** IMPLEMENTING — CPU checks passed; clean CUDA build, GPU runtime and independent review pending
**Depends on:** existing pkg55-C7 wavefront backend; no new renderer algorithm

## Problem and scope

The owner-requested full root rebuild at source `f30bc5f` exposed the stale
`cudaRenderer.render(...)` call in `apps/main.cpp`. That entry point was removed
in pkg55-C7; the CUDA standalone target no longer compiled even though the
Python/addon targets used the current wavefront entry point. This is a bounded
prerequisite build repair for the current rebuild and handoff, without changing
the pkg241/240 milestone, promoting other backlog work, or unpausing Pillar 4.

Own only `apps/main.cpp`, focused behavior additions in
`tests/test_standalone_renderer.py`, and this spec. No engine, binding, ABI,
reference, CI workflow, or rendering-physics changes.

## Architecture decision

- Route the existing standalone `auto`/`gpu` path-tracer selection through
  `astroray::wavefront::cuda_wavefront_render`, matching the binding contract.
  The wavefront implementation builds and uploads its own scene/environment;
  remove the legacy `uploadScene` and `uploadEnvironmentMap` calls.
- Guard the snapshot header and wavefront call with CUDA and
  `ASTRORAY_WAVEFRONT_CUDA_N3`. In CUDA builds without N3, `auto` uses CPU;
  explicit `gpu` reports the wavefront-build requirement and exits with error.
  Preserve unavailable-device and unsupported-integrator errors.
- Mirror the binding's path-tracer parameters: `getFloat` wavelength bounds
  defaulting to 380–780 nm, output-mode inference at 379.5–780.5 nm, and NEE on.
  Seed zero obtains a random-device seed; nonzero renderer seeds pass through.
  Do not add a seed flag or other CLI options.
- Copy interleaved linear RGB results into camera pixels. Keep the CPU render
  invocation unchanged: its existing `true` argument enables adaptive sampling,
  while gamma defaults off. Existing PNG/PPM writers apply display gamma once.

## Acceptance and evidence

1. Review the exact binding and wavefront contracts and sweep standalone callers;
   no removed CUDA-render entry point remains in this caller.
2. Build the CPU standalone target and complete the full clean root CUDA
   `ALL_BUILD`. Exercise CUDA/N3-off compilation and CPU-auto/explicit-GPU error
   behavior where feasible; report any unrun configuration explicitly.
3. Run actual executable tests for explicit CPU/GPU Cornell and material scenes,
   PNG/PPM validity, auto fallback and explicit errors when unavailable, decimal
   wavelength/output-mode parameters, and an uploaded environment image.
4. Save representative CPU/GPU images with source, artifact and settings identity.
   Astra qualitative review and an independent source/ABI review are required;
   numerical checks alone do not establish image correctness or gamma parity.
5. Run focused tests and differential lint. The implement delegate's wrapper JSON
   is process evidence; inspect its diff and verify locally before sign-off.

Local checks on 2026-09-06 (isolated `pkg250` worktree, source repair above
`083c84b`; the intervening main change only corrected builder documentation):

| Check | Result |
| --- | --- |
| MSVC Release CPU standalone, `windows-cpu-vs`, Python/OIDN off | PASS; `build/bin/Release/raytracer.exe` |
| Full standalone suite against that CPU binary | 11 passed, 5 explicitly skipped because CUDA was not compiled |
| MSVC `/Zs` host syntax, CUDA defined with N3 off and on | PASS for both; no CUDA compilation or linking in these checks |
| Delegated implement process | Completed in 304.5 s, Windows Job cleanup confirmed, zero active processes |

The delegate diff required local repairs: retain the scene builder's required
`buildAcceleration()` precondition and implement N3-off automatic CPU fallback.
No function signatures changed. The caller sweep covers the standalone test
suite, `CMakeLists.txt` target, and the binding/header implementation contract.
The final standalone caller has no legacy upload or removed render call.

Hardware/build evidence and final independent judgment are owned by the parent
delivery agent. CPU tests produced images in `test_results/`; qualitative
review, CUDA completion, GPU images, and CUDA/N3-off runtime behavior remain
pending. Syntax-only checks do not establish linking or device behavior.

## Limits

The binding's visible defaults (380–780 nm) and CPU spectral defaults
(360–830 nm) already differ. Arbitrary integrator-parameter parity is outside
this repair. In particular, the existing CLI parser stores integer literals as
integers, while binding-compatible `getFloat` wavelength extraction accepts
float values; tests use explicit decimal literals. No parameter-typing or
spectral-default redesign is included. Existing seed-zero runs are stochastic;
the behavior tests do not claim cross-device bitwise equality or convergence.

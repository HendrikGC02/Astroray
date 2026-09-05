# pkg231 — CUDA build latency diagnosis (cold/incremental timing matrix)

**Pillar:** 5 (delivery tooling for Blender/DCC)
**Track:** A
**Status:** OPEN — detailed architect review required before dispatch
**Estimated effort:** M
**Depends on:** pkg183 (build-integrity guards: `scripts/build/build_guard.py`, header-hash stamp, force-clean-on-mismatch, ABI canary, CUDA-arch gate)

## Goal

Measure cold and incremental CUDA builds by translation unit (TU) and configuration.
Attribute the ~34-minute pkg230 Phase 2 baseline rebuild using reproducible timings;
the diagnosis may conclude there is no actionable regression.

## Context / evidence

- **Observation (pkg230 P2, 2026-09-05):** a forced baseline rebuild of
  `shader_vm.h` and dependent sources on SHA
  `31f30298c79dad151b270bef448184b598995137` took **~34 minutes wall** in the
  pkg230 Phase 2 session (local 23:15:33 → module 23:49:22). This interval is
  **session observation, NOT translation-unit profiler output** — it must be
  re-measured with per-TU timing before any attribution. `stage_advance.cu`
  **appeared** to dominate; this is a hypothesis to quantify, not a measured
  breakdown.
- The baseline log (`test_results/pkg230-p2/baseline-build.log`, main-checkout
  artifact) confirms pkg183 detected layout-critical header changes and
  force-cleaned objects. Toolchain: NVCC 12.8, MSVC 14.44.35207, native sm_120;
  the source session recorded wavefront N3 ON / OpenMP ON. Build used the repo-root
  `build_cuda_worktree.bat` (canonical VS-generator pipeline). **This is a
  measurement, NOT a proven regression** against the historical ~61 s rebuild
  claims: sources, generator, cache state, clean/incremental classification,
  and build options must all match before any comparison.

## Investigation scope

1. Reproducible cold and incremental timing, per TU and per configuration,
   distinguishing: no-op rebuild, implementation-file edit, shared-header edit,
   forced clean, and warm vs cold compiler cache.
2. Compare the repo-root canonical VS wrapper (`build_cuda_worktree.bat`)
   against the Ninja wrapper (`scripts/build/build_cuda_worktree.bat`) and the
   shared sccache, with **matched** source SHA, toolchain, native arch, build
   options, configuration, and controlled concurrency.
3. Gather per-TU compile time, device-link / host-link time, wall time, cache
   hit/miss, and the guards' rebuild reason.
4. Explicitly investigate **header fanout** and the **all-128 shade
   specializations** as hypotheses — not proven causes; examine low-cost
   **host semantic gates** that give earlier useful feedback while preserving
   full native-hardware acceptance.

## Candidate existing scripts (extend, do not fork)

- repo-root `build_cuda_worktree.bat` (VS multi-config, no configure step)
- `scripts/build/build_cuda_worktree.bat` (Ninja single-config + sccache)
- `scripts/build/build_cuda.bat` (dev Ninja + sccache)
- `scripts/build/build_guard.py` (pkg183) and the existing test runner

Only later implementation may extend these canonical scripts. **No parallel
one-off build wrapper; no deleting the intentionally distinct wrappers.** Build
guard protections are retained: source/header freshness, actual import path,
architecture, host ABI canary, codegen/register, and caller/binding checks.

## Risks

- OneDrive timestamps and cache state can confound rebuild classification;
  record freshness decisions and compare wrappers only with matched inputs.
- GPU-heavy builds must be serialized with the project GPU lock; max 2 active
  implementation worktrees; first action verifies the worktree toplevel.

## Non-goals

- No shader/transport/physics semantics changes, kernel-specialization redesign,
  guard removal, or build-wrapper unification. No new UI, no astrophysics
  (Pillar 4 remains PAUSED).
- No speculative engine optimization and no promised speedup target.
- This follow-up does **not** outrank the current owner post-pkg230 priority
  choice; no queue promotion.

## Acceptance (all UNRUN — no passed results or PR IDs claimed)

- [ ] Repeatable, documented, matched-source timing matrix + raw logs with
      variance and config/cache metadata; bottleneck attribution supported by
      measured TU/link/cache data and the stated hypothesis outcome (header
      fanout, 128 shade specializations, `stage_advance.cu`).
- [ ] Documented low-cost host semantic gate subset and what it cannot prove.
- [ ] Any later build-script tweak shows a measured benefit with unchanged
      architecture/codegen/ABI/native gates.
- [ ] Independent architect/Claude review per workflow; diagnostic result may
      validly be **no actionable regression**.

Independent Claude filing review: SIGN-OFF, 2026-09-06; explicitly not
implementation-ready. Evidence: `test_results/pkg231/claude-filing-review.txt`.

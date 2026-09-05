# pkg244 — Compiler identity and post-configure build safeguards

**Pillar:** 5 (reliable Blender/native builds)
**Track:** A
**Status:** OPEN — detailed architect review required before implementation
**Estimated effort:** S, confirm at architect review
**Depends on:** existing addon builder and pkg183 build guards

## Reproduced failure

During pkg230b verification on 2026-09-06 Sydney, the canonical addon builder
reconfigured the existing pkg230 Phase 2 CUDA cache. Compiler discovery returned
`nvcc.EXE` while the cache held the same Windows executable as `nvcc.exe`.
CMake treated the textual compiler-path change as a compiler replacement and
re-ran configuration with a cleared cache. The first configuration said Release,
native sm_120, OpenMP disabled; the subsequent configuration silently selected
Debug, architectures 75/86/89, and OpenMP enabled. The helper proceeded to build.
Compilation failed on incompatible `/RTC1` and `/O2`; no replacement module was
produced or used. The retry restored the canonical flags and shared dependency
directory before compilation. A successful retry is not yet this package's gate.

Evidence at root `test_results/pkg230b/fresh-cuda-build.log` and
`fresh-cuda-build-retry.log`; source baseline `305caf5`, source-identical native
cache at `4035a00`. This is configuration correctness, distinct from pkg231's
broader local rebuild-latency diagnosis and pkg240's CI cost audit.

## Goal and scope

Extend `scripts/build/build_blender_addon.py` and existing build-guard/tests so
equivalent Windows compiler paths do not invalidate a valid cache, and every
configure is followed by verification of the actual effective build settings
before any compilation, staging or installation. Reuse canonical helpers.

The architect pass must distinguish path spelling/case from a genuinely changed
compiler/toolchain. Normalize identity using Windows path semantics without
mistaking a different executable/version for the same compiler. An intentional
toolchain change must re-establish the complete requested configuration after a
cache reset, or fail explicitly. Never continue with silently substituted flags.

Validate Release, requested backend/CUDA presence, disabled OpenMP for Blender,
resolved CUDA architectures, build ID and selected Python ABI. Preserve intended
dependency-cache configuration. Inspect generated target flags where a cache
value alone does not prove the requested setting took effect. Keep custom
CPU/CUDA/tcnn and configure-only behavior intact.

## Acceptance — implementation gates UNRUN

- [ ] Windows case/separator-equivalent compiler paths preserve cache identity;
      a genuinely different compiler follows the explicit replacement path.
- [ ] Simulated CMake cache reset cannot reach build/stage/install with Debug,
      wrong CUDA architecture, enabled Blender OpenMP, missing build ID, or
      a different Python ABI.
- [ ] Actual Windows configure/reconfigure canary reproduces the spelling
      transition and confirms final settings using the recorded toolchain.
- [ ] CPU, CUDA, configure-only and supported tcnn configuration contracts remain
      covered; unavailable variants are reported rather than counted as passes.
- [ ] One fresh native build/import and canonical guard check prove the accepted
      configuration reaches the artifact; serialize CUDA work with the GPU lock.
- [ ] Differential lint, caller sweep, and independent Astra/Claude review.

## Non-goals

No broad build-speed claims, cache deletion policy rewrite, renderer changes,
new build wrapper, or live Blender installation. No queue preemption or Pillar 4
activation merely from filing this spec.

# Production gap audit — 2026-09-06

**Source baseline:** `305caf569b43c62cb8a8a0d6af9f35fb5f4fc9a2` (pkg230 Phase 2
closeout, PR #703)
**Date:** 2026-09-06 (Sydney)
**Status:** Accepted new filings; no implementation, hardware, or visual gates
run.

## Accepted new filings

- [pkg241 — Cooperative render cancellation and viewport-response
  contract](../packages/pkg241-render-cancellation-viewport-response.md) —
  Pillar 5, Track A, OPEN. Phase 0 latency measurement before any code;
  bounded cancellation/restart/stale-result contract.
- [pkg242 — Procedural transformed-p and bake/cache-domain
  parity](../packages/pkg242-procedural-mapping-bake-parity.md) — Pillar 5,
  Track A, OPEN, sequenced AFTER pkg230b. One transformed-coordinate contract
  for CPU+GPU bake domains.
- [pkg243 — Raw relative band output and honest
  provenance](../packages/pkg243-raw-band-output-provenance.md) — Pillar 5 + 2,
  Track A, OPEN. Preserve the existing relative raw band quantity before
  display; honest provenance; no calibrated-SI or GPU-support claims.

## Existing coverage exclusions

- Cancellation/viewport response reuses DONE pkg52 (persistent session),
  pkg81 (interactivity benchmark), pkg191 (progressive refinement), pkg192
  (navigation interactivity), pkg196 (reduced-res navigation), pkg147
  (OpenMP/GIL hang). OPEN pkg232 owns delegate process lifecycle only;
  OPEN pkg236 owns isolated smoke profiles. pkg241 adds the cancellation/
  response contract and reuses the existing benchmark; future architecture
  decides the session mechanism.
- Procedural mapping reuses pkg59, pkg115 (line 125 full-3D Mapping TODO),
  pkg190 (UV/Generated bake only, guarded Object fallback), pkg219
  (image Mapping acceptance), active pkg230b (image/compatible-program affine path;
  warns on unsupported procedurals). pkg242 excludes pkg230b's child-sampler
  cache isolation, pkg234 image filtering, pkg233 standalone BSDF texture
  plumbing.
- Raw band reuses pkg39, pkg54, pkg58, pkg125. pkg133 (SRF/instrument
  channels) and pkg130/pkg134 (light groups/LPEs) own their scopes; pkg243
  does not touch them.

## Future priority

- Cancellation/viewport response (pkg241) is the highest production risk and
  first priority.
- Procedural mapping parity (pkg242) second, after pkg230b lands.
- Raw band provenance (pkg243) is lower immediate priority.
- pkg230b is currently active — do NOT duplicate-dispatch it.

## Owner state

Owner priority newly delegated to Astra. Pillar 4 remains PAUSED; none of
these filings unpause it.

## Build correctness finding during verification

[pkg244 — Compiler identity and post-configure build safeguards](../packages/pkg244-build-compiler-identity-config-guard.md)
records a reproduced case-only nvcc path change that triggered a CMake cache
reset and lost requested Release/architecture/OpenMP settings. Compilation
failed before any replacement artifact was used. This is separate from pkg231
local build latency and pkg240 CI cost. Implementation gates remain UNRUN.

## Release spec

No extra release spec filed: [pkg175](../packages/pkg175-blender-dev-loop-one-command.md),
[pkg183](../packages/pkg183-incremental-build-staleness-guard.md), and
[pkg236](../packages/pkg236-hermetic-blender-smoke.md)
already cover substantial build/install coverage. The remaining full release
matrix is unverified and out of scope here.

## pkg127 Phase 2 — RECONCILIATION REQUIRED

- [pkg127 spec](../packages/pkg127-specular-polynomials-sms.md) Phase 2 is
  OPEN; line 127's `sms_polynomial_seed` flag name is obsolete. This audit
  does not change that status.
- Actual flag: `sms_specular_poly` —
  `plugins/integrators/spectral_path_tracer.cpp:104` and
  `plugins/integrators/sms_caustic_path_tracer.cpp:84`.
- Implementation: `include/astroray/manifold/specular_poly.h:391`
  `solveSphereChain`; `include/astroray/manifold/sms_attempt.h:386`
  `runSphereChainAttempt`; called at `spectral_path_tracer.cpp:358` and
  `:427` — under [pkg227](../packages/pkg227-general-specular-polynomials.md)
  line 413, Phase 2a.
- `sms_attempt.h:397` rejects `reflections < 1`; the current caller supports
  entry/reflection(s)/exit, with three or four vertices. This does not prove
  the two-vertex entry/exit requirement is covered. Reconcile the pkg127 RR
  wording against its double-refraction gate and the implemented topology.
- Before closing or redispatching pkg127 Phase 2: audit the exact topology,
  callers, tests, and gates. Code existence never proves missing tests or
  hardware gates are complete.

## Process note

The readonly grunt inventory timed out at 240 s (transcript
`20260906-032221-grunt.jsonl`); partial leads were verified directly by Astra.
No performance or visual result is claimed from that inventory.

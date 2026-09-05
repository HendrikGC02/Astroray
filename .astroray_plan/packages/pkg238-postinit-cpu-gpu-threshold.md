# pkg238 — PostInit CPU/GPU numerical threshold diagnosis

**Pillar:** 5 (GPU numerical parity gates)
**Track:** A
**Status:** OPEN — detailed architect review required before implementation
**Estimated effort:** TBD at architect review
**Depends on:** none (diagnosis of existing behavior)

## Evidence

`tests/wavefront_diff/test_pkg55_cuda_threshold_gate.py::test_cpu_to_gpu_threshold_gate`
failed PostInit max-ULP 13 against the pinned bound 4 IDENTICALLY on baseline and
feature. PostInit is initial camera/wavelength state before shader evaluation, so
this does not prove a pkg230 VM regression. Evidence files: feature
`test_results/pkg230-p2/full-suite.log` and `baseline-full-suite-failures.log`.

## Goal

Diagnose the exact snapshot fields/pixels/lanes behind the PostInit max-ULP
overshoot, including signed-zero/subnormal/near-zero handling in the ULP metric,
compiler/math options (FMA, fast math, FP precision), seeding/camera/wavelength
initialization, and the actual code paths, before proposing any bound change.
Preserve root/feature raw snapshots and source/toolchain/options/import identity
throughout. Do not assume 13 is acceptable or 4 is invalid; decide only on
independent numerical evidence.

## Scoped direction

Detailed architect review decides the correct minimal implementation or a
calibrated bound change only after independent numerical evidence is produced.
This follow-up does not change owner queue priority; Pillar 4 remains PAUSED.

## Acceptance — all implementation gates UNRUN

- [ ] Repeated identical baseline/feature reproductions produce field-attributed
      ULP plus relative/absolute error distributions.
- [ ] Compare attributed fields against independent initialization oracles.
- [ ] Matched toolchain/math flags and seed determinism documented.
- [ ] Why the existing bound fails is documented from evidence, not assumption.
- [ ] PostIntersect/PostShade/PostLightSample and other later-stage gates remain
      unchanged during diagnosis.
- [ ] Any fix/bound proposal is independently reviewed and scientifically
      supported; native architecture/ABI/resource checks and full required
      regressions if the engine changes.
- [ ] GPU lock and at most two isolated implementation worktrees; independent
      Astra/Claude sign-off.

## Non-goals

A blanket threshold increase could mask a genuine PostInit divergence or a later
regression. No blanket threshold increase; no masking of later-stage failures; no
shader VM/transport changes; no owner queue priority change; no Pillar 4 work.

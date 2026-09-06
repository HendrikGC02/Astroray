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

## Evidence — diagnosis 2026-09-07 (fix/pkg237-238-diagnosis)

Full detail: `.astroray_plan/docs/pkg237-238-diagnosis-2026-09-07.md`.

ROOT CAUSE: the overshoot is the `lambdas` field, made transcendental by pkg206 AFTER the
4-ULP pin. Two compounding defects (pkg73 pattern):

- Defect A (actual surface): PostInit bounds ["ray_origin","ray_direction","lambdas"] under
  one max_ulp=4. Since pkg206 the default wavelength sampler is `sampleImportance`, which
  inverts a logistic CDF with `std::log`/`std::exp` (CPU, spectrum.cpp:171) vs `logf`/`expf`
  (GPU, stage_init.cu:182/163). Device transcendentals are not IEEE-correctly-rounded (the
  yaml header says so). At lambda~552nm, 1 float32 ULP ~ 6.6e-5nm; a ~1e-6 relative log
  divergence ~ 5e-4nm ~ 8-13 ULP => exactly the observed 13. Geometry stays ~1-2 ULP.

- Defect B (why 4 looked right): the 4-ULP pin (pkg55_cuda_thresholds.yaml, "Measured ULP=2,
  2026-05-23") was set under the LINEAR sampleUniform, and its note explicitly assumes
  PostInit is "geometry-only, no transcendentals beyond normalize." pkg206 invalidated that;
  the pin was never re-measured -> stale pin masking the field's changed character. Fails
  identically on baseline+feature because it is a stable host/device transcendental property,
  not a code regression (pkg230 not the cause).

Distinguishing tests (need GPU lock — held by lead, not run): (1) split PostInit ULP into
origin/dir/lambdas; predict lambdas~13, geometry<=4. (2) build with hero_importance=0
(sampleUniform); predict PostInit ULP drops to <=4.

Proposed fix (field-attributed, NOT a blanket increase; mirrors PostShade which already
carries no max_ulp for transcendentals and uses p99.9 relative error): keep
ray_origin/ray_direction on a tight geometry ULP (<=4) and move `lambdas` to the existing
PostInit p99.9 relative-error bound (1.0e-5, satisfied by the ~2.3e-6 drift), or give lambdas
a separate ~16-ULP transcendental bound. Land only after GPU field attribution + independent
review.

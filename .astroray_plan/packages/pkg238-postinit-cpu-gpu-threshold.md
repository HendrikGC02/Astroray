# pkg238 — PostInit CPU/GPU numerical threshold diagnosis

**Pillar:** 5
**Track:** A
**Status:** open — detailed architect review required before implementation
**Estimated effort:** TBD
**Depends on:** none

---

## Goal

Before: the PostInit max-ULP overshoot is undiagnosed — the exact snapshot
fields, pixels, and lanes behind it are unknown, as are the roles of
signed-zero/subnormal/near-zero handling in the ULP metric, compiler/math
options (FMA, fast math, FP precision), seeding/camera/wavelength
initialization, and the actual code paths. After: the overshoot is diagnosed
down to those exact fields/pixels/lanes, with root/feature raw snapshots and
source/toolchain/options/import identity preserved throughout, before
proposing any bound change. Do not assume 13 is acceptable or 4 is invalid;
decide only on independent numerical evidence.

---

## Context

This package serves Pillar 5 (GPU numerical parity gates). It is a diagnosis
of existing behavior and depends on no other package. The effort estimate is
to be determined at architect review.

---

## Evidence

- `tests/wavefront_diff/test_pkg55_cuda_threshold_gate.py::test_cpu_to_gpu_threshold_gate`
  failed PostInit max-ULP 13 against the pinned bound 4 identically on
  baseline and feature.
- PostInit is initial camera/wavelength state before shader evaluation, so
  this does not prove a pkg230 VM regression.

### Diagnosis 2026-09-07 (fix/pkg237-238-diagnosis, PR #731)


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

---

## Reference

- Evidence files: feature `test_results/pkg230-p2/full-suite.log` and
  `baseline-full-suite-failures.log`.

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

Detailed architect review decides the correct minimal implementation or a
calibrated bound change only after independent numerical evidence is
produced. This follow-up does not change owner queue priority; Pillar 4
remains PAUSED.

---

## Acceptance criteria

All implementation gates are UNRUN.

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

---

## Non-goals

- Risk: a blanket threshold increase could mask a genuine PostInit divergence
  or a later regression.
- No blanket threshold increase.
- No masking of later-stage failures.
- No shader VM/transport changes.
- No owner queue priority change.
- No Pillar 4 work.

---

## Progress

- [x] 2026-09-07 — root-cause diagnosis landed (PR #731); fix is a test-method change pending owner review.

---

## Lessons

- (none yet)

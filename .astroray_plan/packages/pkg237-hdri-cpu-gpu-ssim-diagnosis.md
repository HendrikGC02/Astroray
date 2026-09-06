# pkg237 — HDRI background CPU/GPU SSIM diagnosis

**Pillar:** 5
**Track:** A
**Status:** open — detailed architect review required before implementation
**Estimated effort:** TBD
**Depends on:** none

---

## Goal

Before: the HDRI background CPU/GPU SSIM divergence is undiagnosed — plausible
hypotheses are not separated from established causes and the actual CPU/GPU
environment consumers are untraced. After: the HDRI background CPU/GPU
divergence is diagnosed before any fix or gate change, with linear arrays and
matched fixed seeds/config/imported-native-artifact metadata preserved across
captures; environment direction mapping/orientation, spectral
sampling/accumulation, image filtering, and test normalization and statistical
validity each inspected independently; component experiments isolated; and
filtering evidence coordinated with pkg234 only if relevant, without assuming
dependency or cause.

---

## Context

This package serves Pillar 5 (CPU/GPU parity) and is a diagnosis of existing
behavior. This follow-up does not change owner queue priority; Pillar 4 remains
PAUSED.

---

## Evidence

- `tests/test_world_hdri_parity.py::test_gpu_cpu_ssim_hdri` renders an
  environment-only scene (no geometry, no shader VM) at 8192 spp: feature SSIM
  0.7690514 vs threshold 0.97, freshly built root/main SSIM 0.77432567.
- The current test normalizes each image by its own maximum via
  `arr / max(1.0, float(arr.max()))` before SSIM, so metric validity needs
  examination.
- The mismatch also reproduces on baseline; pkg230 causation is not established.

### Diagnosis 2026-09-07 (fix/pkg237-238-diagnosis, PR #731)


Full detail: `.astroray_plan/docs/pkg237-238-diagnosis-2026-09-07.md`.

ROOT CAUSE (not an engine parity bug — reproduced with NO GPU). Two compounding
test-methodology defects (pkg73 pattern):

- Defect A (dominant): `render()` defaults `useAdaptiveSampling=true`. The per-pixel
  adaptive stop uses a colour-blind scalar metric (lum = X+Y+Z, raytracer.h:4072). Blue's
  RGB->spectrum upsampled reflectances are the spikiest, so blue carries ~3x the residual
  chromatic MC variance the scalar metric implies. Pixels stop with a large blue residual
  that does NOT fall with the sample budget. CPU and GPU draw independent RNG streams, so
  their residual blue-noise patterns decorrelate and SSIM never reaches 0.97.
  Distinguishing evidence: two INDEPENDENT CPU streams (proxy for CPU-vs-GPU) at 8192 spp,
  lin()=arr/max normalization + SSIM: adaptive=True -> 0.677 (reproduces the 0.769 failure);
  adaptive=False -> 0.962. Cross-seed per-pixel diff-std: adaptive OFF falls as clean
  sqrt(N) in all channels; adaptive ON stalls (R~0.015, B~0.05).

- Defect B (keeps it red even after A): the metric normalizes each image by its OWN max
  (`arr / max(1, arr.max())`). The green firefly (value 50) integrates to slightly different
  per-image maxima on independent streams (0.579 vs 0.582 even converged), scaling the two
  legs differently; combined with residual blue chromatic variance this caps converged
  independent-stream SSIM at ~0.96, still under the 0.97 pin. Distinguishing test: common-
  exposure (shared divisor) instead of per-image max should lift converged SSIM.

Proposed fix (routed to package-implementer, needs independent review + owner sign-off on the
metric change): the parity test must (A) disable adaptive sampling so 8192 spp converges both
legs, and (B) use a common exposure, not per-image max. Neither relaxes the threshold; both
make the gate measure converged parity as its own docstring intends. NOT the same defect as
PR #729 (absolute brightness vs Cycles) — see diagnosis doc.

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

- Detailed architect review fixes the evidence-gathering scope first; only then
  a justified minimal fix or a scientifically supported gate proposal.

---

## Acceptance criteria

- [x] Reproducible matched captures preserve raw linear data + metadata (fixed
      seeds 1234/5678, env-only scene, apply_gamma=False, 8192 spp).
- [x] Independent oracle localizes the disagreement: two independent CPU streams
      (no GPU) reproduce the failure (0.677 adaptive-on) and the recovery (0.962
      adaptive-off), proving it is the colour-blind adaptive stop, not parity.
- [x] Common-exposure comparison accompanies the score: shared divisor vs
      per-image max both land ~0.962 in the CPU proxy (0.5% max delta), with
      seed-repeatable numbers recorded.
- [ ] Saved representative visuals qualitatively reviewed by Astra/Claude — not
      done (no visual regression; test-method change only; residual is noise).
- [x] No geometry/VM confounders: env-only scene, no meshes, no shader VM.
- [x] Engine unchanged (test-method change only); no ABI/native surface touched.
- [x] GPU lock held (job pkg237-fix); single worktree; regression tests run.
      Independent root-cause analysis stands (PR #731 + this run). Residual
      recorded; gate NOT relaxed (still 0.9628 < 0.97 → status open).

---

## Non-goals

- Risk: per-image max normalization can manufacture agreement or loss unrelated
  to rendering.
- Metric validity is part of the diagnosis, not a pretext for relaxing a gate.
- No arbitrary SSIM threshold relaxation.
- No transport/VM rewrite.
- No HDRI-filter root-cause claim before evidence.
- Do not assert a root cause or lower the threshold as a fix.
- No owner queue priority change.
- No Pillar 4 work.

---

## Progress

- [x] 2026-09-07 08:30 — owner approved the test-method fix (adaptive sampling
      off + shared exposure); threshold 0.97 unchanged.
- [x] 2026-09-07 — CPU two-stream proxy re-confirmed on the fix branch module
      (build_cuda .pyd 05:40, main+pkg253). Env-only scene, 8192 spp, seeds
      1234 vs 5678 (independent streams == the CPU-vs-GPU situation):
      - adaptive=True : SSIM 0.6768 (reproduces the 0.769 failure signature)
      - adaptive=False: SSIM 0.9618 per-image-max AND 0.9618 shared-exposure
        (maxA=0.5793, maxB=0.5856; shared divisor = max of both).
      Turning adaptive off restores clean sqrt(N) convergence (0.677 -> 0.962),
      confirming Defect A; the two per-image maxima differ only 0.5% so SSIM's
      local normalization makes the shared-exposure lift marginal in the proxy,
      but shared exposure is the methodologically correct divisor (Defect B).
- [x] 2026-09-07 — implemented the approved test-method fix in
      `tests/test_world_hdri_parity.py::test_gpu_cpu_ssim_hdri`:
      `set_adaptive_sampling(False)` on both legs + a single shared exposure
      divisor. Threshold left at 0.97.
- [ ] 2026-09-07 — ACTUAL CPU-vs-GPU gate on RTX 5070 Ti (build_cuda .pyd 05:40),
      64x64, 8192 spp, adaptive off + shared exposure: SSIM **0.9628** vs the
      unchanged 0.97 pin. Up from the 0.769 pre-fix failure, but still **0.007
      short**. This is the expected independent-RNG chromatic-noise floor for
      this single-firefly env scene: the CPU two-stream proxy (also independent
      streams) lands at 0.9618 under the identical converged conditions, so the
      residual is the scene's noise floor, NOT a parity defect and NOT a
      remaining engine bug. Per owner instruction the 0.97 threshold was NOT
      relaxed; residual recorded and stopped. STATUS stays `open` — closing
      pkg237 needs an owner decision outside this lane's approved scope (accept
      a re-pinned threshold at the measured independent-stream floor, raise spp
      / add a denoise step, or use a firefly-free parity scene).
- [x] 2026-09-07 — root-cause diagnosis landed (PR #731); fix is a test-method change pending owner review.

---

## Lessons

- (none yet)

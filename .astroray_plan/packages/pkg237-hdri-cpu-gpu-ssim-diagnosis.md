# pkg237 — HDRI background CPU/GPU SSIM diagnosis

**Pillar:** 5 (CPU/GPU parity)
**Track:** A
**Status:** OPEN — detailed architect review required before implementation
**Estimated effort:** TBD at architect review
**Depends on:** none (diagnosis of existing behavior)

## Evidence

`tests/test_world_hdri_parity.py::test_gpu_cpu_ssim_hdri` renders an
environment-only scene (no geometry, no shader VM) at 8192 spp: feature SSIM
0.7690514 vs threshold 0.97, freshly built root/main SSIM 0.77432567. The current
test normalizes each image by its own maximum via
`arr / max(1.0, float(arr.max()))` before SSIM, so metric validity needs
examination. The mismatch also reproduces on baseline; pkg230 causation is not
established. Do not assert a root cause or lower the threshold as a fix. Evidence
files: feature `test_results/pkg230-p2/full-suite.log` and
`baseline-full-suite-failures.log`.

## Goal

Diagnose the HDRI background CPU/GPU divergence before any fix or gate change.
Preserve linear arrays and matched fixed seeds/config/imported-native-artifact
metadata across captures. Inspect environment direction mapping/orientation,
spectral sampling/accumulation, image filtering, and test normalization and
statistical validity independently. Trace the actual CPU/GPU environment
consumers, isolate component experiments, and separate plausible hypotheses from
established causes. Coordinate filtering evidence with pkg234 only if relevant, without
assuming dependency or cause.

## Scoped direction

Detailed architect review fixes the evidence-gathering scope first; only then a
justified minimal fix or a scientifically supported gate proposal. This follow-up
does not change owner queue priority; Pillar 4 remains PAUSED.

## Acceptance — all implementation gates UNRUN

- [ ] Reproducible baseline/feature matched captures preserve raw linear data plus
      metadata (fixed seeds, config, imported native artifact identity).
- [ ] Independent direction/spectrum/filter oracles localize the disagreement.
- [ ] Common-exposure comparisons accompany the existing score; any metric change
      requires justification, uncertainty, and seed-repeatability evidence.
- [ ] Saved representative visuals qualitatively reviewed by Astra/Claude.
- [ ] No geometry/VM confounders in any isolating experiment.
- [ ] If the engine changes: fresh native-arch/import/ABI/resource checks and
      caller review.
- [ ] GPU lock and at most two isolated implementation worktrees; documented
      focused regression tests; independent Claude root-cause analysis and sign-off.

## Non-goals

Per-image max normalization can manufacture agreement or loss unrelated to
rendering; metric validity is part of the diagnosis, not a pretext for relaxing a
gate. No arbitrary SSIM threshold relaxation; no transport/VM rewrite; no
HDRI-filter root-cause claim before evidence; no owner queue priority change; no
Pillar 4 work.

## Evidence — diagnosis 2026-09-07 (fix/pkg237-238-diagnosis)

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

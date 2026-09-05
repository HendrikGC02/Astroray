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

# pkg249 — CI reference-smoke diagnostics

**Pillar:** 5
**Track:** A
**Status:** open — detailed architect review required before implementation
**Estimated effort:** TBD at architect review
**Depends on:** none

---

## Goal

Before: the informational `Reference bank smoke` step reports `cornell-mini ... FAIL (2/3 gates)` in CI with the failed metric unidentified and no cause established. After: enough reproducible evidence is recovered to identify the failed gate and explain the divergence from the pinned reference; only a demonstrated defect is fixed, after detailed architecture and independent root-cause review. Current required checks, their trust, and the smoke step's advisory semantics are preserved throughout diagnosis, and any proposed policy or threshold change requires separate evaluation.

---

## Context

This package serves Pillar 5, renderer verification and delivery tooling. It is a diagnosis of existing informational CI behavior and depends on none. Detailed architect review is required before implementation; estimated effort is TBD at that review. The smoke failure remains unresolved across four CI runs (see Evidence), so diagnosis must preserve required checks' trust and the smoke step's advisory semantics.

---

## Evidence

- The informational `Reference bank smoke` step reported `cornell-mini ... FAIL (2/3 gates)` in both successful pkg236 CI runs and both earlier pkg230b CI runs. The runner prints `passed_count/total`: **two gates passed and one failed**, rather than two failed. The retained console logs do not identify the failed metric or preserve its raw arrays/images. No cause has been established.
- pkg236, PR #711 — GitHub CI runs [34001551993](https://github.com/HendrikGC02/Astroray/actions/runs/34001551993), [34001549179](https://github.com/HendrikGC02/Astroray/actions/runs/34001549179); retained main-checkout evidence `test_results/pkg236/ci-pr.log`, `test_results/pkg236/ci-push.log`.
- pkg230b, PR #708 — GitHub CI runs [34000095026](https://github.com/HendrikGC02/Astroray/actions/runs/34000095026), [34000075314](https://github.com/HendrikGC02/Astroray/actions/runs/34000075314); retained main-checkout evidence `test_results/pkg230b/ci-pr.log`, `test_results/pkg230b/ci-push.log`.
- 2026-09-06: the pkg236 PR/push log entries are dated 2026-09-06 01:01:31/01:01:29 UTC; the earlier pkg230b entries are dated 00:22:31/00:27:36 UTC. All four report the same aggregate gate count; that does not establish the same failed metric.
- `.github/workflows/ci.yml:91–101` deliberately keeps this step informational with `continue-on-error: true`. Required pytest and CUDA checks succeeded; the separate smoke failure remains unresolved. The workflow comment mentions cross-platform RNG/thread ordering as a possible explanation, but that comment is not measured root-cause evidence for these runs.
- Comparing pre-pkg236 main `8217234b` with pkg236 merge `2699b43` shows no changes in engine source (`src/`, `include/`, `plugins/`, `module/`, `CMakeLists.txt`), the CI workflow, the reference bank, or `tests/test_reference_bank_smoke.py`. Pkg236 causation is not established. Source identity alone does not prove identical native artifacts, execution settings, or images.

---

## Reference

- Runner to reuse: `python -m benchmarks.reference_bank.runner --mode smoke` (its `GateResult`/`_write_report` path).
- Existing capture/report tools are indexed in `scripts/README.md`.
- Workflow context: `.github/workflows/ci.yml:91–101` (informational `Reference bank smoke` step, `continue-on-error: true`).

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

1. Reuse `python -m benchmarks.reference_bank.runner --mode smoke`, its `GateResult`/`_write_report` path, and existing capture/report tools indexed in `scripts/README.md`. Recover existing artifacts first. Extend the canonical capture path only where evidence is missing; do not create a parallel runner.
2. Record every gate's identity, measured value, threshold, direction, and applicable region/domain. Preserve raw render arrays before display transforms, actual metric-input arrays, display images, exact pinned reference data/images, and raw/display difference outputs. State transforms, normalization, clipping, and difference-display scaling explicitly; the current normalized `diff.png` alone cannot establish absolute error size.
3. Bind captures to exact source SHA and dirty state, imported native-module path/build identity/hash, reference hash/provenance, platform/compiler/Python identity, backend, scene and effective render settings, sample count, seed, and actual thread/OpenMP configuration. Confirm the loaded artifact before comparing outputs. Preserve failed evidence alongside successful repeats.
4. Establish repeatability on the failing CI platform and compare matched runs against a pinned source/artifact baseline and the pinned reference. Detailed architecture chooses repeat counts and controlled variations. Distinguish repeat variation, reference provenance, metric/display handling, and renderer behavior using measurements; do not assign an RNG explanation by default.
5. Obtain Astra qualitative inspection of representative actual/reference/diff images and independent root-cause review. Only then propose the smallest demonstrated fix with matched before/after evidence. Do not bless a new reference or lower a threshold merely to make the smoke pass.

---

## Acceptance criteria

All diagnosis and implementation gates are UNRUN.

- [ ] The failed metric(s) and exact values are identified from retained per-gate records, with complete source/artifact/reference/run identity.
- [ ] Raw, metric-input, display, reference, and difference evidence is saved with explicit data domains and transformations.
- [ ] Matched repeated captures establish behavior against a pinned baseline; hypotheses and demonstrated causes are clearly distinguished.
- [ ] Astra qualitative inspection and independent root-cause review pass; any proposed fix is tied to demonstrated evidence and documented gates.
- [ ] Required checks and existing advisory semantics remain intact; any threshold/reference/policy proposal is evaluated separately.

---

## Non-goals

- This filing is a diagnostic follow-up, not implementation approval or queue promotion.
- It is distinct from pkg237's HDRI CPU/GPU metric diagnosis, pkg239's local backdrop highlight, and pkg240's CI throughput audit.
- No speculative renderer, workflow, reference, or threshold edits belong in this filing.
- Pillar 4 remains PAUSED.

---

## Progress

- (none yet)

---

## Lessons

- (none yet)

# pkg317 — Gate (c) noise-aware comparison: measure the options, give the owner a decision

**Pillar:** 5
**Track:** C
**Status:** open
**Estimated effort:** 1 session (~3 h) + ~20 min of GPU renders under the lead's lock
**Depends on:** pkg278, pkg284

---

## Goal

Before: gate (c) is RED only on SSIM ≥ 0.95. The terrace-with-hair pair reads SSIM 0.783 while every ROI mean agrees
within 0.61 % and the images are visually identical; windowed SSIM between two independent 128-spp Monte Carlo
renders is bounded by the noise, not by agreement (memory `ssim-wrong-gate-for-independent-rng`). The same failure
mode hits `run_parity` world_sky_hdri (SSIM 0.807, means 1.008/0.999/1.001, #1060) and the #1052 pHash gate.
After: a decision document measures the candidate metrics on the real gate (c) legs, with positive controls (known
defects injected) and negative controls (independent seeds of the same backend). The owner picks one; nothing changes
in the gate definition or thresholds until then.

---

## Context

Gate (c) cannot turn green by honest engineering while its gating metric measures noise. Raising spp until SSIM
passes costs time and still tests noise; a per-pixel statistical test asks the right question: do both renderers
converge to the same image? This package only measures and reports. Owner decision required before any gate change.

---

## Evidence

- 2026-10-05 (`stage0-gate-scoring-2026-10-05.md`): max ROI channel gap 0.61 %; SSIM terrace 0.783, gallery 0.963,
  workshop 0.978; non-vacuity checks true. Local evidence `%LOCALAPPDATA%\astroray-evidence\2026-10-05\c\evidence_c\`.
- 2026-10-06 (architect): both terrace legs show heavy independent floor speckle (yellow/blue chroma) at 128 spp;
  geometry, hair, reflections and shadows match.
- Memory `ssim-wrong-gate-for-independent-rng`: SSIM floor ~ signal_var / (signal_var + noise_var); measured 0.786 at
  64 spp on a closed Cornell, ~0.97 only at 4096 spp.

---

## Reference

- Jung, Hanika, Dachsbacher 2020, "Detecting Bias in Monte Carlo Renderers using Welch's t-test", JCGT 9(2)
  (https://cg.ivd.kit.edu/welch.php): per-pixel / per-tile Welch test from per-pixel mean and variance over
  independent runs, with tile-wise difference maps and p-value histograms. Implement from the paper with
  `scipy.stats` (Welch's test is textbook); do not vendor the paper's code (licence unstated).
- Mitsuba 3 `src/render/tests/test_renders.py` (BSD-3): z-test against a reference with a variance image, the
  production precedent for a statistical render gate.
- `tests/test_pkg55_reference_pt_oracles_equivalent.py` docstring: the repo's earlier SSIM→mean-ratio swap.

---

## Prerequisites

- [ ] Gate (c) legs reproducible with `benchmarks/blender_parity/harness.py` (Blender 5.2 via `BLENDER_EXE`).
- [ ] Lead schedules the GPU legs under `gpu_locked_run.py`.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/blender_parity/mc_compare.py` | Candidate metrics over multi-seed legs: per-tile Welch t-test (Jung 2020) with Holm–Bonferroni or FDR control, SSIM noise ceiling (same-backend independent seeds), SSIM on a box-downsampled pair, mean-ratio per ROI |
| `tests/test_pkg317_mc_compare.py` | Synthetic fixtures: identical-mean noisy pairs pass; a 2 % ROI bias and a missing-feature image fail; false-positive rate at α holds on null pairs |
| `.astroray_plan/docs/gate-c-metric-study-2026-10.md` | Results table + owner decision options |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/blender_parity/harness.py` | `--seeds` for gate (c) study legs (N independent seeds per backend), written beside the gate legs; the gate path itself unchanged |
| `scripts/README.md` | Register `mc_compare.py` |

### Key design decisions

- **Legs:** trio × {CPU, GPU} × N = 8 seeds at the gate's 128 spp and 480×270; seeds spread (278, 1301, 2711, 4177,
  6113, …), never adjacent (#986 CPU seed-stream overlap).
- **Candidates measured, all at unchanged gate settings:** (1) per-tile Welch test, tile 8×8 px, family-wise error
  controlled; (2) SSIM(CPU, GPU) vs the SSIM noise ceiling SSIM(CPU_s, CPU_s'); (3) SSIM on 4×4 box-downsampled
  images; (4) SSIM at the mean of N seeds (equivalent higher spp); (5) existing ROI mean ratio.
- **Controls:** negative = CPU seed A vs CPU seed B (must pass); positive = injected defects on the GPU leg: global
  ×0.98, a 3 % shift in one ROI, hair removed (hair_off leg), HDRI off (hdri_off leg), a 1-px shift, a blur.
  A candidate is usable only if it passes every negative control and fails every positive one.
- Report the cost (render time) of each candidate at its working N.
- Do not edit `gate_manifest.py`, thresholds or the committed manifest.

---

## Acceptance criteria

- [ ] `pytest tests/test_pkg317_mc_compare.py` green; null false-positive rate within α ± 2σ on 200 synthetic pairs.
- [ ] Study doc: table of candidate × {gallery, workshop, terrace, negative controls, each positive control} with
      pass/fail and the statistic, plus cost; contact sheet of tile-wise p-value maps (inspected).
- [ ] The doc ends with the owner question and a recommendation; no gate file changed.

---

## Non-goals

- Do not change gate (c)'s metric, threshold or manifest (owner decision).
- Do not denoise the gate legs or raise their spp.
- Do not fix #1052 (same class; reuse the study's conclusion there later).

---

## Progress

- [ ] `mc_compare.py` + synthetic tests.
- [ ] Multi-seed legs rendered (CPU lane; GPU via the lead).
- [ ] Controls + study doc + owner question.

---

## Lessons

*(Fill in after the package is done.)*

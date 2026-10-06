# Gate (c) noise-aware metric study (pkg317, 2026-10-06)

**Decision (owner 2026-10-06): adopted candidate 1b** (8×8 tiles, RGB, Holm α = 0.05, 1 % margin, N = 8 seeds per
backend), conditional on the M1 re-run passing all three roles. It did (`astra_run\batch-i\m1b\`): gallery 0/7920,
workshop 0/24116, terrace 0/5940 rejected; negatives 0.97–1.00; every positive caught. Implemented in
`scripts/gate_manifest.py` row (c): Welch-1b must reject no tile in any role; the ±5 % ROI channel-mean band on the
8-seed means stays as a guard (it passes every negative control, so it costs no false reds); SSIM is informational;
non-vacuity is the unchanged paired-control check at the frozen seed. Evidence: `harness.py --seeds study` legs
(now with per-leg logs, control masks and `checker_flat`) adapted by `gate_manifest.py --adapt-c-seeds`.

The text below is the study as run (before adoption).

## Setup

- Trio roles from `gate_c.freeze.json`: materials_hall (gallery, 960x176, 256 spp), textures_mapping (workshop, 960x540,
  192 spp), world_sky terrace-with-hair (480x270, 128 spp). Gate settings unchanged.
- 8 independent seeds per backend (278, 1301, 2711, 4177, 6113, 7919, 9371, 11027; spread, never adjacent, #986), CPU and GPU
  baseline, plus GPU-side `hair_off` / `hdri_off` legs for terrace. Build = the gate's module (sha 93cc14f0...). Seed 278
  reproduces the 2026-10-05 gate legs bit-exactly on CPU and to 1e-6 on GPU (float atomics).
  Legs: `harness.py --seeds study --gate-c-freeze F --out D` (CPU) and the same under `gpu_locked_run.py` (GPU: 161 s for 66 legs).
  Local data `%LOCALAPPDATA%\astroray-evidence\2026-10-06\c-seeds\` (99 MB, not committed).
- Analysis: `python -m benchmarks.blender_parity.mc_compare` -> `study.json`, `study_tables.md`, `welch_pvalue_maps.png`
  (all under `astra_run\batch-f\f4\pkg317\`). Method and citation: `welch-bias-test-research.md` (Jung, Hanika, Dachsbacher 2020).
- Controls. Negative: all 35 half-splits (4 vs 4 seeds) of CPU-only and of GPU-only (independent noise, same engine; want PASS).
  Positive: injected on the 8 GPU renders (global x0.98, +3 % in the role's first ROI, 1-px shift, 1-px Gaussian blur) and the
  rendered `hair_off` / `hdri_off` legs (want FAIL). Welch: 8x8 tiles, three channels, Holm family-wise alpha = 0.05; the
  `margin1pct` variant only rejects a bias larger than 1 % of the tile mean.
- Synthetic unit tests (`tests/test_pkg317_mc_compare.py`): 200 null pairs give a per-test rate 0.0484 at alpha 0.05 and a Holm
  per-pair FWER 0.035 (<= 0.05 + 2 sigma); 2 % ROI bias, x0.98 and a missing feature fail; independent noisy pairs pass.

## Results (full tables: `astra_run\batch-f\f4\pkg317\study_tables.md`)

Real CPU vs GPU, 8 seeds each:

| candidate | gallery | workshop | terrace |
|---|---|---|---|
| gate SSIM >= 0.95 (existing; per-ROI, seed pairs) | PASS 0.964 | PASS 0.978 | FAIL 0.778 |
| ROI mean ratio +-5 % (existing) | PASS 0.0001 | PASS 0.0061 | PASS 0.0062 |
| 1 Welch 8x8 tiles, Holm | FAIL 48/7920 | FAIL 759/24116 | PASS 0/5940 |
| 1b Welch + 1 % margin | FAIL 46/7920 | FAIL 584/24116 | PASS 0/5940 |
| 2 SSIM vs same-backend ceiling (tol 0.01) | PASS 0.964 vs 0.964 | FAIL 0.977 vs 0.999 | PASS 0.777 vs 0.772 |
| 3 SSIM on 4x4 box-downsampled | PASS 0.998 | PASS 0.990 | PASS 0.989 |
| 4 SSIM of the 8-seed mean | PASS 0.995 | PASS 0.978 | FAIL 0.929 |

Controls (verdicts across all roles; negative = fraction of splits passing, positive = verdicts):

| candidate | negatives (cpu/cpu, gpu/gpu, 3 roles) | positives missed (of 14 role x control cells per candidate) |
|---|---|---|
| gate SSIM | terrace 0.00 (noise-bound; the original problem) | 5 (gallery gain, 3 % ROI, blur; workshop gain, 3 % ROI); terrace "FAIL" is vacuous (fails the null too) |
| ROI ratio +-5 % | 1.00 | 13 (blind below 5 % by design; also misses hair_off, shift, blur; only hdri_off caught) |
| **1 Welch** | 0.94-1.00 (expected 1 - alpha = 0.95) | **0** |
| **1b Welch + 1 % margin** | 1.00 | **0** |
| 2 SSIM ceiling | 1.00 | 6 (gain, ROI shift, blur on gallery and terrace) |
| 3 SSIM box 4x4 | 1.00 | 12 (hair_off, gain, ROI shift, blur, most shifts) |
| 4 SSIM of mean | terrace 0.00 (fails same-engine pairs at N = 4) | 6 (gallery: all 4; workshop: gain, ROI shift) |

Only candidates 1 and 1b pass every negative and fail every positive. Candidate 4 fails the negative control on terrace
because even the mean of 4 seeds is noise-bound there.

Sensitivity: on CPU-only halves (4 v 4), a global x0.999 already trips Holm in all three scenes (sky and large flat areas are nearly
noise-free), so the pure test (delta = 0) flags any systematic difference above ~0.1 %. A practical-equivalence margin is a
policy choice, not a statistical one.

## What the Welch test found in the real CPU/GPU pair (inspected, `real_cpu_gpu_difference.png`, `real_difference_crops.png`)

Terrace: no tile rejected. The noise-bound SSIM 0.778 is not a defect: hair, reflections and sky agree.

Gallery (materials_hall): a dark panel at about (x 690, y 90) of 960x176 renders pure black on the GPU and faintly lit on the CPU
(tile means 0.013 CPU vs 0.0 GPU), plus scatter on shiny props. Outside the gate's ROI and tiny in SSIM terms.

Workshop (textures_mapping): the procedural texture swatches on the back row (checker/noise/voronoi/wave) differ pixel-for-pixel
between backends, one smooth gradient swatch is offset, and the stripes under the swatches shift. Rejected tiles carry
essentially all of the signed difference (21.66 of 21.73 summed tile-mean difference, which is the 1.3 % lower GPU image mean).
These are real, localized CPU/GPU behaviour differences that the +-5 % ROI gate and SSIM >= 0.95 both pass. Root causes not
investigated (out of scope).

## Cost (render seconds per leg, this session)

| role | CPU leg | GPU leg | Welch N=8+8 | single pair (existing gate / 3 / 5) |
|---|---|---|---|---|
| gallery | 27.0 | 1.0 | 224 s | 28 s |
| workshop | 34.0 | 2.8 | 294 s | 37 s |
| terrace | 6.2 | 0.7 | 55 s | 7 s |

Welch needs N = 8 seeds per backend for the table above (null calibration was only run at 4 v 4; power at 4 v 4 was checked
only for gains). The CPU legs dominate; the CPU backend is the oracle, so one set of 8 CPU legs could be cached per build.
Analysis time is 50 s for everything.

## Owner decisions

1. Replace gate (c)'s SSIM >= 0.95 with the Welch tile test (Holm, 8x8 tiles, N = 8)? It is the only candidate that passes the
   negatives and fails every positive. Terrace turns green on the merits.
2. Accept that gallery and workshop turn RED on the same legs (a black GPU panel; GPU/CPU procedural-texture differences), i.e.
   the metric swap exposes real defects the current gate cannot see? Or gate with the 1 % margin (still red on both) and file the
   defects first?
3. If adopted: pure test or a margin (1 %?), N (8 vs 4), and whether the 5 % ROI band stays as a secondary gate.
4. The same swap would apply to run_parity world_sky_hdri (SSIM 0.807) and #1052 (not changed here).

Recommendation: adopt candidate 1b (Welch tiles, Holm, 1 % margin, N = 8) as the gate-(c) metric and file the two defects
(GPU black panel in materials_hall; CPU/GPU procedural texture mismatch in textures_mapping) as the work that turns it green.
Do not adopt 2-4 (each misses controls or fails the null) or keep SSIM alone (it measures noise on terrace).

## Caveats

- Only these three scenes; heavy-tailed noise (fireflies) can break normality of tile means. The 35-split null passes 94-100 %.
- Splits are not independent; the 0.94/0.97 gallery numbers are descriptive, not a calibrated false-positive rate.
- GPU legs reproduce only to 1e-6, so a "same-seed" GPU pair is not bit-identical; irrelevant at 8 seeds.

# pkg307 — Noise-per-time benchmark vs Cycles CPU/OptiX, with a Mitsuba 3 spectral arbitration leg

**Pillar:** 3
**Track:** B
**Status:** open
**Estimated effort:** 3 sessions (~9 h): Phase 1 1.5, Phase 2 1 (after owner install), Phase 3 0.5
**Depends on:** pkg284, pkg298

---

## Goal

Before:
- "Astroray is noisier than Cycles" has no reproducible measure.
- The corpus v2 harness (`mc_tolerance.py`) produces mean bands only.
- The Cycles leg is hard-coded to CPU (`render_leg.py`).
- Visual sheets put a 1024 spp Cycles reference beside 64 spp Astroray renders.
- No engine can arbitrate spectral scenes where the Cycles RGB reference and
  Astroray disagree.

After:
- One command produces an equal-spp and equal-time table per corpus v2 scene and
  ROI, committed as a dated record:
  - relVar, chroma relVar, relMSE split into variance and bias^2, the
    top-0.1 % tail share, N x relVar slope, and efficiency 1/(relMSE x t);
  - legs: Astroray CPU/GPU, Cycles CPU/OptiX, and Mitsuba 3 spectral on three
    arbitration scenes.
- Contact sheets compare engines at equal time.

---

## Context

This is the instrument for every gate in `research-noise-2026-09-29.md` §5 (N0-N4,
"parity" and "beat"). pkg305, pkg306 and pkg297 each need a before/after on the
same footing, and the owner wants to see whether Astroray "holds up against the
big guns".

Build it by extending the existing corpus harness, not as a new script
(CLAUDE.md §5b). GPU timing reuses pkg298's harness once it lands.

Sonnet 5.5 or DeepSeek implements, evidence-verified. Opus 5.5 reviews the
arbitration scenes.

---

## Evidence

- 2026-09-29 (`astra_run\RS\rs-noise\e1,e2`, `times.jsonl`): spp differencing
  (t(N2) − t(N1)) gives render-only per-sample time without Blender start-up.
  - Astroray GPU vs Cycles OptiX at 1280x720: 3.8-9.1x.
  - At 320x180 the same scenes read up to 16x, because small frames under-fill the GPU.
  - Cycles OptiX and CPU renders with the same seed agree to relMSE 2e-8 (bit-level determinism).
- 2026-09-29: Cycles OptiX is driven headless through a `load_post` hook that
  sets `compute_device_type = 'OPTIX'` (`rs-noise\pre.py`). `render_leg.py` has
  no Cycles-device flag.
- 2026-09-29: the corpus scenes author `blur_glossy = 0` and
  `sample_clamp_indirect = 0` (`benchmarks/blender_showcase/showcase.py:69-70`).
  This must be stated on every table: it is not Blender's default.

---

## Reference

- `.astroray_plan/docs/comparison-renderers-2026-09-29.md` (shortlist, install
  plan, benchmark design).
- `.astroray_plan/docs/research-noise-2026-09-29.md` (metrics, first table).
- `.astroray_plan/docs/research-performance-2026-09-29.md` and
  `packages/pkg298-perf-harness-bvh-cache-path-pool.md` (GPU timing instrument).
- Mitsuba 3 docs (BSD-3): variants `llvm_ad_spectral`, `cuda_ad_spectral`;
  plugins `volpath`, `dielectric` (spectral IOR), `rectangle`/`directional`
  emitters, `box` rfilter.
- Memories: `gpu-perf-ab-clock-drift`, `cuda_verifier_concurrency`,
  `pc-hard-resets-under-combined-load`, `ssim-wrong-gate-for-independent-rng`.

---

## Prerequisites

- [ ] Phase 2 only: owner approves the Mitsuba 3 install (companion doc, plan item 1).
- [ ] pkg298 Phase 0 merged, or Phase 1 uses spp differencing and switches later.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `benchmarks/reference_corpus/arbitration/build_arbitration.py` | Builds the three arbitration scenes in Blender (prism under sun + floor; chromatic homogeneous medium under a rectangle lamp; narrow-band emitter on a coloured wall) with box 1 px filter, clamps and filter glossy off |
| `benchmarks/reference_corpus/arbitration/mitsuba_scenes.py` | Hand-written Mitsuba 3 scene dicts matching those three scenes exactly (no exporter dependency) |
| `tests/test_pkg307_noise_bench.py` | Harness self-test on synthetic arrays: metric definitions (relVar, chroma, bias/variance split, tail share, efficiency) and the spp-differencing timer |

### Files to modify

| File | What changes |
|---|---|
| `benchmarks/reference_corpus/mc_tolerance.py` | Legs `cycles_gpu` and `mitsuba` (Phase 2); `--noise-bench` mode: equal-spp (64, 256) and equal-time (2/10/60 s budgets, from measured per-sample time) tables per scene and ROI, markdown + JSON under `test_results/noise_bench/`; shares `--tail-report` with pkg306 |
| `benchmarks/blender_parity/render_leg.py` | `--cycles-device cpu\|gpu` (OptiX) |
| `benchmarks/reference_corpus/report_tools.py` | Equal-time contact sheet (all legs at the same wall-time budget) |
| `scripts/README.md` | Register the new mode and the arbitration builders |

### Key design decisions

- **Timing.**
  - Per-sample time comes from spp differencing: min-of-3, after a burn-in.
  - GPU timing runs at ≥ 1280x720 (the manifest resolution scaled up), under
    `gpu_locked_run.py`, never beside a build.
  - Once pkg298's `wavefront_baseline.py` exists, call it for GPU legs instead.
- **Equal time.**
  - Render each leg at the spp its per-sample time affords within the budget,
    rounded down to a power of two.
  - Report relMSE against the scene reference, using 5 seeds for the variance
    term.
- **References.**
  - RGB-safe scenes: Cycles 1024 spp (existing `refs_v2/`).
  - Arbitration scenes: Mitsuba spectral at ≥ 16k spp.
  - Arbitration rule: Mitsuba vs Cycles vs Astroray. A Cycles-only disagreement
    is labelled "RGB reference limit". pkg307 does not decide pkg306 verdicts;
    it supplies the numbers.
- **Settings banner.** Every table header states:
  - clamps, filter glossy, adaptive and denoise;
  - the Cycles sampling pattern;
  - build SHAs;
  - GPU clock notes.
- **Phases.**
  - Phase 1: Cycles CPU/OptiX legs plus metrics on corpus v2. Delivers N0.
  - Phase 2: Mitsuba leg plus the arbitration scenes (after install).
  - Phase 3: a weekly entry in `scripts/benchmarks/weekly_local_bench.ps1`.

---

## Acceptance criteria

- [ ] Phase 1: one command writes the N0 table for 8 corpus v2 scenes x
      {Astroray CPU, GPU} x {Cycles CPU, OptiX} at equal spp and equal time.
      Two runs on a quiet machine agree within 10 % on every efficiency ratio.
- [ ] Phase 1: the harness self-test passes. It reproduces this research's
      `v2_sky_sun` sky ROI R/B relVar (0.0024 / 0.0026 ± 30 %) from fresh
      renders.
- [ ] Phase 2: the three arbitration scenes render in Astroray, Cycles and
      Mitsuba. On the narrow-band emitter scene, Mitsuba and Astroray means agree
      within 3 sigma (a sanity check of the arbitration setup itself).
- [ ] Phase 2: the dispersion-floor arbitration row exists for pkg306.
- [ ] Equal-time contact sheets exist for all scenes, and Opus or Astra has
      inspected them.
- [ ] No new parallel harness: the diff touches only the files listed above.

---

## Non-goals

- Do not change the renderer, sampler or estimators.
- Do not install anything without owner approval. pbrt-v4 and LuxCore legs are
  follow-ups.
- Do not gate CI on these numbers: they are measurement records, since CI has no GPU.

---

## Progress

- [ ] Phase 1: Cycles OptiX flag, noise-bench mode, metrics, self-test, N0 table
- [ ] Phase 2: Mitsuba leg + arbitration scenes (after install approval)
- [ ] Phase 3: weekly bench entry

---

## Lessons

*(Fill in after the package is done.)*

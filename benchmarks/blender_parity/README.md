# Blender differential parity harness (pkg119 Phase B)

The verification layer of the Integration Milestone. Phase A produced a
machine-readable **coverage matrix** (`docs/blender_parity/coverage_matrix.json`)
classifying every enumerable Blender feature as SUPPORTED / APPROXIMATED /
DROPPED-SILENT. Phase B takes the **SUPPORTED + APPROXIMATED** cells (the
differential test population), renders each through both **Cycles (oracle)** and
the Astroray **CUSTOM_RAYTRACER** addon, compares them, and triages every
failure into exactly one of three buckets that feed the roadmap.

## Architecture

```
coverage_matrix.json  (Phase A)
        │  select_features()  → 36 unique SUPPORTED/APPROXIMATED features
        ▼
harness.py  (driver, plain Python — NO bpy)
        │  per (feature, engine): spawn one headless-Blender subprocess
        ▼
render_leg.py  (INSIDE Blender, one engine)
        │  scene_library.build_scene(bpy, …) → render → <stem>.npy (linear f32)
        ▼
harness.py  loads both .npy, runs reference-bank metrics, gates, triages
        ▼
triage_report.json + triage_report.md
```

* **Subprocess isolation** (pkg71 discipline): Cycles and the Astroray addon
  hold conflicting global state, so each engine renders in its own Blender
  process — one subprocess per `(feature, engine)`. A leg that crashes, times
  out, or fails to print its `PKG119B_LEG PASS` sentinel is recorded as a
  crashed feature and **the run continues** (Phase-B "no crash on any feature").
  A crash back-propagates a note to close the feature's Phase-A UNKNOWN cell.
* **No new metric stack / no new render driver** (spec non-goal): the render legs
  reuse the pkg104 EXR→linear path and the metrics are pkg104's
  `benchmarks/reference_bank/metrics` (`compute_ssim`, `compute_delta_e_2000`).
  The only added computation is a per-channel mean ratio — one `np.mean` — used
  for triage, not a metric stack.
* **Runner substrate** is pkg175's dev loop (`scripts/dev_addon.ps1`,
  `dev_loop_guards.py`): same headless-Blender + staged-`.pyd` + sentinel
  discipline; the pytest gate skips cleanly with no Blender/GPU exactly like
  `tests/test_dev_loop_smoke.py`.

## Files

| File | Runs in | Purpose |
|------|---------|---------|
| `harness.py` | plain Python | driver + CLI: select, orchestrate, compare, triage, report |
| `render_leg.py` | Blender | build+render one `(feature, engine)` → `.npy`+`.png`+sentinel |
| `scene_library.py` | Blender | generic node-wiring + light/camera/world + composite scenes |
| `triage.py` | plain Python | thresholds + gate + rule-based triage (unit-tested) |

## What gates a feature

A feature **passes** iff:

* `compute_ssim ≥ 0.90` — structural agreement. The floor is deliberately loose:
  Cycles and Astroray draw *independent* Monte Carlo streams, so a tight
  windowed SSIM is unreachable at modest spp (memory
  `ssim-wrong-gate-for-independent-rng`). 0.90 still catches a black material,
  wrong texture, or missing feature.
* `compute_delta_e_2000 ≤ 8.0` — mean CIEDE2000 over the frame; a correct RGB
  translation lands well under it.

A per-channel mean-ratio band `[0.85, 1.18]` is **not** part of the pass gate; it
is used in triage to recognise a uniform energy-scale offset (e.g. pkg89
dedicated lights render ~3× hot) so it triages as INTENTIONAL-DIVERGENCE rather
than a translation bug.

## Triage buckets (every FAIL lands in exactly one)

| Bucket | Rule |
|--------|------|
| `INTENTIONAL-DIVERGENCE` | known-intentional table (pkg89 light energy/GPU-upload, spectral WAVELENGTH/BLACKBODY), OR Phase-A `APPROXIMATED`, OR uniform energy-scale ratio |
| `NOT-IMPLEMENTED` | explicit known-not-implemented table (filled from observed no-effect renders) |
| `TRANSLATION-BUG` | default: Phase-A `SUPPORTED` yet the render diverges |

`NOT-IMPLEMENTED` and `TRANSLATION-BUG` features are listed as follow-up-package
candidates in the report (round-close input). `INTENTIONAL-DIVERGENCE` is
documented, not "fixed" here — this package builds the measurement system, it
does not fix the red cells it finds (spec non-goal).

## Running

One command (needs Blender 5.x + a built addon `.pyd` + the GPU):

```
python -m benchmarks.blender_parity.harness \
    --matrix docs/blender_parity/coverage_matrix.json \
    --out test_results/blender_parity_diff
```

Outputs `triage_report.{json,md}` and per-leg renders under `renders/`.

The pytest wrapper `tests/test_blender_parity_harness.py` runs the pure
metric/triage/selection unit tests everywhere and the full differential run only
as a local-host gate that **skips cleanly** when Blender or the GPU is absent
(CI has neither).

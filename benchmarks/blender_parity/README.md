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
| `render_leg.py` | Blender | build+render one `(feature, engine)` → `.npy`+`.png`+sentinel; also `--export-blend`/`--load-blend`/`--report-only` for the reference-scene corpus below |
| `scene_library.py` | Blender | generic node-wiring + light/camera/world + composite scenes + the pinned `REFERENCE_SCENES` corpus |
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

### SPP-escalation (noise vs bug)

A single-spp read **cannot** tell MC noise from a mean-preserving structural bug:
both a noise-limited cell and a flipped/rotated-UV or geometry-offset bug can land
ratios-in-band + small-dE + low-SSIM (memory `mc-noise-vs-deterministic`). The
only robust discriminator is a **samples sweep**. So when a FAIL would otherwise
be `TRANSLATION-BUG` but its ratios are all in-band **and** mean dE is small
(`≤ DELTA_E_MAX/2 = 4.0`), the harness marks it a *noise-suspect* and **re-renders
both legs at 4× spp** (`ESCALATION_FACTOR`), then re-gates. `classify_noise_vs_bug`
(pure, in `triage.py`) then decides:

* **NOISE-LIMITED** if the higher-spp SSIM **crosses** `SSIM_MIN`, **or** it climbs
  by `≥ 0.03` (`NOISE_CLIMB_MARGIN`) **and** the gap-to-threshold shrinks by
  `≥ 40 %` (`NOISE_GAP_SHRINK`). A converging deficit is under-sampling, not a bug.
* **TRANSLATION-BUG** (unchanged) if the SSIM **plateaus** — a structural bug's
  deficit does not shrink with more samples, so it is never masked.

The escalation (both SSIM readings + the two spp) is written into the report so a
NOISE-LIMITED verdict is auditable. Without a sweep (e.g. the escalation render
crashed) the noise rule is skipped and the `TRANSLATION-BUG` default stands.

## Triage buckets (every FAIL lands in exactly one)

| Bucket | Rule |
|--------|------|
| `INTENTIONAL-DIVERGENCE` | known-intentional table (pkg89 light energy/GPU-upload, spectral WAVELENGTH/BLACKBODY), OR Phase-A `APPROXIMATED`, OR uniform energy-scale ratio |
| `NOT-IMPLEMENTED` | explicit known-not-implemented table (filled from observed no-effect renders) |
| `NOISE-LIMITED` | SPP-escalation sweep shows SSIM climbing toward the threshold with in-band ratios + small dE — under-converged, not a bug |
| `TRANSLATION-BUG` | default: Phase-A `SUPPORTED`, render diverges, and the SSIM deficit PLATEAUS across the SPP sweep (or no sweep was available) |

`NOT-IMPLEMENTED` and `TRANSLATION-BUG` features are listed as follow-up-package
candidates in the report (round-close input). `INTENTIONAL-DIVERGENCE` and
`NOISE-LIMITED` are documented, not "fixed" here — this package builds the
measurement system, it does not fix the red cells it finds (spec non-goal); a
NOISE-LIMITED cell is a harness-convergence note, not an engine defect.

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

## Pinned reference-scene corpus (north-star gate (c))

`--export-blend <dir>` builds and saves the three `.blend` assets required by
the Pillar-4 exit gate (c) in
`.astroray_plan/docs/north-star-and-integration-gate-2026-09-07.md` instead of
running the differential matrix:

```
python -m benchmarks.blender_parity.harness --export-blend benchmarks/blender_parity/scenes
```

For each of `cornell_interior` / `material_zoo` / `hdri_exterior_hair`
(builders + pinned resolution/spp in `scene_library.REFERENCE_SCENES`) this:
builds the scene and saves it under `scenes/`; reopens it headlessly to
census objects/nodes/triangle count; renders it with Cycles CPU at 32 spp into
`scenes/refs/` (small PNGs); attempts a tiny (<=320x180, <=32spp) Astroray CPU
render (a thrown exception is *recorded*, not fixed, in the manifest); and
runs the scene-specific non-vacuity checks (`checker_contrast_ok`,
`hdri_background_ok`, `hair_pixel_coverage_ok` in `harness.py`) against both
renders. All of this is written to `scenes/manifest.json` (SHA-256, triangle
count, node-id list, settings, non-vacuity results per engine).
`tests/test_reference_scene_corpus.py` checks the manifest SHA-256s against
the committed `.blend` files - no Blender needed.

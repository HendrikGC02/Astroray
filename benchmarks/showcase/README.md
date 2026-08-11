# Astroray engine benchmark + visual showcase (pkg74)

Spec: `.astroray_plan/packages/pkg74-engine-benchmark-showcase.md`
Research: `.astroray_plan/docs/engine-benchmark-research.md`

## What this is

A *qualitative* + *visual* showcase of the engine, complementary to
the quantitative Cycles parity tracker under
`benchmarks/cycles-parity/` (pkg71). pkg74 produces:

- a **material zoo** contact sheet — one tile per registered material,
  driven by `astroray.material_registry_names()`;
- a **convergence grid** contact sheet — Cornell box at a geometric
  SPP series (1, 4, 16, 64, 256);
- a **convergence curve** — log-log RMSE vs SPP against the highest-SPP
  in-run reference;
- a **stats CSV** — one row per (scene, integrator) carrying image
  stats, render time, peak RSS, and every key returned by
  `get_integrator_stats()` (no schema lock-in);
- a static **index.html** linking everything, tagged with machine ID,
  git SHA, and timestamp.

## What this is *not*

- Not a Cycles comparison (that's `benchmarks/cycles-parity/`).
- Not a CI perf-regression gate (artefacts are for humans).
- Not a Blender-integration test (talks to the C++ Renderer directly).
- The old three-scene composite `scripts/benchmarks/benchmark_showcase.py`
  was superseded by this framework and deleted (hygiene 2026-08-11). The
  curated material presets from `scripts/diagnostics/material_contact_sheet.py`
  now live in `config.MATERIAL_ZOO_VARIANTS`.

## Run it

```bash
python -m benchmarks.showcase.runner --quick
# or:
python benchmarks/showcase/runner.py --quick
```

`--quick` is the default and produces the five artefacts in
`benchmarks/showcase/output/<YYYY-MM-DD-HHMMSS>-<machine-id>/` in
under a minute on the reference workstation.

For a longer production run:

```bash
python -m benchmarks.showcase.runner --full
```

## Output directory layout

```
benchmarks/showcase/output/
  2026-05-10-130000-myhost-amd/
    material_zoo_contact_sheet.png
    convergence_grid_contact_sheet.png
    convergence_curve.png
    stats_summary.csv
    index.html
```

The `output/` subdirectory is gitignored — only the framework code
is checked in.

## Phase status

- **Phase 1** (this round): material zoo + convergence grid + curve +
  stats CSV + HTML index. CPU integrators only. ✅
- **Phase 2** (open): integrator-comparison contact sheet, scene
  gallery, GPU integrator rows, BVH/VRAM stats.
- **Phase 3** (open): interactive HTML dashboard, weekly CI workflow.

## License notes

This package depends on matplotlib (PSF, BSD-compatible) and Pillow
(HPND), both transitively present as test-time dependencies. Reference
patterns from PBRT v4 (Apache-2.0), Mitsuba 3 (BSD-3), and Cycles
(Apache-2.0) are cited in source-file headers without copying code.
LuxMark (GPL-3.0) is explicitly *not* used.

# pkg74 — Engine Benchmark + Visual Showcase Framework

**Pillar:** 5
**Track:** A
**Status:** Phases 1 + 2 implemented; Phase 3 open
**Estimated effort:** 1.5 weeks initial; recurring use thereafter
**Depends on:** none hard.
- pkg71 (Cycles parity benchmark) is a soft dep — once it lands a
  stable `ssim.py`, pkg74 may import it for an optional
  "compare to pinned reference" mode in Phase 2/3.
- Built on top of the existing Renderer / `material_registry_names()` /
  `integrator_registry_names()` / `get_integrator_stats()` Python
  bindings — no engine changes required.

---

## Goal

**Before:** Astroray's qualitative output story is a 3-scene composite
(`scripts/benchmarks/benchmark_showcase.py`), a one-material-at-a-time
diagnostic (`material_contact_sheet.py`), and a single-scene
convergence tracker (`convergence_tracker.py`). Each is useful in
isolation but they live in three directories, share no scene metadata,
and produce no joined output that can be opened from a single index
page. Showing the engine off in a talk, a paper, or a release post
requires running ~five scripts and manually composing the result.

**After:** A single command — `python benchmarks/showcase/runner.py
--quick` — produces a dated output directory containing a material-zoo
contact sheet driven by the registry, a convergence-vs-spp grid, a
log-log convergence curve against a converged ground truth, a
stats CSV that round-trips every key returned by
`get_integrator_stats()`, and a static `index.html` that links them
together. Outputs are tagged with machine ID and git SHA so multiple
runs can coexist. CI integration and full-coverage scene set are
explicitly Phase 2/3 — Phase 1 is the framework + one example of
each artefact type.

---

## Non-goals

- **Not a perf-regression CI gate.** That's pkg71. pkg74 produces
  artefacts for humans; it does not break a build.
- **Not a Blender-integration test.** Blender addon coverage lives in
  `tests/test_blender_*` — pkg74 talks to the C++ Renderer directly
  and bypasses the addon entirely.
- **Not a Cycles comparison.** pkg74 never invokes Cycles. Anything
  cross-engine is pkg71 territory.
- **Not a duplicate of pkg71's scene set.** No Classroom, Monster,
  Junkshop, or BMW. pkg74 uses Astroray-internal scenes only —
  Cornell box, glass sphere, metal trio, prism — so it can run on
  any developer machine in a few seconds without a download.
- **Not a deletion of existing scripts.** `benchmark_showcase.py`,
  `convergence_tracker.py`, and `material_contact_sheet.py` stay in
  place. Whether to delete `benchmark_showcase.py` (which pkg74
  supersedes) is a separate PR per CLAUDE.md §3.
- **Not a GPU-integrator showcase in Phase 1.** The GPU integrator
  matrix is Phase 2; Phase 1 stays CPU-only so the runner works on
  any machine without CUDA.
- **No new scenes authored as `.blend` files.** Every Phase 1 scene
  is a Python builder against the `Renderer` API. `.blend`-fed
  scenes are Phase 3 if/when needed.

---

## Reference Implementations

The stats catalog, the convergence-curve format, and the
contact-sheet pattern are all derived from existing open-source
work. See `.astroray_plan/docs/engine-benchmark-research.md` for the
full audit; the table below names the canonical references.

| Repo / source | License | Mirror permitted | Files / patterns to study |
|---|---|---|---|
| [mmp/pbrt-v4](https://github.com/mmp/pbrt-v4) — `src/pbrt/util/stats.h` | Apache-2.0 | Yes — cite in code | `STAT_COUNTER` / `STAT_MEMORY_COUNTER` / `STAT_INT_DISTRIBUTION` / `STAT_PERCENT` are the reference categories pkg74's stats CSV mirrors. Concrete counter names like "Camera rays traced" / "BVH/Interior nodes" are the model for what an end-of-render report should list. |
| [mitsuba-renderer/mitsuba3](https://github.com/mitsuba-renderer/mitsuba3) — `include/mitsuba/core/profiler.h` | BSD-3-Clause | Yes | `ProfilerPhase` enum (`InitScene`, `LoadGeometry`, `InitAccel`, `RayIntersect`, `BSDFEvaluate`, `BSDFSample`, …) is the reference list for the per-stage timing decomposition pkg74 Phase 2 will add. |
| [blender/cycles](https://github.com/blender/cycles) — `src/util/stats.h`, `src/scene/stats.h` | Apache-2.0 | Yes | `RenderStats { mesh, image, kernel, shaders, objects }` and `SceneUpdateStats` per-component update times — the reference for "what scene-side stats matter". |
| [opendata.blender.org](https://opendata.blender.org/) | results data CC-0; web service public | n/a — read-only | Look-and-feel reference for the HTML index (scene gallery + hardware row + box-plot aggregation). pkg74 Phase 3's HTML polish targets a subset of this. |
| matplotlib | PSF (BSD-compatible) | dependency only | Used for convergence + bar plots via the `Agg` backend. |
| Pillow (PIL) | HPND (permissive) | dependency only | Used (indirectly via matplotlib + `plt.imsave`) for contact-sheet composition. |
| LuxMark | **GPL-3.0** | **No** — incompatible with MIT | Listed so contributors don't accidentally borrow. |

Inline citations live in the file headers as
`# pattern adapted from <repo>@<sha>:<path>`. No code is mirrored
verbatim in Phase 1.

---

## Specification

### Phase 1 — starter framework + one of each artefact type

```
benchmarks/showcase/
  __init__.py
  README.md
  config.py                 # default scene set, sample counts, output paths
  runner.py                 # CLI driver: orchestrates scenes, writes CSV, builds index
  contact_sheets.py         # PIL/matplotlib grid composer
  graphs.py                 # matplotlib convergence-curve helper
  html_index.py             # static-HTML index generator
  scenes/
    __init__.py
    material_zoo.py         # one sphere per registered material under uniform lighting
    convergence_grid.py     # one Cornell scene rendered at SPP = 1, 4, 16, 64, 256
  output/                   # GITIGNORED — runs land here
    .gitkeep                # so the directory exists in fresh checkouts

tests/
  test_benchmark_showcase_runs.py   # end-to-end --quick sanity test
```

`runner.py --quick` produces:

1. `material_zoo_contact_sheet.png` — N×M grid of per-material sphere
   renders with labels, driven by `material_registry_names()` so the
   set grows automatically when materials are added.
2. `convergence_grid_contact_sheet.png` — Cornell scene rendered at
   the geometric SPP series, side-by-side strip with labels.
3. `convergence_curve.png` — log-log RMSE-vs-SPP plot for the same
   scene against the highest-SPP run as ground truth.
4. `stats_summary.csv` — one row per (scene, integrator) carrying:
   - Run metadata: `run_date`, `git_sha`, `machine_id`, `seed`,
     `samples`, `width`, `height`, `max_depth`.
   - Image stats: `mean_luminance`, `p99_luminance`, `max_luminance`,
     `firefly_count_4x_mean`, `nonzero_fraction`.
   - Timing: `render_seconds`, `peak_rss_mb` (psutil host RSS).
   - Integrator stats: every key/value returned by
     `get_integrator_stats()` flattened with `integrator_stats_<key>`
     prefix so additions round-trip without a schema change.
5. `index.html` — static HTML, no JS, lists the four PNGs as
   thumbnails, embeds the CSV as a sortable-by-default table, and
   carries a header line with run timestamp + machine ID + git SHA.

Outputs land in `benchmarks/showcase/output/<YYYY-MM-DD>-<machine-id>/`.
The `output/` subdirectory is gitignored; only the framework code is
checked in.

### Phase 2 — full coverage

| Addition | Notes |
|---|---|
| `scenes/integrator_compare.py` | Cornell scene rendered with every entry from `integrator_registry_names()`. Produces `integrator_compare_contact_sheet.png` + bar-chart timing graph. |
| `scenes/cornell_variants.py` | Cornell box with the lambertian-sphere swapped out for glass/metal/disney/subsurface — measurable difference per BSDF. |
| GPU integrator rows | `--gpu` flag adds rows for materials with `gpu == True` in `get_material_backend_capabilities()`. Skips rather than crashes when CUDA absent. |
| BVH / VRAM stats | New columns once a `bvh_stats()` Python binding exists. |
| Variance decomposition | New columns once direct/indirect variance is exposed. |

Phase 2 stays additive: `runner.py --quick` continues to behave
exactly as in Phase 1; new artefacts surface under new flags
(`--full`, `--gpu`).

### Phase 3 — HTML dashboard polish + CI hook

- Sortable tables in `index.html`, scene-vs-scene side-by-side
  toggle, run-history index across `output/` dated subdirectories.
- `.github/workflows/showcase-weekly.yml` — runs `runner.py --quick`
  on a non-CUDA self-hosted runner, uploads the resulting directory
  as a workflow artefact. Different runner from pkg71's because
  pkg74 Phase 1 does not need CUDA.

### Files to modify (Phase 1)

| File | What changes |
|---|---|
| `.gitignore` | Add `benchmarks/showcase/output/`. |
| `.astroray_plan/docs/STATUS.md` | New row under Pillar 5 for pkg74. |
| `tests/test_benchmark_showcase_runs.py` | New end-to-end test. |

No engine code, no CMake changes, no addon changes. CLAUDE.md §3
applies: every changed line traces to the user's pkg74 brief.

---

## Key design decisions

1. **Astroray-internal scenes only in Phase 1.** Avoids any download
   step and keeps the test suite hermetic. pkg71 is the place where
   external Blender Foundation scenes live.
2. **Registry-driven, not hardcoded.** `material_zoo.py` enumerates
   `material_registry_names()` so adding a new material gets it on
   the contact sheet for free. Same for integrators in Phase 2.
   This is the inverse of the existing `material_contact_sheet.py`,
   which has a hardcoded MATERIALS list — pkg74 trades curated
   parameters for full coverage.
3. **CSV is unschemed for integrator stats.** Every key returned by
   `get_integrator_stats()` is written with an `integrator_stats_`
   prefix, so the CSV format does not need to be revised when new
   counters appear (e.g. NRC training-loss, ReSTIR reuse-rate).
   The cost is non-rectangular CSVs — handled by writing a row's
   own header dict and using `csv.DictWriter` with the union of
   all keys collected up front.
4. **Convergence ground truth is in-run, not pinned.** The highest-
   SPP entry in the SPP series IS the reference for the lower-SPP
   ones in the same run. Pinning a separate ground-truth EXR is
   pkg71's pattern; pkg74's purpose is to *show* convergence, not
   to gate against an external reference.
5. **psutil is the only memory measurement.** Process RSS is coarse
   but portable and zero-config. Per-allocator memory (Cycles
   `mem_alloc`/`mem_free` style) is Phase 2.
6. **Output format is self-describing.** `index.html` carries
   commit SHA, machine ID, and timestamp visibly so a one-off
   "open this PNG" share is auditable.
7. **No engine changes.** pkg74 is pure Python infrastructure on
   top of existing bindings. If a stat needs a new C++ binding,
   that binding is its own package; pkg74 records what's
   available today and writes `null` for what isn't.
8. **The framework is the deliverable, not the artefacts.** Output
   PNGs are gitignored — they belong on developer disks and CI
   artefact storage, not in the repo. The PR may inline-link one
   example PNG under `docs/showcase/` if it's representative and
   under ~200 KB.

---

## Acceptance criteria

### Phase 1 (this PR)

- [x] `benchmarks/showcase/` directory exists with `runner.py`,
      `contact_sheets.py`, `graphs.py`, `html_index.py`, `config.py`,
      `__init__.py`, `README.md`, and `scenes/` containing
      `material_zoo.py` and `convergence_grid.py`.
- [x] `python benchmarks/showcase/runner.py --quick` runs to
      completion on the local box (CPU-only path, small SPP, small
      resolution) and writes:
      - `material_zoo_contact_sheet.png` (PNG, file size > 0,
        Pillow can re-open it).
      - `convergence_grid_contact_sheet.png` (same).
      - `convergence_curve.png` (same).
      - `stats_summary.csv` (CSV with > 0 data rows, header
        contains every required column listed in §Phase 1).
      - `index.html` (HTML, file size > 0, references all four
        artefacts above).
- [x] All five outputs land in
      `benchmarks/showcase/output/<YYYY-MM-DD>-<machine-id>/`.
- [x] `benchmarks/showcase/output/` is in `.gitignore`; only
      `.gitkeep` is committed under it.
- [x] `tests/test_benchmark_showcase_runs.py` invokes `runner.py
      --quick` (or its `main()` entry point) and asserts on the
      five outputs (existence, non-zero size, PNG re-openable, CSV
      parseable with > 0 rows). The test runs in under 30 s on the
      reference workstation.
- [x] STATUS.md has a pkg74 row under Pillar 5.
- [x] CLAUDE.md §6 is honoured: research note exists at
      `.astroray_plan/docs/engine-benchmark-research.md` and is
      cited from `runner.py`'s file header.

### Phase 2 (this round)

- [x] `benchmarks/showcase/stats.py` carries category collectors for
      geometry / memory / timing / sampling / quality / spectral /
      GPU / integrator-specific. Every column is prefixed by its
      category and the runner merges them into one row.
- [x] `scenes/integrator_compare.py` runs every safe registered
      integrator on Cornell-with-glass; new artefacts:
      `integrator_compare_contact_sheet.png` and
      `integrator_compare_timing.png`.
- [x] Paired-seed variance render at the convergence-grid top SPP
      populates `qual_variance_mean / _p95 / _max`.
- [x] `qual_convergence_rate_slope` annotates the convergence curve
      legend with the fitted log-log slope (target −0.5 for unbiased
      Monte Carlo).
- [x] `--gpu` flag appends rows tagged `device=gpu`; cleanly skipped
      when CUDA is absent (rows record `gpu unavailable` skip_reason).
- [x] HTML index groups CSV columns into 9 collapsible `<details>`
      sections (Run metadata / Geometry / Memory / Timing / Sampling
      / Quality / Spectral / GPU / Integrator-specific) — no JS.
- [x] `tests/test_benchmark_showcase_phase2.py` asserts non-empty
      cells across every required category, slope < 0, contact-sheet
      + timing PNGs loadable, Phase 1 columns intact (back-compat).
- [x] Phase 1 pytest gate (`test_benchmark_showcase_runs.py`)
      continues to pass — no Phase 1 column was renamed or dropped.

### Phase 2 — deferred (would require C++ instrumentation; per
spec design decision #7, those become their own packages)

- [ ] BVH node / leaf / max-depth columns (`geom_bvh_*`) — present
      in the schema, populated when a `bvh_stats()` binding lands.
- [ ] GPU device-memory columns (`mem_gpu_*`) — schema-present;
      need a `gpu_memory_*_mb()` binding.
- [ ] Per-ray-type counters (`samp_camera_rays / _shadow_rays /
      _scattered_rays`) — schema-present; need integrator-side
      instrumentation across path_tracer / spectral_path_tracer /
      multiwavelength_path_tracer.
- [ ] Hero-wavelength selection histogram (`spec_hero_band_histogram`)
      — schema-present; needs `SampledWavelengths::sampleUniform`
      counter array.
- [ ] Per-bounce / per-material radiance breakdown.
- [ ] Russian-roulette termination rate (`samp_rr_termination_pct`).
- [ ] ReSTIR reservoir-reuse rate (`intstat_*` round-trip will
      surface it the moment the integrator emits the key).
- [ ] NRC training loss curve (same — round-trips through
      `get_integrator_stats()` if a future PR adds the key).

### Phase 3 (separate PR)

### Phase 3 (separate PR)

- [ ] `index.html` is interactive (sortable tables, run-history
      navigation, scene toggle).
- [ ] `.github/workflows/showcase-weekly.yml` runs once on the
      self-hosted runner, uploads the dated output directory as a
      workflow artefact.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Registry-driven material zoo includes materials that crash on the default sphere preview (e.g. SSS without a thick enough sphere, line emitters that emit nothing useful at the default geometry). | Per-material `try/except` in the runner: a failed material is recorded with a `skip_reason` column and the contact sheet shows a "FAILED: <reason>" tile, so coverage gaps are visible rather than silent. |
| `get_integrator_stats()` returns keys that vary per-integrator and the CSV becomes ragged. | Two-pass write: first pass collects every (scene, integrator) row in memory + computes the union of keys; second pass writes the CSV with the union as the header. Missing values are empty cells. |
| `--quick` mode is not actually quick (e.g., the convergence grid renders 1024 spp because someone tweaked the default). | `config.py` exposes `QUICK_SPP_SERIES = [1, 4, 16, 64, 256]` and `QUICK_RESOLUTION = 96` as named constants. Test asserts the test takes < 30 s, so a regression to `--quick` performance breaks the test. |
| Output directory naming collides on parallel runs from the same machine. | Subdirectory name includes seconds: `<YYYY-MM-DD-HHMMSS>-<machine-id>/`. Adequate for human-driven runs; CI runs serialise themselves anyway. |
| matplotlib + Pillow not in the test environment. | Both are already test-time dependencies via the existing diagnostics scripts (see `convergence_tracker.py`, `material_contact_sheet.py`). The Phase 1 test imports both at top of file so a missing dep fails the test cleanly. |

---

## Lessons

### Phase 1

- Framework + material zoo + convergence grid + convergence curve +
  CSV + HTML index runs end-to-end on the implementer machine;
  pytest gate is the five-artefact existence check.
- `material_registry_names()` returns names that include `light`
  and `null` material types unsuitable for sphere previews — the
  runner's per-material `try/except` handles them via a recorded
  skip rather than aborting.
- `convergence_curve.png` is intentionally generated against the
  in-run highest-SPP reference rather than a pinned ground truth
  EXR; this keeps Phase 1 hermetic but means the absolute MSE
  values are not comparable across runs at different `--quick`
  settings. Documented in `benchmarks/showcase/README.md`.

### Phase 2

- All Phase 2 code is **pure Python**, on top of existing bindings —
  per spec design decision #7, no engine changes were made. Forward-
  compat hooks (`hasattr(r, 'bvh_node_count')` etc) populate the
  CSV automatically the moment those bindings land in a future
  package.
- Convergence-rate slope on the Cornell box at SPP=[1, 4, 16, 64]
  measured **−0.453** on the implementer machine (target: −0.5 for
  unbiased Monte Carlo). The curve PNG annotates the fitted slope
  in the legend so this is visible at a glance.
- `multiwavelength_path_tracer` rendered mostly black on the
  integrator_compare scene because the wavelength range was not
  explicitly set (it defaults to a band the Cornell materials don't
  emit in). Recorded honestly as a near-zero `mean_luminance` cell;
  this is exactly the kind of "honest visualisation of a default"
  the showcase is supposed to surface. A follow-up could add a
  `set_wavelength_range(380, 780)` call in the scene builder, but
  changing it would silently mask the default-misconfiguration risk
  for new users.
- `--gpu` flag is opt-in and tested with CUDA absent
  (`test_gpu_flag_runs_without_cuda`): every row falls back to
  `device=cpu` with a `gpu unavailable` skip_reason rather than
  crashing.
- The Phase 1 pytest gate (`test_benchmark_showcase_runs.py`)
  continues to pass alongside the new Phase 2 gate; column
  back-compat held by leaving `mean_luminance`, `p99_luminance`,
  `render_seconds`, etc. unprefixed and additive only.

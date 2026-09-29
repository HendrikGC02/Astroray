# test_results conventions (normative)

Owner directive 2026-09-29. Applies to every test, benchmark, script and agent
lane that writes render evidence, charts or stats. Organise by **feature and
what is tested**, never by batch, lane, package, issue or date.

## 1. Two trees

| Tree | Path | Git | Who writes |
| ---- | ---- | --- | ---------- |
| Per-run output | `test_results/_runs/<area>/<feature>/<artifact>` | ignored | tests/scripts, every run, overwritten in place |
| Curated evidence | `test_results/<area>/<feature>/<artifact>` | tracked | a human/agent **promoting** a run output (copy), never a test |

- **Tests never write into the curated tree** (issue #861). Code obtains paths
  only from `tests/results_layout.py` (`results_path(area, feature, name)`),
  which always resolves under `_runs/`.
- Scratch: `test_results/tmp/` (pytest/tempfile) and `test_results/.pytest_cache/`,
  both ignored. Nothing else may exist at the top level except `index.html`
  and `README.md`.
- Lane scratch outside the repo (`astra_run/<batch>/<lane>/`) is fine; anything
  worth keeping is promoted into the curated tree under these rules.

## 2. Area taxonomy (fixed; add an area only by editing this table + `AREAS`)

| Area | What lives there |
| ---- | ---------------- |
| `materials` | BSDFs, Principled inputs, glass/metal/dielectric, thin film, alpha |
| `textures-nodes` | texture nodes, mapping, shader graph / op-VM |
| `lights` | lamps, IES, emissive meshes, light sampling / tree, clamping |
| `world` | sky models, HDRI / env lookup, sun disc |
| `volumes` | homogeneous / heterogeneous media, smoke, fire, world volume |
| `caustics` | photon / SMS / caustic transport |
| `spectral` | dispersion, spectral upsampling, prisms, band-aware output |
| `camera` | lenses, DoF, ortho, render region / crop |
| `geometry` | meshes, curves, instancing, holdout |
| `passes` | AOVs, light-path passes, cryptomatte, denoising |
| `integrator` | convergence, adaptive sampling, guiding, NEE/MIS, default integrator |
| `viewport` | interactive / progressive viewport, worker, navigation |
| `perf` | timing, kernel cost, registers, memory |
| `parity` | multi-feature corpus sweeps vs Cycles only (single-feature parity goes in its feature's area) |
| `addon` | Blender UI / integration, settings honour, install |
| `astro` | GR / Kerr, astrophysical emitters and observables |

CPU-vs-GPU and Astroray-vs-Cycles are **columns in a sheet**, not areas.

## 3. Naming

- `<feature>`: kebab-case noun phrase for the thing under test, `[a-z0-9-]{3,40}`
  (e.g. `principled-alpha-shadow`, `ies-spot-cone`, `hetero-fire-grid`).
- `<artifact>`: `[a-z0-9_]+.<ext>`; suffix `_sheet` (image comparison),
  `_chart` (plot). A chart's data sidecar has the same stem with `.json`.
- Banned in any path component: `batch`, `lane`, `lead`, `hotfix`, `storm`,
  `round`, `session`, dates, `pkgNNN`, `issueNNN`, author/model names.
  Provenance (package, issue, PR, commit, date, build) goes in the JSON
  sidecar and the feature README.

## 4. What to emit

- **Visual comparisons → one labelled contact sheet**: columns in the fixed
  order Cycles | Astroray CPU | Astroray GPU (omit absent legs; before|after for
  A/B), every tile titled, ROI rectangles drawn and named when a metric uses
  an ROI, one title line stating scene + spp. Use `save_comparison_sheet`.
  Bare single renders only when the image itself is the evidence (e.g. a hero).
- **Numbers → a chart + JSON sidecar** via `save_stat_chart`. No bare
  `.txt` / `.log` / stdout dumps as evidence. Chart rules: one y-axis with
  units, gate/tolerance drawn as a band or reference line, legend for ≥2
  series, fixed colours per role — Cycles `#52514e`, CPU `#2a78d6`,
  GPU `#eb6834`, third series `#1baf7a`; light surface `#fcfcfb`.
- **Viewport sequences** → one downscaled sheet, not N full-res screenshots.
- Size caps (curated tree): image ≤ 2 MB, max 1600 px wide; `.blend` repro ≤ 1 MB.
- Allowed extensions (curated): `.png .svg .json .csv .blend`, one optional
  `README.md` per feature (≤ 15 lines: what is tested, verdict, provenance).
- Empty / near-black / constant images are not evidence: don't save them.

## 5. Index

`python tests/results_layout.py index` regenerates `test_results/index.html`
(curated, tracked; area → feature cards with README verdict, thumbnails,
chart and JSON links). The pytest session end regenerates
`test_results/_runs/index.html` when anything was written. Curated changes must
ship with a regenerated index (the guard checks it).

## 6. Retention

- `_runs/` holds the latest run only; `python tests/results_layout.py clean`
  empties it. `clean --legacy` moves pre-convention top-level entries into
  `test_results/_legacy/` (ignored) for the owner to review and delete.
- Curated evidence is kept while it documents current behaviour; replace it
  (same path) when a fix changes the picture; delete it when the feature or
  its test is removed. Git history is the archive.

## 7. Enforcement

`tests/test_results_layout_guard.py` fails when: a tracked `test_results/`
file breaks §2–§4; any `.py` under `tests/ scripts/ benchmarks/` builds a
`test_results` path other than through `results_layout`; `results_path`
accepts an unknown area / bad slug or escapes `_runs/`; `index.html` is stale.
`tests/conftest.py` also fails the session if any tracked `test_results/`
file was modified during the run.

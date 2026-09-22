# pkg48 — HDF5 & NumPy Simulation Data Loader

**Pillar:** 4
**Track:** B
**Status:** paused — Pillar 4 (Stage 3); rewritten 2026-09-22 (DensityGrid path retired)
**Estimated effort:** 1 session (~3 h)
**Depends on:** pkg267

---

## Goal

Before: pkg48 specified a bespoke `DensityGrid`/`SimulationVolume` C++ plugin and an in-house `.npy` parser; neither was ever written, and pkg267 has since landed the real volume contract (`GridMedium` + `set_volume_grid` + Blender-native OpenVDB import). After: `scripts/sim_to_volume.py` converts HDF5 (`h5py`), yt and `.npy` simulation fields into dense arrays for `set_volume_grid` or into `.vdb` files, carrying cgs units, world transform and per-field provenance in a sidecar JSON, with resampling loss measured rather than assumed.

## Context

The engine already ingests dense NumPy density/temperature grids directly and reads `.vdb` through Blender's bundled `openvdb`. The missing piece is not an engine reader but a trustworthy converter: simulation data must arrive with declared units, transforms and provenance, and the mass/energy lost in regridding must be measured. Without it, ingest silently rescales physics. This is conversion tooling for the Pillar 4 tracks (pkg46 nebula, pkg49 SPH), not a new engine subsystem.

## Evidence

- 2026-09-22: rewritten in the planning session (stage-plan-2026-09-22.md §4); previous text superseded.
- 2026-09-22: Codex Terra review defects applied (planning session).
- 2026-09-13: pkg267 (PR #810) landed `GridMedium` + majorant grid, `PyRenderer.set_volume_grid`, and Blender-native OpenVDB import (`blender_addon/volume_export.py`).
- `include/astroray/density_grid.h`, `plugins/data/simulation_volume.cpp` and `include/astroray/npy_reader.h` do not exist on main; the old spec's engine-plugin path was never implemented.
- Stage plan §4: dense NumPy density/temperature arrays already reach the engine; the packages become conversion tooling with units, transforms, field provenance, conservation and resolution-convergence evidence.

## Reference

- Design: `.astroray_plan/docs/pillar4-data-io-research.md §§1, 3, 4, 6` — the DensityGrid/HDF5/npy sections; the common-volume-type part is superseded by `GridMedium`.
- Design: `.astroray_plan/docs/astrophysics.md §4.5` (simulation data import).
- Engine contract: `include/astroray/volume/grid_medium.h`; `module/blender_module.cpp` (`set_volume_grid`); `blender_addon/volume_export.py` (read side); `include/astroray/volume/volume_emission.h` (pkg270 temperature emission).
- Sibling input path: pkg47 `include/astroray/fits_io.h` + `plugins/data/fits_loader.cpp`; its deferred `FITSVolume` registration (owner ruling 2026-05-15) is not revived here.
- External licenses: HDF5 (BSD-style, HDF5 Software License 1.0), `h5py` (BSD-3-Clause), yt (BSD-3-Clause), NumPy `.npy` format spec (BSD-3-Clause), OpenVDB / Blender-bundled `openvdb` (MPL-2.0).
- External: Case-B Hα/Hβ ≈ 2.86 reference (A&A 2021, aa40890-21) — the downstream tolerance this ingest must not perturb.

## Prerequisites

- [ ] pkg267 is done and tests are green (done: PR #810).
- [ ] Build passes on main.
- [ ] (Added for Phase 2 only) Blender 5.2 with the bundled `openvdb` module available.

## Specification

### Files to create

| File | Purpose |
|---|---|
| `scripts/sim_to_volume.py` | Convert HDF5/yt/.npy simulation fields to dense arrays (for `set_volume_grid`) or `.vdb`, plus a provenance sidecar JSON and a resampling-loss report. |
| `tests/test_pkg48_sim_to_volume.py` | Round-trip Gaussian-blob mass-conservation test, unit-conversion and provenance-schema tests (synthetic files under `tmp_path`). |

### Files to modify

| File | What changes |
|---|---|
| `scripts/README.md` | Register `sim_to_volume.py` as the canonical simulation-→-volume conversion script (same-commit rule). |
| `.astroray_plan/docs/STATUS.md` | Record pkg48's rewrite and its paused/dispatch state. |
| `CHANGELOG.md` | Add the pkg48 conversion-tooling entry. |

### Key design decisions

- **Retire the engine plugin.** No `DensityGrid`, `SimulationVolume`, `npy_reader.h`, HighFive/HDF5 C++ dependency, or `ASTRORAY_ENABLE_HDF5` flag. The engine contract is `set_volume_grid(name, density, bbox_min, index_to_object, object_to_world, density_scale, …, temperature, temperature_bbox_min, …)`: `density` is a dense float32 `(nz, ny, nx)` C-order array, `bbox_min` the `(i, j, k)` active-block minimum, transforms row-major 4×4.
- **Field-role → renderer mapping is declared and recorded.** Every field role has exactly one renderer consumer, unit convention and conversion, written to the sidecar; a role without a mapping is carried as provenance only and forces `"renderer_supported": false`:
  - `density` (g/cm³) → voxel values of `set_volume_grid`. The API's `density_scale` is the dimensionless Principled "Density" multiplier `D` (`σ_s/σ_a ∝ D · density(p)`), so the adapter folds opacity into `D`: `density_scale = κ_ref`, giving `σ_t = density_scale · ρ_phys · κ(λ)`. Default `κ_ref = 1.0` cm²/g `(frozen 2026-09-22, lead may adjust)` — a synthetic unit-opacity normalisation, **not** a measured dust/line opacity; any physical-σ claim requires an explicit `--opacity-cm2-per-g` with provenance for `κ` (source constant cited at use).
  - `temperature` (K) → `set_volume_grid`'s `temperature` grid (pkg270 emission); `blackbody_temperature`/`emission_strength` must be set explicitly, never defaulted silently.
  - `ion_fraction` (dimensionless) and `velocity` (cm/s) → no engine consumer; sidecar provenance only.
  - The sidecar records role, unit, conversion factor, target API argument and the resulting `density_scale`.
- **Input adapters, one output contract.** `h5py` for HDF5 datasets (user names the group/dataset paths), yt for frontend-specific snapshots (in-memory covering grid), and `.npy`/`.npz`. Every adapter emits the same field record; no per-format runtime in the engine.
- **cgs units, declared not inferred.** Density `g/cm^3`, temperature `K`, ionisation fraction dimensionless, velocity `cm/s`. A unit table converts recognised alternatives; an unknown unit is **refused** — the sole override is an explicit `--assume-unit <unit>`, recorded in the sidecar as a user override with the assumed unit — never silently relabelled.
- **World transform is explicit.** Bounding box and affine come from source attributes when present, else from the command line; no implicit rescaling. Both are written to the sidecar.
- **Provenance sidecar JSON**, per field: source path + SHA-256, dataset path, field name, units, dtype, shape, `bbox_min`, `index_to_object`, `object_to_world`, resampling method and target dims, per-field before/after statistics, the field-role → renderer mapping, and the tool version.
- **Resampling loss is field-specific and measured.** Cell volume is `dV = |det(A)|`, with `A` the upper-left 3×3 of the index→object affine (constant under a uniform affine). Conservative operators and diagnostics per field:
  - `density`: volume-weighted mass `M = Σ ρ_i dV`; relative mass error `|M_out − M_in| / M_in`.
  - `temperature`, `velocity`, `ion_fraction`: mass-weighted mean `⟨x⟩ = Σ x_i ρ_i dV / Σ ρ_i dV`, reported before/after with physical bounds (`T ≥ 0 K`, `0 ≤ f_ion ≤ 1`, `|v| ≤ c`).
  - Energy is **not** claimed by default: an energy number is emitted only when a declared EOS gives internal energy `ε(T, ρ)`, via `E = Σ ρ_i (ε_i + |v_i|²/2) dV`; otherwise the report reads "energy: no EOS, not computed".
  - Fixed target grids coarse/medium/fine = 32³/64³/128³ `(frozen 2026-09-22, lead may adjust)`. Acceptance: `density` mass relative error ≤ 0.5 %, other fields' mass-weighted-mean relative error ≤ 1 %, and the error must be **strictly decreasing** coarse → medium → fine against the analytic/synthetic reference (non-monotonic ⇒ fail).
- **`.vdb` output uses Blender's `openvdb`** (must run inside Blender's Python). Write `FloatGrid`s carrying the explicit index→object transform (voxel size taken from `index_to_object`, not the default unit transform) with active-index origin `bbox_min`; the read path expects this (`blender_addon/volume_export.py`). **Round-trip validation is required**: re-read through the pkg267 path and assert (a) array orientation matches the written array (same `(nz, ny, nx)`, voxel-identical within float32 round-off, max abs diff ≤ 1e-6), (b) active-index origin equals `bbox_min` exactly, and (c) the eight affine-transformed bbox corners agree within 1e-5 relative to the bbox diagonal `(frozen 2026-09-22, lead may adjust)`.

#### Phase 1 — arrays for `set_volume_grid`

- `.npy`/`.npz` + HDF5 adapters, cgs unit-table conversion (`--assume-unit` override), explicit transform, field-role → renderer mapping, sidecar, and the field-specific mass/mean report with the 32³/64³/128³ convergence check.

#### Phase 2 — `.vdb` writer

- Dense fields → OpenVDB FloatGrid under Blender's Python, with the explicit index→object transform and active-index origin; round-trip through the pkg267 read path validating array orientation (≤ 1e-6), active-index origin (exact) and affine bbox corners (≤ 1e-5 of the diagonal).

#### Phase 3 — yt adapter (optional)

- `yt.load(...).covering_grid(...)` → arrays; only worth doing if a frontend cannot export HDF5 directly.

## Acceptance criteria

- [ ] First measurable deliverable: a round-trip figure for a synthetic Gaussian density blob (identity grid) with total mass conserved within 0.5 % (`|M_out − M_in| / M_in ≤ 0.005`) and strictly decreasing error across the fixed 32³/64³/128³ grids; the text states that the ingest must not perturb the downstream Case-B Hα/Hβ ≈ 2.86 (2 %) deliverable (pkg46).
- [ ] Provenance sidecar schema test: every field record carries source SHA-256, units, dtype, shape, transforms, resampling metadata, per-field before/after statistics, the field-role → renderer mapping (role, unit, conversion, target API argument, `density_scale`), and `renderer_supported` (`false` when any field lacks a mapping).
- [ ] Unit conversion: a cgs-declared grid round-trips value-identical; a non-cgs declaration is converted by the documented factor; an unknown unit is refused unless `--assume-unit` is given, and then the sidecar records it as a user override.
- [ ] `.npy` and `h5py` adapters produce identical arrays from the same data (max abs diff < 1e-6).
- [ ] Resampling-loss report is emitted for a downsampled grid, matches an independent NumPy computation, uses `dV = |det(A)|`, and satisfies the per-field thresholds and strictly-decreasing-error criterion.
- [ ] `.vdb` round-trip test passes: array orientation (≤ 1e-6), active-index origin (exact) and affine bbox corners (≤ 1e-5 of the diagonal).
- [ ] `scripts/README.md` registers the script (same commit).
- [ ] New tests pass; no regressions; spec lints clean.

## Non-goals

- **No engine-side reader.** A C++ HDF5/AMR reader is a non-goal unless a demonstrated gap (irregular AMR, particle-only data) is documented; `set_volume_grid` and native OpenVDB already cover dense grids.
- Do not create `DensityGrid`, `SimulationVolume`, `npy_reader.h`, or a HighFive/HDF5 CMake flag.
- No AMR or particle reading; yt regrids, and SPH is pkg49.
- No time-series/animation. One snapshot per conversion.
- No absolute calibration; the downstream nebula target is relative line transport.
- Do not revive the deferred `FITSVolume` engine registration (pkg47 ruling 2026-05-15); FITS stays a sibling input path.

## Progress

- [ ] Define the field record, field-role → renderer mapping and sidecar schema.
- [ ] Implement `.npy`/`.npz` and h5py adapters (cgs unit table, transforms).
- [ ] Implement the field-specific mass/mean resampling report with the 32³/64³/128³ convergence check.
- [ ] Add the `.vdb` writer under Blender's `openvdb` with the explicit transform and round-trip validation.
- [ ] Add the optional yt adapter.
- [ ] Write tests (synthetic Gaussian blob; provenance schema).
- [ ] Register in `scripts/README.md`; update STATUS.md, CHANGELOG.md.
- [ ] Full test suite green.

## Lessons

*(Fill in after the package is done.)*

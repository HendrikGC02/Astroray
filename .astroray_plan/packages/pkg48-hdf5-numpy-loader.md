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
- **Input adapters, one output contract.** `h5py` for HDF5 datasets (user names the group/dataset paths), yt for frontend-specific snapshots (in-memory covering grid), and `.npy`/`.npz`. Every adapter emits the same field record; no per-format runtime in the engine.
- **cgs units, declared not inferred.** Density `g/cm^3`, temperature `K`, ionisation fraction dimensionless, velocity `cm/s`. A unit table converts recognised alternatives; an unknown unit is refused (or the assumed unit recorded) — never silently relabelled.
- **World transform is explicit.** Bounding box and affine come from source attributes when present, else from the command line; no implicit rescaling. Both are written to the sidecar.
- **Provenance sidecar JSON**, per field: source path + SHA-256, dataset path, field name, units, dtype, shape, `bbox_min`, `index_to_object`, `object_to_world`, resampling method and target dims, mass/energy before and after, and the tool version.
- **Resampling loss is reported.** Compare total mass (`Σρ·dV`) and an energy proxy before/after; require conservation for identity/injection paths and report the loss for regrids, with a resolution-convergence check (error vs target dims).
- **`.vdb` output uses Blender's `openvdb`** (must run inside Blender's Python), writing FloatGrids with the same transform semantics the read path expects (`blender_addon/volume_export.py`).

#### Phase 1 — arrays for `set_volume_grid`

- `.npy`/`.npz` + HDF5 adapters, cgs conversion, transform, sidecar, mass-conservation report.

#### Phase 2 — `.vdb` writer

- Dense fields → OpenVDB FloatGrid under Blender's Python; round-trip through the pkg267 read path.

#### Phase 3 — yt adapter (optional)

- `yt.load(...).covering_grid(...)` → arrays; only worth doing if a frontend cannot export HDF5 directly.

## Acceptance criteria

- [ ] First measurable deliverable: a round-trip figure for a synthetic Gaussian density blob (identity grid) with total mass conserved within 0.5 % (`|M_out − M_in| / M_in ≤ 0.005`), stable across at least two resolutions; the text states that the ingest must not perturb the downstream Case-B Hα/Hβ ≈ 2.86 (2 %) deliverable (pkg46).
- [ ] Provenance sidecar schema test: every field record carries source SHA-256, units, dtype, shape, transforms, resampling metadata and before/after mass.
- [ ] Unit conversion: a cgs-declared grid round-trips value-identical; a non-cgs declaration is converted by the documented factor (or refused).
- [ ] `.npy` and `h5py` adapters produce identical arrays from the same data (max abs diff < 1e-6).
- [ ] Resampling-loss report is emitted for a downsampled grid and matches an independent NumPy computation.
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

- [ ] Define the field record + sidecar schema.
- [ ] Implement `.npy`/`.npz` and h5py adapters (cgs conversion, transforms).
- [ ] Implement the mass/energy resampling-loss report.
- [ ] Add the `.vdb` writer under Blender's `openvdb`.
- [ ] Add the optional yt adapter.
- [ ] Write tests (synthetic Gaussian blob; provenance schema).
- [ ] Register in `scripts/README.md`; update STATUS.md, CHANGELOG.md.
- [ ] Full test suite green.

## Lessons

*(Fill in after the package is done.)*

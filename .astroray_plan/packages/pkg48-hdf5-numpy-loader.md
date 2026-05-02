# pkg48 — HDF5 & NumPy Simulation Data Loader

**Pillar:** 4
**Track:** B (self-contained I/O plugin)
**Status:** open
**Estimated effort:** 1–2 sessions (~4 h)
**Depends on:** pkg04 (plugin system), pkg47 (establishes data loader pattern)

---

## Goal

**Before:** Astroray cannot load simulation data from hydrodynamic or
MHD codes (AREPO, FLASH, Enzo, Athena++, PLUTO). Users who have run
simulations cannot visualise them in the renderer.

**After:** A `SimulationVolume` plugin loads 3D grid data from NumPy
`.npy` files (the recommended yt preprocessing output) and optionally
from HDF5 files directly via HighFive. Multiple fields (density,
temperature, velocity, magnetic field) can be loaded simultaneously
and mapped to volume density, emission, and colour.

---

## Context

The standard astrophysical simulation data pipeline is:

1. User runs a simulation (AREPO, FLASH, etc.) → HDF5/custom output.
2. User preprocesses with yt in Python → uniform 3D grid → `.npy`.
3. Astroray loads the `.npy` grid and renders it as a volume.

This two-step approach avoids Astroray needing to understand every
simulation code's bespoke HDF5 schema. yt handles the regridding and
format normalisation; Astroray just reads uniform grids.

For users who prefer to skip yt, direct HDF5 loading via HighFive
(header-only, BSD-3) is also supported for simple uniform-grid
datasets.

---

## Reference

- Design doc: `.astroray_plan/docs/astrophysics.md §4.5`
- yt: https://yt-project.org/ (BSD-3; Python preprocessing only)
- HighFive: https://github.com/BlueBrain/HighFive (BSD-3, header-only)
- NumPy .npy format: https://numpy.org/devdocs/reference/generated/numpy.lib.format.html
- External references: `.astroray_plan/docs/external-references.md §4`

---

## Prerequisites

- [ ] Plugin architecture (Pillar 1) complete.
- [ ] Build passes on main.
- [ ] All existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/data/simulation_volume.cpp` | `SimulationVolume` plugin. Reads `.npy` and HDF5 grids. |
| `include/astroray/npy_reader.h` | Minimal `.npy` file parser (header + raw float data). ~80 lines. |
| `tests/test_simulation_volume.py` | Unit and integration tests. |
| `tests/data/test_density.npy` | Small (16×16×16) synthetic density grid for testing. |
| `tests/data/test_temperature.npy` | Small (16×16×16) synthetic temperature grid. |
| `scripts/preprocess_simulation.py` | Example yt preprocessing script (documentation/reference, not a dependency). |

### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | Add HighFive as optional header-only dependency. HDF5 C library as optional `find_package`. |
| `module/blender_module.cpp` | Expose `load_simulation_volume(density_path, temperature_path=None, ...)`. |
| `blender_addon/__init__.py` | Add simulation data import panel with file browsers for each field. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg48 done. |
| `CHANGELOG.md` | Add pkg48 entry. |

### Data formats

#### NumPy .npy (primary)

The `.npy` format stores a single N-dimensional array with a short
header (magic, shape, dtype, fortran-order flag) followed by raw data.
Parsing it requires ~80 lines of C++ — no external dependency.

Expected input: 3D float32 or float64 array, shape (nx, ny, nz),
C-order. The reader validates the header and rejects non-float or
non-3D files with a clear error message.

#### HDF5 (optional, via HighFive)

For users who have uniform-grid HDF5 files and don't want to
preprocess with yt. The plugin reads a named dataset from a specified
group:

    load_simulation_volume(path="snapshot.hdf5",
                           dataset="/PartType0/Density",
                           shape=[256, 256, 256])

HighFive is header-only and BSD-3; it wraps the HDF5 C library. Like
CFITSIO for FITS, HDF5 is an optional dependency: if not found, the
HDF5 path is disabled but `.npy` loading still works.

### Volume representation

The `SimulationVolume` is a box-shaped volume in world space. User sets:

| Parameter | Default | Description |
|---|---|---|
| `density_file` | (required) | Path to density `.npy` or HDF5 file. |
| `temperature_file` | None | Optional temperature field. |
| `velocity_file` | None | Optional velocity field (3-component). |
| `bbox_min` | (-1,-1,-1) | World-space bounding box minimum. |
| `bbox_max` | (1,1,1) | World-space bounding box maximum. |
| `density_scale` | 1.0 | Multiplier on density values. |
| `emission_mode` | "absorption" | "absorption" (density → extinction), "emission" (density → luminosity), or "both". |
| `transfer_function` | "linear" | "linear", "log", or "sqrt" — maps raw values to visual density. |

The plugin implements trilinear interpolation on the grid for smooth
sampling between voxels.

### Integration with renderer

In **absorption mode**, the simulation volume acts like a
`ConstantMedium` with spatially-varying density. Rays are attenuated
according to the local extinction coefficient derived from the density
field.

In **emission mode**, the volume emits spectral radiance proportional
to the density (and optionally temperature-dependent via a blackbody
or user-specified colour map). This uses the `VolumetricEmission`
interface from pkg42.

In **both mode**, both absorption and emission are applied (standard
emission-absorption radiative transfer).

### Key design decisions

1. **NumPy .npy as primary format.** Zero external dependencies,
   trivial to generate from Python, and the yt preprocessing path
   naturally outputs `.npy`. This makes the most common workflow
   dependency-free on the C++ side.

2. **HighFive, not raw HDF5 C API.** HighFive is header-only and
   provides a type-safe C++ interface. No library to link against
   beyond the HDF5 C library itself. Keeps plugin code clean.

3. **User-specified bounding box, not physical units.** Simulation
   data comes in arbitrary code units. Rather than trying to parse
   unit metadata (which varies by simulation code), the user sets the
   world-space extent in Blender. The example yt script shows how to
   extract physical dimensions for reference.

4. **Transfer function is visual, not physical.** The log/sqrt options
   are for visual clarity (compressing dynamic range in density fields
   that span many orders of magnitude). They do not change the physics
   of radiative transfer — they map raw values to the visual density
   parameter that drives extinction/emission.

---

## Acceptance criteria

- [ ] `SimulationVolume` registered as both a shape plugin and an
      emission plugin.
- [ ] `.npy` loader reads float32 and float64 3D arrays correctly.
- [ ] A synthetic density grid renders as a volume with visible density
      variation (not uniform or black).
- [ ] Trilinear interpolation: sampling at grid centre matches the
      stored value exactly; sampling between grid points produces a
      smooth intermediate value.
- [ ] Optional HDF5: if HighFive + HDF5 are available, loads a dataset
      from an HDF5 file and produces identical results to the `.npy`
      equivalent.
- [ ] Missing HDF5: build completes; `.npy` loading still works.
- [ ] Transfer functions: log and sqrt modes compress dynamic range
      visually compared to linear.
- [ ] Blender addon has simulation data import UI with file browsers.
- [ ] All existing tests pass.
- [ ] ≥6 new tests covering: `.npy` load, shape validation, trilinear
      interpolation, absorption render, emission render, bad-file error.

---

## Non-goals

- Do not implement AMR (adaptive mesh refinement) grid reading. Only
  uniform grids. AMR data should be regridded to uniform via yt.
- Do not implement particle data (SPH) loading. That is pkg49.
- Do not implement yt as a C++ dependency. yt runs in Python as a
  preprocessing step only.
- Do not implement time-series animation (loading multiple snapshots).
  Single snapshot per render.
- Do not implement isosurface extraction. Volume rendering only.

---

## Progress

- [ ] Implement `.npy` reader in `npy_reader.h`.
- [ ] Implement `SimulationVolume` plugin: grid storage, trilinear
      interpolation, absorption/emission modes.
- [ ] Add optional HighFive/HDF5 path.
- [ ] Generate synthetic test grids.
- [ ] Write example yt preprocessing script.
- [ ] Add Blender UI.
- [ ] Write tests.
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md.

---

## Lessons

*(Fill in after the package is done.)*

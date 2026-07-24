# pkg48 — HDF5 & NumPy Simulation Data Loader

**Pillar:** 4  
**Track:** B (self-contained I/O plugin)  
**Status:** paused (owner directive 2026-06-08 — resume when core rendering stable)  
**Estimated effort:** 1–2 sessions (~4 h)  
**Depends on:** pkg04 (plugin system), pkg47 (establishes data loader pattern)

**Reference research:** `.astroray_plan/docs/pillar4-data-io-research.md §§1, 3, 4`  
(DensityGrid type, HDF5/HighFive CMake recipe, in-house npy parser spec,
chunked-read pattern, vcpkg setup, license notes — read before writing any
simulation volume code)

---

## Reference Implementations

| Source | License | What we use | What we do NOT mirror |
|---|---|---|---|
| [HDF5 C library](https://www.hdfgroup.org/solutions/hdf5/) (HDF Group) | BSD-style (HDF5 Software License 1.0) | System dep; accessed via HighFive wrapper | Not mirrored |
| [HighFive](https://github.com/highfive-devs/highfive) (highfive-devs) | **MIT** | Header-only C++ wrapper; vcpkg or submodule | Headers may be bundled with copyright notice |
| [yt](https://yt-project.org/) | BSD-3-Clause | Chunked-read pattern cited in code comment; Python preprocessing example | No C++ code from yt |
| [h5py](https://docs.h5py.org/) | BSD-3-Clause | Python test data generation only | None |
| NumPy .npy format spec | BSD-3-Clause | In-house C++ parser (~80 lines) derived from spec | Parser written from spec, not from NumPy source |

**Do not vendor HDF5.** Use as system dependency (vcpkg on Windows).
**HighFive** may be referenced via vcpkg or bundled as a git submodule (MIT, no
copyleft). The npy parser is written from scratch against the published spec.

---

## Goal

**Before:** Astroray cannot load simulation data from hydrodynamic or MHD codes
(AREPO, FLASH, Enzo, Athena++, PLUTO). Users who have run simulations cannot
visualise them.

**After:** A `SimulationVolume` plugin loads 3D grid data from NumPy `.npy` files
(the recommended yt preprocessing output) and optionally from HDF5 files directly
via HighFive. Multiple fields (density, temperature, velocity) can be loaded
simultaneously and mapped to volume density, emission, and colour.

---

## Context

Standard astrophysical simulation data pipeline:

1. User runs simulation → HDF5/custom output.
2. User preprocesses with yt in Python → uniform 3D grid → `.npy`.
3. Astroray loads `.npy` and renders as volume.

This two-step approach avoids Astroray needing to understand every simulation
code's bespoke HDF5 schema. yt handles regridding and format normalisation;
Astroray reads uniform grids.

For users who skip yt, direct HDF5 loading via HighFive is supported for
simple uniform-grid datasets.

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
| `plugins/data/simulation_volume.cpp` | `SimulationVolume` plugin. Reads `.npy` via `npy_reader.h` and HDF5 via HighFive. |
| `include/astroray/npy_reader.h` | In-house `.npy` parser (~80 lines). Validates header, reads float32/float64 3D arrays. |
| `include/astroray/density_grid.h` | `DensityGrid` struct (shared by pkg47, pkg48, pkg49). See §1 of research note. |
| `tests/test_simulation_volume.py` | Unit and integration tests. Synthetic data generated at test time. |
| `scripts/preprocess_simulation.py` | Example yt preprocessing script (documentation/reference, not a C++ dependency). |

### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | Add HDF5/HighFive as optional dependency via `ASTRORAY_ENABLE_HDF5` flag (see CMake recipe below). |
| `module/blender_module.cpp` | Expose `load_simulation_volume(density_path, temperature_path=None, ...)`. |
| `blender_addon/__init__.py` | Add simulation data import panel with file browsers for each field. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg48 done. |
| `CHANGELOG.md` | Add pkg48 entry. |

### CMake recipe

```cmake
option(ASTRORAY_ENABLE_HDF5 "Enable HDF5 I/O (requires HDF5 + HighFive)" OFF)

if(ASTRORAY_ENABLE_HDF5)
  find_package(HighFive CONFIG QUIET)   # automatically discovers HDF5 C library
  if(NOT HighFive_FOUND)
    find_package(HDF5 QUIET COMPONENTS C)
  endif()

  if(HighFive_FOUND OR HDF5_FOUND)
    target_sources(astroray PRIVATE plugins/data/simulation_volume.cpp)
    if(HighFive_FOUND)
      target_link_libraries(astroray PRIVATE HighFive::HighFive)
      target_compile_definitions(astroray PRIVATE ASTRORAY_HIGHFIVE_ENABLED)
    else()
      target_include_directories(astroray PRIVATE ${HDF5_INCLUDE_DIRS})
      target_link_libraries(astroray PRIVATE ${HDF5_C_LIBRARIES})
      target_compile_definitions(astroray PRIVATE ASTRORAY_HDF5_RAW_ENABLED)
    endif()
    message(STATUS "HDF5 I/O enabled")
  else()
    message(WARNING
      "ASTRORAY_ENABLE_HDF5=ON but HDF5/HighFive not found. "
      "Install via: vcpkg install hdf5 highfive  (Windows) or  apt install libhdf5-dev  (Linux). "
      ".npy loading still works without HDF5.")
  endif()
endif()

# .npy loading is always compiled (no external dependency)
target_sources(astroray PRIVATE plugins/data/simulation_volume.cpp)
target_compile_definitions(astroray PRIVATE ASTRORAY_NPY_ENABLED)
```

**Codex-ready when:** `find_package(HighFive CONFIG QUIET)` resolves on the
Windows MinGW toolchain. Verify with:
`cmake -DCMAKE_TOOLCHAIN_FILE=%VCPKG_ROOT%/scripts/buildsystems/vcpkg.cmake
-DASTRORAY_ENABLE_HDF5=ON .`

### Windows / vcpkg setup

```
vcpkg install hdf5 highfive
```

On Windows with static builds, add to CMake invocation:
```
-DHDF5_USE_STATIC_LIBRARIES=ON
```

### `npy_reader.h` parser spec

Derived from the official .npy format spec:
https://numpy.org/doc/stable/reference/generated/numpy.lib.format.html

```
Byte layout:
  [0:6]    magic: \x93NUMPY
  [6]      major version (uint8): 1 or 2
  [7]      minor version (uint8): 0
  [8:10]   header length (uint16, little-endian)  -- if major == 1
  [8:12]   header length (uint32, little-endian)  -- if major == 2
  [10/12 : 10/12+N]  header dict (ASCII/UTF-8), padded with spaces to
                     align total bytes to 64-byte boundary, terminated \n
  [after header]     raw float data, C-order
```

Parser requirements:
- Accept `'<f4'` (float32) and `'<f8'` (float64); reject others.
- Accept `fortran_order: False` only; reject Fortran-order.
- Accept 3D shape only (rank-3 array); reject other ranks.
- Extract shape by scanning for `'shape': (` and reading three integers.
- Return `DensityGrid` with `data` vector (always float32 after conversion).

### Data formats

#### NumPy .npy (primary, no external dependency)

Expected input: 3D float32 or float64 array, shape `(nx, ny, nz)`, C-order.
The reader validates the header and rejects non-float or non-3D files.

#### HDF5 via HighFive (optional)

```cpp
// Reads dataset "density" from an HDF5 file into DensityGrid
HighFive::File file(path, HighFive::File::ReadOnly);
auto ds = file.getDataSet("density");
auto dims = ds.getDimensions();  // {nx, ny, nz}
std::vector<float> buf(dims[0] * dims[1] * dims[2]);
ds.read(buf);
```

User specifies the dataset path:
```python
load_simulation_volume(path="snapshot.hdf5",
                       dataset="/PartType0/Density",
                       shape=[256, 256, 256])
```

For large datasets: read in z-slabs of 64 layers (see research note §3 for
chunked-read pseudocode). Cite: yt chunked-read pattern,
`yt/frontends/enzo/data_structures.py` (BSD-3).

### Volume representation

`SimulationVolume` is a box-shaped volume in world space. Parameters:

| Parameter | Default | Description |
|---|---|---|
| `density_file` | (required) | Path to density `.npy` or HDF5 file. |
| `temperature_file` | None | Optional temperature field. |
| `velocity_file` | None | Optional velocity field (3-component). |
| `bbox_min` | (-1,-1,-1) | World-space bounding box minimum. |
| `bbox_max` | (1,1,1) | World-space bounding box maximum. |
| `density_scale` | 1.0 | Multiplier on density values. |
| `emission_mode` | "absorption" | "absorption", "emission", or "both". |
| `transfer_function` | "linear" | "linear", "log", or "sqrt". |

The plugin implements trilinear interpolation on the grid for smooth sampling.

---

## Acceptance criteria

- [ ] `.npy` loader compiled unconditionally (no feature flag).
- [ ] `SimulationVolume` registered as both shape plugin and emission plugin.
- [ ] `.npy` float32 load: 16×16×16 synthetic grid read back with shape `(16,16,16)` and values matching within 1e-6.
- [ ] `.npy` float64 load: same grid as float64, values converted to float32, same tolerance.
- [ ] `.npy` rejection: non-3D array → `std::runtime_error` with message containing "expected 3D".
- [ ] `.npy` rejection: wrong dtype (e.g. int32) → `std::runtime_error` with message containing dtype name.
- [ ] Trilinear interpolation: sampling at grid centre matches stored value exactly; sampling at a midpoint between two adjacent cells with values 0 and 1 returns 0.5 ± 1e-5.
- [ ] `transfer_function="log"`: log-scale output compresses dynamic range (max/min ratio in log space < max/min ratio in linear space for a grid spanning [0.01, 100]).
- [ ] HDF5 (if enabled): a 16×16×16 synthetic HDF5 dataset produces identical `DensityGrid` to the equivalent `.npy` file (element-wise comparison, max absolute diff < 1e-6).
- [ ] HDF5 absent: `ASTRORAY_ENABLE_HDF5=OFF` build compiles; `.npy` path still works.
- [ ] All existing tests pass.
- [ ] ≥ 6 new tests: `.npy` float32 load, `.npy` float64 load, rank validation, dtype validation, trilinear interpolation, log transfer function.

### Concrete test data shapes

| Test | Shape | dtype | Created by |
|---|---|---|---|
| density grid | (16, 16, 16) | float32 | `np.random.rand(16,16,16).astype(np.float32); np.save(tmp, data)` |
| temperature grid | (16, 16, 16) | float32 | same pattern |
| HDF5 density | (16, 16, 16) | float32 | `h5py.File(tmp)["density"] = data` |
| uniform grid (interp test) | (4, 4, 4) | float32 | `np.arange(64).reshape(4,4,4).astype(np.float32)` |

All written to `tmp_path` (pytest); no binaries committed.

---

## Non-goals

- No AMR (adaptive mesh refinement) reading. Only uniform grids. AMR data should be regridded via yt.
- No particle data (SPH). That is pkg49.
- No yt as a C++ dependency. yt runs in Python only.
- No time-series animation (multiple snapshots). Single snapshot per render.
- No isosurface extraction. Volume rendering only.

---

## Progress

- [ ] Define `DensityGrid` struct in `include/astroray/density_grid.h`.
- [ ] Implement `npy_reader.h` (parse header, validate dtype and rank, return `DensityGrid`).
- [ ] Implement `SimulationVolume`: grid storage, trilinear interpolation, absorption/emission modes.
- [ ] Add optional HighFive/HDF5 path (behind `#ifdef ASTRORAY_HIGHFIVE_ENABLED`).
- [ ] Write example yt preprocessing script.
- [ ] Add Blender UI.
- [ ] Write tests (synthetic data via numpy/h5py at test time).
- [ ] Verify `ASTRORAY_ENABLE_HDF5=ON` on Windows toolchain.
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md.

---

## Lessons

*(Fill in after the package is done.)*

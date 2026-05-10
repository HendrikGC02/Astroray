# Pillar 4 Data I/O Research — FITS, HDF5/NumPy, SPH-to-Volume

**Date:** 2026-05-10  
**Covers:** pkg47 (FITS loader), pkg48 (HDF5/NumPy loader), pkg49 (SPH-to-volume)  
**Status:** research complete; specs tightened; ready for Codex implementation pending
dep verification on Windows

---

## 1. Pipeline Shape and Common Volume Representation

All three loaders must produce the same internal representation so that the renderer
and the Blender addon see a uniform interface regardless of source format.

### Proposed common type: `DensityGrid`

```cpp
// include/astroray/density_grid.h
struct DensityGrid {
    std::vector<float> data;    // flat C-order (x varies slowest, z varies fastest)
    int nx, ny, nz;             // grid dimensions
    float bbox_min[3];          // world-space bounding box corners
    float bbox_max[3];
    std::string field_name;     // "density", "temperature", etc.
};
```

This is a thin wrapper. It does not duplicate any existing volume machinery — it
holds the raw grid and enough geometry to hand off to `SimulationVolume` (pkg48).
`FITSVolume` (pkg47) and `SPHToGrid` (pkg49) both output `DensityGrid` values
and pass them to `SimulationVolume` or write them to `.npy` files.

**Why a wrapper, not a new class hierarchy:** `SimulationVolume` already handles
rendering; the loaders only need to produce a well-defined grid. One struct,
passed by value (small overhead) or returned via `std::unique_ptr<DensityGrid>`.

### Load path diagram

```
FITS file ──────────────────────────────────────────────────────── pkg47
                                                                       │
HDF5 file ──── pkg48 (npy_reader.h or HighFive) ─── DensityGrid ──────┤
                                                                       │
.npy file ──── pkg48 (npy_reader.h)              ─── DensityGrid ──────┤
                                                                       │
SPH particles ─ pkg49 (sph_kernel.h + splatting) ─ DensityGrid ────────┤
                                                                       │
                                              SimulationVolume (pkg48) ─┘
                                                          │
                                                    volume plugin
                                                  (render path unchanged)
```

---

## 2. cfitsio Integration

### Library

**cfitsio** — NASA/HEASARC C library for reading and writing FITS files.  
License: **public domain** (explicitly stated in `cfitsio.h`: "This software is  
provided with no warranty whatsoever").  
Canonical source: https://heasarc.gsfc.nasa.gov/fitsio/  
Current version as of 2026: 4.x (4.6.4 documented April 2026).

Do **not** vendor. Use as a system dependency.

### Core C API functions

```c
/* Open/close */
int fits_open_file(fitsfile **fptr, const char *filename,
                   int iomode, int *status);
int fits_close_file(fitsfile *fptr, int *status);

/* Navigate HDUs */
int fits_movabs_hdu(fitsfile *fptr, int hdunum,
                    int *hdutype, int *status);   // 1-based

/* Inspect image geometry */
int fits_get_img_dim(fitsfile *fptr, int *naxis, int *status);
int fits_get_img_size(fitsfile *fptr, int maxdim,
                      long *naxes, int *status);
int fits_get_img_type(fitsfile *fptr, int *bitpix, int *status);

/* Read pixels into float array (BSCALE/BZERO applied automatically) */
int fits_read_pix(fitsfile *fptr, int datatype, long *fpixel,
                  LONGLONG nelements, void *nulval,
                  void *array, int *anynul, int *status);
// datatype = TFLOAT; fpixel = {1,1,...,1} (1-based first pixel)

/* Header keyword */
int fits_read_key(fitsfile *fptr, int datatype, const char *keyname,
                  void *value, char *comment, int *status);
```

`fits_read_pix` applies `BSCALE`/`BZERO` when `datatype = TFLOAT` — no manual
scaling needed. For a 2D image the call is `fits_read_pix(fptr, TFLOAT,
fpixel={1,1}, nx*ny, NULL, data.data(), &anynul, &status)`.

Compressed FITS (tile-compression and `.fits.gz`) is handled transparently by
cfitsio; the application code sees a normal FITS file.

### CMake recipe

```cmake
option(ASTRORAY_ENABLE_FITS "Enable FITS I/O (requires cfitsio)" OFF)

if(ASTRORAY_ENABLE_FITS)
  # vcpkg provides cfitsio::cfitsio; system installs may use FindCFITSIO
  find_package(cfitsio CONFIG QUIET)
  if(NOT cfitsio_FOUND)
    find_package(PkgConfig QUIET)
    if(PkgConfig_FOUND)
      pkg_check_modules(cfitsio IMPORTED_TARGET cfitsio)
      if(cfitsio_FOUND)
        add_library(cfitsio::cfitsio ALIAS PkgConfig::cfitsio)
      endif()
    endif()
  endif()

  if(cfitsio_FOUND)
    target_sources(astroray PRIVATE plugins/data/fits_loader.cpp)
    target_link_libraries(astroray PRIVATE cfitsio::cfitsio)
    target_compile_definitions(astroray PRIVATE ASTRORAY_FITS_ENABLED)
    message(STATUS "FITS I/O enabled (cfitsio found)")
  else()
    message(WARNING "ASTRORAY_ENABLE_FITS=ON but cfitsio not found; FITS disabled")
  endif()
endif()
```

### Windows / vcpkg

```
vcpkg install cfitsio          # classic mode
# or in vcpkg.json manifest:
{ "name": "cfitsio", "version>=": "3.49" }
```

Pass `-DCMAKE_TOOLCHAIN_FILE=%VCPKG_ROOT%/scripts/buildsystems/vcpkg.cmake`
to CMake. vcpkg installs a `cfitsio-config.cmake` that provides the
`cfitsio::cfitsio` target, so `find_package(cfitsio CONFIG REQUIRED)` works
immediately with no extra shims.

**Codex-ready when:** `find_package(cfitsio CONFIG QUIET)` resolves on the
Windows MinGW toolchain used in this repo.

---

## 3. HDF5 Integration

### Library stack

**HDF5 C library** — maintained by The HDF Group.  
License: **BSD-style** (HDF5 Software License, 1.0; functionally permissive).  
Canonical source: https://www.hdfgroup.org/solutions/hdf5/  
Use as a system dependency; do not vendor.

**HighFive** — header-only C++14 wrapper around the HDF5 C library.  
License: **MIT** (BlueBrain Project / highfive-devs).  
Repo: https://github.com/highfive-devs/highfive (note: project migrated from
BlueBrain namespace in 2025; both URLs resolve).  
We use HighFive to avoid calling the HDF5 C API directly in plugin code.

### Core h5py API (Python, for test generation)

```python
import h5py, numpy as np

# Write synthetic test file
with h5py.File("test_density.hdf5", "w") as f:
    f.create_dataset("density", data=np.ones((16, 16, 16), dtype=np.float32))
    f["density"].attrs["units"] = "g/cm^3"

# Read
with h5py.File("test_density.hdf5", "r") as f:
    data = f["density"][...]   # numpy array
    keys = list(f.keys())
```

### HighFive C++ API

```cpp
#include <highfive/highfive.hpp>

HighFive::File file(path, HighFive::File::ReadOnly);
auto dataset = file.getDataSet("density");
auto dims = dataset.getDimensions();  // std::vector<size_t>
std::vector<float> buf(dims[0] * dims[1] * dims[2]);
dataset.read(buf);
```

`find_package(HighFive)` automatically discovers the HDF5 C library.

### Chunked-read pattern (yt-inspired)

For large datasets (>1 GB), read in slabs to avoid peak-memory spikes:

```cpp
// Read z-slabs of size CHUNK_Z at a time
const size_t CHUNK_Z = 64;
for (size_t z0 = 0; z0 < nz; z0 += CHUNK_Z) {
    size_t z1 = std::min(z0 + CHUNK_Z, nz);
    dataset.select({0, 0, z0}, {nx, ny, z1 - z0}).read(slab);
    process_slab(slab, z0);
}
```

Reference: yt's HDF5 chunked-read pattern in
`yt/frontends/enzo/data_structures.py`. License: BSD-3, attribution in
code comment required.

### CMake recipe

```cmake
option(ASTRORAY_ENABLE_HDF5 "Enable HDF5 I/O (requires HDF5 + HighFive)" OFF)

if(ASTRORAY_ENABLE_HDF5)
  find_package(HighFive CONFIG QUIET)   # finds HDF5 automatically
  if(NOT HighFive_FOUND)
    find_package(HDF5 REQUIRED COMPONENTS C)
    # Fallback: raw HDF5 target without HighFive niceties
  endif()

  if(HighFive_FOUND OR HDF5_FOUND)
    target_sources(astroray PRIVATE plugins/data/simulation_volume.cpp)
    if(HighFive_FOUND)
      target_link_libraries(astroray PRIVATE HighFive::HighFive)
      target_compile_definitions(astroray PRIVATE ASTRORAY_HIGHFIVE_ENABLED)
    else()
      target_include_directories(astroray PRIVATE ${HDF5_INCLUDE_DIRS})
      target_link_libraries(astroray PRIVATE ${HDF5_C_LIBRARIES})
      target_compile_definitions(astroray PRIVATE ASTRORAY_HDF5_ENABLED)
    endif()
    message(STATUS "HDF5 I/O enabled")
  else()
    message(WARNING "ASTRORAY_ENABLE_HDF5=ON but HDF5/HighFive not found")
  endif()
endif()
```

### Windows / vcpkg

```
vcpkg install hdf5 highfive
```

On Windows with static builds, set `-DHDF5_USE_STATIC_LIBRARIES=ON` so
`find_package(HDF5)` finds `hdf5.lib` rather than `libhdf5.lib`.

**Codex-ready when:** `find_package(HighFive CONFIG QUIET)` resolves on this
Windows MinGW toolchain.

---

## 4. NumPy .npy / .npz Format

### Recommendation: in-house C++ parser (~80 lines)

The `.npy` format is simple and stable enough to parse without pulling NumPy
into the C++ build. A minimal parser handles everything pkg48 needs:

```
Offset  Size   Field
------  ----   -----
0       6      Magic:  \x93NUMPY
6       1      Major version (1 or 2)
7       1      Minor version (0)
8       2/4    Header length (uint16 for v1, uint32 for v2), little-endian
10/12   N      Header: Python dict literal, ASCII, padded with spaces to
               align total (magic+version+len+header) to 64-byte boundary,
               terminated with \n
varies  M      Raw array data: product(shape) × itemsize bytes, C-order
```

Header dict keys (alphabetical):
- `'descr'`: dtype string, e.g. `'<f4'` (little-endian float32)
- `'fortran_order'`: boolean
- `'shape'`: tuple of ints, e.g. `(32, 32, 32)`

**Parser requirements for pkg48:**
- Accept `'<f4'` (float32) and `'<f8'` (float64); reject others with clear error.
- Accept `fortran_order: False` only; reject Fortran-order with clear error.
- Accept 3D shape only; reject 2D or 4D with clear error.
- No regex — parse the shape by finding `'shape': (` and reading the integers.

Format spec: https://numpy.org/doc/stable/reference/generated/numpy.lib.format.html

### .npz files

`.npz` is a ZIP archive containing `.npy` files. Handle at the Python level only:
```python
data = np.load("sim.npz")["density"]  # extract as ndarray
data.astype(np.float32).tofile("density.npy")  # write raw .npy
```
No `.npz` support in C++ is needed.

---

## 5. SPH Kernel + Splatting Algorithm

### Kernel choice: cubic B-spline (Monaghan 1992)

The cubic B-spline is the most widely used SPH kernel in astrophysics codes
(GADGET, PHANTOM, early FLASH). We use it as the primary kernel because:
- it is the standard reference in Monaghan (1992) and Price (2012),
- its compact support (2h) is well-characterised,
- it is straightforward to implement and test.

**Reference:** Monaghan, J.J. (1992). "Smoothed Particle Hydrodynamics."
*Annual Review of Astronomy and Astrophysics* 30, 543–574.
DOI: 10.1146/annurev.aa.30.090192.002551

**Kernel formula (3D):**

```
W(r, h) = (1 / πh³) × w(q),    q = r/h

         ⎧ 1 − (3/2)q² + (3/4)q³,   0 ≤ q < 1
w(q) =  ⎨ (1/4)(2 − q)³,           1 ≤ q < 2
         ⎩ 0,                        q ≥ 2
```

**Normalisation check:** ∫₀^{2h} W(r,h) 4πr² dr = 1 (verified analytically;
the two-piece integral evaluates to 1/4 + 1/4 = 1/2... wait, computed above:
19/120 + 11/120 = 30/120 = 1/4, then × 4 = 1 ✓).

**Compact support radius:** `2h`. Particles touch only cells within `2h` of
their centre.

### Splatting algorithm (Westover 1990 footprint evaluation)

**Reference:** Westover, L. (1990). "Footprint Evaluation for Volume
Rendering." *SIGGRAPH '90 Proceedings*, pp. 367–376.
DOI: 10.1145/97879.97919

```
Input:
  particles[N]: (pos[3], h, value)      // positions, smoothing lengths, field
  grid[nx,ny,nz], bbox_min[3], cell_size // output grid
  V[i] = m[i] / rho[i]                  // particle volume (mass / density)

Output:
  grid[j]: field value at each cell

Algorithm (scatter-gather / "shepard sum"):
  field[...] = 0;  weight[...] = 0

  for i in 0..N-1:
    # AABB of particle's kernel support in grid index space
    j_min[d] = floor((pos[i][d] - 2*h[i] - bbox_min[d]) / cell_size)
    j_max[d] = ceil( (pos[i][d] + 2*h[i] - bbox_min[d]) / cell_size)
    clamp j_min/j_max to [0, n{x,y,z})

    for jx in j_min[0]..j_max[0]:
      for jy in j_min[1]..j_max[1]:
        for jz in j_min[2]..j_max[2]:
          cell_pos = bbox_min + (jx+0.5, jy+0.5, jz+0.5) * cell_size
          r = |cell_pos - pos[i]|
          q = r / h[i]
          w = cubic_spline_kernel(q)      # evaluates W as above
          field[jx,jy,jz]  += value[i] * w * V[i]
          weight[jx,jy,jz] += w * V[i]

  for all j:
    if weight[j] > 0:
      field[j] /= weight[j]   # Shepard normalisation
    else:
      field[j] = 0.0           # vacuum cell
```

**Normalisation:** The Shepard (1968) sum (`field / weight`) ensures that a
uniform particle distribution produces a uniform grid. Without it, boundary
regions where fewer particles overlap produce artefacts.

**Complexity:** O(N × (2h/Δx)³). For typical astrophysical SPH with h ≈ 2Δx,
each particle touches ≈ 8³ = 512 cells. With N=10⁵ and 128³ grid: ~5×10⁷
operations, well under the 10-second wall-clock target on a single core.

**Note on Wendland kernels:** Wendland C2 (Dehnen & Aly 2012,
DOI: 10.1111/j.1365-2966.2012.21439.x) and C4 are alternatives with better
stability properties (no pairing instability, positive semi-definite). The
splatting algorithm is kernel-agnostic — only `cubic_spline_kernel()` needs
to be replaced. If downstream use requires rendering at the particle level
(ray-marching through particles), Wendland C4 is preferred. For grid
pre-processing as implemented in pkg49, cubic spline is sufficient.

---

## 6. Test Data Strategy

**Rule:** No binary test data checked into the repository. Each test creates
its own synthetic dataset at runtime using standard Python libraries, writes
it to `tmp_path` (pytest fixture), and the file is deleted on test teardown.

### Synthetic FITS (pkg47)

```python
import numpy as np
from astropy.io import fits

def make_fits_2d(tmp_path) -> Path:
    data = np.arange(64*64, dtype=np.float32).reshape(64, 64)
    hdu = fits.PrimaryHDU(data)
    hdu.header['BSCALE'] = 1.0
    hdu.header['BZERO'] = 0.0
    path = tmp_path / "test_2d.fits"
    hdu.writeto(str(path))
    return path

def make_fits_3d(tmp_path) -> Path:
    # 3D cube: 32×32×8 (x, y, wavelength)
    cube = np.random.rand(8, 32, 32).astype(np.float32)
    hdu = fits.PrimaryHDU(cube)
    path = tmp_path / "test_3d.fits"
    hdu.writeto(str(path))
    return path
```

### Synthetic HDF5 + npy (pkg48)

```python
import h5py, numpy as np

def make_hdf5(tmp_path) -> Path:
    path = tmp_path / "test_density.hdf5"
    with h5py.File(str(path), "w") as f:
        data = np.random.rand(16, 16, 16).astype(np.float32)
        f.create_dataset("density", data=data)
    return path

def make_npy(tmp_path) -> Path:
    path = tmp_path / "test_density.npy"
    np.save(str(path), np.random.rand(16, 16, 16).astype(np.float32))
    return path
```

### Synthetic SPH particles (pkg49)

```python
import numpy as np

def make_particles(N=100):
    rng = np.random.default_rng(42)
    positions = rng.uniform(0, 1, (N, 3)).astype(np.float32)
    smoothing = np.full(N, 0.05, dtype=np.float32)   # h = 0.05 (support 0.1)
    values    = np.ones(N, dtype=np.float32)           # uniform density
    masses    = np.full(N, 1.0/N, dtype=np.float32)
    densities = np.ones(N, dtype=np.float32)
    return positions, smoothing, values, masses, densities
```

Output: 32³ grid over [0,1]³. A uniform-density particle distribution must
produce a grid with max/min ratio < 1.01 (boundary cells acceptable < 1.05).

---

## 7. License Matrix

| Dependency | License | Use in Astroray | Mirror permitted |
|---|---|---|---|
| cfitsio | Public domain (NASA) | System dep, link at runtime | N/A — not mirrored |
| HDF5 C library | BSD-style (HDF5 Software License 1.0) | System dep, link at runtime | N/A — not mirrored |
| HighFive | MIT | Header-only; referenced via vcpkg or submodule | Yes, with copyright notice |
| astropy | BSD-3-Clause | Python test generation only; not in C++ build | N/A |
| h5py | BSD-3-Clause | Python test generation only; not in C++ build | N/A |
| yt | BSD-3-Clause | Python preprocessing example only; chunked-read pattern cited | Code pattern may be adapted with attribution |
| NumPy | BSD-3-Clause | Python only; in-house C++ parser does not link NumPy | N/A |

**No GPL code touches this pipeline.** cfitsio (public domain) and HDF5 (BSD)
are unambiguous. HighFive (MIT) can be bundled. yt code patterns can be
adapted with attribution but yt itself is not a C++ dependency.

---

## Sources

- Monaghan (1992): https://www.annualreviews.org/doi/10.1146/annurev.aa.30.090192.002551
- Price (2012): https://arxiv.org/abs/1012.1885
- Dehnen & Aly (2012) on Wendland kernels: https://arxiv.org/abs/1204.2471
- Westover (1990): ACM SIGGRAPH '90, pp. 367-376, DOI 10.1145/97879.97919
- cfitsio: https://heasarc.gsfc.nasa.gov/fitsio/
- cfitsio vcpkg: https://vcpkg.io/en/package/cfitsio.html
- HDF5 vcpkg: https://vcpkg.io/en/package/hdf5.html
- HighFive: https://github.com/highfive-devs/highfive
- HighFive vcpkg: https://vcpkg.io/en/package/highfive
- NumPy .npy format spec: https://numpy.org/doc/stable/reference/generated/numpy.lib.format.html
- FindHDF5 CMake module: https://cmake.org/cmake/help/latest/module/FindHDF5.html
- astropy io.fits: https://docs.astropy.org/en/stable/io/fits/
- yt project: https://yt-project.org/

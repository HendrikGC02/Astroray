# pkg47 — FITS Data Loader

**Pillar:** 4  
**Track:** B (self-contained I/O plugin)  
**Status:** open  
**Estimated effort:** 1–2 sessions (~4 h)  
**Depends on:** pkg04 (shape/texture plugin system)

**Reference research:** `.astroray_plan/docs/pillar4-data-io-research.md §2`  
(cfitsio API, CMake recipe, vcpkg setup, test data strategy, license notes —
read before writing any FITS code)

---

## Reference Implementations

| Source | License | What we use | What we do NOT mirror |
|---|---|---|---|
| [cfitsio](https://heasarc.gsfc.nasa.gov/fitsio/) (NASA/HEASARC) | **Public domain** | System dep; `fits_open_file`, `fits_read_pix`, `fits_get_img_dim/size/type` | Not mirrored — linked as system library |
| [astropy io.fits](https://docs.astropy.org/en/stable/io/fits/) (BSD-3) | BSD-3-Clause | Python test data generation only; API design reference for clean FITS reader | No C++ code from astropy |
| FITS Standard 4.0 (NASA/IAU) | Public domain | Spec for BITPIX, NAXIS, BSCALE/BZERO, HDU structure | N/A |

**Do not vendor cfitsio.** Use as a system dependency installed via vcpkg on
Windows or the system package manager on Linux. The plugin build is gated by
`ASTRORAY_ENABLE_FITS` (default `OFF`) and silently skips if cfitsio is absent.

---

## Goal

**Before:** Astroray cannot load observational or simulation data in FITS format.
Users with Hubble, JWST, or radio telescope data cannot visualise it in the
renderer.

**After:** A `FITSLoader` plugin reads FITS files and exposes them as either
volumetric data cubes (3D: x, y, wavelength/velocity) or plane-sky textures (2D
images). The data integrates with the existing texture and volume plugin systems
so it can be assigned to objects, used as emission sources, or displayed as
environment maps.

---

## Context

FITS (Flexible Image Transport System) is the universal data format in astronomy.
Every major observatory — Hubble, JWST, ALMA, VLA, Chandra — outputs FITS.
Supporting FITS import lets users overlay their own data with synthetic models
(e.g., render a Kerr black hole in front of a real JWST deep field, or
volume-render an ALMA data cube of a protoplanetary disk).

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
| `plugins/data/fits_loader.cpp` | `FITSTexture` (2D) and `FITSVolume` (3D) plugins. |
| `include/astroray/fits_io.h` | FITS reading wrapper around cfitsio. Isolates the C API from plugin code. |
| `tests/test_fits_loader.py` | Unit and integration tests. Synthetic data generated at test time (no checked-in binaries). |

### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | Add cfitsio as optional dependency via `ASTRORAY_ENABLE_FITS` flag (see CMake recipe below). |
| `include/astroray/register.h` | Confirm `DataLoaderRegistry` exists; add if needed. |
| `module/blender_module.cpp` | Expose `load_fits_texture(path)` and `load_fits_volume(path)` on the renderer. |
| `blender_addon/__init__.py` | Add FITS file browser to import panel. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg47 done. |
| `CHANGELOG.md` | Add pkg47 entry. |

### CMake recipe

```cmake
option(ASTRORAY_ENABLE_FITS "Enable FITS I/O (requires cfitsio)" OFF)

if(ASTRORAY_ENABLE_FITS)
  # vcpkg provides cfitsio::cfitsio; system installs may use pkg-config
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
    message(WARNING
      "ASTRORAY_ENABLE_FITS=ON but cfitsio not found. "
      "Install via: vcpkg install cfitsio  (Windows) or  apt install libcfitsio-dev  (Linux). "
      "FITS plugins will be skipped.")
  endif()
endif()
```

**Codex-ready when:** `find_package(cfitsio CONFIG QUIET)` resolves on the
Windows MinGW toolchain used in this repo. Verify with:
`cmake -DCMAKE_TOOLCHAIN_FILE=%VCPKG_ROOT%/scripts/buildsystems/vcpkg.cmake
-DASTRORAY_ENABLE_FITS=ON .`

### Windows / vcpkg setup

```
vcpkg install cfitsio
```

Or in `vcpkg.json`:
```json
{ "name": "cfitsio", "version>=": "3.49" }
```

### `fits_io.h` wrapper interface

```cpp
class FITSFile {
public:
    static FITSFile open(const std::string& path);  // throws on error
    ~FITSFile();                                     // RAII close

    int naxis() const;                               // 2 or 3
    std::vector<long> shape() const;                 // [ny, nx] or [nz, ny, nx]
    std::string header(const std::string& key) const;

    // Reads entire image as float (applies BSCALE/BZERO automatically)
    std::vector<float> readFloat() const;
};
```

CFITSIO C API calls inside the wrapper:
- `fits_open_file` → `fits_get_img_dim` → `fits_get_img_size` → `fits_read_pix`
  with `datatype=TFLOAT`
- `fits_read_key` for header access

### Supported FITS features

| Feature | Supported | Notes |
|---|---|---|
| 2D images (IMAGE HDU, NAXIS=2) | Yes | Loaded as texture. |
| 3D data cubes (NAXIS=3) | Yes | Loaded as volume. Third axis interpreted as wavelength or velocity per WCS. |
| Multiple HDUs | First IMAGE HDU by default; user can specify HDU index. | |
| Floating point (BITPIX −32, −64) | Yes | Native float/double. |
| Integer data (BITPIX 8, 16, 32) | Yes | Converted to float; BSCALE/BZERO applied by cfitsio. |
| WCS coordinates | Read and stored as metadata; used for physical scale if present. | Not required. |
| Compressed FITS (.fits.gz, tile compression) | Via cfitsio transparent decompression. | |
| FITS tables (BINTABLE) | No | Out of scope. |

### Key design decisions

1. **BSCALE/BZERO applied automatically.** cfitsio applies scaling when reading
   to `TFLOAT`; the wrapper does not suppress this.
2. **WCS is metadata, not geometry.** Headers stored but data not transformed.
   The user positions and scales the object in Blender.
3. **No astropy C++ dependency.** astropy is used only in test data generation.
4. **Optional, not required.** Plugin simply absent if cfitsio not found.

---

## Acceptance criteria

- [ ] `ASTRORAY_ENABLE_FITS=OFF` (default): build succeeds; no FITS symbols.
- [ ] `ASTRORAY_ENABLE_FITS=ON` with cfitsio present: build succeeds; plugins compiled.
- [ ] `ASTRORAY_ENABLE_FITS=ON` without cfitsio: CMake warning printed; build succeeds with FITS disabled.
- [ ] `FITSTexture` registered; loads a 64×64 synthetic float32 FITS image as a texture. Shape matches.
- [ ] `FITSVolume` registered; loads a 32×32×8 synthetic FITS cube as a volume. Shape matches.
- [ ] BSCALE/BZERO: an integer FITS file with `BZERO=1000.0, BSCALE=0.1` produces correct float values (test: pixel stored as `int16(500)` → expected `1000.0 + 0.1×500 = 1050.0`).
- [ ] First IMAGE HDU selected by default; user can override by index.
- [ ] Header keyword round-trip: write `OBJECT = 'NGC 1234'` in astropy; read back via `FITSFile::header("OBJECT")` in C++ → returns `"NGC 1234"`.
- [ ] Missing file: `FITSFile::open` throws with message containing the path.
- [ ] Blender addon has a FITS import button (both `FITSTexture` and `FITSVolume` assignable).
- [ ] All existing tests pass.
- [ ] ≥ 6 new tests: 2D load (shape, dtype, values), 3D load (shape, axis order), BSCALE/BZERO scaling, header read, missing-file error, build-without-cfitsio.

### Concrete test data shapes

| Test | Shape | dtype | Created by |
|---|---|---|---|
| 2D gradient image | (64, 64) | float32 | `astropy.io.fits.PrimaryHDU(np.arange(64*64).reshape(64,64).astype(np.float32))` |
| 3D cube | (8, 32, 32) | float32 | `astropy.io.fits.PrimaryHDU(np.random.rand(8, 32, 32).astype(np.float32))` |
| Integer with BSCALE | (16, 16) | int16 + BZERO/BSCALE | `fits.PrimaryHDU(arr_int16, header)` with header keywords set |

All written to `tmp_path` (pytest); no binaries committed.

---

## Non-goals

- No FITS table reading (BINTABLE). Only IMAGE HDUs.
- No FITS writing. Astroray reads FITS; it writes PNG and EXR.
- No full WCS → 3D coordinate transformation. Pixel data loaded as-is.
- No on-the-fly regridding or resampling. Native resolution only.
- No multi-HDU compositing. Single HDU per object.

---

## Progress

- [ ] Verify `ASTRORAY_ENABLE_FITS` flag works on this toolchain (cfitsio via vcpkg).
- [ ] Implement `fits_io.h` wrapper.
- [ ] Implement `FITSTexture` plugin (2D).
- [ ] Implement `FITSVolume` plugin (3D).
- [ ] Write tests (synthetic data via astropy at test time).
- [ ] Add Blender UI.
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md.

---

## Lessons

*(Fill in after the package is done.)*

# pkg47 — FITS Data Loader

**Pillar:** 4
**Track:** B (self-contained I/O plugin)
**Status:** open
**Estimated effort:** 1–2 sessions (~4 h)
**Depends on:** pkg04 (shape/texture plugin system)

---

## Goal

**Before:** Astroray cannot load observational or simulation data in
FITS format. Users with Hubble, JWST, or radio telescope data cannot
visualise it in the renderer.

**After:** A `FITSLoader` plugin reads FITS files and exposes them as
either volumetric data cubes (3D: x, y, wavelength/velocity) or
plane-sky textures (2D images). The data integrates with the existing
texture and volume plugin systems so it can be assigned to objects,
used as emission sources, or displayed as environment maps.

---

## Context

FITS (Flexible Image Transport System) is the universal data format in
astronomy. Every telescope — Hubble, JWST, ALMA, VLA, Chandra — outputs
FITS. Supporting FITS import is essential for Astroray's positioning as
an astrophysical visualisation tool, because it lets users overlay their
own data with synthetic models (e.g., render a Kerr black hole in front
of a real JWST deep field, or volume-render an ALMA data cube of a
protoplanetary disk).

---

## Reference

- Design doc: `.astroray_plan/docs/astrophysics.md §4.5`
- CFITSIO: https://heasarc.gsfc.nasa.gov/fitsio/ (permissive license)
- EleFits: https://github.com/CNES/EleFits (LGPL-3, dynamic link OK)
- External references: `.astroray_plan/docs/external-references.md §4`
- FITS standard: https://fits.gsfc.nasa.gov/fits_standard.html

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
| `include/astroray/fits_io.h` | FITS reading wrapper around CFITSIO. Isolates the C API from plugin code. |
| `tests/test_fits_loader.py` | Unit and integration tests. |
| `tests/data/test_2d.fits` | Small (64×64) synthetic 2D FITS image for testing. |
| `tests/data/test_3d.fits` | Small (32×32×8) synthetic 3D FITS cube for testing. |
| `scripts/generate_test_fits.py` | Python script to create the synthetic test FITS files using astropy.io.fits. |

### Files to modify

| File | What changes |
|---|---|
| `CMakeLists.txt` | Add CFITSIO as optional dependency via `find_package` or FetchContent. Build gate: if CFITSIO not found, FITS plugins are skipped (no build failure). |
| `include/astroray/register.h` | Confirm `DataLoaderRegistry` exists; add if needed. |
| `module/blender_module.cpp` | Expose `load_fits_texture(path)` and `load_fits_volume(path)` methods on the renderer. |
| `blender_addon/__init__.py` | Add FITS file browser to import panel. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg47 done. |
| `CHANGELOG.md` | Add pkg47 entry. |

### Supported FITS features

| Feature | Supported | Notes |
|---|---|---|
| 2D images (IMAGE HDU, NAXIS=2) | Yes | Loaded as texture. |
| 3D data cubes (NAXIS=3) | Yes | Loaded as volume. Third axis interpreted as wavelength or velocity per WCS. |
| Multiple HDUs | First IMAGE HDU by default; user can specify HDU index. | |
| Floating point data (BITPIX −32, −64) | Yes | Native float/double. |
| Integer data (BITPIX 8, 16, 32) | Yes | Converted to float, applying BSCALE/BZERO. |
| WCS coordinates | Read and stored as metadata; used for physical scale if present. | Not required. |
| Compressed FITS (.fits.gz, tile compression) | Via CFITSIO transparent decompression. | |
| FITS tables (BINTABLE) | No | Out of scope. |

### Data representation

**2D → FITSTexture**: registered as a texture plugin. The FITS image
becomes a 2D floating-point texture that can be assigned to any object's
surface or used as an environment map background. Values are normalised
to [0, 1] by default (using DATAMIN/DATAMAX or computed min/max) with
an optional `exposure` parameter for manual scaling.

**3D → FITSVolume**: registered as a volume plugin (or as a
`ConstantMedium`-style shape with density from the cube). Each voxel's
value maps to density and/or emission intensity. The third axis
(wavelength/velocity) can optionally drive spectral emission: at each
sample point, the plugin looks up the cube slice closest to the current
hero wavelength and returns that value as spectral radiance. This enables
wavelength-resolved volume rendering of IFU data cubes.

### CFITSIO integration

The `fits_io.h` wrapper provides:

- `FITSFile::open(path)` — opens file, reads primary HDU metadata.
- `FITSFile::readImage2D()` → `std::vector<float>` + width, height.
- `FITSFile::readCube3D()` → `std::vector<float>` + nx, ny, nz.
- `FITSFile::header(key)` → string value of any header keyword.
- RAII: file handle closed on destruction.

CFITSIO's C API is wrapped in this single header so plugin code never
touches `fitsio.h` directly.

### Key design decisions

1. **CFITSIO, not EleFits, for the initial implementation.** CFITSIO
   is more widely available (often pre-installed on Linux), has no C++20
   requirement, and handles compressed FITS transparently. EleFits can
   be considered as a future alternative if the C API proves painful.

2. **Optional dependency.** If CFITSIO is not found at build time, the
   FITS plugins are simply not compiled. No build failure. A runtime
   warning is printed if a user tries to load FITS without the plugins.

3. **BSCALE/BZERO applied automatically.** Integer FITS data uses
   BSCALE and BZERO header keywords to map to physical values. CFITSIO
   applies these by default when reading to float; the wrapper does not
   suppress this.

4. **WCS is metadata, not geometry.** WCS (World Coordinate System)
   headers encode the mapping from pixel to sky coordinates. The loader
   reads and stores them but does not transform the data — the user
   positions and scales the object in Blender. Physical scale from WCS
   can be exposed as a convenience (e.g., auto-setting object
   dimensions to match the angular extent) in a future enhancement.

5. **No astropy dependency at runtime.** astropy is used only in the
   test-data generation script. The C++ loader uses CFITSIO directly.

---

## Acceptance criteria

- [ ] CFITSIO added as optional CMake dependency; build succeeds with
      and without it.
- [ ] `FITSTexture` registered and loads a 2D FITS image as a texture.
- [ ] `FITSVolume` registered and loads a 3D FITS cube as a volume.
- [ ] Test 2D: a synthetic gradient FITS image renders correctly on a
      plane (gradient visible, not black or inverted).
- [ ] Test 3D: a synthetic cube renders as a volume with density
      variation along the third axis.
- [ ] BSCALE/BZERO: an integer FITS file with non-trivial scaling
      produces correct float values.
- [ ] Missing CFITSIO: build completes; attempting to load FITS prints
      a clear error message.
- [ ] Blender addon has a FITS import button.
- [ ] All existing tests pass.
- [ ] ≥6 new tests covering: 2D load, 3D load, header reading,
      scaling, missing-file error, build-without-CFITSIO.

---

## Non-goals

- Do not implement FITS table reading (BINTABLE). Only IMAGE HDUs.
- Do not implement FITS writing. Astroray reads FITS; it writes PNG
  and (eventually) EXR.
- Do not implement full WCS → 3D coordinate transformation. Pixel
  data is loaded as-is; positioning is manual.
- Do not implement on-the-fly regridding or resampling. Data is loaded
  at native resolution.
- Do not implement multi-HDU compositing (e.g., RGB from 3 separate
  HDUs). Single-HDU loading per object.

---

## Progress

- [ ] Add CFITSIO to CMakeLists.txt as optional dependency.
- [ ] Implement `fits_io.h` wrapper.
- [ ] Implement `FITSTexture` plugin (2D).
- [ ] Implement `FITSVolume` plugin (3D).
- [ ] Generate synthetic test FITS files.
- [ ] Write tests.
- [ ] Add Blender UI.
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md.

---

## Lessons

*(Fill in after the package is done.)*

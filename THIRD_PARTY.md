# Third-party attributions

Astroray is licensed under the MIT License (see [LICENSE](LICENSE)). This
file records the provenance and license terms of third-party code and
data vendored into the repository.

---

## Data files

### `data/spectra/rgb_to_spectrum_srgb.coeff`

Pre-trained Jakob-Hanika (2019) sigmoid coefficient lookup table for
upsampling sRGB values into spectral reflectances.

- **Paper:** Wenzel Jakob and Johannes Hanika,
  *A Low-Dimensional Function Space for Efficient Spectral Upsampling*,
  Computer Graphics Forum (Eurographics 2019), Volume 38, Number 2.
- **Data mirror used:** the binary file was obtained from the
  `simple-spectral` repository by Ian Mallett
  ([geometrian/simple-spectral](https://github.com/geometrian/simple-spectral),
  MIT-licensed) at
  `data/jakob-and-hanika-2019-srgb.coeff`. The same data is also
  mirrored in the PBRT v4 distribution and published by the authors on
  Zenodo.
- **License:** released by the authors under the Apache License 2.0
  alongside their reference implementation.
- **Why vendored:** the file is 9.4 MB of immutable binary data with no
  build-time toolchain; downloading at build time would introduce a
  network dependency.

### `data/spectra/cie1964_10deg_1nm.csv`

Comma-separated table of the CIE 1964 10° Standard Observer colour
matching functions at 1 nm resolution over 360–830 nm. Used only by
`scripts/generate_spectrum_data.py` as an input cross-check — the
runtime ships the baked `.inc` header, not this CSV.

- **Canonical source:** CIE (Commission Internationale de l'Éclairage),
  via the Colour & Vision Research Laboratory mirror at
  http://cvrl.ucl.ac.uk/.
- **License:** the underlying data is public domain (a CIE technical
  standard); Astroray ships a verbatim copy of the commonly-distributed
  1 nm tabulation. No additional license terms attach.

### `data/spectra/cie_cmf.inc` and `data/spectra/illuminant_d65.inc`

Auto-generated C++ `constexpr` tables containing the CIE 1964 10°
Standard Observer and the CIE Standard Illuminant D65 SPD,
respectively, at 1 nm resolution over 360–830 nm.

- **Generator:** `scripts/generate_spectrum_data.py` (Astroray).
- **Input sources:** the `MSDS_CMFS` and `SDS_ILLUMINANTS` tables
  shipped with [Colour-Science](https://www.colour-science.org/)
  version 0.4.7 (BSD 3-Clause). Colour-Science itself is *not* vendored
  into Astroray; only the generated numeric output is.
- **License of the data values:** public domain (CIE standards).

---

## C/C++ headers

### `include/stb_image.h`, `include/stb_image_write.h`

Single-file image IO libraries by Sean Barrett and contributors.

- **Upstream:** [nothings/stb](https://github.com/nothings/stb).
- **License:** dual-licensed under the MIT License and the Public
  Domain (Unlicense). The full license text is preserved at the bottom
  of each header.
- **How used:** implementations are compiled into the `stb_impl` /
  `stb_image_write_lib` static libraries defined in
  [CMakeLists.txt](CMakeLists.txt).

---

## Test-time dependencies (not redistributed)

The offline data generator `scripts/generate_spectrum_data.py` uses
[Colour-Science](https://github.com/colour-science/colour) (BSD
3-Clause) to read the authoritative CIE tables. The library is used at
generation time only; the generated artefacts (`cie_cmf.inc`,
`illuminant_d65.inc`, `tests/data/spectrum_reference.json`) contain no
Colour-Science code. Astroray does not depend on Colour-Science at
build time or runtime.

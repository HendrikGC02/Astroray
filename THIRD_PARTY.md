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

### `data/spectra/cie_cmf.inc` and `data/spectra/illuminant_d65.inc`

Auto-generated C++ `constexpr` tables containing the CIE 1964 10°
Standard Observer and the CIE Standard Illuminant D65 SPD,
respectively, at 1 nm resolution over 360–830 nm.

- **Generator:** `scripts/data/generate_spectrum_data.py` (Astroray).
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

### `include/astroray/bssrdf_random_walk.h`

Random-walk BSSRDF (subsurface scattering) CPU-prototype core. The math is
ported (not a verbatim file copy) from Blender Cycles and cited per-function.

- **Upstream:** [blender/cycles](https://github.com/blender/cycles) —
  `src/kernel/integrator/subsurface_random_walk.h` and
  `src/kernel/closure/bssrdf.h` (`main`, fetched 2026-08-08, Blender 5.2-era).
- **License:** Apache-2.0 (`SPDX-FileCopyrightText: 2011-2022 Blender
  Foundation`). Compatible with Astroray's MIT LICENSE — Apache-2.0 permits
  redistribution of derivative works with attribution; this notice + the
  per-function citations in the header satisfy it.
- **Papers cited in the header:** Chiang/Kutz/Burley (SIGGRAPH 2016, color
  remap), d'Eon *Hitchhiker's Guide* (2016, van de Hulst inversion),
  Křivánek & d'Eon (SIGGRAPH 2014), Meng/Hanika/Dachsbacher (EGSR 2016),
  d'Eon & Křivánek (SIGGRAPH 2020) — Dwivedi / zero-variance guiding;
  Henyey-Greenstein (1941, phase function).
- **How used:** header-only CPU prototype (pkg178 D2 parallel track); not yet
  compiled into a target. Research note:
  `.astroray_plan/docs/bssrdf-random-walk-research.md`.

### `external/cycles_light_tree/`

Vendored reference copy of Blender Cycles' light-tree implementation,
kept alongside the Astroray port for per-function citation and future
parity work (pkg86). Not compiled into any target.

- **Upstream:** [blender/cycles](https://github.com/blender/cycles) —
  `src/scene/light_tree.{h,cpp}` and related kernel headers.
- **License:** Apache-2.0 (`SPDX-FileCopyrightText: 2011-2022 Blender
  Foundation`). Compatible with Astroray's MIT LICENSE with attribution;
  the ported code cites the reference per-function in
  `src/light_tree.cpp` and `include/astroray/light_tree.h`.
- **How used:** reference-only (license attribution + parity audits);
  deleting it would break the citation chain.

---

## Test-time dependencies (not redistributed)

The offline data generator `scripts/data/generate_spectrum_data.py` uses
[Colour-Science](https://github.com/colour-science/colour) (BSD
3-Clause) to read the authoritative CIE tables. The library is used at
generation time only; the generated artefacts (`cie_cmf.inc`,
`illuminant_d65.inc`, `tests/data/spectrum_reference.json`) contain no
Colour-Science code. Astroray does not depend on Colour-Science at
build time or runtime.

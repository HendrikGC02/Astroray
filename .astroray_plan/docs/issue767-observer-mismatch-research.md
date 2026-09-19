# #767 colour skew — observer mismatch (batch T, 2026-09-20)

## Verdict

The engine integrated spectra with the **CIE 1964 10°** CMF but converted XYZ with
the **CIE 1931 2°** sRGB matrix, and the Jakob–Hanika LUT is also fit against 1931 2°.
The mismatch owns essentially all of #767 and the #795 chrome green skew.
Albedo upsampling and illuminant upsampling are ≤0.4 % terms once the observer matches.
Fix: bake the 1931 2° table (`data/spectra/cie_cmf.inc`), rename
`cieCmf1964_10deg` → `cieCmf1931_2deg`. CPU and GPU read the same table.

## Sources (cite-algorithm)

- **sRGB/Rec.709 matrix observer.** IEC 61966-2-1:1999 and ITU-R BT.709-6 §1 give
  primaries and D65 white as **CIE 1931** xy chromaticities. The matrix in
  `include/astroray/spectral.h::xyzToLinearSRGB` (3.2406 …) is derived from them.
  Empirical check: D65 through 2° CMF + this matrix = (0.9999, 1.0001, 0.9997);
  through the 10° CMF it is (1.0001, 1.0017, 0.9831).
- **JH LUT fitting observer.** Jakob & Hanika 2019, "A Low-Dimensional Function
  Space for Efficient Spectral Upsampling" (DOI 10.1111/cgf.13626). Reference optimiser
  `mitsuba-renderer/rgb2spec` `rgb2spec_opt.cpp` includes `details/cie1931.h`
  ("CIE 1931 curves", 360–830 nm at 5 nm, `cie_x[0]=0.0001299`). Empirical check: with
  the 2° CMF the vendored LUT round-trips a 7³ RGB grid in [0.05, 0.95] under D65 to
  max |err| 9.9e-4. With the 10° CMF the max |err| is 0.117.
- **Cycles cross-check.** Cycles is RGB. A white world returns exactly (1, 1, 1) and a
  diffuse tile returns exactly its albedo (measured below).
- Observer data: CIE 1931 2° from colour-science 0.4.7 `MSDS_CMFS` (cvrl.ucl.ac.uk,
  public domain), the same pipeline as the old table (`scripts/data/generate_spectrum_data.py`).

## Method

1. **Quadrature model** (1 nm, 380–780 nm band). It mirrors `src/spectrum.cpp`: LUT
   lookup, sigmoid, `RGBIlluminantSpectrum` = JH·D65/∫D65ȳ, `toXYZ`, and the
   engine's matrix.
2. **Addon renders.** Headless Blender 5.2 with main's staged addon (916907b), Astroray
   on CPU (`cycles.device=CPU`) against Cycles CPU. 512 spp, adaptive off, clamps off,
   linear EXR. Five 0.9 m tiles at near-orthographic zenith view (50 m, 5.6 m
   field). Tiles: Diffuse grey 0.18, #767 ground (0.25, 0.27, 0.24), green
   (0.15, 0.45, 0.25), blue (0.1, 0.1, 0.8), and chrome (Principled metallic 1, base
   (0.9, 0.9, 0.92), roughness 0.05). Worlds: flat white 1.0 (**test 2**, albedo path)
   and `syferfontein_18d_clear_1k.hdr` (**test 1**, illuminant path). ROI = inner
   60 % of each tile.
3. **Test 3 (observer swap)** = the same model with the 2° table, then the same
   renders on the fixed build.

## Results — Astroray/Cycles per channel (R, G, B)

White world (test 2). Render matches the 10° model to ≤0.1 %.

| tile | render, 10° (main) | model 10° | model 2° |
|---|---|---|---|
| grey 0.18 | 0.997 / 0.999 / 0.981 | 0.997 / 0.999 / 0.980 | 0.997 / 0.997 / 0.997 |
| #767 ground | 1.011 / 0.993 / 0.976 | 1.011 / 0.994 / 0.975 | 0.999 / 0.999 / 0.998 |
| green | 1.195 / 0.978 / 0.936 | 1.195 / 0.978 / 0.936 | 0.998 / 1.000 / 0.999 |
| blue | 0.639 / 1.441 / 1.014 | 0.640 / 1.441 / 1.014 | 0.999 / 0.997 / 1.000 |
| chrome | 0.999 / 1.004 / 0.985 | 1.000 / 1.004 / 0.985 | 1.001 / 1.001 / 1.000 |
| world seen directly | 1.000 / 1.002 / 0.983 | 1.000 / 1.002 / 0.983 | 1.000 / 1.000 / 1.000 |

HDRI (test 1). Hemisphere-weighted model over all 512×1024 texels. The render
matches the 10° model to ≤1.3 %; the remainder is sun MC noise.

| tile | render, 10° (main) | model 10° | model 2° |
|---|---|---|---|
| grey 0.18 | 1.006 / 0.980 / 0.969 | 1.009 / 0.983 / 0.973 | 1.000 / 1.000 / 0.999 |
| #767 ground | 1.015 / 0.965 / 0.961 | 1.023 / 0.974 / 0.964 | 1.003 / 0.997 / 0.998 |
| green | 1.276 / 0.941 / 0.918 | 1.293 / 0.954 / 0.929 | 1.090 / 0.990 / 1.005 |
| blue | 0.659 / 1.427 / 1.007 | 0.668 / 1.445 / 1.020 | 0.928 / 1.100 / 1.014 |
| chrome (zenith sky) | 0.950 / 1.080 / 1.005 | 0.940 / 1.081 / 1.005 | 1.000 / 0.998 / 1.000 |

## Attribution

| term | size with 2° observer | owns |
|---|---|---|
| Observer mismatch (10° CMF, 2° matrix and LUT) | removed | #767 B −3…−4 % and G −2…−3.5 % on the ground; white B −1.7 %; #795 chrome G +8 % (zenith) and +11 % (pkg275 sphere median) |
| Albedo upsampling (JH round trip under D65) | ≤0.4 % (grid max abs 9.9e-4) | nothing measurable |
| Illuminant upsampling (HDRI texels) | ≤0.1 % grey, ≤0.2 % chrome | nothing measurable |
| Spectral product (JH albedo × JH sky, metamerism) | 0.3 % on the #767 ground; up to 9–10 % on saturated green/blue under sky | physical, not a bug. Cycles multiplies in RGB. Within the cross-check band |

## Side effects

- D65 white XYZ becomes (0.95047, 1, 1.08883), the CIE nominal (was 0.9481, 1, 1.0731).
- Blackbody luminance normalisation and D65 Y = 1 re-derive from the table automatically.
- The pkg206 hero-λ proposal was fitted to the 10° ȳ. It stays unbiased (pdf = own
  density). A re-fit would only change variance. Not done.
- `include/astroray/spectral.h` already carried a 1931 2° 5 nm table (legacy
  `SpectralSample`, ReSTIR luminance). The pkg218 thread-B "1931/1964 split" is gone.

## After-fix measurement

(filled after the build; see PR.)

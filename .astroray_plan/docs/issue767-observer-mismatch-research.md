# #767 colour skew — observer mismatch (batch T, 2026-09-20)

Status: fix in PR #837 (engine table CIE 1931 2°, build 887bdfb0). Follow-up: #848 (hero-λ re-fit).

## Verdict

The engine integrated spectra with the **CIE 1964 10°** CMF but converted XYZ with
the **CIE 1931 2°** sRGB matrix, and the Jakob–Hanika LUT is also fit against 1931 2°.
The mismatch owns the grey and low-chroma skew: the #767 ground, white B −1.7 %, and
the #795 chrome G +8 %. Albedo upsampling and illuminant upsampling are ≤0.4 % terms
once the observer matches. Saturated albedo under a coloured sky keeps a residual of
up to ~9 %. That residual is the physical spectral product (Cycles multiplies in
RGB), not a bug.
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
  ("CIE 1931 curves", 360–830 nm at 5 nm, `cie_x[0]=0.0001299`;
  https://github.com/mitsuba-renderer/rgb2spec, not vendored; the `.coeff` comes via
  simple-spectral). Empirical check: with
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
  density). A 2° re-fit (kHeroA +0.8 %, kHeroX0 552.0 → 555.7 nm) only changes
  variance and needs a CPU+GPU lockstep constant edit. Deferred to #848; the
  comments now say so.
- Mercury line lamp (pkg222): xy (0.334, 0.368) under 10° → (0.317, 0.396) under 2°.
  Real-lamp targets are quoted in CIE 1931 xy, so pkg222's "Δxy≈0.01" claim needs a
  re-check under pkg218.
- `include/astroray/spectral.h` already carried a 1931 2° 5 nm table (legacy
  `SpectralSample`, ReSTIR luminance). The pkg218 thread-B "1931/1964 split" is gone.

## After-fix measurement (build 887bdfb0, same addon renders)

The fix `.pyd` was overlaid on a scratch copy of the 916907b staged addon; the
branch changes no addon `.py`. Sheet (Cycles | main | fix | ratio maps):
`test_results/batchT/issue767_tiles_before_after.png`.

| tile | white world, fix | HDRI, fix (mean ratio) | HDRI, main |
|---|---|---|---|
| grey 0.18 | 0.997 / 0.997 / 0.997 | 0.997 / 0.997 / 0.995 | 1.006 / 0.980 / 0.969 |
| #767 ground | 0.999 / 0.999 / 0.999 | 0.994 / 0.988 / 0.993 | 1.015 / 0.965 / 0.961 |
| green | 0.998 / 1.000 / 1.000 | 1.075 / 0.977 / 0.992 | 1.276 / 0.941 / 0.918 |
| blue | 0.998 / 0.997 / 1.000 | 0.915 / 1.086 / 1.001 | 0.659 / 1.427 / 1.007 |
| chrome | 1.000 / 1.001 / 1.000 | 1.006 / 1.001 / 1.000 | 0.950 / 1.080 / 1.005 |
| world seen directly | 1.000 / 1.000 / 0.999 | 0.990 / 0.986 / 1.000 | 0.976 / 0.946 / 0.965 |

- The #767 ground's G/B spread under the HDRI drops from 5.4 pp to 0.6 pp. Chrome G
  +8 % → +0.1 %.
- The green and blue HDRI rows match the 2° model's spectral-product prediction
  (1.09 / 0.99 / 1.005 and 0.93 / 1.10 / 1.01) to ≤1.5 %.
- HDRI per-pixel medians sit low (sun noise, skewed per-pixel distribution). The
  diffuse tiles therefore use the ROI mean.

In-process (CPU, `path_tracer`, lambertian sphere under white world, 1024 spp):
sphere/albedo within 0.4 % for grey, #767 ground and blue (main: blue 0.633 / 1.447 / 1.011).

**Blackbody colour against an independent oracle.** Oracle: colour-science
`sd_blackbody` → 1931 XYZ → sRGB. Dedicated area light on a white plane, black world:

| T | oracle | fix | main |
|---|---|---|---|
| 6500 K | 1 / 0.943 / 0.992 | 1 / 0.944 / 0.991 | 1 / 0.946 / 0.983 |
| 3000 K | 1 / 0.477 / 0.154 | 1 / 0.477 / 0.154 | 1 / 0.459 / 0.148 |

`test_pkg89_phase_b_dedicated_lights::test_g2` failed after the fix (12.16 % vs its
12 % gate). A probe showed it never measured the light. The emitter faced away from
the plane, so with a black world the plane rendered 0 for 6500 K, 3000 K and RGB white.
The gamma-encoded default sky was the entire signal. The test was rewritten to measure
the light against the oracle above.

**GPU and test attribution (under the GPU lock).**

`tests/test_issue767_observer_contract.py`, run with each `.pyd`:
- #837: 15/15 pass, including the GPU legs of the white-world sphere.
- main: all 8 engine tests fail (binding, round trip, and the CPU and GPU sphere legs).

`test_gpu_spectral_melanin_matches_cpu` failed on #837 (B 0.832 < 0.85):
- It is seed noise, not a regression. Per-seed B GPU/CPU on main is 0.79–0.91
  over 6 seeds, and 2 of 6 already fail.
- Pooled over the 6 seeds, B is 0.865 on main and 0.880 on #837.
- The test now pools those 6 seeds.
- The underlying GPU/CPU hair difference is pre-existing: GPU +11 % on
  unpigmented hair. Filed as #853.

# pkg54c — GPU Jakob-Hanika Spectral Upsampling

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 3–5 days
**Depends on:** pkg54b

---

## Goal

**Before:** The GPU multi-wavelength path tracer upsamples RGB to spectra via
a 3-Gaussian basis (`gpu_spectralChannelWeight` in
[include/astroray/gpu_materials.h](include/astroray/gpu_materials.h)) — a
cheap analytic stand-in for proper sigmoid coefficients. The CPU
integrator uses Jakob-Hanika 2019 sigmoid coefficients via
`RGBAlbedoSpectrum` / `RGBIlluminantSpectrum` in
[src/spectrum.cpp](src/spectrum.cpp), backed by the
`data/spectra/rgb_to_spectrum_srgb.coeff` LUT. After pkg54b (CMF table
parity) and the D65 SPD lookup added during pkg54a/b verification,
visible-band SSIM lands at ~0.988 at 64 spp / ~0.996 at 512 spp; the
remaining gap is entirely the upsampling shape mismatch.

**After:** GPU and CPU evaluate the *same* spectral upsampling kernel.
`gpu_rgbSpectrumAt` consults the same Jakob-Hanika sigmoid coefficient
LUT (uploaded once to constant or texture memory) and evaluates
`evalSigmoidCoeffs` per wavelength. Both `GSPEC_RGB_REFLECTANCE` and
`GSPEC_RGB_ILLUMINANT` go through the LUT; the latter additionally
multiplies by `gpu_sampleD65(λ)` (already present from the pkg54b
verification work).

---

## Context

The pkg54a/b verification on hardware uncovered that the residual
visible-band SSIM gap (≥0.99 unreachable) is *not* a CMF or D65 issue —
those are now fixed — but the per-wavelength shape difference between a
3-Gaussian RGB→spectrum mix and Jakob-Hanika sigmoid coefficients. The
gap is small (CPU/GPU pixel means agree within ~2 %) but SSIM picks it
up as a chromaticity shift the integration never averages out.

---

## Reference

- Jakob & Hanika, *"A Low-Dimensional Function Space for Efficient
  Spectral Upsampling"*, Eurographics 2019.
  - DOI: 10.1111/cgf.13626
  - Reference implementation:
    [https://github.com/mitsuba-renderer/rgb2spec](https://github.com/mitsuba-renderer/rgb2spec)
    (BSD-3-Clause; compatible with Astroray licensing).
- Existing CPU port: `evalSigmoidCoeffs` + `RGBAlbedoSpectrum` in
  [src/spectrum.cpp](src/spectrum.cpp) and the baked LUT
  `data/spectra/rgb_to_spectrum_srgb.coeff`.

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `src/gpu/multiwavelength_kernel.cu` | Add `__constant__` (or `cudaTextureObject_t`) for the JH coefficient LUT; add `uploadJakobHanikaTable()` + `gpu_evalSigmoidCoeffs(coeffs, λ)` device helper. |
| `include/astroray/gpu_materials.h` | Replace the 3-Gaussian mix in `gpu_rgbSpectrumAt` with a JH lookup. Same forward-declaration pattern as `gpu_sampleD65`. |
| `src/gpu/scene_upload.cu` | Per-material RGB → JH sigmoid coefficients computed at upload time (mirror `RGBAlbedoSpectrum` / `RGBIlluminantSpectrum` constructors); store the 3 coeffs on `GMaterial`. |
| `include/astroray/gpu_types.h` | Add `float jhCoeffs[3]` to `GMaterial` (or compute coeffs at lookup time from `baseColor` if cheap enough). |
| `src/gpu/cuda_renderer.cu` | Call `uploadJakobHanikaTable()` next to `uploadCmfTables()`. |
| `tests/test_gpu_multiwavelength.py` | Tighten visible-band SSIM gate from 0.985 to **0.999**. |

### Key design decisions

1. **LUT layout.** The JH LUT is a 3D `(z, y, x)` grid of 3 sigmoid
   coefficients (~256³ × 3 × 4 B = 192 MB raw; the actual baked file is
   smaller via the resolution / quantization choices in
   `rgb_to_spectrum_srgb.coeff`). Texture memory with linear
   filtering is the right home; constant memory is too small.
2. **Coefficient storage on `GMaterial`.** Pre-baking the 3 coeffs at
   `uploadScene` time avoids a 3D texture lookup per BSDF eval; only the
   sigmoid evaluation runs on the device hot path. This mirrors how
   `RGBAlbedoSpectrum` caches `c_` in [src/spectrum.cpp:418](src/spectrum.cpp).
3. **Illuminant scaling.** Keep the existing `gpu_sampleD65(λ)` factor
   for `GSPEC_RGB_ILLUMINANT` — it already mirrors
   `RGBIlluminantSpectrum::sample` once the spectral RGB factor matches.

---

## Acceptance criteria

- [ ] Visible-band CPU vs GPU SSIM ≥ **0.999** on the pkg54 parity scene
  at 64 spp.
- [ ] CPU/GPU per-pixel mean ratio ≥ 0.999 (currently ~0.982).
- [ ] No regression in NIR/UV gates (still ≥ 0.97).
- [ ] `gpu_evalSigmoidCoeffs(c, λ)` matches CPU `evalSigmoidCoeffs(c, λ)`
  bit-equal (within 1 ULP) for a sampled grid of (c, λ) values via a
  Python test harness.

---

## Non-goals

- No change to the CPU upsampling.
- No spectral closure rework — `gpu_material_eval_spectral` still routes
  through `gpu_rgbToSampledSpectrum`.
- No support for non-sRGB gamuts (sRGB LUT only, like the CPU).

---

## Progress

- [ ] Bake / load `data/spectra/rgb_to_spectrum_srgb.coeff` to GPU texture memory.
- [ ] Add `gpu_evalSigmoidCoeffs` device function.
- [ ] Pre-bake JH coefficients on `GMaterial` in `scene_upload.cu`.
- [ ] Replace the Gaussian mix in `gpu_rgbSpectrumAt`.
- [ ] Tighten visible-band gate to 0.999.

---

## Lessons

*(Fill in after the package is done.)*

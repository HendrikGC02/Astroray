# Noise per time: Astroray vs Cycles, with a Mitsuba 3 spectral arbitration leg (pkg307, 2026-10-02)

Instrument: `benchmarks/reference_corpus/mc_tolerance.py --noise-bench` (+ `report_tools.py noise-bench`).
Evidence: `test_results/integrator/noise-per-time/` (charts, equal-time sheets, `efficiency_table.csv`,
`arbitration/`). Companion: `research-noise-2026-09-29.md`, `comparison-renderers-2026-09-29.md`.

## Settings (state these with every number)

- Build: Astroray `94992cb1` C++ (`Astroray-aq-300/build_cuda`), Blender 5.2.0, RTX 5070 Ti, CPU legs 8 threads.
- Corpus v2 scenes as authored: `blur_glossy = 0`, `sample_clamp_indirect = 0` (**not Blender's defaults**),
  adaptive and denoise off, Cycles pattern AUTOMATIC (Sobol-Burley), pixel filter Blackman-Harris 1.5 px.
- Seeds 278-282 (5 per point). Reference: Cycles 1024 spp (`refs_v2/`); arbitration scenes: Mitsuba spectral 16384 spp.
- Time = render-only seconds by spp differencing (64 -> 320 spp GPU at >= 1280 px wide; 8 -> 72 spp CPU at the manifest
  size, scaled by pixel count), burn-in then median of 3 paired slopes; reported per 1280x720 frame. Noise is measured per
  pixel at the manifest resolution. Equal time = spp rounded **down** to a power of two within the budget; efficiency
  `1/(relMSE x t)` uses the actual time, so the rounding does not bias ratios.
- relMSE = relVar + bias^2, bias^2 at ROI-mean level (a per-pixel bias against a finite-spp reference is dominated by the
  reference's own noise at long budgets).
- GPU clocks: 2880-3090 MHz during timing, 47-50 C; per-batch notes in `timing.json`.

## Headline: equal-time efficiency, whole image (1 = Cycles; < 1 = Astroray less efficient)

| scene | GPU 2 s | GPU 10 s | GPU 60 s | CPU 10 s |
|---|---|---|---|---|
| camera_geometry | 0.161 | 0.148 | 0.133 | 0.129 |
| camera_geometry@ortho | 0.160 | 0.142 | 0.108 | 0.267 |
| dispersion_caustics | 0.042 | 0.043 | 0.014 | 0.120 |
| light_tree | 0.322 | 0.289 | 0.271 | 0.275 |
| media | 0.052 | 0.028 | 0.006 | 0.128 |
| sky_sun | 0.090 | 0.070 | 0.064 | 0.040 |
| textures_opvm | 0.093 | 0.088 | 0.074 | 0.040 |
| thin_film_metals | 0.255 | 0.250 | 0.251 | 0.230 |

At equal time on the GPU Astroray's MSE is 3x (light_tree) to 36x (media at 60 s) Cycles OptiX's; the GPU figures are far
from parity everywhere (best 0.32). Per-spp time ratios (GPU, was 3.8-9.1x on 2026-09-29, now after pkg298/299/300):
1.4 (media), 2.1 (opvm), 2.5-2.7 (camera), 3.0 (thin film), 3.3 (light_tree), 3.5 (sky), 3.8 (dispersion).

## Where Astroray is noisier, and why (64 spp, whole image, GPU vs OptiX)

| scene | time/spp | var ratio | chroma ratio | top-0.1 % share A / C | N x relVar slope A / C | bias^2 share |
|---|---|---|---|---|---|---|
| camera_geometry | 2.7 | 1.9 | 5.8 | 0.13 / 0.17 | -0.01 / -0.09 | 0.1 % |
| light_tree | 3.3 | 0.9 | 1.0 | 0.09 / 0.07 | -0.04 / -0.04 | 0.1 % |
| thin_film_metals | 3.0 | 1.2 | 2.7 | 0.45 / 0.45 | -0.02 / -0.03 | 0.0 % |
| textures_opvm | 2.1 | 4.5 | 3.8 | 0.38 / 0.44 | 0.00 / -0.00 | 0.0 % |
| sky_sun | 3.5 | 2.3 | 1.9 | 0.79 / 0.85 | -0.45 / -0.45 | 0.0 % |
| media | 1.4 | 10.4 | 4.0 | 0.79 / 0.70 | +0.46 / -0.24 | 0.1 % |
| dispersion_caustics | 3.8 | 248 | 318 | 1.00 / 1.00 | -0.22 / +1.78 | 0.0 % |

Reading: noise is **variance, not bias**: at the image level bias^2 is < 0.5 % of relMSE everywhere (ROI rows can differ;
see `efficiency_table.csv`). Three sources, in order of measured weight:

1. **Per-sample throughput** (1.4-3.8x slower than OptiX): equal-spp variance is only 0.9-2.3x Cycles on light_tree, thin
   film, camera and sky, so the equal-time gap there is mostly time (3x to 7x).
2. **Heavy tails in media and dispersion caustics.** Media: the relVar ratio is 10x and N x relVar *rises* (+0.46:
   variance falls slower than 1/N, 256 -> 1024 spp relMSE 0.51 -> 0.36), so its gap grows with budget (0.052 -> 0.006).
   Dispersion: 0.1 % of pixels hold ~100 % of the variance in both engines, and Astroray's variance is 248x Cycles'.
3. **Colour (chroma) noise and missing stratification of the remaining dimensions.** Chroma relVar is 2-6x Cycles on
   camera, opvm, media, thin film (the hero-wavelength cost; sky_sun is now 1.9x after pkg305 and shows N x relVar slope
   -0.45 in both engines). Cycles' N x relVar slope is -0.09 to -0.24 on camera_geometry, light_tree and media while
   Astroray's is ~0 (plain MC) on all but sky_sun: the QMC gain (pkg297) is still unclaimed.

CPU is similar: Astroray CPU is 1.5-5.5x slower per spp and 0.9-5.8x the variance at equal spp.

## Arbitration scenes (Mitsuba 3 spectral reference; lamp scale anchored to one ROI per scene)

Means at 256 spp, 5 seeds, ratio to the Mitsuba 16384 spp reference (`arbitration/arbitration_roi_means.json`):

| scene / ROI | Cycles | Astroray CPU | Astroray GPU | note |
|---|---|---|---|---|
| chromatic medium, medium_core (R, G, B) | 1.08 / 0.99 / 1.20 | 0.96 / 1.00 / 1.01 | 0.96 / 1.00 / 1.01 | Cycles RGB transport is up to 20 % off in blue; Astroray within 4 % |
| chromatic medium, floor ROIs | 1.00-1.05 | 0.98-1.00 | 0.98-1.00 | all engines agree |
| narrow band (sodium), luminance | 0.18 (white lamp: RGB limit) | 0.999 | 0.999 | anchored at wall_centre |
| narrow band, R / G | 0.11 / 0.27 | 0.93 / 1.07 | 0.93 / 1.07 | **Astroray R/G is 14 % below the CIE integral** |
| prism, floor_caustic (luminance) | 0.04 CPU / 0.38 OptiX | 1.17 | 1.11 | dispersive floor caustic: Astroray mean 11-17 % above Mitsuba, ref SE 1 % |

- **Setup check.** Mitsuba matches a first-principles CIE 1931 integration of the same SPD and Jakob-Hanika albedo to 0.3 %
  in R/G (4.61 vs 4.62); Astroray and Mitsuba share identical CMF tables (max difference 0). Medium and floor ROIs agree
  to 1-4 % across all three engines.
- **Narrow-band chromaticity (new finding).** Astroray renders the sodium lamp with R/G = 3.90 on a grey wall; the CIE
  integral of the same stored SPD (Astroray's `emission(λ)` is `reflectance(λ)`) gives 4.51. That equals a ~1.75 nm shift of
  the SPD. Mitsuba's negative blue (-0.1, out of the sRGB gamut) is clipped to 0 in Astroray. Cause not isolated
  (CMF tables are identical; suspects: wavelength sampling of narrow SPDs on the CPU path, composite white filter).
  Follow-up for pkg218 / the architect; **the acceptance sentence "Mitsuba and Astroray means agree within 3 sigma" holds for
  luminance and for the medium scene, and fails for R and G on the narrow-band scene.**
- **Dispersion floor (for pkg306).** The Mitsuba reference shows the same streak morphology as Astroray GPU (equal-time
  sheet). Astroray's caustic mean is within 11-17 % of Mitsuba (z 3-5 at ref SE 1 %), so the Astroray floor "confetti" is
  mostly real specular-caustic transport, not an energy bug; the variance there (248x Cycles) is tail variance, and
  Mitsuba shows the same sparse hits at equal spp. Cycles recovers only 4 % (CPU) / 38 % (OptiX) of the caustic (no
  dispersion; it finds the 4 degree sun only by chance paths).
- **Open.** Astroray reads 12-16 % above Cycles and Mitsuba at `floor_far` (the anchor ROI, which the sun lights directly);
  `floor_prism_shadow` is 22 % lower in Mitsuba than in all three other engines. Neither is isolated; a prism-less control
  render separates sun/floor convention from caustic leakage.

## Limits

- Mitsuba 3.9.1's `dielectric` has a constant IOR, so scene (a) uses a Python `DispersiveDielectric` (Sellmeier at the hero
  wavelength, lanes 1-3 terminated, x4 once per path at hits from outside). A BSDF cannot see throughput, so a path with a
  diffuse bounce between two prism hits is over-weighted; the floor albedo is 0.15 to keep that share small and the plugin
  is validated against the stock dielectric at constant IOR. It is a bounded few-percent effect, not an exact estimator.
- Mitsuba rows on scene (a) are references, not a noise-per-time comparison of a spectral path tracer.
- The sun is a 4 degree disc in all engines (a delta sun is invisible to path tracers). Mitsuba's lamp scale is anchored on
  a ROI that does not depend on the effect under test (floor vs Cycles; wall luminance vs Astroray CPU for the narrow-band
  lamp, since Astroray does not draw the lamp face), so luminance on the anchor ROI is agreement by construction.
- LuxCore and pbrt-v4 legs are follow-ups (BlendLuxCore 2.11.1 is not installed; pbrt is not built).

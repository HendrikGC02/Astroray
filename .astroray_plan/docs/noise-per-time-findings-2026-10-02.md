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
| camera_geometry | 0.162 | 0.148 | 0.134 | 0.134 |
| camera_geometry@ortho | 0.154 | 0.137 | 0.104 | 0.150 |
| dispersion_caustics | 0.041 | 0.042 | 0.014 | 0.441 (tail-noise) |
| light_tree | 0.309 | 0.277 | 0.261 | 0.213 |
| media | 0.052 | 0.027 | 0.006 | 0.124 |
| sky_sun | 0.093 | 0.073 | 0.067 | 0.043 |
| textures_opvm | 0.085 | 0.081 | 0.068 | 0.029 |
| thin_film_metals | 0.264 | 0.243 | 0.245 | 0.186 |

Run of record: the third full run (two quiet runs agree: 46 of 47 efficiency ratios within 10 %, worst 19 % on a 2 s
dispersion CPU row whose relMSE is 1e6, i.e. pure noise; the first run was not quiet and is not used, its CPU timings
differed by up to 47 %).

At equal time on the GPU Astroray's MSE is 3.2x (light_tree) to 167x (media at 60 s) Cycles OptiX's; the GPU figures are far
from parity everywhere (best 0.31). Per-spp time ratios (GPU, was 3.8-9.1x on 2026-09-29, now after pkg298/299/300):
1.4 (media), 2.3 (opvm), 2.6-2.7 (camera), 3.0 (thin film), 3.4 (light_tree, sky), 3.8 (dispersion); CPU 1.5-6.7x.

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

## Arbitration scenes (Mitsuba 3 spectral reference)

Means at 256 spp, 5 seeds, ratio to the Mitsuba 16384 spp reference (`arbitration/arbitration_roi_means.json`). Prism and
narrow-band rows re-run 2026-10-03 after the #1020/#1021 fixes (Astroray build e584ad85; Cycles legs from the pkg307 run):

| scene / ROI | Cycles | Astroray CPU | Astroray GPU | note |
|---|---|---|---|---|
| chromatic medium, medium_core (R, G, B) | 1.08 / 0.99 / 1.20 | 0.96 / 1.00 / 1.01 | 0.96 / 1.00 / 1.01 | Cycles RGB transport is up to 20 % off in blue; Astroray within 4 % |
| chromatic medium, floor ROIs | 1.00-1.05 | 0.98-1.00 | 0.98-1.00 | all engines agree |
| narrow band (sodium), R / G | 0.13 / 0.30 (white lamp: RGB limit) | 1.000 / 0.997 | 1.000 / 0.997 | R/G 4.62 = CIE integral (Astroray -0.04 % analytic); was 0.93 / 1.07 (#1020) |
| prism, floor_far (luminance) | 0.886 | 1.004 (z 0.4) | 0.988 (z -1.4) | sun-lit floor + prism light; was 1.16 / 1.12 against a Cycles-anchored ref (#1021) |
| prism, floor_caustic (luminance) | 0.04 CPU / 0.33 OptiX | 0.74 (z -7.4) | 0.92 (z -2.5) | CPU caustic deficit #1025; was 1.17 / 1.11 with the desaturating film |
| prism, floor_prism_shadow (luminance) | 1.08 | 1.08 | 1.08 | all three engines 8 % above Mitsuba (z ~40); not isolated |

- **Setup check.** Mitsuba matches a first-principles CIE 1931 integration of the same SPD and Jakob-Hanika albedo to 0.3 %
  in R/G (4.61 vs 4.62); Astroray and Mitsuba share identical CMF tables (max difference 0). Medium and floor ROIs agree
  to 1-4 % across all three engines.
- **#1020 (fixed): narrow-band chromaticity.** The film conversion of the final pixel (CPU and GPU) desaturated out-of-gamut
  colours toward white (`rgb -= min(rgb)`, a display heuristic from the 2026-04 GR commit). The sodium lamp has B < 0, so
  R/G fell from 4.52 (CIE integral of the stored SPD) to 3.90 and luminance rose 12 %. The film now uses the exact
  IEC 61966-2-1 matrix and clips negative channels per channel (B renders 0 where Mitsuba writes -0.08; #1024 decides
  whether scene-linear output keeps negatives). The narrow-band lamp scale had been anchored on the inflated Astroray
  luminance; re-anchored, with the Mitsuba anchor luminance clipped like the film. R agrees within 3 sigma; G is 0.3 % low
  at |z| 4-8 because the reference SE is 0.01 %: that residual is Mitsuba's own 0.3 % offset from the CIE integral above.
- **#1021 (not an engine bug): sun-lit floor.** A Lambertian floor under the 4 degree sun at 22 degrees renders
  rho S sin(e) / pi to -0.3 % on CPU and GPU (sun, uniform dome, both; `tests/test_1021_sun_floor_analytic.py`). Mitsuba
  without the prism gives 0.16115 at `floor_far` (analytic 0.16098), with it 0.1811: the ROI holds 12.5 % prism light that
  Cycles barely renders. The pkg307 calibration anchored Mitsuba's lamp to Cycles on that ROI, scaling Mitsuba down by
  exactly the missing light (0.886), so "Cycles and Mitsuba agree" was by construction. The prism scene now runs Mitsuba in
  physical sun units (no anchor).
- **Dispersion floor (for pkg306).** The Mitsuba reference shows the same streak morphology as Astroray GPU (equal-time
  sheet). With the desaturation gone, Astroray GPU is 8 % and CPU 26 % below Mitsuba on the caustic: the CPU deficit is
  transport (clipping can only raise a channel), filed as #1025 (related #959). Cycles recovers only 4 % (CPU) / 33 %
  (OptiX) of the caustic (no dispersion; it finds the 4 degree sun only by chance paths).
- **Open.** `floor_prism_shadow` is 8 % lower in Mitsuba than in Cycles and both Astroray legs (all three agree).

## Limits

- Mitsuba 3.9.1's `dielectric` has a constant IOR, so scene (a) uses a Python `DispersiveDielectric` (Sellmeier at the hero
  wavelength, lanes 1-3 terminated, x4 once per path at hits from outside). A BSDF cannot see throughput, so a path with a
  diffuse bounce between two prism hits is over-weighted; the floor albedo is 0.15 to keep that share small. Measured against the stock dielectric at constant IOR (8 seeds x 8192 spp):
  floor_caustic +1.4 % (z 3.1), prism_body +6.9 % (z 3.5), floor ROIs 0.0 %. So the plugin over-reads the caustic by 1-7 %: the
  plugin bias is small next to the post-#1020 Astroray caustic gaps (GPU -8 %, CPU -26 %). Not an exact estimator.
- Mitsuba rows on scene (a) are references, not a noise-per-time comparison of a spectral path tracer.
- The sun is a 4 degree disc in all engines (a delta sun is invisible to path tracers). Mitsuba's sun is in physical units
  (irradiance = Blender strength). The rectangle lamps' scale is anchored on a ROI that does not depend on the effect under
  test (lit floor vs Cycles for the medium; wall luminance vs Astroray CPU for the narrow-band lamp, since Astroray does not
  draw the lamp face), so luminance on an anchor ROI is agreement by construction.
- LuxCore and pbrt-v4 legs are follow-ups (BlendLuxCore 2.11.1 is not installed; pbrt is not built).

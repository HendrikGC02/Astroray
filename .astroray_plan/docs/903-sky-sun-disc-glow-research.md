# #903 — Sky Texture sun disc + glow vs Cycles (2026-09-25)

## Sources (no new algorithm; parity fix)
- Sky model: Blender `intern/sky/source/sky_multiple_scattering.cpp` (MIT,
  García Liñán 2022), vendored in `external/blender_sky/` (#799).
- Disc drawing: Cycles `intern/cycles/kernel/svm/sky.h` `sky_radiance_nishita`
  (Apache-2.0) — the disc is part of the background shader, so camera rays see it.
- Sun azimuth convention: measured, `814-sun-direction-convention-research.md`
  (Cycles world azimuth = 90deg - sun_rotation).

## Root causes
1. Glow azimuth. `astroray.nishita_sky(..., rot)` places its sun at world
   azimuth `rot`. The addon passed Blender's `sun_rotation` raw, while the
   dedicated sun (and Cycles) sits at 90deg - sun_rotation. The #814 scope
   correction kept the old bake on the strength of a weak gate (Preetham bake,
   brightest-column test with both peaks at the frame edge). At rotation 0 the
   glow was 90deg off: no warm glow in view, bluer sky.
2. Disc invisible. The disc is a dedicated DistantLight (sharp shadows, #799);
   dedicated lamps are skipped for camera rays (pkg181, lamp parity). Cycles'
   disc is background, so it must be camera-visible.

## Fix
- Addon passes `pi/2 - sun_rotation` to `nishita_sky`.
- `Light::cameraVisible` (CPU) / `GDedicatedLight::cameraVisible` (GPU);
  `add_sun_light_dedicated(camera_visible=True)` for the sky sun only. Bounce-0
  hits count as background (PASS_ENVIRONMENT, GPU transparent-film coverage).
  Regular Blender lamps are unchanged.

## Measured (Blender 5.2 Cycles CPU vs Astroray, MS sky, elev 4, size 1.2,
## alt 200 m, aerosol 1.2; world-only 90deg-FOV views, luminance ratio)
| view | before | after |
|---|---|---|
| toward sun (disc excluded), rot 0 | 0.40 | 0.993 |
| toward sun, rot 60 | 1.19 | 0.993 |
| sun + 90deg, rot 0 / 60 | 1.19 / 1.38 | 0.998 |
| anti-sun, rot 0 / 60 | 0.84 / 0.94 | 0.998 |

Disc: Cycles centre (2.19e5, 1.01e5, 1.70e4), limb-darkened mean
(1.81e5, 8.4e4, 1.4e4); Astroray uniform disc = 0.8 x nishita_sun mean
= (1.77e5, 8.1e4, 1.4e4). Evidence: `astra_run/batchU/f903/`.

## Not covered
- ReSTIR-DI bounce-0 path passes no dedicated lights (disc invisible there).

## Follow-ups landed on this branch
- `multiwavelength_path_tracer`: camera rays see camera-visible lamps (unit
  weight, NEE on or off), matching the GPU.
- #905: Preetham fallback bake glow moved to 90deg - R. The pkg256 Cycles A/B
  now aims the camera at the true sun (the corpus camera faced azimuth 90 with
  the sun at -25, out of frame); exposure constant recalibrated 1/1766 -> 1/1333
  on the full-sky mean (bands: upper 1.40, horizon 0.60, full 1.00; sun
  column 120 vs 120 of 240).

# #852 AREA light spread — research note

**Symptom.** lighting_studio AREA booth (RECTANGLE 1.3 x 0.32 m, 140 W, spread 45 deg,
rot X 50 deg) rendered 0.17x Cycles.

**Two causes.**
1. Convention: Blender `light.spread` is the FULL angle; Cycles uses
   `half_spread = 0.5 * spread` (`intern/cycles/scene/light.cpp`, Apache-2.0).
   The addon passed the full angle into `AreaLight(spread)`, a half-angle.
2. Model: Astroray only hard-clipped the cone. Cycles scales radiance by the
   soft-box grid attenuation (`intern/cycles/kernel/light/area.h`
   `area_light_spread_attenuation`, Apache-2.0; Blender D10594):
   `f(a) = max(tan h - tan a, 0) * N`, `N = 1/(tan h - h)` (`3/h^3` for h <= 0.05).

**Derivation (power preservation).** Emitted power of a lamp with radiance L f(a):
`L A int_hemi f cos a dw = 2 pi L A N int_0^h (tan h - tan a) cos a sin a da`.
The integral is `tan h sin^2 h / 2 - (h/2 - sin 2h / 4) = (tan h - h)/2`, so the
power is `pi L A N (tan h - h) = pi L A`, the Lambertian value. Checked numerically
(trapezoid, h = 45/22.5/5/1 deg: 1.0000). Hence `power()`, light selection and the
uniform-area NEE pdf stay as they are; f > 0 exactly on the existing hard-cone
support (a < h), so NEE pdf, BSDF-hit pdf and radiance keep matching support.
On-axis boost f(0) = tan h / (tan h - h): 4.66 at h = 45, 19.3 at h = 22.5.

**Implementation.** `include/astroray/area_spread.h` (host+device), used by
`AreaLight::sampleLi`/`intersect` (CPU) and `gpu_dedicated_sample`/
`gpu_dedicated_intersect` (GPU). Addon halves `light.spread`. The binding default
spread changed 1.0 rad -> pi/2 (Lambertian), since a 1.0 rad default would now
imply a 2.8x soft-box.

**Not ported.** Cycles clamps the sampled rectangle to the spread-visible region
(`area_light_spread_clamp_light`); that is variance reduction only. Uniform-area
sampling stays unbiased.

Tests: `tests/test_issue852_area_spread.py`. Evidence: `astra_run/batchU/u852/`.

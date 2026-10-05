# #946 -- Nishita sky sun disc profile (2026-10-06)

## Source (Apache-2.0, ported as math)
Blender/Cycles `intern/cycles/kernel/svm/sky.h`, `sky_radiance_nishita` (SPDX Apache-2.0):

```
y     = (dir_elevation - sun_elevation) / angular_diameter + 0.5
limb  = 1 - 0.6 * (1 - sqrt(1 - (sun_dir_angle / half_angular)^2))
xyz   = mix(pixel_bottom, pixel_top, y) * sun_intensity * limb     // inside the disc
```
`pixel_bottom/top` = the vendored `precompute_sun` pair (`astroray.nishita_sun`).

## Root cause
The addon fed the dedicated sun lamp the MEAN of bottom/top times 0.8 (limb mean) as a
uniform disc. Mean flux is right (disc sum within 1-2 % of Cycles) but at 4 deg elevation the
lower limb is much redder/dimmer than the upper one (bottom/top luminance ~2-3x), and the
corpus ROIs sit on the disc's lower half (`sun_disc`) and straddle its upper half
(`sun_glow`), so the uniform disc read 1.16/1.28/1.58 (r/g/b) and 0.93/0.90/0.86.

## Fix
`DistantLight::setDiscProfile(bottomRGB, topRGB)`: relative colours `pixel_{bottom,top}/lum(mean)`
(mean = the lamp colour, so NEE energy is unchanged). Rays that hit the lamp (camera and BSDF
rays, CPU `intersect`, GPU `gpu_dedicated_intersect` + advance lamp pass) see
`lerp(up(bottom), up(top), y) * limb / 0.8` (0.8 = disc-area mean of `limb`).
World +Z is up (Blender world). NEE keeps the uniform mean.

## Measured (CPU seed 278, 64 spp, v2_sky_sun vs Cycles 5.2 1024 spp)
| ROI | before r/g/b/L | after r/g/b/L |
|---|---|---|
| sun_disc | 1.158/1.280/1.581/1.234 | 0.9999/0.9990/0.9963/0.9994 |
| sun_glow | 0.926/0.904/0.864/0.912 | 0.9998/1.0003/0.9981/1.0001 |

## Findings left open
- NEE irradiance: a profiled disc delivers ~1.3 % more ground irradiance than the uniform mean
  at a 4 deg sun (the brighter upper limb has the larger cos(theta)); `ground_foreground`
  0.974 -> 0.987 when `sampleLi` applies the profile (tried on CPU, reverted: GPU NEE is the
  REG-254-saturated shade kernel, so a CPU-only change would split CPU/GPU parity).
- `chrome_reflection` ROI is a stone pillar base (r 0.81 / g 0.91 of Cycles, unchanged at 512 spp)
  plus a chrome rim (0.99); the sun disc is not in it. Residual warm-light transport gap.
- Cycles hides the part of the disc below the horizon (`dir_elevation > earth_intersection_angle`);
  not modelled (irrelevant at >= half-diameter elevation).

# #814 — Nishita sun direction convention vs Cycles (Batch L, 2026-09-15)

## Source (Apache-2.0, vendorable)
Blender/Cycles `intern/cycles/kernel/svm/sky.h` (`sky_radiance_nishita`) and the
helpers in `intern/cycles/util/math_float3.h`:

```c
// sky.h
float3 geographical_to_direction(float lat, float lon) {
  return spherical_to_direction(lat - M_PI_2_F, lon - M_PI_2_F);
}
// in sky_radiance_nishita:
const float3 sun_dir =
    spherical_to_direction(sun_elevation - M_PI_2_F, sun_rotation - M_PI_2_F);

// util/math_float3.h (standard textbook spherical->cartesian)
float3 spherical_to_direction(float theta, float phi) {
  float sin_theta = sinf(theta);
  return make_float3(sin_theta*cosf(phi), sin_theta*sinf(phi), cosf(theta));
}
float2 direction_to_spherical(float3 dir) {
  return make_float2(acosf(dir.z), atan2f(dir.y, dir.x));
}
```

## Derivation
With E = sun_elevation, R = sun_rotation:
- sin(E - pi/2) = -cos E ; cos(E - pi/2) = sin E
- cos(R - pi/2) = sin R ; sin(R - pi/2) = -cos R

`sun_dir` (Cycles, world Z-up, pointing TOWARD the sun):
```
sun_dir = ( -cosE*sinR,  cosE*cosR,  sinE )
azimuth(atan2(y,x)) = atan2(cosE*cosR, -cosE*sinR) = R + 90 deg
```

Astroray today (blender_addon/__init__.py setup_world, MS/SS branch, and
sky_bake.sun_disc_params) places the sun POSITION at:
```
sun_pos = ( cosE*cosR, cosE*sinR, sinE )   =>  azimuth = R
```
=> **constant +90 deg azimuth offset** vs Cycles (a rotation, NOT a mirror).

## Fix (apply consistently so glow + disc stay coincident, now matching Cycles)
1. Sun-light TRAVEL direction (= -sun_dir): `( cosE*sinR, -cosE*cosR, -sinE )`.
2. `src/world/nishita_sky.cpp` beta: rotate the glow placement by the same +90.
   Using azimuth(D_sun) = model_az - beta, target azimuth R+90:
   - SS  (model_az 0):   beta = -R - pi/2   (was -R)
   - MS  (model_az pi):  beta = pi/2 - R    (was pi - R)
   i.e. uniformly `beta_new = beta_old - pi/2`.
3. `sky_bake.sun_disc_params` (Preetham/Hosek legacy disc) direction likewise.

## EMPIRICAL CORRECTION (Blender 5.2 Cycles, measured 2026-09-15)
The analytic atan2 above did NOT survive the render A/B. Headless Blender 5.2
Cycles top-down ortho pole-shadow renders (scratchpad cycles_visual.py, view
transform Standard, exposure -5, RGB axis markers to calibrate +X=image-right,
+Y=image-up), sun_elevation 15 deg:
  - sun_rotation   0 deg: all shadows point world -Y  => sun at +Y  (az  90)
  - sun_rotation  90 deg: shadows point world -X      => sun at +X  (az   0)
  - sun_rotation 225 deg: shadows point +X,+Y (up-right)=> sun at -X,-Y (az 225)
=> **Cycles sun world azimuth = 90 deg - sun_rotation** (a REFLECTION, not the
+90 rotation the raw atan2 predicted -- Blender's world/background applies an
extra X-flip relative to the bare sky_radiance_nishita sun_dir). Confirmed world
sun direction (toward sun, Z-up):
```
sun_dir_world = ( cosE*sinR, cosE*cosR, sinE )     azimuth = 90 - R
travel(-)     = (-cosE*sinR,-cosE*cosR,-sinE )
```
Astroray was at ( cosE*cosR, cosE*sinR, sinE ) => azimuth R.

## Fix (all consistent; glow + disc coincide, now matching Cycles)
1. __init__.py setup_world MS/SS branch sun-light direction:
   `[-(ce*sin R), -(ce*cos R), -se]`.
2. sky_bake._sun_direction (Preetham/Hosek bake glow AND sun_disc_params):
   return `(ce*sin R, ce*cos R, se)`.
3. src/world/nishita_sky.cpp beta (glow world az = model_az - beta, target 90-R):
   - SS (model_az 0):  beta = sun_rotation - pi/2   (was -sun_rotation)
   - MS (model_az pi): beta = sun_rotation + pi/2   (was pi - sun_rotation)

NOTE: fix items 2 and 3 above were an OVER-CORRECTION — see the scope
correction below. The bake was already correct; only the raw-world sun LIGHT
(item 1, plus sky_bake.sun_disc_params' direction field) needed changing.

## SCOPE CORRECTION (2026-09-18) — fix the sun LIGHT only, not the bake
Building the first attempt and running the pre-existing LIVE-Cycles gate
`test_pkg256_sky_bake.py::test_sun_column_matches_cycles` FAILED (bake_col
26->239 vs Cycles 41): rotating the bake moved the sky glow to the WRONG side.
Reason: the baked sky is loaded via `load_environment_map(blender_convention=
True)`, whose coord swap ALREADY maps the bake's authoring azimuth onto Cycles'
world azimuth — so the OLD bake was correct and must not be touched. Only the
dedicated distant sun is a RAW WORLD vector that bypasses that swap. Final fix =
sun-LIGHT direction only (world dir toward sun = (cosE sinR, cosE cosR, sinE)):
blender_addon/__init__.py MS/SS branch + sky_bake.sun_disc_params' `direction`
field. src/world/nishita_sky.cpp beta and sky_bake._sun_direction reverted to
origin/main.

## VERIFIED (direct Astroray CPU render vs Cycles, 2026-09-18)
scratchpad/astro_sun_probe.py renders a top-down sphere scene with the fixed
dedicated sun (no Blender, set_use_gpu(False)); RGB marker spheres calibrate
+X=image-right, +Y=image-up.

| sun_rotation | Cycles sun az | Astroray sun az | match |
|--------------|---------------|-----------------|-------|
| 0   deg | 90  (+Y)  | 90  (+Y)  | yes |
| 90  deg | 0   (+X)  | 0   (+X)  | yes |
| 225 deg | 225 (-X-Y)| 225 (-X-Y)| yes |

(Superseded as primary evidence by the addon A/B below — the direct render did
not exercise the addon export path and was not like-for-like with Cycles.)

## DEFINITIVE — Blender addon A/B (staged CUDA addon, device CPU, 2026-09-19)
ONE scene (grey ground + tall pole + RGB marker cubes, top-down ortho) rendered
by BOTH Cycles CPU and the STAGED Astroray addon (`bl_ext.user_default.astroray`,
device CPU) at the same resolution / view transform Standard / exposure, sun
elevation 30 deg. Scripts: scratchpad/blender_ab_814.py (render) +
scratchpad/measure_814.py (radial matched-filter pole-shadow azimuth on the
linear EXRs). Exercises the exact `__init__.py` Nishita export path the owner
uses.

Item 1 — pole-shadow azimuth (sun_az = shadow_az - 180):

| sun_rotation | Cycles sun az | Astroray sun az | target (90-R) | |Astro-Cyc| |
|--------------|---------------|-----------------|---------------|------------|
| 0   deg | 92 | 88 | 90  | 4 deg |
| 90  deg |  2 |  2 | 0   | 0 deg |
| 225 deg | 222| 222| 225 | 0 deg |

Astroray addon shadows match Cycles within 4 deg at every rotation.
Evidence: test_results/batchL/814_addon_ab_contact_sheet.png (Cycles top,
Astroray bottom; yellow = measured shadow azimuth).

## Item 2 — irradiance re-measure (same linear EXRs, rot=0, matched ROIs)
Tight shadow ROI on the pole-shadow streak + sunlit ROI on open ground, SAME
pixel rectangles in both engines (drawn: roi_{cyc,astro}_rot0.png):
- Cycles   sunlit lum 12.05, shadow lum 5.85 -> sunlit/shadow 2.06
- Astroray sunlit lum 11.62, shadow lum 6.20 -> sunlit/shadow 1.87
- Sunlit radiance ratio Astroray/Cycles per channel R,G,B = 0.972, 0.962, 0.950
  (lum 0.964) -> within ~4%, so the "warm brown vs neutral grey" tint the lead
  flagged was the MISSING sky in the direct render, not a real divergence.
- Analytic E_sun (Nishita, elev 30, sun_size 0.009512): L_disc RGB
  [2.63e6, 2.16e6, 1.53e6], Omega 7.11e-5 sr, E_sun RGB [186.8, 153.2, 109.0]
  (direct-normal irradiance; absolute scale is model-defined and BOTH engines
  apply it — they agree to ~4%).

### VERDICT for #814 (posted on the issue)
The sun-DIRECTION bug is FIXED: the dedicated sun light now points at Cycles'
world azimuth (90 - sun_rotation), shadows match Cycles within 4 deg at 0/90/225
through the real addon. The prior gate-2 "~1.48x over-bright disc" is CONFIRMED
INVALID — it compared different ground patches because the shadows were
90-mirrored. Re-measured on matched ROIs the sunlit radiance is 0.96x Cycles per
channel and direct:diffuse (sunlit/shadow) is 1.87 vs Cycles 2.06 (~9%), i.e. NO
material divergence — well inside the physics-first cross-check band, NOT a bug.

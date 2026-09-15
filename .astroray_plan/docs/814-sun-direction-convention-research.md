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

## Gate
The self-consistency test (glow == disc) must still pass with updated expected
values. The decisive external gate is the headless Blender 5.2 Cycles-vs-Astroray
A/B (pole shadow azimuth at sun_rotation 0/90/225): a constant offset (this
model) vs a mirror is distinguished by whether (astro_az - cycles_az) is constant
across rotations. Verify before finalizing — Blender 5.2's shipped convention is
the ground truth, this note is the analytic prediction.

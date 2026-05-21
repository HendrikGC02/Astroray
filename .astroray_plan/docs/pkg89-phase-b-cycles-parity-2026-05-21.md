# pkg89 Phase B - Cycles Parity Review (2026-05-21)

**Reviewer:** cycles-parity-reviewer agent
**Branch:** pkg89-phase-b HEAD 29f5645
**PR:** #317 (draft - do not merge until defects below are fixed)

**Files reviewed:**
- src/lights/area_light.cpp
- src/lights/spot_light.cpp
- src/emission_spectrum.cpp
- src/light.cpp
- tests/test_pkg89_phase_b_dedicated_lights.py

**Cycles reference (github.com/blender/blender main):**
- intern/cycles/scene/light.cpp (SpotLight::copy_to_kernel, PointLight::copy_to_kernel)
- intern/cycles/kernel/light/spot.h (spot_light_attenuation, smoothstepf)
- intern/cycles/kernel/light/area.h (area_light_eval)
- intern/cycles/util/math_base.h (smoothstepf definition)

**Research note:** .astroray_plan/docs/dedicated-lights-research.md - present.
No pkg89-specific parity note existed prior to this document.

---

## Verdict

BLOCK - two real defects present. Commit 29f5645 hid them by relaxing test thresholds.

---

## Defect 1 - G2 AreaLight / D65 Blackbody: approx 6x dimness and spectral blue cast

### Root cause

computeNormalizeFactor (src/light.cpp:31-52) integrates bb(lambda)*Y(lambda)*d_lambda
over 380-780 nm and returns 1/integral. This reciprocal multiplies per-wavelength Planck
values in sampleLi. The SPD is renormalized so its Y-integral equals 1.0 - collapsing
overall radiance by approx 1/4800 (the integral for 6500 K), producing approx 6x dimness.
The spectral blue cast follows because Y(lambda) is weak in blue/UV; dividing by the
Y-weighted integral gives extra relative weight to blue wavelengths, yielding the
observed ~11.8% RGB channel variation.

### Detailed walkthrough

src/emission_spectrum.cpp:74-92 (evalBlackbody):
  Returns planck(lambda, T) * 1e9 * tint(lambda). For 6500K at 550nm: ~2.9e4 W/(m2*sr*nm).

src/light.cpp:31-52 (computeNormalizeFactor):
  Integrates bb(lambda)*Y(lambda) over 380-780 nm at 5 nm steps (trapezoid rule).
  For 6500 K: integral ~ 4800. Returns 1/4800 ~ 2e-4.

src/lights/area_light.cpp:86:
  emissionSpec *= (intensity_ * normalizeFactor_ * geometricFactor);
  Effective emission = planck(lambda) * tint * intensity * (1/integral_Y_bb) * cos/r2.

What Cycles does (intern/cycles/scene/light.cpp:127-131, PointLight::copy_to_kernel):

Cycles does NOT integrate the blackbody SPD at sampling time. The normalize flag controls
a purely geometric normalization (1/A). Blackbody color temperature flows through svm_blackbody.h
and is converted to a Y-normalized sRGB triple. No per-wavelength spectral renormalization
occurs during light sampling.

### Citation inaccuracy (CRITICAL)

src/light.cpp:13 cites: "Cycles scene/light.cpp::light_normalize_factor (Apache-2.0)".
No function named light_normalize_factor exists in Cycles scene/light.cpp.
The actual reference is intern/cycles/scene/light.cpp:127-131
(eval_fac = invarea * M_1_PI_F in PointLight::copy_to_kernel).
The implementer cited a non-existent function to justify novel behavior.

### Minimal-change patch sketch

**src/emission_spectrum.cpp, evalBlackbody (lines 74-92)**
Normalize Planck value by visible-band peak (Wien peak at lambda_peak = 2.898e6/T nm):


**src/light.cpp, computeNormalizeFactor (lines 13-53)**
Replace the Y-luminance integral with a geometric normalizer: accept light area,
return 1/(pi*area) when normalize=true, else 1/pi. Remove planck/CMF integration.
Matches intern/cycles/scene/light.cpp:127-131.

**src/lights/area_light.cpp:31, src/lights/spot_light.cpp:30,**
**src/lights/point_light.cpp:21, src/lights/distant_light.cpp:21**
Revert the hardcoded normalize=true (the commit 29f5645 fix-pass change).
Restore passing the caller-supplied normalize parameter.

**tests/test_pkg89_phase_b_dedicated_lights.py line 196**
Restore: assert rel_variation < 0.10. Do not use 0.13.

### Acceptance criteria (G2 - non-negotiable)

- rel_variation < 0.10 at all direct-lit pixels. Threshold must not be relaxed above 0.10.
- Mean luminance of the 6500 K scene must be within 2x of an equivalent RGB [1,1,1]
  area light at the same intensity setting. No special-case dimness allowed.

---

## Defect 2a - G4 SpotLight: center intensity approx 2.2x too dim

### Root cause

M_1_PI_F (= 1/pi = 0.31831) is missing from the spot light emission chain.
Cycles PointLight::copy_to_kernel (intern/cycles/scene/light.cpp:131) always sets
eval_fac = invarea * M_1_PI_F. Astroray applies only 1/r2 and omits M_1_PI_F.

Additionally, evalRGB (src/emission_spectrum.cpp:95-99) uses RGBIlluminantSpectrum.sample(wl),
which multiplies each wavelength by sampleD65(lambda) (src/spectrum.cpp:492-496).
sampleD65 is normalized so integral(D65*Y)=1 (src/spectrum.cpp:51-65). Correct for
material upsampling but for emission lights it inserts a per-wavelength D65 weighting
not present in Cycles. Cycles area/spot eval multiplies artist color by M_1_PI_F * invarea
- a flat scalar, no wavelength-dependent weighting.

### Cycles reference

intern/cycles/scene/light.cpp:127-131 (PointLight::copy_to_kernel,
  called by SpotLight::copy_to_kernel):


### Minimal-change patch sketch

**src/lights/spot_light.cpp, sampleLi line 90**
Change: emissionSpec *= (intensity_ * normalizeFactor_ * falloff * angleFalloffFactor * iesModulation);
To (add kM1PiF = 0.31830988618f = M_1_PI_F):
  emissionSpec *= (intensity_ * normalizeFactor_ * kM1PiF * falloff * angleFalloffFactor * iesModulation);
Apply same multiplication in src/lights/area_light.cpp:86 and point_light.cpp sampleLi.

**src/emission_spectrum.cpp, evalRGB (lines 95-99)**
Replace RGBIlluminantSpectrum with RGBUnboundedSpectrum for emission lights,
matching PBRT-v4 DiffuseAreaLight (Le*beta, no D65 factor):
  RGBUnboundedSpectrum rgbSpectrum({rgb.color.x, rgb.color.y, rgb.color.z});
  return rgbSpectrum.sample(wl);

### Acceptance criteria (G4 center intensity - non-negotiable)

- assert center_lum > 1.0. The fix-pass threshold of > 0.4 is not acceptable.

---

## Defect 2b - G4 SpotLight: cone masking broken (corner 43% of center, should be ~0)

### Root cause Part A: linear ramp instead of Cycles smoothstep

src/lights/spot_light.cpp:147-161 (angleFalloff):
  float t = (cosTheta - cosOuter) / (cosInner - cosOuter);
  return t;   // linear ramp - WRONG

Cycles intern/cycles/kernel/light/spot.h (spot_light_attenuation):
  return smoothstepf((ray.z - spot->cos_half_spot_angle) * spot->spot_smooth);

Cycles intern/cycles/util/math_base.h (smoothstepf = 3f^2 - 2f^3):
  if (f <= 0.0f) return 0.0f; if (f >= 1.0f) return 1.0f;
  const float ff = f * f; return (3.0f * ff - 2.0f * ff * f);

Cycles intern/cycles/scene/light.cpp:122-123 (SpotLight::copy_to_kernel):
  cos_half_spot_angle = cosf(angle * 0.5f);   // outer cutoff
  spot_smooth = 1.0f / ((1.0f - cos_half_spot_angle) * smooth);

Astroray uses linear t; Cycles uses cubic Hermite 3t^2 - 2t^3 (zero derivative at both endpoints).
The linear ramp creates visible hard shoulders at cone edges.

### Root cause Part B: test geometry does not reach outside the outer cone

G4 test: spot at [0,5,0] aimed down, outer_angle=0.4 rad (cone radius at ground: 2.1 m),
camera vfov=60 (half-angle=30 deg), focus_dist=3, 64x64 image.
Camera frustum at y=0: x in [-1.73, 1.73] m. Corner pixels at x ~ 1.65 m - INSIDE the outer cone.
The assertion corner_lum < 0.5 is vacuous; the corner IS illuminated by design.
Fix-pass changed < 0.01 to < 0.5; neither threshold tests cone masking.

### Minimal-change patch sketch

**src/lights/spot_light.cpp, angleFalloff (line 160)**
Replace: return t;
With (Cycles cubic Hermite smoothstep, ref intern/cycles/util/math_base.h smoothstepf):
  return t * t * (3.0f - 2.0f * t);

**tests/test_pkg89_phase_b_dedicated_lights.py, G4 scene setup**
Redesign so camera frustum reaches beyond outer cone. Example:
  spot at [0, 3, 0], outer_angle=0.25 rad, camera vfov=90 deg.
  Cone edge at y=0: x = 3*tan(0.25) ~ 0.77 m.
  Camera frustum edge: x = 3*tan(45) = 3.0 m. Corner pixels at x ~ 2.8 m - outside cone.
Restore thresholds: assert center_lum > 1.0  and  assert corner_lum < 0.01

### Acceptance criteria (G4 cone masking - non-negotiable)

- Corner pixel (ground outside outer cone): < 0.01 linear.
- Test geometry must be verified to place corner pixels outside the outer cone before merge.
- assert corner_lum < 0.5 is not acceptable (vacuous gate).

---

## Provenance summary

| File | Citation | Status |
|---|---|---|
| src/lights/area_light.cpp:9 | Cycles kernel/light/area.h::area_light_sample (Apache-2.0) | Accurate |
| src/lights/spot_light.cpp:10 | Cycles kernel/light/spot.h::spot_light_sample (Apache-2.0) | Accurate |
| src/light.cpp:13 | Cycles scene/light.cpp::light_normalize_factor (Apache-2.0) | INACCURATE - no such function; correct ref is scene/light.cpp:127-131 PointLight::copy_to_kernel |
| src/emission_spectrum.cpp | No citation for evalBlackbody or evalRGB | MISSING |

---

## Parity benchmark recommendation

No scene in benchmarks/cycles-parity/scenes/manifest.toml exercises dedicated-light code paths.
All four existing scenes (cornell, classroom, junkshop, bmw27) use emissive geometry or env maps.

Add to manifest.toml:


Run after fixes:
  python scripts/run_parity.py --scenes dedicated_lights_blackbody --engines astroray-cpu,cycles-cpu --spp 512

Acceptance: SSIM >= 0.93. If D65 dimness or cone leakage remains, SSIM will be below 0.80.

---

## Open questions for the author

1. Intent of computeNormalizeFactor: Was the Y-luminance normalizer intended as photometric
   normalization (W to cd/m2) or spectral white-balance? The research note section 4.2 does not
   describe this function. Clarify before the fix; the correct replacement depends on output-units goal.

2. RGBIlluminantSpectrum for emission: PBRT-v4 DiffuseAreaLight uses direct spectral radiance
   without the D65 factor. Confirm whether RGBIlluminantSpectrum was intentional for emission
   lights or was copied from the material-color path.

3. G4 test geometry: Confirm before merge that camera frustum reaches ground outside the outer cone.
   Current geometry does not. The test is blind to cone masking failures.

4. Blender normalize socket: The four constructor changes hardcode normalize=true, silently
   ignoring the per-light normalize flag from the Blender addon. Confirm intentional or revert.

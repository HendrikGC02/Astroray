# pkg89 Dedicated-Light Energy Audit (2026-07-20)

**Author:** pkg89-fix agent (GAP 2 audit leg)
**Status:** AUDIT ONLY — no CPU calibration behavior was changed. This is the
evidence base for the pkg122 follow-up (dedicated-light radiometry redesign).
**Trigger:** the recorded pkg89 gap "CPU energy scale ~3x dimmer than Cycles at
equal wattage" (pkg115 texture-grid CPU leg, uniform across materials).

All measurements: Astroray **CPU**, linear output (`render(..., applyGamma=False)`),
gray Lambertian floor (albedo ρ=0.5), camera looking straight down, black
background. Built module at repo HEAD 94ae956. Scripts archived under the agent
scratchpad (`gap2_repro.py`, `gap2_area.py`, `gap2_iso.py`).

## Headline conclusion

The dedicated-light wattage→radiance conversion is **wrong**, and it is **NOT a
clean single conversion factor** — it is a structural solid-angle / pdf-measure
sampling problem in `AreaLight::sampleLi`, and it is **per-type inconsistent**
(point and area diverge in opposite directions). It is entangled with a disputed,
cross-cutting spectral-emission convention (RGBIlluminant vs RGBUnbounded) that
also affects materials / env / the reference bank. Per the "clean fix vs ambiguous
convention" branch, this was left unchanged and escalated.

## Measurement 1 — dedicated AREA light vs Cycles-calibrated geometry (the field symptom)

Harness config: AREA light, size 3×3 m, energy 300 W, height 3 m, over the floor.
Reference = the geometry emitter path (`add_area_light` → emissive `AreaLightShape`,
radiance `L_e = P/(π·A)`), which is the reference-bank Cycles-calibrated path.

| Light | measured floor radiance (mean linear) | ratio vs geometry |
|---|---|---|
| GEOMETRY area (calibrated reference) | 1.179 | 1.00 |
| DEDICATED pkg89 area (RGB white, intensity=300) | 0.154 | **0.13 (≈7.7× too dim)** |

This reproduces the field "~3× dimmer" report in the exact harness configuration
(the exact factor is scene-dependent).

## Measurement 2 — the error is SIZE-DEPENDENT (rules out a clean constant)

Same comparison, shrinking the light toward a point source (tiny + far, cos_l≈1):

| Light size | geometry/dedicated ratio |
|---|---|
| 3.0 m (harness) | 7.68× |
| 0.05 m (≈ point) | 1.40× |

The gap **collapses as the subtended solid angle shrinks**. A clean conversion
factor would be size-independent. This is the smoking gun that the defect is a
**solid-angle / pdf-measure sampling bias** in the extended-area sampling, not a
missing scalar.

## Measurement 3 — per-type INCONSISTENCY

| Dedicated light | vs analytic Cycles value `ρ·P/(4π²d²)` | direction |
|---|---|---|
| POINT (RGB white) | 3.59× | **too BRIGHT** |
| POINT (blackbody 6500K) | 14.4× | far too bright + blue cast |
| AREA (harness) | ~0.13× of calibrated geometry | **too DIM** |

Point and area scale in **opposite directions**, so no single global correction
exists. (POINT/geometry-area ≈ 0.65× in the tiny-far probe — a third value.)

## Measurement 4 — the BLACKBODY path is separately, grossly wrong

`EmissionSpectrum::evalBlackbody` returns **raw unnormalized Planck**
(`planck(λ,T)·1e9`, white-tint short-circuit) — see `src/emission_spectrum.cpp`.
The Q11 "normalize by integrated photopic luminance" the spec describes is **not
implemented**; only the geometric `1/area` normalize is applied
(`Light::computeNormalizeFactor`). Result: a 6500 K point light measured **14.4×**
the analytic value and chromatically blue (`[21.4, 19.6, 19.7]`). Any blackbody
dedicated light is wildly over-bright.

## The RGBIlluminant-vs-RGBUnbounded dispute (cross-cutting, unresolved)

Both the dedicated lights and the geometry `diffuse_light` material emit through
`RGBIlluminantSpectrum` (D65-weighted, Y-normalized):
- The 2026-05-21 cycles-parity review (`.astroray_plan/docs/pkg89-phase-b-cycles-parity-2026-05-21.md`,
  Defect 2a) says RGBIlluminant inserts a D65 weighting absent in Cycles and makes
  emission ~3× too dim; recommends `RGBUnboundedSpectrum` (PBRT-v4 DiffuseAreaLight).
- The implementer's `evalRGB` comment (`src/emission_spectrum.cpp`) says the
  opposite: switching to RGBUnbounded would drop illuminance ~3× and break G4/G5.

These are contradictory. Changing `evalRGB` is cross-cutting — it also moves
material/env emission and the 12/13 reference-bank Cycles-parity scenes. A live
headless-Cycles A/B of the exact scenes is required to arbitrate; the geometry-path
proxy used here is reference-bank-calibrated but is not a substitute.

Corroborating in-repo evidence: `tests/test_pkg89_phase_b_dedicated_lights.py`
G4 already documents the symptom — intensity was cranked 100→320 (×π) to
compensate for the `kM1PiF` factor, and the center STILL measures "~3× below
naïve theory," attributed to the RGB→Jakob-Hanika→XYZ→sRGB chain.

## Suspect code for the pkg122 implementer (AreaLight::sampleLi pdf measure)

`src/lights/area_light.cpp` `sampleLi` (the size-dependent bias lives here):

```cpp
// geometric term: area measure -> solid angle
float distSq = distance * distance;
float geometricFactor = cosFalloff / distSq;            // cos_l / d²  (folded INTO emission)
...
emissionSpec *= (intensity_ * normalizeFactor_ * kM1PiF * geometricFactor);
...
sample.pdf = 1.0f / area_;                               // AREA-measure pdf (1/A)
```

The emission carries a `cos_l/d²` (a solid-angle-measure factor) while `pdf` is an
area-measure `1/area`. Downstream NEE divides `emission_spec / (pdf+ε)` with these
in **mixed measures**. On paper the `area` cancels and it matches the geometry
path's solid-angle sampling; empirically it does not (size-dependence above), so
the bias is in this measure handling and/or the `withinSpread`/`cosTheta<=0`
rejection interacting with the area sample distribution. The correct construction
is Cycles `kernel/light/area.h::area_light_sample` (area→solid-angle pdf
`d²/(cos_l·area)`, emission = plain radiance), i.e. mirror the geometry path's
solid-angle pdf rather than folding `cos_l/d²` into the radiance with a `1/area`
pdf. Point/spot use `pdf=1` (delta) or `1/coneSA`; distant uses `1/diskSA` and
omits `kM1PiF` — each type needs re-deriving against its Cycles kernel.

## Recommendation

File pkg122 (dedicated-light radiometry redesign): re-derive each type's
wattage→radiance against Cycles `kernel/light/{point,area,spot,distant}.h` with a
live headless-Cycles A/B as the oracle; fix the blackbody normalization
(implement the Q11 photopic-luminance normalize or precompute XYZ per Cycles
`svm_blackbody.h`); resolve the RGBIlluminant-emission convention once for all
paths and re-bless the reference bank. Add a before/after energy gate keyed on the
live-Cycles numbers.

## Relationship to GAP 1 (GPU upload)

GAP 1 (this PR) uploads dedicated lights to the GPU and gates on **GPU==CPU**
parity — it faithfully mirrors whatever the CPU currently does, INCLUDING the
mis-scaling documented here. GPU==CPU parity must **not** be read as "the energy
is correct." Fixing the absolute calibration is pkg122's job; when it lands, the
GPU side inherits the fix automatically (the device mirrors the CPU sampleLi).

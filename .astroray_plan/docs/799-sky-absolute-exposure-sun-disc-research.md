# #799 part 1 — Sky absolute exposure + sun disc — Research (cite-algorithm, CLAUDE.md §6)

**Issue:** #799 (pkg256 Phase 2). **Author:** griminkel@gmail.com (Claude Opus 4.8).
**Date:** 2026-09-12. Touches `blender_addon/sky_bake.py`, `blender_addon/__init__.py`
(`setup_world`), `benchmarks/reference_corpus/sky_ab_bands.py`.

---

## 1. What we implement

Two things, both physically grounded and cited:

1. **Absolute-exposure derivation** — replace the opaque single-scene fit
   `LUM_TO_RADIANCE = 1/1766` with an explicit *decomposition* into a physics
   factor (photopic luminous efficacy) and a documented Cycles-exposure
   residual, plus a multi-point A/B that measures the residual drift.
2. **Sun disc** — add a dedicated distant sun light (`DistantLight`, angular
   diameter = node `sun_size`) so the baked Preetham sky gains a real sun disc:
   sharp shadows and correct direct-beam ground irradiance, gated on the node's
   `sun_disc` property. The disc radiance/irradiance comes from the solar-disc
   luminance and Beer-Lambert atmospheric extinction, converted through the same
   luminance→radiance bridge as the sky (mutually consistent).

## 2. Absolute exposure — the photometry

Preetham zenith luminance `Yz` is **absolute photometric luminance** in cd/m²
(= lm/(sr·m²)); the paper is a fit to measured daylight, so `Yz(T, θs)` *is* an
independent oracle for real-world sky luminance (Preetham et al. 1999 §A.6;
Perez et al. 1993). Our bake produces linear sRGB whose Rec.709 luminance
(0.2126R+0.7152G+0.0722B) equals `Y` in cd/m² before scaling.

Luminance ↔ radiance is the photopic relation
`Y[cd/m²] = K_m · ∫ L(λ) ȳ(λ) dλ`, `K_m = 683 lm/W` (CIE 1924 V(λ), maximum
luminous efficacy at 555 nm). Dividing luminance by `K_m` therefore yields an
**absolute radiance floor** (the value if all sky power were at 555 nm); the
true broadband daylight efficacy is ≈ 120 lm/W, so physical radiance is
`Y/120`.

### Why a single constant cannot reach Cycles-absolute parity (measured)

`1/1766` decomposes as:

    LUM_TO_RADIANCE = 1/1766
                    = (1/683)  ·  (683/1766)
                    = (1/683)  ·  (1/2.586)
      = [photopic K_m, PHYSICS] · [Cycles-Nishita exposure convention, UNITS CHOICE]

- `1/683` is physics (peak luminous efficacy).
- `1/2.586` (equivalently `120/1766 → 1/14.7` relative to daylight efficacy) is
  **Cycles' Nishita absolute-exposure normalisation**, measured once against the
  corpus scene. It is *not* independently derivable: Cycles' Nishita absolute
  scale lives in GPL code (`intern/cycles/kernel/svm/sky.h`, not read for
  algorithm content) and is undocumented as an SI value. This residual is a
  legitimate **units choice**, not a physics fit.

The residual is **model- and condition-dependent**, so no constant serves all
cases. Measured on `world_sky_sky` (Blender 5.2 Cycles CPU, 240×135×48,
`benchmarks/reference_corpus/sky_ab_bands.py`, `PKG256_AB_PT`):

| sky_type            | turbidity | sun elev | upper ratio_lum | horizon ratio_lum |
|---------------------|-----------|----------|-----------------|-------------------|
| MULTIPLE_SCATTERING | (aerosol) | 28°      | **1.005**       | **0.898**         |
| PREETHAM            | 2.6       | 28°      | 14.969          | 13.966            |
| PREETHAM            | 5.0       | 10°      | 7.688           | 7.540             |
| PREETHAM            | 2.0       | 60°      | 11.117          | 10.664            |

The constant is calibrated for Cycles' **Nishita** (`MULTIPLE_SCATTERING`,
ratio ≈ 1.0); Cycles' **legacy Preetham** sky_type carries a completely
different absolute scale (ratio 7.7–15). Even within one model the ratio drifts
with (turbidity, elevation). This confirms issue #799's prediction: **absolute
parity across models/conditions requires an engine-side spectral/analytic sky
lookup** (evaluate the model per-ray in the world lookup instead of a fixed bake
+ constant), which is #799's stated Phase-2 "real fix" and needs its own
architecture pass. Per the owner's 2026-09-08 physics-first rule, the bake's
absolute radiance (`Y/K`) is the physically-meaningful quantity and the Cycles
A/B is a **cross-check band**, not the acceptance criterion, for anything but
the calibrated Nishita point.

**Decision:** keep the numeric value (corpus Nishita gate stays green) but ship
it as the documented decomposition above + the measured drift table, rather than
churn a new constant that the data proves cannot do better. The extended
`PKG256_AB_PT` sweep is the diagnostic that makes the residual visible.

## 3. Sun disc — the radiometry

Cycles' Nishita renders a sun disc of angular diameter `sun_size` with
`sun_intensity` and limb darkening (`intern/sky/source/sky_nishita.cpp`
`sun_radiation`/`sun_limb_darkening`, GPL — **not read for algorithm content**;
only the *node semantics* `sun_size` = angular diameter, `sun_intensity` = scalar
multiplier, `sun_disc` = on/off are used as facts). Preetham/Perez has **no**
disc (a smooth circumsolar peak), which is the pkg256 review's "soft shadows,
cooler ground".

**Physically clean route (chosen):** a dedicated `DistantLight`
(`include/astroray/lights/distant_light.h`, already cited to Cycles
`distant.h`/PBRT-v4 `DistantLight`, Apache-2.0), *not* disc pixels baked into a
1024×512 equirect (a 0.53° disc is ~1.5 px — cannot be area-correct). The
distant light gives sharp shadows (half-angle = `sun_size/2`), is hittable
(visible disc, `DistantLight::intersect`), and delivers the direct beam as an
irradiance `S = E_sun` (the engine's `intensity_` is irradiance to a normal
surface; radiance `L = S/Ω`, `distant_light.cpp` sampleLi).

**Sun irradiance (Beer-Lambert clear-sky):**

    L_sun(m) = L_sun0 · exp(-τ · m)            solar-disc luminance [cd/m²]
    E_sun    = L_sun · Ω_disc · sun_intensity  direct normal illuminance [·efficacy]
    intensity[bake units] = E_sun · LUM_TO_RADIANCE

- `L_sun0 ≈ 1.6e9 cd/m²` — extra-atmospheric solar-disc luminance (measured
  solar constant; textbook, e.g. IES Lighting Handbook; ≈1.6–2.0×10⁹ cd/m² at
  the surface for a high clear sun).
- `Ω_disc = 2π(1 − cos(sun_size/2))` — disc solid angle (≈ 6.8e-5 sr for 0.53°).
- `m = 1/max(sin(elevation), ε)` — relative optical air mass (plane-parallel;
  Kasten-Young is the refinement, not needed for a floor).
- `τ` — broadband optical depth, turbidity-scaled: `τ = 0.10 + 0.045·(T−2)`
  (clear T≈2 → τ≈0.10; hazy T≈6 → τ≈0.28). Beer-Lambert attenuation is the
  standard clear-sky direct-beam model (Preetham 1999 §A.3 uses the same
  `exp(-optical_depth · m)` form for the attenuated solar spectrum; Bird &
  Riordan 1986 SPCTRAL2).
- Converting through the **same** `LUM_TO_RADIANCE` as the sky keeps the sun and
  sky in one exposure system; the sun's absolute level therefore inherits the
  sky's single-point Nishita calibration (documented, same status as the sky
  fit).

**Sun colour:** the direct beam reddens at low sun (Chappuis/Rayleigh). We take
the disc colour from the baked sky value at the sun direction (warm near the
horizon, consistent with our own sky), normalised to unit luminance so `E_sun`
sets the magnitude. This avoids inventing a second spectral solar model.

**Dropped (named in the warning):** limb darkening (the `DistantLight` disc is
uniform — Hestroffer & Magnan 1998 profile is a documented non-goal for the
floor); `sun_size`, `sun_intensity`, `sun_disc` are now **honoured** and leave
`DROPPED_SOCKETS`.

## 4. Sources

- Preetham, Shirley, Smits, "A Practical Analytic Model for Daylight", SIGGRAPH
  1999 (§A.3 attenuated solar spectrum, §A.6 zenith luminance). Appleseed
  `preethamenvironmentedf.cpp` (MIT) — Perez constant verification (pkg256).
- Perez, Seals, Michalsky, "All-weather model for sky luminance distribution",
  Solar Energy 1993.
- CIE 1924 photopic V(λ), `K_m = 683 lm/W` (CIE 018:2019).
- Bird & Riordan, "Simple solar spectral model for direct and diffuse
  irradiance", J. Climate Appl. Meteorol. 1986 (SPCTRAL2, Beer-Lambert direct
  beam).
- Solar-disc luminance ≈ 1.6×10⁹ cd/m²: IES Lighting Handbook; standard
  photometry.
- `include/astroray/lights/distant_light.h` (Astroray) — cited to Cycles
  `kernel/light/distant.h` + PBRT-v4 `lights.cpp::DistantLight` (Apache-2.0).
- Cycles `sky_nishita.cpp` / `svm/sky.h` (GPL) — **node semantics only**
  (`sun_size`/`sun_intensity`/`sun_disc`), NOT read for algorithm content.

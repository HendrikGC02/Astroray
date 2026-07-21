# Defect 4 — RGB emission-convention adjudication: reference research + citations

**Author:** architect (arch/pkg142-defect4)
**Date:** 2026-07-21
**Owner directive (verbatim):** "What ever is best and used by other renderers, your call."
**FINAL DECISION (2026-07-21, supersedes all below): KEEP `RGBIlluminant` (D65).**
The D65-weighted illuminant lift is **required and correct** for Astroray's
D65-referred spectral pipeline; the "switch to RGBUnbounded" premise was a
misattribution. Revert PR #511; net code change NONE. The residual offset is
re-attributed to a new investigation (pkg146). Details in the pkg142 spec's
✅ FINAL ADJUDICATION; the arc is summarized in the Final Adjudication section
immediately below.

*(Historical decision, now superseded: "switch RGBIlluminant → RGBUnbounded +
`1/CIE_Y_integral` anchor.")*

---

## Final Adjudication (2026-07-21, post-regate `790eb9e`) — the D65 factor's THREE roles

The regate (RGBUnbounded + explicit anchor) **fixed the units** (suite 68→6) but
exposed a **new ~30% R-channel excess / pink renders** vs neutral Cycles (R 1.29–1.37,
G 1.028–1.097, B 0.996–1.071). Root cause: the `· sampleD65(λ)` factor carried **three**
roles, not two:

1. **Units anchor** `1/CIE_Y_integral` (the ~116×, fixed by the explicit anchor).
2. **White-point adaptation E→D65** (the ~30% R-excess). The unweighted JH sigmoid for
   white is near-flat = **illuminant E** (≈(0.333,0.333)); the spectral→RGB path is
   **D65-referred** (standard sRGB matrix + `data/spectra/rgb_to_spectrum_srgb.coeff`).
   E-white through a D65 matrix is pink: `XYZ(1,1,1) → sRGB (1.205, 0.948, 0.909)`,
   **R/G ≈ 1.27** — matching the measurement. The D65 lift makes white emit **D65-white**
   → neutral, like Cycles.
3. A small residual tilt, subsumed by (2).

`RGBUnbounded` is a **reflectance/HDR-value** upsampler (dimensionless, E-white). A
**spectral** renderer's **emission** needs an **illuminant-referred** lift for roles 1+2.
**pbrt-v4 (`SpectrumType::Illuminant`) and Mitsuba 3 (`srgb_d65`) both do exactly this,
for white preservation** — it is the standard construction, not a pbrt-vs-Cycles dispute
(Cycles sidesteps it only by being RGB-native). Option (b) (explicit E→D65 adaptation on
a flat sigmoid) = multiply by `D65/E ≈ D65` = `RGBIlluminant` again. So **keep
`RGBIlluminant`**.

The original "+7–16% offset" premise was a misattribution: `RGBIlluminant` renders
neutral + anchored, and the **pkg139 oracle rows are 0.96–1.01 without pkg142** → the
offset is scene/type-dependent, not the lift. Re-attributed to **pkg146** (lead: the
pkg139-vs-pkg122 oracle discrepancy).

**Postmortem:** one symbol did three jobs; each fix peeled one layer and exposed the next
(units → white point). Lesson: emission needs an illuminant-referred lift; a reflectance
upsampler is the wrong category for a light; and validate a convention change against a
**neutral-white render**, not a scalar brightness ratio.

---

## Correction (2026-07-21, post-hardware-failure) — units vs shape

The first version of this note (and pkg142) said "switch to `RGBUnbounded`" full
stop. That carried a **category error**: it treated the `· sampleD65(λ)` factor as
**only** a chromaticity tilt, when it was doing **two** jobs.

**Two-role decomposition of `· sampleD65(λ)` in `RGBIlluminantSpectrum::sample`:**

1. **Shape (chromaticity):** the D65 spectral *tilt* — the ~10% daylight-white
   imprint that diverges from Cycles' RGB-native scaling. **Removing this is
   correct** (the Cycles-parity argument in §3–§4 stands).
2. **Magnitude (units):** a scalar **photometric anchor ≈ `1/CIE_Y_integral =
   1/116.66`** (1964 10° observer). Astroray's `sampleD65` is normalized so
   `∫ sampleD65·ȳ dλ = 1` (`src/spectrum.cpp:49-77`), so the multiply also *scales*
   the emission onto the toXYZ/luminance units. `RGBUnbounded` is pbrt's
   **reflectance** upsampler — **dimensionless, no photometric anchor** — so
   swapping the class dropped **both** roles.

**Consequence (measured):** PR #511 HW-verified at **~116× uniform brightness**
(not the ~10% tilt predicted). `116 ≈ CIE_Y_integral` — the missing anchor is the
smoking gun. A flat unit reflectance integrates in luminance to `∫ȳ dλ ≈ 116.66`
instead of `1`.

**Corrected fix:** `RGBUnbounded` **chromaticity + `× 1/cieYIntegral()`** on CPU and
GPU — exactly pbrt-v4's `SpectrumToPhotometric` reduced to a constant for a white
emission. Direction (drop the tilt) unchanged; class choice corrected (add the
anchor). Revised expected effect: **tilt-only**; the live-Cycles oracle
`[0.97,1.03]` is still the gate.

**Lesson:** when a change removes/replaces a spectral factor, decompose it into
**shape × magnitude** and account for both — a units constant can hide inside a
factor named for its shape (`Illuminant`/`Unbounded`/`Albedo`). A uniform,
large, integer-ish blow-up is a units/normalization bug (here literally
`CIE_Y_integral`), never a chromaticity tilt. And a fallback clause must model the
*mechanism* and *magnitude* it guards against: this note's §5 fallback named the
right remedy (`SpectrumToPhotometric`) but anticipated a −3% undershoot when the
real trigger was +11,600%.

---

## 1. The question

After pkg122 (PR #500) fixed the per-type radiometry (Defects 1–3: area
mixed-measure pdf, point `1/π`→`1/(4π)`, blackbody photopic normalization), the
live headless-Cycles oracle still measures **all four dedicated-light types
1.07–1.16× brighter than Cycles at equal wattage** on a gray Lambertian floor.
Decoupled pure-Lambertian analytic checks are 0.99×, so the residual is **not**
radiometry — it is specifically how an RGB emission color is *lifted to a
spectrum* in the spectral integrator. Astroray's RGB emission path is:

`EmissionSpectrum::evalRGB` → `RGBIlluminantSpectrum(rgb).sample(wl)`
(`src/emission_spectrum.cpp:187-191`, `src/spectrum.cpp:475-498`).

`RGBIlluminantSpectrum::sample` computes, per wavelength:

```
s[i] = scale_ * sigmoid(rsp_, λ_i) * sampleD65(λ_i)      // scale_ = 2·max(rgb)
```

where `sampleD65(λ) = rawD65(λ) / ∫ rawD65·ȳ dλ` — the D65 SPD **normalized to
unit photopic luminance** (`src/spectrum.cpp:49-77`). This is a faithful mirror of
pbrt-v4's `RGBIlluminantSpectrum`.

The **only** structural difference between `RGBIlluminantSpectrum` and
`RGBUnboundedSpectrum` in Astroray is the `* sampleD65(λ)` factor
(`src/spectrum.cpp:451-473` vs `475-498`). `RGBUnbounded` is
`scale_ · sigmoid(rgb/scale_)` — the same Jakob-Hanika reflectance lift the gray
floor **albedo** already uses (`RGBAlbedoSpectrum`), just with the magnitude
factored back in. So the fork is precisely: **does emission carry a D65 illuminant
chromaticity, or is it a plain reflectance-style lift symmetric with the albedo
path?** *(Correction: the `sampleD65` factor is not **only** chromaticity — it also
carries the `1/CIE_Y_integral` photometric anchor; the fork below decides the
chromaticity, and the anchor must be re-added explicitly. See Correction above.)*

---

## 2. What the reference renderers actually do

### pbrt-v4 (spectral) — RGBIlluminant, D65-weighted. **License: Apache-2.0** (verified `LICENSE.txt`).

- `RGBIlluminantSpectrum::Sample` = `scale * rsp(λ) * illuminant->Sample(λ)`,
  `illuminant = &cs.illuminant` (= D65 for the sRGB color space).
  Source: `src/pbrt/util/spectrum.h`.
- `DiffuseAreaLight::Create` parses emission as
  `GetOneSpectrum("L", …, SpectrumType::Illuminant, …)` → **`RGBIlluminantSpectrum`**,
  and additionally does `scale /= SpectrumToPhotometric(L)` (a photometric
  self-normalization). Source: `src/pbrt/lights.cpp`.
- `RGBUnboundedSpectrum::Sample` = `scale * rsp(λ)` (**no illuminant**). pbrt uses
  it for unbounded/HDR *values* where an illuminant assumption is not wanted.
  Source: `src/pbrt/util/spectrum.h`.

So pbrt's **light emission convention is RGBIlluminant** (D65). Astroray currently
matches pbrt here. The audit's earlier note that RGBUnbounded is "PBRT-v4
DiffuseAreaLight" is **incorrect** — pbrt lights use `SpectrumType::Illuminant`.

### Mitsuba 3 (spectral) — D65 illuminant for emitters. **License: BSD-3-Clause** (compatible).

Mitsuba's docs state D65 is "the default emission spectrum used for light sources
in all spectral rendering modes," and that a flat spectrum value of 1.0 as
emitter radiance renders purple-ish (because sRGB has a D65 whitepoint), whereas
the same spectrum as a BSDF reflectance renders white — i.e. Mitsuba's
`srgb_d65` emitter lift is **D65-weighted**, exactly like pbrt/RGBIlluminant.

### Cycles (RGB-native) — identity linear-RGB scaling, **no** spectral upsampling, **no** D65. **License: Apache-2.0** (verified `LICENSE`).

- `src/kernel/light/area.h::area_light_eval`: `ls->eval_fac = M_1_PI_F * invarea`
  — a **dimensionless geometric factor**, no color.
- `src/scene/light.cpp`: `copy_v3_v3(klight->strength, strength);` — the light
  `strength` (color × power) is stored **directly as a linear-RGB `float3`** and
  the emitted radiance is `strength × eval_fac`. There is no spectrum, no
  Jakob-Hanika lift, no D65 anywhere in the light path.

So Cycles' "emission convention" is **the identity**: the RGB you type *is* the
radiance, in linear Rec.709/sRGB primaries.

---

## 3. Why RGBIlluminant is +7–16% vs Cycles, and why RGBUnbounded fixes it

For a **pure white** light both conventions give unit luminance in isolation
(`RGBIlluminant` white → `sampleD65` integrates to Y=1 by construction;
`RGBUnbounded` white → flat sigmoid at ~0.5 × scale 2 ≈ flat 1.0, also Y=1). The
offset does **not** appear in the emitter alone — it appears in the **reflected
product** off the gray floor:

- **Cycles (RGB):** `out = albedo_RGB ⊙ light_RGB` — an exact per-channel product
  (white × 0.5-gray = 0.5).
- **Astroray spectral:** `out_RGB = M_xyz→rgb · ∫ S_albedo(λ)·S_emit(λ)·CMF(λ) dλ`.

When `S_emit` carries the **D65 tilt** (RGBIlluminant) but `S_albedo` is a plain
Jakob-Hanika reflectance sigmoid, the two spectra are from **different families**;
their product integrated against the CMF does **not** round-trip to the RGB
product — the D65-vs-reflectance spectral mismatch injects a systematic
metameric offset (measured +7–16%, uniform across all four light types because it
is a property of the shared `evalRGB`/albedo pipeline, not per-type geometry).

Switching emission to **RGBUnbounded** makes `S_emit = scale · sigmoid(rgb/scale)`
— the **same reflectance-sigmoid family** as `S_albedo`. Two same-family
Jakob-Hanika spectra multiplied and integrated round-trip back to the RGB product
with minimal crosstalk (this is exactly the property Jakob-Hanika 2019 fits for),
so the spectral render reproduces Cycles' RGB multiply. This is the standard
technique for making a spectral engine match RGB-native input.

**Vindication of pkg89 phase-b.** The 2026-05-21 cycles-parity review (Defect 2a)
already recommended `RGBUnboundedSpectrum` for emission. The pkg122 implementer
over-rode it citing a "~3× too dim" measurement — but that measurement was taken
with Defects 1–3 (the `1/π` point error, the mixed-measure area pdf) still
present, which confounded the emission convention with the radiometry. With those
fixed in PR #500, the clean residual is +7–16% and phase-b's recommendation is the
correct one.

---

## 4. pbrt vs Cycles genuinely disagree — which to match

They disagree by the **spectral-vs-RGB metamerism gap**. pbrt/Mitsuba deliberately
imprint a D65 illuminant chromaticity on RGB lights (physically: "this light
behaves like a real daylight-ish source"). Cycles works in RGB and has no such
imprint. There is no single "physically correct" answer — it is a **modeling
convention**, and the two well-known families sit on opposite sides.

**Astroray's entire quality program is Cycles parity**: the reference bank is
Cycles-calibrated (12/13 passing), every energy gate is keyed on live-Cycles
numbers, and the pkg122 oracle *is* a headless-Cycles A/B. Given the owner
directive ("best and used by other renderers, your call") and that the practical
north star is Cycles, the project should **match Cycles** for the emission lift
and **document the divergence from pbrt/Mitsuba**. We are not inventing a
convention — `RGBUnbounded` is a real pbrt-v4 class (`src/pbrt/util/spectrum.h`,
Apache-2.0) and already exists in Astroray (`RGBUnboundedSpectrum`,
`src/spectrum.cpp:451-473`); we are re-pointing the emission path at it.

---

## 5. Residual-risk / empirical honesty (CLAUDE.md §1)

The +7–16% → [0.97,1.03] closure is **argued analytically, not yet measured** (the
architect cannot build the `.pyd`). The metameric offset's *sign* and exact
magnitude depend on the shipped Jakob-Hanika sRGB LUT and the D65 table, so the
**gate is the live-Cycles oracle re-run**, not the reasoning.

**[CORRECTED]** This section under-scoped the risk: it named the right remedy
(pbrt's `SpectrumToPhotometric`) but as a *fallback* for a hypothetical **−3%
undershoot**. The actual PR #511 trigger was a **+11,600% units blow-up** because
`RGBUnbounded` (a dimensionless reflectance upsampler) dropped the
`1/CIE_Y_integral` photometric anchor the D65 factor carried — see Correction.
So `SpectrumToPhotometric` (as the constant `1/cieYIntegral()`) is **mandatory and
primary**, not a fallback. With it in place, the *residual* risk this section
describes (a small chromaticity/crosstalk offset resolved by the live oracle)
applies as written.

---

## 6. Sources

- pbrt-v4 `src/pbrt/util/spectrum.h` (RGBAlbedo/Unbounded/Illuminant classes),
  `src/pbrt/lights.cpp` (DiffuseAreaLight → `SpectrumType::Illuminant`,
  `scale /= SpectrumToPhotometric`), `LICENSE.txt` — Apache-2.0.
  https://github.com/mmp/pbrt-v4
- Cycles `src/kernel/light/area.h` (`eval_fac = M_1_PI_F*invarea`),
  `src/scene/light.cpp` (`copy_v3_v3(klight->strength, strength)`), `LICENSE` —
  Apache-2.0. https://github.com/blender/cycles
- Mitsuba 3 emitter/spectra docs (D65 default emission; reflectance-vs-emission
  upsampling asymmetry). https://mitsuba.readthedocs.io/en/stable/src/generated/plugins_emitters.html
  and .../plugins_spectra.html — BSD-3-Clause.
- Jakob & Hanika 2019, "A Low-Dimensional Function Space for Efficient Spectral
  Upsampling," Computer Graphics Forum (Eurographics) — the sigmoid RGB→spectrum
  fit both `RGBAlbedo` and `RGBUnbounded` use.
- "Spectral rendering, part 3: Spectral vs. RGB," momentsingraphics.de — the
  E-vs-D65 upsampling-illuminant subtlety.

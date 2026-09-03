# pkg225 Stage 5 — Spectral melanin absorption: algorithm research

CLAUDE.md §6 gate: no invented physics. This note records the cited sources for
the Stage-5 per-wavelength melanin absorption cross-section that replaces the
RGB→σ_a→upsample seam in the Chiang 2016 hair BSDF
(`plugins/materials/principled_hair.cpp` `sigmaAAtLambda()` +
`include/astroray/gpu_hair.cuh` `gpu_hair_sigmaAAtLambda()`), **before engine
code is written**, per the `cite-algorithm` skill.

Companion notes: `pkg225-hair-bsdf-research.md` (BSDF), `pkg225-curve-intersect-research.md` (geometry).

---

## Paper / data source

- **Jacques, S. L. 2013** — "Optical properties of biological tissues: a review."
  *Physics in Medicine and Biology* 58(11), R37–R61. **DOI:10.1088/0031-9155/58/11/R37.**
  The canonical review compiling melanin/melanosome absorption. Primary PDF on
  the author's own site (OMLC): https://omlc.org/news/dec14/Jacques_PMB2013/Jacques_PMB2013.pdf
- **Jacques, S. L. 1998** — "Skin Optics Summary" (Oregon Medical Laser Center
  note). https://omlc.org/news/jan98/skinoptics.html — gives the melanosome
  interior absorption **verified verbatim** (see below).
- **Donner, C. & Jensen, H. W. 2006** — "A Spectral BSSRDF for Shading Human
  Skin." *Eurographics Symposium on Rendering 2006*. The graphics-canonical
  pairing of the two melanin power laws (eumelanin + pheomelanin) used for
  spectral skin/hair rendering. PDF: graphics.ucsd.edu/~henrik/papers/skin_bssrdf/skin_bssrdf.pdf
- Secondary/biophysics context: **Alaluf et al. 2002** (ethnic variation in
  eumelanin/pheomelanin content) — motivates the two-pigment (eu/pheo) split and
  the redness parameter, not a formula source.

## The cited formulae

Two featureless power laws in wavelength λ (nm), monotonically rising toward the
blue (both pigments absorb short λ more — hair passes red, absorbs blue → the
characteristic brown/black/red appearance):

- **Eumelanin:**  σ_a,eu(λ) = 6.6×10¹¹ · λ^(−3.33)  [cm⁻¹]
  (= 6.6×10¹⁰ · λ^(−3.33) mm⁻¹ — same law, Donner&Jensen's mm⁻¹ units).
  **Exponent −3.33 verified verbatim** against the Jacques 1998 Skin-Optics
  melanosome fit `mua.mel = (6.6×10¹¹)(nm^−3.33) [cm⁻¹]` (OMLC, fetched
  2026-09-03). (Jacques' later 2013/OMLC `mua.html` revision gives 1.70×10¹²·λ^−3.48
  for the lumped melanosome — the −3.33 eumelanin form is the one Donner&Jensen
  and the graphics literature standardised on; we use it.)
- **Pheomelanin:**  σ_a,pm(λ) = 2.9×10¹⁴ · λ^(−4.75)  [mm⁻¹]  (Donner&Jensen 2006).
  Steeper falloff than eumelanin (−4.75 vs −3.33) → redder residual transmission.
  **Exponent −4.75 confirmed** from the Donner&Jensen 2006 pairing (web-verified
  2026-09-03); the primary PDF host has a TLS-cert error so it could not be
  quoted line-for-line — flagged for an owner spot-check, but the value is the
  long-standing graphics-canonical constant and the eumelanin half of the pair
  cross-checks exactly against the Jacques primary.

## What we reproduce

Only the **wavelength dependence (the exponents −3.33 / −4.75)** — the physical
spectral *shape* of melanin absorption. This is the whole point of Stage 5: the
4-λ hero pipeline evaluates σ_a per sampled wavelength directly from the power
law, with **no Jakob–Hanika RGB→spectral→RGB round-trip** (which smears out the
monotone melanin structure the acceptance gate checks for).

## Differences from the reference (documented, deliberate)

1. **Magnitude anchor, not absolute cm⁻¹.** The published constants are
   melanosome-interior coefficients in physical units (huge — a fibre would be
   opaque). Astroray's hair σ_a is a per-fibre-chord Beer–Lambert coefficient
   already calibrated by the existing RGB melanin path (Cycles coefficients
   `c_e=(0.506,0.841,1.653)`, `c_p=(0.343,0.733,1.924)`; see BSDF note §3e). So
   we keep only the **exponent** and **anchor each power law at λ=550 nm (green)
   to the Cycles green coefficient**:
   - κ_eu(λ) = 0.841 · (λ/550)^(−3.33)
   - κ_ph(λ) = 0.733 · (λ/550)^(−4.75)
   σ_a(λ) = eumelanin · κ_eu(λ) + pheomelanin · κ_ph(λ).
   **Property:** at 550 nm this equals the RGB-mode green σ_a *exactly*
   (`0.841·eu + 0.733·ph`), so RGB and spectral melanin agree at green and diverge
   (physically) toward the red/blue extremes — the intended "spectral is the
   ground truth, RGB approximates it" relationship. The anchor is an engineering
   calibration to preserve backward-compatible magnitude, **not** invented physics
   (the cited content is the exponent). Spot-check: κ_eu anchored at 550 reproduces
   the Cycles eumelanin RGB triple to within ~10–24 % at representative primary
   wavelengths — i.e. the Cycles triple was itself ≈ this power law, which
   validates the anchor.
2. **Two-pigment split via `melanin`+`redness`** (unchanged from Stage 2): the
   `eumelanin`/`pheomelanin` concentrations come from the existing perceptual
   remap `m = −log(1−melanin)`, `eu = m·(1−redness)`, `ph = m·redness` (Cycles
   `svm/closure.h`). Stage 5 only changes how eu/ph map to per-λ σ_a.
3. **Tint** stays an RGB-mode-only refinement; the spectral melanin path is pure
   eu/ph physical absorption (default Tint=(1,1,1) contributes 0 in both, so this
   is exact for all default use). Keeps CPU==GPU parity with minimal GMaterial
   field reuse.

## What we deliberately do NOT take

- No absolute-radiometric melanosome units / concentration-in-g·L⁻¹ modelling
  (Donner&Jensen's full skin layer model) — out of scope; hair σ_a is a
  per-fibre coefficient.
- No Jakob–Hanika upsample anywhere on this path (the design point).
- Reflectance / Direct-Absorption parametrizations keep the Stage-2 RGB→σ_a
  upsample seam unchanged (they have no melanin concentrations to evaluate
  spectrally).

## Integration plan in Astroray

- **New:** `include/astroray/hair_melanin_spectral.h` — `AR_HAIR_HD` (host+device)
  scalar `melaninSigmaAtLambda(eu, ph, λ)` (the seam) + a host-only
  `SampledSpectrum melaninAbsorption(eu, ph, SampledWavelengths)` convenience.
- **CPU edit:** `plugins/materials/principled_hair.cpp` — store `melaninMode_/eu_/ph_`;
  `sigmaAAtLambda()` branches to `melaninSigmaAtLambda` in melanin mode. RGB
  `sigmaA_` (and the S2 melanin test) unchanged.
- **GPU edit:** `include/astroray/gpu_hair.cuh` `gpu_hair_sigmaAAtLambda()` gains
  the same branch; eu/ph/mode ride hair-**unused** GMaterial scalar fields
  (`metallic`=eu, `subsurface`=ph, `specular`=melaninMode flag) — GMaterial stays
  **exactly 640 B** (no new field). `HairGPUParams` + `scene_upload.cu` carry
  them host-side.
- **Package:** `.astroray_plan/packages/pkg225-hair-rendering.md` Stage 5.
- **Tests:** `tests/test_pkg225_spectral_hair.py` — (a) `melaninSigmaAtLambda`
  ratio at 500/600/700 nm matches λ^−3.33 within 10 % (the acceptance gate);
  (b) CPU spectral-mode dark-hair render vs RGB-mode render shows a steeper
  red/blue channel spread (narrower absorption feature); (c) GPU↔CPU spectral
  melanin parity (per-channel mean-ratio). Register probe: fleet shade kernel
  REG:254 unchanged (the melanin branch lives inside the already-`__noinline__`
  hair body).

## Open questions

- Owner spot-check of the pheomelanin constant/exponent against the Donner&Jensen
  2006 PDF (TLS-cert error blocked a verbatim fetch; exponent −4.75 is web-confirmed
  and eumelanin cross-checks exactly). The anchor makes the absolute constant a
  non-issue; only the exponent matters.

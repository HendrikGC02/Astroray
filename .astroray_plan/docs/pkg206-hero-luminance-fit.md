# pkg206 — Luminance-weighted hero-wavelength importance sampling (research note)

**Skill:** cite-algorithm (CLAUDE.md §6). Sampling algorithm — non-trivial, cited.
**Date:** 2026-08-20.

## Problem

Astroray draws the hero wavelength **uniformly** over [360, 830] nm
(`SampledWavelengths::sampleUniform`, `src/spectrum.cpp:82`; GPU mirror
`sampleUniformWavelength`, `src/gpu/wavefront/stage_init.cu:119`), pdf = 1/span.
Uniform draws spend equal sampling effort on wavelengths the eye barely sees, so
dispersive-caustic renders carry more chromatic noise per sample than necessary.

## Cited sources

1. **Wilkie, Nawaz, Droske, Weidlich, Hanika 2014, "Hero Wavelength Spectral
   Sampling", CGF 33(4), DOI 10.1111/cgf.12419.** The hero-wavelength framework:
   one hero λ is drawn per path and `k-1` stratified companions are wrapped into
   range. Under a **non-uniform** hero proposal density `p(λ)`, each companion's
   pdf is `p` evaluated at *its own* λ (NOT the hero's, NOT 1/span). We keep the
   one-hero-per-path structure; only the proposal density changes.

2. **Blender Cycles, `intern/cycles/kernel/util/colorspace.h`, `sample_wavelength()`
   (Apache-2.0), and `intern/cycles/app/cie_d65_luminance_fit.py`.** Cycles draws
   the hero wavelength from a **luminance-weighted D65 distribution** fitted to a
   logistic (sigmoid) CDF. Verbatim Cycles constants (fit in **micrometres**,
   CIE-1931 2° observer, 380–780 nm):

   ```
   a  = 21.71348444564851   (1/um)
   x0 = 0.5554867905834258  (um  = 555.49 nm)
   y0 = 0.021659159132699574
   N  = 0.9707633294863183
   ```

   Cycles' sampler (um):
   ```
   rand = N*rand + y0;
   prob = a*rand*(1-rand) * (WAVELENGTH_CIE_MAX - WAVELENGTH_CIE_MIN) / N;  // ratio-to-uniform
   wavelength = -logf(1/rand - 1)/a + x0;   // um
   ```

   Fit target (from `cie_d65_luminance_fit.py`): CDF of `(cie_y + 0.25) * d65`.
   The **+0.25 additive constant** on the luminance CMF ("we want a bit of all
   the wavelengths") blends between pure-luminance (green caustic noise) and
   uniform (noisier everywhere). Model `F(x) = 1/(1+exp(-a(x-x0)))`,
   `y0 = F(0.38)`, `N = F(0.78) - y0` (CDF-space truncation to the range).

## Observer-mismatch decision (spec §1)

Cycles fits against the **CIE-1931 2°** observer; Astroray carries the
**CIE-1964 10°** observer (`data/spectra/cie_cmf.inc`) and a D65 SPD
(`illuminant_d65.inc`). The two y-bar functions differ (the 10° observer is
broader and slightly red-shifted). Rather than reuse Cycles' 1931-2° constants
blindly, we **re-fit against Astroray's own tables** with the same model,
same +0.25 blend, over Astroray's own [360, 830] nm range, in **nm units**
(so no unit-conversion footgun in the runtime code).

Script: `scripts/data/fit_hero_luminance_cdf.py` (reads the baked `.inc` tables,
`scipy.optimize.curve_fit` on the empirical CDF).

### Fitted constants (Astroray, CIE-1964 10°, nm units, [360,830] nm, blend +0.25)

```
a  = 0.0221679280f   // 1/nm     (Cycles equiv 0.0217135 /nm — 2.1% higher)
x0 = 552.040271f     // nm       (Cycles equiv 555.49 nm — 3.4 nm bluer)
y0 = 0.0139650380f
N  = 0.9839309253f
```

- Max fit error `|F_fit - F_emp| = 2.77e-2` (CDF, comparable to Cycles).
- Sampled λ spans **[360.00, 829.99] nm** — full [360,830] coverage, so the
  sampler support ⊇ the CMF/emission support ⇒ importance sampling stays
  unbiased for every integrand (pdf > 0 wherever the integrand is nonzero).
- Verified `∫ pdf(λ) dλ = 0.999999` over the analytic support (target 1.0).

The re-fit lands close to Cycles (same regime, same "bit of all wavelengths"
blend) while being self-consistent with Astroray's observer — no measured
error bound against a foreign observer is needed because we did not reuse the
foreign constants.

## Runtime formulation (nm units, unbiased)

Draw one uniform `u ∈ [0,1)` (SAME draw count as uniform — CPU↔GPU dimension
counters stay aligned):

```
rand  = N*u + y0
hero  = x0 - log(1/rand - 1) / a          // nm, in [360, 830]
pdf(λ) = a * rand_λ * (1 - rand_λ) / N     // 1/nm  (rand_λ = F(λ) = sigmoid)
```

The **hero** pdf uses `rand` directly (`rand_hero = rand`). Each stratified
**companion** λ_i = wrap(hero + i*step) gets its pdf from the density evaluated
at ITS OWN λ_i: `rand_i = sigmoid(λ_i; a, x0)`, `pdf_i = a*rand_i*(1-rand_i)/N`
(Wilkie 2014). This is a proper density in 1/nm that integrates to 1, so the
existing MC estimator (`SampledSpectrum::toXYZ` divides by `pdf(i)`) stays
unbiased — only the variance drops.

Note vs Cycles: Cycles' `prob` is a **dimensionless ratio-to-uniform**
(multiplies by span). Astroray's `pdf` is a **true density in 1/nm** (divides by
`N` only) because Astroray's estimator divides by a genuine per-wavelength
density (`toXYZ`: `value * CMF(λ) / pdf`). Getting this unit right is the
unbiasedness-critical difference from a blind Cycles port.

## Non-goals

- No per-bounce λ re-sampling / spectral MIS (pkg211).
- No λ→RGB change (Astroray integrates against the CIE-1964 observer directly;
  Cycles' D65 RGB-uplift workaround does not apply).

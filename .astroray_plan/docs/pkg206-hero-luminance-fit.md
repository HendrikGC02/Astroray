# pkg206 — Luminance-weighted hero-wavelength importance sampling: fit derivation

**Package:** pkg206. **Author:** package-implementer, 2026-08-21.
**Code sites citing this note:** `src/spectrum.cpp` (`SampledWavelengths::sampleImportance`),
`src/gpu/wavefront/stage_init.cu` (`sampleImportanceWavelength`).
**Fit script:** `scripts/data/fit_hero_luminance_cdf.py`.

## 1. Algorithm sources (CLAUDE.md §6, cite-algorithm)

- **Wilkie, Nawaz, Droske, Weidlich, Hanika 2014, "Hero Wavelength Spectral
  Sampling", Computer Graphics Forum 33(4) (EGSR), DOI 10.1111/cgf.12419.**
  The hero-wavelength framework: one hero wavelength is drawn per path, all
  directional sampling keys off it, and `N-1` companion wavelengths are placed
  so that together the samples evenly cover the range. The MC estimator for a
  spectral integral is the balance-heuristic average
  `(1/N) Σ_i f(λ_i) / p(λ_i)`, so **each companion must be divided by the density
  evaluated at ITS OWN wavelength** — not by the hero density and not by a shared
  `1/span`. This is the requirement that keeps the estimator unbiased when the
  hero proposal is non-uniform.

- **Blender Cycles**, `intern/cycles/kernel/util/colorspace.h::sample_wavelength`
  and `intern/cycles/app/cie_d65_luminance_fit.py` (SPDX `Apache-2.0`, verified
  on the file header 2026-08-21). Cycles draws the hero wavelength from a
  luminance-weighted D65 distribution fitted to a **logistic (sigmoid) CDF**:

  ```
  rand       = N * rand + y0;                    // truncate uniform to CDF window
  prob       = a * rand * (1 - rand);            // density in CDF units
  wavelength = -logf(1/rand - 1) / a + x0;       // inverse logistic CDF
  ```

  and adds a **constant to the luminance CMF before fitting** ("we want a bit of
  all the wavelengths") so the proposal lands between pure-luminance (green
  caustic noise) and uniform (noisier everywhere).

- **PBRT-v4** `SampledWavelengths::SampleVisible` / `SampleVisibleWavelengths`
  (Apache-2.0) is the structural template for the **CDF-space stratified**
  construction that keeps the estimator unbiased (see §3): stratify the single
  uniform `u` into `N` equal strata in **CDF (uniform) space**, invert each
  through the inverse CDF, and set `pdf[i] = density(λ_i)`.

## 2. Observer-mismatch decision (RE-FIT, not reuse)

Cycles fits its constants against the **CIE 1931 2° observer**. Astroray carries
the **CIE 1964 10° observer** (`data/spectra/cie_cmf.inc`, `kCieCmfY`) plus a
normalized D65 SPD (`data/spectra/illuminant_d65.inc`, `kD65Spd`). The spec
requires either re-fitting against Astroray's own tables OR reusing Cycles'
constants with a measured error bound.

**Decision: re-fit against Astroray's own `(y_bar + 0.25)·D65` luminance target.**
This eliminates the observer mismatch by construction — there is no residual
error bound to carry because we never import Cycles' 1931 constants. The fit is
cheap, deterministic, and reproducible from the baked tables via the registered
script. (The `sample_wavelength` inversion math and the `+const` blend trick are
reused verbatim from Cycles; only the four numeric constants are Astroray's.)

## 3. Why CDF-space stratification is unbiased (the pkg67/PR#627 trap)

The naive reading of "hero + stratified companions" — offset in **wavelength**
space (`λ_i = hero + i·step`) and set `pdf_i = density(λ_i)` — is **biased** under
a non-uniform proposal: the companion's true marginal density is the hero density
transported by the fixed offset, not `density(λ_i)`. On an achromatic flat scene
this oversamples the ~555 nm luminance peak while under-correcting it, producing a
systematic green cast + brightness offset. That is exactly the bias the 2026-08-21
triage flagged on the closed PR #627.

The unbiased construction (PBRT `SampleVisible`) stratifies the **uniform**
variable, then inverts each stratum through the inverse CDF:

```
for i in 0..N-1:
    u_i    = frac(u + i/N)              // stratify in CDF/uniform space
    rand_i = N_win * u_i + y0           // map into the truncated CDF window
    λ_i    = x0 - log(1/rand_i - 1)/a   // inverse logistic CDF
    pdf_i  = a * rand_i * (1 - rand_i) / N_win   // density at λ_i, 1/nm
```

Here each lane `i` is a genuine draw from stratum `i` of the target distribution,
so its marginal density **is** `p(λ_i)` and `pdf_i = p(λ_i)` is exact. The
estimator `Σ f(λ_i)/p(λ_i) / N` is therefore unbiased; only the variance changes.
Under a *uniform* `F` (linear CDF) this construction collapses byte-for-byte to
the old `sampleUniform` (equal strata coincide, `pdf → 1/span`).

Draw count: `sampleImportance` consumes exactly **one** uniform `u`, identical to
`sampleUniform`, so the CPU↔GPU PCG32 dimension counters stay aligned
(`stage_init.cu` draw-count invariant, the 8.7M-ULP divergence guard).

## 4. Fitted constants (nm units, range [360, 830], blend +0.25)

Reproduce with `python scripts/data/fit_hero_luminance_cdf.py`:

```
kHeroA  = 0.0221679280f;   // 1/nm   (logistic steepness)
kHeroX0 = 552.040271f;     // nm     (luminance-weighted centre, near the ~555 nm peak)
kHeroY0 = 0.0139650380f;   //        F(360 nm)  — CDF value at lambdaMin
kHeroN  = 0.9839309253f;   //        F(830 nm) - F(360 nm)  — CDF-window width
```

Fit quality (measured):

- `max |F_fit − F_empirical|` over the 471-point grid = **2.77e-2** (CDF space).
- Sampled λ over `u ∈ (0,1)` spans **[360.00, 829.99] nm** — full range covered.
- `∫ pdf(λ) dλ` over the analytic support = **0.999999** (target 1.0), i.e. the
  density normalizes to 1 — the unit/normalization check for unbiasedness.

The 2.77e-2 CDF residual is a shape-approximation of the true luminance CDF by a
2-parameter logistic; it does **not** bias the estimator (any strictly-increasing
proposal CDF with `pdf_i = its own derivative` is unbiased — Wilkie 2014 / PBRT).
It only affects how close the proposal is to the variance-optimal one, i.e. the
size of the convergence win, which pkg206's benchmark measures empirically.

## 5. Companion pdf plumbing (unbiasedness in the transport)

`SampledSpectrum::toXYZ(wl)` already divides each lane by `wl.pdf(i)` (PBRT MC
convention). Because `sampleImportance` writes the per-lane logistic density into
`pdf[i]`, no downstream change is needed for the XYZ reconstruction to stay
unbiased. `redshift()` and `terminateSecondary()` operate on `pdf[i]` uniformly
and remain correct (they scale / zero whatever density is stored).

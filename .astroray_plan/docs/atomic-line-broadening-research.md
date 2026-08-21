# Atomic Emission-Line Broadening (Gaussian / Voigt line shape) — Research

**Package:** pkg214 — Sodium-vapor lamp preset emits no light (narrow D-line aliased to zero)
**Date:** 2026-08-21
**Researcher:** package-implementer (deepseek-v4-pro)

---

## Paper

- **Title:** Spectrum line profiles: The Voigt function
- **Author:** B. H. Armstrong
- **Year / Venue:** 1967, *Journal of Quantitative Spectroscopy and Radiative Transfer* 7(1), 61–88
- **DOI:** [10.1016/0022-4073(67)90057-X](https://doi.org/10.1016/0022-4073(67)90057-X)
- **PDF:** https://www.sciencedirect.com/science/article/pii/002240736790057X

Supporting canonical context:

- **Voigt (1912)** — original convolution definition of the Voigt profile (Gaussian × Lorentzian).
- **Doppler broadening** — the Gaussian line shape is the Doppler-broadening limit,
  arising from the Maxwellian velocity distribution of emitting atoms
  (see e.g. AstroBaki "Line Profile Functions": a normalized profile
  ∫ φ(ν) dν = 1, with the Doppler width Δν = (ν₀/c)√(2kT/m)).

## Reference implementation

- **Repo:** https://github.com/scipy/scipy
- **Function:** `scipy.special.voigt_profile(x, sigma, gamma)` — the Voigt profile
  as the convolution of a 1-D Normal (σ) and a 1-D Cauchy (γ) distribution;
  `gamma = 0` reduces to the Normal (Gaussian) PDF, `sigma = 0` to the Cauchy PDF.
- **Commit / tag:** `main` (BSD-3-Clause, stable API since SciPy 0.19 / v1.7).
- **License:** BSD-3-Clause — compatible with Astroray's MIT/Apache-2.0 target
  (see `.astroray_plan/docs/external-references.md` §License compatibility reminder).
- **Files we mirror (conceptually, not copied):**
  - The Gaussian limit `V(x; σ, 0) = exp(−x²/(2σ²)) / (σ√(2π))` — a one-line
    closed form implemented directly in `build_spectral_profiles.py` (no SciPy
    runtime dependency is introduced; the data-build script already depends only
    on numpy + colour-science).

## What we reproduce

- **Gaussian (Doppler) line shape** `G(λ) = exp(−(λ−λ₀)²/(2σ²)) / (σ√(2π))`,
  normalised to unit integral, with `σ = FWHM / (2√(2 ln 2))`.
- Each atomic line is deposited as `intensity · G(λ)` so the **area** under each
  line's profile equals its relative intensity. This conserves total energy and
  the D2:D1 = 2:1 ratio exactly (the two lines share the same σ, so the area
  ratio equals the intensity ratio).
- **Differences from the reference:** we use the *pure Gaussian* (γ = 0) limit,
  not the full Voigt, and we set the FWHM **deliberately** to the renderer's
  spectral sampling resolution, not to any physical linewidth. See §FWHM
  justification below.

## Why Gaussian (not Lorentzian / Voigt) — FWHM justification

The Na I D-lines have a physical linewidth ~0.1 nm (low-pressure) — a full
Lorentzian/Voigt treatment is *irrelevant* here because 0.1 nm ≪ 1 grid bin
(5 nm): the physical line shape is unrepresentable on the stored grid regardless
of its exact form, and only its **area** survives resampling. So the choice of
kernel is about *numerical bandwidth*, not physics. A Gaussian is the standard
choice because:

1. It is energy-normalised (unit area) and compact — energy is conserved and
   stays localised around λ₀ rather than spreading across the whole grid.
2. The Gaussian is the Doppler-broadening limit (Voigt with γ→0), so it is a
   physically-motivated line shape even though we widen σ far beyond the true
   Doppler width for representability.
3. `FWHM = 15 nm` (σ ≈ 6.37 nm) equals **3 × the 5 nm grid step**, so the line
   spans **≥ 3 grid bins** (actually ~7 bins above 5% of peak, 575–605 nm).

Justification against the render's wavelength-sampling resolution
(`include/astroray/spectrum.h:25` `kSpectrumSamples = 4`,
`src/spectrum.cpp:82` `sampleUniform`): at the u = 0.5 stratification the four
carried wavelengths are {580, 680, 380, 480} nm over [380, 780]. The nearest of
these to the 589.2 nm D-line centroid is **580 nm (9.2 nm away)**. With the
pre-fix single-bin deposit, `emission(580)` = 0 (linear interpolation between
two zero bins), so the u = 0.5 hero wavelengths all read ~0 — the degenerate-CDF
failure documented at `src/light_sampler.cpp:55–67`. With FWHM = 15 nm the
peak-normalised SPD at 580 nm is `exp(−(9.2/6.37)²/2) ≈ 0.35`, i.e. the hero
wavelength reads ~35% of peak emission, and the lamp becomes robustly visible.
The two D-lines (588.995 / 589.592 nm, 0.6 nm apart ≪ σ) merge into one
unresolved ~589 nm feature — physically correct for low-pressure sodium, which
reads as a single amber doublet.

**Honest tradeoff (CLAUDE.md §1):** FWHM = 15 nm is ~150× wider than the true
~0.1 nm linewidth. That is intentional and standard: the pipeline stores and
samples spectra on a 5 nm grid, so a sub-bin feature is unrepresentable; the
broadening *matches the line to the renderer's spectral resolution*, not a
physics claim about the lamp. This is stated inline in the code comment.

## What we deliberately do NOT take

- The full Voigt profile (Lorentzian × Gaussian convolution) — physically
  irrelevant at 5 nm resolution.
- Emission-line importance sampling (draw λ ∝ SPD) in the wavelength sampler —
  that is pkg206's scope and the general-case follow-up; out of scope for pkg214.
- Any mercury-continuum change — mercury's flat 50-unit 400–700 nm continuum is
  left untouched; only its discrete lines pass through the same broadened
  `_atomic_lines`.

## Integration plan in Astroray

- **Files to edit:** `scripts/data/build_spectral_profiles.py` (`_atomic_lines`),
  `tests/test_pkg195_stage_b_spectral_lamp.py` (`test_b1_sodium_lamp_is_amber`
  explicit positive floor), `tests/test_spectral_profiles.py`
  (`test_sodium_vapor_d_line_concentration` — window/tolerance restated for the
  broadened line).
- **Data regenerated:** `data/spectral_profiles/profiles.bin`,
  `data/spectral_profiles/profiles_metadata.json`, `data/spectral_profiles/sources.md`
  (the script writes all three; only the first two are expected to change).
- **Package:** `.astroray_plan/packages/pkg214-sodium-vapor-emission-fix.md`.
- **Tests / parity check:** `tests/test_spectral_profiles.py`,
  `tests/test_pkg195_stage_b_spectral_lamp.py` (B1 amber + B2 + B3), plus a
  per-channel mercury mean-RGB regression check against the pre-fix profile.

## Open questions

- None blocking. The FWHM (15 nm) is a free choice within the spec's 10–15 nm
  band; it is the value that keeps the ~589 nm energy concentration highest
  while still reading ~35% at the 580 nm hero wavelength.

# Spectral Power Distribution Normalization: Energy (unit integral) vs Peak — Research

**Package:** pkg214 (fix) — sodium-vapor broadening regressed mercury via peak normalization
**Date:** 2026-08-21
**Researcher:** package-implementer (Opus 4.8)

---

## Problem

`scripts/data/build_spectral_profiles.py` `mat_ls()` stored every light-source
SPD normalized so its **peak bin = 1.0** (`peak = data.max(); data /= peak`).
pkg214 broadened atomic emission lines from a single-bin spike to an
area-conserving Gaussian (FWHM 15 nm). Broadening lowers a line's PEAK while
preserving its AREA. Under peak-normalization the whole SPD is then rescaled by
that now-smaller peak, which **inflates every other feature** — in particular
mercury's flat phosphor continuum. Measured: mercury's stored-SPD sum jumped
4.71 → 30.60 (~6.5x), rendering mercury 4.5-8.6x too bright (PR #629 HW FAIL).

The defect is that **peak normalization couples the continuum level to the line
peak**: a change in line SHAPE (broadening, which is physically radiance-neutral
because it conserves area) leaks into the continuum:line RATIO. That ratio is a
physical property of the lamp and must be invariant.

## The physically-correct normalization: unit integral (energy)

Normalize each SPD so its **integral over the wavelength grid = 1**
(equivalently, with a uniform grid, `Σ_j r_j = 1` — a discrete PMF / relative
spectral power density over the 5 nm bins). Under a discrete uniform grid the
integral `∫ S(λ) dλ ≈ Δλ · Σ_j r_j`, so dividing by `Σ_j r_j` fixes the total
emitted (relative) power to a constant independent of spectral shape.

Key properties (all verified empirically for every lamp — see PR body table):

1. **Total stored power invariant under area-conserving broadening.** Gaussian
   line broadening conserves each line's `Σ_j r_j`, so the energy-normalized
   TOTAL stays 1 regardless of line shape. A lamp's overall brightness relative
   to other lamps is therefore decoupled from broadening → the mercury
   regression cannot occur. (Broadening still redistributes energy *across
   bins* — that is the intended, radiance-neutral effect of representing a line
   at grid resolution; the fixed-window line:continuum split shifts slightly,
   but total energy and hence overall brightness are conserved.)
2. **Every bin ≤ 1.** With non-negative bins summing to 1, each bin is ≤ 1, so
   the existing `[0,1]` storage/QC contract holds without clipping. (Verified:
   the largest single bin across all 7 lamps is sodium's ~0.19.)
3. **Magnitude now lives in Power, shape in the SPD.** Peak=1 and sum=1 differ
   per-lamp by a lamp-dependent constant, so this rescales every lamp's stored
   magnitude. That is correct: absolute lamp brightness is set by the light
   **Power** (pkg213, just landed) times the normalized spectral SHAPE. The SPD
   now carries only chromaticity/shape, not an arbitrary absolute level.

## Canonical sources

- **Wyszecki, G. & Stiles, W. S., "Color Science: Concepts and Methods,
  Quantitative Data and Formulae", 2nd ed., Wiley 1982.** Standard reference for
  *relative* spectral power distributions: an SPD used for color/shape is defined
  up to a multiplicative constant, fixed by a normalization convention
  (unit-area, peak, or value-at-560 nm). We adopt unit-area because it makes the
  stored spectrum a normalized density whose shape is decoupled from magnitude.
- **Pharr, Jakob & Humphreys, "Physically Based Rendering: From Theory to
  Implementation", 4th ed., §4.5 "Representing Spectral Distributions"**
  (https://pbr-book.org/4ed/Radiometry,_Spectra,_and_Color/Representing_Spectral_Distributions).
  Spectra are evaluated at discrete wavelengths inside the Monte Carlo estimator;
  a normalized spectral density (unit integral over the sampling domain) is the
  natural representation for a probabilistic/MC pipeline, with absolute scale
  supplied separately by the emitter's power.
- **Reference implementation (conceptual, not copied):**
  `colour.SpectralDistribution.normalise()` / relative-SPD handling in
  colour-science (BSD-3-Clause, already a build-time dependency of this script).
  The unit-integral form is `S(λ) / (Δλ · Σ_j S(λ_j))`; on a uniform grid the
  `Δλ` cancels in downstream *relative* use, so we store `S / Σ_j S`. No new
  runtime dependency is introduced (pure numpy).

## What we reproduce
- Discrete unit-integral normalization `r ← r / Σ_j r_j` in `mat_ls()`, replacing
  `r ← r / max_j r_j`.

## What we deliberately do NOT change
- The Gaussian line broadening from pkg214 (kept; see
  `atomic-line-broadening-research.md`).
- Mercury's flat 50-unit 400-700 nm continuum (untouched in `_atomic_lines`
  caller).
- Any engine / sampler / C++ code — this is a data-build change only.

## Differences from a strict physical SPD
- We store the dimensionless normalized density `r / Σ_j r_j` (the `Δλ` factor
  is a global constant that cancels in relative use and is absorbed into the
  emitter Power). This is the "relative SPD" convention of Wyszecki & Stiles.

## Tests / parity
- `tests/test_spectral_profiles.py` (`test_light_source_normalisation` flips
  peak==1 → Σ==1; `test_mercury_vapor_line_peaks` drops the peak==1 assertion,
  keeps line-dominance-over-continuum).
- `tests/test_pkg195_stage_b_spectral_lamp.py` B1/B2/B3.
- Before/after stored-SPD integral+peak table for all 7 lamps (PR body).

## Open questions
- None blocking. Parent (Claude) render-verifies all lamps on RTX hardware;
  this data change is engine-agnostic and flows to both backends via profiles.bin.

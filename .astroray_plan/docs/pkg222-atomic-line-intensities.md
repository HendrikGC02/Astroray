# pkg222 — atomic-line lamp SPDs: cited line intensities + chromaticity audit

**CLAUDE.md §6 citation record.** Fixes the stored `mercury_vapor` SPD, which
integrated to a **magenta-below-locus** colour (the pkg218 Thread-A finding),
because its relative line intensities were wrong and it carried an unjustified
flat continuum.

## Root cause

The generator built mercury from `435.83 nm (1000) : 546.07 nm (500) : 404.66 nm
(400)` plus a flat 5%-of-peak continuum over 400–700 nm. That over-weights the
blue 435.8 line 2:1 over the green 546.1 line and **omits the yellow 576.96/
579.07 doublet entirely** — so the stored SPD integrates (against the engine's own
CIE-1964-10° CMF) to **xy ≈ (0.314, 0.311)**, a magenta-white *below* the
blackbody locus. A real clear high-pressure mercury lamp is a **greenish-white
~xy (0.33, 0.38)** *above* the locus.

## Cited fix — NIST Handbook Hg I persistent lines

Relative intensities from the **NIST Handbook of Basic Atomic Spectroscopic Data,
persistent lines of neutral mercury (Hg I)** (public domain, US Gov):

| λ (nm) | line        | NIST rel. intensity |
|--------|-------------|---------------------|
| 404.66 | violet      | 200                 |
| 435.83 | blue        | 300                 |
| 546.07 | green       | **400 (strongest)** |
| 576.96 | yellow      | 160                 |
| 579.07 | yellow      | 200                 |

Two corrections vs the old model: the **green 546 line is the strongest** (not
the blue), and the **yellow doublet is present** (≈360 combined, comparable to
green). No artificial continuum — a clear (non-phosphor) mercury lamp is a line
source; the old flat baseline only dragged the chromaticity back below the locus.

## Chromaticity audit (vs the engine `cie_cmf.inc`, CIE-1964-10°)

Computed with `scripts` chromaticity integration (SPD·CMF → XYZ → xy):

| SPD                              | xy               | verdict            |
|----------------------------------|------------------|--------------------|
| OLD Hg (435:1000/546:500 +5% cont) | (0.314, 0.311) | magenta, below locus (BUG) |
| **NEW Hg (NIST Handbook lines)**   | **(0.335, 0.369)** | greenish-white, above locus ✓ |
| target (real clear HPMV)           | ~(0.33, 0.38)  | Δxy ≈ (0.005, 0.011) < 0.02 |
| sodium_vapor (unchanged)           | (0.583, 0.417) | deep amber, correct — not regressed |

The sodium D-doublet is confirmed unchanged (matches the pkg214 value). Only the
`mercury_vapor` block changed; all other lamps are byte-identical in the
generator.

## Sources

- **NIST Handbook of Basic Atomic Spectroscopic Data**, persistent lines of
  mercury (Hg I): https://physics.nist.gov/PhysRefData/Handbook/Tables/mercurytable4.htm
- CIE 1964 10° Standard Observer CMF (the engine's `data/spectra/cie_cmf.inc`,
  via cvrl.ucl.ac.uk).
- Line shape: energy-normalised Gaussian, FWHM 15 nm (Armstrong 1967 Voigt /
  Doppler limit) — the existing `_atomic_lines` convention, unchanged.

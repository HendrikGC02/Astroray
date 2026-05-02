# pkg45 — CLOUDY Emissivity Table Preprocessing

**Pillar:** 4
**Track:** B (Python-only, no C++ changes)
**Status:** open
**Estimated effort:** 1 session (~3 h)
**Depends on:** none (independent Python preprocessing)

---

## Goal

**Before:** Astroray has no way to render emission nebulae. Computing
recombination line emissivities from first principles at render time
would require solving the full photoionisation/recombination equilibrium
— far too expensive for a path tracer.

**After:** A Python preprocessing pipeline drives CLOUDY (or reads
published CLOUDY results) to produce a 4D emissivity lookup table
j_ν(ρ, T, U, λ) stored as a compact binary file. The C++ HII region
plugin (pkg46) loads this table and samples it per-voxel during
rendering.

---

## Context

HII regions emit via recombination and collisional excitation of ions.
The dominant visible lines are Hα (656.3 nm), Hβ (486.1 nm),
[OIII] (500.7 / 495.9 nm), and [NII] (658.4 / 654.8 nm). The relative
line ratios depend on density, temperature, and ionisation parameter U.
CLOUDY is the standard photoionisation code for computing these; it is
GPL-licensed and cannot be linked into Astroray, but it can be run
offline to produce tables.

This package is Python-only. It produces a static data file that the
C++ plugin reads. It can be developed and tested independently of any
C++ changes.

---

## Reference

- Design doc: `.astroray_plan/docs/astrophysics.md §4.4`
- CLOUDY: https://www.nublado.org/ (GPL; offline preprocessing only)
- pyCloudy: https://github.com/Morisset/pyCloudy (GPL; offline)
- Osterbrock & Ferland 2006 — "Astrophysics of Gaseous Nebulae and
  Active Galactic Nuclei" (reference line ratios)
- External references: `.astroray_plan/docs/external-references.md §4`

---

## Prerequisites

- [ ] CLOUDY or pyCloudy installed locally (not a repo dependency).
- [ ] Python 3.11 available.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `scripts/generate_cloudy_tables.py` | Main preprocessing script. Drives CLOUDY via pyCloudy (if available) or reads pre-computed results. Outputs the binary emissivity table. |
| `scripts/cloudy_table_format.md` | Documentation of the binary table format so the C++ loader (pkg46) knows what to expect. |
| `data/emissivity/hii_emissivity.bin` | The output emissivity table (committed to repo). |
| `data/emissivity/hii_emissivity_metadata.json` | Grid axes, units, line identifications, version info. |
| `tests/test_cloudy_tables.py` | Validates the table: correct shape, physical bounds, known line ratios. |

### Table specification

#### Grid axes

| Axis | Symbol | Range | Points | Spacing |
|---|---|---|---|---|
| Electron density | n_e | 10¹ – 10⁶ cm⁻³ | 20 | log-uniform |
| Electron temperature | T_e | 5000 – 20000 K | 16 | linear |
| Ionisation parameter | log U | −4 to 0 | 16 | linear |
| Wavelength | λ | line centres only | 8 | discrete |

#### Lines included

| Line | λ (nm) | Transition |
|---|---|---|
| Hα | 656.28 | H I Balmer-α |
| Hβ | 486.13 | H I Balmer-β |
| Hγ | 434.05 | H I Balmer-γ |
| [OIII] | 500.68 | O III 1D₂ → 3P₂ |
| [OIII] | 495.89 | O III 1D₂ → 3P₁ |
| [NII] | 658.34 | N II 1D₂ → 3P₂ |
| [NII] | 654.80 | N II 1D₂ → 3P₁ |
| [SII] | 671.65 | S II 2D₃/₂ → 4S₃/₂ |

Total table size: 20 × 16 × 16 × 8 × 4 bytes (float32) ≈ 640 KB.
Small enough to commit to the repo.

#### Binary format

Header (64 bytes):
- Magic bytes: `AHII` (4 bytes)
- Version: uint32 (currently 1)
- n_density, n_temp, n_logU, n_lines: 4 × uint32
- Density range (log10): 2 × float32
- Temperature range: 2 × float32
- logU range: 2 × float32
- Reserved: pad to 64 bytes

Data: float32 array in row-major order
[density][temperature][logU][line], shape (20, 16, 16, 8).
Values are emissivity j in erg s⁻¹ cm⁻³ sr⁻¹.

Line wavelengths stored in metadata JSON, not in the binary.

#### Fallback: published tables

If CLOUDY is not installed, the script falls back to tabulating
emissivities from the Case B recombination coefficients in Osterbrock
& Ferland (2006) Table 4.2 (hydrogen lines) and the collisional
excitation rates from Proxauf et al. 2014 (forbidden lines). This
produces a less accurate table but is sufficient for visualization
purposes and does not require any external software.

### Key design decisions

1. **Offline preprocessing, not runtime.** CLOUDY is GPL and
   computationally expensive. The table is generated once and committed.
   The C++ side never runs CLOUDY.

2. **Discrete lines, not continuous spectra.** HII region emission is
   dominated by a handful of lines. Storing continuous spectra would
   increase table size ~100× for negligible visual benefit. The C++
   plugin (pkg46) will model each line as a narrow Gaussian centred on
   the line wavelength.

3. **Published-table fallback.** Not everyone has CLOUDY installed.
   The Case B + collisional excitation fallback produces physically
   reasonable line ratios (within ~20% of CLOUDY) and makes the
   pipeline self-contained.

4. **Metadata separate from binary.** The JSON sidecar makes the
   table inspectable and debuggable without parsing the binary. It also
   allows the C++ loader to validate table dimensions before reading.

---

## Acceptance criteria

- [ ] `scripts/generate_cloudy_tables.py` runs successfully with
      `--fallback` mode (no CLOUDY required) and produces
      `data/emissivity/hii_emissivity.bin` and
      `data/emissivity/hii_emissivity_metadata.json`.
- [ ] Table dimensions match specification: (20, 16, 16, 8).
- [ ] All emissivity values are non-negative and finite.
- [ ] Hα/Hβ ratio at T_e=10000K, n_e=100 cm⁻³ is within 10% of the
      Case B value (~2.86).
- [ ] [OIII] 500.7/495.9 ratio is within 5% of the quantum-mechanical
      value (~2.98).
- [ ] [NII]/Hα ratio varies monotonically with ionisation parameter
      (higher U → lower [NII]/Hα), consistent with standard BPT
      diagram behaviour.
- [ ] Binary file < 1 MB.
- [ ] `tests/test_cloudy_tables.py` passes: shape, bounds, and line
      ratio checks.
- [ ] `cloudy_table_format.md` documents the binary format
      sufficiently for the C++ loader to be written from it alone.

---

## Non-goals

- Do not write the C++ loader. That is pkg46.
- Do not model dust emission or absorption in HII regions.
- Do not model radio recombination lines (only optical/near-IR).
- Do not model planetary nebulae (different density/temperature regime).
- Do not require CLOUDY as a build or test dependency.

---

## Progress

- [ ] Implement Case B hydrogen emissivity computation.
- [ ] Implement collisional excitation emissivities for forbidden lines.
- [ ] Write binary table output.
- [ ] Write metadata JSON output.
- [ ] (Optional) Implement pyCloudy driver for full CLOUDY mode.
- [ ] Validate line ratios against published values.
- [ ] Write format documentation.
- [ ] Write tests.
- [ ] Commit table to `data/emissivity/`.
- [ ] Update STATUS.md.

---

## Lessons

*(Fill in after the package is done.)*

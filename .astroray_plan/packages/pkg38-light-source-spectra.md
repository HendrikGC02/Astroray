# pkg38 — Light-Source SPD Amendment (Spectral Profile Database)

**Pillar:** 5 (rendering data assets)
**Track:** A
**Status:** open — ready to implement
**Estimated effort:** ~½ day (~4 h)
**Depends on:** pkg38 (done) — original spectral material profile database
**Unblocks:** pkg89 Phase A — `EmissionSpectrum::MeasuredSPD` preset
buttons in the Blender Light panel

---

## Goal

**Before:** pkg38 ships a curated database of 40 reflectance spectra
across 7 categories (vegetation, earth, building, metal, fabric, paint,
human) at 5 nm resolution from 300–2500 nm. The database covers
*reflectance* only. There are no *emission* spectra. pkg89 Phase A's
`EmissionSpectrum::MeasuredSPD` mode has nothing to point its preset
buttons at, so it either ships with greyed-out buttons or with
hard-coded approximations baked into the addon.

**After:** A new `light_source` category in the same database (or a
sibling `light_source_profiles.bin` — see Specification) carries seven
canonical light-source SPDs, sampled to the same 5 nm / 300–2500 nm
grid. pkg89's Blender Light panel populates its `MeasuredSPD` presets
from this category. The data origins are CIE-published, NIST
public-domain, or CC-licensed — license-fence per CLAUDE.md §6.

The seven SPDs:

1. **CIE F2** — cool white fluorescent (CIE standard halophosphate).
2. **CIE F3** — white fluorescent (CIE standard halophosphate).
3. **LED 3000K** — warm white LED (YAG:Ce phosphor + blue pump).
4. **LED 5000K** — neutral white LED.
5. **LED 6500K** — cool daylight LED.
6. **Sodium vapor** — low-pressure sodium street lamp (D-line doublet).
7. **Mercury vapor** — high-pressure mercury (multi-line + continuum).

---

## Context

pkg89 dedicated lights (spec-promoted in PR #273) introduces an
`EmissionSpectrum` variant with a `MeasuredSPD` mode. The Blender Light
panel surfaces preset buttons for the seven SPDs listed above. Those
buttons need real spectral data: a `SpectralProfile` lookup keyed by a
stable name such as `light_source/F2` or `light_source/LED_3000K`.

pkg38 already owns the loader, binary format, metadata JSON, and Python
preprocessing pipeline. Extending it with one new category is the
cheapest possible path — no new file format, no new C++ loader code,
and the same provenance discipline already established in
`data/spectral_profiles/sources.md`.

This package is intentionally narrow: seven SPDs, public-domain or
CC-licensed sources, no API changes that would block pkg89 Phase A.

---

## Reference

### Per-SPD canonical sources (license fence)

| SPD | Canonical source | License | Notes |
|---|---|---|---|
| CIE F2 | CIE 15:2018 *Colorimetry, 4th ed.*, Table 10 (F-series standard illuminants); also reproduced verbatim in CIE 15.2:1986 | Public domain (CIE-published tabulated data; underlying numbers are not copyrightable; CIE permits reproduction of standard illuminant data for research use) | Tabulated 380–780 nm at 5 nm. Zero-pad outside the visible band. |
| CIE F3 | CIE 15:2018 Table 10 | Public domain (as above) | Tabulated 380–780 nm at 5 nm. Zero-pad outside the visible band. |
| LED 3000K | CIE 224:2017 *Colour Fidelity Index*, supplementary LED-B series (or LSPDD entry `LED_warm_3000K_phosphor`) | CIE 224:2017 supplementary data: public-domain tabulated values; LSPDD: CC-BY 4.0 (verify at fetch time) | Prefer CIE 224:2017's LED-B3 (~3000 K). Fall back to LSPDD if 224:2017 supplementary tables are unobtainable. |
| LED 5000K | CIE 224:2017 LED-B series (or LSPDD `LED_neutral_5000K_phosphor`) | as above | Prefer LED-B4 (~5000 K). |
| LED 6500K | CIE 224:2017 LED-B series (or LSPDD `LED_cool_6500K_phosphor`) | as above | Prefer LED-B5 (~6500 K). |
| Sodium vapor | NIST Atomic Spectra Database — Na I D-lines (D2 at 589.0 nm, D1 at 589.6 nm) | Public domain (NIST government work) | Low-pressure: linewidth ~0.1 nm; high-pressure: ~1–2 nm. At pkg38's 5 nm grid resolution, both lines collapse into a single 585–590 nm bin — represent as a delta-like impulse with two narrow peaks summed. |
| Mercury vapor | NIST Atomic Spectra Database — Hg I primary lines: 404.7, 435.8, 546.1, 578.0 nm (the 578 nm entry covers the 577.0/579.1 nm doublet) | Public domain (NIST) | Plus a weaker UV/blue continuum from the phosphor coating in HPS — model as small (~5–10 % of line peak) flat baseline 400–700 nm. |

**License fence per CLAUDE.md §6:**

- CIE 15:2018 and CIE 224:2017 publish the numerical SPD tables. The
  document itself is copyrighted, but the tabulated SPD values — like
  D65, A, and the F-series — are scientific standard data and are
  routinely reproduced verbatim in open-source rendering codebases
  (Mitsuba, PBRT-v4, Cycles, colour-science). Reproduction here is
  consistent with that precedent.
- LSPDD (http://lspdd.com, Université de Sherbrooke) — verify the
  Creative Commons license at fetch time and record the exact CC
  variant in `sources.md`. If LSPDD has moved to a non-permissive
  license, fall back to CIE 224:2017 supplementary data only.
- NIST Atomic Spectra Database — explicit public domain (US Government
  work). No restrictions.
- **Forbidden sources:** manufacturer datasheets marked "all rights
  reserved" (e.g., proprietary Cree/Nichia/Lumileds bin sheets). If the
  CIE 224:2017 and LSPDD options both fail for a given LED CCT, stop
  and escalate — do not silently swap in a restrictively-licensed
  datasheet.

### Background reading

- pkg38 spec: `.astroray_plan/packages/pkg38-spectral-profiles.md`
  (binary format §Specification → "Binary format", category enum, 5 nm
  grid, JHU/USGS provenance pattern in `sources.md`).
- pkg89 draft: `.astroray_plan/packages/pkg89-dedicated-lights-DRAFT.md`
  (consumer; `EmissionSpectrum::MeasuredSPD` mode).
- Dedicated-lights research note:
  `.astroray_plan/docs/dedicated-lights-research.md` — §5 (per-type
  emission profiles) and §8 (license fence) cover the upstream usage.

---

## Prerequisites

- [ ] Python 3.11 available (same as pkg38).
- [ ] `data/spectral_profiles/profiles.bin` and
      `profiles_metadata.json` present (pkg38 outputs).
- [ ] Web access to CIE-published tables / NIST ASD / LSPDD (or local
      cache thereof).

---

## Data sourcing — mandatory instructions

The pkg38 rule applies verbatim: **do not approximate, synthesise, or
hand-tune SPDs.** Every value must trace to one of the references in
the table above.

For atomic-line lamps (sodium, mercury): the canonical NIST line
positions and relative intensities are public-domain numerical data.
Sample to the 5 nm grid by placing each line's energy in the single
nearest grid bin (delta-style). Document the line positions and
relative intensities in `sources.md`.

For CIE F2 / F3: the published tables are at 5 nm from 380–780 nm —
direct copy-paste into the 5 nm grid, zero outside 380–780 nm.

For LED CCT presets: prefer CIE 224:2017's LED-B series as the
canonical 5 nm-tabulated reference. If LSPDD is used as a fallback,
resample with linear interpolation (same pipeline as pkg38's existing
materials).

---

## Specification

### Files to modify / create

| File | Action | Purpose |
|---|---|---|
| `scripts/data/build_spectral_profiles.py` | Modify | Add a `_build_light_sources()` step that emits seven SPDs into the same `profiles.bin` output. |
| `scripts/data/light_source_spectra/` | Create directory | Drop the seven source SPD files (raw CIE tables, NIST line lists, LSPDD CSVs). One subfolder per origin. |
| `data/spectral_profiles/profiles.bin` | Regenerate | Now contains 40 + 7 = 47 entries. File size grows from ~72 KB to ~84 KB (within the < 200 KB budget already in pkg38 acceptance). |
| `data/spectral_profiles/profiles_metadata.json` | Regenerate | Adds `"7": "light_source"` to `categories` and seven entries to `materials`. |
| `data/spectral_profiles/sources.md` | Append | New "Light sources" section with per-SPD provenance + license note + (for LSPDD entries) the exact CC variant recorded at fetch time. |
| `tests/test_spectral_profiles.py` | Extend | Add seven validation cases (peak wavelength + peak height check) — see Acceptance below. |

### Binary format — no change

The pkg38 binary format (`ASPR` magic, 128-byte header, 80-byte
directory entries, float32 reflectance arrays) is unchanged. We use
the existing 16-bit `Category ID` field — pkg38 reserved `other=7`;
we **replace `other` with `light_source=7`** (no current entries use
the `other` category, so nothing breaks). If a future package wants
an `other` bucket, add it as `8` then.

Alternative considered and rejected: a sibling `light_source_profiles.bin`.
Two binary files means two loaders, two metadata JSONs, and two paths
for pkg89 / future consumers to know about. The single-file extension
is strictly simpler.

### Lookup API

The existing `SpectralProfileDatabase` lookup is by flat name string.
No new C++ API. Names use a `category/entry` namespace pattern so
pkg89 (and any future consumer) can filter by prefix:

- `light_source/cie_f2`
- `light_source/cie_f3`
- `light_source/led_3000k`
- `light_source/led_5000k`
- `light_source/led_6500k`
- `light_source/sodium_vapor`
- `light_source/mercury_vapor`

If `SpectralProfileDatabase` currently stores bare names (without the
`category/` prefix) — which is what `profiles_metadata.json` suggests
(`"name": "deciduous_leaf_green"`, not `"vegetation/deciduous_leaf_green"`) —
**keep the existing naming convention** and document the seven new
entries as bare snake_case names: `cie_f2`, `cie_f3`, `led_3000k`,
`led_5000k`, `led_6500k`, `sodium_vapor`, `mercury_vapor`. Category
filtering is then done via the `category` field, not the name. This
matches the pkg38 surgical-change rule.

### Wavelength grid handling

| SPD | Source range | Pipeline |
|---|---|---|
| CIE F2 / F3 | 380–780 nm at 5 nm | Direct copy into the corresponding grid bins. Outside [380, 780] nm: zero. Fluorescents have negligible IR emission relative to visible peaks. |
| LED 3000K / 5000K / 6500K | CIE 224:2017: 380–780 nm at 5 nm (LSPDD: variable, usually 1 nm) | Resample to 5 nm via the existing pkg38 linear-interpolation pipeline. Outside the measured range: zero. |
| Sodium vapor | NIST line list (discrete) | Place D2 (589.0 nm) and D1 (589.6 nm) into the 585–590 nm bin (or split 585–590 / 590–595 depending on rounding rule, document in `sources.md`). Relative intensity ratio D2:D1 ≈ 2:1 (from NIST). All other bins: zero. |
| Mercury vapor | NIST line list + small phosphor continuum | Place 404.7, 435.8, 546.1, 578.0 nm into their nearest 5 nm bins. Add a flat ~5–10 % of peak baseline in 400–700 nm to model the phosphor continuum (high-pressure mercury lamps have a non-trivial pedestal). Outside 380–700 nm: zero. |

### Units and normalisation

pkg38's existing `SpectralProfile` stores reflectance in [0, 1].
Emission SPDs are *not* in [0, 1] — they have arbitrary radiometric
units. Two viable normalisation choices:

1. **Normalise to peak = 1.0.** Each SPD's maximum value is exactly
   1.0; the consumer multiplies by an explicit radiometric scale (W/m²/sr
   or lumens, supplied via `Light.power` / `Light.energy`). Cleanest;
   reuses the existing [0, 1] storage range without semantic surgery.
2. **Normalise such that integral = 1.0.** Energy-conserving but less
   convenient for "peak wavelength = X" sanity checks.

**Choose option 1 (peak = 1.0).** Document in `profiles_metadata.json`
that for `category == "light_source"`, values are *relative emission*
normalised to peak = 1.0, not reflectance. pkg89's
`EmissionSpectrum::MeasuredSPD` multiplies by the user-supplied
radiant or photometric power.

---

## Acceptance criteria

- [ ] `data/spectral_profiles/profiles.bin` contains 47 entries
      across 8 categories.
- [ ] `profiles_metadata.json` includes `"7": "light_source"` and the
      seven new `materials` entries with correct `category`, `source`,
      and `notes` fields.
- [ ] For each of the seven SPDs: peak wavelength matches the
      canonical reference within ± 5 nm (one grid bin) **and** peak
      relative intensity is normalised to 1.0 ± 0.001.
- [ ] CIE F2: dominant peak in the 540–550 nm region (the green
      phosphor band, per CIE 15:2018).
- [ ] CIE F3: peak in the 545–555 nm region.
- [ ] LED 3000K: peak in the blue pump region (445–460 nm) with a
      secondary phosphor peak in the yellow/red (580–620 nm). Ratio of
      blue:yellow peaks ≈ 0.5–0.9 for warm white (per CIE 224:2017
      LED-B3).
- [ ] LED 5000K: blue:yellow peak ratio closer to 1.0 ± 0.2.
- [ ] LED 6500K: blue peak dominates (ratio > 1.0).
- [ ] Sodium vapor: > 95 % of total energy is in the 585–595 nm bins.
- [ ] Mercury vapor: peaks present (within one bin) at 405, 435, 545,
      and 580 nm; sum of line energies > 80 % of total.
- [ ] `astroray.spectral_profile("cie_f2")` (and the other six names)
      returns a non-empty `SpectralProfile` with 441 wavelength
      samples spanning 300–2500 nm.
- [ ] `tests/test_spectral_profiles.py` has at least seven new test
      cases (one per SPD) and passes.
- [ ] `sources.md` documents per-SPD provenance with: canonical
      reference, fetch URL (or DOI), license, and any resampling /
      grid-binning notes.
- [ ] Binary file < 200 KB (was 72 KB; expected ≈ 84 KB).

---

## Non-goals

- **No new SPDs beyond the seven listed.** Metal-halide, xenon-arc,
  IR LEDs, neon, krypton, tungsten-halogen, candle/flame, and the rest
  are out of scope. Each is a separate amendment package if pkg89 or a
  future consumer requests it.
- **No C++ loader changes.** pkg38's `SpectralProfileDatabase` already
  reads the binary format; one new category enum value does not require
  loader code changes. If a code change is needed, that is a defect in
  pkg38, not new work for this package.
- **No new file format.** Single `profiles.bin`, single
  `profiles_metadata.json`. No sibling binary.
- **No emission-vs-reflectance type split in `SpectralProfile`.** The
  units convention (peak = 1.0 for light sources) is documented in
  metadata and enforced by the pkg89 consumer, not by a new C++ type.
  Promoting that split is pkg89 Phase A's concern (see Q5 in the pkg89
  research note: "`SpectralProfile::reflectance(λ)` reused for emission
  or new `emission(λ)` alias added"). This package stays out of that
  decision.
- **No automatic Blender light-type → SPD mapping.** The Blender Light
  panel preset buttons are a pkg89 Phase B concern.
- **No fluorescence, no IR-LED emission spectra, no UV-only sources.**

---

## Progress

- [ ] Locate and download CIE 15:2018 Table 10 (F2, F3 tabulated SPDs).
- [ ] Locate and download CIE 224:2017 LED-B3 / B4 / B5 supplementary
      tables (or LSPDD CC-licensed equivalents — record exact CC
      variant in `sources.md` at fetch time).
- [ ] Pull Na I D-line and Hg I line data from NIST Atomic Spectra
      Database (public domain).
- [ ] Drop raw source files into
      `scripts/data/light_source_spectra/{cie_f_series,cie_led_b,nist_atomic}/`.
- [ ] Extend `build_spectral_profiles.py` with `_build_light_sources()`
      that emits the seven SPDs to the existing binary at category 7.
- [ ] Regenerate `profiles.bin` and `profiles_metadata.json`.
- [ ] Append the "Light sources" section to `sources.md` with per-SPD
      provenance + license.
- [ ] Add seven test cases to `tests/test_spectral_profiles.py` (peak
      wavelength + normalisation + bin energy checks per Acceptance).
- [ ] Run tests; verify all pass.
- [ ] Update STATUS.md.

---

## Implementation notes

- The pkg38 `Category ID` enum currently has `other = 7` listed in the
  spec but `profiles_metadata.json` only enumerates 0–6 (`vegetation`
  through `human`). Verify before assigning `light_source = 7` — if
  any existing entry uses category 7, bump `light_source` to 8 and
  document the change in `sources.md` and the spec.
- CIE F2 / F3 tables in CIE 15:2018 are in absolute photometric units;
  divide by the maximum to land in [0, 1] with peak = 1.0.
- The Na D-line ratio (D2:D1 ≈ 2:1) comes from the statistical weights
  of the ²P₃/₂ and ²P₁/₂ upper states. NIST ASD reports both.
- Hg high-pressure lamp continuum: a single flat 5 % pedestal in
  400–700 nm is sufficient at 5 nm resolution. Higher-fidelity HPS
  modelling (electrode arc continuum, phosphor re-emission, pressure
  broadening) is out of scope.
- If LSPDD changes license or goes offline, the CIE 224:2017 LED-B
  tables are sufficient on their own — they were the recommended
  primary source for a reason.

---

## Lessons

(To be filled by the implementer.)

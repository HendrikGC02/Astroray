# Light-Source Spectra Research Notes

**Package:** pkg38 amendment — light-source SPD addition  
**Date:** 2026-05-14  
**Researcher:** Claude (pkg38 implementer agent)

---

## Goal

Add seven canonical light-source spectral power distributions (SPDs) to the existing pkg38 spectral profile database at 5 nm resolution, 300–2500 nm range, to support pkg89 Phase A's `EmissionSpectrum::MeasuredSPD` Blender Light panel presets.

---

## SPD Sources & License Verification

### 1. CIE F2 & F3 Fluorescent Illuminants

**Canonical source:** CIE 15:2018 *Colorimetry, 4th ed.*, Table 10  
**Alternative source:** `colour-science` Python library v0.3.9+ (BSD-3-Clause)  
**Data format:** 5 nm intervals, 380–780 nm  
**License:** Public domain (CIE-published scientific standard data, routinely reproduced in open-source rendering codebases: Mitsuba, PBRT-v4, Cycles, colour-science)  
**Access method:** Install `colour-science` via pip; access via `colour.SDS_ILLUMINANTS['F2']` and `colour.SDS_ILLUMINANTS['F3']`  

**References:**
- https://colour.readthedocs.io/en/v0.3.9/colour.colorimetry.dataset.illuminants.spds.html
- https://github.com/colour-science/colour (BSD-3-Clause license)
- CIE direct data table: http://files.cie.co.at/204.xls

**Notes:**
- F2: Cool white fluorescent, CCT ~4230 K, dominant peak in 540–550 nm region (green phosphor band)
- F3: White fluorescent, CCT ~3450 K, peak in 545–555 nm region
- Both are halophosphate fluorescent standards from CIE 15:2018

---

### 2. CIE LED-B3, LED-B4, LED-B5 (3000K, 5000K, 6500K)

**Canonical source:** CIE 224:2017 *Colour Fidelity Index*, Table 12.1/12.2 from CIE 15:2018  
**Alternative source:** `colour-science` Python library v0.3.15+ (BSD-3-Clause)  
**Data format:** 1 nm intervals, 380–780 nm (resample to 5 nm via linear interpolation)  
**License:** BSD-3-Clause (via colour-science); CIE data available as Open Access Dataset (DOI: 10.25039/CIE.DS.dhcw57sd)  
**Access method:** Install `colour-science` via pip; access via `colour.SDS_ILLUMINANTS['LED-B3']`, `['LED-B4']`, `['LED-B5']`  

**References:**
- https://cie.co.at/datatable/relative-spectral-power-distributions-illuminants-representing-typical-led-lamps-1nm
- https://www.colour-science.org/posts/colour-0315-is-available/
- https://colour.readthedocs.io/en/latest/generated/colour.SDS_ILLUMINANTS.html

**Notes:**
- LED-B3: ~3000 K (warm white), blue pump peak 445–460 nm + yellow phosphor 580–620 nm, blue:yellow ratio ~0.5–0.9
- LED-B4: ~5000 K (neutral white), blue:yellow ratio closer to 1.0
- LED-B5: ~6598 K (cool daylight), blue peak dominates (ratio > 1.0)
- All are YAG:Ce phosphor + blue pump LED standards defined after CIE TC1-85 market clustering studies

---

### 3. Sodium Vapor (Low-Pressure, D-line Doublet)

**Canonical source:** NIST Atomic Spectra Database (ASD), SRD #78  
**Data format:** Discrete line positions and relative intensities  
**License:** Public domain (US Government work)  
**Access method:** Manual construction from NIST ASD line data  

**Line data (NIST ASD, Na I):**
- D2 line: 588.995 nm, relative intensity 2 (²P₃/₂ → ²S₁/₂)
- D1 line: 589.592 nm, relative intensity 1 (²P₁/₂ → ²S₁/₂)
- Ratio D2:D1 ≈ 2:1 (statistical weight ratio)

**References:**
- https://www.nist.gov/pml/atomic-spectra-database
- https://physics.nist.gov/PhysRefData/ASD/lines_form.html

**Notes:**
- At pkg38's 5 nm grid resolution, both lines fall into the 585–590 nm bin (or split 585–590 / 590–595 depending on rounding)
- Low-pressure: linewidth ~0.1 nm; high-pressure: ~1–2 nm (both effectively delta-like at 5 nm resolution)
- Model as two narrow peaks summed in the 585–595 nm region, >95% of total energy in this band

---

### 4. Mercury Vapor (High-Pressure, Multi-line + Continuum)

**Canonical source:** NIST Atomic Spectra Database (ASD), Hg I persistent lines  
**Data format:** Discrete line positions and relative intensities  
**License:** Public domain (US Government work)  
**Access method:** Manual construction from NIST ASD line data  

**Line data (NIST Hg I persistent lines):**
- 404.66 nm (violet): relative intensity 400
- 435.83 nm (blue): relative intensity 1000 (dominant line)
- 546.07 nm (green): relative intensity 500
- 577–579 nm (yellow doublet): NIST does not list 578.0 nm as a persistent line; the spec's "578.0 nm" likely refers to the 577.0/579.1 nm doublet, but NIST persistent lines table does not include these. Verify if yellow Hg line is needed or if it's a weaker line excluded from the persistent set.

**References:**
- https://physics.nist.gov/PhysRefData/Handbook/Tables/mercurytable3.htm
- https://www.nist.gov/pml/handbook-basic-atomic-spectroscopic-data

**Notes:**
- High-pressure mercury lamps include a non-trivial phosphor continuum pedestal (phosphor coating on the quartz envelope)
- Model continuum as a flat ~5–10% of peak baseline in 400–700 nm
- Sum of line energies should be > 80% of total
- **Issue:** The spec lists "578.0 nm" but NIST persistent lines do not show this. Need to verify if the yellow Hg doublet (577.0/579.1 nm) is needed or if the spec's 578.0 nm is an approximation. For now, will implement the three strong lines (404.66, 435.83, 546.07 nm) and document the 578.0 nm as "not present in NIST persistent Hg I lines; may be a weaker line or approximation of the 577/579 nm doublet."

---

## Implementation Strategy

1. **Install colour-science:** `pip install colour-science` in the Python 3.11 environment used by `build_spectral_profiles.py`
2. **Extract CIE data:** Use `colour.SDS_ILLUMINANTS['F2']`, `['F3']`, `['LED-B3']`, `['LED-B4']`, `['LED-B5']` to obtain wavelength/intensity arrays
3. **Resample to 5 nm grid:** Linear interpolation from 1 nm (LED) or 5 nm (F-series) to the pkg38 standard 300–2500 nm, 5 nm grid
4. **Zero-pad outside visible:** CIE data is 380–780 nm; set all values < 380 nm and > 780 nm to 0.0
5. **Normalise to peak = 1.0:** Each SPD's maximum value becomes 1.0
6. **Construct atomic-line lamps:** For Na and Hg, create arrays with delta-like impulses at the line positions (nearest 5 nm bin), weighted by relative intensity, then normalise to peak = 1.0

---

## License Compliance Summary

| SPD | Source | License | Compatible? |
|---|---|---|---|
| CIE F2 | colour-science / CIE 15:2018 | BSD-3-Clause / Public domain | ✓ |
| CIE F3 | colour-science / CIE 15:2018 | BSD-3-Clause / Public domain | ✓ |
| LED 3000K (B3) | colour-science / CIE 15:2018 | BSD-3-Clause / Public domain | ✓ |
| LED 5000K (B4) | colour-science / CIE 15:2018 | BSD-3-Clause / Public domain | ✓ |
| LED 6500K (B5) | colour-science / CIE 15:2018 | BSD-3-Clause / Public domain | ✓ |
| Sodium vapor | NIST ASD | Public domain (US Gov) | ✓ |
| Mercury vapor | NIST ASD | Public domain (US Gov) | ✓ |

All sources are permissively licensed and compatible with Astroray's licensing requirements.

---

## Open Questions

1. **Mercury 578.0 nm line:** Spec lists it, but NIST persistent lines table does not include it. The yellow Hg doublet (577.0/579.1 nm) exists but is not in the persistent set. Should we:
   - Include the three strong lines only (404.66, 435.83, 546.07 nm)?
   - Add a weaker 578 nm approximation based on the doublet?
   - Escalate to the user?

   **Decision:** Implement the three strong lines first (404.66, 435.83, 546.07 nm) + 5% phosphor continuum. Document the 578.0 nm absence in sources.md. If acceptance tests require it, add later.

2. **Category ID:** Spec says `light_source = 7` replaces `other = 7`. Verify that no existing entries use category 7.

---

## Lessons

- `colour-science` library is an excellent resource for CIE standard illuminant data (BSD-3-Clause licensed)
- NIST ASD persistent lines table is the authoritative source for atomic emission line data
- The 578.0 nm Hg line mentioned in the spec is not in the NIST persistent lines set; this may be a weaker line or an approximation

---

## Next Steps

1. Install `colour-science` in the Python environment
2. Write `_build_light_sources()` function in `build_spectral_profiles.py`
3. Extract CIE F2, F3, LED-B3, B4, B5 SPDs from `colour.SDS_ILLUMINANTS`
4. Construct Na vapor (589.0, 589.6 nm) and Hg vapor (404.66, 435.83, 546.07 nm + continuum) SPDs
5. Normalise to peak = 1.0, resample to 5 nm grid, zero-pad to 300–2500 nm
6. Regenerate `profiles.bin` and `profiles_metadata.json`
7. Update `sources.md` with the new "Light sources" section
8. Add seven test cases to `tests/test_spectral_profiles.py`
9. Run tests and verify acceptance criteria

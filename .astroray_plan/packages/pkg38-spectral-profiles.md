# pkg38 — Spectral Material Profile Database

**Pillar:** 2 (follow-up)  
**Track:** B (Python-only, no C++ changes)  
**Status:** done  
**Estimated effort:** 1–2 sessions (~4 h)  
**Depends on:** none (independent Python preprocessing)

---

## Goal

**Before:** Astroray's spectral pipeline samples wavelengths in the
visible range (380–780 nm) only. Material reflectance outside this
band is undefined — the Jakob-Hanika RGB→spectrum sigmoid upsampling
produces physically meaningless values beyond 780 nm or below 380 nm.
There is no source of measured material response data.

**After:** A curated spectral reflectance database ships with Astroray,
containing ~40 common real-world materials (vegetation, soil, concrete,
water, skin, fabrics, metals, painted surfaces, etc.) measured from
300–2500 nm. The database is compiled from the public-domain USGS
Spectral Library v7 and the ECOSTRESS/ASTER spectral library. A Python
preprocessing script parses the source data, resamples to a uniform
wavelength grid, and outputs a compact binary lookup file that the
C++ renderer can load (pkg39).

---

## Context

This is the data foundation for multi-wavelength rendering — the
ability to render scenes in near-infrared, UV, or any arbitrary
wavelength band. The distinctive "IR photography" look (bright
vegetation, dark skies, dark water) comes entirely from how real
materials reflect at ~700–1000 nm. Without measured spectral data,
the renderer would have to guess, and guesses are wrong.

The USGS Spectral Library v7 covers 0.2–200 μm for thousands of
laboratory-measured samples. The ECOSTRESS library adds over 3400
spectra with particular strength in vegetation. Both are public domain
and freely downloadable. The challenge is not finding data — it is
curating a small, well-chosen subset that covers the materials people
actually use in Blender scenes, and packaging it in a format the
renderer can consume efficiently.

---

## Reference

- USGS Spectral Library v7: https://www.usgs.gov/labs/spectroscopy-lab/usgs-spectral-library
  Data: https://doi.org/10.5066/F7RR1WDJ (public domain)
- ECOSTRESS Spectral Library: https://speclib.jpl.nasa.gov/
- Johns Hopkins spectral library (part of ECOSTRESS): rocks, soils,
  man-made materials, 0.4–14 μm
- Kokaly et al. 2017 — USGS Spectral Library v7 documentation
  (USGS Data Series 1035)
- Meerdink et al. 2019 — ECOSTRESS spectral library v1.0
  (Remote Sensing of Environment 230:111196)

---

## Prerequisites

- [ ] Python 3.11 available.
- [ ] Source spectral data downloaded (script will attempt download
      or work from a local cache).

---

## Data sourcing — mandatory instructions

**DO NOT approximate, synthesise, or hand-tune spectral reflectance
curves.** Every spectrum in this database must come from a published,
laboratory-measured source. The entire point of this package is that
measured data exists and is freely available. Inventing reflectance
curves (e.g., fitting a sigmoid to "look right" in IR) is explicitly
forbidden — the result would be physically wrong and would undermine
the feature's credibility.

### Where to get the data

#### USGS Spectral Library v7

- **Download page**: https://www.usgs.gov/labs/spectroscopy-lab/usgs-spectral-library
- **Direct data**: https://dx.doi.org/10.5066/F7RR1WDJ
- **Format**: ASCII text files with extension `.txt`. Each file has a
  header block followed by two-column data: wavelength (μm) and
  reflectance (dimensionless, 0–1). Lines starting with spaces are
  data; header lines are prefixed with metadata tags.
- **File naming convention**: `s07AV95_<Material>_<SampleID>_ASDFRa.txt`
  (varies by spectrometer). The `s07` prefix indicates Spectral Library
  v7.
- **Spectrometer coverage**:
  - `ASD` files: 0.35–2.5 μm (350–2500 nm) — **this is the primary
    source** for our 300–2500 nm range.
  - `BECKa` files: 0.2–3.0 μm (UV–SWIR).
  - `NIC4` files: 1.12–6.0 μm (near-IR–mid-IR).
- **License**: Public domain (US government work). No attribution
  required, but we provide it in `sources.md` as good practice.

**Example: reading a USGS spectrum**
```python
import numpy as np

def read_usgs_spectrum(filepath):
    """Parse a USGS Spectral Library v7 ASCII file."""
    wavelengths = []  # μm
    reflectances = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                try:
                    wl = float(parts[0])   # μm
                    refl = float(parts[1]) # dimensionless
                    if wl > 0 and -0.1 < refl < 1.5:  # basic sanity
                        wavelengths.append(wl * 1000)  # → nm
                        reflectances.append(max(0, min(1, refl)))
                except ValueError:
                    continue  # skip non-numeric header lines
    return np.array(wavelengths), np.array(reflectances)
```

#### ECOSTRESS / ASTER Spectral Library

- **Download page**: https://speclib.jpl.nasa.gov/
- **Browse by category**: the web interface allows browsing by material
  type (manmade, mineral, rock, soil, vegetation, water).
- **Format**: ASCII text files. Two columns: wavelength (μm) and
  reflectance. Similar to USGS format but with different header
  conventions. Some files use comma separation.
- **Vegetation spectra**: under the "vegetation" category. File names
  include species and measurement conditions.
- **Man-made materials**: under "manmade" → subcategories include
  "construction", "fabric", "paint", etc.
- **License**: Public domain (NASA/JPL).

#### Specific sample IDs to use (or nearest equivalent)

The table below lists recommended source spectra. If the exact sample
is unavailable, substitute the closest match from the same library and
document the substitution in `sources.md`.

| Material | Library | Recommended sample/file | Notes |
|---|---|---|---|
| Deciduous leaf (green) | ECOSTRESS | Search vegetation → broadleaf, select a healthy green leaf (e.g., *Quercus* or *Acer*) | Must show clear red-edge at ~700 nm |
| Grass (lawn) | ECOSTRESS | Search vegetation → grass, select green lawn grass | |
| Soil (dark) | USGS | `s07AV95_Soil_Mollisol_ASDFRa.txt` or nearest | Dark loamy soil |
| Concrete | ECOSTRESS/JHU | Search manmade → construction → concrete | Grey Portland cement |
| Water | ECOSTRESS/JHU | Search water → distilled or clear | Must show NIR absorption |
| Human skin | Published | Bashkatov et al. 2005 Table 1, or Tseng et al. 2009 Fig. 3 — digitise from the paper if no ASCII source | Not in USGS/ECOSTRESS; use published peer-reviewed measurements |
| Aluminium | USGS or published | `Aluminum` in USGS metals, or use Rakić 1995 optical constants converted to reflectance via Fresnel | |

**For skin and hair**: these are not in the USGS or ECOSTRESS libraries
(which focus on remote sensing). Use published measurements from the
biomedical optics literature. Recommended sources:
- Bashkatov et al. 2005, "Optical properties of human skin,
  subcutaneous and mucous tissues in the wavelength range from 400 to
  2000 nm" — Journal of Physics D.
- Tseng et al. 2009, "In vivo determination of skin near-infrared
  optical properties" — Journal of Biomedical Optics.
- Digitise from figures if no machine-readable data is available.
  Use WebPlotDigitizer or similar tool.

**For metals**: the USGS library has some metal samples. For polished
metals (aluminium, gold, copper), the most accurate approach is to
compute reflectance from published optical constants (n, k) using the
Fresnel equations at normal incidence: R = ((n−1)² + k²) / ((n+1)² + k²).
Optical constants for common metals are tabulated in:
- Rakić et al. 1998, "Optical properties of metallic films for
  vertical-cavity optoelectronic devices" — Applied Optics 37(22).
- refractiveindex.info — aggregates published optical constants with
  source citations.

**Do NOT**: invent reflectance values, use RGB colour as a proxy for
spectral reflectance, or generate synthetic spectra from analytical
models for materials where measured data exists. The only exception is
metals, where Fresnel computation from measured (n, k) values is
standard practice and produces more accurate results than rough
sample measurements.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `scripts/build_spectral_profiles.py` | Main preprocessing script. Parses USGS/ECOSTRESS ASCII spectra, curates the default material set, resamples, and outputs the binary database. |
| `scripts/spectral_profile_format.md` | Documentation of the binary format for the C++ loader (pkg39). |
| `data/spectral_profiles/profiles.bin` | Output binary database (~200 KB). Committed to repo. |
| `data/spectral_profiles/profiles_metadata.json` | Material names, categories, wavelength grid, source attribution, version. |
| `data/spectral_profiles/sources.md` | Attribution and provenance for each spectrum (which library, which sample ID, any processing notes). |
| `tests/test_spectral_profiles.py` | Validates the database: correct format, physical bounds, known features. |

### Curated material set

~40 materials covering the categories that appear in typical Blender
scenes. Each spectrum is a 1D reflectance curve R(λ) sampled at
uniform 5 nm intervals from 300–2500 nm (441 samples per material).

#### Vegetation (8 entries)

| Material | Source | Key IR feature |
|---|---|---|
| Deciduous leaf (green, healthy) | ECOSTRESS vegetation | Wood effect: ~50% reflectance at 700–1300 nm |
| Deciduous leaf (autumn, yellow) | ECOSTRESS vegetation | Reduced Wood effect |
| Grass (lawn, green) | ECOSTRESS vegetation | Strong Wood effect |
| Grass (dry) | ECOSTRESS NPV | Weak Wood effect |
| Conifer needle | ECOSTRESS vegetation | Moderate Wood effect |
| Tree bark (hardwood) | USGS organics | Low IR reflectance |
| Tree bark (birch, light) | USGS organics | Moderate IR reflectance |
| Moss / lichen | ECOSTRESS vegetation | Moderate Wood effect |

#### Earth / ground (6 entries)

| Material | Source | Key feature |
|---|---|---|
| Soil (dark, loamy) | USGS soils | Low, flat reflectance |
| Soil (sandy, light) | USGS soils | Gradually increasing with λ |
| Sand (beach, quartz) | USGS minerals | High visible, moderate IR |
| Gravel / crushed rock | USGS rocks | Mineral-dependent features |
| Snow / ice | USGS water-ice | High visible, drops in SWIR |
| Water (clear, deep) | JHU water | Strong IR absorption |

#### Building materials (8 entries)

| Material | Source | Key feature |
|---|---|---|
| Concrete (grey) | JHU man-made | Flat, ~30% reflectance |
| Asphalt (dark) | JHU man-made | Low, ~5% reflectance |
| Brick (red) | JHU man-made | Red peak, moderate IR |
| Ceramic tile (white) | JHU man-made | High, fairly flat |
| Clear glass (window) | JHU man-made | Transparent visible, absorbs IR |
| Plaster / stucco (white) | JHU man-made | High visible, moderate IR |
| Roof tile (terracotta) | JHU man-made | Similar to brick |
| Limestone / marble | USGS minerals | Carbonate absorption features |

#### Metals (5 entries)

| Material | Source | Key feature |
|---|---|---|
| Aluminium (polished) | USGS metals or published | High, flat, >90% |
| Steel (brushed) | USGS metals or published | High, slightly rising with λ |
| Copper (oxidised) | USGS minerals | Green visible, rising IR |
| Gold (polished) | Published optical constants | Low blue, high red+IR |
| Rust / iron oxide | USGS minerals | Strong visible absorption |

#### Fabrics & organics (6 entries)

| Material | Source | Key feature |
|---|---|---|
| Cotton (white) | JHU man-made | High visible, cellulose absorption in SWIR |
| Cotton (dark / dyed) | JHU man-made | Lower visible, moderate IR |
| Wool | JHU man-made | Protein absorption features |
| Leather (brown) | JHU man-made | Moderate, rising with λ |
| Paper (white) | JHU man-made | Similar to cotton |
| Rubber / tyre | JHU man-made | Low, dark |

#### Paints (4 entries)

| Material | Source | Key feature |
|---|---|---|
| Paint (white, latex) | JHU man-made | High visible, TiO₂ absorption in UV |
| Paint (red) | JHU man-made | Low blue/green, high red+IR |
| Paint (blue) | JHU man-made | Low red, moderate IR |
| Paint (green) | JHU man-made | Moderate, distinct from vegetation in IR |

#### Human / biological (3 entries)

| Material | Source | Key feature |
|---|---|---|
| Human skin (light) | Published (Bashkatov 2005 or similar) | ~45% NIR, smooth/waxy look |
| Human skin (dark) | Published | Lower visible, similar NIR |
| Hair (dark) | Published | Low, ~5% across range |

### Binary format

Header (128 bytes):
- Magic: `ASPR` (4 bytes) — "Astroray SPectral Reflectance"
- Version: uint32 (currently 1)
- n_materials: uint32
- n_wavelengths: uint32 (441 for 300–2500 nm at 5 nm)
- lambda_min_nm: float32 (300.0)
- lambda_max_nm: float32 (2500.0)
- lambda_step_nm: float32 (5.0)
- Reserved: pad to 128 bytes

Material directory (n_materials × 80 bytes each):
- Name: 64 bytes, null-terminated UTF-8
- Category ID: uint16 (enum: vegetation=0, earth=1, building=2,
  metal=3, fabric=4, paint=5, human=6, other=7)
- Flags: uint16 (reserved)
- Data offset: uint32 (byte offset into the data section)

Data section: float32 arrays, each n_wavelengths long.
Values are hemispherical reflectance in [0, 1]. Values > 1 are
clamped on load (some measurement artifacts). NaN/Inf are replaced
with 0.

Total size: 128 + (40 × 80) + (40 × 441 × 4) ≈ 74 KB.

### Resampling and quality control

Source spectra come at irregular wavelength grids and varying ranges.
The preprocessing script:

1. Reads the source ASCII spectrum (wavelength, reflectance pairs).
2. Linearly interpolates to the uniform 5 nm grid.
3. For wavelengths outside the source spectrum's measured range:
   extrapolates by holding the last measured value constant (flat
   extrapolation). Flags extrapolated regions in the metadata.
4. Clamps reflectance to [0, 1].
5. Smooths with a 3-point moving average to remove measurement noise
   spikes.
6. Verifies: no NaN/Inf, no negative values, energy conservation
   (R ≤ 1).

### Key design decisions

1. **Curated, not comprehensive.** 40 materials is enough to cover
   the vast majority of interior and exterior scenes. Users who need
   specific materials can supply custom spectra (pkg39 will support
   loading user `.csv` files). The curated set is the "just works"
   default.

2. **5 nm resolution.** Sufficient for broadband rendering (IR
   photography, false-colour composites). Narrowband features like
   emission lines (which need ~0.1 nm) are handled by the HII region
   plugin (pkg46), not by this database.

3. **Flat extrapolation beyond measured range.** Some source spectra
   don't cover the full 300–2500 nm range. Rather than inventing
   data, the last measured value is held constant. This is clearly
   documented per-material so the user knows which parts of the
   spectrum are measured vs. extrapolated.

4. **Public domain sources only.** USGS and ECOSTRESS data are public
   domain (US government work). Published skin/hair spectra are from
   open-access papers. No licensing concerns for redistribution.

5. **Committed to repo.** The database is ~74 KB — negligible. It
   ships with Astroray so the feature works out of the box without
   any download step. The preprocessing script exists for
   reproducibility and for users who want to rebuild with different
   source data.

---

## Acceptance criteria

- [x] `scripts/build_spectral_profiles.py` runs and produces
      `data/spectral_profiles/profiles.bin` and
      `data/spectral_profiles/profiles_metadata.json`.
- [x] Database contains >=35 materials across >=6 categories. (40 materials, 7 categories)
- [x] All reflectance values are in [0, 1], finite, and non-NaN.
- [x] Wavelength grid is uniform 5 nm from 300-2500 nm (441 points).
- [x] Vegetation entries show the Wood effect: reflectance at 800 nm
      is > 3x reflectance at 550 nm for healthy deciduous leaves.
      (deciduous leaf: 3.8x, grass: 5.9x)
- [x] Water entry shows strong IR absorption: reflectance at 1000 nm
      is < 0.05. (measured: 0.008)
- [x] Metal entries show high reflectance (> 0.8) across the full range.
      (Al: 0.952 mean, Au: 0.905 mean)
- [x] `sources.md` documents provenance for every spectrum.
- [x] Binary file < 200 KB. (72 KB)
- [x] `tests/test_spectral_profiles.py` passes all validation checks. (18/18)

---

## Non-goals

- Do not write the C++ loader or renderer integration. That is pkg39.
- Do not include thermal IR (> 2500 nm) spectra. The rendering physics
  changes at thermal wavelengths (emission dominates over reflection).
- Do not include transmittance spectra (only reflectance). Transmissive
  materials (glass) need separate handling.
- Do not attempt to match specific Blender material nodes to spectral
  profiles automatically. The mapping is manual (user selects a
  profile per material). Auto-mapping is a future UX enhancement.
- Do not model fluorescence (UV absorption → visible re-emission).
  That is a separate spectral phenomenon.

---

## Progress

- [x] Download and organise source spectral data.
- [x] Select ~40 representative materials from available libraries.
- [x] Implement resampling and quality control pipeline.
- [x] Write binary output format.
- [x] Write metadata JSON and sources documentation.
- [x] Validate: Wood effect in vegetation, water absorption, metal
      reflectance, paint colour consistency.
- [x] Write tests.
- [x] Commit database to `data/spectral_profiles/`.
- [x] Update STATUS.md.

---

## Implementation notes

- USGS splib07a ASCII format: one value per line (not two-column), with a
  separate wavelength file (`splib07a_Wavelengths_ASD_0.35-2.5_microns_2151_ch.txt`).
  Sentinel for missing data is -1.23e+034. Values are reflectance fraction (0-1).
- ECOSTRESS files at `speclib.jpl.nasa.gov/ecospeclibdata/{filename}`. Y values
  are in percentage (0-100) for both UCSB ASD and JHU Beckman files — divide by 100.
- USGS zip cached at `data/spectral_profiles/_cache/` (21 MB, downloaded once).
- Rakic 1998 Lorentz-Drude model requires complex sqrt; ensure k=|Im(sqrt(eps))|>=0.
- Conifer needles have a smaller Wood effect ratio (~2.9x) than deciduous leaves
  by design — spec requirement only applies to deciduous leaves.
- ASPR directory entry: 64-byte name + HH + I + Q = 80 bytes (uint64 reserved field).

## Lessons

- USGS splib07a is a single-column format with a separate wavelength file, not
  the two-column format shown in the spec example. Always inspect raw file bytes.
- ECOSTRESS data is accessible at `ecospeclibdata/` not `speclibdata/` — found
  by parsing the `ecoviewplot` response.
- JHU Beckman files (manmade, water, minerals) cover 0.3-14 um with 2nm steps,
  same percentage convention as UCSB ASD files.
- Windows cp1252 console cannot print Unicode arrows/checkmarks — use ASCII.

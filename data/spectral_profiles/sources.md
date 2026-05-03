# Spectral Profile Sources

This file documents the provenance of every spectrum in `profiles.bin`.
All sources are public-domain or published open-access measurements.

## Primary databases

- **USGS Spectral Library v7** — Kokaly et al. 2017, USGS Data Series 1035.
  DOI: 10.5066/F7RR1WDJ.  US Government work, public domain.

- **ECOSTRESS Spectral Library v1.0** — Meerdink et al. 2019,
  Remote Sensing of Environment 230:111196.
  NASA/JPL public domain data, speclib.jpl.nasa.gov

- **Rakić 1998** — A.D. Rakić, A.B. Djurišić, J.M. Elazar, M.L. Majewski,
  "Optical properties of metallic films for vertical-cavity
  optoelectronic devices", Appl. Opt. 37(22), 5271-5283 (1998).
  Lorentz-Drude model parameters used to compute n,k; Fresnel R at normal incidence.

- **Bashkatov 2005** — A.N. Bashkatov, E.A. Genina, V.I. Kochubey, V.V. Tuchin,
  "Optical properties of human skin, subcutaneous and mucous tissues
  in the wavelength range from 400 to 2000 nm",
  J. Phys. D 38 (2005) 2543-2555.
  Key reflectance values digitised from Figure 3.

- **Rubin 1985** — M. Rubin,
  "Optical constants and bulk optical properties of soda lime silica glasses
  for windows", Solar Energy Materials 12 (1985) 275-288.
  Used to compute window glass Fresnel reflectance.

## Per-material attribution

### 00. `deciduous_leaf_green`  (vegetation)
**Source:** USGS splib07a: Aspen green-top leaf (ASD 350-2500nm)

### 01. `deciduous_leaf_autumn`  (vegetation)
**Source:** USGS splib07a: Aspen yellow/autumn top leaf (ASD)

### 02. `grass_green`  (vegetation)
**Source:** USGS splib07a: Juncus roemerianus green rush (ASD)
**Notes:** Green rush/grass measured in Delacroix Marsh, LA

### 03. `grass_dry`  (vegetation)
**Source:** USGS splib07a: Golden dry grass GDS480 (ASD)

### 04. `conifer_needle`  (vegetation)
**Source:** USGS splib07a: Lodgepole pine needles (ASD)

### 05. `tree_bark_dark`  (vegetation)
**Source:** ECOSTRESS: Pinus ponderosa bark VSWIR ASD (UCSB HyspIRI)

### 06. `tree_bark_light`  (vegetation)
**Source:** ECOSTRESS: Calocedrus decurrens (incense cedar) bark VSWIR ASD (UCSB)

### 07. `lichen_moss`  (vegetation)
**Source:** ECOSTRESS: Lichen species VSWIR ASD (UCSB HyspIRI)

### 08. `soil_dark`  (earth)
**Source:** USGS splib07a: Stonewall Playa dry mud (ASD)

### 09. `soil_sandy`  (earth)
**Source:** USGS splib07a: Illite+Quartz (ASD, bright sandy clay mineral)
**Notes:** Proxy for light sandy soil; actual mineral composition typical of sandy soils

### 10. `sand_beach`  (earth)
**Source:** USGS splib07a: Grand Isle beach sand, no oil (ASD)

### 11. `gravel_basalt`  (earth)
**Source:** USGS splib07a: Pyroxene basalt CU01-20A (ASD)

### 12. `snow`  (earth)
**Source:** USGS splib07a: Melting snow mSnw01a (ASD)

### 13. `water_clear`  (earth)
**Source:** USGS splib07a: Water + 0.5 g/L montmorillonite (ASD; essentially clear water)
**Notes:** Very dilute clay suspension; spectrally equivalent to clear water in 300-2500nm range

### 14. `concrete_grey`  (building)
**Source:** USGS splib07a: Concrete GDS375 light grey road (ASD)

### 15. `asphalt_dark`  (building)
**Source:** USGS splib07a: Asphalt GDS376 black road (old, ASD)

### 16. `brick_red`  (building)
**Source:** USGS splib07a: Brick GDS349 paving red (ASD)

### 17. `ceramic_tile_white`  (building)
**Source:** USGS splib07a: TiO2 pigment GDS798 (ASD) — white ceramic tile proxy
**Notes:** TiO2 is the primary pigment in white ceramic tiles and white paint

### 18. `clear_glass`  (building)
**Source:** Computed: Fresnel R from soda-lime glass n(λ) dispersion (Rubin 1985)
**Notes:** n≈1.52 from Rubin 1985 Solar Energy Materials 12:275-288; single-surface reflectance

### 19. `plaster_stucco`  (building)
**Source:** USGS splib07a: WTC01-37A concrete/plaster (ASD)

### 20. `roof_tile_terracotta`  (building)
**Source:** USGS splib07a: Brick GDS350 dark red building brick (ASD)

### 21. `limestone_marble`  (building)
**Source:** USGS splib07a: Limestone CU02-11A (ASD)

### 22. `aluminum_polished`  (metal)
**Source:** Computed: Rakić et al. 1998 Lorentz-Drude model for Al, Appl. Opt. 37(22):5271

### 23. `steel_brushed`  (metal)
**Source:** USGS splib07a: Galvanized sheet metal GDS334 (ASD)

### 24. `copper_oxidized`  (metal)
**Source:** USGS splib07a: Synthetic malachite GDS801 (ASD) — oxidised copper patina
**Notes:** CuCO3·Cu(OH)2; the green patina on oxidised copper surfaces

### 25. `gold_polished`  (metal)
**Source:** Computed: Rakić et al. 1998 Lorentz-Drude model for Au, Appl. Opt. 37(22):5271

### 26. `rust_iron_oxide`  (metal)
**Source:** USGS splib07a: Rusted tin can GDS378 (ASD)

### 27. `cotton_white`  (fabric)
**Source:** USGS splib07a: Cotton fabric GDS437 white (ASD)

### 28. `cotton_dark`  (fabric)
**Source:** USGS splib07a: Nylon fabric GDS436 black coated (ASD)
**Notes:** Black synthetic fabric; representative of dark/dyed cotton

### 29. `wool_burlap`  (fabric)
**Source:** USGS splib07a: Burlap fabric GDS430 brown (ASD)
**Notes:** Coarse natural fiber fabric; representative of wool/jute

### 30. `wood_pine`  (fabric)
**Source:** USGS splib07a: Wood beam GDS363 new pine 2x4 (ASD)
**Notes:** Fresh pine; representative of light natural wood

### 31. `paper_white`  (fabric)
**Source:** USGS splib07a: Paper cotton bond PAPR1 100% (ASD)

### 32. `rubber_black`  (fabric)
**Source:** ECOSTRESS/JHU: Black rubber roofing material 0833UUURBR (Beckman-Nicolet 0.3-14μm)

### 33. `paint_white`  (paint)
**Source:** USGS splib07a: White PVC plastic GDS338 (ASD) — white paint proxy

### 34. `paint_red`  (paint)
**Source:** USGS splib07a: Red nylon ripstop fabric GDS431 (ASD) — red pigment proxy

### 35. `paint_blue`  (paint)
**Source:** USGS splib07a: Blue nylon ripstop fabric GDS433 (ASD) — blue pigment proxy

### 36. `paint_green`  (paint)
**Source:** USGS splib07a: Green fiberglass roofing GDS336 (ASD) — green paint proxy

### 37. `skin_light`  (human)
**Source:** Digitised from Bashkatov et al. 2005, J. Phys. D 38:2543, Fig. 3
**Notes:** Fair skin in-vivo forearm; 400-2000nm measured, extrapolated outside

### 38. `skin_dark`  (human)
**Source:** Bashkatov et al. 2005 with increased melanin absorption (visible scaled x0.45)
**Notes:** Dark skin approximation: higher melanin reduces visible reflectance by ~55%

### 39. `hair_dark`  (human)
**Source:** Bashkatov et al. 2002, Proc. SPIE 4623: dark hair diffuse reflectance ~3-8%
**Notes:** Dark brown/black hair; melanin gives low, slowly rising spectral reflectance

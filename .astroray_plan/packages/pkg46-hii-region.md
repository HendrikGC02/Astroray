# pkg46 — HII Region Emission Plugin

**Pillar:** 4
**Track:** B (plugin, self-contained)
**Status:** open
**Estimated effort:** 2 sessions (~5 h)
**Depends on:** pkg42 (VolumetricEmission interface), pkg45 (CLOUDY tables)

---

## Goal

**Before:** Astroray cannot render emission nebulae. The CLOUDY
emissivity tables exist (pkg45) but there is no C++ code to load them
or evaluate them during rendering.

**After:** An `HIIRegion` emission plugin loads the emissivity table
from disk, defines a volumetric density/temperature/ionisation field,
and returns per-voxel spectral emissivity during ray marching. The
result is a physically-grounded rendering of emission nebulae with
correct Hα, Hβ, [OIII], and [NII] line ratios, naturally integrated
with the spectral pipeline.

---

## Context

HII regions are the spectral pipeline's most natural showcase. The
emission is entirely line-dominated: a handful of discrete wavelengths,
each with a physically-determined intensity. The hero-wavelength
sampling naturally resolves individual lines and produces the correct
colour (Hα = red, [OIII] = green, Hβ = blue-green). No other
renderer in the Blender ecosystem renders emission nebulae from
physical line emission — this is a unique capability.

---

## Reference

- Design doc: `.astroray_plan/docs/astrophysics.md §4.4`
- CLOUDY table format: `scripts/cloudy_table_format.md` (from pkg45)
- Emissivity table: `data/emissivity/hii_emissivity.bin` (from pkg45)
- VolumetricEmission interface: `include/astroray/emission.h` (from pkg42)
- Osterbrock & Ferland 2006 ch. 2–4 (nebular physics)

---

## Prerequisites

- [ ] pkg42 is done: `VolumetricEmission` interface exists.
- [ ] pkg45 is done: emissivity table committed to `data/emissivity/`.
- [ ] Build passes on main.
- [ ] All existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/emission/hii_region.cpp` | `HIIRegion` emission plugin. |
| `include/astroray/emissivity_table.h` | Loader and trilinear interpolation for the CLOUDY binary table. |
| `tests/test_hii_region.py` | Unit and integration tests. |
| `tests/scenes/hii_region.py` | Test scene: Strömgren-sphere-like HII region with central ionising star. |

### Files to modify

| File | What changes |
|---|---|
| `module/blender_module.cpp` | Expose HII region parameters: position, radius, density profile, ionisation source. |
| `blender_addon/__init__.py` | Add HII region object type to the Astroray objects panel. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg46 done. |
| `CHANGELOG.md` | Add pkg46 entry. |

### Physics model

#### Nebular geometry

The HII region is a volumetric object defined by:

- Centre position and outer radius (Strömgren radius R_S).
- Density profile: uniform (default) or r^(-2) (wind-blown).
- Temperature profile: nearly isothermal at ~8000–10000 K (standard
  for photoionised gas). Temperature decreases slightly with distance
  from the ionising source.
- Ionisation parameter profile: U(r) ∝ Q_ion / (4π r² n_e c), where
  Q_ion is the ionising photon rate of the central source. Falls off
  as r⁻².

The ionisation front (edge of the HII region) is modelled as a smooth
transition over ~5% of R_S, not a hard cutoff.

#### Emissivity evaluation

At each point (r) during ray marching:

1. Compute local n_e, T_e, log U from the profiles.
2. Look up emissivity j_λ for each emission line from the CLOUDY table
   using trilinear interpolation in (n_e, T_e, log U) space.
3. For each line, model the spectral profile as a Gaussian centred on
   the rest wavelength with thermal broadening:

       Δλ = λ₀ · √(2 k_B T / m_ion c²)

   For hydrogen at 10000 K: Δλ ≈ 0.04 nm (Hα). The hero-wavelength
   sampler will resolve this: if the sampled wavelength is within ~3σ
   of a line, it contributes; otherwise it sees zero emission.
4. Sum contributions from all lines. Return as `SampledSpectrum`.

#### Radiative transfer

Optically thin for the initial implementation. Nebulae are optically
thin to their own line emission (photons escape freely after
emission). Dust attenuation within the nebula is not included in this
package.

Accumulation: j_ν · ds along the ray, same as the jet and ADAF.

#### Parameters

| Parameter | Default | Description |
|---|---|---|
| `centre` | (0,0,0) | Position of the HII region centre. |
| `radius` | 10 pc (scene units) | Strömgren radius. |
| `density` | 100 cm⁻³ | Electron density at centre. |
| `density_profile` | "uniform" | "uniform" or "wind" (r⁻²). |
| `temperature` | 8000 K | Electron temperature. |
| `log_ionisation_param` | −2.5 | log U at the inner boundary. |
| `ionising_luminosity` | 10⁴⁹ s⁻¹ | Q_ion (used to compute U(r) if not specified directly). |

### Table loader design

The `EmissivityTable` class in `emissivity_table.h`:

- Reads the binary header, validates magic and dimensions.
- Maps the float32 data into a contiguous array.
- Provides `float lookup(float log_ne, float T_e, float logU, int line_index)` with trilinear interpolation and clamping at grid boundaries.
- Thread-safe (read-only after construction).
- Loaded once at scene build time; shared across all HII region
  instances via `std::shared_ptr`.

### Key design decisions

1. **Lines as narrow Gaussians, not delta functions.** A delta function
   at the exact line wavelength would almost never be hit by the hero
   wavelength sampler. The thermal Gaussian profile gives each line a
   physical width (~0.04–0.1 nm) that the sampler can resolve with
   reasonable probability. For 4-wavelength hero sampling across
   380–780 nm, the probability of hitting within 3σ of Hα is ~0.03% per
   sample — low but non-zero. For efficient rendering, the plugin
   checks all 8 lines per evaluation and returns the sum.

2. **Table is loaded once, not per-ray.** The emissivity table is
   small (~640 KB) and constant. It is loaded into memory at scene
   construction and shared read-only across threads.

3. **HII region is not coupled to GR.** Unlike the accretion models,
   HII regions exist at kiloparsec scales, far from any black hole.
   The plugin works with the standard flat-space ray marcher, not the
   GR integrator. It implements `VolumetricEmission` for interface
   consistency but is evaluated by the standard volume integration
   path, not the GR path.

4. **No scattering or fluorescence.** The nebula does not scatter
   starlight; it only emits. This is physically reasonable for pure
   emission-line visualisation. Reflection nebulae (dust scattering)
   are a different phenomenon and a separate plugin.

---

## Acceptance criteria

- [ ] `HIIRegion` registered via
      `ASTRORAY_REGISTER_EMISSION("hii_region", HIIRegion)`.
- [ ] `EmissivityTable` loads the binary table and interpolates
      correctly (verified by spot-checking known grid values).
- [ ] Test scene renders a glowing nebula with visible colour structure:
      red (Hα) dominant with green ([OIII]) and blue-green (Hβ) visible.
- [ ] Hα/Hβ ratio in the rendered output is within 15% of the Case B
      value (~2.86) when measured by integrating pixel values in narrow
      wavelength bands.
- [ ] [OIII]/Hβ ratio varies with ionisation parameter as expected
      (higher U → higher [OIII]/Hβ).
- [ ] Density profile is visible: uniform nebula vs wind-blown nebula
      show different brightness distributions.
- [ ] Blender addon exposes HII region creation and parameters.
- [ ] All existing tests pass.
- [ ] ≥8 new tests covering: table loading, interpolation, line
      profile shape, line ratios, geometry, visual render.

---

## Non-goals

- Do not implement dust within the nebula. Dust attenuation and
  reddening are a separate post-process.
- Do not implement reflection nebulae (dust scattering of starlight).
- Do not implement planetary nebulae (would need different density/
  temperature profiles and additional lines like [OII], HeII).
- Do not implement velocity fields or Doppler shifts within the
  nebula. All emission is at rest-frame wavelengths.
- Do not render the ionising star itself. The star can be added as a
  standard Astroray point light or emission object separately.

---

## Progress

- [ ] Implement `EmissivityTable` loader and interpolator.
- [ ] Implement `HIIRegion` plugin: geometry, profiles, emissivity
      evaluation with Gaussian line profiles.
- [ ] Wire into the standard volume integration path.
- [ ] Create test scene.
- [ ] Validate line ratios.
- [ ] Add Blender UI.
- [ ] Write tests.
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md.

---

## Lessons

*(Fill in after the package is done.)*

# pkg39 — Multi-Wavelength Rendering

**Pillar:** 2 (follow-up) / 5 (production feature)  
**Track:** A (touches integrator + material dispatch + output)  
**Status:** open  
**Estimated effort:** 3 sessions (~9 h)  
**Depends on:** pkg38 (spectral profile database), pkg14 (spectral pipeline)

---

## Goal

**Before:** Astroray renders exclusively in the visible range
(380–780 nm). The spectral path tracer samples hero wavelengths within
this fixed band, and the output is always converted to sRGB via
CIE XYZ colour matching functions. Materials outside visible are
undefined (Jakob-Hanika sigmoid extrapolation is meaningless).

**After:** Users can render any scene in an arbitrary wavelength band.
The renderer accepts a configurable wavelength range (e.g., 700–1000 nm
for near-IR photography, 300–380 nm for UV). Materials use physically
measured spectral profiles (from pkg38) outside the visible range.
Output is mapped to a user-chosen colourmap (grayscale, false-colour,
or multi-band RGB composite). The visible-range rendering path is
completely unchanged — this is a purely additive feature.

---

## Context

No other Blender addon — and arguably no other offline renderer — can
do this. The spectral pipeline that Pillar 2 built makes it a natural
extension: the integrator already evaluates materials at specific
wavelengths. Widening the range and providing real reflectance data is
all that's needed.

The most immediately compelling use case is simulated IR photography:
vegetation glows white, skies go dark, water turns black, skin looks
smooth and waxy. This is a well-known photographic aesthetic that
currently requires a physically modified camera. Being able to preview
it in a 3D renderer — with full path-traced global illumination — is
novel.

UV rendering is the secondary use case: fluorescent materials, UV
photography aesthetics, and scientific visualisation (e.g., how a
flower looks to a pollinator). X-ray and radio are out of scope for
this package (different transport physics), but the infrastructure
built here makes future extension straightforward.

---

## Reference

- Spectral profile database: `data/spectral_profiles/profiles.bin`
  (from pkg38)
- Binary format: `scripts/spectral_profile_format.md` (from pkg38)
- Spectral pipeline: `include/astroray/spectrum.h`,
  `plugins/integrators/path_tracer.cpp`
- Jakob-Hanika upsampling: existing sigmoid functions in the spectral
  material path
- CIE colour matching: `include/astroray/spectral.h`

---

## Prerequisites

- [ ] pkg38 is done: spectral profile database exists in
      `data/spectral_profiles/`.
- [ ] Pillar 2 (spectral core) complete.
- [ ] Build passes on main.
- [ ] All existing tests pass.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/spectral_profile.h` | `SpectralProfile` class: loads and interpolates measured reflectance curves. `SpectralProfileDatabase`: loads the binary database, provides lookup by name. |
| `include/astroray/wavelength_config.h` | `WavelengthConfig` struct: render band (λ_min, λ_max), output mode (colourmap, false-colour, multi-band), colourmap selection. |
| `plugins/passes/colourmap_output.cpp` | `ColourmapOutput` post-process pass: maps single-band intensity to a colourmap, or composites multi-band renders into RGB. |
| `tests/test_multiwavelength.py` | Unit and integration tests for the full pipeline. |
| `tests/scenes/ir_photography.py` | Test scene: outdoor scene with vegetation, sky, water, and a building. Rendered in visible and IR side-by-side. |
| `tests/scenes/uv_render.py` | Test scene: same scene rendered in UV (300–380 nm). |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/spectrum.h` | `SampledWavelengths::sampleUniform()` and `sampleHero()` accept configurable λ_min, λ_max instead of hardcoded 380, 780. |
| `plugins/integrators/path_tracer.cpp` | Read `WavelengthConfig` from integrator params. Pass configured wavelength range to `SampledWavelengths` sampling. |
| Material plugin dispatch (all materials) | When a `SpectralProfile` is assigned to a material and the current wavelength is outside 380–780 nm: use the profile's reflectance instead of Jakob-Hanika sigmoid upsampling. When inside 380–780 nm: use existing RGB path (profile is ignored, no visible-range regression). |
| `include/astroray/register.h` | No new registry needed. `SpectralProfile` is a data object, not a plugin. |
| `module/blender_module.cpp` | Expose: `set_wavelength_range(lambda_min, lambda_max)`, `set_output_mode(mode)`, `set_colourmap(name)`, `set_material_spectral_profile(material_id, profile_name)`, `spectral_profile_names()`. |
| `blender_addon/__init__.py` | Add render settings panel: wavelength range (min/max sliders, preset buttons for "Visible", "Near IR", "UV", "Custom"), output colourmap dropdown, per-material spectral profile dropdown. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg39 done. |
| `CHANGELOG.md` | Add pkg39 entry. |

### Rendering pipeline changes

#### Wavelength sampling

Current: `SampledWavelengths::sampleHero(u)` samples λ₁ uniformly in
[380, 780] and stratifies the remaining hero wavelengths.

New: `sampleHero(u, lambda_min, lambda_max)` samples in the
user-specified range. When the range is [380, 780], behaviour is
identical to current (zero regression risk). The range is set once per
render, not per ray.

#### Material reflectance dispatch

The key decision point is in each material's `evalSpectral()` and
`sampleSpectral()` methods. The logic is:

```
if (wavelength is in [380, 780] nm):
    use existing Jakob-Hanika sigmoid upsampling from RGB  ← no change
else if (material has a SpectralProfile assigned):
    use SpectralProfile::reflectance(wavelength)
else:
    return 0 (black — no data available)
```

This means:
- Visible-range rendering is completely unchanged. No regression.
- Outside visible, materials with assigned profiles render correctly.
- Materials without profiles render black outside visible. This is
  physically honest: "I don't have data for this wavelength."

The `SpectralProfile::reflectance(λ)` call is a simple linear
interpolation on the 5 nm grid — ~3 instructions, negligible cost.

#### Output mapping

In visible mode, the spectral accumulator converts to CIE XYZ via
colour matching functions, then to sRGB. This remains unchanged.

In single-band mode (e.g., 700–1000 nm IR), the accumulator produces
a single luminance value per pixel (the integrated spectral radiance
over the band). This is mapped to display via a colourmap:

| Colourmap | Description |
|---|---|
| `grayscale` | Linear grey ramp. Classic IR photography look. |
| `inferno` | Perceptually uniform, yellow-to-black. Scientific. |
| `viridis` | Perceptually uniform, green-to-purple. Scientific. |
| `hot` | Black-red-yellow-white. Thermal imaging aesthetic. |
| `ir_false_colour` | Custom: maps IR intensity to a warm palette that mimics the look of colour IR film (Kodak Aerochrome style). |

In multi-band composite mode, the user defines 2–3 bands, each mapped
to an RGB channel:

```
Band 1 (e.g., 800–900 nm) → Red channel
Band 2 (e.g., 500–600 nm) → Green channel
Band 3 (e.g., 400–500 nm) → Blue channel
```

The renderer runs one pass per band (or stratifies hero wavelengths
across bands in a single pass — see Key Design Decisions) and
composites the result. This is exactly how astronomical false-colour
images are made (e.g., Hubble's "Pillars of Creation": [SII] → red,
Hα → green, [OIII] → blue).

### SpectralProfile class

```
class SpectralProfile:
    - Constructed from a slice of the binary database (pointer + length).
    - reflectance(float lambda_nm) → float: linear interpolation on
      the 5 nm grid. Clamps to grid boundaries.
    - Thread-safe (read-only after construction).
    - ~0 allocation cost (views into the database memory).

class SpectralProfileDatabase:
    - Loaded once at renderer startup from profiles.bin.
    - get(string name) → const SpectralProfile*
    - names() → vector<string>
    - Singleton, shared across all materials.
    - Total memory: ~74 KB (entire database).
```

### Blender UI

#### Render Settings panel: "Wavelength" section

```
┌─ Wavelength ──────────────────────────┐
│ Mode:      [Visible ▼]               │
│                                       │
│ Presets:   [Visible] [Near IR] [UV]   │
│            [Custom]                   │
│                                       │
│ Range:     380 nm ──── 780 nm         │
│            ◄━━━━━━━━━━━━━━━►         │
│                                       │
│ Output:    [Grayscale ▼]              │
│                                       │
│ ☐ Multi-band composite               │
│   R: 800–900 nm                       │
│   G: 500–600 nm                       │
│   B: 400–500 nm                       │
└───────────────────────────────────────┘
```

Presets set the range and output mode:
- **Visible**: 380–780 nm, sRGB output (current behaviour, default).
- **Near IR**: 700–1000 nm, grayscale output.
- **UV**: 300–400 nm, grayscale output.
- **Custom**: user sets range and output manually.

When "Visible" is selected, the colourmap/multi-band options are
hidden (output is always sRGB).

#### Per-material: "Spectral Profile" property

Added to each material's Astroray properties panel:

```
┌─ Spectral Profile ────────────────────┐
│ Profile:   [Deciduous Leaf (Green) ▼] │
│                                       │
│ (Only used outside visible range.     │
│  Visible rendering uses the material  │
│  colour as normal.)                   │
└───────────────────────────────────────┘
```

Dropdown lists all profiles from the database, plus:
- `(none)` — material renders black outside visible.
- `(custom file)` — user points to a CSV file with (wavelength_nm,
  reflectance) columns.

### Environment map handling

Outside visible, the HDRI environment map has no defined spectral
content (it was captured in RGB). Two options:

1. **Analytic sky model** (default for outside visible): a simple
   Rayleigh + Mie scattering model where sky brightness scales as
   λ⁻⁴ (Rayleigh) and ground albedo uses the "soil" spectral profile.
   This automatically gives dark IR skies and realistic UV skies.

2. **User-supplied wideband HDRI**: if the user provides an IR-captured
   HDRI (these exist for IR photography), it is used directly. The
   existing `loadEnvironmentMap()` path is unchanged; an additional
   `loadEnvironmentMap(path, band="ir")` call allows specifying which
   band the HDRI represents.

For the initial implementation, option 1 (analytic fallback) is
sufficient. Option 2 is a natural follow-up.

### Key design decisions

1. **Additive, not replacing.** The visible-range pipeline is
   completely untouched. When `WavelengthConfig` is at the default
   (380–780 nm), every codepath is identical to pre-pkg39. The new
   logic only activates when the range is changed. This eliminates
   regression risk.

2. **Profile lookup is per-material, not per-texture.** A Blender
   material (node tree) maps to one spectral profile. If a material
   uses a texture for colour variation, the visible-range texture
   provides the spatial pattern, and the spectral profile provides
   the wavelength-dependent reflectance. The profile scales the
   texture's greyscale intensity outside visible. This is physically
   approximate but visually correct for most cases (a green leaf
   texture with a "deciduous leaf" profile will be bright in IR
   everywhere the texture is green, and darker where it shows bark).

3. **Single-pass multi-band via stratified sampling.** For multi-band
   composites, rather than running N separate render passes, the hero
   wavelength sampler can stratify across the N bands: sample λ₁ from
   band 1, λ₂ from band 2, etc. This produces all bands in a single
   render pass at the cost of fewer samples per band. For 2–3 bands
   with 4 hero wavelengths, this is efficient. The alternative (N
   passes) is also supported as a quality option.

4. **Colourmap is a post-process pass.** The renderer produces a
   single-channel floating-point luminance buffer. The `ColourmapOutput`
   pass maps this to RGB for display. This keeps the integrator clean
   and allows the colourmap to be changed without re-rendering.

5. **Analytic sky fallback, not HDRI extrapolation.** Extrapolating
   an RGB HDRI into IR is poorly defined (what does "extrapolate"
   mean for a photograph?). A simple physics-based sky model with
   λ⁻⁴ Rayleigh scattering produces the correct qualitative behaviour
   (dark IR sky, bright UV sky) and is more honest than extrapolation.

6. **Custom CSV loading for user-supplied spectra.** Power users
   (researchers, VFX artists with measured data) can supply their own
   (wavelength, reflectance) CSV. The CSV is parsed at scene load
   time and converted to a `SpectralProfile` in memory. This is a
   simple feature but dramatically extends the system's usefulness.

---

## Acceptance criteria

- [ ] Visible-range rendering (380–780 nm) is pixel-identical to
      pre-pkg39 output (regression test with saved reference PNG).
- [ ] IR render (700–1000 nm) of the test scene shows:
      - Vegetation is bright (brightest material in the scene).
      - Sky is dark.
      - Water is dark.
      - Concrete / building is mid-grey.
      - These match the qualitative behaviour of real IR photographs.
- [ ] UV render (300–400 nm) of the test scene shows:
      - Vegetation is dark (chlorophyll absorbs UV).
      - White paint is dark (TiO₂ absorbs UV).
      - Metals are reflective.
- [ ] Materials without spectral profiles render black outside visible
      (not NaN, not garbage, not sigmoid extrapolation).
- [ ] Colourmap pass correctly maps luminance to the selected palette.
- [ ] Multi-band composite: 3-band false-colour render produces an
      RGB image with each channel from a different wavelength band.
- [ ] Custom CSV: a user-supplied spectrum is loaded and produces
      correct reflectance at sampled wavelengths.
- [ ] Analytic sky model produces dark sky in IR, bright in UV.
- [ ] Blender UI: wavelength range controls, presets, per-material
      profile dropdown, colourmap selection all functional.
- [ ] `spectral_profile_names()` Python API returns the database
      contents.
- [ ] All existing tests pass.
- [ ] ≥12 new tests covering: wavelength range configuration, profile
      loading, reflectance interpolation, visible-range regression,
      IR render, UV render, colourmap mapping, multi-band composite,
      custom CSV, no-profile fallback, analytic sky, Blender UI round-
      trip.

---

## Non-goals

- Do not change the visible-range material pipeline. Jakob-Hanika
  sigmoid upsampling remains the default for 380–780 nm.
- Do not implement X-ray or radio rendering (different transport
  physics — photoelectric absorption, plasma dispersion).
- Do not implement fluorescence (UV absorption → visible re-emission).
- Do not implement spectral textures (per-texel wavelength-dependent
  reflectance). The profile is per-material.
- Do not implement dispersion outside visible (Sellmeier coefficients
  are only valid in their measured range).
- Do not implement thermal emission from scene objects based on
  temperature (emissive IR). Only reflective IR.
- Do not implement auto-mapping from Blender material properties to
  spectral profiles. The user selects the profile manually.

---

## Progress

- [ ] Implement `SpectralProfile` and `SpectralProfileDatabase` in
      `spectral_profile.h`.
- [ ] Implement configurable wavelength range in `SampledWavelengths`.
- [ ] Implement material dispatch: profile lookup outside visible.
- [ ] Save visible-range regression reference render.
- [ ] Implement analytic sky model for outside-visible environment.
- [ ] Implement `ColourmapOutput` post-process pass.
- [ ] Implement multi-band composite mode.
- [ ] Implement custom CSV loading.
- [ ] Create IR and UV test scenes.
- [ ] Verify IR photography qualitative correctness.
- [ ] Add Blender UI (render settings + per-material property).
- [ ] Write tests (≥12).
- [ ] Full test suite green.
- [ ] Update STATUS.md, CHANGELOG.md.

---

## Lessons

*(Fill in after the package is done.)*

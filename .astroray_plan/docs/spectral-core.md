# Pillar 2: Spectral Core

**Status:** Not started
**Depends on:** Pillar 1
**Track:** A (core), B (measured BRDF plugins)
**Duration:** 3–4 weeks

## Goal

Upgrade Astroray's light transport from RGB to a full spectral pipeline
following the PBRT v4 / Mitsuba 3 pattern: `SampledSpectrum` and
`SampledWavelengths` types, Jakob-Hanika RGB→spectrum upsampling for
backward compat, spectral BSDFs and environment maps, spectral-to-XYZ
accumulation. The 4-wavelength hero-wavelength approach from the
existing GR renderer is the right default.

## Why spectral (the "so what")

- **Astrophysics requires it.** Doppler shifts, gravitational redshifts,
  emission lines (Hα, Hβ, [OIII]), blackbody with relativistic boost —
  all physically wrong in RGB. Currently hacked or unavailable.
- **Dispersion is free once it's in.** Prism, water, diamond, chromatic
  aberration in lenses — all render correctly with zero extra code per
  material.
- **Measured materials.** The RGL and MERL databases give spectral
  reflectance curves for real materials (paint, metal, fabric). RGB
  cannot represent these.
- **Small cost.** 4 wavelengths per path is ~33% more work than 3 RGB
  channels. Jakob-Hanika upsampling is 6 FLOPs per RGB→spectrum
  conversion.

## Reference (do not reinvent)

- **PBRT v4** `src/pbrt/util/spectrum.h` — canonical types. Apache 2.0;
  port the design, not the code.
- **Mitsuba 3** `src/librender/spectrum.cpp` — cross-reference.
- **Jakob-Hanika coefficient tables** — Zenodo download; ship in
  `data/spectra/`.
- **simple-spectral** (geometrian) — minimal LUT reader reference.
- **RGL material database** (rgl.epfl.ch) — measured spectral BRDFs.

## Design

### The four types

```cpp
// include/astroray/spectrum.h
inline constexpr int kSpectrumSamples = 4;
inline constexpr float kLambdaMin = 360.0f, kLambdaMax = 830.0f;

class SampledWavelengths {
    std::array<float, kSpectrumSamples> lambdas_, pdf_;
    bool terminated_ = false;
public:
    static SampledWavelengths sampleUniform(float u);
    void terminateSecondary();  // at dispersive interface
    float operator[](int i) const { return lambdas_[i]; }
    float pdf(int i) const { return pdf_[i]; }
};

class SampledSpectrum {
    std::array<float, kSpectrumSamples> values_{};
public:
    SampledSpectrum() = default;
    explicit SampledSpectrum(float v) { values_.fill(v); }
    // componentwise +, -, *, /, max, sum, isZero, hasNaN
    float luminance(const SampledWavelengths&) const;
    Vec3 toXYZ(const SampledWavelengths&) const;
};

class RGBAlbedoSpectrum {
    float c0_, c1_, c2_;  // Jakob-Hanika sigmoid coefficients
public:
    explicit RGBAlbedoSpectrum(const Vec3& rgb);  // uses global LUT
    SampledSpectrum sample(const SampledWavelengths&) const;
};
// Also RGBUnboundedSpectrum (scattering coeffs),
//      RGBIlluminantSpectrum (emission)
```

### The invariant

**Everything that used to return `Vec3` radiance or reflectance now
returns `SampledSpectrum` and takes `const SampledWavelengths&`:**
`Material::eval`, `Material::sample` (BSDFSample.f), `sampleDirect`,
`pathTrace` throughput, env map sampling. The per-pixel accumulator
holds XYZ; conversion happens once per path at the end.

### Per-path lifecycle

```cpp
// Per pixel sample:
float wlSample = rng01(gen);
auto lambdas = SampledWavelengths::sampleUniform(wlSample);
SampledSpectrum rad = pathTraceSpectral(ray, lambdas, gen, maxDepth);
Vec3 xyz = rad.toXYZ(lambdas);
accumulator[pixel] += xyz / float(kSpectrumSamples);
```

At a dispersive interface: `lambdas.terminateSecondary()` — zeros the
PDFs of siblings; only the hero wavelength's path continues.

## Migration strategy

Never flip everything in one commit. The plugin architecture makes this
easier — each material is one file.

### Phase 2A: Scaffolding (1 week)

Package `pkg10-spectral-types.md` — header, LUT loader, unit tests. No
integration yet.

### Phase 2B: Shadow path tracer (1 week)

Package `pkg11-spectral-path-tracer.md` — parallel `pathTraceSpectral`
using `SampledSpectrum` throughout. Materials get both a `Vec3 eval`
and a `SampledSpectrum evalSpectral` path. The legacy `pathTrace`
remains for A/B comparison.

### Phase 2C: Migrate materials (1 week)

Packages `pkg12-spectral-lambertian.md`, `pkg13-spectral-disney.md`, etc.
Each material adds its spectral overload; Jakob-Hanika handles the RGB
inputs. The spectral-native GR materials plug into the same interface.

### Phase 2D: Spectral env map (1 week)

Package `pkg14-spectral-envmap.md`. HDRI env map texels become
`RGBIlluminantSpectrum` via Jakob-Hanika. Spectral-native sky models
(Hošek-Wilkie) become plugins.

### Phase 2E: Flip the default (part of 2D)

Once all materials are migrated: delete the legacy `pathTrace`, wire the
spectral version everywhere. Firefly clamp, MIS, NEE all unchanged —
they just operate on `SampledSpectrum`. One code path, not two.

## Acceptance criteria

- [ ] A scene rendered in spectral mode and RGB mode produces mean
      brightness within 1% (they should be identical to noise, not
      close — the spectral path handles RGB inputs identically).
- [ ] A prism scene (single glass wedge under broad-spectrum light)
      shows visible rainbow dispersion in spectral mode, solid
      refraction in RGB mode. Irreducible evidence the spectral
      pipeline works.
- [ ] Spectral rendering is no more than 1.5× slower than RGB on the
      Cornell box benchmark (4 wavelengths vs 3 channels + overhead).
- [ ] All existing tests pass with the internal spectral pipeline
      enabled.

## Non-goals

- **More than 4 wavelengths.** PBRT v4 and Mitsuba 3 both default to 4.
  More wavelengths means more variance reduction but linearly slower.
  Expose the constant but do not tune it.
- **Full 16-bin spectral storage.** Do not store spectra as vectors per
  pixel. Only the reconstructed XYZ accumulates. If someone needs
  per-wavelength output later (for scientific measurement), add a
  separate AOV pass — that's its own plugin.
- **Metameric-correct light sources.** Initially all RGB illuminants go
  through the standard upsampling. Tódová-Wilkie 2025 is a future
  plugin.

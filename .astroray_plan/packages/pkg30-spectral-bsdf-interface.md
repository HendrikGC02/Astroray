# pkg30 — Spectral BSDF Sampling Interface

**Pillar:** 2 follow-up  
**Track:** A  
**Status:** open  
**Estimated effort:** 1 session (~3 h)  
**Depends on:** pkg13 (done)  
**Blocks:** pkg31, pkg29

---

## Goal

**Before:** `Material::sample()` returns `BSDFSample` with no wavelength
information. The spectral path tracer calls `sample()` then `evalSpectral()`
separately, so the sampled direction is always wavelength-independent. Delta
materials (dielectric, mirror) return `evalSpectral → 0` and the integrator
falls back to RGB upsampling of `bs.f`. Dispersive refraction is impossible.

**After:** `Material` has a `sampleSpectral()` virtual method that receives
`SampledWavelengths` and can produce wavelength-dependent directions. The
default implementation delegates to `sample()` so all existing materials
work unchanged. The spectral path tracer calls `sampleSpectral()` instead
of `sample()`.

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | Add `BSDFSampleSpectral` struct (extends `BSDFSample` with `SampledSpectrum f_spectral`). Add `virtual BSDFSampleSpectral sampleSpectral(const HitRecord&, const Vec3& wo, std::mt19937& gen, astroray::SampledWavelengths& lambdas) const` to `Material`, defaulting to delegating to `sample()` + upsampling `bs.f`. |
| `include/raytracer.h` (spectral path tracer) | Change line ~1853 from `rec.material->sample(rec, wo, gen)` to `rec.material->sampleSpectral(rec, wo, gen, lambdas)`. Remove the delta-fallback RGB upsample block (lines ~1861-1863) since `sampleSpectral` handles it in the default impl. Use `bss.f_spectral` for throughput instead of calling `evalSpectral()` separately for delta lobes. |

### `BSDFSampleSpectral` struct

```cpp
struct BSDFSampleSpectral {
    Vec3 wi;
    astroray::SampledSpectrum f_spectral;
    float pdf;
    bool isDelta;
};
```

### Default `sampleSpectral` implementation

```cpp
virtual BSDFSampleSpectral sampleSpectral(
        const HitRecord& rec, const Vec3& wo,
        std::mt19937& gen,
        astroray::SampledWavelengths& lambdas) const {
    BSDFSample bs = sample(rec, wo, gen);
    BSDFSampleSpectral bss;
    bss.wi = bs.wi;
    bss.pdf = bs.pdf;
    bss.isDelta = bs.isDelta;
    if (bs.isDelta) {
        bss.f_spectral = astroray::RGBAlbedoSpectrum(
            {bs.f.x, bs.f.y, bs.f.z}).sample(lambdas);
    } else {
        bss.f_spectral = evalSpectral(rec, wo, bs.wi, lambdas);
    }
    return bss;
}
```

### Acceptance criteria

- [ ] All existing tests pass without changes to any material plugin.
- [ ] The spectral path tracer calls `sampleSpectral()` instead of `sample()`.
- [ ] Delta-fallback RGB upsample block removed from integrator (handled by default impl).
- [ ] Non-dispersive dielectric/mirror/metal scenes render identically to before.

---

## Non-goals

- Do not implement wavelength-dependent refraction here (that is pkg31).
- Do not add Sellmeier data.
- Do not change any material plugin file.

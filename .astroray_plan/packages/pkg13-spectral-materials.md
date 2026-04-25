# pkg13 — Spectral remaining materials and textures

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 2 sessions (~6–8 h)
**Depends on:** pkg12

---

## Goal

**Before:** only Lambertian has a native `evalSpectral` override.
Every other material (Metal, Dielectric, Phong, Disney, DiffuseLight,
NormalMapped, Emissive, Isotropic, OrenNayar, TwoSided) and every
texture (Checker, Noise, Gradient, Voronoi, Brick, Musgrave, Magic,
Wave, Image) goes through the pkg11 RGB→Jakob-Hanika fallback. This
works but is wasteful and physically lossy in two specific places —
Dielectric and Metal — where the index of refraction is wavelength-
dependent.

**After:** every plugin under `plugins/materials/` overrides
`evalSpectral` (and emission counterparts where they exist). Two
materials gain genuine wavelength-dependent physics:

- **Dielectric** uses Sellmeier coefficients per λ for refractive
  index, calls `lambdas.terminateSecondary()` at refraction events,
  and produces visible chromatic dispersion in the prism scene.
- **Metal** uses tabulated complex IOR (n, k) sampled per λ for the
  shipped presets (gold, silver, copper, aluminium) — accurate
  reflectance colour without the RGB→spectrum→RGB round-trip.

Textures gain a `Texture::sampleSpectral(uv, lambdas)` virtual with a
default that calls `Texture::sample(uv)` and upsamples; image textures
override it (cache the upsampled spectrum per-texel via Jakob-Hanika
on first access, evict by texel rather than texture). All other
materials override with the same caching pattern as pkg12.

---

## Context

Phase 2C concludes here. Once this package merges, every shading event
in the spectral pipeline runs without the pkg11 fallback path —
the fallback stays as the safety net for new materials, but the shipped
tree no longer relies on it. The two physics upgrades (dispersive
glass, complex-IOR metal) are the "irreducible evidence" the spectral
pipeline does work the spectral pipeline can't be faked in RGB. After
pkg13 the only remaining piece is the env map (pkg14).

This is the largest package in Pillar 2; consider splitting into
pkg13a (materials) and pkg13b (textures + Metal/Dielectric physics)
if the diff exceeds ~800 lines. The plan keeps it as one package
because the two changes share the same caching pattern and are easier
to review side by side.

---

## Reference

- Design doc: `.astroray_plan/docs/spectral-core.md §Phase 2C`
- Spectral types: `include/astroray/spectrum.h`
- Pattern reference: pkg12's Lambertian override
- Sellmeier coefficients (BK7, fused silica, etc.): public optical
  data, mirrored under `data/spectra/iors/` (new subdirectory)
- Refractive Index Database (refractiveindex.info) — source for the
  Metal preset (n, k)(λ) tables; data is CC-BY, attribution in
  `THIRD_PARTY.md`
- `plugins/materials/*.cpp` — every existing material plugin
- `plugins/textures/*.cpp` — every existing texture plugin

---

## Prerequisites

- [ ] pkg12 is merged on `main`; spectral Lambertian is the default
      pattern reference.
- [ ] Build is green; full pytest passes.
- [ ] Refractive-index data files acquired and license-cleared.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `include/astroray/texture.h` *(or wherever `Texture` lives)* | Add `virtual SampledSpectrum sampleSpectral(const Vec2& uv, const SampledWavelengths& lambdas) const` with default fallback (call `sample(uv)`, upsample via `RGBAlbedoSpectrum`). |
| `data/spectra/iors/dielectrics.inc` | `constexpr` Sellmeier coefficients for shipped glass presets (BK7, fused silica, water). |
| `data/spectra/iors/metals.inc` | `constexpr` (λ, n, k) tables for gold, silver, copper, aluminium at 1 nm step over 360–830 nm. |
| `tests/test_spectral_materials.py` | pytest: every material's `evalSpectral` matches the pkg11 default fallback ≤1e-5 for non-physics materials; Dielectric prism produces non-zero R/G/B angular spread (**this is the prism/dispersion test originally scoped for pkg11 and deferred here, since wavelength-dependent IOR is the only way to get direction-spread dispersion** — also build the prism scene under `tests/scenes/`); Metal gold reflectance peak in the 550–600 nm band; image-texture spectral cache returns identical results across multiple lookups. |
| `tests/test_spectral_textures.py` | pytest: every texture's `sampleSpectral` matches its `sample` upsampled, except procedurals where it's an exact match by construction. |
| `scripts/generate_iors.py` | Repeatable script that writes `dielectrics.inc` / `metals.inc` from the upstream sources. Documents the pinned source URLs. |

### Files to modify

| File | What changes |
|---|---|
| `plugins/materials/lambertian.cpp` | (already done in pkg12 — left here for reference, no change in pkg13) |
| `plugins/materials/metal.cpp` | Override `evalSpectral`. Replace RGB Fresnel with complex-IOR Fresnel sampled per λ from `metals.inc`. Allow material spec to select a preset (`"gold"`, etc.) or fall back to RGB→spectrum upsample for arbitrary tints. |
| `plugins/materials/dielectric.cpp` | Override `evalSpectral`. Sellmeier-based IOR per λ. On refraction events call `lambdas.terminateSecondary()`. Schlick / dielectric Fresnel becomes per-λ. |
| `plugins/materials/phong.cpp` | Override `evalSpectral` with same caching pattern as Lambertian (RGB diffuse + RGB specular each cached as `RGBAlbedoSpectrum` — specular probably as `RGBUnboundedSpectrum` if HDR is allowed). |
| `plugins/materials/disney.cpp` | Override `evalSpectral`. Per-component cache (basecolor as albedo, sheen tint as albedo, specular tint as unbounded). Disney's existing internal RGB math runs once per-λ; check that the per-bounce cost stays under the 1.5× budget — if not, fall back to upsampling the final RGB. |
| `plugins/materials/diffuse_light.cpp` | Override `emittedSpectral` using `RGBIlluminantSpectrum` cache. |
| `plugins/materials/normal_mapped.cpp` | Override `evalSpectral` by delegating to the wrapped material's spectral path. |
| `plugins/materials/emissive.cpp` | Override `emittedSpectral` (illuminant cache). |
| `plugins/materials/isotropic.cpp` | Override `evalSpectral` (volumetric albedo as `RGBAlbedoSpectrum`). |
| `plugins/materials/oren_nayar.cpp` | Override `evalSpectral` (albedo cache, RGB roughness math runs per-λ). |
| `plugins/materials/two_sided.cpp` | Override `evalSpectral` by delegating to the wrapped material. |
| `plugins/textures/image.cpp` | Override `sampleSpectral` with per-texel `RGBAlbedoSpectrum` cache (lazy populated, sized to image resolution; consider a small LRU if memory budget bites). |
| `plugins/textures/{checker,noise,gradient,voronoi,brick,musgrave,magic,wave}.cpp` | Override `sampleSpectral` calling existing `sample` and upsampling per-call (no cache — UV-varying). |
| `THIRD_PARTY.md` | Add provenance for refractive-index data. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg13 done; bump Pillar 2 % to ~85. |
| `CHANGELOG.md` | Add pkg13 entry. |

### Files explicitly NOT touched

- `Renderer`, `Integrator`, framebuffer, NEE/MIS code (all pkg11).
- `plugins/passes/*.cpp` and the env map (env map is pkg14).
- `path_tracer` legacy plugin (still the default until pkg14).
- `spectral.h` and the GR renderer.
- Any new material/texture plugin not currently in-tree.

### Key design decisions

1. **Two flavours of override.** "Dumb" override (Lambertian, Phong,
   Disney, OrenNayar, Isotropic, NormalMapped, TwoSided, DiffuseLight,
   Emissive) just caches one or more `RGB*Spectrum` instances and
   evaluates per-λ. "Physics" override (Dielectric, Metal) actually
   uses the wavelength: tabulated IOR or Sellmeier per-λ.
2. **Texture cache lives in the texture instance.** Image textures
   own a parallel spectral atlas built lazily on first `sampleSpectral`
   call, sized to the source image. Memory hit is acceptable because
   image textures are already the dominant memory consumer; the
   spectral atlas is 3× the source's float storage.
3. **Procedural textures don't cache.** Their `sampleSpectral` is just
   `RGBAlbedoSpectrum(sample(uv)).sample(lambdas)`. Fast enough; no
   cache because UV varies per-pixel.
4. **Hero-wavelength termination is the dispersive interface contract.**
   Dielectric is the only currently-shipped material that calls
   `lambdas.terminateSecondary()`. Document this in the dielectric
   plugin's header comment so future authors know when to call it.
5. **Metal preset selection.** The material spec gains an optional
   `"preset"` string param. If unset, falls back to the existing RGB
   tint upsampled (preserves backward compatibility with scenes that
   set arbitrary RGB metal tints).
6. **No new public API.** Existing scene files still load; users opt
   into wavelength-correct Metal/Dielectric by setting the preset
   string.
7. **Performance budget.** This package is where the 1.5× spectral-vs-
   RGB ceiling can be breached. Profile after each material migrates;
   if the cumulative drift breaches the budget, fall back to
   upsampling for the offending material and document why.

---

## Acceptance criteria

- [ ] Every material plugin overrides `evalSpectral`; for materials
      without a physics upgrade, override values match the pkg11
      default fallback ≤1e-5 on a sweep of `(wo, wi, normal, uv,
      lambdas)` tuples.
- [ ] Every texture plugin overrides `sampleSpectral` with the same
      ≤1e-5 match against the upsampled `sample`.
- [ ] Glass-prism scene renders rainbow dispersion (R/G/B exit angle
      spread > 0).
- [ ] Gold Metal preset shows correct yellow-tone reflectance peak
      in the 550–620 nm band (not the muddy cyan-ish result the RGB
      upsample of a yellow `Vec3` gives).
- [ ] Cornell box render time stays ≤1.5× the RGB baseline.
- [ ] All existing tests still pass.
- [ ] No legacy `eval`/`sample` signatures changed.

### Non-goals

- No deletion of the pkg11 default fallback. It remains the safety net
  for future materials.
- No deletion of `path_tracer` (legacy RGB integrator). pkg14.
- No env map work. pkg14.
- No measured-BRDF (RGL/MERL) loader. Future package.
- No Hošek-Wilkie sky model. Future package.
- No new material types (e.g., subsurface, volumetric Henyey-Greenstein
  upgrade). Out of scope.
- No public API change to material/texture spec dicts beyond the
  optional Metal `preset` string.

---

## Progress

- [ ] Branch `pkg13-spectral-materials` from `main`.
- [ ] Acquire IOR datasets, write `scripts/generate_iors.py`, generate
      `dielectrics.inc` and `metals.inc`, attribute in `THIRD_PARTY.md`.
- [ ] Add `Texture::sampleSpectral` virtual with default.
- [ ] Migrate "dumb" materials (Phong, Disney, DiffuseLight,
      NormalMapped, Emissive, Isotropic, OrenNayar, TwoSided).
- [ ] Migrate physics materials (Metal, Dielectric).
- [ ] Migrate textures (image cache + procedural overrides).
- [ ] Write `tests/test_spectral_materials.py`,
      `tests/test_spectral_textures.py`.
- [ ] Profile cumulative spectral cost on Cornell + a glossy scene.
- [ ] Update STATUS.md, CHANGELOG.md.
- [ ] Commit per granularity plan; push branch; open PR.

---

## Lessons

*(Fill in after the package is done.)*

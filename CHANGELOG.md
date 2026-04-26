# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

---

### Pillar 2 — Spectral core (in progress)

- **pkg13c** — Four new material plugins completing pkg13 (closes issue #105).
  `plugins/materials/oren_nayar.cpp`: OrenNayar diffuse model (A/B coefficients
  precomputed in ctor from roughness; `evalSpectral` uses cached
  `RGBAlbedoSpectrum albedo_spec_`; cosine hemisphere sampling).
  `plugins/materials/isotropic.cpp`: uniform volumetric phase function (1/4π);
  `evalSpectral` returns `albedo_spec_.sample(lambdas) * 1/4π`; `sample` picks
  a uniformly random direction on the unit sphere. `plugins/materials/two_sided.cpp`:
  wraps an inner material (registry lookup via `inner_type` param), flips hit
  record normal on back-face hits, delegates all `eval`/`sample`/`pdf`/
  `evalSpectral` calls to the inner material. `plugins/materials/emissive.cpp`:
  omnidirectional emitter — emits from both faces (unlike `DiffuseLight` which
  gates on `frontFace`); `emittedSpectral` returns cached `RGBIlluminantSpectrum`.
  5 new tests in `test_spectral_materials.py`; 223 passed, 1 skipped.
  **pkg13 is now fully complete.** Every plugin in `plugins/materials/` and
  `plugins/textures/` has a concrete spectral override; the pkg11 Jakob-Hanika
  fallback remains only as the safety net for future materials.
- **pkg13 (Copilot — pkg13a #104, pkg13b #106)** — Dumb-material overrides
  (Phong `evalSpectral` with cached diffuse+specular spectra;
  Disney `evalSpectral` via final-RGB upsample; NormalMapped `evalSpectral`
  delegation; DiffuseLight `emittedSpectral` with `RGBIlluminantSpectrum` cache)
  and 8 procedural texture `sampleSpectral` overrides (checker, noise, gradient,
  voronoi, brick, musgrave, magic, wave — all call `sample(uv, p)` and upsample
  per-call, no cache needed for UV-varying procedurals).
- **pkg13 (physics/infra — Claude Code #103)** — Three deliverables.
  (1) `Texture::sampleSpectral` virtual added to `Texture` base in
  `include/advanced_features.h`: default upsamples `value(uv, p)` via
  `RGBAlbedoSpectrum`; non-virtual helper handles coord-mode dispatch.
  `ImageTexture` overrides with an eager per-texel `RGBAlbedoSpectrum` cache
  built in `setData()` (12 bytes/texel, zero lock overhead). (2) `MetalPlugin`
  gains `albedo_spec_` member and overrides `evalSpectral` with a per-λ Schlick
  Fresnel inside the GGX microfacet model — `F0` becomes a `SampledSpectrum`
  evaluated from the cached albedo. Near-delta and roughness paths both covered.
  (3) `DielectricPlugin` and `MirrorPlugin` gain trivial zero `evalSpectral`
  overrides (delta lobes). `SubsurfacePlugin` gains `albedo_spec_` cache and
  overrides `evalSpectral` with per-call transmission spectrum from scatter
  distance. Dispersive glass (Sellmeier + `terminateSecondary`) and metal
  complex-IOR presets (gold/silver) remain deferred. 206 passed, 1 skipped
  (+8 new in `tests/test_spectral_materials.py`).
- **pkg12** — Spectral Lambertian override. `LambertianPlugin` in
  `plugins/materials/lambertian.cpp` gains an `astroray::RGBAlbedoSpectrum
  albedo_spec_` member, eagerly initialised from `albedo_` in the constructor
  (12 bytes, zero runtime overhead). Overrides `evalSpectral` to return
  `albedo_spec_.sample(lambdas) * cosTheta / PI`, bypassing the default
  per-call Jakob-Hanika LUT lookup. `eval()`, `sample()`, `pdf()` and all
  other plugin files are untouched. The override is more physically correct
  than the default fallback (which upsamples the pre-scaled BRDF value rather
  than the pure albedo reflectance — the two formulas are NOT scale-linear for
  saturated colours). Cornell A/B at 64 spp: spectral matches RGB within 3%
  per channel. Establishes the cache pattern that pkg13 will copy verbatim
  across the remaining 9 material plugins. Test suite: 198 passed, 1 skipped
  (+5 new tests in `tests/test_spectral_lambertian.py`; Cornell PNGs in
  `test_results/pkg12_*.png`).
- **pkg11** — Spectral path tracer (opt-in). New `spectral_path_tracer`
  integrator plugin under `plugins/integrators/`, registered alongside
  the legacy `path` and `ambient_occlusion`. Activated via
  `r.set_integrator("spectral_path_tracer")`; the legacy `path` remains
  the registry default (pkg14 will flip it). Adds `IntegratorKind` enum +
  `Integrator::kind()` virtual; `Material::evalSpectral` and
  `Material::emittedSpectral` virtuals with Jakob-Hanika upsampling
  defaults so every existing material renders correctly under the spectral
  path without per-material edits (concrete spectral overrides land in
  pkg12+). New `Renderer::pathTraceSpectral` mirrors the legacy `pathTrace`
  recursion but carries `SampledSpectrum` throughput, samples one hero
  wavelength bundle per primary ray via `SampledWavelengths::sampleUniform`,
  applies the same `wasSpecular || bounce==0` emission gate, MIS power
  heuristic on area-light NEE, and Russian roulette after depth 3. The
  `Renderer` now stores a `spectralMode_` flag (set from the integrator's
  `kind()`); when active, the per-pixel accumulator stores XYZ, the per-
  sample firefly clamp gates on Y instead of sRGB luminance (threshold
  unchanged at 20.0), and a single `xyzToLinearSRGB` conversion happens
  before gamma — preserving the "gamma once" invariant. Existing `Material`
  signatures untouched; `plugins/materials/*.cpp` and `plugins/passes/*.cpp`
  unchanged. Cornell box A/B at 32 spp matches RGB within ~3% per channel
  (rel. delta `[0.012, 0.015, 0.028]`); spectral wall-clock 1.34× of RGB
  on the same scene (well under the 1.5× pkg11 ceiling). Test suite: 193
  passed, 1 skipped (4 new tests under `tests/test_spectral_path_tracer.py`,
  including a Cornell A/B match assertion and PNG outputs in
  `test_results/pkg11_cornell_*.png`). Conftest fix: prepend
  `C:\Program Files\mingw64\bin` to PATH so subprocess-launched
  `raytracer.exe` finds the modern libstdc++ ahead of Git Bash's older
  copy. Prism / dispersion criterion deferred to pkg13.
- **pkg10** — Spectral core scaffolding. New `include/astroray/spectrum.h`
  declares `SampledWavelengths`, `SampledSpectrum`, `RGBAlbedoSpectrum`,
  `RGBUnboundedSpectrum`, and `RGBIlluminantSpectrum` (float precision,
  4 hero wavelength samples, 360-830 nm) following the PBRT v4 design.
  `src/spectrum.cpp` lazily loads the Jakob-Hanika 2019 sRGB coefficient
  LUT from `data/spectra/rgb_to_spectrum_srgb.coeff`, and embeds the
  CIE 1964 10° standard observer CMF and D65 illuminant SPD as
  `constexpr` tables at 1 nm. New `astroray_core_impl` CMake static
  library; `ASTRORAY_DATA_DIR` compile definition (with env-var
  override) lets the loader find the LUT both in-tree and post-install.
  Python bindings expose every new type plus a top-level
  `rgb_to_spectrum()` helper, `sample_d65()`, `cie_cmf_1964_10deg()`,
  and `spectrum_lut_path()`. `THIRD_PARTY.md` added with license and
  provenance for the shipped data files. No integration into any
  material, integrator, pass, or environment map — the existing
  `spectral.h` (CIE 1931 2°, GR renderer) is untouched. Test suite:
  189 passed, 1 skipped (20 new spectrum tests; 1% round-trip against
  a Colour-Science-generated reference JSON).

---

### Pillar 1 — Plugin architecture COMPLETE (pkg01–pkg06)

All materials, shapes, textures, integrators, and post-process passes are now
plugin-registered. The core render loop has zero hardcoded knowledge of any
specific material, integrator, or post-process effect. New implementations
drop in as single files.

- **pkg06** — Pass registry closes Pillar 1. `Pass` abstract base class in
  `include/astroray/pass.h`; `Framebuffer` named-buffer API in `raytracer.h`.
  Five pass plugins in `plugins/passes/`: OIDN denoiser, depth AOV, normal AOV,
  albedo AOV (and the `.gitkeep` placeholder). `Renderer` gains `addPass()` /
  `clearPasses()` and a post-render pass loop. Python bindings: `add_pass(name)`,
  `clear_passes()`, `pass_registry_names()`. Blender addon: `use_denoising`
  checkbox wires to `add_pass("oidn_denoiser")`. Inline OIDN code removed from
  `blender_module.cpp` — no hardcoded denoiser remains in the render loop.
  Test suite: 169 passed, 1 skipped.

- **pkg05** — `Integrator` abstract base class in `include/astroray/integrator.h`.
  `PathTracer` and `AmbientOcclusion` plugins in `plugins/integrators/`.
  `SampleResult` struct and `Renderer::traceFull()` for AOV preservation across
  the integrator boundary. `set_integrator(name)` Python binding and
  `integrator_registry_names()` module function. Blender addon: `integrator_type`
  `EnumProperty` backed by the live registry. Test suite: 165 passed, 1 skipped.

- **pkg04** — Migrated nine texture classes (Checker, Noise, Gradient, Voronoi,
  Brick, Musgrave, Magic, Wave, Image) and five shape classes (Sphere, Triangle,
  Mesh, ConstantMedium, BlackHole) to plugin files under `plugins/textures/` and
  `plugins/shapes/`. Shape class bodies moved to `include/astroray/shapes.h`.
  Python bindings: `sample_texture()`, `texture_registry_names()`,
  `shape_registry_names()`. Test suite: 161 passed, 1 skipped.

- **pkg03** — Migrated all remaining material types to plugin files: Metal,
  Dielectric, Phong, Disney, DiffuseLight, NormalMapped, Emissive, Isotropic,
  OrenNayar, TwoSided.

- **pkg02** — Migrated Lambertian material to a plugin file, establishing the
  pattern for all subsequent Track A plugin migrations.

- **pkg01** — Added `Registry<T>` template, `ParamDict`, and `ASTRORAY_REGISTER_*`
  macros. Created `plugins/` directory tree and the CMake OBJECT library that
  preserves static initialisers from registration macros across linker
  dead-stripping.

---

### Other

- Refreshed core documentation (`README.md`, `docs/README.md`,
  `docs/QUICKSTART.md`, `CONTRIBUTING.md`, `docs/agent-context/renderer-internals.md`)
  to reflect the plugin architecture and current API.
- Added a visual gallery section to `README.md` with the GR black hole
  showcase as the hero image.
- Removed the `notebooks/` directory from the repository.

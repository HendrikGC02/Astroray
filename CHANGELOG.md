# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

---

### Pillar 2 — Spectral core (in progress)

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

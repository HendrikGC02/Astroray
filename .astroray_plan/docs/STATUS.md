# Astroray Status

**Last updated:** 2026-04-26 (pkg13 fully complete — all four threads merged: physics/infra #103, pkg13a Copilot #104, pkg13b Copilot #106, pkg13c missing plugins #107)

This is the source-of-truth for "where are we?" Updated by the overseer
at the start of each week, and by the project owner when a significant
event happens (pillar transition, major failure, scope change).

If you are reading this to start a coding session: check **Pillar
status** for what's active, then check **This week** for what you
personally should pick up.

---

## Pillar status

| # | Name | Status | % | Next milestone | Blocked on |
|---|---|---|---|---|---|
| 1 | Plugin architecture | **Done** | 100% | — | — |
| 2 | Spectral core | **In progress** | ~90% | pkg14 spectral env map | ~~Pillar 1~~ |
| 3 | Light transport | Queued | 0% | — | Pillars 1, 2 |
| 4 | Astrophysics platform | Queued | 0% | Kerr | Pillars 1, 2 |
| 5 | Production polish | Ongoing | — | OpenEXR output | — |

**Pillar 1 package summary:**

| Package | Description | Status |
|---|---|---|
| pkg01 | Registry skeleton | done |
| pkg02 | Migrate Lambertian | done |
| pkg03 | Migrate remaining materials | done |
| pkg04 | Migrate textures + shapes | done |
| pkg05 | Integrator interface | done |
| pkg06 | Pass registry | done |

**Pillar 2 package summary:**

| Package | Description | Status |
|---|---|---|
| pkg10 | Spectral types (scaffolding) | done |
| pkg11 | Spectral path tracer | done |
| pkg12 | Spectral Lambertian override | done |
| pkg13 | Spectral remaining materials & textures (all threads: physics/infra, pkg13a, pkg13b, pkg13c) | **done** |
| pkg14 | Spectral environment map | queued |

---

## This week

**Week of:** 2026-04-21

### Track A (Claude Code)

- Package in flight: pkg14 (spectral environment map)
- Next session goal: implement spectral env map sampling in the spectral path tracer

### Track B (Copilot cloud)

- Assigned issues: —
- In review: —
- Queue depth: —

### Track C (Cline prototype)

- Active: no
- Current exploration: none

### Track D (Ralph loop)

- Last run: —
- Queue depth: —

---

## Recently merged (this week)

| Date | PR | Track | Pillar | Description |
|---|---|---|---|---|
| 2026-04-26 | pkg13c-missing-material-plugins | A | 2 | Created 4 missing material plugins: `oren_nayar` (OrenNayar diffuse + spectral override), `isotropic` (uniform volumetric phase function + spectral override), `two_sided` (wraps inner material, renders both faces + spectral delegation), `emissive` (two-sided omnidirectional emitter + `emittedSpectral`). Closes issue #105. 5 new tests; 223 passed, 1 skipped. **pkg13 fully complete.** |
| 2026-04-26 | #106 pkg13b Copilot | B | 2 | 8 procedural texture `sampleSpectral` overrides (checker, noise, gradient, voronoi, brick, musgrave, magic, wave). |
| 2026-04-26 | #104 pkg13a Copilot | B | 2 | `evalSpectral` overrides for Phong, Disney, NormalMapped, `emittedSpectral` for DiffuseLight. |
| 2026-04-26 | #103 pkg13 physics/infra | A | 2 | `Texture::sampleSpectral` virtual + ImageTexture eager cache; Metal per-λ Schlick Fresnel; Dielectric/Mirror delta overrides; Subsurface cached albedo + transmission spectrum. 206 passed (+8 new). |
| 2026-04-25 | pkg12-spectral-lambertian | A | 2 | First concrete `evalSpectral` override: `LambertianPlugin` gains `RGBAlbedoSpectrum albedo_spec_` (eager ctor cache) and `evalSpectral` returning `albedo_spec_.sample(lambdas) * cosTheta / PI`. Cache eliminates per-call Jakob-Hanika LUT lookup. Cornell A/B within 3%. 5 new tests; 198 passed, 1 skipped. |
| 2026-04-25 | pkg11-spectral-path-tracer | A | 2 | Spectral path tracer plugin (`set_integrator("spectral_path_tracer")`), `IntegratorKind` enum, `Material::evalSpectral`/`emittedSpectral` defaults via Jakob-Hanika upsample, `Renderer::pathTraceSpectral` helper + XYZ accumulator + single sRGB conversion. Cornell A/B match within ~3% per channel; 1.34× wall-clock vs RGB. Legacy `path` integrator stays the default. 193 tests (+4 new). |
| 2026-04-24 | pkg10-spectral-types | A | 2 | Spectral scaffolding: `SampledWavelengths`, `SampledSpectrum`, three `RGB*Spectrum` upsamplers over a shipped Jakob-Hanika LUT, CIE 1964 10° CMF + D65 SPD, Python bindings, 189 tests (+20 new). No integration — renderer is untouched. |
| 2026-04-22 | feat/pkg06-pass-registry | A | 1 | Pass registry; OIDN + 3 AOV plugins; Framebuffer API; add_pass/clear_passes bindings; 169 tests passing. **Pillar 1 complete.** |
| 2026-04-22 | feat/pkg05-integrator-interface | A | 1 | Integrator base class, PathTracer + AO plugins, Blender UI selector; 165 tests passing |
| 2026-04-21 | feat/pkg04-migrate-textures-shapes | A | 1 | Migrate 9 textures + 5 shapes to plugin files; 161 tests passing |
| 2026-04-21 | feat/pkg03-migrate-remaining-materials | A | 1 | Migrate remaining materials to plugin files |

---

## Active packages

| Package | Track | Status | Blocker |
|---|---|---|---|
| pkg14-spectral-env-map | A | queued | pkg13 (now complete) |

---

## Known issues

- `include/raytracer.h` and `include/advanced_features.h` still contain texture class bodies (`CheckerTexture`, `NoiseTexture`, etc.). These are used directly by `blender_module.cpp` and will be cleaned up in a future package if the plan calls for it.

---

## Decisions pending (for project owner)

- Confirm whether lights should be migrated to plugins (currently out of scope per pkg04 non-goals) and if so, which package handles it.

---

## Changelog

Brief notes on notable events.

- **2026-04-26** — pkg13 fully complete. All four threads merged: (1) physics/infra PR #103 — Texture::sampleSpectral, ImageTexture cache, Metal/Dielectric/Mirror/Subsurface evalSpectral; (2) Copilot PR #104 — Phong/Disney/NormalMapped/DiffuseLight evalSpectral/emittedSpectral; (3) Copilot PR #106 — 8 procedural texture sampleSpectral overrides; (4) pkg13c PR — 4 new plugins: oren_nayar, isotropic, two_sided, emissive. Every shading event in the spectral pipeline now has a concrete override. Test suite: 223 passed, 1 skipped. Pillar 2 ~90%.
- **2026-04-24** — pkg10 merged: Pillar 2 scaffolding. New `include/astroray/spectrum.h` defines `SampledWavelengths`, `SampledSpectrum`, `RGBAlbedoSpectrum`, `RGBUnboundedSpectrum`, `RGBIlluminantSpectrum` (float, 4 samples, 360-830 nm). `src/spectrum.cpp` loads the shipped Jakob-Hanika sRGB LUT lazily from `data/spectra/rgb_to_spectrum_srgb.coeff` and embeds the CIE 1964 10° CMF and D65 SPD as `constexpr` tables. New `astroray_core_impl` CMake target; `ASTRORAY_DATA_DIR` compile definition + env-var override for runtime data discovery. Python bindings expose every type plus a top-level `rgb_to_spectrum()` helper. No integration into any material, integrator, pass, or env map — that is pkg11+. Test suite: 189 passed, 1 skipped (20 new spectrum tests).
- **2026-04-22** — pkg06 merged: Pass registry closes Pillar 1. `Pass` abstract base + `Framebuffer` named-buffer API in `include/astroray/pass.h` / `raytracer.h`. Five plugins in `plugins/passes/` (OIDN denoiser, depth/normal/albedo AOV). `add_pass`/`clear_passes` Python bindings. `pass_registry_names()` module function. Blender `use_denoising` property wired to `add_pass("oidn_denoiser")`. Inline OIDN code removed from `blender_module.cpp`. Test suite: 169 passed, 1 skipped.
- **2026-04-22** — pkg05 merged: `Integrator` abstract base class in `include/astroray/integrator.h`; PathTracer and AmbientOcclusion plugins in `plugins/integrators/`; `SampleResult` + `Renderer::traceFull()` for AOV preservation; `set_integrator` Python binding + `integrator_registry_names()`; Blender `integrator_type` EnumProperty wired into render. Test suite: 165 passed, 1 skipped.
- **2026-04-21** — pkg04 merged: 9 texture plugin files + 5 shape plugin files. `Sphere`/`Triangle` bodies moved to `include/astroray/shapes.h`. Python bindings `sample_texture()`, `texture_registry_names()`, `shape_registry_names()` added. Test suite: 161 passed, 1 skipped.
- **2026-04-21** — pkg03 merged: all remaining material types (Metal, Dielectric, Phong, Disney, DiffuseLight, NormalMapped, Emissive, Isotropic, OrenNayar, TwoSided) migrated to plugin files.
- **Earlier** — pkg01/02 merged: registry skeleton and Lambertian plugin established the pattern.

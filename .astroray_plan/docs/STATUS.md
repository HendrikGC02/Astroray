# Astroray Status

**Last updated:** 2026-05-01 (pkg28 complete — NRC training buffered at frame boundary; Pillar 3 package queue implemented)

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
| 2 | Spectral core | **Done** | 100% | — | — |
| 3 | Light transport | **Validation** | 85% | Pillar acceptance scenes | ~~Pillars 1, 2~~ |
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
| pkg14 | Spectral environment map + flip default | **done** |

**Pillar 3 package summary:**

| Package | Description | Status |
|---|---|---|
| pkg20 | ReSTIR reservoir core | implemented |
| pkg21 | ReSTIR light sample abstraction | implemented |
| pkg22 | ReSTIR initial sampling | implemented |
| pkg23 | ReSTIR temporal/spatial reuse design | implemented |
| pkg24 | ReSTIR validation | implemented |
| pkg25 | tiny-cuda-nn prototype | implemented |
| pkg26 | NRC prototype | implemented |
| pkg27 | NRC integrator plugin | implemented |
| pkg28 | NRC training buffer | implemented |

---

## This week

**Week of:** 2026-04-28

### Track A (Claude Code)

- Package in flight: —
- pkg20–pkg28 complete. Next target: Pillar 3 acceptance validation
  (ReSTIR quality/perf scenes and NRC indirect-quality timing).

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

### Track E (Codex)

- Recently merged: PR #116 (`codex/render-test-triage`) and PR #117 (`codex/gr-spectral-dispatch`).
- In review: PR #119 (`codex/native-gr-spectrum`) — native sampled-spectrum GR disk emission.
- Active: issue #114 (`codex/restir-package-specs`) — Pillar 3 ReSTIR package specs through pkg25, plus Pillar 2 verification/doc alignment.

---

## Recently merged (this week)

| Date | PR | Track | Pillar | Description |
|---|---|---|---|---|
| 2026-04-26 | pkg14-spectral-env-map | A | 2 | Spectral HDRI atlas (`spectralAtlas_` in `EnvironmentMap`, bilinear spectral-space interpolation); env-miss wired to `evalSpectral`; legacy `PathTracer` plugin + `pathTrace()` deleted; `"spectral_path_tracer"` renamed `"path_tracer"`; `IntegratorKind`/`spectralMode_` removed; `Material::eval` virtual deleted; `Material::evalSpectral` made pure virtual. **Pillar 2 complete.** |
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
| native-gr-spectrum | E | in review | PR #119 |
| pillar-3-acceptance-validation | A | queued | pkg20-pkg28 implemented |

---

## Known issues

- `include/raytracer.h` and `include/advanced_features.h` still contain texture class bodies (`CheckerTexture`, `NoiseTexture`, etc.). These are used directly by `blender_module.cpp` and will be cleaned up in a future package if the plan calls for it.
- ReSTIR work is now scoped at package-file level in issue #114; implementation should start at `pkg20` after review.
- Windows verification is sensitive to stale build caches; test bootstrap now supports `ASTRORAY_BUILD_DIR` and standard `build/Release` layouts, but the old `build/` cache on this workstation still points at a missing MinGW install.
- Transparent/glass objects still do not produce prism-style spectral
  dispersion in the current spectral path tracer. The glass-prism rainbow render
  needs wavelength-dependent dielectric sampling before it can become a
  non-xfailed image/angle-spread test. Draft follow-up:
  `pkg29-spectral-dielectric-prism.md`.

---

## Decisions pending (for project owner)

- Confirm whether lights should be migrated to plugins (currently out of scope per pkg04 non-goals) and if so, which package handles it.

---

## Changelog

Brief notes on notable events.

- **2026-05-01** — pkg28 complete. `neural-cache` now buffers warmup training
  samples during `sampleFull()` and performs one padded tiny-cuda-nn training
  step in `Integrator::endFrame()`, so cache queries use the previous frame's
  parameters while current-frame targets are collected. Added
  `pkg28-nrc-training-buffer.md`. Default and opt-in focused tests pass; opt-in
  tiny-cuda-nn builds require a short build path on Windows because CUTLASS docs
  exceed path-length limits under the OneDrive repo path.
- **2026-05-01** — pkg27 complete. Added `plugins/integrators/neural_cache.cpp`
  and registered `neural-cache`. Default builds keep the plugin selectable via
  a spectral path-tracer fallback; `ASTRORAY_TINY_CUDA_NN=ON` now builds a
  reusable `astroray_neural_cache` backend from `src/neural_cache.cu` and links
  it into production targets. Focused tests cover registry exposure and Python
  selection.
- **2026-05-01** — pkg26 complete. `NeuralCache` (16-in/16-out FullyFusedMLP, Adam, RelativeL2) + `nrc_smoke_render` Cornell box harness both working on RTX 5070 Ti (sm_120). Two tcnn master gotchas resolved: (1) `TCNN_MIN_GPU_ARCH=120` static_assert override for sm_89 build; (2) `BATCH_SIZE_GRANULARITY=256` in master (was 128 in v1.x) — `BATCH_ALIGN` updated to 256. Luminance: 0.2841 (frame 1) → 0.4317 (frame 50), Δ+52%. See `.astroray_plan/docs/nrc-prototype-notes.md`.
- **2026-05-01** — pkg25 fully complete. Driver updated from 576.57 to 596.36; CUDA 13.2 runtime now supported. Switched `GIT_TAG` to master (fixes sm_89 FullyFusedMLP crash); added `set_params()` call before `forward()` (required in tcnn master). `tcnn_smoke.exe` reports `OK (non-finite: 0 / 4096 outputs)`. VS Code cmake settings updated to use VS 2022 generator with `BUILD_PYTHON_MODULE=ON`; conftest extended to check `build_tcnn/Release`. pkg26 spec drafted. See `.astroray_plan/docs/tiny-cuda-nn-prototype-notes.md` for full resolution log.
- **2026-04-30** — pkg25 build complete; runtime initially blocked by driver version. tiny-cuda-nn master FetchContent integration works; `tiny-cuda-nn.lib` and `tcnn_smoke.exe` build cleanly via MSVC+CUDA 13.2.
- **2026-04-30** — pkg24 complete. Temporal and spatial reservoir reuse implemented in `restir_di.cpp` (Bitterli et al. 2020, Algorithms 1–3). `targetLuminanceRGB()` added to `ReSTIRCandidate` for wavelength-independent cross-frame W values. `set_integrator_param` Python binding added. 13-test validation suite covers all 6 design-note criteria (finitude, determinism, temporal variance, spatial MSE, bias magnitude for both passes, default-mode regression). 287 passed, 1 skipped, 16 xfailed.
- **2026-04-29** — Verification/docs pass: pytest collection restored to 229 tests when pointed at a valid Windows build via `ASTRORAY_BUILD_DIR`; full suite baseline on the fresh MSVC build is `211 passed, 1 skipped, 16 xfailed, 1 xpassed`. Test bootstrap now understands standard `build/Release` layouts and custom build dirs. Drafted `pkg25` and aligned status docs with the already-landed Pillar 2 stabilization work and ReSTIR package sequence.
- **2026-04-28** — PR #116 and PR #117 merged. Codex docs/local-agent scaffolding, render-output triage, refreshed deterministic spectral tests, and restored spectral black-hole GR dispatch are now on `main`. PR #119 is in review for native spectral GR disk emission; issue #114 is active for Pillar 3 ReSTIR package specs.
- **2026-04-26** — pkg14 complete. Spectral HDRI atlas built at load time; env-miss path wired to `evalSpectral`; legacy RGB `PathTracer` plugin and `pathTrace()` kernel deleted; registry entry renamed `"path_tracer"`; `Material::evalSpectral` is now pure virtual; `Material::eval` virtual removed. **Pillar 2 is 100% complete (pkg10–pkg14).**
- **2026-04-26** — pkg13 fully complete. All four threads merged: (1) physics/infra PR #103 — Texture::sampleSpectral, ImageTexture cache, Metal/Dielectric/Mirror/Subsurface evalSpectral; (2) Copilot PR #104 — Phong/Disney/NormalMapped/DiffuseLight evalSpectral/emittedSpectral; (3) Copilot PR #106 — 8 procedural texture sampleSpectral overrides; (4) pkg13c PR — 4 new plugins: oren_nayar, isotropic, two_sided, emissive. Every shading event in the spectral pipeline now has a concrete override. Test suite: 223 passed, 1 skipped. Pillar 2 ~90%.
- **2026-04-24** — pkg10 merged: Pillar 2 scaffolding. New `include/astroray/spectrum.h` defines `SampledWavelengths`, `SampledSpectrum`, `RGBAlbedoSpectrum`, `RGBUnboundedSpectrum`, `RGBIlluminantSpectrum` (float, 4 samples, 360-830 nm). `src/spectrum.cpp` loads the shipped Jakob-Hanika sRGB LUT lazily from `data/spectra/rgb_to_spectrum_srgb.coeff` and embeds the CIE 1964 10° CMF and D65 SPD as `constexpr` tables. New `astroray_core_impl` CMake target; `ASTRORAY_DATA_DIR` compile definition + env-var override for runtime data discovery. Python bindings expose every type plus a top-level `rgb_to_spectrum()` helper. No integration into any material, integrator, pass, or env map — that is pkg11+. Test suite: 189 passed, 1 skipped (20 new spectrum tests).
- **2026-04-22** — pkg06 merged: Pass registry closes Pillar 1. `Pass` abstract base + `Framebuffer` named-buffer API in `include/astroray/pass.h` / `raytracer.h`. Five plugins in `plugins/passes/` (OIDN denoiser, depth/normal/albedo AOV). `add_pass`/`clear_passes` Python bindings. `pass_registry_names()` module function. Blender `use_denoising` property wired to `add_pass("oidn_denoiser")`. Inline OIDN code removed from `blender_module.cpp`. Test suite: 169 passed, 1 skipped.
- **2026-04-22** — pkg05 merged: `Integrator` abstract base class in `include/astroray/integrator.h`; PathTracer and AmbientOcclusion plugins in `plugins/integrators/`; `SampleResult` + `Renderer::traceFull()` for AOV preservation; `set_integrator` Python binding + `integrator_registry_names()`; Blender `integrator_type` EnumProperty wired into render. Test suite: 165 passed, 1 skipped.
- **2026-04-21** — pkg04 merged: 9 texture plugin files + 5 shape plugin files. `Sphere`/`Triangle` bodies moved to `include/astroray/shapes.h`. Python bindings `sample_texture()`, `texture_registry_names()`, `shape_registry_names()` added. Test suite: 161 passed, 1 skipped.
- **2026-04-21** — pkg03 merged: all remaining material types (Metal, Dielectric, Phong, Disney, DiffuseLight, NormalMapped, Emissive, Isotropic, OrenNayar, TwoSided) migrated to plugin files.
- **Earlier** — pkg01/02 merged: registry skeleton and Lambertian plugin established the pattern.

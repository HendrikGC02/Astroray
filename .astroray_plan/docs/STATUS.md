# Astroray Status

**Last updated:** 2026-05-03 (pkg38 spectral material database complete)

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
| 3 | Light transport | **Validation** | 88% | NRC batched-inference speedup target | ~~Pillars 1, 2~~ |
| 4 | Astrophysics platform | Preparation | 5% | Kerr metric extraction | Pillars 1, 2 complete; backend parity bridge recommended before GPU parity claims |
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
| pkg27a | NRC training observability | implemented |
| pkg27b | NRC indirect validation + graphs | implemented |
| pkg28 | NRC training buffer | implemented |

**Spectral dielectric chain (Pillar 2 follow-up):**

| Package | Description | Status |
|---|---|---|
| pkg30 | Spectral BSDF sampling interface (`sampleSpectral` on Material) | implemented |
| pkg31 | Spectral dielectric with Sellmeier dispersion | implemented |
| pkg29 | Spectral dielectric prism validation | implemented |
| pkg29a | Scoped caustic validation for spectral optics | implemented |

**Material backend parity bridge (Pillar 2/5 follow-up):**

| Package | Description | Status |
|---|---|---|
| pkg34 | Material backend capabilities + no silent GPU fallback | **done** |
| pkg35 | Spectral GPU material kernels | **done** |
| pkg36 | Shared material closure graph | **done** |
| pkg37 | Blender addon backend refresh + runtime diagnostics | open |

**Visual diagnostics & production polish (Pillar 5):**

| Package | Description | Status |
|---|---|---|
| pkg32 | Visual diagnostics & benchmark renders | **done** |
| pkg33 | OIDN FetchContent integration | **done** |
| pkg38 | Spectral material profile database | **done** |
| pkg39 | Spectral profile C++ loader | open |

**Astrophysics platform (Pillar 4):**

| Package | Description | Status |
|---|---|---|
| pkg40 | Kerr metric plugin and Schwarzschild extraction | open |
| pkg41 | Kerr geodesic validation | open |
| pkg42 | Synchrotron emission and relativistic jets | open |
| pkg43 | Slim disk accretion model | open |
| pkg44 | ADAF accretion model | open |
| pkg45 | CLOUDY emissivity table preprocessing | open |
| pkg46 | HII region emission plugin | open |
| pkg47 | FITS loader | open |
| pkg48 | HDF5/NumPy simulation-volume loader | open |
| pkg49 | SPH-to-volume preprocessing | open |
| pkg50 | Weak lensing pass | open |
| pkg51 | Synthetic telescope post-process | open |

---

## This week

**Week of:** 2026-05-03

### Track A (Claude Code)

- pkg29 prism validation is complete.
- Complete: pkg32 visual diagnostics, pkg33 OIDN, pkg34 backend capability
  guardrails, pkg35 spectral GPU material payloads, and pkg36 shared closure
  graphs.
- Next up: pkg37 Blender addon backend refresh.
- Pillar 4 can begin with pkg40 once the current registry/reference cleanup is merged.

### Track B (Copilot cloud)

- Assigned issues: #121 (albedo AOV), #122 (normal AOV), #123 (depth AOV),
  #124 (bounce heatmap pass), #125 (sample heatmap pass), #126 (convergence
  tracker script), #127 (showcase render script).
- **Action needed:** Enable Copilot coding agent in repo Settings → Copilot
  → Policies, then assign `copilot` to issues #121–#127.
- Queue depth: 7

### Track C (Cline prototype)

- Active: no
- Current exploration: none

### Track D (Ralph loop)

- Last run: —
- Queue depth: —

### Track E (Codex)

- Recently merged: PR #116 (`codex/render-test-triage`), PR #117 (`codex/gr-spectral-dispatch`), and PR #119 (`codex/native-gr-spectrum`) — native sampled-spectrum GR disk emission.
- Complete: pkg29 implementation; local triage work recorded convergence tracker repair, GGX/rough-metal sampling cleanup, and Disney rough-glass transmission.
- Active: Pillar 4 prep cleanup — registry scaffolds, Schwarzschild baseline reference, package-number alignment, and material backend bridge specs.

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
| pkg34 | A | **done** | — |
| pkg37 | A/E | open | pkg34 recommended for capability-aware Auto mode |
| pkg32 | A+B | **done** | — |
| pkg33 | A | **done** | — |
| pkg38 | B | **done** | — |
| pkg40 | A | open | current registry/reference cleanup |

---

## Known issues

- `include/raytracer.h` and `include/advanced_features.h` still contain texture class bodies (`CheckerTexture`, `NoiseTexture`, etc.). These are used directly by `blender_module.cpp` and will be cleaned up in a future package if the plan calls for it.
- ReSTIR work is now scoped at package-file level in issue #114; implementation should start at `pkg20` after review.
- Windows verification is sensitive to stale build caches; test bootstrap now supports `ASTRORAY_BUILD_DIR` and standard `build/Release` layouts, but the old `build/` cache on this workstation still points at a missing MinGW install.
- ReSTIR temporal variance has a known tiny deterministic inversion on this
  workstation (`0.0723` temporal vs `0.0719` no-reuse). The test now xfails
  only this narrow <2% baseline condition while still failing larger regressions.
- Prism-style spectral dispersion now has a deterministic validation scene and
  saved render outputs. pkg29a adds caustic validation scenes, metrics, and an
  opt-in specular-chain connection experiment; it is still not a final
  caustic-perfect showcase.
- GPU material support is now capability-gated, so unsupported materials no
  longer silently lower to approximate CUDA records. pkg35 adds sampled
  wavelength payloads and `gpu_spectral` metadata for the core GPU material
  set; Sellmeier direction-splitting and true spectral emitter parameter
  upload remain CPU-only. pkg36 expands shared closure lowering.
- The Blender addon can import and render through Astroray, but its backend
  UI and packaging are stale. pkg37 refreshes Auto/GPU/CPU selection,
  viewport GPU parity, CUDA/tiny-cuda-nn packaging, and runtime diagnostics.

---

## Decisions pending (for project owner)

- Confirm whether lights should be migrated to plugins (currently out of scope per pkg04 non-goals) and if so, which package handles it.

---

## Changelog

Brief notes on notable events.

- **2026-05-03** — pkg38 complete. Spectral material profile database built from USGS Spectral Library v7, ECOSTRESS/JHU spectra, Rakic 1998 Lorentz-Drude model for polished metals (Al, Au), and Bashkatov 2005 digitised skin measurements. 40 materials across 7 categories (vegetation, earth, building, metal, fabric, paint, human), 441 wavelengths at 5nm from 300-2500nm. ASPR binary format (72 KB), profiles_metadata.json, sources.md provenance. 18 tests all pass; Wood effect 3.8x/5.9x, water R(1000nm)=0.008, Al/Au mean R>0.90.
- **2026-05-03** — pkg36 complete. Added shared material closure graphs,
  Python graph inspection, and CUDA closure-graph lowering. Lambertian,
  metal, flat dielectric, Disney plastic/glass, and a new `closure_matte`
  plugin now exercise the same graph path for backend metadata and GPU upload;
  graphless materials remain explicit CPU-only escape hatches. Focused
  validation: CUDA build passed; closure/backend/GPU material tests passed.
- **2026-05-03** — pkg35 complete. Added compact CUDA sampled-wavelength and
  sampled-spectrum payloads, spectral BSDF/emitter dispatch helpers for core
  RGB-derived GPU materials, Python `gpu_spectral` capability metadata, and
  contact-sheet CSV reporting. Flat-IOR dielectric/glass is spectral-GPU
  capable; Sellmeier dispersion plus line/blackbody emitters remain explicit
  CPU-only until dedicated GPU parameter lowering exists. Focused validation:
  CUDA build passed; pkg35/backend/GPU parity tests passed.
- **2026-05-03** — pkg33 complete. OIDN auto-detection (env var, common Windows paths, FetchContent 2.3.3 fallback) added to CMakeLists.txt. OIDN 2.4.1 found at C:/oidn; `ASTRORAY_OIDN_ENABLED` now active. Duplicate function definitions from the rough-Disney-glass merge fixed in `disney.cpp`. Blender addon `__init__.py` probes `addon_dir/oidn/` and `C:/oidn/bin` for DLLs; `build_blender_addon.py` copies them into the zip. New `tests/test_oidn_denoiser.py` verifies: registry presence, variance reduction (30× at 4 spp), and side-by-side PNG in `test_results/oidn_before_after.png`. 3 new tests; all pass.
- **2026-05-03** — pkg32 complete. Visual AOVs now have non-trivial output
  coverage, convergence/showcase scripts are verified, and
  `scripts/oidn_comparison.py` writes noisy/denoised/side-by-side OIDN PNGs
  when OIDN is compiled in.
- **2026-05-03** — pkg34 complete. Materials now expose backend capability
  metadata, CUDA upload rejects unsupported materials instead of silently
  lowering them to grey Lambertian/generic metal/generic glass, Python exposes
  `get_material_backend_capabilities()`, and the material contact sheet records
  backend choice and fallback reasons from C++ metadata.
- **2026-05-03** — Pillar 4 prep cleanup. Added `MetricRegistry`,
  `EmissionRegistry`, `ASTRORAY_REGISTER_METRIC`, and
  `ASTRORAY_REGISTER_EMISSION` scaffolding to `register.h`; captured the
  pre-refactor Schwarzschild reference render at
  `tests/reference/schwarzschild_baseline_256.png`; updated Pillar 4 package
  numbering to pkg40-pkg51; added pkg34-pkg36 specs for material CPU/GPU
  backend parity.
- **2026-05-03** — Optical material cleanup started for pkg29 follow-up. Added
  a scoped pkg29a caustic-validation design for issue #145, plus issue #142/#146
  work on optical-glass presets and thin architectural glass.
- **2026-05-03** — pkg29a complete. Added `caustic_path_tracer`, three caustic
  validation scenes, saved PNG diagnostics, JSON/CSV stats, and
  `scripts/benchmark_caustic_transport.py`. The opt-in integrator records
  `caustic_connections` and `caustic_energy` while leaving `path_tracer` as
  the default/reference.
- **2026-05-03** — Codex material triage recorded: convergence tracker repair,
  GGX/rough-metal sampling cleanup, and Disney rough-glass transmission with
  CPU/CUDA material support and high-sample GPU contact-sheet diagnostics.
- **2026-05-02** — pkg29 complete. Added
  `tests/scenes/prism_reference.py` and `tests/test_spectral_prism.py`.
  The test renders flat-IOR and BK7 triangular prisms, saves visual artifacts,
  and verifies measurable red/blue centroid spread in the dispersive render.
  Focused validation: `tests/test_spectral_prism.py` passed.
- **2026-05-01** — Created pkg30–pkg33 specs. pkg30: `sampleSpectral()` virtual
  on Material (interface-only, no material changes). pkg31: Sellmeier dispersion
  in DielectricPlugin with `terminateSecondary()`. pkg32: visual diagnostics
  suite (AOV passes, convergence tracker, showcase renders). pkg33: OIDN
  FetchContent fallback so the denoiser actually builds. Opened GitHub issues
  #121–#127 for Copilot-scoped Track B work (3 AOV stub implementations,
  2 heatmap passes, convergence tracker, showcase script). pkg29 (prism
  validation) unblocked once pkg30+pkg31 land.
- **2026-05-01** — pkg28 complete. `neural-cache` now performs backend
  readiness once per frame, buffers warmup samples, pads and trains from
  `endFrame()`, exposes `backend_ready`/`enable_inference` stats, and keeps
  cache inference behind an explicit parameter because current per-sample
  inference is slower than the spectral path tracer. Auto/default therefore
  stays on the fastest validated path-tracer fallback until batched inference
  is performance-positive. Latest 64x64 opt-in benchmark with one untimed
  warmup render: path tracer 0.0391s/frame, auto default 0.0499s/frame, NRC
  fallback 0.0420s/frame, NRC training backend 0.0318s/frame (1.23x, but not
  yet the original 30% speedup/quality target).
- **2026-05-01** — pkg27b complete. Added
  `scripts/benchmark_light_transport.py`,
  `tests/scenes/neural_cache_indirect.py`, and
  `tests/test_neural_cache_validation.py`. The benchmark writes JSON/CSV stats
  and PNG charts comparing path tracer, auto default, NRC fallback, and NRC
  backend. `Renderer::render()` now auto-selects the fastest validated default;
  Blender exposes `Auto (Best Available)` first. The first
  32x32 opt-in benchmark proves training/finiteness but not speedup:
  `neural_cache_backend` was 0.86x path-tracer speed and `auto_default` was
  dominated by first-use training/init overhead on the tiny scene, so pkg28
  remains in validation for performance tuning.
- **2026-05-01** — pkg28 split into explicit completion gates. Added
  `pkg27a-nrc-training-observability.md` and
  `pkg27b-nrc-indirect-validation.md`; pkg27a is complete with
  `get_integrator_stats()` and NRC queue/train/fallback counters. The existing
  pkg28 implementation still buffers warmup training samples during
  `sampleFull()` and performs one padded tiny-cuda-nn training step in
  `Integrator::endFrame()`; pkg27b now owns the indirect-scene validation data.
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

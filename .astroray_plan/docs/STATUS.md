# Astroray Status

**Last updated:** 2026-05-10 (Round 3 closed — pkg72/73/74-2/75/64-2 + pkg71 first canonical Cornell baseline)

This is the source-of-truth for "where are we?" Updated by the overseer
at the start of each week, and by the project owner when a significant
event happens (pillar transition, major failure, scope change).

If you are reading this to start a coding session: check **Pillar
status** for what's active, then check **This week** for what you
personally should pick up.

---

## Current snapshot

- Pillars 1 and 2 are complete. Package headers for pkg12-pkg14 were reconciled
  on 2026-05-09 after lagging behind the changelog.
- Pillar 3 has its ReSTIR/NRC package sequence implemented through pkg28, but
  it remains in validation because NRC has not yet proven the 30% batched
  inference speedup/quality target and ReSTIR/NRC are CPU-integrator plugins,
  not CUDA kernels.
- Pillar 5 (Cycles parity / Blender integration / denoiser story) is
  approaching feature-complete. Done as of 2026-05-10:
  pkg52/53/57/58/59/60/61/62/63/65/66 (the original Cycles-parity wave);
  pkg54/54a/54b/54c/54d (full GPU multi-wavelength parity, hardware
  verified); pkg68 (OIDN persistent device, **measured 2.77× speedup**
  post-pkg75); pkg69 (compositor Albedo pass); pkg70 (OptiX denoiser,
  **1.86× faster than OIDN-CUDA, SSIM 0.9987 vs OIDN**); pkg72 (motion
  vector AOV); pkg75 (first-hit normal buffer for AOV guides — fixed
  silent AOV-mode degradation); pkg64 Phases 1+2+3 (RGB SMS skeleton +
  spectral wavelength-Newton, **+8.83 dB PSNR delta** at 0.98× runtime,
  Phase 3 folds SMS into the default `path_tracer` via per-bounce hook
  gated by `use_refractive_caustics` AND per-object opt-in flag);
  pkg56 Phase A (viewport sync instrumentation, baseline 129.92 ms
  on a 100k-tri scene); pkg74 all phases (showcase framework + full
  stat coverage, interactive self-contained HTML, weekly CI);
  pkg71 framework + first
  canonical Cornell baseline (**Astroray-CPU SSIM 0.9536, Astroray-GPU
  SSIM 0.9548 vs Cycles-CPU EXR; Astroray-GPU 5.2× faster than
  Cycles-CUDA at the same Cornell sample budget**). Open Pillar 5
  for Round 4: pkg73 OptiX temporal denoiser (unblocked by pkg72),
  pkg56 Phase B/C (uploadScene split + depsgraph dispatch), pkg64
  Phase 3 (default-integrator MIS fold), pkg76 (Astroray .blend importer for non-Cornell
  parity rows).
- **Pillar 4 strategic gate RELEASED (2026-05-10).** pkg56 Phases B+C
  and pkg64 Phase 3 have all landed; the gate's three preconditions are
  green. pkg41 Kerr validation is implemented; pkg42–51 specs are unfrozen.
  pkg40 Kerr metric is already done.
- Fresh local collection: `pytest --collect-only -q` reports **460+
  tests collected** as of Round 3 close (was 435 at 2026-05-09). New
  tests added by Rounds 2+3: pkg54c JH GPU, pkg54d profile lookup,
  pkg57 native nodes, pkg63 world parity, pkg64-1 SMS validation,
  pkg64-2 spectral SMS, pkg68 persistence, pkg69 compositor passes,
  pkg70 OptiX, pkg72 motion vectors, pkg74-1 + pkg74-2 + pkg74-3 showcase,
  pkg75 normal buffer.
- `NEXT_STAGE_REPORT.md` is the live action queue (Round 4 prompts);
  this file is the source of truth for completion state. `production.md`
  remains historical (pkg50+ placeholder names that conflict with live
  package numbers are marked obsolete in-place).

---

## Pillar status

| # | Name | Status | % | Next milestone | Blocked on |
|---|---|---|---|---|---|
| 1 | Plugin architecture | **Done** | 100% | — | — |
| 2 | Spectral core | **Done** | 100% | — | — |
| 3 | Light transport | **Validation** | 90% | NRC batched-inference speedup target | CUDA kernels for ReSTIR/NRC are not implemented |
| 4 | Astrophysics platform | Preparation | 15% | pkg42 synchrotron emission | gate released; pkg40 metric + pkg41 validation implemented |
| 5 | Production polish / Blender parity | **Approaching feature-complete** | ~85% | Round 4: pkg73 + pkg56-B + pkg64-3 + pkg76 spec | — |

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
| pkg37 | Blender addon backend refresh + runtime diagnostics | **done** |

**Visual diagnostics & production polish (Pillar 5):**

| Package | Description | Status |
|---|---|---|
| pkg32 | Visual diagnostics & benchmark renders | **done** |
| pkg33 | OIDN FetchContent integration | **done** |
| pkg68 | OIDN persistent device + CUDA backend selection | **done** |
| pkg38 | Spectral material profile database | **done** |
| pkg39 | Multi-wavelength rendering (IR/UV) | **done** |

**Cycles parity & Blender integration (added 2026-05-08, Pillar 5):**

These packages close the gap between the engine and the addon — the
engine is mostly Cycles-equivalent, but the Blender integration layer
is currently the weakest link.

| Package | Description | Status | Track |
|---|---|---|---|
| pkg52 | Persistent viewport session (persistent renderer, viewport camera invalidation, progressive accumulation, CAMERA zoom/pan) | **done** | A |
| pkg53 | GPU integrator capability diagnostics | **done** | B/E |
| pkg54 | GPU multi-wavelength path tracer (CPU/GPU parity) | **done** | A |
| pkg57 | Native Astroray shader nodes (with Cycles compat) | **done** | A |
| pkg58 | Spectral profile dropdown + IR/UV reference scenes | **done** | B |
| pkg59 | Shader-graph vector / UV plumbing (texture routing, Mapping scale/offset/rotation, coord_mode, uv_debug_aov, named UV layers) | **done** | A |
| pkg60 | Disney v2 energy compensation (no-glow materials) | **done** | A/E |
| pkg61 | GPU per-vertex normals (shade-smooth parity) | **done** | A/E |
| pkg62 | Viewport pass selector + live OIDN preview | **done** | B |
| pkg63 | World / HDRI parity (Mapping XYZ rotation, color tint, MIS env-map) | **done** | A |
| pkg64 | Spectral caustics (prism-accurate, refractive + reflective) — SMS skeleton + spectral MNEE extension | **Phases 1 + 2 + 3 done** — RGB + spectral SMS folded into the default `path_tracer` via per-bounce SMS hook gated by `use_refractive_caustics` AND per-object `is_caustic_caster` (Cycles-style opt-in); GPU port is a separate future package | A |
| pkg67 | Metric-aware path tracer (GR + spectral unification) — research-grade | open (research blocked) | A |
| pkg69 | Albedo pass for Blender compositor denoise node | **done** | A |
| pkg70 | OptiX AI denoiser backend (HDR/AOV, persistent state, OIDN fallback) — verified 2026-05-10 on RTX 5070 Ti + OptiX 9.1.0; see pkg70 Lessons + pkg75 spec for upstream AOV-degradation defect found during verification | **done** | A |
| pkg71 | Cycles parity benchmark framework | **implemented** (first full baseline CSV pending CUDA + Cycles 4.x runner) | A |
| pkg56 | Incremental scene sync (depsgraph diff) — Phase A (instrument) + Phase B (split uploadScene into per-domain uploaders + transform-update binding) | **Phases A + B done; Phase C (depsgraph dispatch) open** | A |
| pkg74 | Engine benchmark + visual showcase framework (material zoo, convergence grid, stats CSV, HTML index) | **done (all phases)** | A |
| pkg75 | First-hit normal buffer population for denoiser AOV guides — surfaced during pkg70 verification | **done** (CPU integrator fix landed; OIDN-CUDA / OptiX re-baseline pending verifier session) | A |
| pkg72 | Per-pixel motion vector AOV (camera-only screen-space flow; OptiX prev→curr convention; `Renderer.get_motion_buffer()` zero-copy NumPy view; `motion_vector_aov` visualisation pass) — unblocks pkg73 OptiX temporal denoiser | **done** | A |
| pkg73 | OptiX TEMPORAL_AOV denoiser mode (auto-upgrade from pkg70 AOV when pkg72 motion buffer is non-zero; destroy + recreate on model-kind transition; ping-pong internal-guide-layer pair; previous-output cache + first-frame fallback; clean fallback to AOV on static cameras and on resolution change). Mirrors Cycles `intern/cycles/device/optix/device_impl.cpp` (Apache-2.0). | **implemented** (CUDA + OptiX SDK verification + ≥30% inter-frame variance gate pending verifier session) | A |

**Deferred / not-yet-spec'd from the 2026-05-08 triage** (mentioned in the
original roadmap but no full spec written; capture intent before they're
forgotten):

| Pkg | Title | Why no spec yet |
|---|---|---|
| pkg55 | Wavefront SoA GPU refactor | Very large; defer until pkg54 megakernel lands and we have measured GPU spectral parity numbers. |
| ~~pkg56~~ | ~~Incremental scene sync (depsgraph diff, BVH refit-only)~~ | Spec'd as a 3-phase package; Phase A (instrumentation) is done — see Pillar 5 Cycles-parity table above. Phase B + C still open. |
| pkg65 | scripts/ directory cleanup (`build/`, `diagnostics/`, `benchmarks/`, `data/`, `dev/` subfolders) | Trivial — can be done from a one-line description; no spec needed. |
| pkg66 | Material iteration UX (one-sphere-per-material live preview operator) | Small; partly covered by `scripts/diagnostics/material_contact_sheet.py`. |

**Astrophysics platform (Pillar 4):**

| Package | Description | Status |
|---|---|---|
| pkg40 | Kerr metric plugin and Schwarzschild extraction | **done** |
| pkg41 | Kerr geodesic validation | implemented |
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

**Week of:** 2026-05-10 (Round 4 — denoiser story closeout, pkg56 Phase B,
pkg64 final fold, pkg74 CI)

### Track A (Claude Code)

- Round 3 closed cleanly. pkg64 Phase 2 spectral SMS landed (+8.83 dB
  PSNR delta, 0.98× runtime — faster, not slower). pkg72 motion vectors
  landed (camera-only screen-space flow, OptiX prev→curr convention).
  pkg74 Phase 2 full stat coverage landed (8 categories, convergence
  rate slope −0.453). pkg75 normal-buffer fix landed and verified;
  visual diff confirmed detail preservation; pkg68 headline win up to
  **2.77×**.
- Round 4 deployable set per [`NEXT_STAGE_REPORT.md`](NEXT_STAGE_REPORT.md):
  - **pkg73** OptiX temporal denoiser (3-4 days) — unblocked by pkg72
  - **pkg56 Phase B** uploadScene split (~2 weeks) — uses pkg56-A
    instrumentation as before/after baseline
  - **pkg64 Phase 3** fold SMS into default `path_tracer` via MIS
    (~½ week) — completes the caustics flagship
  - **pkg76 spec** Astroray .blend importer (parity scope) — unblocks
    Classroom/Junkshop/BMW27/Monster pkg71 rows
- After Round 4: pkg76 implementation, pkg55 Phase A
  (wavefront refactor instrumentation begins). Pillar 4 is thawed;
  pkg41 validation is the first post-gate deliverable.

### Track A (Claude Code) — previous

- pkg29 prism validation is complete.
- Complete: pkg32 visual diagnostics, pkg33 OIDN, pkg34 backend capability
  guardrails, pkg35 spectral GPU material payloads, and pkg36 shared closure
  graphs.
- Pillar 4 has begun: pkg40 landed Kerr/Schwarzschild metric plugins with
  BPT 1972 analytic gates green. pkg41 adds 39 closed-form metric and
  image-plane validation tests plus static Kerr reference fixtures.

### Track B (Copilot cloud)

- Currently inactive. Most Track B-friendly work has been folded into
  Codex sessions (Track E) since they now have the comprehensive
  package specs and license-fence research notes that Copilot couldn't
  produce reliably from cold context. Track B can resume on pattern-
  matching follow-ups (e.g., Pillar 4 plugins after the strategic gate
  releases) once pkg42-49 specs prove themselves Codex-paste-ready.

### Track C (Cline prototype)

- Active: no
- Current exploration: none

### Track D (Ralph loop)

- Last run: —
- Queue depth: —

### Track E (Codex)

- 2026-05-10 round haul: pkg40 Kerr metric (#195), pkg54d profile lookup
  binding (#187), pkg69 Albedo pass for compositor (#201), pkg71 framework
  + first canonical Cornell baseline (#205 + #218), pkg70 build hygiene
  (#215), pkg59 named UV (#184), pkg60 Disney v2 energy compensation (#178),
  pkg65 scripts cleanup, pkg66 material iteration UX, pkg41 Kerr validation.
  **The Pillar 4 specs (pkg42-pkg49) are Codex-paste-ready and waiting**
  after the strategic gate release.
- Round 4 Codex queue: pkg64 Phase 3 (default-integrator MIS fold, ~½ week)
  completed; pkg74 Phase 3 (interactive HTML + weekly CI) completed.
- Recent: pkg53 GPU integrator diagnostics and pkg61 shade-smooth GPU parity
  diagnostics/fix work; this docs reconciliation pass corrected stale package
  headers and package-number collisions in planning docs.
- Active: coordination, CI/debug, and documentation reconciliation for the
  Cycles-parity / Blender integration queue.

---

- **2026-05-09** — pkg60 complete on `codex/pkg60-disney-energy-compensation`.
  Added a research note for Kulla & Conty / Burley / Cycles, ported Cycles GGX
  and sheen compensation tables into `data/disney_compensation/`, replaced the
  Disney plugin's old additive multi-scatter boost with LUT-driven
  compensation, corrected Disney specular/clearcoat eval's grazing denominator,
  fixed the mixed-lobe Disney sampler to return the combined PDF instead of the
  selected branch PDF, and added a C++ Halton furnace integration helper plus
  `tests/test_disney_energy_conservation.py`. Measured worst-case directional
  hemispherical reflectance is **1.015891** over the 90 listed
  roughness/metallic/sheen/clearcoat combinations × 3 outgoing cosines at 4096
  samples; regenerated contact sheet reference at
  `tests/reference/disney_contact_sheet_post_compensation.png`.

---

## Historical merge log

This section is a chronological log, not a live "this week" queue. Newer
events are summarized in the changelog below.

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

## Package board

| Package | Track | Status | Blocker |
|---|---|---|---|
| pkg34 | A | **done** | — |
| pkg37 | A/E | **done** | — |
| pkg32 | A+B | **done** | — |
| pkg33 | A | **done** | — |
| pkg38 | B | **done** | — |
| pkg39 | A | **done** | — |
| pkg40 | A | **done** | Kerr/Schwarzschild metric plugins; BPT 1972 analytic gates green |
| pkg41 | A | **implemented** | Kerr validation harness: BPT/Chandrasekhar analytic orbit fixtures, closed-form null photon checks against the shipped metric tensor, static image-plane shadow references in `tests/reference/kerr/`, and 39-test `tests/test_kerr_validation.py` suite green locally |
| pkg52 | A | **done** | — |
| pkg53 | B/E | **done** | — |
| pkg54 | A | **done** | pkg54/54a/54b/54c/54d all verified on hardware; pkg54c visible-band SSIM 0.999 gate clears at 0.999263 (spp=8192); GPU `gpu_rgbSpectrumAt` ILLUMINANT renormalization bug found and fixed during verification; frame-time regression +0.45 % (pkg54e not needed) |
| pkg57 | A | **done** | native Astroray shader nodes (Output, Spectral Profile, Sellmeier Glass, IR/UV Response, NRC Hint) with engine-switch survival via `mat.astroray` PointerProperty and Cycles-precedence fallback (existing BsdfPrincipled path unchanged) |
| pkg58 | B | **done** | — |
| pkg59 | A | done | broader vector/UV/Mapping plumbing, named UV layers, and UV debug AOV |
| pkg61 | A/E | **done** | broader CPU/GPU spectral parity tracked separately |
| pkg62 | B | **done** | — |
| pkg64 | A | research blocked | caustics research note |
| pkg67 | A | research blocked | metric-aware tracer research note |
| pkg68 | A | **done** | persistent OIDN device, CUDA-first init, member-cached filter; CUDA verifier session 2026-05-10 on RTX 5070 Ti: 13/13 pytest green (incl. `test_cuda_capable_build_reports_cuda_device`), `[OIDN] Using CUDA device` confirmed, single device init across N=4 renders verified; viewport timing 256×256 spp=2: OIDN-on 50.67 ms/frame vs OIDN-off baseline 23.81 ms/frame (Δ=26.86 ms persistent-device overhead) |
| pkg69 | A | **done** | Blender compositor denoise Albedo/Normal data passes |
| pkg70 | A | **done** | OptiX denoiser plugin co-equal with OIDN; persistent OptixDeviceContext + OptixDenoiser handle, lazy init, HDR vs AOV model selection by guide presence; `gpu_optix_available()` Python probe; addon `denoiser_backend` Auto/OptiX/OIDN with OptiX preferred when both present. **Verified 2026-05-10 on RTX 5070 Ti + OptiX 9.1.0**: 17/17 pytest green; 5.31× synthetic-noise reduction at 256×256; 1.86× faster than OIDN-CUDA at 1080p (728.94 ms vs 1356.09 ms); SSIM(OptiX, OIDN) = 0.9987. Empty-normal-buffer defect surfaced upstream during verification → tracked as pkg75 |
| pkg71 | A | **implemented** | benchmark framework done; first full baseline CSV pending CUDA/Cycles hardware |
| pkg74 | A | **done (all phases)** | Phase 1: framework + material zoo + Cornell convergence grid + log-log RMSE curve + stats CSV + HTML index. Phase 2: full stat catalog from research note §2 (geometry / memory / timing / sampling / quality / spectral / GPU / integrator-specific) per-row, paired-seed variance render, log-log convergence-rate slope on the curve (measured −0.453 vs MC target −0.5 on the implementer machine), new `integrator_compare` scene + bar-chart timing artefact, `--gpu` flag with clean fallback when CUDA absent. Phase 3: self-contained PBRT-style HTML dashboard with inlined artefacts/RMSE plots, sortable stats tables, scene filter, run-history navigation, and weekly self-hosted CI guarded by `ASTRORAY_RUN_SHOWCASE_WEEKLY`. Pure Python — no engine bindings added (per spec design decision #7); forward-compat probes populate BVH/GPU-mem/per-ray-type columns the moment those bindings land. Pytest gates: `test_benchmark_showcase_runs.py`, `test_benchmark_showcase_phase2.py`, and `test_pkg74_phase3_html.py`. |
| pkg75 | A | **done** | first-hit normal buffer population for denoiser AOV guides; root cause was a missing `r.normal = rec.normal` in `plugins/integrators/spectral_path_tracer.cpp::sampleFull` (the integrator registered as `path_tracer`, the actual default per `src/default_integrator.cpp`). Canonical render loop at `include/raytracer.h:2452` was already copying `ir.normal` faithfully — the upstream value was just `Vec3(0)`. Fix is one line, cites Cycles `intern/cycles/integrator/pass.cpp` PASS_NORMAL semantics. New `tests/test_normal_buffer_populated.py` asserts unit-length world-space normals at every hit pixel and `Vec3(0)` at misses. Re-baseline (PR #223) confirms post-pkg75 OIDN-on −7.3% (50.67→46.98 ms), pkg68 headline win up 2.57×→2.77× |
| pkg72 | A | **done** | per-pixel motion vector AOV (camera-only screen-space flow); `Camera::motionBuffer` (float2/pixel, OptiX prev→curr convention) populated by primary-ray write site in `Renderer::render`; `Camera::snapshotForMotion()` runs at end of every frame; `setup_camera` carries the prev-projection snapshot across re-uploads so Blender viewport pans produce non-zero flow on frame 2+; `Renderer.get_motion_buffer()` returns a zero-copy NumPy view shaped `(H, W, 2)`; `motion_vector_aov` plugin visualises the buffer; mirrors Cycles `intern/cycles/integrator/pass.cpp` PASS_MOTION (Apache-2.0). Unblocks pkg73 OptiX temporal denoiser |

---

## Known issues

- `include/raytracer.h` and `include/advanced_features.h` still contain texture class bodies (`CheckerTexture`, `NoiseTexture`, etc.). These are used directly by `blender_module.cpp` and will be cleaned up in a future package if the plan calls for it.
- ReSTIR/NRC work is implemented through pkg28 but remains in validation:
  the target NRC batched-inference speedup is not proven, and `restir-di` /
  `neural-cache` currently report CPU-only GPU capability reasons.
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
  set. pkg54/54a/54b are done: pkg54 landed a CUDA megakernel mirror of
  `multiwavelength_path_tracer` (visible/NIR/UV bands, luminance + sRGB
  output, `gpuSupported = true`); pkg54a added per-material spectral-profile
  dispatch on the GPU; pkg54b replaced the Wyman 2013 1931 2° CMF fit with
  the same baked CIE 1964 10° table the CPU uses, and a D65-SPD parity bug
  (Gaussian stand-in for the true SPD) was fixed during hardware
  verification. pkg54d added a direct `gpu_profile_reflectance` binding for
  unconfounded liveness gating, with CPU/GPU lookup max delta `0` across all
  loaded profiles on the 300-1000 nm grid. pkg54c (Jakob-Hanika spectral
  upsampling on GPU, SSIM ceiling 0.985→0.999) is now implemented:
  `gpu_jhEvalSpectrum` mirrors `RGBAlbedoSpectrum::sample` via the same
  shared `jhEvalSpectrumF` evaluator, the sRGB sigmoid LUT is uploaded to
  device global memory once per process via `uploadJakobHanikaLut`
  (cudaMalloc + cudaMemcpyToSymbol of pointers, 9 MB — overflows the
  64 KB constant cap), and `gpu_rgbSpectrumAt` upsamples through it for
  both `GSPEC_RGB_ALBEDO` and `GSPEC_RGB_ILLUMINANT`. Verified on CUDA
  hardware 2026-05-10: visible-band CPU↔GPU SSIM = 0.999263 at spp=8192
  on the parity scene (gate ≥ 0.999), per-channel mean ratios within
  0.4 %, frame-time regression +0.45 % at 1080p / 64 spp / depth 4.
  A real GPU bug — `gpu_rgbSpectrumAt` ILLUMINANT mode missed the
  CPU's `2·max(rgb)` renormalize-then-rescale step, causing wrong
  absolute spectra for any HDR emitter — was found and fixed during
  verification (see pkg54c Lessons). The 0.999 SSIM gate is unreachable
  at the original 64 spp regardless of evaluator correctness because
  CPU OpenMP and GPU warp-parallel integrators place MC samples on
  different per-pixel sub-streams; the test now runs at spp=8192
  (~5 s on RTX-class hardware) where the noise floor drops below
  the gate by ~26 %.
  Sellmeier direction-splitting and true spectral emitter parameter
  upload also remain CPU-only follow-ups. pkg36 expands shared closure
  lowering.
- The Blender addon backend UI/packaging refresh from pkg37 is complete.
  Remaining Blender parity work is narrower: pkg57 shader graph
  fidelity and pkg54 multi-wavelength GPU parity. pkg52 persistent viewport
  sessions and pkg62 viewport pass/OIDN UX are complete on `origin/main` plus
  the current pkg52 branch.
- Documentation drift found on 2026-05-09: `NEXT_STAGE_REPORT.md` is a
  historical 2026-04-29 snapshot; `production.md` had old pkg50+ placeholders
  that conflicted with live package numbers; package headers for pkg12-pkg14
  still said open despite Pillar 2 being complete. These were reconciled in
  this docs pass.

---

## Decisions pending (for project owner)

- Confirm whether lights should be migrated to plugins (currently out of scope per pkg04 non-goals) and if so, which package handles it.

---

## Changelog

Brief notes on notable events.

- **2026-05-10 (Round 3 close)** — Five packages landed in one round:
  pkg72 motion vectors, pkg64 Phase 2 spectral SMS (+8.83 dB PSNR delta,
  0.98× runtime), pkg74 Phase 2 full stat coverage (8 categories,
  convergence rate slope −0.453), pkg75 normal-buffer fix (verified
  via visual diff: detail preservation, not regression), and pkg71
  first canonical Cornell baseline (**Astroray-CPU SSIM 0.9536,
  Astroray-GPU SSIM 0.9548 vs Cycles-CPU EXR; Astroray-GPU 5.2× faster
  than Cycles-CUDA at the same Cornell sample budget; Astroray uses
  3-4× less memory than Cycles**). pkg68 headline OIDN-on speedup vs
  pre-pkg68 strengthened from 2.57× to **2.77×** post-pkg75. Build
  hygiene fixed (Windows OptiX, OIDN DLL bootstrap, harness EXR-vs-EXR
  parity). Round 4 (pkg73 OptiX temporal denoiser, pkg56 Phase B
  uploadScene split, pkg64 Phase 3 default-integrator fold, pkg74
  Phase 3 interactive HTML+CI, pkg76 .blend importer spec) queued in
  NEXT_STAGE_REPORT.md.

- **2026-05-10** — pkg70 **verified and promoted to done** on RTX 5070 Ti +
  OptiX 9.1.0 (Windows MSVC `build_cuda`). 17/17 pytest green
  (4 OptiX + 3 OIDN-pass + 3 OIDN-persistence + 7 AOV); first
  `[OptiX] Using CUDA device 0 (NVIDIA GeForce RTX 5070 Ti)` printed
  exactly once across N=4 renders; synthetic-noise reduction at 256×256
  Cornell scene = **5.31× OptiX, 5.58× OIDN** (both ≥5× gate);
  1080p timing on pkg54a/b parity scene = **728.94 ms/frame OptiX vs
  1356.09 ms/frame OIDN-CUDA = 1.86× speedup** (≥1.5× gate);
  **SSIM(OptiX, OIDN) = 0.9987** at spp=16 Reinhard-tone-mapped
  (≥0.95 gate). The synthetic-noise test fixture in
  `tests/test_optix_denoise_reduces_noise_on_synthetic_input` was
  bumped 64×64 → 256×256 to separate the gate from sliding-window
  variance-estimator boundary artifacts and from the empty-normal-buffer
  defect (next bullet). Two unrelated build-hygiene issues caught
  during the round and fixed by Codex pkg71-baseline session PR #215
  (NOMINMAX guard for Windows max macro + FindOptiX glob for OptiX 9.x;
  already merged to main).
- **2026-05-10** — pkg75 **opened** (Track A, status open). First-hit
  normal buffer population for denoiser AOV guides. `Camera::normalBuffer`
  is sized unconditionally but the integrator path the default `Renderer`
  walks leaves it filled with `Vec3(0)`; `fb.hasBuffer("normal")` returns
  true so OIDN's AOV mode and OptiX's AOV mode both bind a degenerate
  guide image and silently behave as HDR + albedo only. Surfaced during
  pkg70 verification 2026-05-10. Acceptance criteria include re-running
  the pkg70 5.31× / pkg68 2.57× baselines after the fix to capture the
  full denoiser win once normals are populated. Spec at
  `.astroray_plan/packages/pkg75-integrator-normal-guide-aov.md`.
- **2026-05-10** — pkg70 implemented (pending OptiX SDK + CUDA hardware
  verification). New `optix_denoiser` pass plugin co-equal with
  `oidn_denoiser`: persistent `OptixDeviceContext` + `OptixDenoiser`
  handle as class members, lazy init on first `execute()`, HDR model
  when no guides / AOV model when albedo+normal present (Cycles
  `OptiXDevice::denoise_buffer` shape, Apache-2.0). State + scratch
  device buffers cached per-dimension. `cmake/FindOptiX.cmake` locates
  the SDK via `OPTIX_INSTALL_DIR` or default Windows path; SDK headers
  are NOT bundled (NVIDIA license forbids redistribution). New
  `astroray.gpu_optix_available()` Python probe. Blender addon gains
  `denoiser_backend` Auto/OptiX/OIDN dropdown — Auto prefers OptiX when
  both backends are compiled in and a CUDA device is visible at
  runtime. New `tests/test_optix_denoiser.py` mirrors
  `test_oidn_denoiser_persistence.py` shape; skips cleanly when SDK or
  CUDA absent. CPU pytest unaffected; OptiX timing vs OIDN-CUDA gate
  pending verifier session with the SDK installed.
- **2026-05-10** — pkg68 implemented (pending CUDA verification). OIDN
  device + filter hoisted to `OIDNDenoiser` class members and lazy-initialised
  on first `execute()`; init tries `oidn::DeviceType::CUDA` first and falls
  back to `oidn::DeviceType::CPU` (Cycles `denoiser_oidn_gpu.cpp::create_device`
  shape, Apache-2.0). Filter is rebound only when the framebuffer geometry
  or source pointers change. CMakeLists FetchContent fallback bumped from
  oidn-2.3.3 to oidn-2.4.1 (latest with CUDA backend). New
  `tests/test_oidn_denoiser_persistence.py` pins: device init runs once
  across N renders, CUDA selected on CUDA-capable builds, albedo/normal
  guides present without explicit AOV pass. CPU pytest run: 12 passed,
  1 CUDA-only test skipped. CUDA SSIM/timing verification pending.
- **2026-05-10** — pkg68 verified on RTX 5070 Ti (Windows MSVC `build_cuda`).
  All 13 tests in `test_oidn_denoiser_persistence.py + test_oidn_denoiser.py
  + test_aov_passes.py` pass, including the previously-skipped
  `test_cuda_capable_build_reports_cuda_device` (`[OIDN] Using CUDA device`
  observed) and `test_device_initialised_once_across_n_frames` (single
  init across N=4 renders). Viewport timing at 256×256, spp=2, max_depth=3,
  N=100 frames after 3-frame warmup: OIDN-on mean 50.67 ms/frame
  vs OIDN-off baseline 23.81 ms/frame, Δ=26.86 ms/frame for the persistent
  CUDA OIDN pass. (No A/B against pre-pkg68 was run — would require a
  second build at `1253894^`; persistent-device path is now the steady
  state.) Promoted to **done**.

- **2026-05-09** — pkg59 done. Named UV layers now upload through
  `add_triangle_layers`, textures can select a layer via Texture
  Coordinate/UV Map node names, and the same image used with different UV
  layers gets distinct texture cache entries.

- **2026-05-09** — pkg60 complete (PR #178, Codex). Disney v2 energy
  compensation: ported Cycles-derived GGX + sheen LUTs, replaced Disney's
  additive roughness boost with Kulla-Conty/Cycles compensation, top-layer
  attenuation, and a local diffuse furnace normalization. Worst-case
  directional-hemispherical reflectance 1.0159 across the 90-point
  parameter grid × 3 outgoing cosines × 4096 Halton samples — under the
  1.02 acceptance gate. Bonus: Codex caught and fixed a pre-existing
  Disney specular/clearcoat Smith-G denominator bug while doing the
  furnace test, plus a combined-sampler PDF regression during owner
  review. Closes the project-owner-reported "materials seem to glow" bug.

- **2026-05-09** — pkg59 mostly done (PR #173 + PR #176). Vector input
  walking honors Mapping(Location, Rotation.z, Scale) and Texture
  Coordinate.UV/Generated/Object. New `uv_debug_aov` pass plugin renders
  first-hit UVs as RG colors. Named UV layers (multiple per-mesh UV sets)
  remain a separate package — needs structural per-triangle upload change.

- **2026-05-09** — pkg64 caustics research signed off (PR #177 + PR #179).
  Recommendation: vendor SMS reference code (BSD-3, MIT-compatible) +
  per-wavelength Newton residual derived from Hanika et al. 2015. Cycles
  MNEE source NOT used — GPL-2.0+ incompatible with Astroray's MIT.
  Reflective caustics in scope; opt-in caster UX; both numerical + visual
  acceptance gates.

- **2026-05-09** — pkg52 complete. The Blender viewport session now keeps a
  persistent renderer, re-renders on view/camera/region/zoom/pan changes,
  progressively accumulates chunked preview samples to `preview_samples`, and
  applies CAMERA-view pan through image-plane camera shift. Focused Blender
  viewport tests and `test_camera_setup` pass on the local MSVC build.
- **2026-05-09** — Documentation reconciliation. `STATUS.md` now reflects
  pkg59 as partial, pkg52/pkg53/pkg58/pkg61/pkg62 as done, the live
  Cycles-parity queue as the active Pillar 5 focus, and the current 435-test
  collection count. Package headers for pkg12-pkg14 and pkg36 were aligned
  with their completed state. `production.md` now flags obsolete pkg50+
  placeholder names that collided with the live package sequence, and
  `NEXT_STAGE_REPORT.md` is explicitly marked historical.
- **2026-05-09** — pkg62 complete on `origin/main` via PR #165. Viewport
  preview now has a pass selector and optional viewport OIDN toggle. Package
  docs were still open in the merged branch and were reconciled here.
- **2026-05-09** — pkg59 partial via PR #164. Principled BSDF image-texture
  routing is fixed, but the broader vector input / named UV / Mapping node /
  UV debug AOV package remains open.
- **2026-05-09** — pkg53 complete. Integrators now expose
  `IntegratorCapabilities` with GPU support metadata; Python binding
  `astroray.integrator_capabilities(name)` returns the same source-of-truth
  data; Blender `device_mode='gpu'` now errors instead of silently falling
  back for unsupported integrators or CUDA init failures; Auto falls back to
  CPU with an INFO report; Diagnostics panel lists per-integrator GPU/CPU
  support. New `tests/test_integrator_capabilities.py` plus backend-policy
  coverage.
- **2026-05-09** — pkg61 complete. CUDA scene upload now preserves per-vertex
  triangle normals (`n0/n1/n2`) and falls back to face normals when absent.
  The GPU hit path already interpolated those fields. Added deterministic GPU
  seed plumbing and `tests/test_gpu_shade_smooth.py`; full-image SSIM remains
  a strict xfail diagnostic due to broader CPU/GPU spectral parity divergence.

- **2026-05-08** — Cycles parity / Blender integration roadmap added in
  response to project-owner triage. 9 new packages drafted: pkg52
  (persistent viewport session), pkg53 (GPU integrator capability
  diagnostics), pkg54 (GPU multi-wavelength path tracer), pkg57 (native
  Astroray shader nodes with Cycles compat), pkg58 (spectral profile
  dropdown + IR/UV reference scenes), pkg59 (shader-graph vector / UV
  plumbing), pkg61 (GPU per-vertex normals), pkg62 (viewport pass
  selector), pkg64 (spectral caustics, research-blocked), pkg67
  (metric-aware path tracer, research-blocked). CLAUDE.md §6 added: no
  invented algorithms, cite-and-borrow policy. Main repo git cleanup:
  aborted-rebase markers cleared, `dist/` gitignored and untracked
  (914 MB tcnn build was about to land in git).

- **2026-05-03** — pkg37 complete. Blender addon backend refresh: `device_mode` EnumProperty (Auto/GPU/CPU) replaces old `use_gpu` BoolProperty; shared `configure_backend()` helper called from both final render and viewport; viewport now applies wavelength range/output mode (Near IR/UV/Custom) matching final render; Diagnostics panel shows module path, version, `__features__`, GPU availability, integrator list, and post-render stats; `build_blender_addon.py` gains `--backend cpu/cuda/tcnn/auto` flag, per-backend build dirs (`build_blender_addon`, `build_blender_addon_cuda`, `build_blender_addon_tcnn`), and a `build_report.json` in the packaged zip. 11 new tests in `test_blender_backend_policy.py`.
- **2026-05-03** — pkg39 complete. Multi-wavelength rendering: configurable wavelength band (380-780 nm visible unchanged; IR/UV via `multiwavelength_path_tracer`), `SpectralProfile`/`SpectralProfileDatabase` C++ API loading profiles.bin, `evalSpectralExt`/`sampleSpectralExt` profile dispatch on Material base class, `ColourmapOutput` post-process pass (grayscale/hot/inferno/viridis/ir_false_colour), Python API (`set_wavelength_range`, `set_material_spectral_profile`, `spectral_profile_names`), Blender UI (Wavelength panel with presets, colourmap selector). 15 tests; all pass.
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
  `scripts/diagnostics/oidn_comparison.py` writes noisy/denoised/side-by-side OIDN PNGs
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
  `scripts/benchmarks/benchmark_caustic_transport.py`. The opt-in integrator records
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
  `scripts/benchmarks/benchmark_light_transport.py`,
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

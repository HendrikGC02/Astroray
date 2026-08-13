# pkg195 — Spectral node system Phase 1: make spectral authoring real (fix dead nodes + spectrum sources + spectral lights)

**Pillar:** 2/3 (spectral rendering / Blender integration)
**Track:** A
**Status:** Stage A + B done (PR #602, 2026-08-13 — MW NIR snow-sphere mean
0.0709 > 0.05, snow/water NIR ratio 4.82, MW↔path_tracer visible parity 1.00;
sodium lamp linear RGB (0.673, 0.127, 0.000) amber, cie_f2 differs 100% on blue;
headless Blender 5.1 render confirms amber sodium vs neutral cie_f2). Stage C
(register_spectral_profile + Drawn/Preset/Blackbody spectrum nodes + in-band
Replace mode + IR/UV de-fang + Sellmeier B/C) remains OPEN — independently
landable. Filed 2026-08-12 from the owner-directed spectral-node design session;
design doc: `.astroray_plan/docs/spectral-node-system-design-2026-08.md`.
**Estimated effort:** L (three gated stages; each independently landable)
**Depends on:** nothing in flight. Touches `multiwavelength_path_tracer.cpp`
(CPU only), `blender_addon/`, `module/blender_module.cpp`,
`plugins/materials/dielectric.cpp`. Does NOT touch the wavefront GPU kernels
(REG:254 — keep it that way).

---

## Why (30 seconds)

The owner asked for working spectral nodes and spectral light sources. The
design session (2026-08-12) established with headless Blender 5.1 renders that
the existing pkg57 nodes are non-functional end-to-end:

1. **Out-of-visible-band rendering is dead.** `multiwavelength_path_tracer`
   has no light sampling — no NEE, no dedicated-light loop
   (`plugins/integrators/multiwavelength_path_tracer.cpp:135-256` reads only
   env/background and emissive materials hit by BSDF chance). Every Blender
   lamp becomes a pkg89 dedicated light (`blender_addon/__init__.py:4376-4430`),
   so any lamp-lit scene renders black in NIR/UV band mode (measured: mean
   0.00034 vs sky, all profiles, even with a 5000 K blackbody sun).
2. **Spectral Profile node is a visible-band no-op by design** — the
   `astroray_spectral_only` path creates a *white* Disney
   (`blender_addon/__init__.py:2229-2231`) and profiles are only consulted
   outside 380-780 nm (`include/raytracer.h:582-584`). Measured: swapping
   `paint_red` ↔ `grass_green` changes the render by |Δmean| = 0.00028.
3. **IR/UV Response node is destructive**: it replaces the wired base BSDF
   with a grey Disney (base colour destroyed — measured red→grey), its `band`
   enum is ignored, and its reflectance changes the *visible* render.
4. **Sellmeier manual B/C coefficients are silently dropped** — exported to
   params (`__init__.py:2204-2207`) that no engine code reads;
   `plugins/materials/dielectric.cpp:86` consumes only `sellmeier_preset`.
5. **Sodium-lamp-class SPDs already ship** (`sodium_vapor`, `mercury_vapor`,
   `cie_f2/f3`, `led_3000k/5000k/6500k` in `data/spectral_profiles/profiles.bin`)
   and `EmissionSpectrum::MeasuredSPD` exists engine-side
   (`include/astroray/emission_spectrum.h:62-64`, parser
   `module/blender_module.cpp:104-161`) — but the addon can only send
   `blackbody`/`rgb` (`_build_emission_dict`, `__init__.py:4340-4359`).

Full inventory, evidence tables, survey of other renderers, and the phased
node-family architecture: **design doc
`.astroray_plan/docs/spectral-node-system-design-2026-08.md`** (this spec is
its Phase 1). Phases 2-4 (spectrum math/filter graph, world spectra, SPD file
import, camera response, GPU spectral-light parity, Pillar-4 units) are
follow-ups recorded in the design doc §5 — do not scope-creep them in.

---

## Stage A — transport: MW integrator sees lights (prerequisite for everything) — DONE (PR #602)

Add spectral next-event estimation over dedicated lights to
`MultiwavelengthPathTracer::pathTrace`.

> **Landed 2026-08-13.** Ported the in-header `pathTraceSpectral` dedicated-light
> NEE + two-sided MIS (raytracer.h:2415-2568) into the MW integrator, using
> `evalSpectralExt`/`sampleSpectralExt`. Also fixed a latent light-sampler bug the
> spec's own Gate B exposed: a narrow-line lamp SPD (sodium) makes every light's
> single-stratum `power()` read 0 → `totalPower==0` → `selPdf=0/0=NaN` → the NEE
> leg was silently dropped; `PowerLightSampler` now falls back to uniform light
> selection for a degenerate CDF (`src/light_sampler.cpp`). Gate results: A1 mean
> 0.0709, A2 ratio 4.82, A3 per-channel parity 1.00.
>
> **NEE is gated on an `enable_nee` integrator param (default 1 = on).** The
> engine-wide contract `enableNEE = (integrator != "multiwavelength_path_tracer")`
> (module/blender_module.cpp:1814) makes this integrator the light-sampling-blind
> NAIVE oracle the GPU wavefront naive route is gated to match (pkg120/pkg156). An
> unconditional NEE changed that oracle's physics while the GPU comparator did not,
> collapsing 3 CPU↔GPU parity gates (SSIM 0.30). `enable_nee=0` is byte-identical
> to the pre-Stage-A integrator; the parity harnesses
> (`test_gpu_multiwavelength`, `test_pkg55_c3_wavefront_nonvisible`) pin it on the
> CPU MW oracle legs. **Phase-3 item now explicitly encoded by those gates: the
> GPU MW/wavefront leg has no dedicated-light sampling — GPU spectral-light NEE
> parity is deferred to pkg195 Phase 3** (design doc §5, Phase 3).

- Template: the in-header path tracer's dedicated-light NEE
  (`include/raytracer.h:2423` area, and the `astroray::Light` spectral sample
  API — `include/astroray/light.h:119,136` already returns
  `emission_spec` as `SampledSpectrum` for given `SampledWavelengths`).
- Evaluate the light's `EmissionSpectrum::eval(lambdas)` so blackbody /
  measured-SPD lamps emit correctly outside the visible band; BSDF side uses
  `evalSpectralExt` (profile-aware).
- MIS-weight against BSDF sampling in the same way the visible-band path
  tracer does; do not invent a new estimator (CLAUDE.md §6 — mirror the
  existing NEE structure; cite it in the code header).
- CPU only. The pkg54 GPU MW megakernel keeps its current behaviour;
  wavefront kernels untouched.

**Gate A:** new render-level test: sphere (profile `snow`) + dedicated
blackbody sun, band 700-1000 nm → mean pixel > 0.05 (was 0.0003); and
`snow` vs `water_clear` mean-ratio > 2. Plus visible-band regression: MW
integrator on a lamp-lit scene within per-channel mean-ratio [0.95, 1.05] of
the default path tracer (gamma OFF — linear gate, see memory
gamma-furnace-cannot-detect-energy-gain).

## Stage B — spectral lights in the addon (sodium lamps) — DONE (PR #602)

> **Landed 2026-08-13.** `light.custom_raytracer` PropertyGroup + spectrum-mode
> enum + `DATA_PT_custom_raytracer_light` panel (Astroray-engine only, with a
> per-profile λ-range label via a new `spectral_profile_range` binding).
> `_build_emission_dict` emits `{'mode':'measured_spd','profile_name':<name>}`
> (the parser's actual key — the spec's `'profile'` was shorthand), wrapped in a
> `composite` when the lamp colour is a non-white gel. Headless Blender 5.1 CPU
> render: sodium amber (display RGB 0.291/0.278/0.0003, R>G>3B) vs neutral cie_f2
> (0.289/0.287/0.285). Engine-level linear gate: sodium (0.673, 0.127, 0.000).

1. `light.custom_raytracer.spectrum_mode` enum: `native` (default; exactly
   today's blackbody/rgb behaviour) · `preset` (dropdown over emission-category
   profiles from the DB) · `custom_profile` (any profile by name — enables
   drawn spectra from Stage C).
2. `_build_emission_dict` emits `{'mode':'measured_spd','profile':<name>}`
   for preset/custom modes; colour stays as gel tint via `composite` mode
   (`blender_module.cpp:139-158` already parses it).
3. Light data panel UI (Astroray engine only) with the mode enum + preset
   dropdown; label shows the profile's λ range.
4. GPU note: dedicated lights on GPU use `deviceReference()` RGB
   approximation for non-RGB modes (documented, `emission_spectrum.h:100-108`).
   Acceptable for this package; Stage B renders its gates on CPU.

**Gate B:** headless Blender render: point lamp in `preset/sodium_vapor` mode
over a white sphere, visible band, CPU → hue must land amber
(R > G > 3·B in linear mean); switching to `cie_f2` changes per-channel
ratios by > 10%. Test lives with the pkg119b-style harness
(`ASTRORAY_PYD_DIR` + absolute out-dir conventions).

## Stage C — spectrum sources + honest material nodes — OPEN (descoped from the A+B PR)

> Not started. Independently landable; nothing in A+B blocks it. Note for the
> implementer: A+B already added `SpectralProfile::lambdaMin/lambdaStep/count`
> getters and the `spectral_profile_range` binding, and the light panel's
> `custom_profile` mode is wired to `_spectral_profile_items` — so a
> `register_spectral_profile` insert method (item 1) immediately feeds the Stage-B
> custom-profile dropdown.

1. **`astroray.register_spectral_profile(name, lambda_min_nm, lambda_step_nm,
   values: list[float])`** pybind binding inserting into
   `SpectralProfileDatabase` (`include/astroray/spectral_profile.h:51-58` —
   storage is vectors + name index; add an insert method). Runtime profiles
   participate in everything existing: material attach, emission MeasuredSPD,
   GPU profile-table upload (`src/gpu/scene_upload.cu:926-959`).
2. **Drawn Spectrum node** (`AstrorayShaderNodeDrawnSpectrum`): Blender
   `CurveMapping` widget (`layout.template_curve_mapping` on a hidden
   `ShaderNodeFloatCurve` helper in a private node group — the .blend stores
   the curve; see design doc §3.4), configurable [λmin, λmax] (default
   300-1000 nm), semantic enum (reflectance / emission). On export: evaluate
   at 5 nm steps → `register_spectral_profile` under a
   `__blend__/<mat-or-light>/<node>` name.
3. **Spectrum Preset node** (`AstrorayShaderNodeSpectrumPreset`): dropdown
   filtered by category (reflectance 0-6 / emission 7); replaces the bare
   Spectral Profile node as the source in new trees (keep the old node
   registered for .blend compat; its translation now routes through the same
   path).
4. **Blackbody Spectrum node**: temperature K + normalize toggle → emission
   use only in Phase 1 (feeds light `custom_profile` mode by baking Planck at
   5 nm steps; `src/emission_spectrum.cpp` blackbody normalization pkg122 is
   the reference for the normalize semantics).
5. **In-band native reflectance**: material profile hook grows a mode —
   `setSpectralProfile(profile, ProfileMode::ExtendOnly | Replace)`.
   `Replace`: `evalSpectralExt`/`sampleSpectralExt` use
   `profile->reflectance(λ)·cosθ/π` for ALL λ (bypassing the Jakob-Hanika
   upsample — an authored SPD must never round-trip through RGB; design doc
   §3.1 principle 2). The Spectral Profile / Spectrum Preset / Drawn Spectrum
   nodes wired to a Surface set `Replace`; the pkg58 material-panel fallback
   dropdown keeps `ExtendOnly` (no behaviour change for old scenes).
   GPU: `Replace`-mode materials fall back to CPU-identical behaviour only in
   the MW CPU path this package touches; the GMaterial path is untouched —
   `Replace` + GPU renders emit a one-line degradation warning via the pkg119
   DegradationReport.
6. **IR/UV Response de-fang**: translation becomes non-destructive — base
   BSDF converts normally (passthrough like NRC hint), and the node only
   attaches a constant-band profile (`ExtendOnly`) built from
   band+reflectance via `register_spectral_profile`. The grey-Disney
   promotion (`__init__.py:2210-2221`) is deleted. Visible render with the
   node present must be pixel-identical to without it.
7. **Sellmeier B/C plumbing**: `plugins/materials/dielectric.cpp` reads
   `sellmeier_b`/`sellmeier_c` float3 params when `sellmeier_preset` is
   absent; addon already sends them (`__init__.py:2204-2207`).

**Gate C:**
- `register_spectral_profile` roundtrip unit test (register → names() →
  reflectance interpolation vs numpy reference).
- Render gate: Spectrum Preset `paint_red` vs `grass_green` in Replace mode,
  visible CPU render → per-channel means differ (R-dominant vs G-dominant);
  the exact anti-regression for today's |Δ| = 0.00028 no-op.
- IR/UV non-destructiveness: red Principled with vs without the node, visible
  band → SSIM = 1.0 / byte-identical.
- Sellmeier: manual BK7 B/C (preset off) vs `bk7` preset → prism dispersion
  renders within per-channel mean-ratio 2% (reuse
  `benchmarks/reference_bank/scenes/prism-bk7-collimated`).
- Drawn Spectrum: headless test drives the CurveMapping points
  programmatically (narrow 550 nm bump vs flat) → green-dominant vs neutral
  render.

---

## Verification (package-wide)

- Full local suite + the new render-level tests; build via
  `build_cuda_worktree.bat` (root copy) and confirm `.pyd` mtime before any
  claim (memory: implementer-ships-without-building).
- Addon staging: any new `blender_addon/*.py` module or `nodes/` file must be
  covered by `build_blender_addon.py` staging (ADDON_FILES / nodes copytree —
  `scripts/build/build_blender_addon.py:74-79,832-837`); verify staged-dir
  register in headless Blender 5.1 (memory: addon-packaging-file-list).
- Call-site sweep for every changed signature (`setSpectralProfile` gains a
  parameter — sweep `module/`, `src/gpu/scene_upload.cu`, tests).
- HW closeout: this is CPU-scoped, but run the standard RTX sweep before
  merge to prove no GPU regression (CI has no GPU — memory:
  ci_has_no_gpu_runtime_blindspot).
- Cite in code: NEE structure ports the in-header path tracer's
  dedicated-light loop (repo-internal citation); tabulated-SPD interpolation
  cites PBRT-v4 `PiecewiseLinearSpectrum` (Apache-2.0) per the design doc §4.

## Out of scope (recorded in design doc §5, file follow-ups at close)

- Spectrum Math / Filter / Gaussian nodes, gel filters on lights (Phase 2)
- SPD file import, world/environment spectra (Phase 2)
- Camera/sensor response curves, false-colour pipelines (Phase 3)
- GPU spectral-light parity, MW/wavefront GPU NEE, GMaterial Replace mode (Phase 3)
- Pillar-4 physical units audit, GR emission-model surfacing, log-λ wide-band
  tables (Phase 4)

## Hardware verification 2026-08-13

Independent HW verification of PR #602 (Stage A + B), RTX 5070 Ti, Windows 11
Enterprise 10.0.26200, NVIDIA driver 610.47, CUDA 12.8 (nvcc V12.8.61), sm_120.

**Round 1 — commit `9018368` (initial Stage A+B): FAIL on Gate 3.**
- Gate 1 (clean rebuild): PASS — `.pyd` embeds sm_120, ABI canary green,
  HEAD SHA verified.
- Gate 2 (`test_pkg195_stage_a_mw_nee.py` + `test_pkg195_stage_b_spectral_lamp.py`,
  6 tests): PASS, numbers matched claims exactly (A1 mean 0.0709, A2 ratio 4.82,
  A3 ratio [1,1,1]; B1 sodium (0.6730, 0.1265, 0.0000); B2 max Δ 1.00; B3 gel
  ~7.0× red suppression).
- **Gate 3 (deferred GPU parity suites — `test_pkg55_c3_wavefront_nonvisible.py` +
  `test_gpu_multiwavelength.py`, 10 tests): FAIL, 3/10.**
  `test_naive_mode_wavefront_cpu_parity` SSIM 0.3001 (gate ≥0.97);
  `test_visible_band_cpu_gpu_ssim` SSIM 0.3061 (gate ≥0.995);
  `test_visible_band_no_regression` GPU/CPU mean drift 79.27% (gate <2%).
  Root cause (confirmed by reading the diff, not the failure alone): Stage A
  gave `MultiwavelengthPathTracer` unconditional dedicated-light + emissive-hit
  NEE. Both suites use this exact integrator as their light-sampling-blind
  "naive" CPU oracle for the GPU wavefront/megakernel comparison
  (`test_pkg55_c3_wavefront_nonvisible.py:119` literally selects it for
  `enable_nee=False`). The oracle's physics changed while the GPU comparator
  did not, so the CPU leg went bright (real NEE on the scene's ceiling-light
  quad) while the GPU leg stayed dim — a structural collision, not noise.
  Gates 4-6 (light_sampler.cpp scrutiny, visual PNG inspection, headless-Blender
  addon smoke) all PASSED independently of this failure. Reported FAIL,
  did not merge, did not attempt a fix (escalated for an architect decision).

**Fix — commit `c07671e`, spec update `90ee32e`.** Implementer added an
`enable_nee` integrator param (default on) gating all three NEE/MIS legs in
`MultiwavelengthPathTracer::pathTrace` (dedicated-light visibility w_B,
emissive-hit w_B — the exact pkg120/pkg156 bug class — and the NEE sample
leg), and pinned `enable_nee=0` on the CPU oracle legs in both parity test
files via `set_integrator_param`. No gate threshold was edited in either test
file (diff-verified: only `set_integrator_param("enable_nee", 0)` calls added).

**Round 2 — commit `90ee32e` (confirmation pass): PASS, all gates green.**
- HEAD SHA `90ee32e80d816b9935c415db1528c1c853489e6f` confirmed = PR #602
  `headRefOid` at time of this check.
- Gate 1 (clean rebuild): PASS — sm_120 embedded, pkg183 stamp
  `sha=90ee32e80d81`, ABI canary unchanged/green.
- Gate 2 (6 pkg195 tests): PASS, identical numbers to Round 1 (unaffected by
  the fix — these use `enable_nee` default-on).
- **Gate 3 (10 deferred GPU parity tests): PASS, 10/10, recovered.** Measured
  independently (not just re-running the assertions — recomputed the exact
  SSIM/drift values the tests check):
  - `test_naive_mode_wavefront_cpu_parity`: SSIM = 0.99158 (gate ≥0.97;
    implementer reported 0.9816 — both comfortably clear the gate; the ~0.01
    spread across independent runs is consistent with GPU-warp/OpenMP MC
    sample-stream non-determinism documented elsewhere in this suite, not a
    correctness concern).
  - `test_visible_band_cpu_gpu_ssim`: SSIM = 0.995426 (gate ≥0.995; implementer
    reported 0.9954 — matches to 4 decimal places).
  - `test_visible_band_no_regression`: CPU mean 0.027330, GPU mean 0.027687,
    drift = 1.3054% (gate <2%; implementer reported 1.31% — matches).
  - Remaining 7 of the 10 (NIR/UV band agreement-on-black, visible-band
    default-unchanged, NIR/UV CPU-GPU SSIM with profiles, no-profile fallback,
    GPU MW kernel finiteness): all PASS, unchanged from Round 1 (these were
    never affected — they don't use the naive-oracle integrator in the broken
    configuration).
- 16/16 total tests green (`test_pkg55_c3_wavefront_nonvisible.py` +
  `test_gpu_multiwavelength.py` + both pkg195 Stage A/B files).
- `enable_nee` diff re-read line-by-line: gating mirrors the in-header
  template's condition exactly, including the emission two-sided-MIS w_B leg
  (the pkg156 bug class — this is the leg that would silently re-break GPU
  naive-mode parity if left unconditional). Parity-test edits pin the oracle
  without touching any assertion threshold (diff-verified).
- Gates 4-6 unaffected by the fix commit (`light_sampler.cpp`,
  `blender_addon/__init__.py`, `module/blender_module.cpp` are untouched
  between `9018368` and `90ee32e`) — Round 1's PASS results for those stand.

**Visual inspection (unchanged from Round 1, re-confirmed applicable):**
`test_results/pkg195_gateA_nir_snow.png` (smooth-lit greyscale sphere, visible
terminator, no fireflies/banding/NaN pixels), `test_results/pkg195_gateB_sodium.png`
(bright amber sphere, R≫B, clean), `test_results/pkg195_gateB_cie_f2.png`
(neutral white/grey sphere, clean) — no anomalies in either round.

**Verdict: mergeable on HW evidence.** All 6 verification-workflow gates green
on the current PR head (`90ee32e`); the Round-1→fix→Round-2 arc is preserved
here as the record of a real regression the deferred-suite gate was specifically
designed to catch, and of a fix that did not relax any threshold.

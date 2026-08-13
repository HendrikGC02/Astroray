# pkg195 — Spectral node system Phase 1: make spectral authoring real (fix dead nodes + spectrum sources + spectral lights)

**Pillar:** 2/3 (spectral rendering / Blender integration)
**Track:** A
**Status:** Stage A + B done (PR #602, 2026-08-13 — MW NIR snow-sphere mean
0.0709 > 0.05, snow/water NIR ratio 4.82, MW↔path_tracer visible parity 1.00;
sodium lamp linear RGB (0.673, 0.127, 0.000) amber, cie_f2 differs 100% on blue;
headless Blender 5.1 render confirms amber sodium vs neutral cie_f2). Stage C
done (PR #610, 2026-08-14 — register_spectral_profile + Drawn/Preset/Blackbody
spectrum nodes + in-band Replace mode + IR/UV de-fang + Sellmeier B/C; Gate C all
green, headless Blender drawn 550 nm bump G=0.4396>R=0.2642>B=0.0003, manual BK7
B/C == bk7 preset 0.00%, 16/16 A/B+parity gates unchanged). All three stages
landed. Filed 2026-08-12 from the owner-directed spectral-node design session;
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

## Stage C — spectrum sources + honest material nodes — DONE (PR #610, 2026-08-14)

> **Landed 2026-08-14.** All 7 items shipped. `register_spectral_profile(name,
> lmin, step, values)` binding inserts into `SpectralProfileDatabase` via
> pointer-stable deque storage (materials cache `SpectralProfile*` across a
> render; a push_back must not dangle them). `ProfileMode::{ExtendOnly,Replace}`
> added to `setSpectralProfile`; Replace drives all λ via
> `profile->reflectance(λ)·cosθ/π`, bypassing the JH RGB round trip
> (`raytracer.h` evalSpectralExt/sampleSpectralExt). Three source nodes
> (Drawn Spectrum with a native CurveMapping, Spectrum Preset two-tier, Blackbody
> Spectrum) + a Bake-to-Profile operator. IR/UV Response de-fanged: base BSDF
> converts normally, node only attaches a constant-band ExtendOnly profile
> (visible render byte-identical). Sellmeier manual B/C now read in
> `dielectric.cpp` (matched the bk7 preset within 0.00%). A visible-band CPU
> render with a Replace-mode material is routed to the MW integrator (the only
> transport that consults evalSpectralExt in-band; the pkg57 no-op fix); GPU keeps
> its integrator + a degradation note (Replace is CPU-exact, enableNEE contract
> untouched). Gate results below.
>
> **Gate C (all green, CPU, sm_120 build):**
> - C1 register_spectral_profile roundtrip + interpolation exact vs numpy;
>   overwrite-in-place (no duplicate name).
> - C2 paint_red vs grass_green Replace mode: paint_red R=0.0152≫G=0.0012 (R-dom),
>   grass_green G=0.0050>R=0.0049 (G-dom), G/R signatures 3×+ apart — was the
>   |Δmean|=0.00028 no-op.
> - C3 IR/UV ExtendOnly band profile: visible render BYTE-IDENTICAL to base.
> - C4 manual BK7 B/C vs bk7 preset prism dispersion: 6.350px vs 6.350px (0.00%).
> - C5 drawn-equivalent 550 nm bump green-dominant; flat SPD neutral.
> - Headless Blender 5.1 drawn-spectrum end-to-end (CPU, OpenMP-off build):
>   550 nm bump curve → G=0.4396>R=0.2642>B=0.0003 (clean green sphere PNG),
>   flat curve neutral (span 0.009); MW-routing degradation note confirmed fired.
> - Stage A/B (6) + 10 GPU-parity gates: 16/16 unchanged (enable_nee contract
>   intact).

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

## Hardware verification 2026-08-14

Independent HW verification of PR #610 (Stage C -- drawn-spectrum node, runtime
profile registration, preset/blackbody nodes, ProfileMode::Replace, Sellmeier
manual fix), branch pkg195c, worktree
C:/Users/hgcom/OneDrive/Astroray/Astroray_repo/Astroray-pkg195c. RTX 5070 Ti,
Windows 11 Enterprise 10.0.26200, NVIDIA driver 610.47, CUDA 12.8 (nvcc
V12.8.61), sm_120. Verified at commit 9f32c288fbbf25e046b0651adf0bcf03dbf2f869
(the post-review hardening commit -- registration-time reflectance clamp).

**Staleness check:** .pyd LastWriteTime (build_cuda/Release/astroray.cp313-win_amd64.pyd)
was 2026/08/14 02:40:22, 47s older than the 9f32c28 commit timestamp
(02:41:09) -- the CLAUDE.md protocol trigger fired. First rebuild attempt via
cmd /c build_cuda_worktree.bat from Bash was the documented false-green
failure mode (gitbash-cmd-c-pathconv-false-green): banner-only output, exit 0,
.pyd mtime unchanged. Rebuilt via PowerShell directly -- full build succeeded,
arch-verify OK: astroray.cp313-win_amd64.pyd embeds sm_120, ABI canary green,
build stamp sha=9f32c288fbbf. The .pyd on-disk write timestamp did not advance
a second time either (LastWriteTime unchanged, LastAccessTime updated) -- the
linker produced a byte-identical relink and skipped the write; consistent
with a host-only relink (implementer built-then-committed within the same
minute), not staleness, corroborated by the build-stamp SHA match and by
every test result below matching the implementer-claimed numbers exactly.

Python smoke-check: astroray.__file__ resolves to the canonical
build_cuda/Release/astroray.cp313-win_amd64.pyd (not a shadow copy);
hasattr(astroray, register_spectral_profile) -> True.

### Gate results (measured verbatim, pytest tests/ -v -s --tb=short)

All 29 collected tests passed in a single run (test_results/verifier_run_pr610.txt):

| Suite | Tests | Result |
|---|---|---|
| test_pkg195_stage_c.py | 8 (C1, C1b, C1c, C1d, C2, C5, C3, C4) | 8/8 PASS |
| test_pkg195_stage_c_routing.py | 5 | 5/5 PASS |
| test_pkg195_stage_a_mw_nee.py | 3 (A1, A2, A3) | 3/3 PASS |
| test_pkg195_stage_b_spectral_lamp.py | 3 (B1, B2, B3) | 3/3 PASS |
| test_pkg55_c3_wavefront_nonvisible.py | 4 | 4/4 PASS |
| test_gpu_multiwavelength.py | 6 | 6/6 PASS |
| Total | 29 | 29/29 PASS |

Selected verbatim console output:
- [C1c PASS] register clamps reflectance samples to [0,1]
- [C1d PASS] Replace energy bounded by clamp
  unit=[0.0540355  0.05403457 0.05279671]
  over=[0.0540355  0.05403457 0.05279671]
  a [5.0]*n profile (5x over-unity) renders np.allclose(atol=1e-5) to a
  [1.0]*n profile: the registration-time clamp holds, no energy gain from an
  authored >1 curve.
- [C2 PASS] Replace-mode preset drives visible hue
  paint_red G/R=0.079 vs grass_green G/R=1.025, R-delta=0.01034
- [C5 PASS] drawn-equivalent 550 nm bump is green; flat SPD is neutral
  550nm-bump linear RGB = [1.0724303e-02 3.1662770e-02 1.4524326e-06]
  flat SPD linear RGB = [0.03242185 0.03242096 0.03167837]
- [C3 PASS] IR/UV ExtendOnly band profile is visible-band byte-identical
- [C4 PASS] manual Sellmeier B/C matches bk7 preset within 0.00%
  bk7 preset red/blue separation = 6.350px, manual B/C = 6.350px
- [A1 PASS] mean 0.0709, [A2 PASS] ratio 4.82, [A3 PASS] ratio [1,1,1]
- [B1 PASS] sodium (0.6730, 0.1265, 0.0000), [B2 PASS] max delta 1.00, [B3 PASS] gel attenuation
- 10/10 GPU parity tests PASS (test_pkg55_c3_wavefront_nonvisible.py + test_gpu_multiwavelength.py)

### GPU parity -- independently recomputed (not just re-running assertions)

Wrote a standalone script importing the same _render_pair / _render_wavefront_vs_cpu
helpers used by the test modules and printed the raw numbers feeding each assert:

test_visible_band_cpu_gpu_ssim: SSIM=0.995426 (gate>=0.995)
test_visible_band_no_regression: CPU mean=0.027330 GPU mean=0.027687 drift=1.3054% (gate<2%)
test_naive_mode_wavefront_cpu_parity: SSIM=0.991580 CPU mean=0.027287 WF mean=0.027670 (gate>=0.97)

These match the PR #602 Round-2 hardware-verification numbers in this spec
2026-08-13 section exactly -- expected, since Stage C does not touch the MW
integrator naive-oracle NEE contract or the GPU wavefront kernels (spec own
Depends-on line: does not touch the wavefront GPU kernels). No GPU regression
from Stage C.

### End-to-end drawn-spectrum check -- no committed harness existed; reconstructed independently

Searched the worktree and full git history for a pkg195 Stage-C headless-Blender
script; none was ever committed. The PR body Drawn-Spectrum-headless-Blender-5.1
end-to-end claim (G=0.4396 > R=0.2642 > B=0.0003) was evidently produced by a
one-off, uncommitted script and its output PNGs
(test_results/pkg195c_drawn_550bump.png, _drawn_flat.png, mtime 02:17,
predating this verification rebuild) are the only surviving artifact --
visually inspected below, consistent with the claim, but the underlying
numeric claim is NOT independently re-run-verified from source.

To close that gap, built a fresh CPU-only, OpenMP-off Blender addon
(python scripts/build/build_blender_addon.py --backend cpu, confirmed
ASTRORAY_DISABLE_OPENMP=ON in the CMake cache, per the pkg119b runbook and
memory mingw_openmp_blender_deadlock), installed it into Blender 5.1
(the extensions/user_default/astroray directory), and wrote a temporary
harness (scripts/dev/verify_pkg195c_drawn_spectrum.py, deleted after use per
CLAUDE.md 5b -- one-off/single-verification) that builds a real Blender node
graph: AstrorayShaderNodeDrawnSpectrum -> AstrorayOutputNode -> Surface, with
the node hidden ShaderNodeFloatCurve CurveMapping programmatically driven
(narrow spike at x=(550-300)/700 for the bump; flat y=0.6 for the neutral
case), a white sphere, black world background, a white point light,
scene.custom_raytracer.device_mode=cpu, engine CUSTOM_RAYTRACER. Ran headless
via blender --background --factory-startup --python.

Console output confirmed the auto-routing this stage adds actually fired:
Astroray degradation: 1 approximated / 0 ignored -- approximated Spectral
Replace material: routed to multiwavelength integrator for per-lambda
reflectance (the _route_replace_to_mw path, blender_addon/__init__.py:1230).

Measured (mean of saved PNG pixels, different scene/light/spike-width than
the implementer uncommitted harness so magnitudes are not expected to match,
but the qualitative signature is the gate):

ADDON-DRAWN 550nm bump: mean RGB = (0.1574, 0.2512, 0.0249)  G>R>>B  (G/B=10.1x, G/R=1.60x)
ADDON-DRAWN flat:       mean RGB = (0.3476, 0.3478, 0.3464)  neutral (span 0.4%)

G > R >> B confirmed independently, and flat confirmed neutral -- both hold
up under an independently-authored scene, not just the implementer own
harness output. Addon files (blender_addon/nodes/__init__.py,
AstrorayShaderNodeDrawnSpectrum, _route_replace_to_mw) are covered by
ADDON_FILES/staging (verified implicitly: the addon registered and rendered
without missing-module errors after staging).

BK7 prism manual-vs-preset: reproduced via the test_c4 pytest run above
(6.350px vs 6.350px, 0.00%); no separate Blender-level harness exists or was
needed per spec Gate C wording (only the Drawn Spectrum gate specifically
calls out the headless-Blender check).

### Visual inspection

- test_results/pkg195c_addon_drawn_550bump.png (own render): clean green
  low-poly sphere, no fireflies, no banding, no NaN pixels.
- test_results/pkg195c_addon_drawn_flat.png (own render): clean neutral
  grey/white sphere, no anomalies.
- test_results/pkg195c_prism_bk7_manual.png and _preset.png (regenerated by
  this run pytest, C4): visually indistinguishable red/blue dispersion
  fringes either side of a dark prism silhouette -- matches the 0.00%
  numeric claim, no artifacts.
- test_results/pkg195c_drawn_550bump.png and _drawn_flat.png (implementer
  surviving PNGs, not regenerated by this run -- see harness-provenance note
  above): green sphere and neutral sphere, consistent with the claim, no
  visible anomalies. Flagged as unverified-from-source but visually
  unremarkable.

No fireflies, banding, NaN pixels (magenta/black), or mode regressions
observed in any of the above.

### Energy check

C1d (above) is the energy-bound gate: a 5x-over-unity registered curve renders
np.allclose(atol=1e-5) to a unit curve -- the registration-time [0,1] clamp
(this PR hardening commit 9f32c28) holds under Replace-mode rendering,
confirmed both via the pytest run and by inspecting the printed per-channel
means (identical to 5 decimal places). No energy gain observed in any linear
(non-gamma) render in this verification pass.

### Verdict: HW PASS

29/29 CPU gate tests pass with numbers matching the PR claims verbatim (C1c
and C1d clamp hardening included). 10/10 GPU parity tests pass, independently
recomputed and matching the PR #602 baseline to 6 significant figures -- no
GPU regression, consistent with Stage C stated scope (does not touch the
wavefront GPU kernels). The Drawn Spectrum end-to-end claim original harness
was never committed to the repo (a process gap, not a code defect -- the PNG
evidence survived, the harness did not); reconstructed an independent
Blender-node-graph harness from scratch and confirmed the same qualitative
signature (G > R >> B for the 550 nm bump, neutral for flat) plus live
confirmation that the new _route_replace_to_mw degradation-report path
fires. No visual anomalies in any inspected render.

Process note for the coordinator: future Stage-C-class PRs that claim a
headless-Blender end-to-end check should commit the harness script (even as
a one-off under scripts/dev/) alongside the PR, or at minimum note in the PR
body that it was ad hoc and will not survive for re-verification -- this
verification had to reconstruct the check from the addon source rather than
simply re-running it.

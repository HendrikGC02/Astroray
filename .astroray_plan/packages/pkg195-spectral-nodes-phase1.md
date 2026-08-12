# pkg195 — Spectral node system Phase 1: make spectral authoring real (fix dead nodes + spectrum sources + spectral lights)

**Pillar:** 2/3 (spectral rendering / Blender integration)
**Track:** A
**Status:** open (filed 2026-08-12 from the owner-directed spectral-node design
session; design doc: `.astroray_plan/docs/spectral-node-system-design-2026-08.md`)
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

## Stage A — transport: MW integrator sees lights (prerequisite for everything)

Add spectral next-event estimation over dedicated lights to
`MultiwavelengthPathTracer::pathTrace`.

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

## Stage B — spectral lights in the addon (sodium lamps)

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

## Stage C — spectrum sources + honest material nodes

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

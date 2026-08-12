# Astroray Spectral Node System — Design (2026-08)

**Status:** design accepted for phased implementation (Phase 1 spec:
`.astroray_plan/packages/pkg195-spectral-nodes-phase1.md`)
**Author:** Fable design session, 2026-08-12 (owner directive: expand Astroray
shader nodes; make the existing ones actually work; spectral light sources
incl. sodium lamps; drawable spectral filters; leverage what only a spectral
renderer can do; be forward-thinking for Pillar 4)
**Scope:** Blender addon node family + light/world spectral settings + the
engine plumbing they need. Research + design only; implementation is phased
(Phase 1 spec above).

---

## 1. Current truth (verified inventory, 2026-08-12)

Every claim below was verified against current `main` (commit 7b9cc1b) and,
where marked **[HW]**, by headless Blender 5.1.0 CPU renders using the
installed extension (build `86dd549+20260810T141401Z`; the staged addon's
`__init__.py` matches the repo copy, mtime 2026-08-12).

### 1.1 What exists

| Piece | Where | State |
|---|---|---|
| 5 custom nodes (Output, Spectral Profile, Sellmeier Glass, IR/UV Response, NRC Hint) | `blender_addon/nodes/__init__.py` (pkg57) | Registered and creatable in 5.1 **[HW]** |
| Node → engine translation | `blender_addon/__init__.py:2076-2234` (`convert_astroray_output` + `_create_astroray_material`) | Dispatches on `bl_idname`; see per-node status below |
| Spectral profile DB | `data/spectral_profiles/profiles.bin` — ASPR v1, **47 profiles**, 441 samples, 300-2500 nm @ 5 nm (`scripts/data/spectral_profile_format.md`) | Loads fine; `astroray.spectral_profile_names()` returns 47 in Blender **[HW]** |
| Emission SPDs already in the DB | `cie_f2`, `cie_f3`, `led_3000k/5000k/6500k`, `sodium_vapor`, `mercury_vapor` (category 7) | Present; **unreachable from any UI** |
| `EmissionSpectrum` (Blackbody / RGB / MeasuredSPD / Composite) | `include/astroray/emission_spectrum.h` (pkg89), parsed from Python dicts in `module/blender_module.cpp:104-161` | Blackbody + RGB reachable from Blender; MeasuredSPD/Composite **never sent by the addon** (`_build_emission_dict`, `blender_addon/__init__.py:4340-4359`) |
| Spectral core | `include/astroray/spectrum.h` — 4 hero-λ `SampledSpectrum`/`SampledWavelengths`, Jakob-Hanika sRGB upsampling; `SampledWavelengths::redshift(g)` (pkg67) and `fromLambdas` (pkg43/44) already exist | Solid foundation; Pillar-4 hooks already present |
| Material profile hook | `include/raytracer.h:554-616` `setSpectralProfile` / `evalSpectralExt` / `sampleSpectralExt` | Profile consulted **only outside 380-780 nm** |
| GPU profile table | `src/gpu/scene_upload.cu:926-959` resamples attached profiles onto a fixed grid for the MW kernel | Exists |
| Band presets + colourmaps | `blender_addon/__init__.py:298-324` (visible / near-IR / UV / custom + grayscale/hot/inferno/viridis/IR-false-colour) | UI works; renders are black (below) |

### 1.2 Functional status per node (measured)

Headless harness: 48x48 CPU renders, sphere + pkg89 dedicated sun,
`device_mode='cpu'`, 8 spp (session scratchpad `node_functional_test*.py`;
means are image-average RGB).

**Astroray Spectral Profile — NOT FUNCTIONAL (two independent causes).**
1. *Visible band:* swapping `paint_red` → `grass_green` changes nothing
   (mean 0.3640/0.3640/0.3615 vs 0.3639/0.3639/0.3613; |Δ| = 0.00028 ≈ noise).
   By construction: `astroray_spectral_only` creates a **white** Disney
   (`__init__.py:2229-2231`) and the profile's 300-2500 nm data — which fully
   covers the visible band — is never used in-band (`evalSpectralExt`,
   `raytracer.h:582-584`, substitutes the profile only for λ outside 380-780).
   The default `path_tracer` never calls `evalSpectralExt` at all.
2. *Near-IR / UV bands:* renders are black (mean 0.00034, = residual Rayleigh
   sky) for **any** profile, even `snow` (NIR reflectance ≈ 1), and even with a
   blackbody sun (`use_temperature=True`, 5000 K) **[HW]**. Root cause: the
   `multiwavelength_path_tracer` (`plugins/integrators/multiwavelength_path_tracer.cpp`)
   has **no light sampling of any kind** — no NEE, no dedicated-light loop; it
   only picks up radiance from the environment or from emissive *materials* hit
   by BSDF chance. It predates pkg89; pkg89 dedicated lights (Point / Distant /
   Area / Spot — what every Blender lamp becomes, `__init__.py:4376-4430`) are
   invisible to it. Any Blender scene lit by lamps renders black outside the
   visible band, so the entire IR/UV feature set is dead end-to-end.

**Astroray IR/UV Response — WORSE THAN NON-FUNCTIONAL (destructive).**
Translation (`_astroray_ir_uv_spec` + `_create_astroray_material`,
`__init__.py:2150-2168, 2210-2221`) discards the wired base BSDF entirely and
replaces the material with a grey Disney at `base_color = reflectance`:
- Visible render with a red Principled wired through it comes out **grey**
  (r-g mean gap 0.0001 at reflectance 0.9) — base colour destroyed **[HW]**.
- The `band` enum (`ir` / `uv` / `both`) is read into the spec dict and then
  **ignored** — no engine parameter consumes it.
- `reflectance` illegitimately changes the *visible* render (mean 0.357 vs
  0.228 for 0.9 vs 0.1) — an "out-of-band response" control must not.
- In its nominal band (near-IR) it has zero effect (black renders, cause 2
  above).

**Astroray Sellmeier Glass — PARTIALLY FUNCTIONAL.**
Preset path is real: `sellmeier_preset` reaches
`plugins/materials/dielectric.cpp:86`. Manual `Sellmeier B` / `C` coefficient
sockets are exported into params (`__init__.py:2204-2207`) that **no engine
code reads** (grep: `sellmeier_b` appears only in the addon) — the "manual
coefficients" UI is a silent no-op, acknowledged as a forward-compat carry in
the code comment.

**Astroray Output / NRC Hint — functional** for their narrow purposes
(dispatch marker; passthrough + `mat.astroray.nrc_cache_hint` annotation).

### 1.3 Light/world spectral status

- Blender lamp → `EmissionSpectrum` dict: `blackbody` mode when the native
  `light.use_temperature` toggle is on (temperature + colour-as-gel-tint),
  else `rgb` (Jakob-Hanika illuminant upsample). Nothing else reachable.
- Blackbody photopic normalization fixed in pkg122
  (`src/emission_spectrum.cpp:16-28,153-167`).
- The engine can already do sodium lamps **today** via
  `EmissionSpectrum::MeasuredSPD{"sodium_vapor"}` + the shipped NIST-derived
  SPD — the gap is purely addon UI + translation.
- GPU: dedicated lights use `EmissionSpectrum::deviceReference()` — an RGB
  approximation for non-RGB modes (documented gap,
  `emission_spectrum.h:100-108`).
- World: env map has `evalSpectral`; background colour goes through
  `RGBIlluminantSpectrum`. No spectral authoring for worlds.

### 1.4 Why the owner sees "nodes that don't work" — summary

1. Out-of-visible-band transport is dead (MW integrator can't see lights).
2. In the visible band, spectral profiles are defined to be no-ops.
3. The IR/UV node destroys the material it wraps.
4. Sellmeier manual coefficients are silently dropped.
5. The genuinely working spectral machinery (lamp SPDs, blackbody, profile DB)
   is either unreachable from the UI or has no observable effect.
6. Test coverage is registration-level only
   (`tests/test_blender_native_nodes.py`) — no render-level assertions, so all
   of the above merged green (cf. memory: PR-named tests insufficient).

---

## 2. Survey — how other spectral renderers expose spectral authoring

Condensed from the session's web survey (sub-agent, 2026-08-12); URLs are the
primary citations. Access notes: the LuxCore wiki, Blender manual, and
pbrt.org blocked direct fetch (403) — those claims rest on search summaries of
the exact pages plus source code fetched from GitHub.

### 2.1 Per-renderer highlights

- **LuxCoreRender / BlendLuxCore** — spectra are *textures*: `blackbody`
  (Kelvin), `irregulardata` (tabulated λ/value pairs), and `lampspectrum` — a
  **two-tier dropdown** (15 lamp categories → per-category presets: daylight,
  candle, incandescent, gas mantle, fluorescents/CFLs, high-pressure mercury,
  low/medium/high-pressure sodium, metal halide, LEDs, laser lines, glow
  discharges)
  (https://github.com/LuxCoreRender/BlendLuxCore/blob/master/nodes/textures/lampspectrum.py).
  A 33-entry IOR preset library ships as a **searchable popup** sorted by name
  or value
  (https://github.com/LuxCoreRender/BlendLuxCore/blob/old-master/operators/ior_presets.py).
  BlendLuxCore is GPL-3: taxonomy/UX is inspiration only; no code or data.
- **Mitsuba 3** — seven spectrum plugins: `uniform`, `regular`, `irregular`,
  `srgb` (upsampling), `d65`, `rawconstant`, `blackbody`; default range
  360-830 nm; `filename` loads from file; dict/XML syntax
  (https://mitsuba.readthedocs.io/en/latest/src/generated/plugins_spectra.html).
  The classic `.spd` format is plain text "λ value" per line, linearly
  interpolated (Mitsuba 0.4.5 manual). Intent (reflectance vs illuminant) is
  carried by the *consuming slot*, not the file.
- **PBRT v4** — spectrum parameters are `"rgb"`, `"blackbody"` (Kelvin), or
  `"spectrum"` as inline interleaved `[λ v λ v …]`, an external "λ value" text
  file, or a **named built-in**: `glass-BK7/…`, `metal-{Ag,Al,Au,Cu,…}-eta/-k`,
  `stdillum-A/D50/D65/F1-F12`, `illum-acesD60` (https://pbrt.org/fileformat-v4).
  Apache-2.0; glass tables credited to refractiveindex.info as CC0
  (https://github.com/mmp/pbrt-v4/blob/master/THIRD_PARTY.md). Rendering is
  always point-sampled spectral; RGB exists only at the boundaries.
- **Indigo** — spectrum elements: `uniform`, `blackbody` (T + gain), `rgb`,
  **`peak`** (parametric bandpass: start λ, width, base value, peak value) and
  `regular` tabulated; media take `absorption_coefficient_spectrum` (m⁻¹,
  Beer-Lambert) and Cauchy-B dispersion (https://indigorenderer.github.io/).
- **Radiance 6.0** — `specdata`/`specpict` primitives + `specfile` 1-D λ/value
  data files (non-uniform allowed; docs recommend them for standard
  illuminants) (https://radsite.lbl.gov/radiance/refer/ray.html).
- **Maxwell** — emitter colour via RGB/CCT-Kelvin; SDK enumerates
  `SPECTRUM_FILE` measured-emitter mode; photometric units (W+efficacy,
  lumens, lux, cd) + IES/Eulumdat
  (https://nextlimitsupport.atlassian.net/wiki/spaces/maxwell4/pages/5679500/Lighting+with+Emitters).
- **Manuka** — fully spectral hero-wavelength transport; applies measured
  **spectral camera sensitivity curves** so renders match specific camera
  footage (https://dl.acm.org/doi/10.1145/3182161). No public authoring UI
  docs. **Arnold** — no public evidence of spectral support; treat as RGB.
- **Cycles baseline** — Blackbody and Wavelength are *converter* nodes:
  spectral parameter in → **RGB out**. Blender users' entire mental model is
  "spectral thing → RGB conversion node"
  (https://docs.blender.org/manual/en/latest/render/shader_nodes/converter/blackbody.html).

### 2.2 Cross-renderer patterns that shape this design

1. **Presets first, files second, inline arrays third.** Every system leads
   with named presets/blackbody; measured SPD files are the power-user tier.
2. **No surveyed system offers a drawn-curve spectrum editor.** The owner's
   drawable-filter ask is a genuine differentiator, not catch-up.
3. **Two-tier lamp taxonomy** (LuxCore) is the proven UX for large lamp
   libraries.
4. **The consuming slot carries semantics** (Mitsuba/PBRT): the same spectrum
   type serves reflectance, illuminant, and absorption depending on where it
   is wired — adopted in §3.1.
5. **Astroray's key UX departure from Cycles:** our nodes must keep the
   spectrum native downstream instead of collapsing to RGB at the node.

### 2.3 SPD data sources and licenses (verified)

| Source | Content | License | Verdict |
|---|---|---|---|
| pbrt-v4 embedded spectra (`src/pbrt/util/spectrum.cpp`) | CIE illuminants A/D50/D65/F1-F12, ACES D60, glass + metal η/k | Apache-2.0; glass tables CC0 via refractiveindex.info | **Ship** — cleanest starter named-spectrum grab |
| refractiveindex.info | measured η/k + Sellmeier/Cauchy coefficients | entries CC0 (per pbrt THIRD_PARTY) | **Ship** — Sellmeier preset expansion |
| colour-science (github.com/colour-science/colour) | CIE illuminants/observers/light sources | BSD-3-Clause | **Ship** — already the pkg38 pipeline |
| NIST Atomic Spectra Database | atomic emission lines (Na, Hg, …) | US-gov, royalty-free | **Ship** — already used for `sodium_vapor` |
| LSPDD (lspdd.org) | measured lamp SPDs | **CC BY-NC-ND 2.5 CA** | **REJECT** — NonCommercial-NoDerivs; reference-only, never ship |
| CIE datasets direct from CIE | illuminant/observer tables | no verifiable open license | **Avoid** — use the numerically identical colour-science / pbrt copies |
| BlendLuxCore lampspectrum data | large lamp library | GPL-3, provenance unclear | **REJECT data**; use category taxonomy as UX inspiration only |

---

## 3. Design

### 3.1 Principles

1. **One currency: the Spectrum.** A single addon-side value type — an
   authored spectrum (λ → value over an explicit range, with a declared
   semantic: reflectance [0,1], transmittance [0,1], or emission (relative or
   W·m⁻²·sr⁻¹·nm⁻¹)) — produced by *source* nodes, transformed by
   *math/filter* nodes, consumed by *application* sinks (BSDF reflectance,
   light emission, world, camera response). Mirrors Mitsuba/PBRT's
   "spectrum is a first-class parameter type; the consuming slot carries the
   semantic" (§2.2/4) rather than bolting one-off enums onto each feature.
2. **True SPD beats upsampled RGB.** Wherever an authored spectrum is
   present, it is evaluated per-λ natively and **bypasses** the Jakob-Hanika
   RGB round trip; the JH path remains the fallback for RGB-authored content.
   (The pkg168/pkg182 lesson: upsampling is nonlinear and lossy; an authored
   SPD must never be squeezed through RGB. PBRT draws the same boundary —
   RGB only at the edges.)
3. **Non-destructive layering** (pkg57's original promise, kept this time):
   application nodes wrap a base BSDF and only modulate it spectrally;
   without an authored spectrum the render is bit-identical to not having
   the node.
4. **Fix the transport before the UI.** No node matters while the MW
   integrator cannot see lights. Phase 1 starts there.
5. **Pillar-4 forward-compatible.** The same Spectrum currency and physical
   units contract must be what blackbody/synchrotron/ADAF emission models
   (`plugins/emission/`, `plugins/accretion/`) plug into later;
   `SampledWavelengths::redshift` (pkg67) already matches this design.

### 3.2 Node family

**Custom socket** `AstroraySpectrumSocket` (new): carries a spectrum
description; unlinked default = flat 1.0. Sockets/nodes follow the pkg57
registration pattern (`blender_addon/nodes/__init__.py`).

**Source nodes** (output: Spectrum):
- **Spectrum Preset** — two-tier dropdown (category → preset, LuxCore-style
  UX taxonomy, §2.1) over the profile DB, reflectance categories 0-6 vs
  emission category 7 filtered by context.
- **Blackbody Spectrum** — temperature (K), normalize toggle
  (photopic-normalized as today vs raw Planck for physical work).
- **Gaussian / Bandpass Spectrum** — centre λ, FWHM, amplitude, baseline
  (Indigo's `peak` model, §2.1); stackable via Spectrum Math.
- **Drawn Spectrum** — the owner's headline ask, and a genuine
  differentiator (no surveyed renderer has one, §2.2/2): a curve the user
  draws mapping λ → value over a configurable [λmin, λmax] (default
  300-1000 nm). UI: Blender's native `CurveMapping` widget via
  `layout.template_curve_mapping` on a hidden helper (`ShaderNodeFloatCurve`
  in a private node group — the established workaround for CurveMapping on
  custom Python nodes; storage lives in the .blend). Export: evaluate the
  curve at 5 nm steps → tabulated SPD.
- **SPD File** — loads two-column "λ value" text (the PBRT/Mitsuba/Radiance
  convergent format, §2.1) or CSV; values cached into the node as a float
  array (the .blend stays self-contained).

**Math/filter nodes** (Spectrum in → Spectrum out):
- **Spectrum Math** — Multiply / Add / Mix(fac) / Scale / Clamp / Invert
  (1-S, turning absorption into transmission).
- Beer-Lambert absorption — exp(-σ(λ)·d), Indigo's
  `absorption_coefficient_spectrum` shape — is deliberately deferred to the
  volume phase; Phase 2 keeps filters linear.

**Application (sink) nodes:**
- **Spectral Reflectance** (fixes + subsumes "Spectral Profile") — inputs:
  base Shader + Spectrum. In-band: the spectrum *replaces* the JH-upsampled
  base colour per-λ (principle 2); out-of-band: extends the material response
  across the full profile range. Without a linked spectrum: pure passthrough.
- **Spectral Filter** — inputs: base Shader + Spectrum (transmittance);
  multiplies the base BSDF spectrally. The same node wired into a light's
  spectrum slot acts as a gel.
- **IR/UV Response (redesigned)** — becomes a preset wrapper over Spectral
  Reflectance: passes the base BSDF through untouched in the visible band and
  applies a constant-or-curve response only in the selected band. The current
  destructive grey-promotion path is deleted.
- **Sellmeier Glass (repaired)** — keep the node; plumb the manual B/C
  coefficients into the dielectric plugin (new `sellmeier_b/c` params read in
  `plugins/materials/dielectric.cpp`); expand the preset table later from
  refractiveindex.info CC0 data (§2.3).
- **Spectral Emission** — emission closure: Spectrum + strength, with a units
  enum (relative × Watts, or spectral radiance) — the Pillar-4-ready surface
  emitter.

**Light settings** (data panel, not nodes — matches how Blender users author
lamps; node-based light spectra can come later):
- Spectrum mode enum on `light.custom_raytracer`:
  `Native` (RGB / native temperature — exactly today's behaviour) ·
  `Lamp preset` (sodium_vapor, mercury_vapor, cie_f2/f3, led_* from the DB —
  the "make a lamp output a sodium spectrum" ask, engine-ready today) ·
  `Custom` (a node-authored / drawn spectrum or SPD file, by profile name).
- Colour stays available as gel tint (Composite mode) for all non-Native
  modes.
- World panel gets the same enum for background emission (Phase 2).

**Measurement/output side** (completes the IR/UV story):
- **Camera response** setting (scene or camera level): band-response curve
  (drawn/preset: photopic, CIE observer, silicon QE, generic NIR) applied as
  the sensor weighting for luminance-mode renders — the correct home for
  "IR/UV response" as *measurement*, distinct from material response.
  (Phase 3; PBRT-v4's `PixelSensor` and Manuka's measured camera-sensitivity
  workflow, §2.1, are the reference shapes.)

### 3.3 Engine & translation plumbing

1. **MW transport fix (prerequisite):** give `multiwavelength_path_tracer`
   next-event estimation over the pkg89 dedicated-light list, evaluating
   `EmissionSpectrum::eval(lambdas)` per sample. The `astroray::Light` base
   already has a spectral sample API (`include/astroray/light.h:119,136`
   returns `emission_spec` for given `SampledWavelengths`); the in-header
   path tracer's dedicated-light NEE (`include/raytracer.h:2423`) is the
   structural template. Alternative considered and rejected for Phase 1:
   folding band support into the default `path_tracer` — bigger blast
   radius, touches the wavefront GPU port (REG:254 kernels; memory:
   register saturation); revisit after Phase 1 proves the semantics.
2. **Runtime spectra:** `astroray.register_spectral_profile(name,
   lambda_min_nm, lambda_step_nm, values)` binding that inserts into
   `SpectralProfileDatabase` (storage is already vectors + a name index,
   `include/astroray/spectral_profile.h:51-58`). Drawn / imported / gaussian
   spectra register under `__blend__/<owner>/<node>` names; everything
   downstream (material attach, emission MeasuredSPD, GPU table upload at
   `scene_upload.cu:926`) is reused unchanged.
3. **Tabulated emission:** reuse `EmissionSpectrum::MeasuredSPD` pointed at a
   runtime-registered profile (zero new engine surface; the dict parser at
   `module/blender_module.cpp:104-161` already handles
   `{'mode':'measured_spd','profile':name}` and `composite` for gels).
4. **In-band native reflectance:** the material profile hook grows a mode —
   `ExtendOnly` (today's out-of-band-only behaviour, default; old scenes
   unchanged) vs `Replace` (profile drives all λ). `evalSpectralExt` /
   `sampleSpectralExt` grow one branch; Spectral Reflectance sets `Replace`.
5. **Bypass boundary:** the JH upsample stays exactly where it is for RGB
   sources; authored spectra short-circuit it (they never construct an
   `RGBAlbedoSpectrum`). Review rule of thumb: *an authored SPD must reach
   `SampledSpectrum` without passing through an RGB triple.*
6. **GPU:** Phase 1 keeps CPU as reference. Material profiles already upload
   (`scene_upload.cu:926-959`); spectral lights fall back to
   `deviceReference()` RGB (existing documented approximation);
   `Replace`-mode materials on GPU emit a pkg119 DegradationReport line.
   Full GPU spectral-light parity + MW wavefront NEE is a recorded follow-up
   (§5 Phase 3), gated by the usual HW sweep discipline (CI has no GPU).

### 3.4 Storage formats

- **Drawn curves:** authoritative storage = the CurveMapping inside the
  .blend (helper node group); exported to the engine as a resampled 5 nm
  float array at translation time. No new file format.
- **Imported SPDs:** cached as a float-array custom property on the node
  (IDProperty) so the .blend is self-contained; the source path is kept for
  re-import only. Accepted input: two-column "λ value" text (§2.1 convergent
  format) and CSV.
- **Shipping library:** stays in ASPR `profiles.bin`; new lamp/illuminant
  entries (CIE A, D50, D65-as-profile, F4/F11, metal halide, HPS vs LPS
  sodium, xenon) are added by `scripts/data/build_spectral_profiles.py` from
  the §2.3 "Ship"-verdict sources only, provenance recorded per entry in
  `data/spectral_profiles/sources.md` as today. LSPDD and BlendLuxCore data
  are explicitly rejected (licenses, §2.3).

### 3.5 Pillar-4 forward compatibility

- The Spectrum currency's emission semantic carries physical units
  (W·m⁻²·sr⁻¹·nm⁻¹) as an explicit enum, so GR emission models (blackbody
  disk, `plugins/emission/synchrotron.cpp`, `plugins/accretion/adaf.cpp`,
  `slim_disk.cpp`) can later surface their SPDs through the same
  light/emission settings without re-plumbing.
  `SampledWavelengths::fromLambdas` (pkg43/44) is already the evaluation API
  those models use.
- Redshift-aware sampling exists (`SampledWavelengths::redshift`, pkg67);
  authored spectra are evaluated at emitter-frame λ, so nodes need no changes
  for GR correctness — only the integrator applies shifts.
- The Drawn Spectrum / bandpass nodes double as instrument filters
  (narrowband imaging of emission lines) once camera response (Phase 3)
  lands — the astrophysics use-case behind the owner's directive.
- The 300-2500 nm range is a *current DB* limit, not a design limit: the
  ASPR header carries λmin/λmax/step and `register_spectral_profile` accepts
  arbitrary ranges; synchrotron work needs far wider bands — a log-λ table
  variant is a recorded Phase-4 follow-up.

---

## 4. Data provenance & licenses (cite-algorithm discipline)

Already-shipped data (`data/spectral_profiles/sources.md`): USGS splib07
(public domain), NASA/JPL ECOSTRESS (public domain), CIE 15:2018 tables via
colour-science v0.4.7 (BSD-3-Clause), NIST Atomic Spectra Database (US-gov
public domain) for Na I / Hg I. New additions follow §2.3's verdict table:

- **CIE standard illuminants** (A, D50, D65, F-series, LED-B): CIE 15:2018
  tables via colour-science (BSD-3) — same pipeline as the existing
  `cie_f2/f3`, `led_*` entries — or pbrt-v4's Apache-2.0 embedded copies.
- **Lamp SPDs** (HPS/LPS sodium, metal halide, xenon): NIST ASD line data +
  published pressure-broadening envelopes, synthesized as for `sodium_vapor`;
  LSPDD rejected (CC BY-NC-ND).
- **Sellmeier presets:** refractiveindex.info (CC0 entries).
- **Planck blackbody:** already implemented + Cycles-pattern photopic
  normalization (pkg122; `src/emission_spectrum.cpp:16-28`). No new
  algorithm.
- **Jakob & Hanika 2019** upsampling (DOI 10.1111/cgf.13626): unchanged; this
  design only adds bypasses around it.
- **Tabulated-SPD evaluation:** linear interpolation over regular/irregular
  samples — reference implementation PBRT-v4 `PiecewiseLinearSpectrum`
  (Apache-2.0, github.com/mmp/pbrt-v4 `src/pbrt/util/spectrum.h`);
  Astroray's `SpectralProfile::reflectance` already implements the
  regular-grid case.
- **Sensor/band response weighting:** PBRT-v4 `PixelSensor` (Apache-2.0) as
  the Phase-3 reference shape; Manuka's measured-sensitivity workflow (TOG
  2018, DOI 10.1145/3182161) as the motivating precedent.

---

## 5. Phasing

- **Phase 1 — make it true
  (`.astroray_plan/packages/pkg195-spectral-nodes-phase1.md`):**
  MW-integrator NEE for dedicated lights; in-band `Replace` mode + JH bypass;
  light Spectrum-mode enum with lamp presets (sodium!) + custom profiles;
  `register_spectral_profile` binding; Drawn Spectrum + Spectrum Preset +
  Blackbody Spectrum source nodes feeding materials and lights; IR/UV node
  made non-destructive; Sellmeier manual B/C plumbed; render-level regression
  tests for every failure in §1.2.
- **Phase 2 — the full node family:** Spectrum socket graph evaluation
  (Math / Filter / Gaussian nodes, gel filters on lights), Spectral Emission
  node, world spectrum, SPD file import.
- **Phase 3 — measurement:** camera/sensor response curves, band-response
  presets, colourmap interaction, false-colour pipelines; GPU spectral-light
  parity + MW wavefront NEE; GMaterial `Replace` mode.
- **Phase 4 — Pillar 4 alignment:** physical-units audit end-to-end, GR
  emission models surfaced through the same spectrum settings, log-λ
  wide-band tables for synchrotron.

Phases 2-4 are recorded here only; file follow-up specs at Phase 1 close.

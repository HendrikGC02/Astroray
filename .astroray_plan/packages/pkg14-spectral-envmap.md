# pkg14 — Spectral env map and flip the default

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 1 week (~3 sessions)
**Depends on:** pkg13

---

## Goal

**Before:** every shading event runs spectrally, but the environment
map (HDRI sampling, importance sampling for IBL) still returns RGB.
The pkg11 fallback upsamples that RGB at every env-map ray miss. The
legacy `path_tracer` plugin remains the registry default; users have
to call `set_integrator("spectral_path_tracer")` to opt into spectral
mode.

**After:** the env map is spectral-native. HDRI texels become
`RGBIlluminantSpectrum` instances, cached at load time so importance
sampling and ray-miss evaluation both run without per-call upsampling.
A Hošek-Wilkie analytical sky model is added as a separate plugin
(spectral-native by construction) for procedural skies. Once the env
map lands, the legacy RGB `pathTrace` and the `path_tracer` plugin are
deleted; `spectral_path_tracer` is renamed `path_tracer` and registered
as the default. Pillar 2 closes with one code path, not two.

This is two packages stacked in one (envmap + flip default). The
spectral-core design doc explicitly bundles them as Phase 2D + 2E
because flipping the default before the env map means the renderer
silently runs the slow fallback for every miss, and shipping the env
map without flipping the default leaves a half-finished pipeline.

---

## Context

Phase 2D + 2E of Pillar 2 — the closing package. After pkg13 every
shading event is spectral; after pkg14 every light-source evaluation is
too. Flipping the default is the smallest change in this package by
line count but the most consequential: the legacy `pathTrace` and
`path_tracer` plugin are deleted outright, every existing scene now
runs through the spectral pipeline, and the registry default name
"path_tracer" now points at the spectral implementation. The 1% A/B
parity check from pkg11–13 is what makes this safe.

---

## Reference

- Design doc: `.astroray_plan/docs/spectral-core.md §Phase 2D & §Phase 2E`
- Hošek-Wilkie 2012 reference: Hošek and Wilkie, "An Analytic Model for
  Full Spectral Sky-Dome Radiance" — coefficient tables in the original
  supplemental materials (BSD-3 license)
- Existing env map: search `module/blender_module.cpp` for
  `set_environment` / `set_environment_map` / `loadHDR` and follow into
  `src/` to find the loader; the env map is currently a `Vec3` HDR
  texture
- pkg10 RGBIlluminantSpectrum: `include/astroray/spectrum.h`
- pkg11 SpectralPathTracer integrator: `plugins/integrators/spectral_path_tracer.cpp`

---

## Prerequisites

- [ ] pkg13 is merged on `main`; every material/texture has a spectral
      override.
- [ ] Build is green; full pytest passes; Cornell A/B parity ≤1% holds.
- [ ] A pre-pkg14 baseline render of every showcase scene is captured
      so the "flip default" step can be A/B-verified without ambiguity.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/integrators/sky_hosek_wilkie.cpp` *(optional, time-permitting)* | Hošek-Wilkie 2012 spectral sky as a separate environment plugin. Registers as `"hosek_wilkie_sky"`. Scene picks one or the other. If timeline tightens, defer to a later package and ship pkg14 with HDRI env map only. |
| `data/spectra/hosek_wilkie_coeffs.inc` *(only if HW lands here)* | `constexpr` table of Hošek-Wilkie radiance coefficients (turbidity × albedo × λ × parameter). |
| `tests/test_spectral_envmap.py` | pytest: HDRI env map sample under `evalSpectral` produces values matching the upsampled-`sample` fallback ≤1e-5 on a sweep of directions; importance sampling PDFs unchanged from RGB version (sampling pattern and PDFs are luminance-driven, identical math); A/B Cornell + outdoor-HDRI scene matches pre-pkg14 render within 1% mean per channel. |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/environment.h` *(or wherever the env map lives)* | Add `virtual SampledSpectrum evalSpectral(const Vec3& dir, const SampledWavelengths& lambdas) const = 0`. The default RGB `eval(dir)` may stay for backward compat or be deleted (decide during implementation; deleting is cleaner if the codebase has only one consumer left). |
| `src/environment.cpp` (HDRI implementation) | At load time, build a parallel `RGBIlluminantSpectrum` atlas next to the RGB HDR data. `evalSpectral` reads from the spectral atlas; importance sampling logic unchanged (still luminance-driven). Memory cost is 3× the source HDR's float storage — acceptable given HDRI is loaded once. |
| `plugins/integrators/spectral_path_tracer.cpp` | Switch env-map ray-miss handling from "RGB then upsample" to direct `envMap->evalSpectral(dir, lambdas)`. Delete the upsample fallback path inside this integrator. |
| `plugins/integrators/path_tracer.cpp` | **DELETE.** Legacy RGB integrator removed in this package. |
| `src/path_tracer.cpp` *(or wherever legacy `pathTrace` lives in core)* | **DELETE** the legacy `pathTrace` function. The spectral integrator becomes the only path. |
| `plugins/integrators/spectral_path_tracer.cpp` | Rename registry name from `"spectral_path_tracer"` to `"path_tracer"` so the default name preserves backward compatibility for scene files / Python users. The plugin file itself can keep its descriptive filename or be renamed — pick one in the implementing PR. |
| `include/astroray/integrator.h` | Delete the RGB `sample()` virtual now that no integrator returns RGB. Make `sampleSpectral()` pure virtual. Remove the `IntegratorKind` enum added in pkg11 — it served only to discriminate the two paths. |
| `include/astroray/material.h` | Make `evalSpectral` (and `emittedSpectral` if applicable) pure virtual. Delete the default fallback. Delete the legacy `Vec3 eval` virtual now that nothing calls it. |
| `include/astroray/texture.h` | Same — make `sampleSpectral` pure virtual; delete `Vec3 sample`. |
| `plugins/materials/*.cpp`, `plugins/textures/*.cpp` | Drop the now-unused `Vec3 eval` / `Vec3 sample` overrides where they exist as RGB-original code. Keep them only where the spectral override delegates back to RGB internally — that case rewrites to spectral-native math. |
| `module/blender_module.cpp` | Delete RGB-only debug bindings (`is_spectral_mode()` from pkg11, any `pathTrace`-direct call, etc.). Update `integrator_type` enum in the Blender addon UI (drop the spectral toggle since spectral is now the only mode). |
| `include/astroray/spectral.h` | **Audit.** If the GR renderer is the only remaining consumer (it is, per pkg10), keep as-is. If anything in the rendering pipeline still includes it, that's a leftover bug — fix in this package. |
| `THIRD_PARTY.md` | Add provenance for Hošek-Wilkie coefficients if that plugin lands here. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg14 done; mark Pillar 2 100%; declare Pillar 2 complete; surface Pillar 3 as next. |
| `CHANGELOG.md` | Add pkg14 entry; close the "Pillar 2 — Spectral core (in progress)" header to "Pillar 2 — Spectral core COMPLETE (pkg10–14)". |

### Files explicitly NOT touched

- `include/astroray/spectral.h` (GR renderer dependency stays).
- The GR renderer itself — its `SpectralSample`-based pipeline is
  orthogonal and stays as-is. Unifying the two spectral pipelines is
  a future package, not pkg14.
- Any plugin under `plugins/passes/` — they continue to operate on the
  RGB framebuffer (the XYZ→sRGB conversion still happens once at write).

### Key design decisions

1. **Env map atlas, not per-call upsample.** HDRI textures are loaded
   once; the spectral atlas is 3× the float storage. Worth it for the
   per-pixel constant-time lookup. Procedural / analytic skies (Hošek-
   Wilkie) compute spectrally on demand — no atlas needed.
2. **Importance sampling stays luminance-driven.** The PDFs of HDRI
   importance sampling are computed from the source's luminance map.
   Replacing that with a spectral importance scheme is a non-goal —
   it would be its own package and the Pillar 2 ≤1.5× perf budget
   doesn't allow for the variance penalty.
3. **Hošek-Wilkie is best-effort in pkg14.** If it lands cleanly,
   great. If it adds risk to the "flip default" step, defer to a
   follow-up package — the env map atlas is the load-bearing piece;
   the analytic sky model is value-add.
4. **Flip the default in the same PR as the env map.** They have to
   land together because the spectral pipeline isn't complete until
   the env map is spectral, and the legacy path can't be deleted
   until the spectral pipeline is complete. Bundling means one
   reviewable A/B parity check covers both halves.
5. **Delete legacy code, do not leave it as #ifdef.** The plugin
   architecture lets us reintroduce a "rgb_path_tracer" plugin
   later if anyone wants to compare; it would be a clean fork from
   the spectral version, not a half-resurrected dead path.
6. **Rename registry name `spectral_path_tracer` → `path_tracer`.**
   Backward compat for scene files and Blender UI — users see
   "path_tracer" everywhere. Internally the file is still
   `plugins/integrators/spectral_path_tracer.cpp` (or rename it
   too — bikeshed during the PR).
7. **`Material::eval` removal is the breaking change for plugin
   authors.** Document it in `CONTRIBUTING.md` and the migration
   notes section of `CHANGELOG.md`.

---

## Acceptance criteria

- [ ] HDRI env map produces spectral results within ≤1e-5 of the
      pkg11-style upsample-from-RGB fallback (which is now deleted but
      can be reproduced in the test by upsampling the source RGB
      manually).
- [ ] An outdoor scene (existing showcase, e.g. `Scene2_envmap`)
      renders within 1% mean per channel of the pre-pkg14 baseline.
- [ ] All five showcase renders in the README match their pre-pkg14
      baselines within 1% mean per channel.
- [ ] No reference to `Vec3 eval` / `Vec3 sample` remains in
      `Material` / `Texture` / `Integrator` interface headers.
- [ ] `astroray.integrator_registry_names()` returns `["path_tracer",
      "ambient_occlusion"]` (no `"spectral_path_tracer"` entry — the
      rename is complete).
- [ ] `pathTrace` symbol no longer exists in the core library.
- [ ] All existing tests still pass.
- [ ] Cornell box at 32 spp render time is no more than 1.5× the
      pre-pkg11 RGB-only baseline.
- [ ] Pillar 2 acceptance criteria from `spectral-core.md` all met:
      RGB/spectral parity to noise, prism dispersion visible, ≤1.5× perf
      ceiling, all existing tests pass.

---

## Non-goals

- No GR-renderer unification. `spectral.h` (CIE 1931 2°) and the new
  `spectrum.h` (CIE 1964 10°) coexist deliberately; a unification
  package can come later if it's worth doing at all.
- No measured-BRDF loader (RGL/MERL). Pillar 3+.
- No spectral AOV pass. Plugin, separate package.
- No Tódová-Wilkie 2025 metameric illuminants. Plugin, separate package.
- No new wavelength-sample-count tuning. `kSpectrumSamples = 4` stays.
- No volumetric / participating media spectral upgrade beyond the
  existing `Isotropic` material (Pillar 3 scope).
- No OpenEXR output upgrade. Pillar 5.

---

## Progress

- [ ] Branch `pkg14-spectral-envmap` from `main`.
- [ ] Capture pre-pkg14 baseline renders of every showcase scene.
- [ ] Add `Environment::evalSpectral` virtual + HDRI atlas
      implementation.
- [ ] Wire spectral integrator's env-map miss to `evalSpectral`.
- [ ] (Optional) implement Hošek-Wilkie sky plugin + coeff table.
- [ ] Delete `plugins/integrators/path_tracer.cpp`, legacy
      `pathTrace`, `Vec3 eval`/`Vec3 sample` virtuals, RGB integrator
      bookkeeping in Renderer.
- [ ] Rename `spectral_path_tracer` registry name → `path_tracer`.
- [ ] Drop now-dead RGB overrides across all material/texture plugins.
- [ ] Update Blender addon UI (remove integrator-mode toggle).
- [ ] Run full pytest; render every showcase scene; compare to
      baseline within 1% per channel.
- [ ] Profile spectral Cornell vs pre-pkg11 RGB baseline; confirm
      ≤1.5× ratio.
- [ ] Update STATUS.md, CHANGELOG.md, CONTRIBUTING.md.
- [ ] Commit per granularity plan; push branch; open PR with the
      "Pillar 2 complete" summary.

---

## Lessons

*(Fill in after the package is done.)*

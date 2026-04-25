# pkg11 — Spectral path tracer

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 1 week (~3 sessions)
**Depends on:** pkg10

---

## Goal

**Before:** the pkg10 spectral types compile and are tested in isolation,
but no integrator consumes them. The default integrator is the legacy
RGB `path_tracer` plugin; `Integrator::sampleSpectral` returns a
flat-luminance fallback over the legacy `SpectralSample`.

**After:** a new `spectral_path_tracer` plugin (registered alongside
the existing `path_tracer` and `ambient_occlusion`) traces with
`SampledSpectrum` throughout — radiance, throughput, BSDF eval, light
contribution. `Material` gains a virtual `evalSpectral(...)` with a
default that calls the existing RGB `eval(...)` and upsamples via
Jakob-Hanika; concrete materials override it in pkg12–13. The renderer
accumulates XYZ per pixel when this integrator is active and converts
to sRGB once at framebuffer write time. The legacy `path_tracer` stays
the registry default — flipping the default is pkg14.

---

## Context

This is Phase 2B of the Pillar 2 roadmap (spectral-core.md). It is the
"shadow path tracer" step: spectral and RGB code paths run side by side,
selectable from Python via `set_integrator("spectral_path_tracer")`,
so we can A/B compare on a single scene before committing the renderer
to spectral-only. The default `evalSpectral` fallback is the load-bearing
piece — without it, every existing material would have to migrate before
the spectral integrator is even runnable. With it, pkg11 ships a working
end-to-end spectral path on day one and pkg12+ migrate materials one at
a time, each step keeping the test suite green.

---

## Reference

- Design doc: `.astroray_plan/docs/spectral-core.md §Migration strategy → Phase 2B`
- Per-path lifecycle pseudocode: same doc, §Per-path lifecycle
- Existing integrator pattern: `plugins/integrators/path_tracer.cpp`,
  `plugins/integrators/ambient_occlusion.cpp`
- Integrator base + `SampleResult`: `include/astroray/integrator.h`
- Spectral types: `include/astroray/spectrum.h` (pkg10)
- Material interface: `include/astroray/material.h`,
  `include/raytracer.h` (Material::eval)

---

## Prerequisites

- [ ] pkg10 is merged on `main`; `tests/test_spectrum.py` is green.
- [ ] Build is green on `main`: `cmake -B build && cmake --build build -j && pytest tests/ -v`.
- [ ] A reference Cornell box render exists from `main` for the A/B
      comparison check below.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `plugins/integrators/spectral_path_tracer.cpp` | Registers `spectral_path_tracer`. Implements `sampleSpectral(ray, gen) -> SampleResult` using `SampledWavelengths::sampleUniform`, recursive bounce loop, MIS-equivalent NEE, firefly clamp at luminance > 20.0f, emission only when `wasSpecular` or `bounce==0`. Returns `SampleResult` with `radiance` populated as the XYZ projection (`rad.toXYZ(lambdas) / kSpectrumSamples`) so the existing RGB framebuffer path keeps working. |
| `tests/test_spectral_path_tracer.py` | pytest: spectral integrator registers; A/B Cornell box renders within 1% mean brightness of legacy `path_tracer`; prism scene shows dispersion in spectral mode (qualitative — distinct R/G/B exit angles assert non-zero spread); existing 189 tests still pass. |
| `tests/data/cornell_spectral_baseline.exr` *(optional)* | Reference baseline for pixel-mean comparison if EXR support exists; otherwise a JSON of mean RGB. |

### Files to modify

| File | What changes |
|---|---|
| `include/astroray/material.h` | Add `virtual SampledSpectrum evalSpectral(const Vec3& wo, const Vec3& wi, const Vec3& normal, const Vec2& uv, const SampledWavelengths& lambdas) const`. Default implementation: call `eval(wo, wi, normal, uv)` to get RGB, build `RGBAlbedoSpectrum(rgb)` and return `.sample(lambdas)`. Same for any other return-radiance entry point currently on the interface (e.g. `emitted`/`emission` if present — add `emittedSpectral` mirror with `RGBIlluminantSpectrum` fallback). Keep all existing `Vec3` methods unchanged. |
| `include/astroray/integrator.h` | Replace the placeholder `sampleSpectral` default with one that delegates to `sample(ray, gen)` and upsamples the resulting RGB radiance via `RGBIlluminantSpectrum`. New plugins override either `sample` or `sampleSpectral`; `Renderer` picks based on integrator capability flag (see below). |
| `include/raytracer.h` (`Renderer`) | Add `bool spectralMode_` set when the active integrator advertises `kind() == IntegratorKind::Spectral`. When true, the per-pixel accumulator stores XYZ; final sRGB conversion uses the `xyzToLinearSRGB` matrix already in `spectral.h`. RGB integrators continue to write into the RGB accumulator unchanged. The firefly clamp moves to operate on luminance computed from XYZ when in spectral mode. |
| `module/blender_module.cpp` | Expose `set_integrator("spectral_path_tracer")` (already works via the registry binding from pkg05 — verify and add a Blender UI option). Add `is_spectral_mode()` debug binding. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg11 in-progress → done; bump Pillar 2 % to ~40; surface pkg12 as next. |
| `CHANGELOG.md` | Add pkg11 entry under "Pillar 2 — Spectral core (in progress)". |

### Files explicitly NOT touched

- `plugins/integrators/path_tracer.cpp` — legacy RGB integrator stays
  the registry default.
- `plugins/materials/*.cpp` — every material keeps its `Vec3 eval`;
  spectral overrides land in pkg12 (Lambertian) and pkg13 (rest).
- `plugins/passes/*.cpp` — passes still operate on the RGB framebuffer.
- `include/astroray/spectral.h` — GR renderer still depends on it.
- Env map / HDRI handling — that is pkg14.

### Key design decisions

1. **Two integrator paths, one Renderer.** Legacy `Integrator::sample`
   returns RGB `SampleResult`; new `sampleSpectral` returns the same
   shape with the radiance pre-projected to XYZ. The Renderer chooses
   which to call from a `kind()` enum. This avoids a whole-codebase
   API churn and keeps RGB plugins (AO, future toy integrators) working.
2. **Default `evalSpectral` is a Jakob-Hanika upsample of `eval`.** This
   is the entire reason pkg11 can ship before pkg12. Materials missing
   a spectral override produce identical results to RGB mode — the only
   visible difference is dispersive ones (handled by overrides in
   pkg13's dielectric).
3. **Hero-wavelength sampling per pixel sample.** `SampledWavelengths::sampleUniform(rng())`
   per primary ray, propagated through every bounce. At a dispersive
   interface the override calls `lambdas.terminateSecondary()`.
4. **XYZ accumulation, single conversion at output.** The per-pixel
   accumulator is XYZ in spectral mode; sRGB conversion happens in
   `Renderer::render` exactly once, alongside gamma correction (the
   project's "gamma once" invariant is preserved).
5. **No new Material plugins.** Every existing material keeps its
   single-file plugin; the `evalSpectral` override lives in the same
   file when added in pkg12+.
6. **Firefly clamp in spectral mode.** Luminance is computed from the
   XYZ Y component (well-defined, photometric); the threshold stays
   20.0f exactly to preserve current image character.
7. **No MIS rewrite.** Existing NEE / multiple importance sampling code
   is rewired to operate on `SampledSpectrum`; the math is identical
   componentwise. Variance reduction over hero wavelengths is a future
   tuning package, not pkg11.

---

## Acceptance criteria

- [ ] `astroray.integrator_registry_names()` contains `"spectral_path_tracer"`.
- [ ] Cornell box at 32 spp rendered with `spectral_path_tracer` matches
      the legacy `path_tracer` baseline mean RGB within 1% per channel.
- [ ] A glass-prism scene under D65 illumination renders visible
      rainbow dispersion in spectral mode (R/G/B exit-ray spread > 0)
      and a single refracted spot in RGB mode.
- [ ] Spectral render time on Cornell box at 32 spp is no more than
      1.5× the RGB render time.
- [ ] All previously-passing tests still pass (189 + new).
- [ ] No signature change to any existing `Material::eval` — only new
      virtual methods added with safe defaults.
- [ ] `plugins/passes/*.cpp` and `plugins/materials/*.cpp` are unchanged.

---

## Non-goals

- No migration of any concrete material (Lambertian, Metal, Dielectric,
  Disney, etc.) to a spectral-native `evalSpectral` body. That is
  pkg12–13.
- No spectral env map sampling. The env map still returns RGB; the
  default upsampling kicks in transparently. pkg14 makes it native.
- No deletion of `pathTrace` or `path_tracer` plugin. pkg14 flips the
  default.
- No new spectral AOV pass.
- No measured-BRDF or Hošek-Wilkie work.
- No tuning of `kSpectrumSamples`.
- No GR-renderer changes — `spectral.h` and the GR path stay frozen.

---

## Progress

- [ ] Branch `pkg11-spectral-path-tracer` from `main`.
- [ ] Add `evalSpectral` (and `emittedSpectral` if applicable) defaults
      to `Material` interface with Jakob-Hanika upsample.
- [ ] Wire `IntegratorKind` enum + `Renderer::spectralMode_` switch
      and XYZ accumulator path.
- [ ] Implement `plugins/integrators/spectral_path_tracer.cpp`.
- [ ] Add Blender UI option for the spectral integrator.
- [ ] Build a glass-prism reference scene under `tests/scenes/` (or
      reuse an existing Cornell box variant) and capture pre-pkg11
      baseline.
- [ ] Write `tests/test_spectral_path_tracer.py`.
- [ ] Run full pytest; render Cornell + prism A/B comparison.
- [ ] Profile spectral vs RGB on Cornell — confirm ≤1.5× ratio.
- [ ] Update STATUS.md, CHANGELOG.md.
- [ ] Commit per granularity plan; push branch; open PR.

---

## Lessons

*(Fill in after the package is done.)*

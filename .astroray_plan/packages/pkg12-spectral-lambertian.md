# pkg12 — Spectral Lambertian

**Pillar:** 2
**Track:** A
**Status:** open
**Estimated effort:** 1 session (~2–3 h)
**Depends on:** pkg11

---

## Goal

**Before:** all materials, including Lambertian, rely on the default
`evalSpectral` from pkg11 — Jakob-Hanika upsamples the RGB albedo at
every shading event. Correct, but redundant: the upsample is recomputed
per-call from the same `Vec3 albedo`. No material has yet demonstrated
the spectral-native pattern.

**After:** `plugins/materials/lambertian.cpp` overrides `evalSpectral`
(and emission/`emittedSpectral` if Lambertian carries an emissive
variant). The override caches a `RGBAlbedoSpectrum` once per material
instance and samples it on demand: `albedo_spec_.sample(lambdas) / pi`.
Identical numerical behaviour to the default fallback (verified by
test) but ~3–5× faster in spectral mode and pattern-establishing for
pkg13. Lambertian becomes the reference example of "what a spectral
material looks like in this codebase."

---

## Context

Phase 2C of Pillar 2 begins here. Lambertian is the right first
material for the same reason it was first to migrate to plugins in
pkg02: minimal BSDF (constant ÷ π), no Fresnel, no anisotropy, no
microfacet machinery. Whatever pattern lands here gets copy-pasted
across nine other materials in pkg13. Picking the wrong cache shape
or naming convention costs nine refactors downstream. Keep it boring,
keep it ugly-direct, keep it copy-pastable.

---

## Reference

- Design doc: `.astroray_plan/docs/spectral-core.md §Phase 2C`
- Default fallback we're replacing: `Material::evalSpectral` (added in pkg11)
- Existing Lambertian: `plugins/materials/lambertian.cpp`
- pkg10 spectral types: `include/astroray/spectrum.h`

---

## Prerequisites

- [ ] pkg11 is merged on `main`; `spectral_path_tracer` integrator is
      present in the registry; A/B Cornell parity is established.
- [ ] Build is green; full pytest passes.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_spectral_lambertian.py` | pytest: spectral Lambertian render of a uniform-grey wall under D65 produces XYZ within 1% of the analytical D65×albedo expectation; spectral-mode render of a coloured Cornell box matches RGB-mode render within 1% mean per channel; cache is built once (private bookkeeping check via a debug counter or via timing parity to pkg10 LUT lookups). |

### Files to modify

| File | What changes |
|---|---|
| `plugins/materials/lambertian.cpp` | Add member `RGBAlbedoSpectrum albedo_spec_` (or equivalent — either eagerly initialised in the constructor from the existing `albedo_` `Vec3`, or lazily on first `evalSpectral` call behind a `std::once_flag`). Override `evalSpectral` returning `albedo_spec_.sample(lambdas) * (1.0f / float(M_PI))`. If the plugin currently exposes `emit`/emission for emissive subclasses, mirror with `emittedSpectral` using `RGBIlluminantSpectrum`. Keep `eval` unchanged. |
| `.astroray_plan/docs/STATUS.md` | Mark pkg12 done; bump Pillar 2 % to ~55. |
| `CHANGELOG.md` | Add pkg12 entry. |

### Files explicitly NOT touched

- Any other material plugin (those are pkg13).
- `Material::eval`, `Material::evalSpectral` defaults — no signature
  change in pkg12.
- `Renderer`, `Integrator`, framebuffer code.

### Key design decisions

1. **Eager cache, not lazy.** `RGBAlbedoSpectrum` is 12 bytes (3 floats)
   and the Jakob-Hanika lookup is cheap; build it in the constructor
   and avoid the `std::once_flag` overhead per shading call.
2. **`Vec3 albedo_` stays.** The RGB representation remains for the
   existing `eval` path and for Blender/Python introspection.
   `albedo_spec_` is computed alongside it. There is one source of
   truth (`albedo_`) and one cache (`albedo_spec_`).
3. **Procedural-texture Lambertian also gets the override.** If
   `lambertian` supports a `Texture` for albedo (currently it does via
   `texture_` indirection), the spectral override samples the texture's
   RGB and upsamples per-call. Caching textures is a non-goal —
   procedural textures vary per-uv. Track in pkg13 if the cache
   strategy needs revisiting.
4. **No public API changes.** `set_material("lambertian", {...})` still
   takes RGB albedo. The user does not see Jakob-Hanika.
5. **Test against the default fallback.** The strongest correctness
   check is that the override produces values matching the pkg11
   default fallback within 1e-5 — i.e., the optimisation is
   numerically a no-op.

---

## Acceptance criteria

- [ ] `evalSpectral` on a Lambertian instance with constant `albedo_`
      returns values numerically identical (≤1e-5) to the pkg11 default
      fallback for the same `(wo, wi, normal, uv, lambdas)` tuple.
- [ ] Cornell box rendered in spectral mode matches RGB mode within 1%
      mean per channel (same criterion as pkg11, must continue to hold).
- [ ] Render-time profile of Lambertian-heavy Cornell scene shows the
      spectral path is ≥3× faster than pkg11's default-fallback baseline
      on the same scene (the entire point of this package).
- [ ] No other plugin file changed.
- [ ] All existing tests still pass.

---

## Non-goals

- No migration of any other material. Pkg13.
- No texture spectral overload. Pkg13 (it lands with the materials
  that need it).
- No public API changes; users still pass `Vec3 albedo`.
- No move of `Material::evalSpectral` from a default-having virtual
  to pure virtual. That happens in pkg14 as part of "flip the default."
- No tuning, no perf chase beyond the cache.

---

## Progress

- [ ] Branch `pkg12-spectral-lambertian` from `main`.
- [ ] Add `RGBAlbedoSpectrum albedo_spec_` member; populate in ctor.
- [ ] Override `evalSpectral`; mirror `emittedSpectral` if applicable.
- [ ] Write `tests/test_spectral_lambertian.py`.
- [ ] Profile against pkg11 baseline on Cornell box; confirm speedup.
- [ ] Update STATUS.md, CHANGELOG.md.
- [ ] Commit, push, PR.

---

## Lessons

*(Fill in after the package is done.)*

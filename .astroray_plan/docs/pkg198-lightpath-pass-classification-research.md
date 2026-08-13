# pkg198 Stage 1 — CPU light-path pass classification: algorithm sourcing

**Cite-algorithm (CLAUDE.md §6).** The tagging conventions are NOT invented — they mirror
Cycles' render-pass (light-path-expression) model, which is what Blender users expect from
`Diffuse Direct/Indirect`, `Glossy …`, `Transmission …`, `Emission`, `Environment`.

## Sources (Apache-2.0, Blender/Cycles `main`)
- `intern/cycles/kernel/film/light_passes.h`
  - `film_write_direct_light`, `film_write_indirect_light`,
    `film_write_emission_or_background_pass`, `film_write_background`.
- `intern/cycles/kernel/integrator/shade_surface.h`
  - `integrate_surface_bsdf_bssrdf_bounce` (weight lock), `integrate_surface_direct_light`.

## The Cycles model (verified 2026-08-14 by fetching the two files above)
1. **Category (diffuse / glossy / transmission) is locked at the FIRST surface bounce**
   (`INTEGRATOR_STATE(state, path, bounce) == 0`): Cycles stores `pass_diffuse_weight` and
   `pass_glossy_weight` from the BSDF eval; transmission weight is the residual
   `1 - diffuse - glossy`. These weights persist unchanged through all later (indirect)
   bounces — the category of the *camera-visible* surface labels ALL light that reaches it.
2. **Direct vs indirect is by bounce count**: light gathered at the first surface = DIRECT;
   light gathered after further bounces = INDIRECT, apportioned by the SAME first-hit weights.
3. **Emission / environment**: `film_write_emission_or_background_pass` — when the contribution
   is *directly visible* (`!(path_flag & PATH_RAY_ANY_PASS)`, i.e. before any non-specular pass
   bounce) surface emission → `PASS_EMISSION` and background → the environment pass. After a
   pass bounce, emission/background is folded into the diffuse/glossy/transmission INDIRECT
   passes by the stored weights.

## Adaptation to Astroray's granularity (documented approximation)
Astroray's `evalSpectral` returns a single combined spectrum (no per-closure diffuse/glossy
split), and `BSDFSampleSpectral` carries no lobe label. So the continuous
`pass_diffuse_weight`/`pass_glossy_weight` split is not available. We use the coarser but
faithful **single path-label** form of the same model (the label variant Cycles itself falls
back to when closure weights are unavailable):

- One category `firstCat ∈ {DIFFUSE, GLOSSY, TRANSMISSION}` is locked at the first BSDF sample.
- **Category of a sample** (`sampleCat`): TRANSMISSION if the sampled `wi` crossed the surface
  (sign of `dot(wo,N)` ≠ sign of `dot(wi,N)`, geometric sign test — no distance/sentinel
  consumed, per [[occlusion-sentinel-as-distance-class-of-bug]]); else GLOSSY if the sample is
  a delta reflection (mirror) or `material->isGlossy()`; else DIFFUSE. This gives: lambertian→
  diffuse, metal/mirror→glossy, dielectric/thin_glass refraction→transmission & Fresnel
  reflection→glossy, principled-glass→transmission, other principled→glossy (Stage-1 fold:
  a mixed Principled surface's diffuse energy is counted glossy — acceptable, documented).
- **Direct regime = `firstCat == -1`** (no BSDF interaction yet): NEE → `<cat>_DIRECT`
  (cat = reflect category of the vertex material); directly-seen surface emission →
  `PASS_EMISSION`; background miss → `PASS_ENVIRONMENT`.
- **Indirect regime = after `firstCat` locked**: every contribution (NEE, lamp hit, emissive
  hit, SMS caustic, background miss) → `<firstCat>_INDIRECT`.

## Sum-to-beauty invariant (gate 1)
Every `color += X` in `pathTraceSpectral` is paired with exactly one `passes[p] += X` (total
partition), so `Σ passes == beauty` per sample, per wavelength bundle, EXACTLY in spectral
space. Passes are stored as XYZ (same convention as `SampleResult.color`) and converted to
linear sRGB in the render loop alongside beauty (`xyzToLinearSRGB` is a linear matrix, so the
sum invariant survives conversion and averaging). The only sub-percent slack is the per-channel
`max(·,0)` gamut clamp applied per-pass vs. per-beauty, negligible for in-gamut scenes.

Opt-in photon-mapped caustic (added in `sampleFull` after `pathTraceSpectral`) is routed to
`PASS_DIFFUSE_INDIRECT` so the invariant also holds when photon mapping is enabled.

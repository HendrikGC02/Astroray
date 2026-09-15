# pkg270 research — chromatic (per-λ) volume tracking + Principled Volume emission (cite-algorithm)

Batch K, 2026-09-15. Required by CLAUDE.md §6 before the tracking / emission code.
Companion to `pkg268-volume-transport-research.md` (grey delta/ratio tracking) and
`pkg267-nanovdb-majorant-research.md`.

## 1. Chromatic extinction: which tracker?

### Papers

- **Kutz, Habel, Li, Novák 2017**, "Spectral and Decomposition Tracking for
  Rendering Heterogeneous Volumes", ACM TOG 36(4) art. 111 (SIGGRAPH 2017),
  DOI 10.1145/3072959.3073665. PDF: https://jannovak.info/publications/SDTracking/SDTracking.pdf
  - *Spectral tracking*: one free-flight sample serves all wavelengths of a
    chromatic σ_t under a single majorant; collisions are classified with
    history-aware probabilities and the per-wavelength throughput is weighted by
    the ratio of the true per-λ coefficient to the sampling probability.
  - *Decomposition tracking*: split σ_t into a homogeneous control component
    (analytic) plus a residual (tracked), cutting the number of lookups.
- **Wilkie, Nawaz, Droske, Weidlich, Hanika 2014**, "Hero Wavelength Spectral
  Sampling", CGF 33(4), DOI 10.1111/cgf.12419 — the hero-wavelength + balance
  heuristic over "which lane is the hero" that Astroray's 4-lane quad already
  implements (`SampledWavelengths::sampleUniform/sampleImportance`, pkg206).
- **Miller, Georgiev, Jarosz 2019**, "A null-scattering path integral
  formulation of light transport", TOG 38(4) — the framework pbrt-v4 uses
  (rescaled path probabilities r_u / r_l).

### Reference implementation (Apache-2.0)

- pbrt-v4 `src/pbrt/cpu/integrators.cpp` `VolPathIntegrator::Li` (medium
  sampling lambda inside `SampleT_maj`) and `VolPathIntegrator::SampleLd`
  (ratio-tracking transmittance with `r_u`/`r_l`), master 2026-09-15.
  Licence: Apache-2.0 ("pbrt is Copyright(c) 1998-2020 Matt Pharr, Wenzel Jakob,
  and Greg Humphreys… SPDX: Apache-2.0") — compatible; clean-room + cited.

Structure we mirror (verbatim semantics, notation ours):

```
per tentative collision at p (sampled at rate σ̄ = sigma_maj):
  emission:  L += β·T_maj/pdf · σ_a·L_e / avg(r_u·σ̄·T_maj/pdf)      (pdf = σ̄[0]·T_maj[0])
  pAbsorb = σ_a[0]/σ̄[0], pScatter = σ_s[0]/σ̄[0], pNull = 1−pAbsorb−pScatter  (hero lane 0)
  absorb : terminate
  scatter: β *= T_maj·σ_s/(T_maj[0]·σ_s[0]);  r_u *= same
  null   : β *= T_maj·σ_n/(T_maj[0]·σ_n[0]);  r_u *= same;  r_l *= T_maj·σ̄/(T_maj[0]·σ_n[0])
escape  : β *= T_maj/T_maj[0]; r_u *= T_maj/T_maj[0]
every radiance add: L += β·(…)/avg(r_u)   (balance heuristic over the 4 hero choices)
```

### Decision: (a) hero-wavelength spectral MIS (pbrt-v4), NOT decomposition tracking

Justification (the lead's default, confirmed after reading the quad plumbing):

1. Astroray carries a 4-lane `SampledSpectrum` throughput and a
   `SampledWavelengths` whose lane 0 is a uniformly-random member of a
   CDF-stratified set (pkg206). That is exactly the precondition of the
   Wilkie/pbrt-v4 balance heuristic: `avg(r_u)` is the marginal pdf over the
   4 equiprobable hero choices, so the estimator is unbiased for every lane.
   No new path state beyond one `SampledSpectrum r_u` (init 1, touched only in
   the bounded-medium block).
2. **Scalar majorant.** The Cycles socket formula gives, per wavelength,
   `s(λ) = color(λ)`, `a(λ) = max(1−color(λ),0)·max(1−√abs(λ),0)` with both
   colours JH-upsampled *reflectances* in (0,1) (memory
   `spectral-upsample-nonlinearity-scaled-bsdf`: upsample the colour, apply the
   formula per λ, never upsample a derived coefficient). Hence
   `s(λ)+a(λ) ≤ s + (1−s) = 1` for every λ, and `σ̄ = D·maxDensity` is an
   exact λ-independent bound. With a λ-independent σ̄, `T_maj` is identical on
   every lane and all `T_maj/T_maj[0]` factors are 1: the pbrt-v4 loop
   collapses to ratios of σ only (see the code). This is the simplest
   provably-unbiased chromatic estimator that fits the quad.
3. Decomposition tracking optimises *cost* (fewer grid lookups via an analytic
   control component); our media are nearest-voxel NanoVDB lookups on the CPU
   oracle — not the bottleneck — and it would still need the same per-λ weighting
   for the residual. Kutz's *spectral tracking* proper (history-aware
   probabilities) is a variance refinement of the same null-collision estimator;
   the pbrt-v4 hero form is its published, licence-clean, quad-shaped instance.
   Both remain available as pkg272-scope variance/perf follow-ups.

Differences from pbrt-v4 (intentional):

- `r_l` (light-path rescaled pdf) is NOT threaded: medium/surface NEE keeps
  Astroray's existing power-heuristic light↔phase MIS and multiplies by a
  per-λ ratio-tracking transmittance. With a λ-independent σ̄ the shadow-ray
  tentative collisions are λ-independent, so `Tr(λ) = Π σ_n(λ)/σ̄` is directly
  unbiased per lane and needs no wavelength MIS.
- Absorption is the analog pbrt-v4 termination (pAbsorb), replacing pkg268's
  "collide then multiply by albedo" weighting. Same expectation; volume-scene
  noise patterns change, grid-free scenes stay byte-identical (the block is
  gated on `!gridMedia_.empty()`).
- If `secondaryTerminated()` (dispersion collapsed the quad) the average is over
  lane 0 only (the other lanes carry pdf 0 and contribute nothing in `toXYZ`).

## 2. Emission along the tracked flight

- Reference: pbrt-v4 `VolPathIntegrator::Li` emission term (above) and Cycles
  `kernel/integrator/shade_volume.h` `volume_emission_integrate`
  (`∫₀ᵗ E·exp(−σ_t s) ds = E(1−e^{−σ_t t})/σ_t` per ratio-tracking step) —
  both Apache-2.0. Cycles' `coeff.emission` is **radiance per unit length**.
- Astroray form (null-scattering-consistent, no fixed-step march — §4
  divergence 5): at every tentative collision (rate σ̄), add
  `throughput · L_e(λ,p) / σ̄` where `throughput = β/avg(r_u)` (pbrt's
  `betap·σ_a·Le/avg(r_e)` with the Cycles per-length emission coefficient in
  place of `σ_a·Le`, and `T_maj/pdf = 1/σ̄`). Expected count of tentative
  collisions per unit length is σ̄, so E[Σ L_e/σ̄] = ∫ Tr·L_e dt. Unbiased.
- **Emission majorant floor.** Cycles' emission does not scale with density
  (verified in the raw source below), so a medium may emit where σ_t = 0; with
  σ̄ = 0 no tentative collision would ever be generated. When the medium is
  emissive the tracking rate is `max(σ̄, 8/diag(AABB))` — raising the majorant
  only adds null collisions (still unbiased); 8 samples per diagonal crossing
  keeps the per-sample relative deviation of the emission estimate ≈ 35 %.

## 3. Cycles Principled Volume semantics (cross-check band)

Raw source read 2026-09-15: `blender/cycles` `src/kernel/svm/closure.h`
`svm_node_principled_volume` (Apache-2.0):

```
weight  = mix_weight * object_volume_density
density = weight * max(Density, 0);  if density>0 and attr "density": density *= attr
if density > 0:  scatter weight = color*density (HG, g = Anisotropy)
                 absorption = max(1−color,0) * max(1−sqrt(Absorption Color),0)
                 extinction = (color + absorption) * density
/* emission is OUTSIDE the density branch */
if Emission Strength > 0:   emission += Emission Strength * Emission Color * weight
if Blackbody Intensity > 0:
    T = Temperature;  if attr "temperature": T *= max(attr, 0);  T = max(T, 0)
    intensity = (5.670373e-8 * 1e-6 / π) * mix(1, T⁴, Blackbody Intensity)
    if intensity > 0: emission += Blackbody Tint * intensity * rec709_to_rgb(blackbody_color_rec709(T)) * weight
```

Facts that shape pkg270:

- Emission is **independent of voxel density**; the Temperature socket is the
  *absolute* T (K) when no temperature attribute exists (mesh-bounded media,
  the #807 cabinet: T = 1400 K) and a *scale* on the attribute otherwise.
- `svm_math_blackbody_color_rec709` (`svm/math_util.h`, tables in
  `kernel/tables.h`) returns a Rec.709 colour normalised to **luminance 1**
  (e.g. its ≥12000 K constant (0.826, 0.995, 1.566) has Y = 1.000); T < 800 K
  is clamped to a fixed red constant. The magnitude is then the
  Stefan–Boltzmann bolometric radiance σT⁴/π scaled by 1e-6 (scene units),
  assigned to the *luminance* channel.

### Decision: Planck spectral shape, Cycles magnitude convention

- Spectral shape = exact Planck `B(λ,T)` per sampled wavelength (physics-first,
  §4 divergence 2) through the **existing engine Blackbody path**:
  `planck()` (`include/astroray/spectral.h`) × the photopic normalisation
  `blackbodyLuminanceNorm(T)` (`src/emission_spectrum.cpp`, pkg122; exposed in
  the header for pkg270) — i.e. the same luminance-normalised Planck the
  `EmissionSpectrum::Blackbody` lamps use.
- Magnitude = Cycles' `intensity = σ_SB·1e-6/π · mix(1, T⁴, I_bb)` applied to
  the luminance-normalised Planck, × JH-upsampled tint. So the *luminance* per
  unit length equals Cycles' exactly (same scene units, the artist-facing
  brightness the owner would compare) while the *colour* is the true Planck
  spectrum integrated by Astroray's CIE-1964 observer rather than Cycles'
  Rec.709 polynomial fit — that chromaticity difference IS the recorded
  divergence and the cross-check band (`tests/test_pkg270_blackbody_furnace.py`
  compares against the Cycles polynomial, vendored coefficient table, Apache-2.0).
- Divergences from Cycles: no 800 K clamp (Planck evaluated for any T > 0; the
  normalisation keeps the luminance at Cycles' value, so a cold body is dim via
  T⁴, not via a colour clamp); CIE-1964 10° vs Cycles' CIE-1931 fit.
- Constant emission (Emission Strength × Emission Color) is upsampled with
  `RGBIlluminantSpectrum` like every other RGB emitter in the engine.
- **Grid gating (approximation, documented):** Cycles renders a Volume object
  through a bounds mesh built around non-background voxels, so constant
  emission is confined to the active voxel neighbourhood. Our AABB is the
  active bounding box, so for *grid* media the constant-emission term is gated
  on `density(p) > 0`; blackbody emission is naturally gated by T(p) > 0.
  Mesh-bounded homogeneous media emit everywhere inside the AABB (identical to
  Cycles for a cube).

## 4. What we deliberately do NOT take

- pbrt-v4's `r_l` bookkeeping and its light-sampler MIS (Astroray keeps its
  power-heuristic NEE); pbrt's `SampleT_maj` DDA majorant iterator (pkg268 uses
  one global bound — pkg269/272 refinement).
- Cycles' per-step analytic emission integral (`volume_emission_integrate`)
  — it belongs to Cycles' fixed-step ratio-tracking march; we accumulate at
  null-collision vertices instead.
- Cycles' RGB blackbody polynomial as the *estimator* (it is the cross-check
  band only), and its T < 800 K colour clamp.

## 5. Integration plan

- `include/astroray/volume/volume_emission.h` — `VolumeEmission` params +
  per-λ evaluator (constant + Planck), Cycles intensity helper.
- `include/astroray/volume/principled_volume.h` — emission/blackbody sockets;
  per-λ coefficient evaluator (Cycles formula on JH-upsampled colours).
- `include/astroray/volume/volume_transport.h` — `spectralTrack` (pbrt-v4
  hero-MIS null-collision loop with emission), `ratioTrackingTransmittanceSpectral`.
- `include/raytracer.h` — bounded-medium block uses the spectral tracker and a
  path-state `r_u`; medium NEE + surface-NEE attenuation use the spectral
  ratio tracker; emission → PASS_EMISSION / `<firstCat>_INDIRECT`.
- `src/volume/grid_medium.cpp` — `temperatureWorld(p)`; `module/blender_module.cpp`
  — emission/blackbody params + temperature bbox; `blender_addon/volume_export.py`
  + `__init__.py` — socket lowering.
- Tests: `tests/test_pkg270_blackbody_furnace.py`,
  `tests/test_pkg270_spectral_extinction.py`; #807 cabinet A/B.

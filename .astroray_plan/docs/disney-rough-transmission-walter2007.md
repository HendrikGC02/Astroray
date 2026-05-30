# Disney rough-glass transmission — energy-loss fix (Walter 2007)

**Bug (was Bug 2 in `glass-dark-energy-bug-2026-05-30.md`):** Disney/Principled glass
(`transmission=1`) at `roughness ≥ 0.05` rendered ~70% too dark — white-furnace ~0.30
vs the required ~1.0, flat across roughness, stepping on exactly at
`kDeltaTransmissionRoughness = 0.03`.

## Reference
- **Walter, Marschner, Li, Torrance 2007, "Microfacet Models for Refraction through
  Rough Surfaces", EGSR.** https://www.graphics.cornell.edu/~bjw/microfacetbsdf.pdf
  - Eq. 21 rough BTDF; Eq. 34 the GGX masking-shadowing `G1`; §5.3 / Eq. 38–41 the
    NDF-importance-sampling estimator weight `G(i,o,m)·|o·m| / (|o·n|·|m·n|)` where `G`
    is the **true Smith G ∈ [0,1]** (product of two `G1 ∈ [0,1]`).
- Cross-checked against Cycles `intern/cycles/kernel/closure/bsdf_microfacet.h`
  (Apache-2.0) and PBRT-v4 `DielectricBxDF`.

## Root cause
`plugins/materials/disney.cpp::smithG_GGX(x,α) = 1/(x + sqrt(α²+x²(1−α²)))` is the
**combined visibility** form, i.e. `G1(x)/(2x)` — it folds the *reflection* BRDF's
`1/(4·cosO·cosI)` into the masking term (which is why the reflection lobe is written
`spec = D·F·Gs` with no explicit `/(4·cosO·cosI)` at `disney.cpp:300`).

`roughTransmissionEval` used `smithG_GGX(cosO)·smithG_GGX(cosI)` =
`G1(cosO)·G1(cosI) / (4·cosO·cosI)`. The throughput reduces to (η², (1−F), and the
Jacobian denom² all cancel against the pdf):

```
f/pdf = G · |HdotO| / (|cosO|·NdotH)        with G = G1·G1/(4 cosO cosI)
      → near normal at low roughness: ≈ 0.25   (the spurious 1/(4 cosO cosI))
```

That constant ≈0.25 deficit, independent of roughness and switching on at the 0.03
delta threshold, is the observed fingerprint.

## Fix
Add a true Smith `smithG1_GGX(x,α) = 2x/(x + sqrt(α²+x²(1−α²)))` (= `2x·smithG_GGX`,
∈[0,1]) and use it **only** in the rough-transmission eval (`disney.cpp` +
`include/astroray/gpu_materials.h::gpu_disney_roughTransmissionEval`). `…Pdf` carries no
G and is unchanged, so the weight becomes the correct Walter §5.3 estimator
`G1·G1·|HdotO|/(|cosO|·NdotH) → ~1`. The reflection/clearcoat lobes keep the combined
`smithG_GGX` (correct there). The GPU dielectric-transmission **closure** (rough,
roughness>0.03) is converted to `GMAT_DISNEY` (`gpu_materials.h:787`) and routes through
the same `gpu_disney_roughTransmissionEval`, so the single GPU edit covers both paths.

Smooth (R=0) glass is unaffected (delta path, furnaces ~0.97). This is independent of
the 2026-05-30 `rec.frontFace` enter/exit fix.

## Acceptance
`tests/test_disney_rough_glass_furnace.py` + `tests/test_dielectric_glass_furnace.py`.

---

## STATUS UPDATE — 2026-05-30 (session 2), measured on RTX

The `smithG1` change above is correct but was **not sufficient**, and a separate,
larger GPU bug was found and fixed. Measured white-furnace (ior 1.5, depth 32):

| roughness | CPU  | GPU  |
|-----------|------|------|
| 0.0, 0.03 | 0.969| 0.991|  ← smooth: energy-conserving ✔
| 0.05      | 0.811| 0.803|
| 0.1       | 0.878| 0.862|
| 0.3       | 0.355| 0.307|
| 0.6       | 0.351| 0.382|
| 1.0       | 0.562| 0.674|

### FIXED — GPU smooth-glass eta² clamp (all GPU glass, scaling with IOR)
A plain `dielectric` material **lowers to `GMAT_CLOSURE_GRAPH`** on the GPU (the
closure-graph check in `scene_upload.cu` runs before the gpuType dispatch), and the
disney rough glass routes through the same graph. The delta refraction
`f = baseColor·eta²` was converted to a spectrum via
`gpu_rgbToSampledSpectrum(..., GSPEC_RGB_ALBEDO)`, whose JH upsampler **clamps rgb to
[0,1]**. The exit `eta²` (2.25 @ ior 1.5, 4.0 @ ior 2.0) was clipped to 1.0, so the
enter (0.44) / exit (2.25) radiance-transport factors no longer cancelled — the GPU
furnace lost energy **scaling with IOR**: 0.991 @ 1.0 → 0.705 @ 1.5 → 0.604 @ 2.0
(CPU stayed ~0.985 because CPU `dielectric.cpp:72` sets `f_spectral = tintSpec·eta²`
directly, never through the albedo upsampler). Fix: in `gpu_material_sample_spectral`
factor any **>1** delta-lobe magnitude out as a flat spectral scalar and upsample only
the normalized tint. GPU furnace → 0.991 flat across IOR; GPU now tracks CPU at all
roughness. This is the dominant glass-energy bug and affects every GPU glass render.

### OPEN RESIDUAL — rough microfacet transmission (CPU **and** GPU, equal)
After the eta² fix the GPU tracks the CPU, so the remaining rough loss is a **shared
algorithm bug**, non-monotonic in roughness (table above). The bespoke
NDF-sampling microfacet-transmission path mixes the lobe-selection probabilities
(`transmission_`, `fresnel`) into `f`/`pdf` inconsistently between the microfacet lobe
(`roughTransmissionPdf` already folds in `transmission·(1−F)`) and the smooth
fallthrough (`disney.cpp:415,421` use `fresnel·transmission_`). The correct fix is a
**Heitz 2018 VNDF** rewrite of `sampleGgxMicroNormal` + `roughTransmission{Pdf,Eval}`
(sample visible normals; pdf includes `G1(wo)`; weight collapses to `G1(wi)`),
mirroring Cycles `bsdf_microfacet.h` `bsdf_microfacet_ggx_sample` (Apache-2.0), with
Turquin 2019 multiscatter energy compensation if VNDF alone undershoots at high R.
Tracked by the **xfail** `test_disney_rough_glass_furnace_energy_cpu`.
- Heitz 2018, "Sampling the GGX Distribution of Visible Normals", JCGT 7(4).
  https://jcgt.org/published/0007/04/01/

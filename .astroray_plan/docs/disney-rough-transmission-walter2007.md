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
`tests/test_disney_rough_glass_furnace.py`: white-furnace disney glass centre ∈
[0.95,1.02], flat for R ∈ {0,0.03,0.05,0.1,0.3,0.6,1.0}; deterministic across spp;
CPU↔GPU both energy-conserving.

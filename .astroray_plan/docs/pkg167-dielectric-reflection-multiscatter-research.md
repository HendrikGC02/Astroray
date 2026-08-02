# pkg167 — Disney dielectric reflection-lobe multi-scatter compensation: research + decisions

## Problem restatement

pkg150's STOP proved the smooth-mirror delta fallback in the Disney dielectric
`sample()` was an *unintentional energy patch* for missing reflection-lobe
multi-scatter energy. Removing it (the pbrt-v4-faithful dead-sample fix)
regresses the white furnace at high roughness (CPU r=1.0 0.997 → 0.788; GPU
1.000 → 0.918). The correct resolution is explicit multiplicative multi-scatter
compensation on the reflection lobe, then remove the hack.

## Citations (CLAUDE.md §6)

- **Kulla & Conty 2017, "Revisiting Physically Based Shading at Imageworks"**
  (SIGGRAPH 2017 Courses, DOI 10.1145/3084873.3084893) — the `E(μ)`-based
  compensation family. Net single-scatter multiplier
  `1 + Fms·(1−E)/E`, `Fms = Fss·Eavg/(1 − Fss·(1−Eavg))`.
- **Turquin 2019, "Practical multiple scattering compensation for microfacet
  models"** (ILM Technical Report,
  https://blog.selfshadow.com/publications/turquin/ms_comp_final.pdf) — the
  dielectric treatment: the directional albedo `E` used for a rough dielectric
  is **η-dependent** (unlike the metal case), and the compensation is applied to
  the whole rough-dielectric closure. This is the paper the in-repo glass tables
  descend from.
- **In-repo pattern (mirrored, not reinvented):**
  - `astroray::ggxDarkeningChannel` (`include/astroray/energy_compensation.h`)
    — the net `1 + Fms·(1−E)/E` factor, pkg60/pkg160.
  - `ggxGlassCompensationFactor` / `gpu_ggxGlassCompensationFactor`
    (`disney.cpp` / `gpu_glass_tables.cuh`) — the η-dependent glass
    factor built from the pkg151 Cycles glass tables
    (`table_ggx_glass_E`/`_Eavg`/`_inv_E`/`_inv_Eavg`, Cycles
    `intern/cycles/scene/shader.tables`, Apache-2.0; formula from
    `intern/cycles/kernel/closure/bsdf_microfacet.h::microfacet_ggx_preserve_energy`,
    BSD-3-Clause).
- **Cycles combined-closure fact (the load-bearing one):** Cycles compensates
  the **combined** glass closure — Fresnel-weighted reflection+transmission
  single-scatter albedo — with ONE factor (`CLOSURE_BSDF_MICROFACET_GGX_GLASS_ID`
  in `microfacet_ggx_preserve_energy`). Recorded already in
  `.astroray_plan/docs/pkg151-cycles-glass-tables-research.md` §"The function to
  mirror" and Caveat 1.

## η-dependence decision: reuse the pkg151 glass tables (table, not new analytic fit)

The dielectric `E` depends on IOR. The in-repo `ggxGlassE(roughness, mu, ior)`
already encodes exactly `E(μ, roughness, η)` for the rough dielectric closure
(the Cycles 16³ table with the `z = sqrt(|ior−1|/(ior+1))` axis remap and the
`_inv_` swap for ior<1). **No new LUT, no from-scratch regeneration** (spec
non-goal, CLAUDE.md §6). The reflection lobe reuses the identical
`ggxGlassCompensationFactor(etap, μ)` the transmission lobe already uses.

## Composition rule vs the existing `ggxGlassCompensationFactor` (no double-compensation)

pkg151 applied `ggxGlassCompensationFactor` to `roughTransmissionEval`'s return
value ONLY — the transmission half of the split closure (Caveat 1). That leaves
the closure under-compensated by exactly the reflection half's multi-scatter
deficit:

```
single-scatter:      R_ss + T_ss = E   (< 1, energy lost to shadowing)
pkg151 (trans only): R_ss + T_ss/E     (< 1 by R_ss·(1/E − 1))  ← the deficit
pkg167 (both lobes): (R_ss + T_ss)/E = E/E = 1   ← Cycles combined-closure result
```

pkg167 applies **the same** `ggxGlassCompensationFactor(etap, |cosO|)` to the
reflection lobe (`roughReflectionEval`), mirroring the transmission twin exactly
(disney.cpp:384 / gpu_materials.h:811). The two lobes therefore carry the SAME
η-dependent factor — this IS the combined-closure compensation, split across the
two sampled lobes. They cannot double-compensate because each lobe's raw
single-scatter throughput is multiplied by the factor exactly once.

Interaction with `ggxCompensationFactor(F0)` (the metal/opaque-specular term,
disney.cpp:663 / gpu_materials.h:999): for a transmissive dielectric `F0 = Cspec0
≈ specular·0.08 ≈ 0.04`, so that factor evaluates to `1 + Fms·(1−E)/E` with
`Fss≈0.04` → **≤1.004** (<0.5%). It is left in place unchanged (it correctly
compensates the opaque-specular blend fraction `(1−dielectricWeight)`); the
<0.5% residual it adds to the reflection blend fraction is negligible and does
not constitute meaningful double-compensation. Documented here per the spec's
composition-rule requirement.

## Spectral handling (pkg163 class rule)

The dielectric reflection lobe is **achromatic**: `roughReflectionEval` returns
`Vec3(fr)` (bare Fresnel reflectance, no baseColor tint — pkg138), and the glass
factor is a scalar from `fresnelDielectricFss(etap)`. No per-λ chromatic term is
introduced, so pkg163's per-wavelength upsample handling does not apply here
(there is no reflectance asset colour to upsample). `evalSpectral` continues to
upsample `eval()`'s final RGB (disney.cpp:704). Recorded per the acceptance
criterion.

## Throughput-only (chi² safety)

The factor multiplies eval() throughput ONLY — `roughReflectionPdf`,
`microfacetReflectionPdf`, and `sampleGgxVNDF` are untouched, exactly like the
pkg151 transmission application. So f/pdf shape is unchanged and chi² cannot
regress from this term. (chi² caveat: pkg150's ires=4 runs are a quadrature
artifact; any chi² reading must use ires≥8 — not gated here.)

## pkg129 relationship

pkg129 owns the **metal** reflection-lobe Turquin-table unification. The
dielectric reflection lobe here reuses the pkg151 *glass* table family, not a
metal `E` table — so there is no shared loader to unify with pkg129. No scope
overlap; pkg129 not blocked.

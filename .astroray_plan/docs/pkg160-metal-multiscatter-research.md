# pkg160 — plain `metal` GGX multi-scatter energy compensation

**Package:** pkg160 (PR #527)
**Date:** 2026-07-26
**Rule:** CLAUDE.md §6 — cite, borrow, verify. Nothing here is derived; the
implementation is the one this repo already ships in `plugins/materials/disney.cpp`.

---

## What was replaced

`MetalPlugin::eval` / `evalSpectral` (`plugins/materials/metal.cpp`) returned

```
singleScatter = F * D * G / (4*NdotV + 0.001)
Fms           = ggxMultiScatterCompensation(NdotV, NdotL, roughness)   // raytracer.h
msWeight      = roughness * (2 - roughness)
multiScatter  = albedo * (Fms * msWeight * 1.3)
return singleScatter + multiScatter
```

Three independent defects, all confirmed by measurement:

1. **Wrong table.** `ggxMultiScatterCompensation` read
   `GGXEnergyCompensationLUT` (`include/raytracer.h`), computed at runtime by
   MC integration with **256 uniform-hemisphere samples per cell**. Uniform
   hemisphere sampling cannot resolve a narrow GGX lobe, so `E -> 0` as
   roughness -> 0. Since `Fms = (1-Ewo)(1-Ewi)/(pi*max(1-Eavg, 1e-4))`, that
   pinned `Fms` near its `1/pi` ceiling exactly where multiple scattering
   should vanish. Measured at roughness 0.15, mu 0.5: runtime `E = 0.040669`
   vs the shipped Cycles table's `0.998543` (**24.6x**), and **1030x** in the
   downstream `Fms` (0.307206 vs 2.98e-4).
2. **Missing cosine.** `AGENTS.md:87` — `Material::eval()` returns
   `brdf * NdotL`. `singleScatter` bakes the cosine in (the `NdotL` cancels
   against the Cook-Torrance `1/(4*NdotV*NdotL)` denominator); the additive
   term carried no `NdotL` at all.
3. **Invented weight.** `roughness*(2-roughness)` and `* 1.3f` appear in no
   publication. CLAUDE.md §6 forbids exactly this.

Combined effect, measured with a white furnace (albedo = 1, uniform
environment radiance 1, convex sphere filling the frame, linear output):
the CPU conductor reflected **1.25x-1.77x** the incident radiance — energy
creation, not just a colour shift.

## What replaced it

`disney.cpp:97` `ggxCompensationFactor` + `disney.cpp:653`
`spec *= ggxCompensationFactor(F0, roughness_, NdotV)` — shipped since
pkg60, refit in pkg145, GPU-mirrored in pkg152/PR #523. Borrowed verbatim.

### Sources

| | |
|---|---|
| **Paper** | Christopher Kulla, Alejandro Conty, *"Revisiting Physically Based Shading at Imageworks"*, ACM SIGGRAPH 2017 Courses (*Physically Based Shading in Theory and Practice*). DOI **10.1145/3084873.3084893**. Slides: https://blog.selfshadow.com/publications/s2017-shading-course/imageworks/s2017_pbs_imageworks_slides_v2.pdf |
| **Reference impl.** | Blender Cycles `intern/cycles/kernel/closure/bsdf_microfacet.h`, `microfacet_ggx_preserve_energy` (`:389-436`). **SPDX-License-Identifier: BSD-3-Clause**, © Sony Pictures Imageworks and Blender Foundation. Permissive, MIT-compatible; attribution preserved in the code comments. |
| **Table data** | Cycles `intern/cycles/scene/shader.tables` `table_ggx_E` (32x32) / `table_ggx_Eavg` (32), **Apache-2.0**, © Blender Foundation. Already extracted into `data/disney_compensation/ggx_E.bin` / `ggx_Eavg.bin` by pkg60; not re-extracted by this package. |

### Math reproduced

```
missing_factor = (1 - E) / E
energy_scale   = 1 / E
Fms            = Fss * Eavg / (1 - Fss * (1 - Eavg))
darkening      = (1 + Fms * missing_factor) / energy_scale
```

Cycles applies `energy_scale` to eval/sample and `darkening` to the closure
weight; the **net** factor on the single-scatter lobe is their product,
`1 + Fms * (1 - E) / E`. That net form is what
`astroray::ggxDarkeningChannel` (`include/astroray/energy_compensation.h`)
returns, and what its device twin `gpu_ggxDarkeningChannel`
(`include/astroray/gpu_ggx_tables.cuh`) returns.

Multiplicative-on-single-scatter fixes all three defects at once: it reads the
shipped table, it inherits `singleScatter`'s cosine, and it has no free
parameters.

### The `Fss` choice for a conductor

Cycles derives `Fss` per Fresnel model:
- `bsdf_microfacet_setup_fresnel_conductor` -> `fresnel_conductor_Fss(ior)`
  (hemispherical average of the complex-IOR Fresnel);
- `bsdf_microfacet_setup_fresnel_generalized_schlick` ->
  `Fss = mix(f0, f90, s)`, with `s = 1/21` for the hardcoded exponent-5
  Schlick — i.e. the exact hemispherical average `integral F_schlick(mu) 2mu dmu`.

Astroray's `metal` uses Schlick with `F0 = albedo`, `F90 = 1`, so the
Cycles-exact value would be `albedo + (1 - albedo)/21`.

**We pass `Fss = albedo_` instead**, matching `disney.cpp:653`'s
`ggxCompensationFactor(F0, ...)`. Reasons:

1. **One compensation for both metal paths.** Disney at `metallic = 1` has
   `F0 = Cspec0*(1-metallic) + Cdlin*metallic = base colour`
   (`disney.cpp:530`). Plain `metal` and Disney-metal are the two halves of the
   pkg158 reconciliation; giving them different `Fss` would re-split them.
   Measured confirmation: `test_glossy_matches_principled_metallic_roughness`
   centre-crop MSE fell **0.02474 -> 0.00353** (7x closer) with `Fss = albedo`.
2. **Second-order.** `mix(F0, 1, 1/21)` is +0.4% over `F0` at albedo 0.92 and
   +9% at 0.35, and it enters through `Fms` which is itself a correction term.
3. **Not unilateral.** Adopting the Cycles-exact `Fss` would have to be done
   for `disney.cpp` at the same time, which is outside pkg160's scope.

Recorded here so a later package can adopt `mix(f0, f90, 1/21)` for both
plugins in one move if it wants to.

## Known residual (NOT fixed here, and not a pkg160 goal)

Post-fix white furnace measures **0.81-0.88**, i.e. the compensated lobe still
loses 12-19%. Expected: the shipped `ggx_E` was baked by Cycles for
height-correlated Smith masking with VNDF sampling, while Astroray's conductor
uses the **UE4/Karis remapped Smith-Schlick** form `k = (roughness+1)^2/8` and
**D-based (non-VNDF)** sampling, so `E_astroray != E_cycles` and the
compensation is approximate for this lobe. This is the same approximation
`disney.cpp` has carried since pkg60. Closing it properly is **pkg129**
(Turquin multi-scatter LUTs), which would re-bake `E` for the lobes Astroray
actually uses.

## Verification

CPU, MinGW `g++ -O2`, `-DASTRORAY_ENABLE_CUDA=OFF`, this branch.

**White furnace (albedo=1, env=1, linear, 32x32 @ 512spp, depth 8, green channel):**

| roughness | before | after |
|---|---|---|
| 0.05 | 1.0007 | 1.0007 (near-delta path, untouched — byte-identical) |
| 0.15 | 1.6434 | 0.8823 |
| 0.30 | 1.2530 | 0.8511 |
| 0.60 | 1.4069 | 0.8092 |
| 0.90 | 1.7690 | 0.8802 |

**Gold conductor `[0.92, 0.78, 0.35]` in a `[0.35, 0.45, 0.60]` environment
(48x48 @ 256spp, depth 4, linear, full-frame sphere), R-channel mean:**

| roughness | before | after | after/before |
|---|---|---|---|
| 0.05 | 0.332707 | 0.332707 | 1.000 |
| 0.15 | 0.551169 | 0.294649 | 0.535 |
| 0.30 | 0.424385 | 0.284630 | 0.671 |
| 0.60 | 0.471202 | 0.265420 | 0.563 |
| 0.90 | 0.590134 | 0.273447 | 0.463 |

At roughness 0.9 the post-fix channel ratios normalised to R are
`1 / 0.878 / 0.373` against the albedo's `1 / 0.848 / 0.380` — a rough
conductor in a uniform environment now returns approximately its own albedo
tint. Pre-fix it returned `1 / 1.037 / 0.613`, a visible hue shift caused by
the cosine-free additive floor.

**Why the existing furnace guards never caught the 1.77x.**
`tests/base_helpers.py::render_image` defaults to `apply_gamma=True`, and the
gamma path clamps to `[0, 1]`. A linear 1.77 reads back as 0.998. Measured:
`test_metal_furnace_energy_above_threshold_all_roughness` recorded 0.9978 at
roughness 1.0 pre-fix (threshold `> 0.78`) while the same configuration was
creating 1.77x the incident energy in linear space. The pkg160 furnace test
therefore renders with `applyGamma=False` (memory
`gamma-vs-linear-comparison-artifact`).

## Second known residual — CPU-spectral vs GPU-RGB compensation (found by the HW gate)

Measured on RTX 5070 Ti, 2026-07-26, by the first hardware run of
`tests/test_pkg160_plain_metal_gpu_cpu_parity.py`: 31/32 assertions inside
`[0.95, 1.05]`; roughness 0.9 channel B = **1.0722**.

`MetalPlugin::evalSpectral` applies the darkening **per wavelength**, with
`Fss = albedo_spec_.sample(lambdas)` (the Jakob-Hanika upsample of the albedo
evaluated at the four hero wavelengths). `gpu_metal_eval` applies it **per RGB
channel** from `mat.baseColor`, and `gpu_material_eval_spectral` upsamples the
product afterwards. Upsampling is not linear, so

```
upsample( f_rgb * darken(f_rgb) )  !=  upsample(f_rgb) * darken(upsample(f_rgb))
```

except for a flat (achromatic) spectrum. The same asymmetry already existed for
the Fresnel term in these two functions; pkg160 pushed a second,
roughness-amplified factor through the same seam, which is what made it
measurable.

Confirmed experimentally rather than assumed (team-lead, three isolations):

1. **Roughness 0.05 is at parity** (0.9977–1.0000) — the near-delta branch,
   where the compensation is inert. A missing or mis-ported term would diverge
   there too, so the port itself is correct.
2. **Neutral albedo collapses the per-channel spread 25x** (0.0589 -> 0.0023).
3. **Decisive:** neutral `[0.35,0.35,0.35]` gives B = 1.0074, chromatic
   `[0.92,0.78,0.35]` — the *same* B — gives B = 1.0743. Ten times the
   divergence with the only variable being whether the OTHER channels differ.
   Only spectral upsampling can produce that.

Amplifier is camera framing, not the background: far camera measures
1.0052/1.0025/1.0056, the gate's close 60-degree grazing-dominated framing
measures 1.0257/1.0154/1.0743; the chromatic background contributes ~0.3%.

Not fixed in pkg160 (it is a whole-pipeline question about where RGB->spectral
upsampling sits relative to per-lobe scalar factors, and it applies to Disney's
compensation and Fresnel too, not just metal). Handled in-tree by an
owner-approved documented exception: `RATIO_HIGH_ROUGHNESS_0_9 = 1.10`, floor
unchanged at 0.95, 2.6% headroom over the observed 1.0722 so a genuine
regression still fails. The architect filed a follow-up package for the
mismatch itself.

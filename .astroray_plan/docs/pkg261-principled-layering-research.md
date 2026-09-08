# pkg261 — Principled specular-layer albedo research note (cite-algorithm)

Date: 2026-09-08. Lane: `fix/pkg261-principled-rough-diffuse`.
Purpose: "find the number before the formula" — identify the term in Astroray's
Principled diffuse/specular layering that disagrees with Cycles and drives the
~6–7 % ground-diffuse deficit at specular roughness 0.85 (pkg258 diagnosis #756).

## 1. What Cycles computes for the specular layer albedo

Cycles layers the diffuse (and everything below the specular) by
`closure_layering_weight`, fed by `bsdf_albedo` → `bsdf_microfacet_estimate_albedo`.

`intern/cycles/kernel/closure/bsdf_util.h` (BSD-3-Clause), lines 248-251:

```c
ccl_device_inline Spectrum closure_layering_weight(const Spectrum layer_albedo,
                                                   const Spectrum weight) {
  return weight * saturatef(1.0f - reduce_max(safe_divide_color(layer_albedo, weight)));
}
```

`intern/cycles/kernel/closure/bsdf.h` line 690, `bsdf_albedo`:
`albedo = sc->weight * bsdf_microfacet_estimate_albedo(...)` for microfacet closures.

`intern/cycles/kernel/closure/bsdf_microfacet.h` line 498,
`bsdf_microfacet_estimate_albedo`, GENERALIZED_SCHLICK branch (which is how the
Principled dielectric specular layer is set up — exponent = -ior < 0):

```c
const float rough = sqrtf(sqrtf(bsdf->alpha_x * bsdf->alpha_y));   // = perceptual roughness
const float z = sqrtf(fabsf((bsdf->ior - 1.0f) / (bsdf->ior + 1.0f)));
s = lookup_table_read_3D(kg, rough, cos_NI, z, kernel_data.tables.ggx_gen_schlick_ior_s, 16,16,16);
const Spectrum F = mix(fresnel->f0, fresnel->f90, s);
const Spectrum reflectance = F * fresnel->reflection_tint * float(eval_reflection);
return reflectance;   // ( + transmittance, zero for the opaque dielectric specular )
```

Key facts about Cycles' estimate:
- The layering albedo is `mix(f0, f90, s)` where `s` comes from the precomputed
  3-D table `ggx_gen_schlick_ior_s` indexed by (perceptual roughness, cos of the
  **view** angle `cos_NI`, and `z = sqrt(|ior-1|/(ior+1)|)`). `s` is the
  lobe-averaged Schlick blend factor fit to the true directional albedo of the
  rough dielectric, so it already folds in both the GGX masking energy loss and
  the Fresnel averaging over the visible-normal distribution.
- **No `microfacet_ggx_preserve_energy` darkening is applied to the layering
  albedo.** `estimate_albedo` never calls the multi-scatter compensation; that
  darkening (`bsdf_microfacet.h:389-436`) is applied only to the specular lobe's
  own `bsdf->weight`, not to the value handed to `closure_layering_weight`.
- Because `s ∈ [0,1]`, Cycles' estimate is clamped to `[f0, 1]` — it cannot dip
  below f0 even where the true single-scatter albedo does (see §3).

## 2. What Astroray computes today

`plugins/materials/principled.cpp`:
- Specular layer site (~L965-966): `specAlb = ggxDirectionalAlbedo(Fview, roughness_, nv); weight = layeringWeightAfter(weight, specAlb);`
- `Fview` (~L953) is the **view-angle** dielectric Fresnel: with default
  specular_tint=1, `Fview = f0 + (1-f0)·generalizedSchlickS(nv,ior) = fresnelDielectricCos(nv,ior)` exactly.
- `ggxDirectionalAlbedo(Fview, r, mu)` (~L638) returns per channel
  `E(r,mu) · clamp(Fview) · ggxDarkeningChannel(clamp(Fview), E, Eavg)`.
- `layeringWeightAfter` (~L663) uses the per-channel `weight·(1 - min(albedo,0.999))`
  form (equivalent to Cycles' scalar-max form for the achromatic dielectric case).

So Astroray's layering albedo = `E(r,mu) · Fview(mu) · darkening`, i.e. it
multiplies the F=1 GGX directional albedo `E` by the Fresnel evaluated at the
**single view/reflection direction**, plus a multi-scatter darkening boost.

Astroray ships `ggx_E`/`ggx_Eavg` (`data/disney_compensation/`, extracted from
Cycles) but **not** the `ggx_gen_schlick_ior_s` table Cycles uses here.

## 3. The numeric diff (the disagreeing term)

Independent oracle: VNDF-importance-sampled Monte-Carlo directional-hemispherical
reflectance of a single-scatter GGX lobe with the exact dielectric Fresnel
(IOR 1.5, f0 = 0.04), 300 000 samples per cell (Heitz 2018 VNDF; Fresnel-weighted
`G2/G1` estimator). Script + reproducible output:
`test_results/2026-09-08-pkg261/mc_vndf.py`.

Columns: `MC` = true single-scatter albedo (the quantity Cycles' `s`-table is fit
to). `Astr` = Astroray `E·Fview·darkening`. `A_noDark` = Astroray without the
darkening boost. `Astr/MC` = Astroray's over/under-estimate factor.

```
 r     mu    MC        Astr      Astr/MC  A_noDark
 0.30  1.00  0.0397    0.0396    0.998    0.0396
 0.30  0.80  0.0443    0.0434    0.980    0.0433
 0.30  0.50  0.0867    0.0871    1.005    0.0869
 0.30  0.20  0.2480    0.3195    1.289    0.3098
 0.50  1.00  0.0370    0.0367    0.992    0.0366
 0.50  0.80  0.0414    0.0395    0.955    0.0394
 0.50  0.50  0.0669    0.0775    1.158    0.0765
 0.50  0.20  0.1341    0.3035    2.264    0.2875
 0.85  1.00  0.0200    0.0199    0.997    0.0194
 0.85  0.80  0.0230    0.0230    1.000    0.0224
 0.85  0.50  0.0325    0.0535    1.649    0.0516
 0.85  0.20  0.0574    0.2660    4.636    0.2454
 1.00  1.00  0.0127    0.0127    1.003    0.0123
 1.00  0.80  0.0155    0.0159    1.029    0.0154
 1.00  0.50  0.0234    0.0421    1.801    0.0402
 1.00  0.20  0.0435    0.2386    5.483    0.2175
```

`ggx_E` table values (for reference), interpolated as the engine does:
roughness → E(mu=1.0)/E(mu=0.5)/E(mu=0.2), Eavg:
```
0.30  0.9905 / 0.9747 / 0.9143   Eavg 0.9763
0.50  0.9153 / 0.8572 / 0.8484   Eavg 0.8820
0.85  0.4857 / 0.5785 / 0.7240   Eavg 0.5527
1.00  0.3069 / 0.4508 / 0.6419   Eavg 0.4091
```

### Findings

1. **The darkening term is not the defect.** `Astr` vs `A_noDark` differ by
   ≤ ~3 % everywhere (for a low-f0 dielectric `ggxDarkeningChannel ≈ 1.00–1.02`).
   Dropping it — the spec's hypothesised fix — changes nothing material. The
   diagnosis's "E·F·darkening" hypothesis names the wrong sub-term.

2. **The defect is the view-angle Fresnel multiplied into the albedo at grazing.**
   At mu ≥ 0.8, Astroray's `E·Fview` matches the true MC albedo within ~2–3 % at
   *every* roughness (that is why the pkg258 diagnosis saw roughness 0 match and
   the *normal-incidence* case behave). At grazing (mu ≤ 0.5) Astroray
   overestimates the specular albedo by 1.2–5.5×, growing with both roughness and
   grazing angle, because `Fview(mu)` → 1 as mu → 0 while the true rough-lobe
   albedo averages the Fresnel over half-vectors that are mostly *not* grazing.

3. **Render direction.** `closure_layering_weight` attenuates the diffuse layer
   below by (1 − specular albedo). Astroray's grazing overestimate therefore
   over-attenuates the diffuse layer exactly for grazing-viewed rough surfaces —
   the pkg258 near-ground band (bottom rows of the frame = nearest, most grazing
   ground), which is where the diagnosis measured the worst deficit
   (row-band ratios 0.84 in the mid/near ground, 1.00 at the sky). Consistent
   in sign and locus with Astroray rendering darker than Cycles there.

4. **Cycles is itself a clamped approximation.** Because `s ∈ [0,1]`, Cycles'
   `mix(f0,1,s)` cannot fall below f0, so at high roughness *normal* incidence
   Cycles returns ≈ f0 = 0.04 vs the true MC 0.020 — a mild over-attenuation of
   the diffuse at normal viewing. Matching Cycles (parity target) rather than the
   raw MC therefore *slightly darkens* the normal-incidence diffuse while
   correcting the much larger grazing error; the ground ROI is grazing-dominated,
   so the net is the required brightening there.

## 4. Fix target and open scope question

Fix target (measured, not hypothesised): the specular-layer albedo handed to
`closure_layering_weight` — specifically its use of the **view-angle** Fresnel.
The coat and sheen layering sites (~L846, L865-866) share the same
`ggxDirectionalAlbedo`/`Fview` construction and would need the same correction.

**Scope fork surfaced to the lead (see PR/handoff):** the faithful Cycles fix is
to port `bsdf_microfacet_estimate_albedo` for the dielectric, which requires the
`ggx_gen_schlick_ior_s` 16³ LUT that Astroray does not ship — a new data table
plus its GPU upload path and the closure-graph mirror, larger than the spec's
implied ~30-line "drop the darkening" edit and touching a new device table. The
alternative is a smaller cited closed-form for the rough-dielectric directional
albedo that reuses the existing `ggx_E` table but replaces the view-angle Fresnel
with a lobe-consistent average. This is a genuine design fork with real
tradeoffs (parity fidelity + GPU-table risk vs. smaller surgical change), so it
is raised before sinking the build time.

## Citations
- Cycles `bsdf_util.h:248` `closure_layering_weight`; `bsdf.h:690` `bsdf_albedo`;
  `bsdf_microfacet.h:498` `bsdf_microfacet_estimate_albedo`,
  `bsdf_microfacet.h:389` `microfacet_ggx_preserve_energy` (all BSD-3-Clause,
  blender/cycles `main`, fetched 2026-09-08).
- Heitz 2018, "Sampling the GGX Distribution of Visible Normals", JCGT — the VNDF
  sampler used by the oracle.
- Kulla & Conty 2017 — the multi-scatter compensation (shown here not to be the defect).

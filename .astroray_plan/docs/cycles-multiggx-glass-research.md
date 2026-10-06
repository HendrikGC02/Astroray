# Cycles 5.2 MULTI_GGX rough glass — port notes (lane i16, 2026-10-06)

Owner decision 2026-10-06: Principled and Glass BSDF rough glass default to Cycles 5.2's
MULTI_GGX on CPU and GPU; the pkg265 Heitz walk stays as the opt-in CPU model
(`rough_glass_walk` = 1). Background: `pkg265-phase3-method-choice.md`.

## Sources (Blender tag v5.2.0, fetched 2026-10-06)

| What | File | Licence |
|---|---|---|
| `microfacet_ggx_preserve_energy` (glass branch, `energy_scale`, darkening) | `intern/cycles/kernel/closure/bsdf_microfacet.h` | BSD-3-Clause |
| `bsdf_microfacet_eval` / `_sample` (D, λ, `pdf_reflect`, Jacobians) | same | BSD-3-Clause |
| `bsdf_microfacet_setup_fresnel_generalized_schlick` (Fss = transmission tint) | same | BSD-3-Clause |
| `lookup_table_read{,_2D,_3D}` | `intern/cycles/kernel/util/lookup_table.h` | Apache-2.0 |
| glass E table generation (`precompute_ggx_glass_E`, `ior_parametrization`) | `intern/cycles/app/cycles_precompute.cpp` | Apache-2.0 |
| Principled / Glass BSDF closure setup | `intern/cycles/kernel/svm/closure.h` | Apache-2.0 |
| Paper: albedo scaling, Fms | Kulla & Conty 2017, "Revisiting Physically Based Shading at Imageworks" | — |

`data/disney_compensation/ggx_glass_{E,Eavg,inv_E,inv_Eavg}.bin` are byte-identical to
`table_ggx_glass_*` in `intern/cycles/scene/shader.tables` at v5.2.0 (max |diff| 0).

## The model

- Lobe: isotropic single-scatter GGX glass (Walter 2007), VNDF sampling (Heitz 2018);
  reflect with `pdf_reflect = avg(F·reflTint) / avg(F·reflTint + (1-F)·transTint)`.
- `energy_scale = 1 + (1-E)/E = 1/E` on eval and sample of both sub-lobes, with
  `E = ggx_glass_E[rough, mu, z]`, `rough = sqrt(alpha)`, `mu = N·view`,
  `z = sqrt(|ior-1|/(ior+1))`, `_inv_` tables at `1/ior` when the relative IOR < 1.
- Closure weight × `darkening = (1 + Fms·missing)/energy_scale`, Fms from
  `Fss = transmission tint` (= 1 for clear glass → no darkening).
- No dead-sample reroute: Cycles drops wrong-side directions (`LABEL_NONE`); the E tables
  were integrated with exactly those losses, so 1/E restores them.

Shared evaluator: `include/astroray/ggx_glass_energy.h` (host+device). CPU
`principled.cpp` (`glassEnergyTerms`, `multiGgxGlass`, `multiGgxGlassPdf`, sampler) and
GPU `gpu_materials.h` (`gpu_pr_glassEnergy`, `gpu_pr_transmissionEval/Pdf`,
`gpu_pr_chooseAndSampleDir`) call the same lookup and single-scatter functions. The GPU's
former transmission-only `gpu_ggxGlassCompensationFactor` (Fss = dielectric Fss) is no
longer used by Principled (Disney GPU still uses it; out of scope). Thin-film glass gets
the same energy terms (Cycles applies preserve_energy with a film too).

Routing: the addon lowers Glass BSDF to `principled` (transmission 1, #1038 tint
encoding) and Principled transmission is the same lobe, so both use it. Smooth glass
(roughness ≤ 0.03, the delta lobe) and the `dielectric` plugin are untouched.

## Deliberate differences from Cycles

1. Radiance convention: Astroray's transmission keeps the pbrt-v4 radiance-mode 1/η²
   (its delta glass and walk already do); Cycles has none. It cancels across a closed
   object, so every glass solid renders the same.
2. Tints: reflection × `specular_tint`, transmission × `sqrt(base_color)` (Astroray's
   existing convention, which #1038's Glass BSDF encoding depends on). Cycles Principled
   folds specular tint into f0 instead; identical for the default white specular tint.
3. `alpha = max(roughness², 0.0064)` floor kept (every Astroray GGX lobe has it).
4. **Refraction validity check kept.** Cycles' `bsdf_microfacet_eval` carries
   `/* TODO: check if the refraction configuration is valid */` and evaluates
   transmission for half vectors on the wrong side (`H·light` with the same sign as
   `H·view`). Its sampler can never produce those directions. Measured effect (lane i16
   diag, `astra_run/batch-i/i16/diag_oracle2v*.py`): on the pkg263 sphere, a front key
   light reaches the camera through camera→P→Q→light paths ONLY via such invalid exit
   configurations — physically-valid term exactly 0, Cycles-eval term ~4× the direct
   reflection at the rim. That is the bright lit-side rim Cycles shows at r ≥ 0.85
   (Cycles r 1.0 one-bounce minus zero-bounce: +0.30 at the rim, Astroray +0.00).
   Keeping the check is the physical choice and keeps NEE/BSDF MIS consistent; dropping
   it would reproduce Cycles' look at high roughness. Decision for the owner.

## Measurements (CPU, MinGW, 2026-10-06)

White furnace (lane i14 scene, 80², 256 spp, depth 64): within 0.008 of Cycles MULTI_GGX
on all 15 IOR × roughness rows, centre and rim (`astra_run/batch-i/i16/furnace_table.md`).
pdf() integrates to the sampler's kept fraction within 0.001 (default), walk proxy pdf
does not (+0.04..+0.42), `pdf_mass_probe.txt`.

pkg263 sphere vs Cycles MULTI_GGX (`glass_ab_table.md`): r 0.2/0.5 centre 0.988/0.983,
limb 0.883/0.947, RMSE 0.121/0.072 (walk 0.124/0.123). r 0.85/1.0 centre 0.931/0.883,
limb 0.732/0.558 — the gap is item 4, not the energy compensation (with compensation
disabled Astroray matches Cycles GGX at zero bounces exactly, and the MULTI/GGX ratio
matches Cycles' to 2 %).

## GPU register impact (rule 13)

All new values are locals inside eval/pdf/sample (no state carried across the shade
kernel). The table reads replace the old factor's E/Eavg reads; reflection now also
reads them. `gpu_pr_chooseAndSampleDir` and `gpu_pr_pdfLobe` take the closure by
reference (already live in their callers). Expected: REG unchanged at 254 on the
principled specialisations, small STACK delta; the lead measures with cuobjdump.

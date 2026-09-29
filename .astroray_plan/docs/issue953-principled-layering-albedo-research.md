# #953: Principled layering albedo (research note, 2026-09-29)

**Symptom.** Principled (spec 0.5) diffuse surfaces read ~0.975 of Cycles. White furnace
(sphere, white world, linear): Astroray 0.973 at roughness 1, 0.981 at 0.75; Cycles 5.2
1.000 at every roughness. Base 0.8: 0.782 vs 0.803. The loss scaled with base colour, so
it sat in the diffuse layer, not the specular lobe.

**Cause.** Cycles (Apache-2.0, blender/cycles main):
- `svm/closure.h` Principled: `albedo = bsdf_albedo(kg, sd, bsdf, true, false)`, then
  `weight = closure_layering_weight(albedo, weight)`.
- `closure/bsdf.h` `bsdf_albedo`: `albedo = sc->weight * bsdf_microfacet_estimate_albedo(...)`.
- `closure/bsdf_microfacet.h` `microfacet_ggx_preserve_energy`: `energy_scale = 1/E`,
  `sc->weight *= (1 + Fms*missing) / energy_scale`, so `sc->weight` carries
  `E * (1 + Fms*missing)`. For the generalized-Schlick spec layer,
  `Fss = mix(f0, f90, saturate(inverse_lerp(F0(ior), 1, fresnel_dielectric_Fss(ior))))`.
  For the coat (dielectric Fresnel), `Fss = fresnel_dielectric_Fss(coat_ior)`, which the
  same formula gives when `f0 = F0(coat_ior)`.
- `app/cycles_precompute.cpp`: `ggx_gen_schlick_ior_s` is `E[eval.x/eval.y]`, the
  Fresnel average normalised by the F=1 lobe. It is not an absolute albedo, so it must
  be multiplied by the lobe's energy.

The pkg261 port used `mix(f0, 1, s)` alone. It dropped `E*(1+Fms*missing)`, so the
diffuse was attenuated by up to 1/E too much (worst at high roughness).

**Fix.** `principled.cpp::ggxLayeringAlbedo` and `gpu_ggx_tables.cuh::gpu_ggxLayeringAlbedo`
multiply the estimate by `E * ggxDarkeningChannel(Fss, E, Eavg)`. This affects both the
specular and coat layers. After the fix the furnace is within 0.3 % of Cycles at every
roughness. Corpus v2 CPU #953 ROIs moved from 0.94-0.97 to 0.99-1.00.

**Residual (not fixed).** The specular eval's multiscatter `compFss` is `specF0`, while
Cycles uses the `Fss` above. That is under 0.1 % at IOR 1.5.

**Review follow-up (Terra).**
- Layering scalar: `closure_layering_weight` is `weight * saturate(1 - reduce_max(safe_divide_color(albedo, weight)))`.
  The Principled path now ports it exactly on CPU (`layeringScale`) and GPU (`gpu_pr_layeringScale`); Disney keeps
  the shared per-channel helper. Coloured sheen tint (0.2, 0.9, 0.3) now reads 0.954 in red vs Cycles 0.952;
  the per-channel form gave 0.995.
- Coat: no change needed. Cycles 5.2, 4.5 and main (`svm/closure.h`) apply
  `closure_layering_weight(bsdf_albedo(coat))` and then `weight *= mix(1, tint^(1/cosNT), coat_weight)`. There is
  no `bsdf_coat_setup`. Astroray already has this form, and the coat-tint furnace matches Cycles within 0.9 %.
- Framing: the first Cycles references set `cam.angle` before `sensor_fit`, which zoomed the view 1.44x. All pins
  were re-rendered with `sensor_fit = VERTICAL; angle_y = 45` (silhouette verified).

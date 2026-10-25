# #1154 Cycles bump-map correction — Research

## Paper
- **Title:** A Microfacet-Based Shadowing Function to Solve the Bump Terminator Problem
- **Authors:** Alejandro Conty Estevez, Pascal Lecocq, Clifford Stein
- **Year / Venue:** 2019, Ray Tracing Gems, ch. 12
- **DOI:** 10.1007/978-1-4842-4427-2_12
- GGX Lambda: Heitz 2014, "Understanding the Masking-Shadowing Function in Microfacet-Based
  BRDFs", JCGT 3(2), Eq. 72.
- `ensure_valid_specular_reflection` has no paper: Cycles derives it in the code comments
  (a quartic in N'.z with one valid root). It is a heuristic, not energy-derived.

## Reference implementation
- **Repo:** https://github.com/blender/blender, tag v5.2.0 (Cycles), Apache-2.0 (compatible:
  permissive, attribution kept in the code comments).
- **Files mirrored:**
  - `intern/cycles/kernel/closure/bsdf_util.h:319-409` `ensure_valid_specular_reflection`,
    `maybe_ensure_valid_specular_reflection`
  - `intern/cycles/kernel/closure/bsdf.h:81-146` `bump_shadowing_term`; call sites `:314`
    (bsdf_sample, `is_eval=false`, skipped for transmission labels) and `:556` (bsdf_eval)
  - `intern/cycles/kernel/closure/bsdf_microfacet.h:597-634` `bsdf_lambda` / `bsdf_G` (GGX)
  - `intern/cycles/kernel/svm/closure.h:154,295,495` — which Principled closures get the lifted
    normal (coat, specular / metal / glass / transmission, BSSRDF); diffuse, sheen and thin-wall
    subsurface keep N.
- Blender property: `Material.cycles.use_bump_map_correction` (default True, checked in 5.2.0).

## What we reproduce
- `include/astroray/bump_correction.h`: both functions, templated on the vector type and shared
  by CPU and GPU.
- CPU: `NormalMappedPlugin` lifts the whole normal for a glossy / glass / mirror inner material
  and multiplies eval and sample by the shadowing term (diffuse class gets the softening). The
  native Principled (`appliesBumpCorrectionPerLobe`) does both per closure, Cycles' split.
- GPU (`HasNormalPerturb` only): lift in the shade kernel, the term at lamp NEE, env NEE (applied
  to the parked record) and BSDF sample. Mode per material on `c_wfTexBinding.matBumpCorrect`.

## Differences from the reference
- Reference normal: Cycles lifts toward the facet normal `sd->Ng` (and also corrects unbumped
  glossy closures on smooth-shaded meshes, where `sd->N != sd->Ng`). Astroray's hit record has no
  facet normal, so both backends lift toward `sd->N` (the pre-bump shading normal). Identical on
  flat geometry; the smooth-mesh case is not ported.
- Sample path: Astroray applies the `is_eval=true` rule to samples too (its spectral sample
  re-evaluates f through evalSpectral), so a sampled glossy direction crossing `sd->N` is zeroed;
  Cycles keeps the sampled glossy closure. CPU and GPU agree.
- GPU Principled: one closure-graph normal (#1153), so it is lifted whole and gets no diffuse
  softening. A mix / Add of diffuse + glossy under a decorator is lifted whole on both backends.
- Disney (non-native fallback) is classed diffuse (no `isGlossy`).

## Gates
- `tests/test_issue1154_bump_correction.py`: grazing normal-mapped delta mirror (analytic: sky
  radiance), Principled metal roughness 0.2 vs Cycles, Lambert terminator softening (closed form,
  equal to Cycles within 0.1 %), light behind `sd->N` rejected, addon export.
- Cycles reference scenes (Blender 5.2.0, CPU, 1024 spp, seed 3, Standard view, 64x64, filter 1.5):
  (1) 80 m plane, Principled metallic 1 base white roughness 0.2, 2x2 Non-Color normal map
  (sin 30, 0, cos 30)*0.5+0.5 via Normal Map (tangent), black Principled floor at z = -0.01,
  world 0.5, camera at 10 deg elevation 6 m from the origin, 20 deg vfov, crop rows 24:40 cols
  16:48: 0.3979 corrected, 0.0 off. (2) 2 m plane, Principled base 0.8, Specular IOR Level 0,
  same normal map, sun 3 W/m^2 angle 0.02 from +x at 20 deg elevation, top-down camera 3 m, 30 deg
  vfov, crop 20:44: 0.54525 corrected, 0.58521 off; sun at -10 deg: 0 both.

# pkg326 - Glass BSDF thin film (research note)

Cycles v5.2.0 (blender/blender tag `v5.2.0`, fetched 2026-10-25):

- `intern/cycles/kernel/svm/closure.h` (Apache-2.0) `CLOSURE_BSDF_MICROFACET_{GGX,BECKMANN,MULTI_GGX}_GLASS_ID`
  :779-840 loads `thin_film_thickness` / `thin_film_ior` into `fresnel->thin_film` of the same
  `FresnelGeneralizedSchlick` the Principled thick-glass transmission builds (:362-423); back faces use
  `thinfilm_ior / ior` (:827) == Principled `adjust_thin_film_ior_at_backface` (:400-403). Reflection and
  transmission tints are both `Color` (#1038).
- `intern/cycles/kernel/closure/bsdf_microfacet.h` (BSD-3-Clause) `bsdf_microfacet_sample` :795-917: a
  singular (smooth) lobe still calls `microfacet_fresnel` (:335, thin-film branch :361-375), so smooth glass
  gets the film; `pdf_reflect = avg(R)/avg(R+T)`.
- Model: Belcour & Barla 2017, via the shared `include/astroray/thin_film_fresnel.h` (pkg178 Stage 4).

Astroray: the Glass node lowers to native `principled` (transmission 1, `specular_tint = Color`,
`base_color = Color^2`). Film glass already works there for `roughness > 0.03` (CPU `principled.cpp`
transmission eval + GPU `gpu_pr_transmissionEval*`). Smooth glass (`roughness <= 0.03`) is a delta lobe sampled
with plain `fresnelDielectric` (CPU ~line 2013; GPU `kPrincipledDeltaGlassRoughness`), so it ignores the film
on both backends.

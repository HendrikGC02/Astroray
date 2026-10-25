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

## #1162 - smooth (delta) glass gets the film

Same Cycles v5.2.0 source. `bsdf_microfacet_sample` :795-917 with `m_singular` (H = N): `microfacet_fresnel`
(:840) runs the thin-film branch, `pdf_reflect = avg(R)/avg(R+T)` (:847), eval = R or T (:865-879), R = F,
T = (1-F)*sqrt(base_color), f0 = F0(ior)*specular_tint (`generalized_schlick_setup` :111-124).

Astroray (CPU `principled.cpp` `sampleLobeDir` delta block + `deltaFilmF`/`deltaFilmFSpectral`; GPU twin
`gpu_pr_chooseAndSampleDir` + `gpu_principled_sample` + `gpu_material_sample_spectral`): pR = the existing
`glassReflectProb` (RGB film R, Cycles formula); f = L.weight*R or L.weight*sqrt(base)*(1-R)*eta^2 (the eta^2
radiance factor of the film-free delta branch), pdf = q_j*pR or q_j*(1-pR). Spectral leg: per-lambda R(lambda)
(analytic sensitivity, upsampled tint) over the RGB-chosen pR, so E[f/pdf] = R(lambda) + T(lambda) per wavelength.
Gated on `L.isDelta && filmActive()`: the film-free delta path and the rough-film dead-sample fallback are unchanged.
Known limit (#1188): the gate also catches ROUGH glass at |IOR-1| < 1e-4 (delta there too), which takes the mirror film
reflection; Cycles keeps GGX film reflection and makes only the refraction singular (bsdf_microfacet.h:868-869).

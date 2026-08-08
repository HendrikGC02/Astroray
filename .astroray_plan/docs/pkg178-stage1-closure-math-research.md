# pkg178 Stage 1 — CPU core-lobe closure math (cite-algorithm)

Companion to `.astroray_plan/docs/cycles-principled-port-research-2026-08.md`
(the architect's package-level note). This note pins the *per-function* math the
Stage-1 CPU scaffold (`plugins/materials/principled.cpp`) ports, so every
non-trivial formula in the code carries a citation (CLAUDE.md §6). Only the
Stage-1 core lobes are covered here: diffuse (Lambert + EON), specular GGX with
generalized-Schlick Fresnel, metallic F82-tint conductor, transmission rough
glass, and the closure-stack layering / one-sample-MIS recombination.

## Paper / reference

- **Reference impl:** Blender Cycles, `github.com/blender/cycles@main`
  (Blender 5.2-era), files:
  - `src/kernel/svm/closure.h` — `CLOSURE_BSDF_PRINCIPLED_ID` closure assembly +
    weight-flow (top-down layering order).
  - `src/kernel/closure/bsdf_util.h` — `closure_layering_weight`,
    `fresnel_dielectric_cos`, `fresnel_f82tint_B` / `fresnel_f82`,
    `schlick_fresnel`, `F0_from_ior`.
  - `src/kernel/closure/bsdf_microfacet.h` — `FresnelGeneralizedSchlick`
    evaluation (`generalized_schlick_fresnel`), GGX D / Lambda / VNDF pdf,
    `microfacet_ggx_preserve_energy` (already ported to
    `astroray::ggxDarkeningChannel`).
  - `src/kernel/closure/bsdf_oren_nayar.h` — Fujii improved Oren-Nayar +
    OpenPBR multiscatter (EON).
  - **License:** Apache-2.0 with several closure headers BSD-3-Clause — both
    compatible with Astroray's LICENSE; identical citation pattern already used
    by `disney.cpp` / `energy_compensation.h`.
- **Papers:** Kulla & Conty 2017 (multiscatter GGX energy compensation);
  Kutz/Hoffman/Hart F82-tint conductor Fresnel (used by OpenPBR/Cycles);
  Walter et al. 2007 (microfacet refraction); Heitz 2018 (VNDF sampling);
  Fujii "improved Oren-Nayar" + OpenPBR surface spec (EON diffuse);
  Veach 1997 §9.2.4 / PBRT-v4 §9.5 (one-sample MIS).

## Closure-stack layering (Cycles `svm/closure.h`, `CLOSURE_BSDF_PRINCIPLED_ID`)

Running spectral `weight` flows top-down; each reflective layer attenuates what
sits below via `closure_layering_weight`. Stage-1 subset (Cycles' order; DEFERRED
layers leave a documented seam — see the Stage-0 table):

1. Emission — DEFERRED (Stage 3).
2. Sheen — DEFERRED (Stage 3).
3. Coat — DEFERRED (Stage 3).
4. **Metallic** (GGX + F82-tint): closure weight `= metallic * weight`;
   `f0 = clamped base_color`, edge tint `= specular_tint`. After:
   `weight *= (1 - metallic)`.
5. **Transmission** (rough glass): closure weight `= transmission_weight * weight`;
   generalized-Schlick dielectric Fresnel, transmission tint `sqrt(base_color)`,
   reflection tint `specular_tint`. After: `weight *= (1 - transmission_weight)`.
   (`thin_wall` variant DEFERRED to Stage 4.)
6. **Specular dielectric** (`eta != 1`): GGX + generalized-Schlick,
   `f0 = F0_from_ior(ior) * 2 * specular_ior_level * specular_tint`,
   `f90 = 1`, `exponent = -ior` (negative → real-dielectric reparam path).
   After: `weight = closure_layering_weight(spec_albedo, weight)`.
7. Subsurface — DEFERRED (owned by the parallel random-walk BSSRDF agent, D2);
   seam left: `diffuse_weight = base_color * (1 - subsurface_weight) * weight`.
8. **Diffuse**: `bsdf_diffuse_setup` (Lambert) when `diffuse_roughness ≈ 0`,
   else `bsdf_oren_nayar_setup` (EON). closure weight `= base_color * weight`.

`closure_layering_weight(layer_albedo, weight) =
 weight * saturate(1 - reduce_max(layer_albedo / weight))` (bsdf_util.h).

## Fresnel

- **`F0_from_ior(ior) = ((ior-1)/(ior+1))²`** (bsdf_util.h).
- **`fresnel_dielectric_cos(cosi, eta)`** (bsdf_util.h): Cycles' exact form
  `g = eta²-1+c²; if g>0: g=√g; A=(g-c)/(g+c); B=(c(g+c)-1)/(c(g-c)+1);
  return 0.5·A²·(1+B²) else 1`.
- **Generalized Schlick, exponent < 0** (bsdf_microfacet.h
  `generalized_schlick_fresnel`): reparameterize to the real dielectric curve —
  `s = saturate(inverse_lerp(F0_from_ior(ior), 1, fresnel_dielectric_cos(cosi,ior)))`,
  `F = mix(f0, f90, s)`. Astroray upsamples the reflectance colours `f0/f90`,
  applies the achromatic scalar `s` per-λ (spectral nativeness).
- **F82-tint conductor** (bsdf_util.h, per channel):
  `f = 6/7; f5 = f⁵; F_s0 = mix(F0, 1, f5); B = F_s0·(7/f⁶)·(1-tint)` then
  `s = saturate(1-cosi); s5 = s⁵; F = saturate(mix(F0,1,s5) - B·cosi·s5·s)`.

## GGX (already in-repo, shared with `disney.cpp` / `metal.cpp`)

- D (Trowbridge-Reitz), Smith Λ/G1, VNDF sampling (Heitz 2018 / pbrt-v4
  BSD-3-Clause), rough-transmission eval/pdf (Walter 2007 §5.3) — ported
  verbatim from `disney.cpp` (which cites pbrt-v4/Walter per function).
- Multiscatter energy compensation: `astroray::ggxDarkeningChannel` +
  `DisneyEnergyCompensationTables` (Kulla & Conty 2017 / Cycles
  `microfacet_ggx_preserve_energy`; reused, not forked).

## EON diffuse (bsdf_oren_nayar.h — Fujii + OpenPBR multiscatter)

`sigma = saturate(diffuse_roughness); a = 1/(π + sigma(π/2 - 2/3)); b = sigma·a`.
Single scatter (achromatic): `s = wi·wo - nl·nv; t = s>0 ? s/max(nl,nv) : s;
single = a + b·t`. OpenPBR multiscatter (per channel albedo `c`):
`Eavg = a·π + ((2π-5.6)/3)·b; Ems(c) = (1/π)·c²·(Eavg/(1-Eavg))/(1 - c(1-Eavg));
El = a·π + b·G(nl); Ev = a·π + b·G(nv); multi(c) = Ems(c)·(1-Ev)·(1-El)` with
`G(cosθ)` the Fujii angular integral (bsdf_oren_nayar_G). Eval intensity
`= nl·(single + multi)`; the diffuse closure weight (`base_color·weight`) applies
`base_color` once more on top — the multiscatter series then carries `base_colorⁿ`
(more saturated multi-bounce), matching Cycles.

## One-sample MIS recombination (the pkg170 lesson — matched normalization)

Each lobe carries a spectral layering weight `wᵢ` (from the chain above) and a
scalar selection weight `selᵢ = luminance(wᵢ · lobe_albedo)`. With `W = Σ selⱼ`:

- `eval_total(wo,wi) = Σ wᵢ · fᵢ(wo,wi)` (fᵢ = intrinsic BSDF·cos, spectrally native)
- `pdf_total(wo,wi) = Σ (selᵢ/W) · pdfᵢ(wo,wi)` (continuous lobes only)
- sample: pick lobe `j` with prob `selⱼ/W`, sample `wi`; continuous → return
  `eval_total`, `pdf_total`; delta (smooth glass) → return `f_j`, `pdf = (selⱼ/W)·pdf_j_internal`.

`eval_total` and `pdf_total` use the SAME `wᵢ`/`selᵢ` (matched) — this is exactly
the property whose violation produced the pkg170 GPU furnace ≈ 1.975 gain
(RAW-weight eval vs normalized-selection pdf). Cycles' physical layering makes
`Σ wᵢ · albedoᵢ ≤ 1`, so the estimator conserves without an ad-hoc `1/W` on eval.

## Differences from the reference (intentional, Stage-1)

- EON multiscatter uses the OpenPBR closed form but the layering `spec_albedo`
  used to attenuate diffuse is the GGX directional albedo at the view angle
  (`ggxDirectionalAlbedo`, the disney.cpp/pkg145 helper) rather than Cycles'
  per-closure `bsdf_albedo` estimate — same Kulla-Conty lineage, small band.
- Transmission rough glass reuses the shipped disney/Walter estimator +
  `ggxGlassCompensationFactor`; the generalized-Schlick reflection/transmission
  *tinting* (`specular_tint` / `sqrt(base_color)`) is applied, thin-film is not
  (Stage 4).
- No emission/sheen/coat/aniso/SSS/thin-film/thin-wall (Stages 3–5). See the
  Stage-0 table for the DEFERRED matrix + owning follow-ups.

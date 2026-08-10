# pkg178 Stage 4 PR-1 — thin-film Fresnel utility, implementation research notes

**Date:** 2026-08-10. Companion to `.astroray_plan/docs/pkg178-stage4-thinfilm-research.md`
(architect's canonical citation note) and `pkg178-stage4-plan.md`. This note records the
concrete PR-1 port decisions (CPU dielectric only).

## Sources (verbatim ports, CLAUDE.md §6)

- Belcour & Barla 2017, "A Practical Extension to Microfacet Theory for the Modeling of
  Varying Iridescence", ACM TOG 36(4):65, DOI 10.1145/3072959.3073620.
- blender/blender `main` (fetched 2026-08-10, sources cached in the session scratchpad
  `cycles/` dir), all BSD-3-Clause / Apache-2.0:
  - `intern/cycles/kernel/closure/bsdf_util.h` (BSD-3-Clause):
    `fresnel_dielectric_polarized`:47, `fresnel_conductor_polarized`:200,
    `iridescence_lookup_sensitivity_channel`:456, `iridescence_airy_summation_channel`:468,
    `fresnel_iridescence_channel`:499.
  - `intern/cycles/kernel/closure/bsdf_microfacet.h` (BSD-3-Clause):
    `adjust_thin_film_ior_at_backface`:86, `generalized_schlick_setup`:110,
    `generalized_schlick_fresnel`:264 (thin-film branch :274-298), `microfacet_fresnel`:335.
  - `intern/cycles/kernel/svm/closure.h` (Apache-2.0): Principled assembly, specular
    :437-472, transmission :362-423 (backface adjust :400-403).
  - `intern/cycles/scene/shader.cpp` (Apache-2.0): `compute_thin_film_table`:932 (XYZ->RGB
    + DC normalization).
  - `intern/cycles/scene/shader.tables` (Apache-2.0): `table_thin_film_cmf[512][6]`:1287.
  - `intern/cycles/kernel/util/lookup_table.h`: `lookup_table_read` — `x = saturatef(x)*(size-1)`,
    clamped linear interp.
  - `intern/cycles/kernel/svm/types.h`:577 `THINFILM_THICKNESS_CUTOFF 0.1f`;
    `kernel/types.h`:37 `THIN_FILM_TABLE_SIZE 512`.

## Key math facts pinned during the port

- **OPD** = `-2 * film_ior * thickness_nm * cos_theta_2` (positive, since cos_theta_2 < 0
  is the in-film refraction cosine returned negative by `fresnel_dielectric_polarized`).
- **Airy series** (Cycles rearrangement, `iridescence_airy_summation_channel`):
  `T121=1-R12; R123=R12*R23; r123=sqrt(R123); Rs=T121^2*R23/(1-R123); R=Rs+R12; Cm=Rs-T121;`
  then for m=1..3: `Cm*=r123; S=sensitivity(m*OPD); R += Cm*2*(acc.re*S.re+acc.im*S.im); acc*=phasor;`
  Truncated at m=3 (residual O(r123^4)).
- **Per-lambda sensitivity degenerates to the exact analytic phasor**
  `S(m*OPD) = {cos, sin}(2*pi*m*OPD/lambda)` — no LUT on the spectral leg (pkg128 design).
  RGB leg uses the Rec.709-baked CIE-sensitivity LUT for Cycles like-for-like parity.
- **Sub-1nm blend:** `film_ior = mix(ambient_ior, film_ior, smoothstep(0,1,thickness))` for
  thickness < 1nm (wave-optics cutoff; keeps the limit continuous). smoothstep(0,1,x)=x^2(3-2x).
- **Film active <=> thickness > 0.1nm** (THINFILM_THICKNESS_CUTOFF). Below that the utility
  is NOT called — the CPU code takes the exact pre-change (Stage-3) Fresnel path.

## CPU integration into `plugins/materials/principled.cpp`

- **Specular lobe** (`generalized_schlick_fresnel` thin-film branch, svm/closure.h:437-472):
  per RGB channel / per lambda `F = fresnel_iridescence_channel<false>(1, {thickness,filmIor}, eta, 0, -1, cos, nullptr)`
  then the F0-rescale block (`F0_real=F0_from_ior(eta); if F0_real>1e-5 && F!=1:
  s=saturate(inverse_lerp(1,F0_real,F)); F *= mix(1, f0/F0_real, s)`). `f0` = specF0 =
  `F0_from_ior(ior)*2*specular_ior_level*specular_tint`, `eta` = the specular ior (L.ior).
  compFss (energy-comp) stays FILM-FREE = specF0 (no double-count). Refraction direction /
  pdf / sampling UNCHANGED (specular pdf is Fresnel-independent NDF sampling).
- **Transmission lobe** (svm/closure.h:405-410, generalized_schlick, both faces): ONE
  iridescence F at the microfacet half-angle `|wo.wm|` with `iorArg = etap` (= bsdf->ior;
  front `ior`, back `1/ior`), film ior backface-adjusted `adjust_thin_film_ior_at_backface`
  (`film_ior *= 1/ior` on the backface). Reflect sub-lobe uses F, transmit sub-lobe uses
  `(1-F)` (colored). transmission_tint = `sqrt(base_color)` unchanged; glass energy-comp
  (dielectric Fss) unchanged (film-free). **Selection pdf / sampler UNCHANGED** — the film
  only scales the eval BSDF magnitude, so the sampled-direction distribution and pdf are the
  exact Stage-3 code (chi² invariance). This is the correct, unbiased one-sample-MIS
  behavior: eval returns the true (film) BSDF, pdf returns the true (unchanged) sampling
  density.
- With the common defaults (`specular_tint=1`, `specular_ior_level=0.5`) the F0-rescale
  factor `f0/F0_real == 1`, so it degenerates to F = raw iridescence — verified.

## thickness-0 bit-equality (load-bearing)

Every film code path is inside `if (filmActive)` where `filmActive = thickness > 0.1`. The
`else` branch is the verbatim pre-change Stage-3 arithmetic. Default `thin_film_thickness=0`
=> filmActive=false => byte-identical output. Proven by render identity thickness{absent, 0,
0.05} and pre-change-main pixel diff.

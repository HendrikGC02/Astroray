# pkg145 research — diffuse-under-specular energy coupling (albedo scaling)

**Date:** 2026-07-23 (architect boot pass for the overnight run)
**Feeds:** `packages/pkg145-disney-specular-energy-compensation-refit.md`
**Prior art in-repo:** `.astroray_plan/docs/disney-energy-compensation-research.md`
(GGX multi-scatter tables; does NOT cover inter-lobe layering — this note closes
that gap).

## Problem this note answers

The 2026-07-21 night-session decomposition (preserved in the pkg145 spec) showed
the grazing-angle overshoot is **uncoupled diffuse + specular layering**, not a
defect in either lobe: at roughness=0.1, cos_theta_o=0.1 the diffuse lobe
integrates to 0.73 and the specular lobe to 0.48 — the naive sum is 1.20.
Disney 2012 famously does not conserve energy across the diffuse/specular split;
every modern production model fixes this with **albedo-scaling layering**. The
question was: what exact formulation do Cycles / OpenPBR use, so we port rather
than invent (CLAUDE.md §6).

## Canonical references (all license-compatible)

### 1. Blender Cycles — `closure_layering_weight` (Apache-2.0)

Cycles' Principled BSDF builds the closure stack top-down
(`intern/cycles/kernel/svm/closure.h`, `CLOSURE_BSDF_PRINCIPLED_ID` branch) and,
after registering each reflective layer (sheen → coat → dielectric specular),
attenuates the weight remaining for the layers *below* it:

```c
const Spectrum albedo = bsdf_albedo(kg, sd, (ccl_private ShaderClosure *)bsdf,
                                    /*reflection*/ true, /*transmission*/ false);
weight = closure_layering_weight(albedo, weight);
```

with (`intern/cycles/kernel/closure/bsdf_util.h`, fetched verbatim 2026-07-23):

```c
ccl_device_inline Spectrum closure_layering_weight(const Spectrum layer_albedo,
                                                   const Spectrum weight)
{
  return weight * saturatef(1.0f - reduce_max(safe_divide_color(layer_albedo, weight)));
}
```

`bsdf_albedo` for the microfacet specular closure resolves to
`bsdf_microfacet_estimate_albedo` (`intern/cycles/kernel/closure/bsdf_microfacet.h`),
which is the **Fresnel-weighted directional albedo of the specular lobe,
including the energy-preservation (multi-scatter) compensation** — i.e. exactly
"how much light the specular layer already accounted for at this view angle."
The diffuse/subsurface base is allocated with the reduced weight. This is the
Cycles-faithful mechanism the pkg145 night note asked for.

### 2. OpenPBR Surface spec — glossy-diffuse albedo scaling (ASWF; ref impl Apache-2.0)

The OpenPBR Surface specification
(https://academysoftwarefoundation.github.io/OpenPBR/, §Glossy-diffuse under
Base Substrate) gives the same coupling as an explicit BRDF sum — the
"non-reciprocal albedo-scaling approximation":

```
f_glossy-diffuse(wi, wo) ≈ f_dielectric(wi, wo) + (1 − E_dielectric(wo)) · f_diffuse(wi, wo)
```

where `E_dielectric(wo)` is the **directional albedo** of the dielectric
(specular GGX + Fresnel) interface at the view direction. The spec documents the
non-reciprocity as an accepted production tradeoff (Cycles ships the same
approximation). Reference implementation: `adobe/openpbr-bsdf` (Apache-2.0,
already license-verified in `2026-07-pbr-advances-research-pass2.md`).

### 3. Kulla & Conty 2017 (origin of the technique)

Kulla, C. & Conty, A., "Revisiting Physically Based Shading at Imageworks,"
SIGGRAPH 2017 Course (Physically Based Shading in Theory and Practice) —
introduces albedo-scaling coupling of diffuse under specular and the E/Eavg
table machinery Cycles adopted. Cite as the paper; Cycles is the code source.

## Mapping onto Astroray (implementation sketch for the implementer)

- Astroray already ships the **D-independent** Cycles `table_ggx_E` (32×32
  directional-albedo table, roughness × cos_theta) used by the pkg60/pkg145
  specular compensation. The specular layer's directional albedo at
  `(roughness, cos_theta_o)` is `E_spec_dir = Fss(cos_theta_o) ⊗ E-compensated
  lookup` — the same quantity `bsdf_microfacet_estimate_albedo` returns. **No
  new table is needed.**
- Apply the coupling on the CPU Disney eval/sample/pdf weights in
  `plugins/materials/disney.cpp`: scale the diffuse (and sheen-adjacent
  diffuse) lobe by `saturate(1 − E_spec_dir(wo))` per the OpenPBR formula /
  Cycles `closure_layering_weight`. Mirror on the GPU Disney path if it carries
  its own lobe weights (`include/astroray/gpu_materials.h`) — RTX parity gate.
- **Sanity check against the measured decomposition:** 0.48 + (1 − 0.48) · 0.73
  = **0.86 ≤ 1.0** at the worst quarantined config (was 1.20). The
  `diffuseFurnaceScale` ad-hoc normalization (pkg60 follow-up) should then be
  removable — re-derive per the spec's fix-contract item 2.
- The lobe **selection probabilities** in `sample()` should track the new
  weights so `f/pdf` stays well-behaved (Cycles does this implicitly via
  closure sample weights); chi² gates must stay green — the coupling changes
  lobe magnitude, not lobe shape.

## What NOT to do

- Do not invent a bespoke coupling factor or re-tune `diffuseFurnaceScale`
  against the broken pre-#498 integrator — the importance-sampled `rho()`
  oracle (pbrt-v4 §14.1.6, in-tree since #498) is the measurement.
- Do not regenerate `table_ggx_E`/`table_ggx_Eavg` — they are D-independent and
  correct (existing research doc).
- Non-reciprocity of the approximation is accepted (documented by OpenPBR,
  shipped by Cycles); do not chase a reciprocal formulation.

Sources:
- https://raw.githubusercontent.com/blender/blender/main/intern/cycles/kernel/svm/closure.h
- https://raw.githubusercontent.com/blender/blender/main/intern/cycles/kernel/closure/bsdf_util.h
- https://academysoftwarefoundation.github.io/OpenPBR/
- https://github.com/adobe/openpbr-bsdf

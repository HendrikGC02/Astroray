# #995 / #955 — closure mix, Add sum, emission with a BSDF (research note)

Lane i995, 2026-10-25. Sources: Blender Cycles, tag `v5.2.0` (`intern/cycles`, Apache-2.0), read directly.

## Ported semantics

| Cycles 5.2 | Behaviour | Astroray |
|---|---|---|
| `kernel/svm/closure.h:1499-1514` `svm_node_mix_closure` | `fac = saturatef(Fac)` at the shading point; children weighted `in_weight*(1-fac)`, `in_weight*fac` | `MixMaterial::weights` (`include/astroray/closure_mix.h`), GPU `gpu_tree_weights` |
| `scene/shader_nodes.cpp:5305` Add Shader (no SVM node), `:5359` zero-weight Mix branch pruned | both children keep the incoming weight; closures accumulate | `AddMaterial::weights` = (1, 1) |
| `kernel/closure/alloc.h:55-62` | closure sample weight = `|avg(weight)|` | leaf pick probability ∝ weight × [has BSDF] |
| `kernel/integrator/surface_shader.h:436-470` | pick one BSDF closure by sample weight (emission is never picked) | CPU: nested binary pick (product of local probabilities); GPU: flat pick over leaves |
| `surface_shader.h:271-315`, `:973-1010` | one-sample MIS, balance heuristic: f = Σ wᵢfᵢ, pdf = Σ qᵢpᵢ | `ClosureNodeMaterial::{eval,pdf,sample}`, `gpu_tree_*` |
| `kernel/integrator/shade_surface.h:817-868`, `:497` | emission written, then direct light + BSDF bounce; the path ends only without `SD_BSDF` | `Material::hasBSDF`; integrators and the GPU intersect stage continue after emission when it is true |

Veach 1997 Eq. 9.15 (one-sample model) keeps any selection probabilities unbiased, so the CPU nested pick and the GPU flat pick
differ only in noise (identical for Mix trees). A delta sample is returned alone with `f·w_c`, `pdf·q_c`.

## Sphere light from its own surface

An emissive analytic sphere with a BSDF now runs NEE from its own surface; the cone sampler `sqrt(1 - r²/d²)` is NaN there.
pbrt-v4 `Sphere::Sample(ctx)` (Apache-2.0) also leaves the cone sampler for points inside, but switches to area sampling.
Astroray drops the strategy (`pdfValue = 0`, matched by the sampler), so the BSDF-hit MIS weight is 1: same expectation,
more noise for this rare case; NEE on/off agree (0.8857 / 0.8858). Triangle emitters need no guard: a coplanar or
zero-cosine light sample has `pdfValue = 0` (`shapes.h` Triangle, GPU `gpu_reconstruct_light_pdf`).

## Residual on prod_shader_stack: the 1/η² radiance factor

Astroray's glass BTDF keeps the pbrt-v4 radiance-mode factor 1/η² (`ggx_glass_energy.h:145`, pbrt-v4 `DielectricBxDF::f`
"account for non-symmetry with transmission to different medium"); Cycles' `bsdf_microfacet_eval` has none
(`kernel/closure/bsdf_microfacet.h:764-772` eval, `:905-911` sample: `sqr(ior*inv_len_H)` is the half-vector Jacobian in both f and pdf, so f/pdf carries no η factor). It cancels for light that enters and leaves a solid, but not for emission
emitted *inside* the glass: the Emission closure of the stack radiates into the sphere and is seen through the wall at
1/1.45² = 0.476 of Cycles' brightness. Measured (CPU, Cycles 512-1024 spp):

* Add(Glass, Emission) variant: lit_front L 0.826; the predicted deficit 0.524 × 0.6 × tint × T matches R/G/B to 1 %.
* Full stack with glass IOR 1 (factor 1): 15/16 channels within 1 % of Cycles (upper_left B 1.045).
* BSDF-only stack (emission 0): all four ROIs within 1.6 %.

Astroray applies the factor consistently (`ggx_glass_energy.h:169`, `principled.cpp`, `gpu_materials.h`, `disney.cpp`;
Cycles-parity review of ffcbb3cb), so this is a radiance convention, not a bug. The open question is what Emission
Strength means inside glass: radiance in the medium (Astroray; it exits at S/n²) or a thermal emitter's basic radiance
(it exits at S, Cycles' number). Owner's call; kept as the documented xfail residual, not a #995 gap.

# #989 per-hit shading inputs in the op-VM: research note (2026-09-30)

Source: Blender Cycles, Apache-2.0 (`blender/blender` main, fetched 2026-09-30).

| Node / output | Cycles function | Formula (wi = toward viewer, N = shading normal) |
|---|---|---|
| Layer Weight.Fresnel | `kernel/svm/fresnel.h` `svm_node_layer_weight` | `eta = max(1 - blend, 1e-5)`; `eta = backfacing ? eta : 1/eta`; `f = fresnel_dielectric_cos(dot(wi, N), eta)` |
| Layer Weight.Facing | same | `f = abs(dot(wi, N))`; if `blend != 0.5`: `blend = clamp(blend, 0, 1-1e-5)`, `blend = blend < 0.5 ? 2 blend : 0.5/(1 - blend)`, `f = pow(f, blend)`; `f = 1 - f` |
| Fresnel.Fac | `kernel/svm/fresnel.h` `svm_node_fresnel` | `eta = max(ior, 1e-5)`; `eta = backfacing ? 1/eta : eta`; `f = fresnel_dielectric_cos(dot(wi, N), eta)` |
| Geometry.Backfacing | `kernel/svm/light_path.h` `NODE_LP_backfacing` | `SR_BACKFACING ? 1 : 0` |
| `fresnel_dielectric_cos` | `kernel/closure/bsdf_util.h` | exact unpolarised dielectric Fresnel without the refracted vector (TIR -> 1) |

Astroray mapping (`include/astroray/shader_vm.h` `OP_SHADING`, `svm_shading`, `SvmShading`): `cosI = dot(wo, N)` with
`wo` the unit direction to the viewer (Cycles `sd->wi`) and `N` the shading normal; `backfacing = !frontFace`. CPU
`ProgramTexture::valueAtHit`, GPU `<HasProgram>` block of `shadePathSlot`. Both formulas take `|cosI|`, so the normal's
orientation convention does not matter.

Deviations (documented, reported where they apply):
* Only the default Normal input is represented; a linked Normal is a `VMCompileError` (flattened + reported).
* Astroray passes the shading normal after normal-map / bump perturbation (CPU `NormalMapped` hands the perturbed
  record to the inner material); Cycles' default `sd->N` is the unperturbed normal. Differs only with a Normal/Bump
  on the same material.
* Geometry Pointiness needs per-vertex curvature (Cycles `ATTR_STD_POINTINESS`, computed at mesh sync); not
  implemented: `VMCompileError` -> reported, not silent. Other Geometry outputs likewise.
* Emission Color chains with shading inputs are dropped with a report (emitters are evaluated without the shading
  context: NEE samples, GPU emission bake).

# #1180 / #1186 -- Principled emission x alpha, tree emission on any leaf, ReSTIR continuation

Lane i1186, 2026-10-31. Source: Blender Cycles tag `v5.2.0` (`intern/cycles`, Apache-2.0), read directly.

## Cycles semantics

| Cycles 5.2 | Behaviour | Astroray |
|---|---|---|
| `kernel/svm/closure.h` CLOSURE_BSDF_PRINCIPLED_ID (~l.113) | `weight *= alpha` (transparent closure took `1 - alpha` first) | `PrincipledPlugin::assembleLobes` step 1 (pkg178 PR-6) |
| same, `principled_bsdf_emission` (~l.213) | `emission_setup(sd, emission * weight)` with the alpha-scaled weight | #1186: `emitted`, `emittedSpectral`, `getEmission` (light-list power), GPU `gpu_principled_emitted` all carry `alpha` |
| `kernel/integrator/shade_surface.h:817-868` | emission written, then the path continues through the BSDF closures | `Material::hasBSDF`; #1186 mirrors it in CPU ReSTIR-DI (`restir_di.cpp`) |

## Decisions

* **#1186 part 1.** One factor at every emission site. CPU: `emissionSpec_` is built with `alpha` folded in (scale-linear
  RGBIlluminantSpectrum), RGB `emitted`/`getEmission` multiply by it. GPU: host-side only, `scene_upload.cu` uploads
  `emissionStrength * alpha` (the intersect stage, NEE emitter evaluation and GPU ReSTIR all read that one field), so the
  light sampler's host power (`getEmission`) and the device emission agree. `isEmissive()` is false at alpha 0. No device code.
* **#1180.** Two fixes were open: (a) lower a non-Principled emissive leaf to a closure-graph Principled equivalent; (b) carry
  the tree emission in the GMaterial of every leaf type. (a) changes the BSDF (Disney, dielectric, thin glass, metal have no
  exact Principled twin) and risks CPU/GPU divergence; chosen (b). `GMaterial::principled` exists (zeroed) on every material,
  so `scene_upload.cu` stamps the tree emission there for any leaf-0 type except `GMAT_DIFFUSE_LIGHT`, and
  `gpu_material_emitted` / `_spectral` read it for every type (`lowerClosureTree` no longer rejects "emission with a
  non-Principled first BSDF"). Device change is confined to the intersect/NEE emission helpers, not the shade kernels.
* **Exporter reach.** `shader_blending.add_shader_specs` folds Emission into a Principled spec, so the Blender path hits this
  only when the pair cannot fold: legacy Disney route (native Principled off), Hair/Transparent + Emission, textured Emission
  (still not lowered), and API users. Python `create_add_material(lambertian, emissive)` is the direct repro.
* **ReSTIR.** The only integrator difference was the unconditional `break` at an emissive hit. Emission is still added at
  `bounce == 0 || wasSpecular` only (later bounces get it through NEE, as for every surface).

## Not taken

Cycles' emission inside glass convention (1/eta^2, see issue995 note) is unchanged.

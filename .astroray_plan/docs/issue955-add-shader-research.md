# #955 Add Shader (closure sum) - research note

- Cycles `kernel/svm/closure.h` `svm_node_add_closure` (Apache-2.0): Add Shader
  concatenates the two closure trees, each keeping its own weight (no
  normalisation). BSDF = f_A + f_B. Mix Shader instead weights (1-fac), fac.
- Estimator: one-sample MIS over the two children (Veach 1997 thesis Eq. 9.15,
  balance heuristic; pbrt-v4 BSDF mixture sampling): pick a child with p = 1/2,
  return summed f and pdf = 0.5 (pdf_A + pdf_B). Delta children are returned alone
  with pdf scaled by the selection probability (their eval is 0).
- Implementation: `include/astroray/add_material.h` (CPU exact), exporter spec
  `{'kind': 'add'}` (`blender_addon/shader_blending.py`), folds for pure-Diffuse
  pairs (albedo adds exactly while <= 1) and Emission (radiance adds).
- GPU (#1072): `gpu_closure_graph_eval` (pkg170) normalises lobe weights, so one merged
  closure graph would average. Instead a summable pair (`AddMaterial::gpuSummable()`:
  plain, opaque, non-emissive, untextured children) uploads child A at the Add's id and
  child B as a hidden material; `GMaterial::addPartner` (+1 index, in existing padding,
  struct stays 640 B) links them and `c_wfAddMaterials` (constant pointer) gives the
  shade kernel the array. The `HasPrincipled=true` wavefront shade path (selected for
  any scene with a partner) runs the CPU scheme: pick a child p = 1/2, return the
  summed f and 0.5 (pdf_A + pdf_B) (`gpu_add_*` in `stage_advance_device.cuh`, bodies
  `ASTRORAY_SHADE_NOINLINE`; the `<false>` fleet compiles none of it). Cycles picks a
  closure proportional to sample_weight (`surface_shader_bsdf_bssrdf_pick`,
  kernel/integrator/surface_shader.h, Apache-2.0); equal weights are the special case.
  Not summable on the GPU (still child A only, reported ADD_SHADER): textured /
  program-driven, emissive, alpha < 1, dispersive, normal-mapped, nested Add / Light
  Path children, children without a GPU lowering. ReSTIR/harness paths and photon
  receivers also see child A only.

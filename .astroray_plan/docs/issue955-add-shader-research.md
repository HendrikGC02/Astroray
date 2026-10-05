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
- GPU: `gpu_closure_graph_eval` (pkg170) normalises lobe weights, i.e. averages;
  GMaterial has no additive-composition flag and the shade kernel is REG 254
  saturated. The GPU therefore uploads child A only (all upload hooks forward to A)
  and the addon reports it (ADD_SHADER). A true GPU sum needs a new kernel path.

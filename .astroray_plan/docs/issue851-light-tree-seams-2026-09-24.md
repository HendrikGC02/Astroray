# #851 CPU light-tree seams (batch U, 2026-09-24)

Sources: Conty Estevez & Kulla 2018, "Importance Sampling of Many Lights with
Adaptive Tree Splitting" (§4.4 importance); Cycles `kernel/light/tree.h`
(Apache-2.0, vendored at `external/cycles_light_tree/kernel/light/tree.h`).

## Changes (measurement: see astra_run/batchU/u851)

1. **MIS pdf normal.** `TreeLightSampler::pdfValue` re-walked the tree with a
   `-dir` proxy normal. Sampling used the shading normal, so the BSDF-hit MIS
   pdf did not equal the pick pdf. The proxy prunes the hit emitter's own
   cluster as "behind the surface", so `lp` ≈ 0 and `w_B` ≈ 1 while NEE also
   counted the light. Cycles `light_tree_pdf` takes the stored `mis_origin_n`.
   Now each integrator carries `misNormalPrev`: the normal passed to
   `lights.sample()` at the previous vertex, or zero after a medium scatter.
   Call sites: `raytracer.h` pathTraceSpectral, `multiwavelength_path_tracer.cpp`,
   and `reference_pt_production.cpp`.
2. **Distance clamp.** `LightTree::importance` used `max(d - r_bbox, 1e-6)`,
   which gives a cluster enclosing the point about 1e12× importance. Cycles
   `light_tree_node_importance` uses `max(0.5·|centroid − bbox.max|, d)`. The CPU
   and `src/gpu/light_tree_device.cuh` now both use the Cycles clamp.

3. **Triangle light pdf.** `Triangle::pdfValue` returned `t²/(|dir·n|·A + 0.001)`,
   and `n` was the interpolated shading normal. `random()` samples uniformly by
   area, so the density is `t²/(|dir·Ng|·A)`, as in Cycles
   `kernel/light/triangle.h` `triangle_light_pdf_area_sampling`. For small
   emitter triangles the fudge under-reports the pdf, which biases NEE bright:
   a 5e-5 m² triangle patch gave NEE-on/NEE-off = 118×. This affects both
   samplers. The tree exposed it because it picks nearby small triangles far
   more often, so materials_hall showed a +0.94% full-frame shift at pedestal H.
   The same fix went into `AreaLightShape::pdfValue` and into the GPU forward
   and reverse triangle pdfs (`gpu_nee.cuh`); the GPU forward pdf had used the
   vertex normal `n0`.

4. **Leaf selection.** Leaves picked uniformly among ≤4 emitters. Now each
   emitter gets `p = ½·(max_i/Σmax + min_i/Σmin)`, with the min term uniform
   over lit emitters when `Σmin = 0`, as in Cycles
   `light_tree_cluster_select_emitter` and the leaf branch of `light_tree_pdf`.
   `LightTree::importanceMinMax` returns both bounds. Nodes still use only the
   max bound. Emitters use the node distance clamp, not Cycles' per-type
   vertex distances. The GPU mirror uploads emitter bounds in `GLightTreeEmitter`.

5. **Area-light cone.** `AreaLight::orientationCone` returned
   `(spread, spread)`, which is a full sphere at Blender's default spread π.
   The tree then sampled back-facing area lights. materials_hall's Rim light
   faces away from the scene: removing it moved floor tree/power variance from
   1.11 to 1.02. The cone is now θo = 0 and θe = min(spread, π/2), following
   Cycles `scene/light_tree.cpp` (area branch: θo = 0, θe = spread/2).
   `min(spread, π/2)` bounds what `sampleLi` emits: it treats `spread` as a
   half-angle limit and rejects back faces.

## Not ported (still differs from Cycles)

- Min/max-importance averaging for inner nodes (`get_left_probability`).
- Per-type emitter distances (triangle vertices, light radius).
- Oriented cones for mesh emitters (Astroray uses a full sphere).
- `has_transmission`.

## Open

- `AreaLight::withinSpread` compares against the full Blender spread as if it
  were a half-angle. For spread < π it emits into twice the Cycles cone. This
  is a radiometry bug, separate from #851.
- `SpotLight::orientationCone` has the same `(angle, angle)` form. Cycles uses
  θo = 0. It costs efficiency only, not bias.

- The GPU `gpu_reconstruct_light_pdf` still uses the `-dir` proxy. It is inert
  when dedicated lights are present, because the tree is not uploaded then.

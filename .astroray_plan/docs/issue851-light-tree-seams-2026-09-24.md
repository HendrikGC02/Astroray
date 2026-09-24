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
   `AreaLight::spread` is the emission half-angle (#852), so this equals the
   Cycles cone. The π/2 cap matches the front-face test.

6. **Tree energy units.** The tree weighted dedicated lights by flux
   (`power()`) and meshes by luminance × AABB surface area. Cycles uses the
   on-axis radiant intensity (`scene/light_tree.cpp`: area strength/π, point
   and spot strength/(4π), mesh area × emission), so energy/d² tracks
   irradiance. Flux made a point light look 4× too important next to an area
   light. The new `Light::treeEnergy()` gives power/π for area, power/4π for
   point and power/Ω for spot. Emissive triangles use L·area, spheres L·πr²,
   and other shapes L·(bbox surface)/4. The power sampler is unchanged.
   Measured on materials_hall (world contribution subtracted): the floor is
   lit by Key 65%, world 18% and Fill 15%. The nearby point lights and meshes
   add about 1%, but the tree sampled them far more often than that.
   Reference: Cycles tree on/off on the same scene gives wall 0.48 and floor
   0.12 (`astra_run/batchU/u851/cycles_table.txt`).

7. **Review fixes (cycles-parity-reviewer).**
   - **C2, energy loss.** A zero normal marks a volume vertex, and the
     importance then has no incidence term, as in Cycles `tree.h:142-167`.
     Surfaces are always treated as `has_transmission` (`|cos θi|`, no
     behind-surface prune; `tree.h:148,161`). Astroray cannot reliably tell
     which materials transmit, and pruning a delta light on the transmission
     side lost its light. Tree/power before → after: medium 0.19 → 1.0,
     translucent plane 0.016 → 1.0.
   - **Distant lights.** The sun and infinite hittables go in one leaf, the
     root's right child, following Cycles `LightTree::build`. Distant
     importance uses distance 1, direction −axis and cos θu = cos(θo+θe)
     (`light_tree_node_importance`). The #851 distance clamp had given an
     unbounded bbox zero importance. The sun cone is now axis = emission
     direction, θo = 0, θe = half angle.
   - **M2.** The leaf pick is the one-pass two-reservoir scheme
     (`light_tree_cluster_select_emitter`), on CPU and GPU.
   - **C1 and M1.** The GPU reverse pdf uses the previous vertex's NEE normal,
     carried in `path_mis_n{x,y,z}`, which is zero after a medium scatter.
     GPU medium NEE passes a zero normal, the same convention as the CPU.

## Remaining deviations (variance-only; pick pdf == MIS pdf, so no bias)

- Inner nodes use only the max-importance share (Cycles averages min and max
  in `get_left_probability`).
- Node and emitter distances use the centroid clamp, not Cycles' per-type
  vertex distances.
- Mesh emitters use a full-sphere cone (sidedness is not exposed per material).
- Surfaces never prune on incidence (always `has_transmission`).
- `SpotLight::orientationCone` still uses (angle, angle), where Cycles uses
  θo = 0.

## Open

- `PowerLightSampler` depends on insertion order. `powerDist` follows the
  order of `add()`/`addLight()` calls, but `sample()` assumes hittables come
  first. With a dedicated light added before a hittable emitter, power
  renders 3–4× dark at 256 spp, on main too (tree is unaffected). Fixed on
  lane u859 (`fix/u-859-restir-dedicated`, 354769ee); it merges with Batch U.
  materials_hall's power baseline may shift slightly after integration.
- #886: `pdfValue` sums the pdfs of back faces of closed emitter meshes.

- `SpotLight::orientationCone` has the same `(angle, angle)` form. Cycles uses
  θo = 0. It costs efficiency only, not bias.

- The GPU `gpu_reconstruct_light_pdf` still uses the `-dir` proxy. It is inert
  when dedicated lights are present, because the tree is not uploaded then.

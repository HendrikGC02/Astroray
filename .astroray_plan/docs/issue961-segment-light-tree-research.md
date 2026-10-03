# #961 / #1019 — light-tree pick for a medium segment — Research

## Paper
- **Title:** Importance Sampling of Many Lights with Adaptive Tree Splitting
- **Authors:** Alejandro Conty Estevez, Christopher Kulla
- **Venue:** Proc. ACM Comput. Graph. Interact. Tech. 1(2), 2018, DOI 10.1145/3233305
- §5.3 / Eq. 4 (via Kulla & Fajardo 2012): the importance of a cluster for a ray
  segment is energy · (θ_b − θ_a) / d, with d the ray's distance to the cluster and
  θ_b − θ_a the angle the segment subtends there.

## Reference implementation
- **Repo:** Blender Cycles, main a456b761 (read 2026-10-03), Apache-2.0.
- `src/kernel/light/tree.h`: `light_tree_node_importance<true>`,
  `light_tree_emitter_importance<true>`, `compute_v`, `light_tree_importance<true>`
  (no incidence term, `theta_d / min_distance`, min importance 0),
  `light_tree_sample<true>`, `light_tree_pdf<true>`, and the forward overload
  that re-walks the segment when `PATH_RAY_VISIBILITY_VOLUME_SCATTER`
  (`P - D_times_t`, `dt`).
- `src/kernel/light/sample.h`: `light_sample_from_volume_segment` picks once per
  segment; `src/kernel/integrator/shade_volume.h` `integrate_volume_direct_light`
  re-samples the SAME emitter (`ls.emitter_id`, `pdf_selection`) at the scatter
  point; `integrate_volume_phase_scatter` stores `mis_origin_n = P - previous_P`
  and `previous_dt = tmax - tmin` for the forward MIS.

## What was wrong (Astroray before)
- Power sampler: one pick per segment, re-sampled at the anchor and at P (#925).
- Light tree: the anchor light was a POINT pick at the segment midpoint, and P got
  an independent point pick. When the midpoint was outside a spot cone the pick
  failed, so there was no equiangular anchor; the exponential at the media hull's
  global majorant (smoke VDB, density 10) could not reach the fog behind it. Mean
  deficit (shaft 0.67-0.71 of Cycles, rising with spp: heavy tail), and the
  anchor/connection mismatch near small emitters gave the emitter-glow tail.

## What we reproduce
- `LightTree::importanceMinMaxSegment` / `pickSegment` / `pdfSegment`
  (`src/light_tree.cpp`), device twins in `src/gpu/light_tree_device.cuh`.
- `LightSampler::pickSegment` / `pdfValueSegment`; the tree sampler re-samples the
  unified index with the stored selection pdf (`TreeLightSampler::resample`).
- `Renderer::segmentDirectLight` always picks per segment (o, d, surface t), clips
  spot/area, anchors on the picked light (any drawn light point, as
  `light_sample<true>` never rejects), and connects to that light at P.
- Forward MIS after a medium scatter: CPU `misSeg*`, GPU `path_mis_n*` =
  P − segment origin, `path_mis_dt` = segment length, flagged by
  `env_nee_sampled_prev == 2` (the surface shade always writes 0/1).

## Differences from the reference
- Emitters use the node form (bbox + cone), as Astroray's point importance does;
  Cycles has per-type emitter parameters.
- Inner nodes use the max importance only (existing Astroray point traversal);
  Cycles averages the max and min probabilities.
- No triangle segment clip (`triangle_light_valid_ray_segment`): variance only.

## Measured (v2_media, CPU, 64 spp, seeds 11-16, luminance)
| | before (tree) | after (tree) | power sampler | Cycles |
|---|---|---|---|---|
| shaft mean | 0.121-0.134 | 0.184-0.193 | 0.184-0.191 | 0.187-0.189 |
| relVar (whole image) | 7.21 | 0.517 | 0.405 | 0.112 |
| top-0.1 % variance share | 0.957 | 0.494 | 0.629 | 0.705 |
| N x relVar 16 / 64 / 256 spp | 69 / 461 / 115 | 34.9 / 33.1 / 30.5 | - | 12.8 / 7.2 / 4.9 |

Remaining per-sample excess sits in the smoke VDB (N x relVar ~90 vs Cycles 1.2,
also in power mode): the hull distance strategy is an exponential at the media's
GLOBAL majorant, where Cycles uses null-scattering tracked collisions with octree
majorants (Miller et al. 2019 MIS, `volume_direct_scatter_mis`). Filed as a
follow-up; it converges as 1/N.

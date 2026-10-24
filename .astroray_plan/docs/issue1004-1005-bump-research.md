# #1004 / #1005 bump parity — research note (2026-10-25, lane i1004)

Source verified by fetching blender/cycles `main` @ `a456b761` (Apache-2.0), not recalled.

## Cycles structure

- `scene/shader_graph.cpp` `refine_bump_nodes`: the Height subgraph is copied three times
  (centre / dx / dy); each copy's texture-coordinate node gets `bump_filter_width`.
- `kernel/svm/tex_coord.h` `svm_node_tex_coord_derivative`: the dx copy reads
  `data.val += data.dx * bump_filter_width` — the INPUT coordinate is offset (before any
  Mapping), by Filter Width (default 0.1, `scene/shader_nodes.cpp` BumpNode) of the pixel
  footprint.
- `kernel/svm/displace.h` `svm_node_set_bump`: `normal_out = safe_normalize(fw * |det| * N -
  scale * sign(det) * surfgrad)`; fw cancels against the scaled offsets, so the result is
  the finite-difference slope over a small step (pkg223b note has the full formula).
- `kernel/device/cpu/image.h` `interp_linear`: Image Texture default Linear,
  `tx = frac(u*w - 0.5)`, 2x2 texels, extension-wrapped per texel.
- `kernel/svm/closure.h` Principled: coat on `Coat Normal`, sheen on
  `normalize(mix(N, coat_normal, coat_weight))`. Coat Normal is `LINK_NORMAL`: unlinked
  means the geometry normal sd->N, not the bumped Normal input.

## What Astroray takes

- Image bump (UV): input-UV step before the Mapping; bilinear height; step 0.1 texel
  (no ray differentials: a texel stands in for the pixel footprint). Normal-map image read
  Linear. CPU `normal_mapped.cpp` + `ImageTexture::valueLinear`; GPU
  `stage_advance_device.cuh` + `gpu_sampleImageTextureLinear` (shared `gpu_imageLinearTaps`).
- Principled coat / sheen keep sd->N (`rec.svmNormal`) under a NormalMapped decorator (CPU).

## Measurements that drove it (CPU, prod corpus, Cycles 1024 spp refs)

- pbr_group: Mapping Scale 3 made the old bump 3x weak; the nearest 1.5-texel forward
  difference put every relief band a texel low (left ROI metal highlight). Normal-map
  nearest vs Linear = 3-6 % (Cycles' own Closest render shifts the same).
- car_paint: with Coat Weight 0 the CPU procedural bump matches Cycles within ~1 %; the
  recorded "~2x overshoot" was the bump reaching the coat.

## Not taken / open

- General Linear/Cubic image sampling (base colour etc.): pkg234.
- `ensure_valid_specular_reflection` (bsdf_util.h, `use_bump_map_correction`): +2 % on the
  pbr_group centre in a trial; touches every bumped glossy lobe, not done here (#1154).
- GPU: procedural Bump Height and the coat normal (#1153).

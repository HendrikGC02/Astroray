# #1004 / #1005 bump parity — research note (2026-10-25, lane i1004)

Source: Cycles at Blender **v5.2.0** (`fbe62287`, the installed 5.2 build), Apache-2.0,
fetched from blender/blender `intern/cycles/`, not recalled. Line numbers are at that tag.

## Cycles structure

- `scene/shader_graph.cpp:946` `refine_bump_nodes`: the Height subgraph is copied three
  times (centre / dx / dy); each copy carries the Bump node's `bump_filter_width`.
- The dx copy offsets the INPUT coordinate, before any Mapping:
  `data.val += data.dx * bump_filter_width` — `kernel/svm/attribute.h:173-186`
  `svm_node_attr_derivative` (the default UV of an unlinked Image Texture Vector, and UV
  attributes); `kernel/svm/tex_coord.h:192-205` for an explicit Texture Coordinate node.
  Filter Width defaults to 0.1 of the pixel footprint (`scene/shader_nodes.cpp:7225`).
- `kernel/svm/displace.h:20-80` `svm_node_set_bump`:
  `normal_out = safe_normalize(fw * |det| * N - scale * sign(det) * surfgrad)`; fw cancels
  against the scaled offsets, so the result is the finite-difference slope over a small step.
- `kernel/device/cpu/image.h:170-178` `interp_linear`: Image Texture default Linear,
  `tx = frac(u*w - 0.5)`, 2x2 texels, extension-wrapped per texel.
- `kernel/svm/closure.h:152-161` coat on Coat Normal, `:127-129` sheen on
  `normalize(mix(N, coat_normal, coat_weight))`. Coat Normal is `LINK_NORMAL`
  (`scene/shader_nodes.cpp:2680`): unlinked means sd->N, not the bumped Normal.
- Output Displacement in Bump mode: `scene/shader_graph.cpp:1005-1098`
  `bump_from_displacement` wires the bump into a SetNormal on the Output; `svm/closure.h:
  1519-1524` `svm_node_set_normal` sets `sd->N`, so every closure, coat and sheen included,
  sees that bump.

## What Astroray takes

- UV image bump: input-UV step before the Mapping; bilinear height; step 0.1 texel. Normal
  Map image read Linear. CPU `normal_mapped.cpp` + `ImageTexture::valueLinear`; GPU
  `stage_advance_device.cuh` + `gpu_sampleImageTextureLinear` (shared `gpu_imageLinearTaps`).
  The addon reports a Closest / Cubic / Smart height or normal image (read Linear).
- Principled coat / sheen stay on sd->N (`rec.svmNormal`) for a Bump / Normal Map on the
  BSDF Normal input (CPU). They follow the bump (`coat_follows_bump`,
  `HitRecord::coatOnSvmNormal = false`) for an Output Displacement bump and for a Coat Normal
  wired to the same node output as Normal; any other Coat Normal chain stays reported.

## Limitations

- No ray differentials: the step is 0.1 texel, not 0.1 pixel. On a minified texture
  (several texels per pixel) Cycles' step spans more than a texel and smooths the relief;
  Astroray keeps the per-texel slope (sharper, sparklier bumps at distance). The Bump node's
  Filter Width input is ignored.
- Displacement bump with a separate BSDF Normal Map: Astroray's coat gets both, Cycles' coat
  only the displacement (sd->N). Not seen in the corpus.

## Measurements (CPU, prod corpus, Cycles 1024 spp refs)

- pbr_group: Mapping Scale 3 made the old bump 3x weak; the nearest 1.5-texel forward
  difference put every relief band a texel low (left ROI metal highlight). Normal-map
  nearest vs Linear = 3-6 % (Cycles' own Closest render shifts the same).
- car_paint: with Coat Weight 0 the CPU procedural bump matches Cycles within ~1 %; the
  recorded "~2x overshoot" was the bump reaching the coat.

## NEE and the bumped normal (review question)

NEE never sees the bumped normal before the lobes: the integrator samples lights with the
hit record's unperturbed normal (`lights.sample(ls, rec.point, rec.normal, ...)`,
`raytracer.h`), and NormalMappedPlugin perturbs only inside eval / pdf / sample. Each
Principled lobe then gates `n.l > 0` on its own frame: base lobes on the bumped normal, the
coat and sheen on sd->N (or the bumped normal when they follow it). Cycles additionally
zeroes a lobe when the light is on opposite sides of the bumped and smooth normals and
softens diffuse near the terminator (`bump_shadowing_term`, `kernel/closure/bsdf.h:86-146`);
Astroray has neither (#1154).

## Not taken / open

- General Linear/Cubic image sampling (base colour etc.): pkg234.
- `ensure_valid_specular_reflection` (`kernel/closure/bsdf_util.h:322-408`) and
  `bump_shadowing_term`: #1154.
- GPU: procedural Bump Height and the coat normal: #1153.

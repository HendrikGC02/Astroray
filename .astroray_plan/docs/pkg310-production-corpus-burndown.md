# pkg310 production node-tree corpus: baseline and gap burn-down (2026-09-30)

Eight production materials (`benchmarks/reference_corpus/production/`), rendered Cycles 5.2 LTS (1024 spp reference) vs
Astroray CPU and GPU (64 spp, seed 278, adaptive off, denoise off), bands from 5 seeds. Charts and contact sheets:
`test_results/textures-nodes/production-corpus/` (`<material>_sheet.png`, `band_utilisation_chart.png`,
`production_summary.json`, `silent_drops.json`). Gate: `tests/test_production_corpus.py` (24 strict xfails after #996, each tied to
an issue in `benchmarks/reference_corpus/provisional_production.toml`).

## Baseline: N/8

PASS = every non-excluded ROI channel inside its MC band AND an empty silent-drop list.

| Material | CPU ROI channels in band | GPU ROI channels in band | Silent pairs (CPU = GPU) | Primary issue (CPU / GPU) |
|---|---|---|---|---|
| prod_car_paint | 0/16 | 0/16 | 3 | #989 |
| prod_wood | 4/16 | 0/16 | 7 | #988 / #994 |
| prod_marble | 4/16 | 0/16 | 8 | #988 / #994 |
| prod_pbr_group | 1/16 | 0/16 | 6 | #988 |
| prod_shader_stack | 0/16 | 0/16 | 4 | #995 |
| prod_attributes | 0/16 | 0/16 | 1 | #990 |
| prod_light_path | 4/20 | 8/20 | 6 | #991 |
| prod_curves_geometry | 0/16 | 2/16 | 4 | #989 (+#992) |
| **Materials passing** | **0/8** | **0/8** | **0/8 silent-free** | |

Nothing rounds up: the closest material is `prod_marble` on CPU, 12 of 16 channels out of band, but three of the four
ROIs are within 3 % of Cycles and the 12 are dominated by one sun-highlight ROI (0.58x) and the 2 % band floor.

## After lane aq-nodes (#988, #989, #994; build 0d626f94, 2026-09-30)

Bands re-blessed from 5 seeds on this build (`mc_tolerance.py --suite production`): the kept Principled lobes raise
Astroray's seed-to-seed variance, so the pkg310 bands were calibrated on the lambertian export. Seed 278.

| Material | CPU in band (was) | GPU in band (was) | Now blocked by |
|---|---|---|---|
| prod_car_paint | 6/16 (0) | 1/16 (0) | #1005 Voronoi flake Bump dropped silently (lit_front B 0.78x, upper_flake G 1.17x) |
| prod_wood | 1/16 (4) | 5/16 (0) | #993, #881, #1006; GPU also #1007 (64^3 bake aliases the rings) |
| prod_marble | 11/16 (4) | 8/16 (0) | pattern residual <= 5 % vs 2-3 % bands (#1006 / #881); GPU #1007 |
| prod_pbr_group | 2/16 (1) | 2/16 (0) | #1004 Mapping Scale from the node-group input dropped silently (tiles 3x large) |
| prod_curves_geometry | 0/16 | 2/16 | Pointiness (reported, not implemented) + #992 |
| others | unchanged | unchanged | #990, #991, #995, #955 |
| **Materials passing** | **1/8** (prod_marble, #1006) | **1/8** | |

What changed: marble's sun-highlight ROI 0.58x -> 0.97x (CPU); car-paint `lit_front` G 4.64x -> 0.87x; marble GPU
0.38-0.72x -> 0.99-1.08x; wood GPU `grain_center` B 5.9x -> 0.98x. No row flipped to pass: each material has a second
root cause (the new issues above were found here). The GPU Object-coordinate bake is lossy (sphere region, 8 px
blocks, |GPU - CPU| / mean: marble 6.7 % vs CPU seed-to-seed 3.7 %, wood 16.4 % vs 5.5 %) and is reported per render.

## Silent drops

Strict definition (spec): an exercised (node, socket) pair, reachable from the active output and linked or non-default,
that the frozen coverage matrix does not classify SUPPORTED and that no DegradationReport entry names. Four deliberate
deviations (in the `silent_drop_audit.py` docstring): Output-node inputs are never drops; the shared `world:` tree is
excluded (counted, identical in all eight scenes); output sockets are judged only for node types the matrix has `output:`
rows for; APPROXIMATED pairs with no report go to a separate unscored `approximated_unreported` bucket. **39 unique
(material, node, socket) pairs at baseline**, identical on CPU and GPU (one Blender export path). Rules and the separate
"approximated, no report" bucket (not scored, 13 unique pairs, dominated by Principled APPROXIMATED rows): see the
`silent_drop_audit.py` docstring; tests: `tests/test_production_corpus.py`.

| Material | Silent pairs |
|---|---|
| prod_attributes | VertexColor.Color |
| prod_car_paint | Math.operation, Mix.data_type, TexVoronoi.Vector |
| prod_curves_geometry | Math.operation, Mix.data_type, RGBCurve.Color, TexNoise.Vector |
| prod_light_path | Math.operation, Math.use_clamp, MixShader.Fac / Shader / Shader_001, ValToRGB.Fac |
| prod_marble | Mapping.Rotation / Scale / Vector, TexNoise.Vector, TexWave.Vector, ValToRGB.Fac, VectorMath.Scale / operation |
| prod_pbr_group | CombineXYZ.X / Y / Z, Mapping.Rotation / Scale / Vector |
| prod_shader_stack | AddShader.Shader / Shader_001, TexNoise.Vector, ValToRGB.Fac |
| prod_wood | Mapping.Rotation / Scale / Vector, Math.operation, TexNoise.Vector, TexWave.Vector, ValToRGB.Fac |

Triage (baseline): **7 were real drops** (no report and the render is wrong): AddShader x2 (#955), MixShader Fac/Shader
x3 from Light Path (#991), VertexColor (#990), RGBCurve (#992). The other 32 were matrix-stale (#996): the render reports
"CPU exact" for those op-VM chains, and disabling the specular lobes in both engines brings `prod_marble` CPU to
0.95-1.04. Non-vacuity: `silent_drop_audit.py --self-test` (fixture with an unhandled Attribute node is flagged, is not
flagged once reported, an unreachable Layer Weight is never exercised) and `test_audit_flags_the_real_attributes_material`.

**After #996 (2026-10-03, lane at-n3; fresh CPU+GPU renders on the main `build_cuda`, seed 278): 7 unique silent pairs,
all real, 32 stale rows gone; 8 of 16 (material, backend) legs are silent-free** (car_paint, marble, pbr_group, wood on CPU
and GPU; their `silent` xfails are deleted and pass strictly).

| Material | Silent pairs now |
|---|---|
| prod_attributes | VertexColor.Color (#990) |
| prod_curves_geometry | RGBCurve.Color (#992) |
| prod_light_path | MixShader.Fac / Shader / Shader_001 from Light Path (#991) |
| prod_shader_stack | AddShader.Shader / Shader_001 (#955) |
| prod_car_paint, prod_marble, prod_pbr_group, prod_wood | none |

How the matrix became trustworthy (`scripts/generate_blender_parity_matrix.py`, all AST-derived, Blender 5.2):

* Named reads (`_get_input(node, 'Fac')`) credit a socket by identifier OR first same-named UI name (Color Ramp's `Fac`
  is `Factor` in Blender 5); Math/Vector Math `operation`, Mix `data_type`, Mapping/Rotate `vector_type`/`rotation_type`
  and every other property the dispatch branch reads are credited (an unrepresentable value raises `VMCompileError`
  and the addon reports "op-VM ... not representable").
* A socket read only under a semantic guard (Math 3rd operand under `op in MATH_TERNARY`, Vector Math `Scale` under
  `op in _VECMATH_USE_SCALE`) is credited iff the guard, evaluated against the compiler's own module constants, holds
  for every enum value for which Blender enables the socket and the compiler does not raise. Math `Value_002` is
  consumed (COMPARE/WRAP/SMOOTH_MIN enable it but the compiler rejects them with a report); a socket Blender enables
  for an accepted op the compiler skips stays DROPPED-SILENT.
* Procedural texture `Vector` is credited from `get_base_color_texture`'s `PROC_TYPES` branch
  (`inputs.get('Vector')` feeds `load_procedural_texture`).
* #872: the hand-edited TEX_SKY rows moved into `SCANNER_BLIND_OVERRIDES`; the report is sorted, so a regeneration
  is reproducible and `tests/test_blender_parity_matrix.py` asserts regeneration == committed (Blender 5.2).
  Drift the scanner now sees truthfully: Emission, Image Texture `Vector` and Voronoi are APPROXIMATED (they warn),
  Image `colorspace_settings` / `extension` are SUPPORTED.
* 47 newly SUPPORTED rows allocated to `textures_mapping` are not wired into any corpus scene yet; they are listed in
  `benchmarks/reference_corpus/scenes/proof_pending.json` (shrink-only: the manifest test fails once a scene tags one).
  A proof card for them is the follow-up; gate (b) scores only exercised sockets, so it is unaffected.

Weighted socket-coverage (pkg278 formula, `silent_drop_audit.py coverage`, matrix classification only, CPU = GPU
because the matrix is backend-agnostic): gate population 0.3811 -> 0.4185 (297 uses; matrix-silent uses 140 -> 120);
production corpus 0.5331 -> 0.7686 (71 uses; matrix-silent 32 -> 15). The gate score proper (`coverage_report --score`)
is `unmeasured` for CPU and GPU: it needs a hash-verified per-variant evidence artifact for every nonzero use and
the frozen v3 input is integrity-failed against the current corpus (scene hashes, matrix hash).

## Ranked backlog

One issue per root cause. Rank: materials whose failing rows name it, then plan-section-1 P-phase. Category is the
theme-1 taxonomy; observable and threshold are in each issue.

| # | Issue | Category | Backend | Materials | Phase |
|---|---|---|---|---|---|
| 1 | #996 coverage matrix marks op-VM-handled sockets DROPPED-SILENT (tooling; 32 of 39 silent pairs) **done 2026-10-03** | tooling | both | 7 (silent rows) | P0 |
| 2 | #988 Principled with per-texel Base Color exports as Lambertian: lobes lost | closure composition / export | both | marble, wood, pbr_group | P2 |
| 3 | #989 no per-hit shading inputs: Layer Weight, Fresnel, Geometry Backfacing/Pointiness | per-hit input | both | car_paint, curves_geometry | P3 |
| 4 | #993 VM_MAX_SLOTS exceeded by an ordinary wood Roughness chain | op-VM bound | both | wood, shader_stack | P3 |
| 5 | #994 GPU skips OBJECT-coordinate procedural programs (flat value) | GPU-only | GPU | marble, wood | P3 |
| 6 | #995 nested Mix Shader with textured Fac + Glass collapses to a constant mix | closure composition | both | shader_stack | P2 |
| 7 | #955 (existing) Add Shader keeps the first BSDF; silent dominant-shader fallback | closure composition | both | shader_stack | P2 |
| 8 | #990 Object Info Random, Attribute, Color Attribute unsupported | per-hit input | both | attributes | P3 |
| 9 | #991 Light Path unsupported; Mix Shader Fac from ray type dropped silently | per-hit input (path state) | both | light_path | P3 |
| 10 | #992 Float Curve and RGB Curves unsupported by the op-VM | op-VM coverage | both | curves_geometry | P3 |
| 11 | #881 (existing) Noise pattern differs from Cycles (corr 0.73) | pattern fidelity | both | wood (pattern) | P3 |

Linked, not duplicated: #955, #881, #954 (GPU single-texture programs, related to #994/#995), #890, #872 (related to #996).

## Input to the P4 fork note (bounded op-VM vs per-hit graph)

Count of materials whose failing legs name each category (primary or contributing), out of 8:

| Category | Issues | Materials | (material, backend) legs |
|---|---|---|---|
| per-hit input | #989 #990 #991 | car_paint, curves_geometry, attributes, light_path (4) | 8 primary |
| closure composition / export | #988 #995 #955 | marble, wood, pbr_group, shader_stack (4) | 6 primary (+2 where #994 is primary) |
| op-VM bound (`VM_MAX_SLOTS`) | #993 | wood, shader_stack (2) | 4, contributing only |
| op-VM node coverage | #992 | curves_geometry (1) | 2, contributing |
| GPU-only | #994 | marble, wood (2) | 2 primary |

Read: the bound is hit by one ordinary material chain (wood Roughness) and by shader_stack, but in neither case is it the
only cause; nothing here fails on the bound alone. Per-hit inputs (4 materials) and closure composition (4) dominate.
Two facts weigh on the fork: (a) 3 of 4 per-hit issues are node types with no path to the shading context at all, which a
larger bounded program does not fix; (b) the largest single error is a closure-composition export choice (#988), not a
VM limit. This is evidence, not the decision.

## Method and caveats

* Scenes are code (`build_corpus.py --families prod_*`), one Blender process each. Rebuilds are structurally identical
  (ROIs, node ids, object census, triangles, checked by `test_rebuild_is_structurally_identical`), **not byte-identical**:
  Blender 5.2 writes zstd `.blend` bytes that differ between two builds of one script (also true of the committed
  `v2_textures_opvm`). The manifest SHA pins the committed file and `load_corpus_manifest` fails closed on a mismatch.
* Bands: 5 seeds (278, 1301, 2711, 4177, 6113), deliberately not 278-282: #986 shows adjacent CPU seeds overlap
  (seed + tile streams), which under-estimates sigma. Gate seed 278; `tol = max(0.02, 3 sqrt(s_cycles^2 + s_astroray^2))`.
* High-variance ROIs (glass, sun highlight) keep their unclipped 3-sigma band, up to 2.1 in `prod_light_path`
  `glass_ball_centre`; the other ROIs of that material carry the gate.
* Build: measurements use the pkg298 CUDA build (`Astroray-ap-298/build_cuda`, main a84204d9 content) with the addon
  Python of this branch (main f0f8b5f6, which adds #953's Principled layering albedo, a few percent on Principled
  diffuse). Every failing row misses by >= 10 % on some channel, so no strict xfail depends on that shift; re-measure
  on the next CUDA build before re-blessing bands.
* Physics over Cycles look-parity (owner): no divergence row is needed; every failure is an Astroray gap.
* Textures are procedural (packed into the `.blend`); the HDRI is CC0 Poly Haven `syferfontein_18d_clear_1k`.

## Contact-sheet verdict

Lane inspection (Sonnet 5.5) of all eight sheets: scenes, ROIs and references are sound (ROIs sit on the textured
regions; Cycles shows the intended pattern in every material). Astroray CPU and GPU agree with each other except in
marble/wood (GPU flat, #994) and `prod_light_path`. Observed: car paint keeps coat and highlights but loses the
facing-dependent tint; attributes render white; shader_stack renders one opaque brown; light_path shows the emitter and
a grey floor; pbr_group keeps the tile layout but loses the chrome tiles; marble and wood keep the pattern (wood
orientation differs). No sheet suggests a scene or reference defect. **Opus sign-off 2026-09-30 (lead): sheets valid; failures match filed issues (marble GPU flat = #994; car-paint facing-ratio tint missing = #989; light-path camera-vs-lit floor colour = #991); no scene/reference defect.**

## Lessons

* Log-derived silent-drop auditing needs the matrix to be trustworthy; 32 of 39 strict hits were matrix rows, so #996
  was rank 1 for the audit to become a gate rather than a to-do list (done: 7 real pairs remain).
* A quick "disable the lobes in both engines" A/B (marble) separated a lobe deficit from a pattern error in one run;
  the same trick is worth building into the corpus tooling for the fixing PRs.

## After lane aq-nodes2 (#1004 root cause, #1005 report; 2026-10-02)

* **#1004 was not a node-group problem.** Blender's `inline_shader_nodes()` already folds the group Tiling input into
  `Mapping.Scale = (3, 3, 1)`. The engine clamped every image sample to [0,1] (no Image Texture `extension`), so a
  Mapping scale > 1 smeared edge texels; the Normal Map / Bump image uploads also dropped their `Vector`/Mapping.
  Fix: `GImgExt` REPEAT / EXTEND / CLIP / MIRROR on CPU `ImageTexture` + GPU `gpu_sampleImageTexture` (Cycles
  `kernel/device/cpu/image.h`, Apache-2.0), tagged from `node.extension` (Blender default REPEAT; untagged native
  textures stay EXTEND). prod_pbr_group: CPU 2/16 -> 8/16, GPU 2/16 -> 7/16 channels; tile layout now matches Cycles.
  Residual (centre ~0.91-0.93x, GPU right ROI B 1.42x): not Closest-vs-Linear alone (Cycles Closest vs Linear <= 4 %).
  Suspect: bump/normal finite-difference step is taken after the Mapping (slope off by the Mapping scale), see #1004.
* **#1005**: a procedural Bump Height is now a reported DEGRADED entry (was silent). The CPU can difference any texture
  (`Texture::valueDisplaced`, exact world-space derivative; verified equal to the image-ramp bump), but it is ~2x
  stronger than Cycles' pixel-footprint finite difference on prod_car_paint (lit_front B 1.41x, upper_flake B 0.68x) and the
  CPU sheet turns sparkly while the GPU (image-only bump) cannot do it, so the addon does not bind it until per-hit
  footprint differentials exist. prod_car_paint stays 5/16 CPU, 2/16 GPU (unchanged).
* No strict xfail row was removed: every affected row still fails on a residual cause (reasons updated).
* Shade kernels: REG 254 unchanged; STACK +64 B on two `stageShadeBucketedKernel` variants (4472 -> 4536).

## After lane ar-1007 (#1007 GPU per-hit Noise / Wave / Voronoi; build c5a26eac, 2026-10-02)

The GPU evaluates the procedurals per hit (shared host + device code, `include/astroray/procedural_tex.h`) instead of
the #994 64^3 voxel bake. CPU output unchanged (marble / wood CPU renders bit-identical to main). Sphere region, 8 px
blocks, |GPU - CPU| / mean, seed 278: marble 3.7 % (main bake 6.0 %, CPU seed-to-seed 3.3 %), wood 5.9 % (main bake
14.9 %, CPU seed-to-seed 4.7 %). The contact sheets lose the voxel blocks (marble) and concentric aliased rings (wood).
#1017 (same lane): procedural op-VM inputs lost their Mapping on the CPU (the addon gave the ProgramTexture the
legacy 2-D transform, which never moves the point a procedural reads) and hence on the per-hit GPU; the program now
carries the inputs' 3-D Mapping matrix (all inputs share one signature). Unmapped materials export the same calls
(marble CPU bit-identical to main). Wood vs Cycles, channels in band: CPU 1/16 -> 4/16, GPU 5/16 (main bake, an
aliased field rotated differently) -> 0/16 (#1007 alone) -> 3/16 (#1007 + #1017); the rings are now horizontal as in
Cycles. Remaining wood residual: band phase / spacing, rows re-pointed to #1006 (world-not-local Object coords,
sphere at z = 0.9) / #881 / #993. Marble GPU 8/16 re-pointed to #1006 (the CPU's residual).

## After lane au-coords (#881 Noise parity, #1006 object-local Object coords; build 0d494227, 2026-10-03)

**N/8 now 1/8 on both backends: prod_marble passes** (parity 16/16 CPU and GPU; its silent rows were removed by
#1028). Seed 278, same build, before = main a97e97ee content (ar-1007 build):

| Material | CPU in band (before) | GPU in band (before) | Residual |
|---|---|---|---|
| prod_marble | **16/16** (11) | **16/16** (8) | none (strict xfails removed) |
| prod_wood | 7/16 (4) | 6/16 (3) | #993 Roughness chain flattened (too glossy, sun highlight) + #1005 procedural Bump not applied |
| other six | identical | identical | unchanged |

* **#1006**: the addon bakes `matrix_world^-1` per triangle vertex (`set_objects_object_transform`; GPU side table
  `triObjectLocal`, read by `gpu_objectCoord`). Texture Coordinate > Object is now object-local, as in Cycles
  `NODE_TEXCO_OBJECT`. Object-coordinate materials skip the GPU instancing fast path (flattened, one frame per dupli).
* **#881**: the 3D Perlin port was already exact. The defects were (1) Noise **Fac** wired straight into a colour
  socket loaded the Color triple, and (2) 1D/2D/4D (and W) were evaluated as 3D. Cycles render probe (Diffuse under
  a uniform white world, 64 spp; min channel r over coplanar tiles):

  | | before | after (CPU = GPU) |
  |---|---|---|
  | 3D / 2D / 4D / Color / distortion / fractional detail / Object coords | -0.49 to -0.10 | >= 0.9989 |
  | multifractal / ridged | negative | 0.88 / 0.92 (slope 1.00 below albedo 0.9: Astroray clamps Diffuse albedo > 1) |
* Lesson: tiles at different heights shade each other's sky (r 0.94-0.98 with occlusion vs 0.999 coplanar); probes
  that isolate a texture need coplanar geometry under a uniform world.

## After lane at-n1 (#991 Light Path, #990 attributes; build b4e15d06, 2026-10-03)

| Material | CPU in band (was) | GPU in band (was) | Now blocked by |
|---|---|---|---|
| prod_light_path | 17/20 (4) | 14/20 (8) | #1038 plain-Glass bias (glass centre r 1.07-1.10, identical with the Mix Shader replaced by its Glass BSDF); GPU floor +2 % (GPU/CPU 1.007 without Light Path) |
| prod_attributes | 0/16 (0) | 0/16 (0) | #993: the Base Color chain needs 10 op-VM slots (reported); pkg314 graph programs host it |
| others | unchanged | unchanged | |
| **Materials passing** | **1/8** (prod_marble, #1006) | **1/8** | |

* **#991 Light Path** (Cycles `svm/light_path.h`, `path_state.h`; shared service `include/astroray/light_path.h`): per-hit
  path state (CPU integrator locals, GPU `GPUWavefrontState.lp_state`), op-VM `OP_SHADING` outputs, and a Mix Shader with a
  boolean Light Path Fac as a per-ray closure switch (CPU `LightPathMixMaterial`, GPU `GLightPathSwitch` intersect remap,
  shadow-context `shadowAlpha` / `gpu_shadow_transmittance`, emission context = child A). Hidden emitter 0.07x -> 1.00x,
  floor Ray Length tint and shadow-transparent glass match Cycles. A transparent pass keeps the ray flags (found on the
  first build: the camera ray hit the hidden emitter's inner back face as a non-camera ray and went black).
* **#990** (Cycles `svm/attribute.h`, `svm/geometry.h`; service `include/astroray/attribute_layers.h`): per-corner
  attribute layers filled at mesh export with Cycles' output value; Object Info Random reproduces Cycles exactly.
* **Bands:** prod_light_path re-blessed from the 5 production seeds (only that block): the old CPU sigma 0.41 at the
  glass centre measured the constant-mixed glass of the flattened export.
* **Silent drops:** the remaining prod_light_path / prod_attributes pairs are exactly the sockets this lane handles; the
  generated matrix (#1028) has no output-socket evidence and does not scan the Mix Shader branch (#1039).
* Registers vs post-#1023: generic shade variants <= 255 (HasProgram +64 B stack), fleet p0 128/432 and p1 198/4904
  unchanged, intersect +2 REG; the Light Path / attribute bodies are out of line (`shading_inputs_eval.cu`). Build 694 s.

## After lane at-n2 (pkg314 graph IR + value programs, #993, #992; build 7a4efb91, 2026-10-03)

| Material | CPU in band (post-#1023) | GPU in band (post-#1023) | Still blocked by |
|---|---|---|---|
| prod_wood | 7/16 (4) | 7/16 (3) | #1006 / #881 ring phase and spacing (grain_center B 0.90-0.92x, lower 1.13-1.16x) |
| prod_curves_geometry | 0/16 (0) | 3/16 (2) | Pointiness (Base Color chain Noise -> RGB Curves -> Mix is reported, not evaluated) |
| others | unchanged | unchanged | as above |

* #993: the wood Roughness chain compiles (4 peak slots with last-use reuse; the op-VM's monotonic allocator needed > 8) and
  runs as a graph program on both backends; no `VM_MAX_SLOTS` report. grain_left in band, grain_right L 1.00 (CPU).
  The spurious sharp sun highlight (constant roughness) is gone on both backends (contact sheet).
* #992: Float Curve / RGB Curves / Vector Curves are graph opcodes (Cycles `svm_node_curve(s)`, 257-entry LUT,
  extrapolation, combined-curve composition, factor). prod_curves_geometry Roughness (Noise -> Float Curve -> ...)
  evaluates; its Base Color chain stays reported because it also reads Pointiness.
* IR stats for every production + corpus v2 program root: `.astroray_plan/docs/pkg314-ir-stats.md` (largest program
  9 instructions / 5 slots; max closures 4, prod_shader_stack).
* No strict xfail removed: every material keeps a residual cause. prod_attributes' Base Color chain needs 10 op-VM
  slots: it routes to a graph program once lane at-n1 (#990) lands (whichever PR merges second re-runs it).

# pkg310 production node-tree corpus: baseline and gap burn-down (2026-09-30)

Eight production materials (`benchmarks/reference_corpus/production/`), rendered Cycles 5.2 LTS (1024 spp reference) vs
Astroray CPU and GPU (64 spp, seed 278, adaptive off, denoise off), bands from 5 seeds. Charts and contact sheets:
`test_results/textures-nodes/production-corpus/` (`<material>_sheet.png`, `band_utilisation_chart.png`,
`production_summary.json`, `silent_drops.json`). Gate: `tests/test_production_corpus.py` (32 strict xfails, each tied to
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

## Silent drops

Strict definition (spec): an exercised (node, socket) pair, reachable from the active output and linked or non-default,
that the frozen coverage matrix does not classify SUPPORTED and that no DegradationReport entry names. Four deliberate
deviations (in the `silent_drop_audit.py` docstring): Output-node inputs are never drops; the shared `world:` tree is
excluded (counted, identical in all eight scenes); output sockets are judged only for node types the matrix has `output:`
rows for; APPROXIMATED pairs with no report go to a separate unscored `approximated_unreported` bucket. **39 unique
(material, node, socket) pairs**, identical on CPU and GPU (one Blender export path). Rules and the separate
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

Triage: **7 are real drops** (no report and the render is wrong): AddShader x2 (#955), MixShader Fac/Shader x3 from
Light Path (#991), VertexColor (#990), RGBCurve (#992). **The other 32 are matrix-stale** (#996): the render reports
"CPU exact" for those op-VM chains, and disabling the specular lobes in both engines brings `prod_marble` CPU to
0.95-1.04. The matrix (pkg229) keys inputs by UI name, marks whole nodes APPROXIMATED, and was frozen by pkg278, so
it was not touched here (non-goal). Non-vacuity: `silent_drop_audit.py --self-test` (fixture with an unhandled Attribute
node is flagged, is not flagged once reported, an unreachable Layer Weight is never exercised) and
`test_audit_flags_the_real_attributes_material`.

## Ranked backlog

One issue per root cause. Rank: materials whose failing rows name it, then plan-section-1 P-phase. Category is the
theme-1 taxonomy; observable and threshold are in each issue.

| # | Issue | Category | Backend | Materials | Phase |
|---|---|---|---|---|---|
| 1 | #996 coverage matrix marks op-VM-handled sockets DROPPED-SILENT (tooling; 32 of 39 silent pairs) | tooling | both | 7 (silent rows) | P0 |
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

* Log-derived silent-drop auditing needs the matrix to be trustworthy; 32 of 39 strict hits are matrix rows, so #996
  is rank 1 for the audit to become a gate rather than a to-do list.
* A quick "disable the lobes in both engines" A/B (marble) separated a lobe deficit from a pattern error in one run;
  the same trick is worth building into the corpus tooling for the fixing PRs.

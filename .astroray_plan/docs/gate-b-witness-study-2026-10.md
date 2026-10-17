# Gate (b) witness control kinds study (pkg323, 2026-10-18)

**Status: CPU measured, GPU legs pending (lead runs them, commands below). Nothing frozen, no gate changed.** `coverage_input_v4*.json`,
the predicate and `acceptance_manifest.json` are untouched; `--score` output is byte-identical before and after this branch
(`astra_run\2026-10-18\pkg323\score_before` vs `score_after`, `cmp` clean). Evidence: `astra_run\2026-10-18\pkg323\study\`
(`study_CPU.json/.md`, `sheets\*_CPU.png`, `sheets_contact\`, `witness_candidates_v5.json`, fresh `node_uses_*.json`, the 4 retained legs per witness under `CPU\`).

## What was built

- Control kinds in `render_leg.py` (reversible, receipt-recorded, one target node): `noise_const` / `wave_const` (the node's linked outputs are
  re-fed from a constant 0.5 Value/RGB node; the target is untouched), `brick_const` (Color1 = Color2 = Mortar = mean of the first two),
  `bump_zero` (Strength 0), `mapping_identity` (Location 0, Rotation 0, Scale 1). A control that would change nothing raises (no silent no-op).
- Mask kind `object_faces`: every face of the object projected through the camera, kept only where the camera ray's first hit is that object, eroded 4 px
  (`inset_px`). Needed because `object_polygon` takes `polygons[0]` only.
- `witness_metrics(..., region="rect"|"mask")`: `rect` (default) is the frozen computation, same keys and values. `mask` averages the *same* per-pixel SSIM and dE2000
  maps over the feature pixels instead of the ROI rectangle. An effect may carry `kind` (default `checker`, i.e. the frozen two-sided phase probe; the new kinds use `changed`).
- `coverage_report.py --study-enumerate | --study | --study-report` and `witness_candidates_v5.json` (27 candidates; not read by `--score`).
  Tests: `tests/test_pkg323_control_kinds.py` (19 tests; a real headless Blender renders a five-card Cycles scene: each kind changes only its target node, the card changes, every pixel
  away from the card is bit-identical).

## Selection rule (mechanical; `STUDY_SELECTION_RULE` in `coverage_report.py`)

Applied to the nine-scene population and the candidate-v2 population (8 `v2_*` + 8 production scenes, 25 scenes), at the corpus-declared resolution, spp and seed 7:

- R1 node reachable from an active output (computed trace), not muted, one of the five families, in a material tree (not world, light or group).
- R2 its material is assigned to exactly one mesh object (so one screen-space region).
- R3 that object's camera-visible mask, eroded 4 px, has >= 300 px.
- R4 the control would change something.
- R5 one witness per (scene, variant digest): the largest mask wins; the others are recorded as covered by it.
- ROI = visible-face bounding box padded 10 %, clipped, 4 places. Effect threshold (a priori, same for every new kind): mean |baseline - control| over the mask > 0.01 and > 5 % of mask pixels above 0.01, in both engines.

Result: 27 witnesses (Noise 13, Wave 5, Mapping 5, Bump 3, Brick 1), 6 excluded (`witness_candidates_v5.json` -> `excluded`):
prod_pbr_group Bump and Mapping (inside a node group), world_sky_hdri Mapping (world tree), materials_hall Noise and Bump (bust, 237 visible px), textures_mapping VectorRotateCard Mapping
(299 px; it shares digest 7c2bf20656 with VectorMixCard, which is registered instead).

## Build and settings

CPU legs: a copy of the lead's `build_cuda` module made 2026-10-18 00:38 (`build_id` "dev", module sha256 `53cf7d35...e77361`, addon sha256 `8885d152...ed381`; predates #1116 / #1123 glass, which
these families do not touch), Blender 5.2.0 LTS, `CUDA_VISIBLE_DEVICES=-1`, 8 threads, corpus-declared settings (textures_mapping 960x540 @ 192 spp; production 320x240 @ 64; v2 480x270 @ 64), seed 7,
no denoise, no adaptive. A leg re-run is bit-identical (checked on CardNoise). Cycles legs are CPU and do not depend on the backend, so the GPU run reuses them.

## Verdicts (witness x predicate x backend)

Predicate = effect shows in both engines AND ssim >= 0.95 AND dE2000 <= 5, over the ROI rectangle (`rect`, frozen) or the feature mask (`mask`, proposed).

| witness | family | mask px | rect CPU | mask CPU |
|---|---|---|---|---|
| prod_car_paint/Hero/Bump | Bump | 17894 | NO-EFFECT | NO-EFFECT |
| prod_curves_geometry/Bowl/Noise Texture | Noise | 14431 | FAIL 0.640/4.85 | FAIL 0.585/4.93 |
| prod_marble/Hero/Mapping | Mapping | 17894 | FAIL 0.711/3.93 | FAIL 0.580/4.84 |
| prod_marble/Hero/Noise Texture | Noise | 17894 | FAIL 0.711/3.93 | FAIL 0.580/4.84 |
| prod_marble/Hero/Wave Texture | Wave | 17894 | FAIL 0.711/3.93 | FAIL 0.580/4.84 |
| prod_shader_stack/Hero/Noise Texture.001 | Noise | 17894 | NO-EFFECT | NO-EFFECT |
| prod_shader_stack/Hero/Noise Texture | Noise | 17894 | NO-EFFECT | NO-EFFECT |
| prod_wood/Hero/Bump | Bump | 17894 | NO-EFFECT | NO-EFFECT |
| prod_wood/Hero/Wave Texture | Wave | 17894 | FAIL 0.732/3.69 | FAIL 0.678/4.59 |
| prod_wood/Hero/Mapping | Mapping | 17894 | FAIL 0.732/3.69 | FAIL 0.678/4.59 |
| prod_wood/Hero/Noise Texture | Noise | 17894 | FAIL 0.732/3.69 | FAIL 0.678/4.59 |
| v2_textures_opvm/RoughnessProg/Noise Texture | Noise | 2079 | FAIL 0.937/2.13 | FAIL 0.910/3.34 |
| v2_textures_opvm/CardMapAfterWarp/Noise Texture | Noise | 2809 | PASS 0.997/0.51 | PASS 0.996/0.51 |
| v2_textures_opvm/CardWave/Wave Texture | Wave | 2809 | PASS 0.999/1.23 | PASS 1.000/1.53 |
| v2_textures_opvm/CardMapAfterWarp/Mapping | Mapping | 2809 | PASS 0.997/0.51 | PASS 0.996/0.51 |
| v2_textures_opvm/CardNoise/Noise Texture | Noise | 2809 | PASS 0.999/0.41 | PASS 0.999/0.32 |
| textures_mapping/TexWaveRings/Wave Texture | Wave | 857 | PASS 0.999/0.83 | PASS 1.000/0.62 |
| textures_mapping/DisplacementDemo/Noise Texture | Noise | 1756 | NO-EFFECT | NO-EFFECT |
| textures_mapping/CurvesCard/Noise Texture | Noise | 1424 | PASS 0.981/0.96 | PASS 0.988/1.15 |
| textures_mapping/TexBrick/Brick Texture | Brick | 786 | PASS 0.978/1.19 | PASS 0.991/1.42 |
| textures_mapping/BumpDemo/Bump | Bump | 1583 | NO-EFFECT | NO-EFFECT |
| textures_mapping/Noise4DCard/Noise Texture | Noise | 464 | NO-EFFECT | NO-EFFECT |
| textures_mapping/TexNoise/Noise Texture | Noise | 857 | PASS 0.998/1.95 | PASS 0.999/2.24 |
| textures_mapping/VectorMixCard/Mapping | Mapping | 300 | PASS 0.996/1.17 | PASS 0.997/0.57 |
| textures_mapping/TexImage/Mapping | Mapping | 1082 | PASS 0.986/1.52 | PASS 0.990/1.17 |
| textures_mapping/TexWaveBands/Wave Texture | Wave | 858 | PASS 1.000/0.49 | PASS 1.000/0.19 |
| textures_mapping/Noise2DCard/Noise Texture | Noise | 599 | NO-EFFECT | NO-EFFECT |

Cell = verdict ssim/dE2000 (predicate: effect passes in both engines, ssim >= 0.95, dE <= 5).

Per-leg numbers (effect values, relative effect, masked and outside-mask mean ratios Astroray/Cycles): `study_CPU.md`.

## What the sheets show (all 27 inspected: Astroray | Cycles | |diff| x3 | mask on top, the two controls and their |change| below)

- Card witnesses agree closely: TexNoise, TexWaveBands/Rings, TexImage and VectorMix mapping, v2 CardNoise/CardWave/CardMapAfterWarp are visually identical patterns; the diff panel is MC noise and thin edge lines.
  Neutralising the feature flattens the card to a constant in both engines.
- Production hero spheres (marble, wood, curves bowl, roughness sphere): patterns and controls match by eye; the SSIM (0.58-0.73 on 64 spp) is MC noise between independent renders, not a feature difference. Masked mean ratios are 0.96-1.01.
- Real engine differences the witnesses surfaced (not investigated or fixed here):
  - Bump has zero effect in Astroray (|effect| = 0.0000, 0 % coverage) in all three scenes (prod_car_paint Voronoi height, prod_wood procedural height, textures_mapping BumpDemo) while Cycles shows 0.056 / 0.015 / 0.009; the Cycles bump is visible on the sheets and the Astroray sphere is smooth. The matrix says SUPPORTED.
  - textures_mapping DisplacementDemo: Cycles shows the Noise-driven displacement, Astroray a smooth sphere (effect 0.000 vs 0.009).
  - prod_shader_stack: Astroray renders a flat orange sphere where Cycles shows the glass/translucent mix; masked mean ratio 0.50/0.34/0.14 and zero effect for both Noise nodes in Astroray.
  - Brick: the control does not neutralise Astroray (pattern persists, effect 0.029 vs Cycles 0.320). `blender_addon/__init__.py` reads the mortar colour from `inputs['Color3']`, which does not exist on the Blender 5.2 Brick node (it is `Mortar`), so the mortar stays black. The baseline matches Cycles only because the authored mortar is black. Same family as the DROPPED-SILENT `TexBrick|input:Mortar` row (pkg321 / #1089).
  - CurvesCard: Cycles' control is magenta, Astroray's grey (RGB/Vector curves downstream of a constant); the controls are not the same image there.
- Noise2DCard and Noise4DCard are dim lit diffuse cards (signal 0.018 / 0.038): the Noise effect is 14-17 % of the signal in both engines but 0.003-0.005 absolute, so the a-priori 0.01 threshold marks them NO-EFFECT.

## Provisional score

If exactly these witnesses were registered (score_use rule: an identity scores only when every (scene, variant) it is exercised in has a passing witness; SUPPORTED identities only; weights from a fresh collect of the current corpus):
`rep` = a witness credits only its registered representative identity, `fanout` = it credits every exercised identity of its node (sockets, outputs, properties).

| population | predicate | credit | S_CPU |
|---|---|---|---|
| candidate_v2 | rect | rep | 0.000 |
| candidate_v2 | rect | fanout | 0.002 |
| candidate_v2 | mask | rep | 0.000 |
| candidate_v2 | mask | fanout | 0.002 |
| nine_scene | rect | rep | 0.004 |
| nine_scene | rect | fanout | 0.058 |
| nine_scene | mask | rep | 0.004 |
| nine_scene | mask | fanout | 0.058 |

Cases needed to credit a family completely:

| population | family | (scene, variant) cases needed | candidate witnesses | missing (and why) |
|---|---|---|---|---|
| candidate_v2 | Bump | 3 | 2 | prod_pbr_group:9a9ae0302d R1 not a material tree (group) |
| candidate_v2 | Mapping | 4 | 3 | prod_pbr_group:f7690f0700 R1 not a material tree (group) |
| candidate_v2 | Noise | 8 | 8 | - |
| candidate_v2 | Wave | 3 | 3 | - |
| nine_scene | Brick | 1 | 1 | - |
| nine_scene | Bump | 2 | 1 | materials_hall:9b5e7a5e56 R3 visible mask 237 px < 300 |
| nine_scene | Mapping | 3 | 2 | world_sky_hdri:64d09eff90 R1 not a material tree (world) |
| nine_scene | Noise | 6 | 5 | materials_hall:99eff2a2d1 R3 visible mask 237 px < 300 |
| nine_scene | Wave | 2 | 2 | - |

- Verdicts are identical under rect and mask for all 27 witnesses on CPU (11 pass, 8 NO-EFFECT, 8 fail ssim), so S is identical under both predicates: nine-scene 0.004 (rep) / 0.058 (fanout), candidate-v2 0.000 / 0.002.
  The matrix-only ceiling is 0.42 (0.64-0.69 once pkg320 credits are counted); the same witnesses all passing would give 0.062 (nine) / 0.127 (candidate-v2) under fan-out, so witnesses alone cannot reach 0.95.
- GPU: S_GPU pending the lead's run.

## Owner question (#1087), as the axes the data shows (not a ballot)

1. **Rectangle vs mask.** On these 27 witnesses it changes no verdict (CPU). Cards fill their ROI, and on noisy hero objects the mask SSIM is lower than the rectangle's (it drops the smooth floor). The checker failure in #1087 was the #1099 emission bug, fixed since. Switching the region is harmless and principled but is not what limits S.
2. **Noise.** All hero-object witnesses (production, 64 spp) fail SSIM at 0.58-0.73 and sit at dE 3.7-4.9 against a limit of 5 under both regions, with visually matching renders: independent MC noise, the same trap as gate (c) before the Welch-1b adoption. A noise-aware metric (Welch tiles, or ratio of the masked means) or more spp is what unlocks production witnesses (candidate-v2 ceiling 0.127 vs 0.002 measured).
3. **Credit granularity.** Per-identity credit (`rep`) gives 0.004; crediting every exercised socket/output/prop of a witnessed node (`fanout`) gives 0.058. A node-level counterfactual proves the node's output path, not that each input is honoured (Brick Mortar is the counter-example above). Per-socket controls multiply the case count.
4. **Eligibility.** Mapping and Bump can never reach full credit with screen-space witnesses alone: world-tree Mapping, node-group Bump/Mapping and the 237-px materials_hall bust have no eligible region. Needs a world witness (sky rays) and a group-instance region, or those identities stay at 0; also whether R3's 300 px floor should be lower.
5. **Effect check.** The absolute 0.01 floor drops dim cards; a relative floor (effect / signal) would admit them. An effect-parity check between engines would have flagged Brick (0.029 vs 0.320) and Bump (0 vs 0.056) as not equivalent counterfactuals.
6. **Engine work the witnesses already justify** (independent of the predicate): Bump from procedural heights, Displacement from Noise, the shader-stack Mix/Add chain, Brick Mortar input, curves downstream of constants.

## Caveats

- Frozen inputs are stale on main, so `--score` on `coverage_input_v4.json` reports UNMEASURED today (scene bytes changed by #1113, matrix hash changed by pkg320, registry ROI differs from the frozen case). The committed `populations/nine_scene.json` is stale too (textures_mapping hash and crops). The study uses fresh derived manifests and fresh collects, never the repo copies. A re-freeze belongs to its own change.
- One a-priori effect threshold, nominal constant 0.5 for Noise/Wave (not the measured texture mean), one 4 px mask erosion; none tuned. Seed 7 only, one build, CPU only so far.
- `_gate_c_mask` kind `sky_rays` (not touched) pairs the view-frame corners with u and v swapped (`frame[0].lerp(frame[1], u)` runs along the vertical edge); the new `object_faces` mask uses the corrected mapping and was checked against projected geometry. Worth a look before the sky mask is relied on.
- Production witnesses on one hero object share one parity verdict (the baseline is the same render); only the effect column differs per node.

## Reproduce / GPU legs for the lead

```
cd <worktree pkg323>
set ASTRORAY_PYD_DIR=<worktree>\build_lane            (a CUDA build; not the one being relinked)
python <main>\scripts\build\gpu_locked_run.py pkg323 -- python -m benchmarks.reference_corpus.coverage_report --study --backend GPU ^
  --study-out <EV>\study --candidates benchmarks\reference_corpus\witness_candidates_v5.json --cycles-from <EV>\study\CPU ^
  --study-node-uses nine_scene=<EV>\study\node_uses_nine_scene.json --study-node-uses candidate_v2=<EV>\study\node_uses_candidate_v2.json
python -m benchmarks.reference_corpus.coverage_report --study-report --study-out <EV>\study      (writes study_combined.md with CPU + GPU columns)
python <main>\scripts\build\gpu_locked_run.py pkg323 -- python -m pytest tests/test_pkg323_control_kinds.py -m gpu -q
```
(`<EV>` = `C:\Users\hgcom\OneDrive\Astroray\astra_run\2026-10-18\pkg323`.) CPU: same `--study` with `--backend CPU` and `CUDA_VISIBLE_DEVICES=-1`; candidates: `blender --background --factory-startup --python benchmarks/reference_corpus/coverage_report.py -- --study-enumerate --study-out <dir> --candidates <file>`.

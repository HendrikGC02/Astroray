# Architect plan 2026-11-01: the Stage 0 exit path

State+refine round, asked for by the 10-31 lead. It ran on Opus 5.5, the architect agent's pinned model, because the app
does not let a session switch its own model; the owner can pick Fable from the model menu. Previous plan:
`architect-plan-2026-10-25.md`. Inputs: STATUS 10-31, `stage0-gate-scoring-2026-10-18.md`,
`next-session-prompt-2026-10-25.md`, `gate-b-provisional-score-2026-10.md`, `gate-b-witness-study-2026-10.md`, the 94 open
issues (Haiku digest, 10-31 gate (e) ratings joined), and a numpy-only re-score of the 10-31 row (g) renders
(`mc_tolerance.score_material` on `%LOCALAPPDATA%\astroray-evidence\2026-10-31\g\renders`; counts match STATUS).

## 1. State (main `f477f024`, 10-31 numbers)

| Row | Status | Measured | In the committed manifest | Next mover |
|---|---|---|---|---|
| (a) latency | GREEN | p95 62.9 / p99 100.6 ms on `3bb710b` (10-18) | **unmeasured** (green only in the scratch `acceptance_manifest.ac2.json`) | re-measure on the exit build |
| (b) coverage | RED | first formal score 10-25: nine_scene 0.00213, owner population 0/474; b4 19 drops | unmeasured | pkg328, owner (§5 Q1) |
| (c) trio | GREEN | Welch-1b 0 rejected tiles on `3bb710b` (10-18) | **unmeasured** (scratch `acceptance_manifest.c.json`) | re-measure on the exit build |
| (d) adaptive + denoise | GREEN | `132c974` (10-04) | green | re-measure on the exit build |
| (e) triage | RED | 5 high on 85 open (10-31): #1174 #1178 #1180 #1186 #1198, all in lanes | red, 8 high (10-24 snapshot) | lanes, then re-rate |
| (f) clean install | waits | — | unmeasured | owner's second PC |
| (g) node score | RED | CPU 2/8, GPU 2/8, 0 silent pairs | unmeasured | §2.1 |

**The exit needs one committed `acceptance_manifest.json` with every row green.** Today it has only (d). The (a) and (c) greens
are in scratch manifests whose evidence is under `%LOCALAPPDATA%`. Since 10-25 alone, seven engine merges touched transport
or shading (#1170 #1181 #1187 #1189 #1191 #1192 #1197). Those two rows have to be re-measured on the exit build and committed
with repo-relative evidence (memory `gate-manifest-instrument-paths-must-be-repo-relative`).

Row (g) per channel (ratio to Cycles; CPU / GPU):

| Scene | CPU | GPU | Out of band | Residual owner |
|---|---|---|---|---|
| attributes, marble | 16/16 | 16/16 | — | — |
| curves_geometry | 15/16 | 15/16 | inner_backface r 0.842 / 0.851 | #1141, minor-channel cluster |
| light_path | 19/20 | 17/20 | CPU floor_near r 0.974; GPU floor_far g/b/L 1.021-1.027 | #1199 (CPU); GPU floor_far has no issue yet |
| car_paint | 14/16 | 2/16 | CPU lit_front b 0.922, upper_flake b 0.960; GPU 14 channels | #1153 lane; CPU = cluster |
| wood | 11/16 | 12/16 | b 0.909-0.961 in 4 ROIs; CPU also grain_center r 0.958, L 0.970 | cluster; grain_center r unexplained |
| pbr_group | 11/16 | 11/16 | CPU right r/g/b/L 1.18-1.29; lower b 0.922 / 0.939; GPU right 0.85-0.94 | firefly; #1156; cluster |
| shader_stack | 6/16 | 4/16 | right / lower / upper_left 0.88-0.98 | #995 1/eta^2 (owner); #1174 lane (GPU) |

Three readings change the plan:

1. **pbr_group CPU "1.23" is one firefly, not a regression.** In the 506-px right ROI, one pixel reads 23.1. The next is 1.39
   and the median 0.175. Without the top 3 pixels the ROI mean is 0.1838, against 0.1829 on 10-25 (`bdbe4f1c`), when the
   ROI was in band. CPU pbr_group is lower b plus a seed-278 tail.
2. **Nothing merged since 10-25 moved GPU (g).** The 10-25 and 10-31 GPU legs score the same for car_paint, light_path and
   wood, and within 0.01 for pbr_group. The GPU path runs through the lanes (#1153, #1174) and GPU twin bugs.
3. **A minor-channel cluster.** In curves, wood, car_paint (CPU) and pbr_group lower, the out-of-band channel is always the
   one the albedo has least of: R for the cyan curves, B for the warm wood, paint and PBR. It reads 4-16 % low, CPU ≈ GPU.
   #1141 measured the mechanism on curves: the spectral product ρ(λ)² of a near-gamut-edge albedo. Grey albedo matches
   (0.997) and a single bounce under a white world is exact. Cycles' RGB product cannot reproduce this, so no engine fix
   closes it. For the warm scenes the mechanism is **inferred**, not measured. An HDRI illuminant-upsampling term may add to
   it (#767's open candidate; the observer is already CIE 1931 2°). light_path floor_near r and wood grain_center r are
   major channels and fall outside the cluster.

## 2. Path to Stage 0 exit

### 2.1 Row (g) to 6/8 on both backends

| # | Item | Moves | Who / cost | Blocked on |
|---|---|---|---|---|
| 1 | Land lanes #1153, #1174, #1178/#1198, #1180/#1186; one (g) re-run after the batch, not per PR | car_paint GPU 2→~14/16; shader_stack GPU 4→~6/16 | lead (builds, GPU legs) | builds queued |
| 2 | **pkg327 Phase A**: attribute the cluster plus floor_near r and wood grain_center r with variants (grey albedo under the scene HDRI; scene albedo under a flat white world). Arbitrate on proxies with the pkg307 Mitsuba suite (`scalar_spectral` / `scalar_rgb` ratio vs Astroray / Cycles) | evidence only | Sonnet lane; CPU Blender + Mitsuba, **no GPU** | CPU budget (≤ 2 CPU-heavy jobs) |
| 3 | **pkg327 Phase B**: per-channel `expected_divergence` only on arbitration-confirmed channels; engine fix for anything else (e.g. illuminant upsampling) | curves 16/16 both; car_paint CPU 16/16; wood GPU 16/16; pbr_group lower b | Sonnet (gates) / Opus (engine) | owner Q2 |
| 4 | GPU twins: light_path floor_far +2.5 % GPU-only (GPU/CPU 1.007 without Light Path; file an issue); pbr_group GPU right ROI dim = #1156 (bump/normal-map twin drift) | light_path GPU 20/20; pbr_group GPU right | Opus lane + lead GPU legs | — |
| 5 | #1199 floor_near r 0.974, by the issue's own recipe (Lambertian-floor variant, R-only albedo sweep), folded into pkg327 Phase A | light_path CPU 20/20 | pkg327 lane | — |
| 6 | pbr_group CPU firefly: trace the seed-278 pixel and its path; pkg306 Phase 1 scope, no new spec | pbr_group CPU right | pkg306 lane | — |
| 7 | shader_stack: owner #995. Keep 1/eta^2: regenerate the Cycles reference with the inner emitter scaled by 1/n² (every other channel stays Cycles-checked; no ROI pin). Match Cycles: drop the factor in `ggx_glass_energy.h` CPU + GPU | shader_stack ~15-16/16 | Sonnet (ref) or Opus (engine) | owner Q3 |

Projection: items 1-5 give attributes, marble, curves, car_paint and light_path, which is 5/8. The sixth is wood (GPU is
B-only; CPU also needs grain_center r), pbr_group (#1156 plus the firefly) or shader_stack (#995). Without the divergence
treatment in item 3, curves cannot pass and the cluster scenes have no engine fix. That makes Q2 the main owner input for (g).

### 2.2 Row (b)

The facts:
- b1 is unsigned.
- b2/b3 score 0 on the owner population.
- b4 has 19 exercised drops. 11 of them are reported at runtime since pkg321 but stay DROPPED-SILENT in the matrix, because
  b4 reads the static classification, not the render log.
- b5 fails: Principled-advanced, Metallic and Sky have no witnesses, and nothing in the corpus exercises Displacement.
- b6 passes.

**0.95 is structurally out of reach as defined.** The matrix-only ceiling is 0.43 today, about 0.69-0.81 once scanner credits
land and Principled is lifted to SUPPORTED. If all 27 pkg323 witnesses passed, candidate_v2 would score 0.127 under fan-out.
Production witnesses fail SSIM on 64-spp MC noise, the trap (c) escaped through Welch-1b.

- **pkg328 Phase 1 (no owner dependency):** b4 counts only unreported drops. Reported drops still score 0 in b2/b3, so nothing
  is inflated. Resolve the 8 non-pkg321 rows (OutputWorld Surface / is_active_output, OutputMaterial target / Thickness,
  TexEnvironment Vector, TexImage interpolation, MapRange clamp) and re-check Coat Normal after #1157 / #1153. Each is a
  scanner credit backed by a probe render, an addon report or a real fix. Target: b4 green.
- **pkg328 Phase 2 (owner Q1):** freeze the pkg323 witnesses that fall on candidate_v2 under the predicate the owner picks for
  #1087, then score. This gives the first nonzero owner-population S.
- After Q1: a Displacement use in the corpus (scenes are replaceable, memory `corpus-scenes-replaceable`) and witnesses for
  Metallic, Sky and Principled-advanced (b5).

### 2.3 Row (e)

- The five highs are in lanes. Re-rate once after the batch merges, with the existing pipeline (two blind Sonnet raters plus
  flash, stricter wins).
- The Haiku digest predicts **#1201 high** under the literal rubric: a linked Thin Film Thickness/IOR silently becomes 0 nm on
  Glass, Principled and Metallic. It is small and addon-side. Give it the next free Sonnet lane before the re-rate.
- Predicted medium or low: #1200 #1204 #1206 #1207 #1208 #1209 (medium), #1202 #1205 (low). #1204/#1205 ride on #1178,
  #1207/#1209 on #1153, #1208 on #1186. Brief those lanes so the follow-ups land together where the code is shared.
- Structural: each parity review files 5-10 issues, a few of them high, so (e) swings back to red after every batch. Rate
  follow-ups at filing time, and fix a high inside the filing lane when it costs under one session.
- Closable after checking: #1004 (fixed by #1157), #1005 (CPU landed; the GPU half is #1153). #1128-#1136 titles say
  "silently", but the drops are now reported; retitle them so b4 and (e) raters read them correctly.

### 2.4 Exit manifest (a)-(g)

Cut an exit-candidate build once (g) reads 6/8 and (e) re-rates to 0 high. On it, re-measure (a) (visible isolated Blender),
(c) (Welch-1b) and (d), then (b) and (g). Rate (e) live. One heavy lead job at a time. Commit all rows with `gate_manifest.py`
and repo-relative evidence. (f) runs on the owner's second PC with the same ZIP.

### 2.5 Backlog: gate vs product

- **Gate-relevant:** the five highs; #1201; #1141, #1199, #1156, #1153, #1174 and #995 for (g); #1087, #1088, #1039 and the
  pkg321 set #1128-#1136 / #1140 for (b).
- **Medium, already rated, worth lane gaps:** #1031, #1164, #1184 and #1185 would rate high on a stricter re-rate.
- **Product, after exit:** #941 (QMC sampler) and #763 (CPU noise), #1024 (film keeps negative channels; science output),
  #1044, #924, #1034, media #967 #983 #1019 #1193 (#1032 in lane), the Disney/rough-glass twins #942 #956 #957 #1126 #783
  #789, the procedural bake #890 #1002, and #38 #39 #398 #141 #144. GR #894 #1081 #1082 stay paused with Pillar 4.

## 3. Waves (lead holds the GPU and the build queue; ≤ 2 CPU-heavy jobs)

| Wave | Lanes | Lead |
|---|---|---|
| W1 (now) | the five live lanes finish; pkg327 Phase A (Sonnet, CPU + Mitsuba) | builds, GPU legs, merges, one (g) re-run |
| W2 | #1201 (Sonnet); pkg328 Phase 1 (Sonnet, Python only); light_path GPU floor_far + #1156 (Opus) | (e) re-rate; GPU legs |
| W3 | pkg327 Phase B; #995 path per Q3; pkg328 Phase 2 per Q1; pkg306 Phase 1 firefly | (g) re-run |
| W4 | — | exit-candidate build, manifest re-measure (§2.4), closeout sweep, run report |

## 4. Specs filed

| Pkg | Name | Size / tier |
|---|---|---|
| **pkg327** | Row (g) minor-channel chroma residual: attribution, Mitsuba arbitration, per-channel divergence | M; Sonnet lane, Opus if an engine fix appears |
| **pkg328** | Gate (b) b4 burn-down and witness freeze on candidate_v2 | M; Sonnet lane, GPU witness legs via the lead |

Issue-sized work (#1201, #1156, light_path GPU floor_far, the shader_stack reference) goes to lanes from the issue, as on
10-31.

## 5. Owner questions

1. **Row (b) at exit** (new; the largest open input). The data shows three axes:
   - what earns credit: a witness per identity, or the matrix audited by a sampled witness set;
   - the predicate: SSIM, or Welch-1b as for (c) (#1087);
   - the threshold.

   As defined (witness per identity, SSIM, 0.95), (b) means months of witnesses plus engine support for every DROPPED
   identity in the population.
2. **Spectral chroma shifts** (new): once Mitsuba spectral reproduces a shift, does the 09-29 "physics over look-parity" rule
   cover it, with a per-channel divergence pin? The cost is that the pinned channel stops being checked against Cycles. The
   caveat is that an RGB-authored albedo has no unique spectrum: the shift is the upsampler's, not nature's.
3. **#995** (carried): keep the pbrt 1/eta^2 radiance factor (shader_stack gets a 1/n²-scaled Cycles reference) or match
   Cycles?
4. **b1** (carried): does the 10-06 population decision count as the sign-off?
5. Carried from 10-25 §5: pkg325 stays off by default (confirm); pkg324 README publishing and licences; material preset
   library scope; evidence storage (git / LFS / local); (f) second PC.

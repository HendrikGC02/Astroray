# Architect plan 2026-11-01: the Stage 0 exit path

State+refine round, asked for by the 10-31 lead. It ran on Opus 5.5, the architect agent's pinned model, because the app
does not let a session switch its own model; the owner can pick Fable from the model menu. Previous plan:
`architect-plan-2026-10-25.md`. Inputs: STATUS 10-31, `stage0-gate-scoring-2026-10-18.md`,
`next-session-prompt-2026-10-25.md`, `gate-b-provisional-score-2026-10.md`, `gate-b-witness-study-2026-10.md`, the 94 open
issues (Haiku digest, 10-31 gate (e) ratings joined), and a numpy-only re-score of the 10-31 row (g) renders
(`mc_tolerance.score_material` on `%LOCALAPPDATA%\astroray-evidence\2026-10-31\g\renders`; counts match STATUS).
The owner answered §5 on 2026-10-31; this revision records the answers.

## 1. State (main `f477f024`, 10-31 numbers)

| Row | Status | Measured | In the committed manifest | Next mover |
|---|---|---|---|---|
| (a) latency | GREEN | p95 62.9 / p99 100.6 ms on `3bb710b` (10-18) | **unmeasured** (green only in the scratch `acceptance_manifest.ac2.json`) | re-measure on the exit build |
| (b) coverage | RED | first formal score 10-25: nine_scene 0.00213, owner population 0/474; b4 19 drops | unmeasured | pkg328 (owner answers 1-4) |
| (c) trio | GREEN | Welch-1b 0 rejected tiles on `3bb710b` (10-18) | **unmeasured** (scratch `acceptance_manifest.c.json`) | re-measure on the exit build |
| (d) adaptive + denoise | GREEN | `132c974` (10-04) | green | re-measure on the exit build |
| (e) triage | RED | 5 high on 85 open (10-31): #1174 #1178 #1180 #1186 #1198, all in lanes | red, 8 high (10-24 snapshot) | lanes, then re-rate |
| (f) clean install | DEFERRED | — | unmeasured | past Stage 0; revisit at the first public release (owner 10-31) |
| (g) node score | RED | CPU 2/8, GPU 2/8, 0 silent pairs | unmeasured | §2.1 |

**The exit needs one committed `acceptance_manifest.json` with (a)-(e) and (g) green.** (f) is deferred. Today only (d) is
green there. The (a) and (c) greens are in scratch manifests whose evidence is under `%LOCALAPPDATA%`. Since 10-25 alone,
seven engine merges touched transport or shading (#1170 #1181 #1187 #1189 #1191 #1192 #1197). Those two rows have to be
re-measured on the exit build and committed with repo-relative evidence (memory
`gate-manifest-instrument-paths-must-be-repo-relative`).

Row (g) per channel (ratio to Cycles; CPU / GPU):

| Scene | CPU | GPU | Out of band | Residual owner |
|---|---|---|---|---|
| attributes, marble | 16/16 | 16/16 | — | — |
| curves_geometry | 15/16 | 15/16 | inner_backface r 0.842 / 0.851 | #1141, minor-channel cluster |
| light_path | 19/20 | 17/20 | CPU floor_near r 0.974; GPU floor_far g/b/L 1.021-1.027 | #1199 (CPU); GPU floor_far has no issue yet |
| car_paint | 14/16 | 2/16 | CPU lit_front b 0.922, upper_flake b 0.960; GPU 14 channels | #1153 lane; CPU = cluster |
| wood | 11/16 | 12/16 | b 0.909-0.961 in 4 ROIs; CPU also grain_center r 0.958, L 0.970 | cluster; grain_center r unexplained |
| pbr_group | 11/16 | 11/16 | CPU right r/g/b/L 1.18-1.29; lower b 0.922 / 0.939; GPU right 0.85-0.94 | firefly; #1156; cluster |
| shader_stack | 6/16 | 4/16 | right / lower / upper_left 0.88-0.98 | #995 1/eta^2 (kept, owner 10-31); #1174 lane (GPU) |

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
| 3 | **pkg327 Phase B**: a per-channel `expected_divergence` pin wherever Mitsuba spectral reproduces the shift; an engine fix for every unconfirmed shift (e.g. illuminant upsampling) | curves 16/16 both; car_paint CPU 16/16; wood GPU 16/16; pbr_group lower b | Sonnet (gates) / Opus (engine) | Phase A (owner answer 5) |
| 4 | GPU twins: light_path floor_far +2.5 % GPU-only (GPU/CPU 1.007 without Light Path; file an issue); pbr_group GPU right ROI dim = #1156 (bump/normal-map twin drift) | light_path GPU 20/20; pbr_group GPU right | Opus lane + lead GPU legs | — |
| 5 | #1199 floor_near r 0.974, by the issue's own recipe (Lambertian-floor variant, R-only albedo sweep), folded into pkg327 Phase A | light_path CPU 20/20 | pkg327 lane | — |
| 6 | pbr_group CPU firefly: trace the seed-278 pixel and its path; pkg306 Phase 1 scope, no new spec | pbr_group CPU right | pkg306 lane | — |
| 7 | **shader_stack 1/n² Cycles reference** (issue-sized; owner 10-31 keeps 1/eta^2): regenerate the Cycles reference with the inner emitter scaled by 1/n², re-calibrate the bands, no ROI pin; every other channel stays Cycles-checked | shader_stack ~15-16/16 | Sonnet lane; Cycles CPU renders | — |

Projection: items 1-5 and 7 give attributes, marble, curves, car_paint, light_path and shader_stack, which is 6/8 if
pkg327 confirms the cluster, the GPU twins land, and #1174 brings GPU shader_stack level with CPU. The IOR-1 control on
#995 read 15/16, so one shader_stack channel may still need attribution. Wood (CPU grain_center r) and pbr_group (#1156
plus the firefly) are the spares.

### 2.2 Row (b)

Owner 10-31 (§5 answers 1-4) redefines how (b) is scored:
- **Credit:** the static matrix, audited by a sampled witness set, instead of a witness per identity.
- **Predicate:** Welch-1b, as for (c) (#1087).
- **Threshold:** 0.95 is retired. After pkg328 Phase 1 and the first Welch-1b witness freeze, the threshold is the measured
  ceiling minus a margin, and the owner signs the number.
- **b1:** the 10-06 population decision (corpus v2 + production) is the sign-off.

Facts the threshold will be set from:
- The matrix-only ceiling is 0.43 today, about 0.69-0.81 once scanner credits land and Principled is lifted to SUPPORTED.
- b4 has 19 exercised drops. 11 of them are reported at runtime since pkg321 but stay DROPPED-SILENT in the matrix, because
  b4 reads the static classification, not the render log.
- b5 fails: Principled-advanced, Metallic and Sky have no witnesses, and nothing in the corpus exercises Displacement.
- b6 passes.

The sequence:
- **pkg328 Phase 1:** b4 counts only unreported drops. Reported drops still score 0, so nothing is inflated. Resolve the 8
  non-pkg321 rows (OutputWorld Surface / is_active_output, OutputMaterial target / Thickness, TexEnvironment Vector,
  TexImage interpolation, MapRange clamp) and re-check Coat Normal after #1157 / #1153. Each is a scanner credit backed by a
  probe render, an addon report or a real fix. Target: b4 green.
- **pkg328 Phase 2:**
  - freeze the candidate_v2 witness sample under Welch-1b;
  - score the audited matrix on CPU and GPU;
  - report the measured ceiling and a proposed threshold (ceiling minus a margin) for the owner's sign-off.
- After Phase 2: a Displacement use in the corpus (scenes are replaceable, memory `corpus-scenes-replaceable`) and
  Metallic, Sky and Principled-advanced witnesses in the audit sample (b5).

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

### 2.4 Exit manifest (a)-(e), (g)

Cut an exit-candidate build once (g) reads 6/8, (e) re-rates to 0 high and the owner has signed the (b) threshold. On it,
re-measure (a) (visible isolated Blender), (c) (Welch-1b) and (d), then (b) and (g). Rate (e) live. One heavy lead job at a
time. Commit all rows with `gate_manifest.py` and repo-relative evidence. (f) is deferred past Stage 0 (owner 10-31).

### 2.5 Backlog: gate vs product

- **Gate-relevant:** the five highs; #1201; #1141, #1199, #1156, #1153, #1174 and #995 for (g); #1087, #1088, #1039 and the
  pkg321 set #1128-#1136 / #1140 for (b).
- **Medium, already rated, worth lane gaps:** #1031, #1164, #1184 and #1185 would rate high on a stricter re-rate.
- **Product, after exit:** #941 (QMC sampler) and #763 (CPU noise), #1024 (film keeps negative channels; science output),
  #1044, #924, #1034, media #967 #983 #1019 #1193 (#1032 in lane), the Disney/rough-glass twins #942 #956 #957 #1126 #783
  #789, the procedural bake #890 #1002, the material preset library (owner 10-31), and #38 #39 #398 #141 #144. GR #894
  #1081 #1082 stay paused with Pillar 4.

### 2.6 Owner follow-ups (issue-sized, not gates)

- **pkg325 default ON plus a parity-harness force-OFF.** Passthrough becomes the user default. Every Cycles-parity harness
  (`render_leg.py`, the `mc_tolerance` production/v2/arbitration legs, gate (c) and (g) tests) sets it OFF explicitly, so
  gate renders stay byte-identical. Land the force-OFF before or in the same PR as the default flip.
- **pkg324 README:** publish the showcase tiles with licence notes (Classroom CC0, Junk Shop CC-BY credited inline). Evidence
  follows the owner's storage rule: hash-pinned summaries, JSON and small PNGs in git, bulk frames local.

## 3. Waves (lead holds the GPU and the build queue; ≤ 2 CPU-heavy jobs)

| Wave | Lanes | Lead |
|---|---|---|
| W1 (now) | the five live lanes finish; pkg327 Phase A (Sonnet, CPU + Mitsuba) | builds, GPU legs, merges, one (g) re-run |
| W2 | #1201 (Sonnet); pkg328 Phase 1 (Sonnet, Python only); pkg325 default ON + harness force-OFF (Sonnet); light_path GPU floor_far + #1156 (Opus) | (e) re-rate; GPU legs |
| W3 | pkg327 Phase B; shader_stack 1/n² Cycles reference (Sonnet); pkg328 Phase 2; pkg306 Phase 1 firefly | (g) re-run; owner signs the (b) threshold |
| W4 | — | exit-candidate build, manifest re-measure (§2.4), closeout sweep, run report |

## 4. Specs filed

| Pkg | Name | Size / tier |
|---|---|---|
| **pkg327** | Row (g) minor-channel chroma residual: attribution, Mitsuba arbitration, per-channel divergence | M; Sonnet lane, Opus if an engine fix appears |
| **pkg328** | Gate (b) b4 burn-down, Welch-1b witness freeze and the audited-matrix score | M; Sonnet lane, GPU witness legs via the lead |

Issue-sized work (#1201, #1156, light_path GPU floor_far, the shader_stack reference, the pkg325 default flip) goes to
lanes from the issue, as on 10-31.

## 5. Owner answers 2026-10-31

1. (b) credit: the static matrix, audited by a sampled witness set.
2. (b) predicate: Welch-1b, as for (c) (#1087).
3. (b) threshold: the measured ceiling minus a margin, set after pkg328 Phase 1 and the first Welch-1b freeze; the owner
   signs the number. 0.95 is retired.
4. b1: the 10-06 population decision (corpus v2 + production) is the sign-off.
5. Chroma: pin a channel as an expected divergence when Mitsuba spectral reproduces the shift; unconfirmed shifts get an
   engine fix. pkg327 Phase B is unblocked.
6. #995: keep 1/eta^2; regenerate the shader_stack Cycles reference with the inner emitter scaled by 1/n², no ROI pin.
7. pkg325: passthrough ON by default for users; Cycles-parity harnesses force it OFF.
8. Material preset library: after Stage 0 exit.
9. pkg324 README: publish the showcase tiles with licence notes (Classroom CC0, Junk Shop CC-BY credited inline).
10. Evidence storage: hash-pinned summaries, JSON and small PNGs in git; bulk frames stay local under
    `%LOCALAPPDATA%\astroray-evidence`.
11. Gate (f): deferred past Stage 0; revisit at the first public release.

Still open: the (b) threshold number, which waits on pkg328 Phase 2 data.

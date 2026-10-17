# Architect plan 2026-10-18: overnight session

State+refine run (Opus 5.5 architect) at session start. Previous plan: `architect-plan-2026-10-06b.md`.

**Read this first:** local `main` is **4 commits behind `origin/main`** (#1116, #1105, #1122, #1121). This plan reads
from `origin/main`. STATUS.md *does* have a 2026-10-07 entry; it is only on origin. Run `git pull --ff-only` once the
in-flight CUDA build finishes. Nothing has merged since
2026-10-07 02:02 (+11). The only open PR is #1123. When this plan was read, `build_cuda/` (Ninja) held **no `astroray*.pyd`**. The lead's build was still running. The newest
CUDA module is `build_blender_addon_cuda/` = `dist/astroray/` (2026-10-06 08:51), which predates five merges.

## 1. What landed since 2026-10-05

| PR(s) | Change | Moves |
|---|---|---|
| #1062 | Gate scoring 10-05 + README gallery | baseline doc |
| #1066, #1068, #1083 (pkg315), #1096, #1106 (#1050) | Frame pruning; dead legacy upload skipped; 100k material edit 44 → 4.2 ms; IAS-only refit 700 → 1–4 ms; worker-OFF raw-event reducer | (a) RED 102.1 → GREEN 78.2 ms |
| #1121 | Welch-1b tile test, 8 seeds/backend (owner) | (c) metric; GREEN on the integration build |
| #1086 (pkg319/317), #1090 (pkg318), #1101 (pkg320), #1109 (pkg310 row g) | Gate-f DLL closure; Welch study; provisional (b) score 0.000; scanner credits outputs/roots/Mix (ceiling 0.42 → 0.64–0.69); manifest row (g) | (b) tooling, (f) prep, (g) instrument |
| #1069, #1071, #1076, #1078, #1079, #1091, #1093 | Gate-e highs: Attribute alpha, BH params / Add (CPU) / photon gather, motion-blur normals + indirect-only, transparent bounces, Nishita disc + ReSTIR curves, Translucent + planar GPU bake, hair g/b dimness | (e) 10 high → 0 open |
| #1074, #1094, #1102 | Cornell harness (SSIM 0.93 → 0.9994); sky_sun firefly ROI; parity matrix regen | harness validity |
| #1095, #1097, #1098 | Shadow-ray transparent budget; GPU Add Shader (HasAdd axis); AOV indirect-only, seed-0 photon map | (e) mediums, (b) |
| #1103, #1104, #1110, #1105 (pkg322) | Glass tint = Color; Emission two-sided (checker witness passes CPU); Voronoi 1D/2D/4D; Pointiness (curves CPU 0 → 13/16, GPU 3 → 15/16) | (b), (g) |
| #1113, #1114, #1116, #1118, #1119 | Card z-fight (scene re-frozen); GPU rough-glass Fresnel side; smooth-glass Fresnel side; ReSTIR stale-guide OOB write; whole-strand self-skip | (c) M1 defects, (e) |
| #1064, #1080, #1107 | GR continuation, scene chords, redshift ref = infinity (owner) | Pillar 4 groundwork |
| #1065, #1077, #1100, #1122 | Test re-target; two plans + pkg315–323 specs; 10-07 checkpoint | docs |

### Stage 0 gates. "Current main" = origin/main 43fd0a2f (+#1123 once merged)

| Row | Status | Measured on | Evidence | Next mover |
|---|---|---|---|---|
| (a) latency | GREEN p95 78.2 / p99 109.7 ms | beda188 (10-06). **UNMEASURED on current main** | `run-report-2026-10-06.md`; local `%LOCALAPPDATA%\astroray-evidence\2026-10-06\a\` | M3 formal re-run |
| (b) coverage | **UNMEASURED.** Provisional 0.000 / 0.000 on a build from before #1069 | — | `gate-b-provisional-score-2026-10.md` | items 4, 6, 7, 8 |
| (c) trio | GREEN (Welch 0 rejected, ROI max 0.73 %) | build_id **`dev`** (integration worktree). **UNMEASURED on a stamped main build**. #1123 changes glass | local `2026-10-06\c-welch-formal\row_c_welch.json` | M1 after #1123 |
| (d) panels | GREEN | 132c974 (10-04), committed | `acceptance_manifest.json` | M-optional re-run |
| (e) triage | Committed manifest still says RED 10 (10-05 snapshot). The 10-06 rating found 0 open highs. **4 issues unrated**: #1108, #1111, #1117, #1120. #1120 reads high to me (wrong GPU image, no warning) | live GitHub | `gate-e-triage-2026-10-06.md` | item 1 + M4 |
| (f) install | UNMEASURED | — | `gate-f-other-pc-runbook.md` | owner, second PC |
| (g) node score | RED: CPU 2/8 (marble, attributes), GPU 1/8 (marble), 1 silent pair (#1117) | build_id `dev`, before #1105. **UNMEASURED on current main** | local `2026-10-06\g\instrument.json`; `provisional_production.toml` | items 2, 3, 4 + M2 |

Path to (g) 6/8: light_path (glass, M2 after #1123) + curves_geometry (item 4) + pbr_group (item 3A) + one of
wood / car_paint (item 3B, #1005) or shader_stack (#995, two sessions). The GPU also needs attributes (item 2).
Realistic tonight: 4–5/8.

## 2. Stale items from plan 10-06b

| Item | State | Verdict |
|---|---|---|
| 1 pkg320 | merged #1101 (spec still `open`) | done; flip spec |
| 2 #1099 | merged #1104; closed | done |
| 3 #1038 | merged #1103; issue open; light_path rows still cite it (measured before #1103) | re-measure (M2/M6), then close. The sun-shadow fill is a physical caustic (owner physics rule) |
| 4 pkg322 | merged #1105 | done; #1117 is the scanner tail → item 4 |
| 5 #975 | merged #1110 | done; 3D deviations → item 5 (#1108) |
| 6 pkg321 | not started | continue → item 6 |
| 7 #1092 | merged #1119 | done |
| 8 pkg323 | not started | continue → item 7 |
| 9 #875 | not started; OFF 77.7 ms vs 20 ms target | drop to reserve: (a) is green, and this is a sub-target |
| 10 #1050 | merged #1106 | done |
| M1 Welch | done; adopted #1121 | the formal stamped run is still owed → M1 |
| M2 pkg310 | first (g) measurement done (#1109), on a `dev` build | re-run → M2 |
| P0 #954 verify-close | not done; still open | the lead verifies it in M6 |
| P2 gate-b legs re-run | not done | → item 8 |
| R1 #1001 TTFS, R4 #1001.4 | not started | reserve (speed session) |
| R2 #1004 residual | not started | continue → item 3A |
| R3 #1044, R5 #1034 | not started | reserve |
| R6 #995 | not started | next session, after #954 |

## 3. Ordered work list for tonight

Lane rules apply (`.astroray_plan/docs/lane-rules.md`). Lanes build CPU only and end with `BUILD REQUEST <sha>`. The
lead owns CUDA builds and the GPU lock. Reviews follow the owner's Codex-out route: one blind Claude reviewer plus an
opencode critic (`delegate --tier verify --agent critic`). Every Cycles source cited below is `intern/cycles/` at
v5.2.0, Apache-2.0.

### Lead pre-steps (no lane)

- **P0.** Let the in-flight build finish, then `git pull --ff-only`. Merge **#1123** (see §6). Rebuild `build_cuda` at
  the merged HEAD, run the arch gate
  and cuobjdump, restage `dist/astroray`, and verify `astroray.__file__` / `__build__`.
- **P1.** File the new issue for item 2 (prod_attributes GPU). The `provisional_production.toml` GPU row cites #993,
  which is stale: the CPU now passes.

### Measurement items (lead, on the stamped merged build; GPU never overlaps a build)

- **M1** Row (c): formal Welch on 8 seeds × CPU/GPU (command in `stage0-gate-scoring-2026-10-05.md`), fresh `--out`,
  ~12 min. Pass = 0 rejected tiles in every role and ROI ≤ 5 %. If gallery fails on glass props, attribute it with a
  #1123-off build before blaming #1123.
- **M2** Row (g): `PKG310_WORK=<dir> gpu_locked_run.py lead -- pytest tests/test_production_corpus.py -k "parity or silent"`,
  then `gate_manifest.py --adapt-g`. Remove any strict row that XPASSes. Inspect the sheets. Repeat after each wave
  that touches (g).
- **M3** Row (a): formal `--mode gate_a`, worker ON, quiet window, ~13 min. Pass = p95 ≤ 100 and p99 ≤ 150.
- **M4** Row (e): two blind ratings of #1108, #1111, #1117, #1120 and every issue filed tonight, then re-reduce the
  committed manifest from live GitHub.
- **M5** #1123 perf: STACK grew +240–272 B on the principled variants. Cornell 1024² 256 spp plus one rough-glass
  scene, GPU, burn-in then min-of-5 (memory `gpu-perf-ab-clock-drift`), pre vs post. Pass = Cornell ≤ +2 %. Report
  the glass number either way.
- **M6** Glass re-measure sweep after #1123: #957 (rough glass GPU/CPU 1.03–1.07), #968 (rim +7.5 %), #773 (limb
  0.84×), #1038 (centre), #954 (verify). Close each or re-scope it with numbers.
- **M7** Viewport stale issues: re-measure #721 (P1-high label, 155 ms camera events) and #855 with
  `--mode gate_a_table`. Close or relabel them. Today they contradict a green (a).
- **M8** Closeout: build an integration branch, then run the full CPU+GPU sweep (~52 min, no `-x`) before declaring
  clean.

### Lanes

| # | Id | Problem | Cited approach | Main files | Gate (pass) | GPU reg risk (rule 13) | Tier | Size | CUDA |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **#1120** + #1123 review minors | GPU folds RGB `L.weight` into the colour before the JH upsample: coat_over_tinted_glass GPU/CPU 0.848. Four minor review items left from i16: GPU ignores `rough_glass_walk` silently, no Ng check in the sampler, `average(darkening)` sample weight, film-glass reflect probability | CPU `principled.cpp` `evalSpectral` (per-λ `wSpec·upsample(c)`); Jakob & Hanika 2019. Cycles `closure/bsdf_microfacet.h` (darkening weight, sampler) | `include/astroray/gpu_materials.h` (~2654), `plugins/materials/principled.cpp`, `tests/test_pkg188_*` | pkg188 coat row in [0.95, 1.05] and its strict xfail removed; other pkg188 rows unchanged; GPU glass suite 41/41; `rough_glass_walk=1` on GPU emits a DegradationReport (test); Ng-reject analytic test | low-med: per-λ multiply in place of a pre-fold. STACK ≤ +64 B vs post-#1123 | Opus 5.5 | M | yes |
| 2 | **new** (prod_attributes GPU) | instance0 G 2.15× of Cycles on GPU; CPU passes. Scene: 3 **linked-mesh** spheres, Object Info Random → Hue/Sat, Color Attribute | Cycles `kernel/geom/object.h` `object_random_number`, `svm/attribute.h` per object. Likely suspect: the GPU instancing fast path shares one object's layers/random (#966 class). Attribute first | `src/gpu/scene_upload.cu`, instancing path, `shading_inputs_eval.cu`, `blender_addon/exporter.py` | prod_attributes GPU all ROIs in band; CPU 1e-6 unchanged; non-instanced scenes 1e-6 | med: any per-instance id goes in a side table (`c_wfTexBinding` precedent), never shade live state | Opus 5.5 | M | yes |
| 3 | **#1004** residual, then **#1005** | A: pbr_group centre 0.91×, GPU right B 1.42× (bump step taken after Mapping). B: procedural Bump Height reported but not applied (car_paint, wood). The CPU exact-derivative taps overshoot Cycles ~2× | Cycles offsets the **coordinate** by the pixel footprint before the Height subgraph: `scene/shader_graph.cpp` bump duplication, `svm/tex_coord.h` `*_bump_dx/dy`, `svm/displace.h` `svm_node_set_bump` (Filter Width), `util/differential.h`; Igehy 1999 ray differentials | `plugins/materials/normal_mapped.cpp`, `include/raytracer.h` (HitRecord dP), addon bump export, `src/gpu/wavefront/proc_tex_eval.cu`, `scene_upload.cu` | A: pbr_group centre ≥ 0.98× and in band on CPU+GPU; unmapped image-bump scenes 1e-6. B: car_paint lit_front / upper_flake B in band CPU+GPU, DEGRADED entry removed, wood rows re-measured. Stop rule: if B cannot get inside 2× band, ship A and report B | A low. **B high:** footprint scalar + 3 height taps go out of line, behind a `HasBump` template axis, so other kernels stay byte-identical | Opus 5.5 | L | yes |
| 4 | **#1117** + curves inner_backface | Scanner misses the `out_name == 'Pointiness'` branch (1 silent pair, both backends). inner_backface R 0.85 on CPU and GPU | #1028 mechanical-evidence discipline with a negative fixture. Backfacing per Cycles `svm/geometry.h` (`SD_BACKFACING`); check the thick/open-bowl normal convention | `scripts/generate_blender_parity_matrix.py`, matrix, addon Backfacing path | Pointiness SUPPORTED, fixture uncredited, 0 silent pairs; inner_backface in band, or a documented divergence with evidence | none (scanner); low if engine | Sonnet 5.5 | S–M | if engine |
| 5 | **#1108** | Voronoi 3D: N-Sphere Radius, unclamped F2/Manhattan, Distance-to-Edge fractal deviate from Cycles. #1110 kept 3D bit-identical on purpose | Exact port of `svm/voronoi.h` 3D paths; Worley 1996 | `include/astroray/procedural_tex.h`, `proc_tex_eval.cu`, addon Voronoi export | Coplanar tiles under a uniform world, per feature × metric: min channel ratio ≥ 0.998 vs Cycles 5.2 on CPU+GPU; 1D/2D/4D unchanged; DEGRADED entries removed; marble/wood (g) not worse (M2) | low: out of line | Sonnet 5.5 | S–M | yes (confirm) |
| 6 | **pkg321** (#1089) | 76/63 weight of DROPPED-SILENT rows never verified | Per spec: one counterfactual probe per family | spec `pkg321-dropped-silent-row-audit.md` | Per spec: every row has a verdict; real drops "reported"; CPU renders byte-identical | none | Sonnet 5.5 (+Haiku sifting) | M | no |
| 7 | **pkg323** (#1087, no predicate change) | One witness, one control kind | Per spec: 5 control kinds; candidate case map scored under rectangle and mask predicates | spec `pkg323-gate-b-witness-kinds-study.md` | Frozen `--score` byte-identical; ≥ 10 witnesses × 2 predicates × CPU/GPU; sheets inspected; owner question written | none | Sonnet 5.5 | M | no (GPU legs via lead) |
| 8 | **Gate (b) re-freeze** | (b) has never been scored on the owner population (corpus v2 + production) | `next-session-prompt-2026-10-07.md` step 3: new scanner-integration receipt (blind Opus reviewer + Flash critic), regenerate `coverage_input_v4` / `node_uses_v4` / runner results, `--score` | `coverage_report.py`, `benchmarks/reference_corpus/populations/` | Reducer exit 0, CPU and GPU reported separately, receipt independent. First nonzero S expected from the checker witness (CPU passes since #1104) | none | Sonnet 5.5 | M | no |
| 9 | **GPU stale-binding batch** | ReSTIR leaves `c_wfTransparentLimit` stale (same class as #1115). #1047 item 4: GPU `lp_state` transparent field saturates at 31 | #1118 reset pattern; widen the bitfield or clamp with a report | ReSTIR/snapshot drivers, `gpu_wavefront_state.h` | Transparent scene rendered after a ReSTIR render equals a fresh process (1e-6); GPU honours limit 40 like CPU; close #1047 | none (host binding); low (bitfield; check struct size) | Sonnet 5.5 | S | yes |
| 10 | **Tooling batch** | Row (d) `evidence_path` uses `\` and fails `validate_manifest` on Linux. #950: harness prefers the MinGW `build_blender_addon` and failed the #1123 sweep. File the Disney delta-glass Schlick issue (#1112 pattern) | — | `scripts/gate_manifest.py`, `tests/test_blender_parity_harness.py`, `benchmarks/blender_parity/harness.py` | Posix-path test; `test_backdrop_is_parity_safe` passes inside a worktree | none | DeepSeek V4.1 Flash (delegate), Sonnet verifies | S | no |
| 11 | **pkg306 Phase 0** (reserve) | media / dispersion firefly tails hold 95–100 % of variance | Per spec: ablation names the owner path class + code site | spec `pkg306-firefly-tail-owners-media-dispersion.md` | Phase 0 table: each tail has a named, ablation-proven owner | none | Opus 5.5 diagnosis, Flash runs the grid | M | no |

Reserve after 11: #875 (100k move), #1001 TTFS / transparent-shadow walk, #1044, #1034.

### Scheduling

- **Lane cap: 2 concurrent lanes**, plus the lead. OMP_NUM_THREADS=8 and MinGW `-j 6` stay as they are. SMT
  (16 threads) is not headroom: the event log has **8 Kernel-Power 41 resets since 09-23**, one at 2026-10-05 18:16
  during a 2-lane run. Owner Q1.
- Waves pair one CUDA lane with one no-build lane, so the queue holds at most one CUDA build:
  W1 (1 + 6), W2 (2 + 4), W3 (3 + 7), W4 (5 + 9: one bundled build, batched-lanes directive), W5 (8 + 10).
  Item 11 fills any idle slot.
- The lead runs M1/M3/M5/M6/M7 right after P0, before W1's first build request. Then M2 after W2 and after W3. M8
  runs last.
- One GPU suite per wave before its PR, never overlapping a build (lane rule 12).

## 4. Excluded / needs owner

- Pillar 4 (#1081, #1082, #894, #144, #141, pkg45–51) stays paused.
- pkg312, pkg313 and pkg311 P2/3 wait for Stage 0 exit (owner 09-29).
- #995 nested Mix (+#954): two sessions. It is the next session's (g) headline if items 2–4 land.
- pkg297 QMC (#941), pkg300 P2, pkg299 P2: multi-session speed/noise work, not gate-moving.
- #1024 negative scene-linear: owner decision.
- #1087 predicate change: owner, after item 7's data.
- Gate (f): owner's second PC.
- #956 and #942: Disney only; the Blender export never uses Disney.
- CUDA 13 trial: owner toolkit install.

## 5. Owner questions for the morning

1. Resets: 8 Kernel-Power 41 events since 09-23 (10-05 18:16, and two on 10-14). Were the 10-14 ones your
   BIOS/SMT change? Keep the 2-lane cap?
2. Gate (b): does your 10-06 population decision count as the b1 sign-off?
3. Gate (b) witness predicate (#1087): feature mask or ROI rectangle? (item 7 gives the data)
4. Where should (a)/(c)/(g) evidence live: git, LFS, or local? (asked for the third time)
5. Gate (f): when can you run the second-PC runbook? Its ZIP (`beda188`, sha `771d2a66…`) is now 13 merges old. The
   lead will rebuild it at tonight's HEAD and update the sha in `gate-f-other-pc-runbook.md`.

## 6. Repo hygiene for the lead

- **Sync:** after the in-flight CUDA build ends, run `git -C <main> pull --ff-only` (main is 4 behind). If that build
  is at 2abe4b22, it lacks #1105 and #1116 (`gpu_materials.h`, `principled.cpp`), so rebuild after the pull plus #1123.
  Do not take M1–M3 numbers from it. There is 1 stash entry. Inspect `git stash list` before any
  lane starts (stashes are shared across worktrees).
- **#1123: merge.** CI is green and the branch merges cleanly. It is behind only #1121 (gate-c tooling/tests, no
  overlap). The owner decided this on 10-06. The Opus review was APPROVE-WITH-FIXES with the M1/M3 conditions met.
  The 4753/2 sweep failures are attributed (timing flake; #950). Run
  `gh pr merge 1123 --squash --delete-branch`, then P0. Two things are still unmeasured: the perf cost of the STACK
  growth (M5) and the (c)/(g) effect (M1/M2). Neither blocks the merge, because glass on main is an explicit owner
  default.
- **Worktrees:** the lead has already pruned 29. Four remain. Keep `batch-i16/cycles-multiggx-glass` until #1123 has
  merged. The other three have no PR, but their content is already on main, so prune them:
  - `batch-e2/gate-e-highs` (8 ahead): its content is the #1078 squash. #1078's head was `batch-e2/gate-e-1033`. The
    merge-base diff has the same 17 files and the same +750 −93 as `fd9e61e3`. Its notes also say #1047 items 1–2 are
    fixed, so they shipped in #1078.
  - `batch-i15/hair-gpu-regression` (1 ahead): `7c2557e2` matches #1118 by patch-id (`git cherry` gives `-`). #1118's
    head was `batch-i15/restir-stale-guide`.
  - `worktree-agent-a51adda7896e13a46`: `cace572d` matches #1074 by patch-id (`-`).

  Before you delete, re-confirm the e2 claim. This command must print nothing:
  `git diff fd9e61e3^ fd9e61e3 --stat > a; git diff $(git merge-base origin/main batch-e2/gate-e-highs) batch-e2/gate-e-highs --stat > b; diff a b`.
  Then, for each branch, run `git worktree remove <path>`, then `git branch -D <branch>`, then `git worktree prune`.
  After that, delete the merged remote branches (`git push origin --delete <b>`). That is about 30
  `origin/batch-[e-i]*` branches plus `origin/docs/checkpoint-2026-10-07`.
- **Spec status flips:** pkg315 → done (#1083), pkg320 → done (#1101).
- **Issues to close after verification:** #1039 and #1088 (via #1101, confirm in item 8); #1111 (A #1114, B #1113;
  confirm in M1); #1060 (cornell fixed; the hdri SSIM is a noise-limited metric, not an engine bug); #1038, #957,
  #968, #773 and #954 (M6).
- **Missing STATUS.md entry:** add a 2026-10-18 entry covering the 11-day gap (no merges 10-07 → 10-18), #1123's
  merge, `build_cuda` having had no `.pyd`, the reset events, SMT now on (8C/16T), and the M1–M3 results that make
  (a)/(c)/(g) current again.

# Next session (written 2026-10-25 ~08:00, end of the Fable-lead overnight session)

Read first: `STATUS.md` (2026-10-24/25 entry), `run-report-2026-10-25.md`, `architect-plan-2026-10-25.md` (§5 owner
questions), `stage0-gate-scoring-2026-10-18.md` (rows (b), (e), (g) re-measures), memories
`ci-changes-filter-hides-tooling-test-breakage`, `coincident-faces-optix-tie-break-parity-gap`,
`vision-model-hallucinates-pixel-shifts`.

## State at handoff
- **main** `c76baf57` (engine ecd36567): merged tonight #1148, #1149, #1151 (#1125), #1157 (#1004/#1005), #1161 (pkg324),
  #1163 (pkg326), #1166 (pkg325), #1169 (gate (b)), #1170 (#995/#955). `build_cuda` stamp c76baf57 (sm_120), `dist/astroray`
  restaged 07:46 from the same HEAD. No worktrees remain.
- **#1173 pkg306 Phase 0 merged** (main 0a4d4aaa; engine byte-identical). Diag switches live on `lane/pkg306-diag`
  372da5c9 for Phase 1.
- **Wave 2 update (19:30):** PRs #1189 (#1162) and #1191 (#1154) opened with GPU legs, cuobjdump and interleaved
  timing done (scratchpad `perf_probe_1162.py` / `perf_probe_1154.py`; both within 1 % of main). Lanes #1152 (worktree
  `i1152`, fixing `kMaxPasses = waves * passDepth + ...`) and #1172 (`i1172`) running. Merge order on green: #1187, #1189,
  #1191, then #1152 / #1172 when they land. After that: rebuild main `build_cuda`, restage `dist/astroray`, re-rate row (e)
  (`known_issues_report.py --capture-gate-e`; all eight highs should now be closed or in PR), re-run row (g)
  (`test_production_corpus.py -k "parity or silent"` under the lock, `gate_manifest.py --adapt-g`). Issues filed today:
  #1177-#1180, #1184-#1186, #1188, #1190. The `i1158` worktree directory is held open by another process; delete it when free.
- **Wave 2 update (16:00):** merged #1181 #1182 #1183 (main 082d05ef). Open: #1187 (#1150, rebased onto main, GPU
  evidence on the identical 4da899a4 engine). #1162 lane: suite green on c6662104 but +4 % GPU time on a no-film
  Principled scene (stack +136..152 B in every `stageShadeBucketed<true>` kernel); cause suspected = the two pointer
  parameters added to `gpu_principled_sample`; lane restoring the signature. Measure with the scratchpad
  `perf_probe_1162.py` (24 Principled spheres, interleaved min-of-4; main 0.786 s) and `res_compare.py`. Main
  `build_cuda` is stale (c76baf57): rebuild + restage after #1187.
- **Wave 2 update (13:30):** #1176 merged (main 03db4155). Also open: #1182 (#1155), #1183 (#1158), #1187 (#1150, based on
  #1181 so merge #1181 first). Lanes #1162 (smooth-glass thin film) and #1154 (bump correction) running; #1152 is the last
  row (e) high without a lane. Issues #1184 #1185 #1186 filed. Merge order on green: #1181, #1187, #1182, #1183.
- **Wave 2 (10-25 late morning):** PR #1176 (#1171 sun power; GPU legs green, merged) and PR #1181 (#1165
  bounce caps = Cycles max_bounces+1 terminate-after, CPU+GPU, reviews PASS/PARITY-OK, GPU legs green on build adcc5cfc;
  last commit 4655c6d1 is test/comment/provisional-row only) wait on CI; merge each when its branch-only run is green and
  any PR-run failures are main's known ones. Lanes: #1150 (Opus, worktree `i1150`, branch `lane/issue1150`, based on the
  #1181 head because it edits the same ReSTIR loop) and #1155 (Sonnet, `i1155`, `lane/issue1155`); on their
  `BUILD REQUEST <sha>` run `scriptsuilduild_cuda_worktree.bat <wt> <sha>`, their GPU legs under `gpu_locked_run.py
  lead`, cuobjdump A/B, reviews, PR, merge. After the merges: rebuild main `build_cuda`, restage `dist/astroray`, re-rate
  row (e) (highs left after #1171/#1165/#1150/#1155: #1152 #1154 #1158 #1162), re-run row (g). New issues from the #1165
  parity review: #1177 #1178 #1179 (engine) and #1180 (GPU Add Shader drops emission when leaf 0 is not Principled).
  Worktrees i1171 i1165 i1150 i1155 and their branches go once merged.
- **Final sweep** on main c76baf57: see `run-report-2026-10-25.md` (SWEEP2 line). The pre-closeout sweep (624e32df) was
  5672 passed / 10 failed, all ten attributed (4 hair_tuft strict XPASS = improvement, 5 incomplete provisional rows
  identical on the pre-#1125 baseline, 1 OneDrive PermissionError). The `benchmarks/reference_corpus/provisional_v2.toml`
  fixes (motion_vane gpu_cpu channels, RoughGlassFilm r/L, hair_tuft ortho un-xfailed) are committed with the final sweep.
- **Gates:** (a) GREEN; (b) **RED first formal score** 0.00213 nine_scene / 0 owner population (no witness registered);
  (c) GREEN; (d) GREEN; (e) **RED** 8 high on 81 open (this session's own findings); (f) owner's second PC; (g) RED 2/8, 2/8,
  0 silent pairs (pbr_group 11/16 both, car_paint CPU 13/16, wood 12/16, shader_stack 4/16 after #1170).

## Order of work
1. (done) #1173 merged, worktree removed; `lane/pkg306-diag` kept.
2. **Row (e) back to green** = fix the highs, smallest first: #1171 (`DistantLight::power()` solid-angle scaling, one
   function + a flat-vs-tree sampler test), #1165 (transmission cap accounting off by two vs Cycles), #1150 (GPU ReSTIR-DI
   black behind alpha-0; CPU ReSTIR counts the pass as a bounce), #1162 (smooth-glass thin film in the Principled delta path,
   CPU RGB/spectral + GPU RGB/spectral, REG 254), #1155 (diamond Sellmeier preset), #1158 (library-linked images),
   #1154 (Cycles bump correction + `bump_shadowing_term`), #1152 (pass-plan counter guard). Re-rate after each batch
   (`known_issues_report.py --capture-gate-e` / `--finalize-gate-e`, two blind raters + flash, stricter rule; pipeline in
   `%LOCALAPPDATA%\astroray-evidence\2026-10-24\gate-e2\`).
3. **Row (g) path to 6/8:** #1153 (GPU procedural Bump Height + coat normal, unblocks car_paint GPU and wood), #993
   (wood Roughness chain over VM_MAX_SLOTS), #1004 residual (pbr_group right ROI, GPU bump tangent frame),
   #1038 (light_path glass), and the owner's #995 1/eta^2 decision (shader_stack lower/upper_left).
4. **Row (b):** freeze pkg323 witnesses on the owner population (`candidate_v2`), fix #1167 (scorer silent zero), then
   #1168 (scanner over-credit paths, with negative fixtures); owner b1 sign-off.
5. **pkg306 Phase 1:** #1172 spot light-tree cone (trimmed 80x -> 25x CPU, 67x -> 11x GPU, means unchanged) and #1032
   segment direct light; the dispersion glints and the photon prism caustic go to the pkg307 Mitsuba arbitration rows.
6. **Showcase follow-ups:** pkg324 sp02 prism throw, sp07 replacement scene (pkg325's `benchmarks/showcase/spectral/pkg325/`),
   #1159 node tiles, #1155; the README/licence question stays with the owner.
7. Retro `cycles-parity-reviewer` pass on #1149 done 10-25 (PARITY-OK; follow-ups filed as the newest "Voronoi 3D port follow-ups" issue); the pass on #1163 is still owed.

## Owner questions (also in `architect-plan-2026-10-25.md` §5)
- #995: keep the pbrt 1/eta^2 radiance convention in the glass BTDF (emission inside glass exits at S/n^2) or match Cycles
  (omits it; a thermal emitter exits at B)? The parity reviewer confirmed it is a convention choice, not a bug.
- pkg325 default stays OFF (Cycles parity) — confirm; pkg324 README publishing + licences; evidence storage (git/LFS/local:
  #1161 added 11 MB); material preset library scope; gate (f) second PC; (b) b1 sign-off.

## Tooling state
- `opencode/deepseek-v4.1-flash-free`: grunt/implement/vision primary; `delegate.py --tier vision --image <png>` critiques
  land in the transcript (status fix e2fa88c8); reliable on presence/absence, not position/size.
- Scratch helpers (session scratchpad, re-create if needed): `watch_ci.sh <PR>` (5-min CI poll), `res_compare.py <main_pyd>
  <new_pyd>` (cuobjdump REG/STACK A/B), `vision_extract.py <dir>`.
- Evidence root `%LOCALAPPDATA%\astroray-evidence\2026-10-24\` (gate-e, gate-e2, gate-b, g2, g3, i1004, i1125, i995,
  pkg324, pkg325, pkg326, pkg306, sweep1, sweep2).

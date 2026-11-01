# Stage 0 gate scoring, 2026-11-01: row (b) under the audited-matrix model (pkg328 Phase 2)

Build under test: staged addon `dist/astroray` `e302ca1+20261101T002422Z` (module sha `7993fecd...`), one build for the CPU and
GPU legs. Engine-identical to the branch base `33be55cb` except #1221's addon EXR change. Blender 5.2.0 LTS. Machine: RTX 5070 Ti,
8C/16T. Evidence root: `%LOCALAPPDATA%\astroray-evidence\2026-11-01\p328b\audit\` (frames, local only; `audit_results.json` carries a
digest per (scene, leg) seed stack so they can be re-verified).

## Result (owner population candidate_v2 = corpus v2 + production, 233 exercised identities, weight 474)

| quantity | CPU | GPU |
|---|---|---|
| measured ceiling (every identity at matrix credit: SUPPORTED 1, APPROXIMATED 0.5, else 0) | 364 / 474 = **0.7679** | 0.7679 |
| **S** (ceiling minus identities zeroed by failing audit witnesses) | 226 / 474 = **0.4768** | 220 / 474 = **0.4641** |
| seed-to-seed spread of S (leave-one-seed-out, 8 verdict sets) | 0.0000 | 0.0000 |
| one witness's weight (largest single witness, Principled on `v2_viewport/Grid100k`) | 43.5 / 474 = 0.0918 | 0.0918 |
| margin = spread + one witness's weight | 0.0918 | 0.0918 |
| **proposed threshold** = ceiling - margin (rounded down to 3 places) | **0.676 (UNSIGNED)** | **0.676 (UNSIGNED)** |

**The owner signs the threshold in the PR.** Until then `docs/blender_parity/evidence/gate_b/threshold_b.json` has `signed: null`, b2/b3
fail and row (b) stays red. The proposed number is recorded there only as `proposed`.

Reading. Measured S is below the proposed threshold on both backends (0.477 / 0.464 against 0.676), so signing 0.676 would leave (b)
red until the failing witnesses are fixed or re-judged; the gap is 11 CPU and 15 GPU failing witnesses, listed below. The spread term is
0 because no verdict changes when any one of the 8 seeds is dropped: the 11 CPU failures reject 1 to 1749 Holm tests, and the one
marginal case (`RoughnessProg`, 1 of 192) fails in every 7-seed subset too. The margin is therefore only the one-witness term; if
the owner thinks that is too tight or too loose, it is the one number to argue.

b-subchecks on candidate_v2: b1 FAIL (population not ratified; the b1 ratification file is still open), b2 FAIL and b3 FAIL (threshold
unsigned), **b4 PASS (0 drops no warning names; was 19)**, b5 FAIL (Displacement is not in the corpus; Metallic and Principled
have zero-credit identities: 13 dropped-silent uses weighing 26), b6 PASS. nine_scene (legacy): S = 1/469 = 0.0021 on both, 1 silent
drop, red.

## Method

Credit is the static matrix per identity (`coverage_report.matrix_credit`). The audit sample is frozen in
`benchmarks/reference_corpus/audit_sample_candidate_v2.json`:

* the 16 candidate_v2 witnesses of `witness_candidates_v5.json` (selection rule R1-R5, unchanged);
* one witness per b5 family the candidates lack, chosen by one a-priori rule (eligible node exercising the most sockets, ties by
  largest mask, scene, object, node): Metallic `v2_thin_film_metals/Gold`, Principled `v2_viewport/Grid100k` (33 sockets), Sky
  `v2_sky_sun/World`. Their controls are new render_leg kinds `metallic_diffuse`, `principled_diffuse` (consumers of the BSDF are fed a
  grey Diffuse) and `sky_const` (the Sky colour is replaced by a constant). Nothing else was added.

Each witness is rendered on CPU and GPU (and Cycles) with the frozen settings: four seed-7 legs (baseline and control, both engines) for
the effect check, and 8 independent baseline seeds per engine (278, 1301, 2711, 4177, 6113, 7919, 9371, 11027) at the scene's own
spp. **The verdict is `mc_compare.welch_verdict(astroray_stack, cycles_stack, alpha=0.05, tile=8, delta_rel=0.01)` over the witness ROI
rectangle** (Welch-1b, the row (c) predicate, called as is). A FAIL zeroes every identity the witness covers on that backend. A
witness whose control is inert in Astroray but moves the image in Cycles is a FAIL; one whose control is inert in both engines (or in
Cycles) is NO-EFFECT, recorded and credits nothing, so its identities are zeroed too. An ERROR or missing backend leg zeroes them and
makes the report `unmeasured` (never a pass). None of NO-EFFECT or ERROR occurred in this run.
GPU legs ran under `gpu_locked_run.py` (4153 s).

## Witnesses (Holm-rejected tiles / tests)

| witness | CPU | GPU |
|---|---|---|
| prod_car_paint/Hero/Bump | FAIL 104/1587 | FAIL 77/1587 |
| prod_curves_geometry/Bowl/Noise | FAIL 44/1368 | FAIL 52/1368 |
| prod_marble/Hero/Mapping | PASS 0/1587 | PASS 0/1587 |
| prod_marble/Hero/Noise | PASS 0/1587 | PASS 0/1587 |
| prod_marble/Hero/Wave | PASS 0/1587 | PASS 0/1587 |
| prod_shader_stack/Hero/Noise | FAIL 547/1587 | FAIL 533/1587 |
| prod_shader_stack/Hero/Noise.001 | FAIL 547/1587 | FAIL 533/1587 |
| prod_wood/Hero/Bump | FAIL 44/1587 | FAIL 24/1587 |
| prod_wood/Hero/Mapping | FAIL 44/1587 | FAIL 24/1587 |
| prod_wood/Hero/Noise | FAIL 44/1587 | FAIL 24/1587 |
| prod_wood/Hero/Wave | FAIL 44/1587 | FAIL 24/1587 |
| v2_sky_sun/World/Sky (supplement) | FAIL 113/2640 | FAIL 112/2640 |
| v2_textures_opvm/CardMapAfterWarp/Mapping | PASS 0/243 | FAIL 65/243 |
| v2_textures_opvm/CardMapAfterWarp/Noise | PASS 0/243 | FAIL 65/243 |
| v2_textures_opvm/CardNoise/Noise | PASS 0/243 | PASS 0/243 |
| v2_textures_opvm/CardWave/Wave | PASS 0/243 | FAIL 33/243 |
| v2_textures_opvm/RoughnessProg/Noise | FAIL 1/192 | FAIL 2/192 |
| v2_thin_film_metals/Gold/Metallic (supplement) | PASS 0/108 | FAIL 1/108 |
| v2_viewport/Grid100k/Principled (supplement) | FAIL 1749/6720 | FAIL 1761/6720 |

CPU 8 PASS / 11 FAIL; GPU 4 PASS / 15 FAIL. Visual check of the contact sheets (Astroray | Cycles | 3x |diff| | mask, then the two
controls): the `prod_shader_stack` failure is a real texture-structure difference (Cycles shows blotchy noise structure on the frosted
sphere, Astroray a finer speckle; known #995 scene); the Sky failure is a sun-region and brightness difference (Nishita
approximation). The Welch failures at `prod_wood` match the known wood divergence (#993).

Design caveat for the owner: a witness judges the whole ROI rectangle, so a scene-level divergence on the same object (for example the
wood or shader_stack material) zeroes the identities of the node under test even when that node's own sockets are fine, and the
Principled witness on `Grid100k` alone zeroes 43.5 of 474. The spec fixes this reading; a mask-limited or control-differenced Welch
would be a different, narrower predicate and is not what was frozen.

## Scanner receipt (independent)

Scanner source sha `78e65e59...` (`scripts/generate_blender_parity_matrix.py`), pinned commit `d7769bf8` (this branch). The earlier
receipt (fdb8774b) was stale: the scanner changed in #1196, #1212 and #1219. A regeneration of the matrix under Blender 5.2
reproduced the committed matrix byte for byte before and after the cap below.

* Blind Claude Opus 5.5 review of the delta fdb8774b..b4e7cbf0, given only the diff and the repo: **round 1 CHANGES**, six non-blocking
  findings. Two could inflate the score: TexEnvironment Vector credited without the socket ever being read (any world Mapping rotation
  is used), and OutputWorld Surface / is_active_output credited SUPPORTED though only a Background linked straight to Surface is
  filtered. All 28 `reported_at_runtime` flags were verified against warning text in the addon; no scope creep in classifications.
* Fix (commit d7769bf8): both World rows capped at APPROXIMATED through `PARTIAL_HANDLING_CAPS` (it only lowers), Env Vector note
  corrected, matrix regenerated; the ceiling dropped by those two rows. The reviewer re-reviewed that follow-up: **round 2 ACCEPT**.
  Round 2 was not blind to round 1, and it covers the scanner and matrix only (not the scorer code).
* opencode flash critic (`deepseek-v4.1-flash-free`): CHANGES, seven claims (Thickness hand credit, report-sink holes in
  `_is_consumed`, Env Vector, `scan_object_image_evidence` stores, branch-local served names, flag scope). They overlap the reviewer's
  findings 1, 5 and 6; none credits an unconsumed row beyond the bounded cases below; none blocking.
* Open follow-ups (non-blocking, for issues): Material Output `target` falls back to an EEVEE-only output; TexImage interpolation is
  not reported on two load paths (b4 only); `_REPORT_SINKS` and `_is_consumed` accept reads that only feed reports; Material Output
  Thickness is credited because Cycles ignores it too.

Files: `docs/blender_parity/evidence/gate_b/scanner_823_{proof,review_receipt}.json`.

## Landing note (the pinned commit must be on main)

`verify_scanner_integration_proof` requires the pinned commit to be an ancestor of `origin/main` and the on-disk scanner to equal it.
`d7769bf8` is the scanner-only commit of this branch. Either land that commit on main first (cherry-pick or fast-forward; then no
change is needed), or, after a squash merge, re-pin: set `commit` in the proof and receipt to the merged main SHA (the scanner file
is unchanged, so its sha stays `78e65e59...`), recompute the receipt sha256 in the proof, then re-run `--freeze-v5` / `--freeze-v4`
and `--score` for both populations. The scores in this doc and the committed reports were produced in a clone in which `origin/main`
pointed at this branch, so the ancestry check held.

## Reproduce

```
export BLENDER_EXE="C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"   # PATH has Blender 5.1 first
export ASTRORAY_PYD_DIR=<staged addon>   PYTHONPATH=<repo>
blender -b --factory-startup --python benchmarks/reference_corpus/coverage_report.py -- --audit-enumerate --study-out <W>   # supplement
python benchmarks/reference_corpus/coverage_report.py --audit-freeze --study-out <W>
python benchmarks/reference_corpus/coverage_report.py --audit-render --backend CPU --study-out <W>
python scripts/build/gpu_locked_run.py <who> -- python benchmarks/reference_corpus/coverage_report.py --audit-render --backend GPU --cycles-from <W>/CPU --study-out <W>
python benchmarks/reference_corpus/coverage_report.py --audit-judge --study-out <W>                  # writes audit_results.json
python benchmarks/reference_corpus/coverage_report.py --freeze-v5 --population candidate_v2 --node-uses docs/blender_parity/evidence/gate_b/node_uses_v4_candidate_v2.json --scanner-integration docs/blender_parity/evidence/gate_b/scanner_823_proof.json
python benchmarks/reference_corpus/coverage_report.py --score --input-manifest docs/blender_parity/coverage_input_v5_candidate_v2.json --node-uses docs/blender_parity/evidence/gate_b/node_uses_v4_candidate_v2.json --out docs/blender_parity/evidence/gate_b/candidate_v2
```

Gotchas found: `harness._find_blender` takes Blender 5.1 from PATH unless `BLENDER_EXE` is set; the matrix generator and the legs need
`ASTRORAY_PYD_DIR`. The earlier `coverage_input_v4_candidate_v2.json` is superseded by the v5 input and no longer scores (its matrix
hash is stale); it is left in place as history.

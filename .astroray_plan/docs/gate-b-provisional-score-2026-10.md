# Gate (b) provisional v4 score — 2026-10-06 (pkg318)

**PROVISIONAL. Not ratified, not gate-eligible.** No population is chosen, b1 is unsigned, and the #823 scanner receipt is
a lane self-review (labelled "not independent" inside the receipt). Nothing here changes `acceptance_manifest.json`.

## Result

| Population | Scenes | Uses | Weight (sum min(n,3)) | S_CPU | S_GPU | Matrix-only ceiling | b1 | b2 | b3 | b4 | b5 | b6 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| nine legacy scenes (`coverage_input_v4.json`) | 9 | 308 | 469 | **0.000** | **0.000** | 0.422 | F (unratified) | F | F | F (57 silent drops) | F (4 of 4 families) | PASS (vacuous) |
| corpus v2 (8 `v2_*`) + production (8) (`coverage_input_v4_candidate_v2.json`) | 16 | 233 | 474 | **0.000** | **0.000** | 0.426 | F | F | F | F (53) | F (3 of 3 exercised; Displacement not exercised) | PASS (vacuous) |

`coverage_report.py --score` exits 0, `status: provisional`, CPU and GPU reported separately (reports:
`docs/blender_parity/corpus_coverage.md` + `coverage_report.json` for the nine scenes,
`docs/blender_parity/evidence/gate_b/candidate_v2/` for the candidate). The candidate input is diagnostic only.

**Nonzero uses: none.** The only registered witness (`ShaderNodeTexChecker|input:Color1`, `textures_mapping`) was rendered on
both backends and failed the frozen predicate (`ssim >= 0.95`, `dE <= 5`):

| Backend | ssim | dE | masked-checker mean ratio vs Cycles | effect (checker present, both engines) |
|---|---|---|---|---|
| CPU | 0.846 | 6.33 | 1.001 / 1.001 / 1.001 | pass |
| GPU | 0.839 | 6.59 | 1.001 / 1.001 / 1.001 | pass |

The checker itself matches Cycles; `witness_metrics` takes ssim/dE over the whole ROI rectangle, and the non-feature pixels
in it read r/g/b 0.84/0.91/0.94 (CPU), 0.85/0.92/0.95 (GPU) of Cycles. Viewing the ROI (Astroray | Cycles | |diff|x3 | mask;
top GPU, bottom CPU): `docs/blender_parity/evidence/gate_b/checker_color1_roi_gpu_cpu_provisional.png`. If it had passed it
would be worth 1/469 = 0.002. Both sidecars are committed (`evidence/gate_b/sidecars/`, `verdict.pass: false`, so they
validate as 0); the retained arrays (~50 MB) stay in `astra_run\batch-f\f6\gate_b\cases\` and the sidecars reference them by
absolute path, so re-verification works on this machine only.

## Method and build

1. `coverage_report.py --collect --population {nine_scene,candidate_v2}` in Blender 5.2 (no collection errors), then
   `--freeze-v4 --population ... --candidate-build ... --scanner-integration ...`; the input files are committed before
   scoring (the scorer requires the exact HEAD bytes).
2. Evidence: `harness.py --gate-b-cases coverage_input_v4.json --corpus-manifest populations/nine_scene.json` under
   `gpu_locked_run.py lane-f6` (about 2 min of rendering after a 3 min lock wait; 2 cases x 4 legs). The candidate has no registered witness, so no render.
3. Build under test: staged CUDA module `build_id 132c974+20261004T124622Z` (2026-10-04, sha256 `93cc14f0...915aac`) — it
   **predates #1069 and #1071**; addon sha256 `002c7c43...dc736e` is `blender_addon/__init__.py` at a52f0e07. The lead
   should re-run the evidence legs on the post-merge build (the checker case is unlikely to move; the module changes
   case ids, so it needs a re-freeze). Receipt: `evidence/gate_b/scanner_823_*_provisional.json` — commit cb70daa3, scanner
   source sha `1488e17e...`; regenerating the matrix with it under Blender 5.2 reproduces the committed 586-row
   `coverage_matrix.json` exactly (so #872's drift is not present on current main).

Code change (tooling only): `coverage_report.py --population` writes a derived corpus manifest under
`benchmarks/reference_corpus/populations/` and the freeze records it as `corpus.manifest_path`; a v4 input may carry a
provisional EMPTY case map (nothing can validate, so it can only score 0). Two tests added; `--self-test` and
`tests/test_pkg278_gate_instruments.py` pass (74).

## Lost-weight ranking (every use scores 0, so lost weight = weight; each use is assigned one root cause)

| # | Root cause | Weight nine / cand | % (nine) | Issue | What fixes it |
|---|---|---|---|---|---|
| 1 | matrix-SUPPORTED, no pixel witness / control mutation (Noise 20, Brick 12, Wave 11, Bump 10, Mapping 8, ...) | 127 / 135 | 27.1 | #1087 (new) | register witnesses + `render_leg` control kinds per family; fix the checker predicate (mask, not rectangle) |
| 2 | Principled BSDF sockets matrix-APPROXIMATED (no note) | 84 / 84 | 17.9 | #1087 (new) | decide approximation vs SUPPORTED per socket; approximations also need an attributable warning + witness (rule d) |
| 3 | output sockets have no matrix row | 70 / 74 | 14.9 | #1039 | scanner credits output sockets |
| 4 | other APPROXIMATED: Diffuse/Refraction 16, Voronoi 11 (#975), Metallic 9, Principled Volume 7, Emission 6, Volume Scatter/Absorption 5, Sky 4 | 58 / 50 | 12.4 | #1087, #975 | witnesses + warnings; Voronoi 2D/4D |
| 5 | Output/Background/Environment/IES "no handler in addon translation layer" | 39 / 40 | 8.3 | #1088 (new) | scanner credits root-output handling (matrix reclassification) |
| 6 | Hair Principled inputs/model DROPPED | 27 / 9 | 5.8 | #1089 (new), #1051 | verify engine, reclassify, witness |
| 7 | BSDF Normal / Tangent / Coat Normal inputs DROPPED | 20 / 11 | 4.3 | #1089 (new) | real drop vs uncredited Bump path |
| 8 | collector socket id has no matrix key (Value_001, Fac, A_Color, Shader_001, NodeGroupOutput) | 15 / 28 | 3.2 | #1088 (new) | reconcile canonical identity |
| 9 | enum props `distribution`, `subsurface_method` + Anisotropic inputs DROPPED | 15 / 12 | 3.2 | #1089 (new) | verify export reads them |
| 10 | Principled Volume "mapped to glass", Sky props, Glass thin film, misc | 14 / 31 | 3.0 | #1089 (new), #946 | stale after #833 / pkg296 / pkg256? |

(The partition sums to 469 and 474.) Ceilings, assuming every credited use then gets perfect evidence: today 0.422 / 0.426;
if causes 3, 5 and 8 are repaired and credited SUPPORTED 0.687 / 0.726; Principled also lifted to SUPPORTED about 0.78 / 0.81.
The DROPPED families (6, 7, 9, 10: 76 / 63 weight) must be proven real or stale before 0.95 is conceivable. The full
per-use list is `docs/blender_parity/coverage_report.json` (`cpu.uses`, weight and reason per identity).

## Findings and owner questions

- Matrix-stale rows go to #872 (not reproducible on main now; consider closing) / #1039; the new audit is #1088/#1089.
- The checker case fails on both backends on whole-ROI metrics although the feature matches; changing the predicate to the
  feature mask is a new frozen version, so it needs an owner decision (#1087).
- Gate (b) needs three owner calls: population (nine scenes vs corpus v2 + production; this lane used the README's eight `v2_*`
  scenes plus the eight production scenes, leaving out `camera_lens_ortho` and the six `vm_*` volume scenes), who signs b1,
  and who gives the independent #823 scanner review (the lane receipt is not independent).
- Reaching even a first nonzero score is bounded by witness authoring, not by the scorer.

# Run report 2026-10-24/25 (Fable 5.1 lead; Opus/Sonnet lanes; DeepSeek V4.1 flash free)

Session: owner resumed 2026-10-24 ~23:40 ("all agents back", free DeepSeek flash with vision, GPU/PC returned);
usage-limit cutoff 03:30-04:40; closeout 2026-10-25 morning. Previous report: `run-report-2026-10-06.md`.

## Merged (9 PRs, all squash, all lead-reviewed + independent review where engine code changed)

| PR | What | Reviews |
|---|---|---|
| #1148 | scanner credits Geometry Pointiness (#1117); matrix regen on Blender 5.2 | lead |
| #1149 | Voronoi 3D = Cycles 5.2 port (#1108), 58/58 exact | lead (retro parity review still owed) |
| #1151 | #1125 uint32 transparent pass count; kWfTransparentOff resets in ReSTIR + snapshot drivers | cpp-abi-guard PASS-notes |
| #1157 | #1004/#1005 image bump steps the input UV, Linear normal map, procedural Height on CPU, coat on sd->N | cycles-parity (2 regressions fixed), cpp-abi-guard x2 |
| #1161 | pkg324 spectral showcase corpus v1: nine scenes, four-way sheets, analytic checks, gallery | lead visual sign-off + vision tier |
| #1163 | pkg326 Glass BSDF Thin Film sockets -> native Principled film | lead |
| #1166 | pkg325 dielectric bounce-cap passthrough (OFF by default) + thick-glass acceptance scene | cpp-abi-guard PASS-notes |
| #1169 | gate (b) first formal score, re-frozen inputs, independent scanner receipt | blind Opus scanner review ACCEPT |
| #1170 | #995/#955 closure composition: Mix per-texel Fac + Add closure sum, CPU+GPU; emissive BSDFs continue | cycles-parity (MAJOR fixed), cpp-abi-guard |

Docs direct to main: models/tiers (free flash + vision tier), delegate fixes (`--dir`, `--file`, text-only finish),
gates (e)/(g)/(b) records, architect plan + specs pkg324/325/326, STATUS, handover.

## Stage 0 gates at closeout (`stage0-gate-scoring-2026-10-18.md`)

| Row | Status | Measured |
|---|---|---|
| (a) latency | GREEN | p95 62.9 / p99 100.6 ms (10-18) |
| (b) coverage | **RED, first formal score** | nine_scene S = 0.00213 (checker witness); owner population 0/474 (no witness registered) |
| (c) trio | GREEN | Welch-1b 0 rejected tiles (10-18) |
| (d) native panels | GREEN | committed |
| (e) triage | GREEN (10-24, 69 open, 0 high) -> **RED (10-25, 81 open, 8 high)** | the highs are this session's own findings (#1150, #1152, #1154, #1155, #1158, #1162, #1165, #1171) |
| (f) clean install | waits on the second PC | — |
| (g) node score | RED | CPU 2/8, GPU 2/8, 0 silent pairs on `bdbe4f1+20261024T162029Z`; pbr_group 11/16 both, car_paint CPU 13/16, wood 12/16 both, shader_stack 4/16 both after #1170 |

## Integration sweeps

- Pre-closeout sweep on main 624e32df (engine bdbe4f1c, dist restaged): **5672 passed, 10 failed, 77 skipped, 66 xfailed,
  3 xpassed, 64 min**. Triage: 4 = hair_tuft ortho GPU strict XPASS (improvement, un-xfailed); 5 = incomplete
  `provisional_v2.toml` rows (motion_vane gpu_cpu listed only r; RoughGlassFilm r) with identical ratios on the pre-#1125
  baseline pyd (bd651551) and main, so pre-existing; 1 = OneDrive PermissionError on the matrix scratch dir (environmental).
  No engine regression attributable to this session's merges.
- Final sweep on main c76baf57 (engine ecd36567: #995 + pkg325 landed; dist restaged 07:46): **5709 passed, 9 failed, 79 skipped, 66 xfailed, 3 xpassed, 60 min**. Triage: 8 = `v2_textures_opvm sphere_MixShaderProg` (4 CPU rows strict XPASS: #1170 fixed the CPU program-Fac mix, un-xfailed; 4 GPU/CPU twin rows 0.86x: the GPU closure tree still lags, filed #1174, rows added); 1 = `test_blender_parity_matrix_generation`: the committed matrix differs from a fresh Blender 5.2 regeneration in exactly one row (`ShaderNodeTexImage|interpolation` DROPPED-SILENT -> SUPPORTED, the #1157 report-only read over-credited by the scanner, #1168); regenerating would break the pkg260/corpus pins, so the fix is #1168, not a regen. After the `provisional_v2.toml` fixes the touched rows verify 44 passed / 29 xfailed / 0 failed under the lock. No engine regression attributable to this session's merges; one GPU gap (#1174) exposed by a CPU fix.

## Issues filed (16) and closed (1)

#1150 GPU ReSTIR-DI black behind alpha-0; #1152 pass-plan counter guard; #1153 GPU procedural bump + coat normal;
#1154 Cycles bump correction + shadowing term; #1155 diamond Sellmeier preset; #1156 bump CPU/GPU twin drift;
#1158 library-linked images; #1159 Separate/Combine + Vector Math tiles; #1160 (closed: scene defect, coincident faces);
#1162 smooth-glass film; #1164 bg colour before env map (unreduced); #1165 cap off-by-two vs Cycles; #1167 scorer silent
zero; #1168 scanner over-credit paths; #1171 sun power scaling; #1172 spot light-tree cone.

## Lanes and cost

Lanes: i1125 (Opus), i1004 (Opus, 2 builds), pkg324 (Sonnet), pkg326 (Sonnet), pkg325 (Sonnet x2, retired on context),
i995 (Opus, 2 builds), gateb (Sonnet), pkg306 Phase 0 (Opus; GPU leg pending). Reviews: cpp-abi-guard x4, cycles-parity x2,
blind scanner review x1, blind raters x5 (Sonnet) + 2 (flash). Builds by the lead: 9 worktree CUDA builds, 3 main rebuilds,
3 addon restages. GPU jobs all under `gpu_locked_run.py`; no overlap with builds; no hardware resets.

## Owner questions (carried in `architect-plan-2026-10-25.md` §5 + `next-session-prompt-2026-10-25.md`)

1. #995 glass 1/eta^2 radiance convention (keep pbrt, or match Cycles for emission seen through glass).
2. pkg325 default stays OFF (Cycles parity) — confirm.
3. pkg324 README publishing + licences; evidence storage (git vs LFS vs local; #1161 added 11 MB).
4. Material preset library scope; gate (f) second PC; (b) b1 sign-off.

## Tooling notes

Vision tier works (`delegate.py --tier vision --image`), reliable on presence/absence, not on position/size; delegate
status fix e2fa88c8; the CI `changes` filter hides tooling test breakage on main (memory
`ci-changes-filter-hides-tooling-test-breakage`); coincident-face scenes masquerade as GPU parity bugs (memory
`coincident-faces-optix-tie-break-parity-gap`).

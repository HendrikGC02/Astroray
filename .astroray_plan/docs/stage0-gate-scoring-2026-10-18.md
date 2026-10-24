# Stage 0 gate scoring, 2026-10-18 (overnight session, Fable lead)

Build under test: main `3bb710b8` (= #1123 merged + the 10-07 PRs), staged addon module
`3bb710b+20261017T134944Z` (`dist/astroray`, sha256 `0dbf6b51…c62489`), `build_cuda` at the same
HEAD. Machine: RTX 5070 Ti, Ryzen 7 7800X3D 8C/16T (SMT on since 2026-10-18). Evidence root:
`%LOCALAPPDATA%\astroray-evidence\2026-10-18\`.

| Row | Status | Value | Evidence | Note |
|---|---|---|---|---|
| (a) latency | **GREEN** | GPU p95 62.9 ms / p99 100.6 ms (thresholds 100/150); cancel p95 33.1 / p99 38.3 ms; stale frames after ack 0; subchecks both_pinned_scenes, 3x100 repetitions, denoise_excluded, gpu_only_latency all true | `a6-10-18-gate-a-instrument.json`, `acceptance_manifest.ac2.json` ((a)+(c) green) | Formal `--mode gate_a`, worker ON, visible isolated Blender 5.2 on 9877, staged addon. A first capture (`a-run1-red-edit6\`) read p95 87.6 / p99 104.5 but was RED on one edit without a presented-generation chain; the clean re-capture is the record. Was 78.2 / 109.7 on beda188 (10-06). |
| (g) node score | RED | CPU 2/8 in band, GPU 1/8 (threshold 6/8); 1 silent pair per backend = `NewGeometry|output:Pointiness` (#1117, fixed on `lane/issue1117`, pending PR) | `g\instrument.json`, `g\work\` | Unchanged from 10-06 on this build. After #1139 + #1117 land: 0 silent pairs; after #1144: prod_attributes GPU in band (GPU 2/8). The path to 6/8 is still #1004/#1005 (bump), #995 (shader_stack), #1038 (light_path glass). |
| (c) trio | **GREEN** | Welch-1b 0 rejected tiles in all roles (materials_hall 0/7920, textures_mapping 0/24116, world_sky terrace 0/5940); ROI channel-mean max 0.73 %; SSIM informational min 0.769 (terrace, noise-limited) | `c-welch\row_c_welch.json`, `acceptance_manifest.c.json` (VALID, (c) green) | First formal run on a stamped main build; the 10-06 run was on a `dev` integration build. Closes #1111. |
| (e) triage | RED → 1 open high | Two blind Sonnet raters, AGREE 8/8 (`gate-e-triage-2026-10-18.md`); #1047 closed (items landed / re-tracked as #1125); the only open high is #1124 (lane item 2 tonight) | `astra_run\2026-10-18\gate-e\rating_{A,B}.md` | The committed manifest still carries the 10-05 snapshot (10 highs); re-reduce at closeout from a fresh snapshot + a ratings file covering all 69 open issues. |
| (e) triage, **2026-10-24 re-reduce** | **GREEN** | 69 open issues, `high_count` 0 (40 medium, 28 low, 1 n/a); every rating from a pass independent of the lead: 10-04 Terra+Sonnet (Opus reconciled) 49, 10-06 blind 5, 10-18 two Sonnet raters 6, 10-24 two blind Sonnet 5.5 raters for #1128–#1136 (agree 8/9; #1132 stricter = medium) | `docs/blender_parity/evidence/e/{instrument,issue-ratings,issues-baseline,issues-recheck}.json`, raters in `%LOCALAPPDATA%\astroray-evidence\2026-10-24\gate-e\` | Committed manifest row (e) green, subchecks all true; manifest VALID. The third (opencode DeepSeek) rater errored on the wrapper's removed `--dir` flag and was not needed. |
| (g) node score, **2026-10-25 re-measure** | RED | CPU 2/8 in band, GPU 2/8 (threshold 6/8); **0 silent pairs** on both backends (Pointiness credited by #1148); build `88d2026+20261024T142646Z` (main 88d2026d = #1148 merged, staged addon restaged at HEAD); 21 passed / 12 xfailed, 133.9 s | `%LOCALAPPDATA%\astroray-evidence\2026-10-24\g2\{instrument.json,work\}` | Silent-pair component of (g) is clear. Remaining path to 6/8: #1004/#1005 (bump; lane PR pending, CPU 11/16 pbr_group, 13/16 car_paint on branch), #995 (shader_stack), #1038 (light_path glass), #993 (wood Roughness chain). |
| (g) node score, **2026-10-25 re-run on the merged build** | RED | CPU 2/8, GPU 2/8 (threshold 6/8), 0 silent pairs; build `bdbe4f1+20261024T162029Z` (main bdbe4f1c = #1125 + #1004/#1005 merged; staged addon restaged 03:31); 21 passed / 12 xfailed, 130.6 s. Per scene (channels in band): pbr_group CPU 11/16, GPU 11/16; car_paint CPU 13/16, GPU 2/16 (#1153); wood CPU 12/16, GPU 12/16; curves 13/16, 15/16; attributes and marble in band; shader_stack 0/16 (#995 lane: CPU in band on its branch) | `%LOCALAPPDATA%/astroray-evidence/2026-10-24/g3/` | Score unchanged because the 16/16 band is per-scene; the path to 6/8 is #995 (both backends), #1153 (GPU procedural bump), #993 (wood B), #1004 residual (pbr_group right ROI). |

## M6 glass re-measure (merged main, Cycles 5.2 MULTI_GGX default, `metal_ab/harness.py --material glass`)

| roughness | centre A/C (R,G,B) | limb A/C | limb/centre Cycles vs Astroray |
|---|---|---|---|
| 0.0 | 0.999 0.9996 0.999 | 0.964 0.970 0.962 | 1.603 vs 1.547 |
| 0.2 | 0.991 0.991 0.991 | 0.886 0.891 0.883 | 1.743 vs 1.559 |
| 0.5 | 0.972 0.972 0.969 | 0.946 0.954 0.945 | 1.919 vs 1.868 |
| 0.85 | 0.928 0.933 0.926 | 0.728 0.732 0.726 | 1.748 vs 1.370 |

Evidence `astra_run6-10-18\m6-glass\metal_ab\glass_ab_report.{json,md}` + renders. Reading: the #1038 centre excess (+6-9 %) and the #968 rim excess (+7.5 %) no longer reproduce; both rows are at or below Cycles. The limb deficit at r >= 0.85 is the documented #1123 divergence (Cycles evaluates geometrically invalid refraction pairs only through NEE; Astroray zeroes them, Walter 2007 / pbrt-v4). `scripts/run_parity.py` could not run (#1145: OpenCV 5.0 wheel has no EXR writer).

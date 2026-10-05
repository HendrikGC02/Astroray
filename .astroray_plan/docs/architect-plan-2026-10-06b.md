# Architect plan 2026-10-06b: overnight long-haul, second queue

This is the second state+refine run of the night (Opus 5.5 architect, ~07:10). The previous plan
(`architect-plan-2026-10-06.md`) is done. Every item is merged, or it is in a PR that carries GPU-verified evidence
(#1093–#1098). The rules stay the same: the lead dispatches Sonnet/Opus lanes, at most 2 run at once, lanes build CPU
only, and the lead owns CUDA builds and the GPU lock.

## Where Stage 0 stands

| Row | Now | Lever that needs no owner input |
|---|---|---|
| (a) latency | RED at 102.1 ms (2026-10-05), before pkg315. #1083 cut the 100k material edit from 44 to 4.2 ms in the engine | Lead re-measure (P1). #1050 makes the worker-OFF capture prove its binding |
| (b) coverage | 0.000 / 0.000. The matrix-only ceiling is 0.42 | Scanner defects (pkg320). The only witness fails on a real scene bias, not on the predicate alone (#1099). DROPPED rows audit (pkg321). Witness instrument (pkg323) |
| (c) trio | RED on SSIM only. Under Welch it was RED on two real defects, which #1091 has since fixed | Welch re-run on post-#1091 main (M1) gives the owner a current answer |
| (d) panels | GREEN | — |
| (e) triage | Every high is fixed or in a PR | Rate tonight's new issues (P3) |
| (f) install | Unmeasured | Needs a clean host (owner) |

Two observations change the plan:

1. **The gate (b) checker witness is not only a predicate problem.** The evidence sheet
   (`docs/blender_parity/evidence/gate_b/checker_color1_roi_gpu_cpu_provisional.png`) shows Astroray's wall darker
   than Cycles. The strip right of the swatch is near black where Cycles is lit brown. CPU and GPU agree, so gate (c)
   cannot see this. It is filed as **#1099**. If the cause is setup or engine and it gets fixed, the existing witness
   can pass under the **unchanged** frozen predicate. That would give gate (b) its first nonzero score with no owner
   decision.
2. **#1038 (Glass centre r/b +6–9 %) has a likely one-line cause.** In Cycles `kernel/svm/closure.h`, the
   `CLOSURE_BSDF_MICROFACET_GGX_GLASS_ID` case sets `reflection_tint = transmission_tint = color`. Astroray's
   `dielectric.cpp` reflects with weight 1. With Color (0.9, 1.0, 0.95), that predicts r > b > g ≈ 1, which is the
   measured sign pattern (1.087 / 1.012 / 1.057).

On the product themes: owner decision 2026-09-29 holds the spectral library (pkg312) and data cubes (pkg313) until
after Stage 0 exit. pkg311 Phases 2 and 3 (the UI) wait on those two. So tonight's only product-theme work is node
coverage. That suits the plan, because node coverage also moves gate (b) and the pkg310 node score.

## Lead pre-steps (no lane)

- P0. Land #1093–#1098 on their reviews and CI. Land or close #1066 (gate (a) frame pruning) before P1. Open a PR for
  `origin/fix/1060-cornell-parity-setup` (cace572d: the cornell harness mismatch, SSIM 0.93 → 0.9994; pushed, no PR).
  Verify #954, which is marked fixed in 80f39ec5, and close it.
- P1. Gate (a) Blender re-measure on the post-#1083 build. Use the formal `--mode gate_a`, ~13 min, worker ON, on a
  quiet window. Record the pooled p95 and a per-cell p95 table.
- P2. Re-run the gate (b) evidence legs on post-merge main. pkg318 measured a build from before #1069/#1071, so this
  needs a re-freeze.
- P3. Rate the new issues under the gate (e) rubric with two blind Claude passes: #1081, #1082, #1087–#1089, #1092,
  #1099. My read: #1081 is medium. Its wrong image is confined to GR scenes with lit non-emissive interiors.

## Ordered work list

The GPU register column follows lane rule 13: the shade kernel is at REG 254. "None" means no device code is touched.

| # | Id | Problem | Approach (cited) | Main files | Gate | GPU register risk | Needs |
|---|---|---|---|---|---|---|---|
| 1 | **pkg320** (#1088 + #1039) | Output sockets, root outputs and the Mix Shader branch are uncredited, and collector socket ids have no matrix key. That is 124 / 142 weight of false DROPPED-SILENT or "absent" | Mechanical scanner evidence (the #1028 discipline). One canonical socket identity (Blender `identifier`) on both sides | `scripts/generate_blender_parity_matrix.py`, `coverage_report.py`, regenerated matrix | Matrix-silent count falls by exactly the listed rows. A negative fixture is still not credited. prod_light_path and prod_attributes show 0 silent pairs. Scratch ceiling ~0.69 / 0.73 (from 0.42 / 0.43) | None | CPU only |
| 2 | **#1099** | textures_mapping wall reads 0.84/0.91/0.94 of Cycles around the checker. The only witness fails because of it | Setup audit first: lights, world node, FOV, wall export. #1060 cornell was exactly this. Then a probe of the wall material on a coplanar surface under a uniform world, the au-coords method | `benchmarks/blender_parity/` scene and harness, or the engine path the probe isolates | Non-feature ROI pixels within the MC band of Cycles on CPU and GPU. The existing checker witness passes under the unchanged frozen predicate, or the report names the residual | None if setup. Low to medium if engine (lead measures) | CPU first; GPU legs via the lead |
| 3 | **#1038** (centre only) | Glass BSDF sphere centre r/b +6–9 % vs Cycles, on CPU and GPU | Tint reflection as well as transmission by Color, as in Cycles `kernel/svm/closure.h` GGX_GLASS (`reflection_tint = transmission_tint = color`, Apache-2.0). Glass only: Principled reflection stays untinted (specular tint) | `plugins/materials/dielectric.cpp` (all sample and eval paths), the rough-glass plugin if Glass roughness > 0 routes there, GPU closure-graph lowering of Glass, addon Glass export | `glass_ball_centre` 1 ± 0.03 on CPU+GPU with plain Glass. A TIR-only analytic test returns Color. Principled glass renders byte-identical. prod_light_path rows re-measured. **Stop rule:** if r moves by less than half the gap, report it and test hypothesis 2 (the roughness 0.02 lobe). The sun-shadow fill is out of scope (physical caustic, owner physics-over-look) | Low: the lobe weight is set at upload, with no per-hit state | CUDA build |
| 4 | **pkg322** (Pointiness, #989 residual) | Geometry Pointiness raises `VMCompileError`. prod_curves_geometry is at 0/16 CPU and 3/16 GPU | Port Cycles `intern/cycles/blender/mesh.cpp` `attr_create_pointiness` (Apache-2.0) to numpy at export, onto the #990 per-corner attribute layer. The op-VM reads it as an Attribute | `blender_addon/pointiness.py` (new), `shader_vm_compiler.py`, `__init__.py`, `build_blender_addon.py` | Per-vertex values within 1e-3 of a Cycles bake on 3 meshes. A CPU+GPU probe lands in the MC band. No Pointiness report on prod_curves_geometry. Scenes that do not read it are byte-identical | None: host side, existing `gpu_attrTexel` | CUDA build only to confirm |
| 5 | **#975** | Voronoi 1D/2D/4D is evaluated as 3D (reported DEGRADED). It carries 11 weight in gate (b) | Port Cycles `kernel/svm/voronoi.h` exactly for 1D/2D/4D: F1, F2, smooth F1, distance to edge, n-sphere radius, all metrics, randomness (Apache-2.0) | `include/astroray/procedural_tex.h`, `plugins/textures/voronoi.cpp`, `src/gpu/wavefront/proc_tex_eval.cu`, addon Voronoi export | Coplanar tiles under a uniform white world, per dimension × feature: min channel ratio ≥ 0.998 vs Cycles 5.2 on CPU+GPU. DEGRADED entry removed. 3D renders byte-identical | Medium: keep the new dimensions in the out-of-line `proc_tex_eval.cu`. REG/STACK for 3D unchanged (cuobjdump) | CUDA build |
| 6 | **pkg321** (#1089) | 76 / 63 weight of DROPPED-SILENT rows has never been checked: Hair, BSDF Normal/Tangent, enums, Principled Volume, Sky, thin film | Counterfactual probe per family. A stale row is credited through the scanner. A real drop gets a DegradationReport warning and an issue, and is not fixed here | Generator, addon warnings, audit doc, probe tests | Every row has a verdict and evidence. Matrix-silent count falls by the stale rows. Real drops read "reported". Renders CPU byte-identical | None | After 1, and after #1093 for the hair rows |
| 7 | **#1092** | A strand's TT and shadow rays re-hit the same fibre. The hair tuft is still ~2.5 % low after pkg316 | Cycles skips the whole curve on self-intersection, not just the segment. Add a per-segment strand-id array; `skipPrim` compares strand ids. Re-pin `test_issue1037` against Cycles (lane rule 9) | `include/astroray/curves.h`, `src/gpu/gpu_nee.cuh`, the GPU intersect `skipPrim` sites | Bent single strand: TT energy vs Cycles 5.2 in the band. hair_tuft rows CPU+GPU. Curve-free scenes byte-identical | Low: the same int compare in intersect, plus one global load on curve hits only | After #1093; CUDA build |
| 8 | **pkg323** (#1087, the part that needs no predicate change) | One control kind and one witness exist, and the owner is asked to change the predicate on a sample of one | Control kinds `noise_const`, `brick_const`, `wave_const`, `bump_zero`, `mapping_identity`. A candidate (unfrozen) case map scored under both the rectangle and the mask predicate (pkg317 study shape) | `render_leg.py`, `coverage_report.py` (`region` argument, frozen default), study doc | Frozen `--score` is byte-identical. ≥ 10 witnesses × 2 predicates × CPU/GPU, with sheets inspected. Owner question written | None | After 1 and 2; GPU legs via the lead |
| 9 | **#875** | An object move on the 100k scene presents at p95 23.5 ms with the worker OFF and 46.8 ms with it ON. The target is < 20 ms, and the engine share is 5.6–6.4 ms | Attribute first: lifelines from the existing `gate_a_table` capture. Then cut the largest share. If it is the engine, apply a device-side delta transform plus GAS refit (OptiX `OPTIX_BUILD_OPERATION_UPDATE`) instead of the host re-upload. The #1096 IAS-only pattern is the precedent | `module/blender_module.cpp`, `src/gpu/gpu_wavefront_snapshot.cu`, `blender_addon/exporter.py` | 100k transform cell (`--mode gate_a_table`) p95 < 20 ms OFF and better than 46.8 ms ON. Render matches a full re-sync within atol 2e-6. Stop rule: if the residual is present/Blender overhead (≥ 13.8 ms, the camera-OFF floor), report it and stop | None for the host path. The refit is host-launched OptiX | CUDA build; GUI Blender under the GPU lock |
| 10 | **#1050** | The worker-OFF gate (a) capture keeps POST_PIXEL presents only in memory. The reducer trusts `correct_present_ns` | Emit raw `sync_render` and `post_pixel_present` events, as the worker path does. The reducer validates the binding, with tests for forged shapes | `benchmarks/viewport_parity/blender_recorder.py`, `blender_driver.py`, `tests/test_pkg278_gate_a_recorder.py` | Forged-shape tests fail closed. The six OFF cells are re-measured once in a quiet window and the table is updated | None | Python; one GUI window via the lead |

Measurement items for closeout (lead, or a measuring lane on the merged build):

- M1. **pkg317 Welch re-run** on post-#1091 main, 8 seeds × 3 trio roles. CPU legs ~9 min, GPU ~3 min. Before #1091,
  gallery and workshop failed mainly on #1084/#1085 (gallery also showed scatter on shiny props). If all three now pass, owner question 2 becomes "adopt and gate
  (c) turns green".
- M2. **pkg310 re-measure**: N/8 for CPU and GPU after #1093/#1097/#1098 and items 3–5. Remove strict rows that now
  pass (0 XPASS). Inspect the sheets.

Reserve, if the queue empties:

- R1. #1001 item 1, TTFS: measure the first-call breakdown on the heavy scene. Then skip the CPU BVH and the GPU
  software-BVH upload for OptiX-eligible scenes that have no software-BVH consumer (photon, ReSTIR, SMS, alpha
  shadow).
- R2. #1004 residual (pbr_group centre 0.91×): apply the bump `valueOffset` step before Mapping on CPU+GPU.
- R3. #1044 CPU photon rounds: SPPM rounds after Hachisuka & Jensen 2009 and Knaus & Zwicker 2011. CPU only.
- R4. #1001 item 4: transparent-shadow walk in OptiX `__raygen__shadow`, after #1095.
- R5. #1034: motion-blur Object/Generated coordinates.
- R6. #995: per-hit Mix Shader closure weights, after #1097. This one is probably 2 sessions.

## Scheduling

- Pairs that keep at most one CUDA build in the queue: (1 + 3), (2 + 4), (5 + 10), (6 + 7), (8 + 9). Then M1 and M2.
- Items 1, 2, 6, 8 and 10 never wait on the build queue. Item 2 goes early, because item 8's table is only readable
  once #1099 is attributed.
- Each batch gets one GPU suite pass before its PR, never overlapping a build (lane rule 12).

## Excluded

- Pillar 4 is paused. That includes #1081 and #1082 (GR in-region lighting needs geodesic NEE, which is research,
  not a lane) and #894.
- pkg312, pkg313 and pkg311 Phases 2/3: owner set them for after Stage 0.
- #1024 negative scene-linear output: needs an owner decision.
- #1005 procedural Bump: needs ray-differential footprints, so it is multi-session.
- #956 and #942 affect the custom Disney material only, which the Blender export does not use.
- pkg297 QMC and pkg300 Phase 2: multi-session.

## Owner questions

1. Gate (b): which population (nine legacy scenes, or corpus v2 + production), who signs b1, and who gives the
   independent #823 scanner review? pkg323 will add the predicate data for #1087.
2. Gate (c): adopt the Welch tile test (pkg317 candidate 1b)? M1 will say whether the trio is then green.
3. Gate (f): a clean host. Windows Sandbox (admin + reboot) or a clean PC/VM?
4. Gate (e): with Codex out until 2026-11-04, may two blind Claude passes stand in for the independent rating?
5. Production node score (pkg310): add it to the manifest as row (g), as the 2026-09-29 decision implies?
6. Carried over: where (a)/(c) evidence is stored (git, LFS or local), and the README prism exposure.

# Architect plan — overnight long-haul, 2026-10-06

State+refine run (Opus 5.5 architect) for the unattended night of 2026-10-06. The lead dispatches Sonnet 5.5 lanes
(CPU builds only, ≤ 2 concurrent) and owns CUDA builds and the GPU lock. Inputs: `STATUS.md` (2026-10-05),
`stage0-gate-scoring-2026-10-05.md`, `gate-e-triage-2026-10-05.md`, `next-session-prompt-2026-10-05.md`,
`lane-rules.md`, owner memories (decisions 09-29, themes 09-29, integration-first, Pillar 4 paused).

## Where Stage 0 stands

| Row | 2026-10-05 | Tonight | Remaining lever |
|---|---|---|---|
| (a) latency | RED, pooled p95 102.1 ms | #1068 −33 ms engine-side on 100k material edits; Blender re-measure pending | pkg315 (#1067) for margin |
| (b) coverage | unmeasured | — | pkg318 measures it; population + b1 are owner calls |
| (c) trio | RED on SSIM only (terrace 0.783; ROI gaps < 0.61 %) | — | pkg317 gives the owner a noise-aware option |
| (d) panels | GREEN | — | — |
| (e) triage | RED, 10 high | 9 of 10 highs in PRs | pkg316 (#1051); tonight's follow-ups will re-open (e) (below) |
| (f) install | unmeasured | — | pkg319 removes the likely failures; host is owner-side |

Two things the run should not lose sight of:

1. **Gate (e) will not reach 0 with the ten highs alone.** Under the published rubric (wrong image, crash, silently
   ignored native setting), several follow-ups filed tonight read as high: #1063 (objects inside a black-hole region
   are invisible), #1073 (`transparent_max_bounces` silently ignored on shadow rays), #1075 (data passes show
   indirect-only objects), probably #1070 (pillar base 0.81× Cycles at low sun). They are in this plan for that reason.
2. **Gate (b) is the furthest row from green and nobody has the number.** The matrix-only upper bound is 0.42 on the
   nine-scene population (0.77 production) against 0.95. pkg318 turns that into a ranked backlog.

## Lead pre-steps (no lane)

- P0. Land the in-flight PRs (#1071, #1074, #1076, #1033, #946/#1042) on their reviews and gates.
- P1. Gate (a) Blender re-measure on the post-#1068 build (`blender_driver.py --mode gate_a`, ~13 min); record a
  per-cell p95 table beside the pooled value, so pkg315's gain is attributable.
- P2. Rate tonight's new issues (#1063, #1067, #1070, #1072, #1073, #1075) under the rubric with two blind Claude
  passes (Sonnet 5.5, Opus 5.5); Codex is out of quota (see owner question 4).

## Ordered work list

GPU register column: the shade kernel is at REG 254 (lane rule 13). "None" = no device code touched.

| # | Id | Problem | Approach (cited) | Main files | Gate | GPU register risk | Needs |
|---|---|---|---|---|---|---|---|
| 1 | **pkg315** (#1067) | 100k material edit re-flattens the whole scene (~32 ms host) | Material-domain invalidation; Cycles `ShaderManager` vs `GeometryManager` device_update split | `gpu_wavefront_snapshot.cu/.h`, `scene_upload.cu`, `blender_module.cpp` | Byte-identical vs full re-flatten (4 edit kinds); engine edit < 10 ms; gate (a) pooled p95 ≤ 100 ms | None (host only) | CUDA build; after P1 |
| 2 | **pkg316** (#1051) | Hair tuft g/b 0.91–0.95 of Cycles; melanin tuft −22 % | Lobe grid + furnace vs pbrt-v4 HairBxDF (Apache-2.0) and Chiang 2016; then parametrization, `h`, integrator legs; stop rule | `hair_bsdf.h`, `gpu_hair.cuh`, `principled_hair.cpp`, `curves.h` | Furnace ±1 %; tuft rows in MC band CPU+GPU, removed from `provisional_v2.toml`; melanin energy ±5 % with matched mask | Low: formula-only in the shade kernel, no new state | CPU first; CUDA build if GPU mirror changes |
| 3 | **#1063** | Geometry inside the black-hole influence region is invisible | Intersect the scene BVH against each accepted RK45 step as a chord: nonlinear ray tracing by piecewise-linear segments (Gröller 1995, *The Visual Computer* 11; Weiskopf et al. 2004) | `include/astroray/black_hole.h` (`traceGR`), `include/raytracer.h` | Emissive sphere straddling `r_max` continuous across the boundary; sphere fully inside visible; GR reference-bank scenes within their gates; non-GR scenes byte-identical | None (GR is CPU-only) | CPU only |
| 4 | **Batch S**: #1073 + #1047 item 3 | Shadow rays ignore `transparent_max_bounces` (CPU 8 / GPU 31 hops); shadow-ray Light Path reads only `LPF_SHADOW` | Mirror Cycles `kernel/integrator/intersect_shadow.h` (transparent-hit budget = max − path's transparent bounces) and the parent path flags carried by `shade_surface.h` (Apache-2.0) | `include/raytracer.h` (`shadowTransmittance`), GPU shadow stage + enqueue site, `include/astroray/light_path.h` | N stacked Transparent sheets, `transparent_max_bounces` N−1 vs N, ROI vs Cycles 5.2 in MC band CPU+GPU; Is Reflection / Is Singular on shadow rays match Cycles on a two-material probe | Medium: shadow-queue entry +budget/flags; reuse `lp_state` bits; lead runs cuobjdump | After #1033 merges; CUDA build |
| 5 | **Batch T**: #1075 + #1046 | Albedo/normal/depth AOVs show indirect-only objects; CPU photon map seeded identically when seed = 0 | Route the AOV first hit through `hitCameraRay` (Cycles writes data passes for camera-visible surfaces only); derive the photon seed from the resolved render seed | `plugins/integrators/spectral_path_tracer.cpp`, GPU AOV first-hit path | Indirect-only sphere absent from 3 AOVs on CPU+GPU, beauty unchanged; two seed-0 renders give different photon maps, seeded renders reproducible | Low: camera/AOV stage only | After #1076 merges; CUDA build for the GPU AOV check |
| 6 | **pkg318** | Gate (b) has no number; v3 input stale, sidecars empty | Run the existing pkg278 scorer end to end: `--collect`, `--freeze-v4`, sidecars, `--score`; rank zero-scoring uses by lost weight | `coverage_report.py` (selector only if needed), new `coverage_input_v4*.json`, sidecars, doc | `--score` exits 0, provisional S_CPU/S_GPU for both populations, every nonzero use linked; top-10 lost-weight causes with issues | None | After #1071; GPU evidence legs via lead |
| 7 | **pkg317** | Gate (c) SSIM fails on independent noise | Per-tile Welch t-test (Jung, Hanika, Dachsbacher 2020, JCGT 9(2)); SSIM noise ceiling; downsampled SSIM; multi-seed mean; Mitsuba 3 z-test precedent | new `benchmarks/blender_parity/mc_compare.py`, `harness.py --seeds` | Synthetic null FPR at α; table over trio + negative/positive controls; owner question; no gate file changed | None | ~20 min GPU legs via lead |
| 8 | **pkg319** | No check that the ZIP is self-contained; no clean host | Transitive PE import closure (Win32 DLL search order, API sets) in the canonical build script; `--rehearse` mode for the gate (f) capture that the validator always rejects | `scripts/build/build_blender_addon.py`, `scripts/validate_clean_install.py`, `docs/install-clean-machine.md` | Closure passes (or lists real misses, then bundled); fixture catches a deleted DLL; rehearsal install + CPU F12 exit 0; `--validate` rejects rehearsal | None | CPU only |
| 9 | **pkg310 re-measure** (burndown refresh) | Production node score last measured 1/8 (2026-10-03); tonight's node fixes unmeasured | Existing harness: `build_corpus.py` scenes, `report_tools.py production`, `silent_drop_audit.py` | `pkg310-production-corpus-burndown.md`, `provisional_production.toml` | N/8 CPU/GPU on the post-merge build; strict rows that now pass removed (0 XPASS); sheets inspected | None | After P0; GPU legs via lead |
| 10 | **#1072** | GPU Add Shader renders child A only (CPU sums since #1071) | Un-normalised `add` node weights; pick a lobe proportional to `sample_weight` with the mixture pdf, as Cycles `surface_shader_bsdf_bssrdf_pick` in `kernel/integrator/surface_shader.h` (Apache-2.0) | `gpu_closure_graph_eval` (`include/astroray/gpu_materials.h`), closure-graph upload | GPU Add(Diffuse red, Diffuse blue) = (0.7, 0.2, 0.7) matches CPU `test_issue955_add_shader.py`; prod_shader_stack GPU rows re-measured | High: shade kernel. Side-table flag + `template<bool>` axis (memory `shade-axis-side-table-avoids-spill`); REG/STACK unchanged for non-add materials | After #1071; CUDA build |

Reserve, if the queue empties: R1 #1070 diagnosis (low-sun stone pillar base 0.81×; CPU-first, suspect low-sun NEE vs
disc profile); R2 #1001 item 2 (IAS-only rebuild on transform edits, keep GAS; viewport); R3 #1052 (apply pkg317's
conclusion to the pHash gate, after the owner picks).

## Scheduling

- Lanes run in pairs; pair CUDA-needing items with CPU-only ones, so the lead's build queue holds one build at a time:
  (1 + 3), (2 + 8), (4 + 7), (5 + 6), then 9 at closeout and 10 if a slot remains.
- CPU-only items (3, 8, most of 6 and 7) never wait on the build queue.
- One GPU-suite pass per batch before its PR (lane rule 12: never overlapping a build).
- Items 6 and 9 measure; they must run after the PRs they measure have merged, or record the exact build.

## Excluded

Pillar 4 (paused); pkg297 QMC and pkg300 Phase 2 (multi-session; not overnight-sized); anything that needs owner
setup (clean host, toolkit installs) or a gate decision.

## Owner questions

1. Gate (b) population: corpus v2 + production (proposed), or the nine legacy scenes? Who signs b1? Your 2026-09-25
   note says the corpus needs no ratification, but b1 requires an owner artifact.
2. Gate (c) metric: once pkg317 reports, do you want the Welch tile test (or another option) in place of SSIM?
3. Gate (f): enable Windows Sandbox (admin + reboot) or provide a clean PC/VM?
4. Gate (e): with Codex out until 2026-11-04, may two blind Claude passes stand in for the independent rating?
5. Production node score (pkg310, 1/8): it was named a Stage 0 exit row on 2026-09-29, but the manifest has no row
   for it. Should it be added as row (g)?
6. Carried over: (a)/(c) evidence storage (git, LFS or local), and the README prism exposure.

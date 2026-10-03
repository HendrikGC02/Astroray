# Scripts — canonical index

**Agents: read this before writing a new script.** Every recurring task
below already has ONE canonical script. Duplicating one of these (e.g. a
new "material contact sheet" one-off) is a hygiene violation — extend the
canonical script instead, or delete yours after use. If you add a genuinely
new reusable script, register it here in the same commit.

## Canonical script per task

| Task | Canonical script |
| ---- | ---------------- |
| Test-suite durations report (junit.xml to by-area/by-file/top-test charts + JSON; before/after with 2 files) | `python scripts/test/durations_report.py --junit PATH [--junit PATH2]` |
| Build engine `.pyd` (dev, Ninja + sccache) | `scripts/build/build_cuda.bat` |
| Build engine in an agent worktree (Ninja) | `scripts/build/build_cuda_worktree.bat` |
| Run ANY command (pytest, render harness) under the shared GPU lock (main-checkout lock path; never write the lock file) | `python scripts/build/gpu_locked_run.py <who> -- <command...>` |
| Lead-only serial CUDA/addon build queue for multi-worktree sessions (FIFO, own lock, clears dead locks; lanes never build) | `python scripts/build/lead_build_queue.py <lane>[:addon-cuda]` |
| CUDA build under the shared GPU lock (main-checkout lock path, launcher-free/no sccache; the lead-session pattern) | `python scripts/build/gpu_locked_build.py <tree> scripts/build/build_cuda_nosccache.bat <who>` |
| Build engine in an agent worktree (VS generator; what `hardware-verifier` / `package-implementer` / `tests/test_hw_verifier_buildenv.py` invoke) | repo-root `build_cuda_worktree.bat` |
| Build-integrity guard (header-hash stamp, <5 s host-only ABI canary, cuobjdump CUDA-arch gate) invoked by all three build wrappers | `scripts/build/build_guard.py` (pkg183) |
| Build/package/install the Blender addon | `scripts/build/build_blender_addon.py` (default backend: `cuda`) |
| One-command Blender dev loop (build → install → smoke) | `scripts/dev_addon.ps1` |
| Diagnose the local Blender MCP bridge without changing it | `scripts/dev/check_blender_mcp.ps1` |
| Run the test suite against a build dir | `scripts/dev/run_tests.py` (default: `build_cuda/`) |
| pkg314 graph-IR resource stats (instructions, peak slots, constants, tables, textures, max closures) per shader-graph program root of a set of `.blend` files (run inside Blender) | `scripts/dev/shader_graph_ir_stats.py -- --out <md> <files...>` |
| Material contact sheet / showcase renders / convergence + timing graphs | `benchmarks/showcase/runner.py` (curated presets: `config.MATERIAL_ZOO_VARIANTS`) |
| Test-result output paths, labelled comparison sheets, stat charts, `test_results/index.html`, `clean` (`python tests/results_layout.py index\|clean [--legacy]`) | `tests/results_layout.py` (`results_path`, `save_comparison_sheet`, `save_stat_chart`); rules in `.astroray_plan/docs/test-results-conventions.md` |
| Multi-scene SPP convergence sweep (diagnostic) | `scripts/diagnostics/convergence_tracker.py` |
| Cycles↔Astroray parity table (CI) | `scripts/run_parity.py` + `scripts/summarize_parity.py` |
| Blender differential parity harness | `benchmarks/blender_parity/harness.py` |
| Visual reference-bank gates | `benchmarks/reference_bank/runner.py` |
| README gallery / hero renders | `scripts/diagnostics/render_readme_gallery.py`, `render_readme_hero.py` |
| Blender addon showcase scenes (glass dispersion, volumes, Nishita sky, thin film + metals): build `.blend` + render Cycles/Astroray PNGs | `benchmarks/blender_showcase/showcase.py` (run inside Blender; `build` / `render` subcommands) |
| Render-output triage | `scripts/diagnostics/render_output_triage.py` |
| Denoiser A/B | `scripts/diagnostics/oidn_comparison.py` |
| Project knowledge index (search / owns / deps / node-tree graph) | `scripts/project_index.py` (SQLite; `build` / `query` / `owns <path>` / `script <task>` / `whatis <pkg>` / `deps` / `graph` / `gh-sync`; auto-rebuilds when a spec is newer than the DB). **Interactive graph of the whole index (2D / 3D / timeline; inspector, search `/`, focus `f`, health overlay, deep links; needs network for the pinned CDN libs, falls back to a table offline): [`.astroray_plan/project-index-graph.html`](../.astroray_plan/project-index-graph.html).** Regenerate with `python scripts/project_index.py build && python scripts/project_index.py graph --html .astroray_plan/project-index-graph.html`. |
| Lint package specs against TEMPLATE v2 | `python scripts/project_index.py lint` (`[PATH...] \| --all`; baselined via `scripts/spec_lint_baseline.txt`) |
| Open-weight model evaluation bench | `scripts/model_bench.py` (`--dry-run`, `--models`, `--timeout`; read-only, writes `.astroray_plan/docs/model-bench-results.json`) |
| Native-settings F12 pixel-honour A/B matrix (does each adopted Blender/Cycles control actually change the render?) | `scripts/verify_pkg200_honour_matrix_run.py` (outer, cv2/per-channel mean-ratio) + `verify_pkg200_honour_matrix.py` (in-Blender A/B leg) + `pkg200_honour_matrix.py` (pure contract/predicate layer, enumerated from `settings_map.py`) |
| Import a .blend without Blender | `tools/blend_import/blend_to_astroray.py` |
| Spectral data/profile generation | `scripts/data/generate_spectrum_data.py`, `build_spectral_profiles.py` |
| Sobol' direction-vector table (pkg224 progressive sampler) | `scripts/gen_sobol_matrices.py` → `include/astroray/sampling/sobol_matrices.h` (bakes SciPy's Joe-Kuo vectors; idempotent, commit header with any change) |
| Hero-wavelength luminance-CDF fit (pkg206 importance-sampling constants) | `scripts/data/fit_hero_luminance_cdf.py` |
| Extract a Cycles `shader.tables` LUT to `data/disney_compensation/*.bin` (pkg261 `ggx_gen_schlick_ior_s`) | `scripts/data/extract_ggx_gen_schlick_ior_s.py` (`--fetch` pins blender/blender@eaa5f63b; parses the C initializer, writes float32 LE) |
| Launch GUI Blender 5.2 with the MCP bridge (watch/restart) | `pwsh scripts/dev/launch_blender_mcp.ps1 -Watch` (diagnostic: `scripts/dev/check_blender_mcp.ps1`) |
| Bring up the MCP bridge inside Blender (startup script `launch_blender_mcp.ps1` passes with `--python`) | `scripts/dev/blender_mcp_autostart.py` |
| Roadmap orchestrator tick | `scripts/orchestrator_tick.ps1 -Driver claude\|opencode` → `python -m roadmap_orchestrator.cli` |
| Regenerate the addon known-issues doc from GitHub issues (`addon-bug`/`addon-gap`) | `python scripts/dev/known_issues_report.py` (`--check` in CI) |
| Viewport-interactivity parity harness (in-process pan/zoom/orbit timing) | `benchmarks/viewport_parity/run.py` (pkg81) |
| Viewport-interactivity Cycles A/B driver (runs inside Blender) | `benchmarks/viewport_parity/blender_driver.py` (pkg81 companion to `run.py`) |
| Gate-(a) real-Blender GPU producer (retains generation-labelled POST_PIXEL evidence; requires two explicit SHA-pinned 10k/100k workload descriptors) | `benchmarks/viewport_parity/blender_driver.py --mode gate_a --gate-a-build-id <id> --gate-a-workload <10k.json> --gate-a-workload <100k.json>` (pkg278; capture only in an isolated GUI Blender session) |
| Isolated GUI Blender on a non-default MCP port (9877) for measurement lanes — never the owner's 9876 | `scripts/dev/launch_isolated_blender.ps1 -Port 9877 -Worker 0\|1 -StateDir <dir> [-StagedAddon <worktree>/dist/astroray]` (`-StagedAddon` loads a worktree build via `BLENDER_USER_EXTENSIONS` without installing into the user profile) (startup `scripts/dev/blender_mcp_isolated.py` stops + rebinds the bridge synchronously) |
| Blender parity coverage-matrix generator (AST-scanned SUPPORTED/APPROXIMATED/DROPPED-SILENT/UNKNOWN; #996: op-VM dispatch reads, guard-evaluated conditional sockets, property reads, procedural `Vector`; hand-verified rows only in `SCANNER_BLIND_OVERRIDES`; a regeneration on Blender 5.2 reproduces the committed `docs/blender_parity/coverage_matrix.json`, enforced by `tests/test_blender_parity_matrix.py`; scanner unit tests `tests/test_pkg310_matrix_scanner.py`) | `scripts/generate_blender_parity_matrix.py` (pkg119 Phase A; run inside Blender 5.2: `blender -b --factory-startup --python scripts/generate_blender_parity_matrix.py -- --out docs/blender_parity`) |
| Cycles feature-coverage reference-corpus builder (pkg259; builds `.blend` + manifest per family, cross-checks builder coverage against `coverage_matrix.json`) | `benchmarks/reference_corpus/build_corpus.py` (run inside Blender; scene ids: `materials_hall`, `textures_mapping` (Phase 1), `lighting_studio`, `world_sky_hdri`, `world_sky_sky` (Phase 2), `geometry_zoo`, `camera_lens`, `render_settings` (Phase 3), `camera_lens_ortho` (#845), `volumes_smoke` (pkg271, writes its own synthetic `.vdb` assets); pkg284 v2 ids `v2_light_tree`, `v2_media`, `v2_dispersion_caustics`, `v2_sky_sun`, `v2_thin_film_metals`, `v2_textures_opvm`, `v2_camera_geometry`, `v2_viewport`; pkg296 `volumes_mesh` ids `vm_icosphere`, `vm_icosphere_empty`, `vm_suzanne`, `vm_nested`, `vm_overlap`, `vm_camera_inside`, `vm_glass_shell`; one scene per Blender process) |
| Cycles feature-coverage reference-corpus report tooling (pkg259; npy->PNG, per-crop extraction from `manifest.json` `crops` rects, Cycles-vs-Astroray + per-crop contact sheets) | `benchmarks/reference_corpus/report_tools.py` (run in the repo's normal Python env, not Blender) |
| Gate (b) weighted socket-coverage scorer (pkg278; `--collect` in Blender computes scene-used reachability and active constant/link variants, `--freeze` writes immutable `docs/blender_parity/coverage_input_v2.json` with an asset- and ledger-locked population, and `--freeze-v4 --scanner-integration <proof.json>` accepts only a hash-pinned #823 commit/source/review receipt; `--input-manifest` and `--sidecar-dir` freeze repository-relative paths. `--score` re-verifies committed input, assets, snapshot and ledger before separately scoring CPU/GPU; #823-gated, never green before it lands) | `benchmarks/reference_corpus/coverage_report.py` (`--collect` run inside Blender; `--freeze`/`--freeze-v4`/`--score`/`--self-test` in the repo's normal Python env) |
| pkg278 acceptance-manifest aggregate (the sole reducer for rows a–f; can adapt Gate-B runner evidence through `--adapt-b-*` before computing statuses) | `scripts/gate_manifest.py` |
| pkg284 corpus-v2 Monte-Carlo tolerance bands (renders each `v2_*` scene on the Cycles CPU / Astroray CPU / Astroray GPU legs at N seeds via `render_leg.py`, derives per-ROI per-channel + luminance bands from both engines' seed scatter, writes `gates_v2.toml` + the 1024 spp reference EXRs; normal Python env, drives Blender) | `benchmarks/reference_corpus/mc_tolerance.py` |
| pkg307 noise-per-time benchmark (equal-spp + equal-time relMSE / relVar / chroma / bias^2 / tail share / N x relVar slope / efficiency per scene and ROI; legs Astroray CPU/GPU, Cycles CPU/OptiX, Mitsuba 3 spectral; render-only time by spp differencing, min-of-3 after a burn-in, per 1280x720 frame). Flags on existing tools: `mc_tolerance.py --noise-bench [--nb-stages time render report] [--nb-legs ...] [--budgets 2 10 60] [--nb-tag T] --work-dir W` (GPU legs only under `scripts/build/gpu_locked_run.py`), `render_leg.py --cycles-leg-device gpu` (Cycles OptiX) and `--res-percent`, `report_tools.py noise-bench --work-dir W --out-dir test_results/_runs/integrator/noise-per-time` (tables, charts, equal-time contact sheets). Arbitration scenes (Phase 2: prism under sun, chromatic medium, narrow-band lamp): `benchmarks/reference_corpus/arbitration/build_arbitration.py` (inside Blender; writes scenes + manifest) and `mitsuba_scenes.py` (Mitsuba venv `C:/Users/hgcom/tools/venv-mitsuba`; `PARAMS` is shared with the builder), run via `mc_tolerance.py --suite arbitration [--arb-calibrate]` | `benchmarks/reference_corpus/mc_tolerance.py` |
| pkg310 silent-drop audit for the production node-tree corpus (`collect` in Blender: exercised = reachable AND linked/non-default (node, socket) pairs, reusing `coverage_report`'s tree builder and reachability trace; `audit`: diffs them against the frozen `coverage_matrix.json` and each render's `DegradationReport` log; `coverage`: pkg278 weighted-score formula over the matrix classification alone, the upper bound gate (b) can reach (#996); `--self-test`: non-vacuity fixture). The rest of the pkg310 harness is flags on existing tools: `build_corpus.py --families prod_*` (writes `benchmarks/reference_corpus/production/`), `mc_tolerance.py --suite production`, `report_tools.py production --work-dir ... --out-dir ...` (Cycles / CPU / GPU contact sheets + band-utilisation chart + N/8 summary) | `benchmarks/reference_corpus/silent_drop_audit.py` |
| pkg296 `volumes_mesh` multi-seed ROI means (mesh-bounded volumes; one Blender process renders every `vm_*` scene x seed x `volume_bounces`, Cycles or Astroray; Cycles output is the committed `refs_v2/volumes_mesh_cycles.json`, the Astroray leg is run by `tests/test_pkg296_mesh_volume_boundary.py`) | `benchmarks/reference_corpus/volumes_mesh_bands.py` (run inside Blender) |
| #881 Blender Noise Texture reference values at exact points (all dimensions 1D-4D x noise types, distortion, normalize off; Fac + Color; Geometry Nodes = the blenlib twin of Cycles `noisetex.h`) for `tests/test_issue881_noise_dimensions.py` | `tests/fixtures/gen_issue881_noise_reference.py` (run inside Blender; writes `tests/data/issue881_noise_blender_reference.json`) |
| pkg256 Cycles-vs-Preetham/Perez sky-band A/B (renders `world_sky_sky` in Cycles, bakes the same Sky node, prints per-band luminance ratios; consumed by `tests/test_pkg256_sky_bake.py`) | `benchmarks/reference_corpus/sky_ab_bands.py` (run inside Blender) |
| Rough-metal/rough-glass live-Cycles A/B driver (CPU/GPU vs Cycles oracle; `--material metal\|glass`) | `benchmarks/cycles-parity/metal_ab/harness.py` (pkg129 metal preset; pkg263 added the glass preset + limb/centre/background ROIs) |
| Thin-film iridescence A/B driver vs Cycles-5.2 oracle | `benchmarks/cycles-parity/thin_film/harness.py` (pkg178 Stage-4 acceptance) |
| Heitz-2016 multiple-scattering dielectric random-walk oracle (numpy; MS vs single-scatter vs Cycles 1/E divergence table + directional histograms) | `benchmarks/cycles-parity/glass_ms_oracle/heitz_random_walk.py` (pkg265; clean-room from DOI 10.1145/2897824.2925943) |
| Heitz-2016 **independent** oracle: explicit Gaussian(Beckmann) heightfield ray tracer (geometric, no Smith abstraction) + numpy glass-sphere path tracer — validates the multiple-scattering exit-interface redistribution vs Cycles 1/E (issue #782) | `benchmarks/cycles-parity/glass_ms_oracle/heightfield_oracle.py` (pkg265; Heitz 2016 §Validation, explicit random Beckmann surfaces) |
| Blender dev-loop guard functions (stale-.pyd, OpenMP-on, addon-files-drift, sentinel-pass) used by `dev_addon.ps1` | `scripts/dev_loop_guards.py` (pkg175; OpenMP guard inverted by #780) |
| Wavefront SoA baseline measurement harness; pkg298 Cornell pair (simple / 2 M-tri) vs Cycles OptiX/CUDA: fixed per-call cost, burn-in + min-of-N full renders, 256² vs 1024² pool throughput | `benchmarks/wavefront_baseline.py` (pkg55 Phase A; `--cornell-pair [--cycles] [--pool]`; pkg300 `--env-sweep 'label:K=V+K=V,...'` interleaved env-config A/B, min-of-rounds, Cycles leg `benchmarks/wavefront/cycles_leg.py`) |
| Caustic-integrator visual/stat validation (pkg74 may reuse its scene builders) | `scripts/benchmarks/benchmark_caustic_transport.py` (pkg29a) |
| Light-transport integrator head-to-head (path tracer / auto / NRC fallback / NRC backend) | `scripts/benchmarks/benchmark_light_transport.py` (pkg27b) |
| Kerr validation fixture generator (analytic, GYOTO/RAPTOR-cited but not linked; imported by `tests/test_kerr_validation.py`) | `scripts/generate_gyoto_references.py` (pkg41) |
| tiny-cuda-nn CUDA smoke build (opt-in CMake target `tcnn_smoke`) | `scripts/cuda/tiny_cuda_nn_smoke.cu` |
| NRC prototype CUDA smoke render (opt-in CMake target `nrc_smoke_render`) | `scripts/cuda/nrc_smoke_render.cu` (pkg26) |
| Standalone-binary render used by the Blender addon smoke test | `scripts/dev/render_test_scene.py` (invoked by `scripts/dev/blender_addon_smoke.py`) |
| Weekly local cycles-parity + showcase bench (manual; replaces the retired self-hosted-runner `cycles-parity.yml` / `showcase.yml` workflows) | `scripts/benchmarks/weekly_local_bench.ps1` |
| Capture and validate portable clean-host Blender ZIP-install evidence for gate (f) | `scripts/validate_clean_install.py --capture` / `--validate` |

Note on the two `build_cuda_worktree.bat` copies: they are intentionally
different pipelines (root = VS multi-config, no configure step, SHA
validation, pinned by agent configs and `tests/test_hw_verifier_buildenv.py`;
`scripts/build/` = Ninja single-config + sccache full configure). Do not
delete either; a future package may unify them.

## Folders

| Folder | Contents |
| ------ | -------- |
| [`build/`](build/README.md) | Blender addon packaging and CUDA build helpers. |
| [`diagnostics/`](diagnostics/README.md) | Render triage, denoising comparisons, convergence checks, README render generators. `_preview_helpers.py` is a shared helper module (imported by the material contact-sheet scripts), not an entry point. |
| [`benchmarks/`](benchmarks/README.md) | Caustic and light-transport benchmark runners (showcase lives in `benchmarks/showcase/`). |
| [`data/`](data/README.md) | Spectral profile and spectrum data generation utilities. |
| [`dev/`](dev/README.md) | Test runners and Blender smoke scripts. |
| [`cuda/`](cuda/README.md) | CUDA smoke harness sources compiled by optional CMake targets (tcnn opt-in). |
| [`test/`](test/) | Test-selection helpers (`run_split.py`, `select_impacted.py`) used by conftest/CI. |
| [`roadmap_orchestrator/`](roadmap_orchestrator/) | The orchestrator subsystem behind `/roadmap-orchestrator`. Modules: `ci.py` reduces a statusCheckRollup; `classify.py` buckets open PRs; `cli.py` is the read-only tick-plan emitter; `locks.py` provides the tick-overlap + single-GPU-slot locks; `plan.py` is the pure tick-plan builder; `priority.py`/`queue.py` order NEXT_STAGE_REPORT; `standup.py` renders the daily standup markdown; `state.py` persists debounce + the SHA-bound HW ledger. |

One-off package-verification scripts (`verify_pkgNNN_*.py`) are deleted once
their package closes — the PR + STATUS.md hold the evidence. Exceptions that
REMAIN because they are reusable harnesses (registered in the table above):
`scripts/verify_pkg175_smoke_blender.py` (wired into `dev_addon.ps1`) and the
`scripts/verify_pkg200_honour_matrix*.py` + `pkg200_honour_matrix.py` A/B
honour driver. pkg201 extended that driver in place (not a fork): the
`world_max_bounces` row was repointed to `world.cycles.max_bounces` (Finding B),
and a `use_light_tree` row + its `many_lights` scene builder were added
(promoting the former pkg200 known-gap) — no new script.

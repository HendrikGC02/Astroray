# Scripts — canonical index

**Agents: read this before writing a new script.** Every recurring task
below already has ONE canonical script. Duplicating one of these (e.g. a
new "material contact sheet" one-off) is a hygiene violation — extend the
canonical script instead, or delete yours after use. If you add a genuinely
new reusable script, register it here in the same commit.

## Canonical script per task

| Task | Canonical script |
| ---- | ---------------- |
| Build engine `.pyd` (dev, Ninja + sccache) | `scripts/build/build_cuda.bat` |
| Build engine in an agent worktree (Ninja) | `scripts/build/build_cuda_worktree.bat` |
| Build engine in an agent worktree (VS generator; what `hardware-verifier` / `package-implementer` / `tests/test_hw_verifier_buildenv.py` invoke) | repo-root `build_cuda_worktree.bat` |
| Build-integrity guard (header-hash stamp, <5 s host-only ABI canary, cuobjdump CUDA-arch gate) invoked by all three build wrappers | `scripts/build/build_guard.py` (pkg183) |
| Build/package/install the Blender addon | `scripts/build/build_blender_addon.py` (default backend: `cuda`) |
| One-command Blender dev loop (build → install → smoke) | `scripts/dev_addon.ps1` |
| Run the test suite against a build dir | `scripts/dev/run_tests.py` (default: `build_cuda/`) |
| Material contact sheet / showcase renders / convergence + timing graphs | `benchmarks/showcase/runner.py` (curated presets: `config.MATERIAL_ZOO_VARIANTS`) |
| Multi-scene SPP convergence sweep (diagnostic) | `scripts/diagnostics/convergence_tracker.py` |
| Cycles↔Astroray parity table (CI) | `scripts/run_parity.py` + `scripts/summarize_parity.py` |
| Blender differential parity harness | `benchmarks/blender_parity/harness.py` |
| Visual reference-bank gates | `benchmarks/reference_bank/runner.py` |
| README gallery / hero renders | `scripts/diagnostics/render_readme_gallery.py`, `render_readme_hero.py` |
| Render-output triage | `scripts/diagnostics/render_output_triage.py` |
| Denoiser A/B | `scripts/diagnostics/oidn_comparison.py` |
| Roadmap orchestrator tick | `scripts/orchestrator_tick.ps1` → `python -m roadmap_orchestrator.cli` |
| Native-settings F12 pixel-honour A/B matrix (does each adopted Blender/Cycles control actually change the render?) | `scripts/verify_pkg200_honour_matrix_run.py` (outer, cv2/per-channel mean-ratio) + `verify_pkg200_honour_matrix.py` (in-Blender A/B leg) + `pkg200_honour_matrix.py` (pure contract/predicate layer, enumerated from `settings_map.py`) |
| Import a .blend without Blender | `tools/blend_import/blend_to_astroray.py` |
| Spectral data/profile generation | `scripts/data/generate_spectrum_data.py`, `build_spectral_profiles.py` |

Note on the two `build_cuda_worktree.bat` copies: they are intentionally
different pipelines (root = VS multi-config, no configure step, SHA
validation, pinned by agent configs and `tests/test_hw_verifier_buildenv.py`;
`scripts/build/` = Ninja single-config + sccache full configure). Do not
delete either; a future package may unify them.

## Folders

| Folder | Contents |
| ------ | -------- |
| [`build/`](build/README.md) | Blender addon packaging and CUDA build helpers. |
| [`diagnostics/`](diagnostics/README.md) | Render triage, denoising comparisons, convergence checks, README render generators. |
| [`benchmarks/`](benchmarks/README.md) | Caustic and light-transport benchmark runners (showcase lives in `benchmarks/showcase/`). |
| [`data/`](data/README.md) | Spectral profile and spectrum data generation utilities. |
| [`dev/`](dev/README.md) | Test runners and Blender smoke scripts. |
| [`cuda/`](cuda/README.md) | CUDA smoke harness sources compiled by optional CMake targets (tcnn opt-in). |
| [`test/`](test/) | Test-selection helpers (`run_split.py`, `select_impacted.py`) used by conftest/CI. |
| [`prototypes/`](prototypes/) | Python-first algorithm validation prototypes (CLAUDE.md §6). |
| [`roadmap_orchestrator/`](roadmap_orchestrator/) | The orchestrator subsystem behind `/roadmap-orchestrator`. |

One-off package-verification scripts (`verify_pkgNNN_*.py`) are deleted once
their package closes — the PR + STATUS.md hold the evidence. Exceptions that
REMAIN because they are reusable harnesses (registered in the table above):
`scripts/verify_pkg175_smoke_blender.py` (wired into `dev_addon.ps1`) and the
`scripts/verify_pkg200_honour_matrix*.py` + `pkg200_honour_matrix.py` A/B
honour driver.

# `scripts/README.md` index audit — 2026-09-15

Scope: `scripts/README.md` (243 lines) checked against every `*.py` / `*.ps1` /
`*.bat` file under `scripts/` (recursive, `__pycache__` skipped). "Registered"
means the file's basename appears anywhere in `scripts/README.md`. Facts only;
no recommendations.

## Unregistered scripts

Basename does not appear anywhere in `scripts/README.md` (literal grep).

- `scripts/dev/blender_mcp_autostart.py` — `"""Blender startup script: bring up the MCP bridge so agents can drive Blender.` — last commit 2026-09-07
- `scripts/diagnostics/_preview_helpers.py` — `"""Shared one-sphere material preview helpers.` — last commit 2026-05-15
- `scripts/roadmap_orchestrator/__init__.py` — no docstring/comment; first line `__version__ = "0.1.0"` — last commit 2026-05-16
- `scripts/roadmap_orchestrator/ci.py` — `"""Reduce a GitHub statusCheckRollup to pass | fail | pending."""` — last commit 2026-05-16
- `scripts/roadmap_orchestrator/classify.py` — `"""Classify open PRs into action buckets. See plan Shared data contracts."""` — last commit 2026-05-22
- `scripts/roadmap_orchestrator/cli.py` — `"""Read-only tick-plan emitter. Side effects belong to SKILL.md, never here."""` — last commit 2026-05-21
- `scripts/roadmap_orchestrator/locks.py` — `"""File-based locks: tick-overlap guard and single-GPU-slot guard.` — last commit 2026-09-13
- `scripts/roadmap_orchestrator/plan.py` — `"""Pure tick-plan builder. Decides; never acts. See design spec Step 1/2/2a."""` — last commit 2026-08-20
- `scripts/roadmap_orchestrator/priority.py` — `"""Best-effort ordered package hint from NEXT_STAGE_REPORT.md section 2.` — last commit 2026-05-16
- `scripts/roadmap_orchestrator/queue.py` — `"""Order the HW-untested queue: NEXT_STAGE_REPORT priority, then oldest PR."""` — last commit 2026-05-16
- `scripts/roadmap_orchestrator/standup.py` — `"""Render and upsert the daily standup markdown. No GPU-debt ledger by design."""` — last commit 2026-05-22
- `scripts/roadmap_orchestrator/state.py` — `"""Persisted debounce + SHA-bound hardware-result ledger."""` — last commit 2026-05-24

Note (factual): `scripts/roadmap_orchestrator/cli.py` is the only entry whose
basename-grep result is arguably a false positive — the README references it in
module form (`roadmap_orchestrator.cli`). The other eleven have no textual
reference at all.

## Dangling index entries

Paths named in `scripts/README.md` that do not resolve to an existing
file/directory on disk.

- `[prototypes/](prototypes/)` (Folders table, in all three copies) → `scripts/prototypes/` does not exist.
- `docs/model-bench-results.json` (`model_bench.py` row) → does not exist; the output file on disk is `.astroray_plan/docs/model-bench-results.json`.
- `build_cuda/` (`run_tests.py` row, default build dir) → does not exist in the working tree.
- `cycles-parity.yml` (weekly-bench row, described as retired) → not present; `.github/workflows/` contains only `ci.yml`.
- `showcase.yml` (weekly-bench row, described as retired) → not present; `.github/workflows/` contains only `ci.yml`.

Bare references that do resolve to an existing file (not dangling):
`settings_map.py` → `blender_addon/settings_map.py`; `coverage_matrix.json` →
`docs/blender_parity/coverage_matrix.json`; `manifest.json` →
`benchmarks/reference_corpus/scenes/manifest.json`; `STATUS.md` →
`.astroray_plan/docs/STATUS.md`; `CLAUDE.md` → repo root;
`../.astroray_plan/project-index-graph.html` →
`.astroray_plan/project-index-graph.html`.

## Possible duplicates

Mechanical grouping by shared name stem and/or first docstring line sharing 2+
keywords (grouping is textual, not a claim of functional duplication).

- `scripts/build/build_cuda.bat`, `scripts/build/build_cuda_worktree.bat`, `scripts/build/build_cuda_nosccache.bat` — shared stem `build_cuda`.
- `scripts/build/build_blender_addon.py`, `scripts/build/build_guard.py`, `scripts/data/build_spectral_profiles.py` — shared stem `build_`.
- `scripts/build/gpu_locked_build.py`, `scripts/build/gpu_locked_run.py` — shared stem `gpu_locked`; first docstrings both contain "orchestrator GPU lock" + "poll, run, release-in-finally".
- `scripts/benchmarks/benchmark_caustic_transport.py`, `scripts/benchmarks/benchmark_light_transport.py` — shared stem `benchmark_*_transport`.
- `scripts/diagnostics/render_readme_gallery.py`, `scripts/diagnostics/render_readme_hero.py` — shared stem `render_readme_`.
- `scripts/diagnostics/render_test_scene.py`, `scripts/diagnostics/render_output_triage.py` — shared stem `render_`.
- `scripts/generate_blender_parity_matrix.py`, `scripts/generate_gyoto_references.py`, `scripts/data/generate_spectrum_data.py` — shared stem `generate_`.
- `scripts/run_parity.py`, `scripts/summarize_parity.py` — shared stem `parity`.
- `scripts/dev/run_tests.py`, `scripts/test/run_split.py` — shared stem `run_`.
- `scripts/verify_pkg200_honour_matrix.py`, `scripts/verify_pkg200_honour_matrix_run.py`, `scripts/pkg200_honour_matrix.py` — shared stem `pkg200_honour_matrix`.
- `scripts/dev/blender_addon_smoke.py`, `scripts/dev/blender_mcp_autostart.py`, `scripts/dev/blender_mcp_isolated.py` — shared stem `blender_` (`blender_mcp_` for the latter two).
- `scripts/dev/launch_blender_mcp.ps1`, `scripts/dev/launch_isolated_blender.ps1` — shared stem `launch_`.
- `scripts/dev_addon.ps1`, `scripts/dev_loop_guards.py` — shared stem `dev_`.
- `scripts/roadmap_orchestrator/{__init__,ci,classify,cli,locks,plan,priority,queue,standup,state}.py`, `scripts/orchestrator_tick.ps1` — shared stem `roadmap_orchestrator` / `orchestrator`.
- `scripts/roadmap_orchestrator/cli.py`, `scripts/roadmap_orchestrator/plan.py` — first docstrings share "tick-plan" + "never".
- `scripts/roadmap_orchestrator/priority.py`, `scripts/roadmap_orchestrator/queue.py` — first docstrings share "NEXT_STAGE_REPORT" + "priority".

## Counts

| Metric | Count |
| ------ | ----- |
| `*.py` / `*.ps1` / `*.bat` files under `scripts/` (recursive, excl. `__pycache__`) | 55 |
| Registered by basename in `scripts/README.md` | 43 |
| Unregistered by basename in `scripts/README.md` | 12 |
| Dangling paths in `scripts/README.md` | 5 |
| Possible-duplicate groups (mechanical) | 16 |
| Lines in `scripts/README.md` | 243 |
| Verbatim copies of the canonical-index + folders + note block in `scripts/README.md` | 3 (lines 1–71, 72–159, 160–243) |

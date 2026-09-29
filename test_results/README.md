# test_results

Curated render evidence and charts, organised by area and feature (`<area>/<feature>/`); open `index.html` for an overview.
Tests never write here: per-run output goes to the ignored `_runs/` tree through `tests/results_layout.py` (`results_path(area, feature, name)`).
Promote a run output by copying it into the curated tree, then regenerate the index: `python tests/results_layout.py index`.
Rules (areas, naming, sheets, charts, size caps): `.astroray_plan/docs/test-results-conventions.md`. Enforced by `tests/test_results_layout_guard.py`.

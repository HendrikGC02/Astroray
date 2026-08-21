# Astroray Knowledge Map

Routing index for agents — if you need X, go here. The machine-readable
version of this map is `python scripts/project_index.py` (a SQLite index over
packages, docs, tests, and optionally GitHub issues/PRs).

## Planning source of truth

- `.astroray_plan/docs/ROADMAP.md` — pillars, sequencing, tracks A–D.
- `.astroray_plan/docs/STATUS.md` — current state (goes stale within days; trust ROADMAP + git over this).
- `.astroray_plan/docs/NEXT_STAGE_REPORT.md` — recommended deployable set + drop-in prompts.

## Work packages (one per PR/session)

- `.astroray_plan/packages/*.md` — ~219 specs. Frontmatter: Pillar / Track / Status / Estimated effort / Depends on.
- `python scripts/project_index.py deps pkgNNN` — a package's dependencies + reverse-dependents.

## Research notes

- `.astroray_plan/docs/*.md` — physics / sampling / parity research, named `<topic>-research.md`.

## Search & graph

- `python scripts/project_index.py query "pixel filter"` — search packages + docs (word-wise).
- `python scripts/project_index.py owns <path>` — which package(s) own a file path, plus their status.
- `python scripts/project_index.py script "<task>"` — the canonical script for a task (the CLAUDE.md §5b no-duplicate gate; mirrors `scripts/README.md`).
- `python scripts/project_index.py whatis pkgNNN` — compact card for one package.
- `python scripts/project_index.py graph --html graph.html` — interactive node tree (packages ↔ docs ↔ files ↔ dependencies).

## GitHub

- `gh issue list` / `gh pr list` — live state (already authenticated).
- `python scripts/project_index.py gh-sync` — pull issues/PRs into the index (network).

## Code & tests

- `include/` — header-only core; `src/` — implementation; `plugins/` — plugin registry; `tests/` — 244 test files.
- Build & test commands: see `AGENTS.md`.

## Rules & drivers

- `AGENTS.md` — shared repo contract (read automatically).
- `CLAUDE.md` §1–§6 — behavioral rules (§6 no-invented-algorithms invokes the `cite-algorithm` skill).
- `.opencode/` — opencode agent drivers (opencode is the primary harness; Claude Code is the fallback).

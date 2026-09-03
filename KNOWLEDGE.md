# Astroray Knowledge Map

Routing index for agents — if you need X, go here. The machine-readable
version of this map is `python scripts/project_index.py` (a SQLite index over
packages, docs, tests, and optionally GitHub issues/PRs).

## Planning source of truth

Read these together before choosing work, in this order:

1. `.astroray_plan/docs/STATUS.md` — latest factual state.
2. `.astroray_plan/docs/NEXT_STAGE_REPORT.md` — current handoff and deployable set.
3. `.astroray_plan/docs/ROADMAP.md` — **Current sequencing**, owner priority, and pause directives.

Then check package frontmatter and current git/GitHub state. Old reports and
archived plans are context, not dispatch authority.

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
- `.codex/` + `.agents/skills/` — Codex project config, lifecycle guards,
  focused subagents, and discoverable workflow/index entry points. Detailed
  shared workflow bodies remain canonical in `.claude/skills/`.

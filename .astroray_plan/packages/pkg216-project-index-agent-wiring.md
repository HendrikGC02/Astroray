# pkg216 — Put the project-index in front of the agents

**Track:** A
**Status:** open (filed 2026-08-21).
**Estimated effort:** S.
**Depends on:** pkg215.

---

## Goal

Before: `project_index` appears in zero agent definitions, zero skills, and
zero hooks in either harness; `KNOWLEDGE.md` mentions it but nothing loads
`KNOWLEDGE.md` into agent context, so agents never learn the tool exists and
fall back to `grep` every time. After: the three agents that do repo-navigation
work — `package-implementer`, `architect`, `docs-updater` — are explicitly
instructed, in both `.claude/agents/` and `.opencode/agents/`, to run the index
for the two questions it now answers best (`owns <file>` before editing,
`script "<task>"` before writing a script), and `AGENTS.md` references
`KNOWLEDGE.md` so the routing map is discoverable. This is the package that
actually closes the owner's "agents don't use it" gap.

---

## Context

Wiring is the crux of the whole exercise (design note
`.astroray_plan/docs/2026-08-21-project-index-usefulness.md` §Diagnosis-1): a
good tool nobody is told to run stays unused. This package is deliberately
sequenced AFTER pkg215 so agents are pointed at a tool whose output is scannable
and fresh, not the current noisy/stale one — pointing them at today's tool would
burn the one chance to earn trust.

Pure markdown/config edits: agent definitions, `AGENTS.md`, `KNOWLEDGE.md`. No
code, no build.

---

## Reference

- `.claude/agents/package-implementer.md` "Before writing a single line of code"
  checklist (`:21`) and `.opencode/agents/package-implementer.md` — the primary
  wiring targets.
- `.claude/agents/architect.md`, `.claude/agents/docs-updater.md` and their
  `.opencode/` twins.
- `KNOWLEDGE.md` (routing map, already documents the subcommands) and `AGENTS.md`
  (the auto-read contract that currently never points at KNOWLEDGE.md).
- CLAUDE.md §5b (no-duplicate-scripts — the `script` lookup enforces it).
- Design note: `.astroray_plan/docs/2026-08-21-project-index-usefulness.md`.

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `.claude/agents/package-implementer.md` | Add index-invocation lines to the pre-code checklist |
| `.opencode/agents/package-implementer.md` | Mirror the same lines |
| `.claude/agents/architect.md` | Add "query the index before proposing scope" line |
| `.opencode/agents/architect.md` | Mirror |
| `.claude/agents/docs-updater.md` | Add "use `owns`/`deps` to find affected specs" line |
| `.opencode/agents/docs-updater.md` | Mirror |
| `AGENTS.md` | One line referencing `KNOWLEDGE.md` as the routing map |
| `KNOWLEDGE.md` | Add the pkg215 subcommands (`owns`/`script`/`whatis`) to the Search & graph section |

### Key design decisions

- **`package-implementer`** gets the load-bearing lines, added to its
  "Before writing a single line of code" list:
  - *Before editing an existing file, run
    `python scripts/project_index.py owns <path>` to see which packages own it
    and their status — it surfaces prior/related work grep won't.*
  - *Before writing ANY new script, run
    `python scripts/project_index.py script "<task>"` (the CLAUDE.md §5b
    no-duplicate gate) in addition to reading `scripts/README.md`.*
- **`architect`** gets one line in goal-capture: *run
  `project_index query "<topic>"` / `deps pkgN` before proposing scope, to
  ground new specs in existing packages and dependencies.*
- **`docs-updater`** gets one line: *use `project_index owns <path>` / `deps` to
  find every spec affected by a landed change before flipping statuses.*
- The lines must be **identical** across the `.claude/` and `.opencode/` twin so
  the two harnesses don't drift.
- Do NOT add a hook. Discovery-by-instruction first; an auto-surface hook stays
  deferred per the design note until there's evidence the instruction is
  insufficient.

---

## Acceptance criteria

- [ ] **Wiring present (machine-verifiable):** `grep -l project_index
      .claude/agents/*.md .opencode/agents/*.md` returns
      `package-implementer`, `architect`, and `docs-updater` in BOTH directories
      (6 files).
- [ ] **`owns` and `script` both cited** in `package-implementer.md` (both
      harness copies) — assert both subcommand names appear.
- [ ] **Twin parity:** the invocation lines added to a `.claude/agents/X.md` are
      byte-identical to those in `.opencode/agents/X.md` (a test or manual diff
      of the added block).
- [ ] **`AGENTS.md` references `KNOWLEDGE.md`** (grep asserts the link exists).
- [ ] **`KNOWLEDGE.md` lists** `owns`, `script`, and `whatis`.
- [ ] No engine/test/build change; no CI job needs a build. CI green on all
      matrix jobs.

---

## Non-goals

- **No hook** (auto-surface on Edit/UserPromptSubmit). Deferred.
- **No MCP server.** The CLI is the mechanism.
- **No change to `session_start.ps1`** to run the index — it must stay a fast
  session banner; auto-running the index on every session start is scope creep
  and the read-time freshness guard (pkg215) already keeps answers current.
- **No changes to the reviewer/verifier agents** (`pr-reviewer`,
  `hardware-verifier`, `cpp-abi-guard`, `cycles-parity-reviewer`,
  `gate-failure-reviewer`) — they don't do exploratory navigation; keep their
  context lean.

---

## Progress

_(none yet)_

## Lessons

_(none yet)_

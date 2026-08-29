# pkg215 — Make the project-index answer real questions, and never be stale

**Pillar:** 5
**Track:** A
**Status:** done (PR #633, 2026-08-22). Query/coverage/freshness overhaul: scannable one-line query, body/file search, new `owns`/`script`/`whatis` subcommands, read-time auto-rebuild. 10/10 tests. Wired into agents by pkg216 (#636).
**Estimated effort:** M.
**Depends on:** none.

---

## Goal

Before: `scripts/project_index.py` builds a SQLite index but its query surface
is unusable in practice — `query` prints entire multi-paragraph Status
post-mortems per hit, searches only title/status/pillar, exposes no file→package
lookup despite having a `package_files` table, doesn't index the canonical-script
map, and the DB is gitignored and never auto-rebuilt so it goes stale silently.
After: the CLI answers the four questions a coding agent actually asks —
"which package owns this file?", "what's the canonical script for task X?",
"what packages relate to this topic?" (body + file search, one scannable line
per hit), "what is pkgN?" — and every read-command auto-rebuilds when the DB is
stale so answers are never silently out of date. Diagnosis:
`.astroray_plan/docs/2026-08-21-project-index-usefulness.md`.

---

## Context

The project index is the owner's designated route to genuine coding-agent
usefulness, but agents fall back to `grep` because the tool's highest-value
outputs are noise or missing (see the design note). This package fixes the
*tool* so it is worth reaching for; pkg216 then wires it into agent workflow.
Both are needed — a good tool nobody runs, or a noisy tool agents are told to
run, each fails. This one must land first.

All work is in one Python file plus its tests. No engine code, no GPU, no ABI,
no physics.

---

## Reference

- `scripts/project_index.py` — the tool. `_parse_package()` (`:46`) fills the
  `status` field from `**Status:** <rest-of-line>`; `query()` (`:187`) searches
  only `title/status/pillar`; `package_files` table (`:139`) is built but never
  queried; `deps()` (`:201`) is the one clean subcommand (keep its style).
- `scripts/README.md` — the canonical-task table (§ "Canonical script per
  task") to index for the `script` lookup; serves CLAUDE.md §5b.
- Design note: `.astroray_plan/docs/2026-08-21-project-index-usefulness.md`.

---

## Specification

Edit `scripts/project_index.py` and add `tests/test_project_index.py`. No other
files change.

### 1. Scannable status + real search (`query`)

- Add a `_status_token(raw: str) -> str` helper that reduces a Status line to a
  short token by taking text up to the first of `(`, `—`, `.`, `,`, or newline,
  lower-cased and stripped (e.g. `done (PR #540, ...)` → `done`;
  `open (filed 2026-08-21).` → `open`; `Stage 2 done ...` → `stage 2 done`).
  Store BOTH a new `status_short` column and keep the existing full `status`
  (used by `whatis`).
- `query` prints one line per package hit using `status_short`:
  `  pkg169  [done] Disney Principled TRANSMISSION lobe CREATES energy ...`
  (title truncated to ≤80 chars). No multi-paragraph dumps.
- Extend `query` matching: index each spec's **body text** (a new
  `package_text(package_key, body)` table or a `body` column on `packages`) and
  match the query words against title, body, and the package's file paths, not
  just title/status/pillar. A search for a term that appears only in a spec body
  or only in a `Files to modify` path must return that package.

### 2. File-owner lookup (`owns <path>`)

- New subcommand `owns <path>`. Normalises slashes, matches `package_files.path`
  by suffix/substring (so both `gpu_materials.h` and
  `include/gpu_materials.h` resolve), and prints each owning package with its
  `status_short` and the action (`create`/`modify`), e.g.:
  `  pkg169  [done]  modify  include/gpu_materials.h`
- If nothing owns the path, print `no package records touching <path>` (exit 0).

### 3. Canonical-script lookup (`script <task>`)

- New parser that reads the `scripts/README.md` "Canonical script per task"
  markdown table into a new `scripts_map(task, script)` table during `build`.
- New subcommand `script <task-substring>` (case-insensitive) that prints
  matching `task → canonical script` rows. Directly answers the CLAUDE.md §5b
  "check the index before writing a new script" gate.

### 4. Compact card (`whatis pkgN`)

- New subcommand `whatis pkgN` printing a compact multi-line card: title,
  `status_short`, track, pillar, effort, depends-on, reverse-deps count, and
  the list of owned files. Reuses `deps()` data; the FULL status narrative may
  be shown here (this is the deliberate "give me everything about one package"
  path, unlike `query`).

### 5. Read-time freshness guard

- Add `_db_is_stale() -> bool`: true if `DB_PATH` is missing OR its mtime is
  older than the newest mtime among all files under `.astroray_plan/packages`,
  `.astroray_plan/docs` (excluding `archive/`), `tests/test_*.py`, and
  `scripts/README.md`.
- `query`, `deps`, `owns`, `script`, and `whatis` call `build()` automatically
  when `_db_is_stale()` and print a single `(index rebuilt)` line to stderr when
  they do. `build`/`gh-sync`/`graph` keep current behaviour (explicit).
- Keep it fast: no per-command full re-scan cost beyond the (already ~instant)
  build; the staleness check is mtime-only.

### Key design decisions

- One file, one PR: the whole point is to avoid two agents serializing on
  `project_index.py`. Freshness ships with the query overhaul, not separately.
- Do NOT change the DB path or un-gitignore it. Read-time rebuild makes the
  gitignore moot — the DB is a local cache that's always fresh on read.
- Match `deps()`'s terse output style everywhere; no ANSI, ASCII-only
  (Windows/PowerShell — CLAUDE.md shell conventions; the file already
  `reconfigure`s stdout to utf-8).

---

## Acceptance criteria

- [ ] **Scannable query (machine-verifiable):** `python scripts/project_index.py
      query "glass"` prints at most one line per package hit, and no single line
      exceeds ~120 chars; a test asserts the output for a known multi-paragraph-
      status package (e.g. pkg169) is a single short line containing `[done]`,
      not its full post-mortem.
- [ ] **Body/file search:** a test picks a term that appears in a spec's *body*
      or a *Files-to-modify path* but NOT its title/status/pillar, and asserts
      `query <term>` returns that package (fails against current `main`).
- [ ] **`owns` (machine-verifiable):** `owns` on a path known to appear in some
      spec's Files table (assert against a package the test discovers by reading
      the DB, so it can't rot) prints that package with its status and action;
      `owns nonexistent/path.xyz` prints the empty-result line and exits 0.
- [ ] **`script` (machine-verifiable):** `script "contact sheet"` (or another
      substring present in `scripts/README.md`) returns the canonical
      `benchmarks/showcase/runner.py` row; a test asserts the row count matches
      the README table's row count for a known task.
- [ ] **`whatis` (machine-verifiable):** `whatis pkg214` prints title, a
      `status`, track, depends, and the owned-files list without exception.
- [ ] **Freshness (machine-verifiable):** a test builds the DB, `touch`es a
      package spec (or writes a temp spec) to make it newer than the DB, runs
      `query`/`owns`, and asserts the new content is reflected AND `(index
      rebuilt)` appeared on stderr — i.e. no manual `build` was needed.
- [ ] **No regression:** `deps`, `build`, `graph --json`, and `gh-sync` still
      run and produce output of the same shape; existing graph HTML still opens.
- [ ] `scripts/README.md` row for `project_index.py` is updated to list the new
      subcommands (`owns` / `script` / `whatis`) in the same commit.
- [ ] CI green on all matrix jobs (`gh run view` on HEAD — memory
      `mingw_local_vs_gcc_ci_divergence`). Pure-Python; no build required.

---

## Non-goals

- **No MCP server.** The CLI is the mechanism; see the design note's rejected
  alternatives. Do not add a server.
- **No auto-surface hook** (injecting owners on every Edit). Deferred pending
  pkg216 adoption evidence.
- **No schema for symbol-level (function/class) indexing.** Files-granularity
  only; symbol indexing is a separate future package if the coarse lookup
  proves insufficient.
- **No change to `graph`/HTML viz** beyond keeping it working.
- **No un-gitignoring the DB**, no committing the DB, no network in the read
  path (`gh-sync` stays the only network command).

---

## Progress

_(none yet)_

## Lessons

_(none yet)_

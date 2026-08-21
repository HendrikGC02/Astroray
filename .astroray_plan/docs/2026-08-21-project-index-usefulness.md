# Making the project-index actually useful to coding agents (2026-08-21)

**Author:** architect (goal-capture, owner directive 2026-08-21)
**Status:** design note → specs pkg215, pkg216

## The directive

`scripts/project_index.py` exists: it builds a SQLite index over packages,
docs, and tests, plus a 3D force-graph viz. But coding agents don't
meaningfully rely on it. Figure out *why*, then design the path to genuine
usefulness.

## Diagnosis — three independent failures, all load-bearing

I read the tool end-to-end, exercised it against the live repo, and grepped
every agent/skill/hook in both harnesses (`.claude/` and `.opencode/`). The
tool is not one broken thing; it fails on three axes at once, and fixing any
one alone leaves it unused.

### 1. It is wired into *nothing*. (This is the crux.)

`project_index` appears in exactly four files: `scripts/project_index.py`
(itself), `scripts/README.md` (the canonical-script table), `scripts/model_bench.py`
(unrelated), and `KNOWLEDGE.md`. It appears in **zero** agent definitions,
**zero** skills, **zero** hooks — in *either* harness (`.claude/agents/*.md`,
`.opencode/agents/*.md`).

`KNOWLEDGE.md` is a nice routing map that points at the tool, but nothing loads
`KNOWLEDGE.md` into an agent's context: it is not read by `session_start.ps1`,
not referenced from `AGENTS.md` (the auto-read contract), and not cited by any
agent definition. The `package-implementer` "before writing a single line of
code" checklist says: read CLAUDE.md, read the spec, grep. It never mentions
the index. So a coding agent never learns the tool exists, and reaches for
`grep` every time — which is exactly what it does today.

**No amount of query-quality improvement fixes this by itself.** A perfect tool
nobody is told to run stays unused.

### 2. When you *do* run it, the highest-value output is noise or missing.

- `query "glass"` is unusable. The `status` column is populated by matching
  `**Status:** <rest of line>`, but our specs jam entire multi-paragraph
  post-mortems onto/after the Status line, so a single query hit prints
  hundreds of words of resolution narrative. Fifteen hits = an unscannable
  wall. An agent cannot skim it.
- `query` searches only `title`/`status`/`pillar`. It does **not** search spec
  body text, and it does **not** search files — so "which package discusses
  photon caustics" misses any spec that doesn't say it in the title.
- **The single most valuable coding-agent query is not exposed at all:**
  "I'm about to edit `gpu_materials.h` — which packages own it and what
  landed?" The schema *has* a `package_files` table, but there is no
  `owns <path>` command. The reverse lookup exists in the data and is thrown
  away.
- The canonical-script map (`scripts/README.md`, the CLAUDE.md §5b
  no-duplicate-scripts rule) is **not indexed**, even though "what's the
  canonical script for task X?" is a first-class recurring agent question and
  the index is exactly the right shape to answer it. Five parallel contact-sheet
  generators already got written for want of this lookup.

`deps` is the one subcommand that works well and returns clean output.

### 3. It goes stale silently, so agents can't trust it.

The DB (`.astroray_plan/.project-index.db`) is **gitignored** — it never
travels, so every checkout and every fresh agent starts with *no* DB until
someone runs `build`. Nothing rebuilds it: no commit hook, no read-time guard.
An agent that runs `query`/`deps` against a month-old DB gets month-old answers
with no warning. Staleness is the fastest way to make an agent stop trusting a
tool and fall back to grep permanently — and grep is never stale.

## The chosen direction

There is essentially **one honest direction**, and I want to name what I
*rejected* so the scope stays tight (CLAUDE.md §2):

- **I am not building an MCP server.** It is tempting (a native `owns`/`deps`
  tool call), but it double-wires two harnesses (opencode + Claude Code),
  adds a server lifecycle, and does not touch the actual root cause — which is
  that the CLI mechanism is *fine*; agents just aren't told to run it and its
  output is noise. An MCP server is over-engineering that fixes nothing on axis
  1 or 3. The Bash-invokable CLI already works in both harnesses.
- **I am not (yet) building an auto-surface hook** (e.g. inject "packages that
  own this file" on every `Edit`). It is attractive as zero-effort discovery,
  but it is cross-harness-fragile (hook models differ between opencode and
  Claude Code), risks context bloat on every edit, and is speculative until we
  see whether wiring the CLI into agent checklists is enough. Deferred; revisit
  only if pkg216's checklist wiring demonstrably fails to drive adoption.

So the path is: **make the CLI answer the questions agents actually ask, keep
it fresh automatically, then put one instruction line where agents will read
it.** Two packages, sequenced:

### pkg215 (M) — Make the index answer real questions, and never be stale

Edits `scripts/project_index.py` only. Three things, one PR (one file, avoid
two agents serializing on it):

1. **Scannable output + real search.** Parse a *short* status token (first
   word/clause: `open`/`in-progress`/`done`/`held`), not the whole narrative
   line, so `query` prints one skimmable line per hit. Extend `query` to also
   match spec **body** text and **file paths**.
2. **The lookups agents ask for.** Add `owns <path>` (file → packages that
   create/modify it, from `package_files`, with each package's status) and
   `script <task-substring>` backed by a new index of the `scripts/README.md`
   canonical-task table (directly serves the §5b no-duplicate rule). Add a
   compact `whatis pkgN` card.
3. **Read-time freshness guard.** `query`/`deps`/`owns`/`script`/`whatis`
   auto-rebuild if the DB is missing or older than the newest source file
   under `.astroray_plan/packages`, `.astroray_plan/docs`, `tests/`, and
   `scripts/README.md`. Build is ~instant at 221 packages, so rebuild-on-read
   is simpler and more robust than a commit hook and needs no cross-harness
   wiring. Print a one-line `(index rebuilt)` note when it fires.

### pkg216 (S) — Put the index in front of the agents

Edits agent definitions and the routing surface, no engine code. Add a single
explicit invocation line to the `package-implementer`, `architect`, and
`docs-updater` definitions in **both** `.claude/agents/` and
`.opencode/agents/`, plus tighten `KNOWLEDGE.md`:

- implementer "before writing code" checklist gains: *before editing a file,
  run `python scripts/project_index.py owns <path>`; before writing any script,
  run `... script "<task>"` (the §5b gate).*
- Reference `KNOWLEDGE.md` from `AGENTS.md` so the routing map is discoverable.

Depends on pkg215 (don't point agents at a noisy tool). Adoption is the whole
point of the exercise, so this package is the one that actually closes the
owner's gap; pkg215 is the prerequisite that makes the instruction worth
following.

## Why this is the minimum that works

Axis 1 (not wired) is the crux, but pointing agents at today's noisy, possibly-
stale tool would burn the one chance to earn trust. So pkg215 makes it
trustworthy and pkg216 makes it reached-for. Neither alone suffices; together
they are ~1.5 sessions of pure-Python/markdown work with fully machine-
verifiable acceptance criteria and no GPU, no ABI, no physics risk.

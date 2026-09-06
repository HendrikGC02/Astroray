# pkgNN — Package Title

**Pillar:** 1
**Track:** A
**Status:** open
**Estimated effort:** e.g. 1 session (~3 h), 3 sessions (~9 h), 1 week, or TBD
**Depends on:** none

---

## Goal

One paragraph. What state does the codebase reach when this package is
done? Write it as a before/after: "Before: X. After: Y."

---

## Context

Why does this need to happen now, and not later? Which pillar does it
serve? What breaks without it?

Keep this under 150 words. If you find yourself writing more, the
package is probably too big.

---

## Evidence

*(Optional. Dated, factual bullets only — measurements, log excerpts,
gate output. No narrative. Omit this section entirely if there is
nothing to cite yet.)*

- 2026-MM-DD: `<fact>`

---

## Reference

Pointers to the relevant design section and any external references
needed:

- Design doc: `docs/plugin-architecture.md §Design`
- External: (see `docs/external-references.md §N`)

---

## Prerequisites

- [ ] pkgXX is done and tests are green.
- [ ] Build passes on main.
- [ ] (Add any specific environment check here.)

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `path/to/new_file.cpp` | One-line description |
| `tests/test_new.py` | Tests for the new file |

### Files to modify

| File | What changes |
|---|---|
| `path/to/existing.cpp` | What and why |

An empty table (nothing to create, or nothing to modify) is written as
the single line `None.` instead of an empty header/separator.

### Key design decisions

Describe any decisions that are not obvious from the goal. If the
answer is "follow the pattern in pkgXX," say that explicitly.

If the package has phases, or an owner-decided fork between competing
approaches, break them out as `####` subsections here (e.g.
`#### Phase 1`, `#### Fork (a): ...`) — never as a new `##` section.

---

## Acceptance criteria

- [ ] Criterion 1: machine-verifiable (e.g., "all 66+ tests pass").
- [ ] Criterion 2: output-verifiable (e.g., "Cornell box renders
      without visual regression").
- [ ] Criterion 3: structure-verifiable (e.g., "new material added by
      creating one file, no other files changed").

---

## Non-goals

List explicitly what this package does NOT do. These are hard stops.

- Do not ...
- Do not ...

---

## Progress

Update this section as work proceeds. Do not delete old entries.

- [ ] Step 1 description
- [ ] Step 2 description
- [ ] Step 3 description

---

## Lessons

*(Fill in after the package is done.)*

What was harder than expected? What would you do differently? What
should the next agent know before starting a similar package?

<!--
TEMPLATE v2 GRAMMAR (2026-09). Delete this comment in real specs.

Header (five bold fields, one physical line each, contiguous, in this
exact order, directly after the title line):
  **Pillar:**            bare integer 1-5, or empty for infrastructure
  **Track:**             a single letter A-D
  **Status:**            open | in-progress | blocked | paused | done |
                          superseded, optionally followed by
                          " — <free text>" (em dash), e.g.
                          "done — PR #716, 2026-09-06"
  **Estimated effort:**  one line; "TBD" if unknown
  **Depends on:**        none | TBD | pkg12, pkg219, pkg223b
                          (comma-separated pkg tokens only; every token
                          must resolve to an existing
                          packages/pkg<token>-*.md file)
No other **Field:** lines belong in the header — prose that used to
live there (Priority, Implementer tier, Dispatch authority, ...) goes
into ## Context as sentences instead.

Sections (## only, in this order): Goal, Context, Evidence (optional),
Reference, Prerequisites, Specification, Acceptance criteria,
Non-goals, Progress, Lessons.

Specification's ### subsections, in order: Files to create, Files to
modify, Key design decisions. Each files table uses a
`| File | Purpose |` or `| File | What changes |` header, a
`|---|---|` separator, then rows with a backticked path (no whitespace)
in the first cell; an empty table is the single line `None.` instead.

Validated by: python scripts/project_index.py lint <spec.md>
-->

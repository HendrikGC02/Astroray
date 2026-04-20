# pkgNN — Package Title

**Pillar:** N  
**Track:** A / B / C / D  
**Status:** open / in-progress / done  
**Estimated effort:** e.g. 1 session (~3 h), 3 sessions (~9 h), 1 week  
**Depends on:** pkgXX, pkgYY (or "none")

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

### Key design decisions

Describe any decisions that are not obvious from the goal. If the
answer is "follow the pattern in pkgXX," say that explicitly.

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

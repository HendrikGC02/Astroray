# pkg248 — Delegate content-change evidence

**Pillar:** 5
**Track:** A
**Status:** open — detailed architect review required before implementation
**Estimated effort:** TBD
**Depends on:** pkg232

---

## Goal

Before: the canonical delegate helper's before/after evidence is only a
porcelain-status set difference (`set(post["dirty_files"]) - set(pre["dirty_files"])`),
so a tracked file whose bytes change under an identical porcelain status is
reported as no change. After: content-aware before/after evidence with schema
compatibility distinguishes pre-existing dirty state from observed
byte/content changes across the full change matrix, with pinned snapshot
cost/limits policy, explicit unavailability reporting, read-only
Git/content operations extending the canonical helper and its tests, and
verified evidence-matrix and bounded-cost/failure behavior.

---

## Context

This package serves Pillar 5 (delivery tooling). It builds on the pkg232
cleanup contract (`pkg232-delegate-timeout-process-tree.md`). Its estimated
effort is TBD pending the detailed architecture review. It is not dispatch
eligible: detailed architecture and independent review are required before
implementation, there is no priority promotion, and Pillar 4 remains PAUSED.
An independent Terra SIGN-OFF was filed, 2026-09-06, under the owner's
authorization to use Terra/DeepSeek while Claude is unavailable;
implementation and hardware gates remain UNRUN.

---

## Evidence

- Pkg232 landed in PR #705, merge `d997c499`; reviewed source
  `32458d64be8ed444df63f3fdbf49339b467702bc` remained unchanged through
  delivery.
- The current canonical `.claude/skills/delegate/scripts/delegate.py` captures
  HEAD and sorted porcelain inventory in `_git_snapshot:200`; the final
  difference near `:525` is
  `set(post["dirty_files"]) - set(pre["dirty_files"])`.
- Astra imported this read-only helper in a disposable temporary Git
  repository, without opencode or live-index mutation.
- Before/after inventories both contained `M tracked.txt`; its content SHA256
  changed but reported `files_changed` was empty.
- Reverting that dirty file to clean also produced an empty difference.
- This proves the narrow helper gap, not attribution of all worker changes.

---

## Reference

- Depends on pkg232 (cleanup contract): `pkg232-delegate-timeout-process-tree.md`.
- Canonical helper under change: `.claude/skills/delegate/scripts/delegate.py`.

---

## Prerequisites

- [ ] pkg232 is landed (PR #705) and its cleanup contract stands.

---

## Specification

### Files to create

None.

### Files to modify

| File | What changes |
|---|---|
| `.claude/skills/delegate/scripts/delegate.py` | Phase 1: extend the helper and its tests with content-aware before/after evidence using read-only Git/content operations; never mutate the live index, stage files, or reset/revert user work. |

### Key design decisions

#### Phase 0 — content-aware evidence and schema compatibility

Define content-aware before/after evidence and schema compatibility.
Distinguish pre-existing dirty state from observed byte/content changes,
including same-status tracked/staged edits, reverts, existing/new untracked
files, deletes, and renames. Record the limits of observation under
concurrent edits. Pin snapshot cost, size/path limits, unreadable-file,
encoding, and symlink policy before implementation; unavailable evidence must
be explicit.

#### Phase 1 — extend the canonical helper and tests

Extend the canonical helper and tests using read-only Git/content
operations. Never mutate the live index, stage files, or reset/revert user
work.

#### Phase 2 — verification

Verify the evidence matrix and bounded-cost/failure behavior.

---

## Acceptance criteria

- [ ] Temporary-repository tests cover the complete change matrix, including
      identical porcelain status with different bytes and dirty-to-clean reverts.
- [ ] Tests cover failed/partial/oversized snapshots and the declared cost bound;
      unobservable changes are reported unavailable, never silently clean.
- [ ] Preserve existing JSON consumers or document reviewed schema compatibility;
      results distinguish baseline state from observed content change.
- [ ] Snapshot operations leave the live index and user files unchanged;
      no opencode process is needed for these unit tests.
- [ ] Retain pkg232's confirmed-cleanup gate before final snapshot evidence
      and require independent review before implementation delivery.

---

## Non-goals

- Risk: Large trees, binary/untracked files, and partial reads can make
  snapshots costly or incomplete.
- Risk: Content differences do not prove which concurrent actor caused them.
- Neither worker narrative nor exit code substitutes for evidence.
- No pkg247 launch-protocol, pkg232 process-containment, model-routing, or
  review policy changes; this is a separate implementation package.

---

## Progress

- (none yet)

---

## Lessons

- (none yet)

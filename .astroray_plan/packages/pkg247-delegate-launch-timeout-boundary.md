# pkg247 — Delegate launch and payload timeout boundary

**Pillar:** 5
**Track:** A
**Status:** open — detailed architect review required before implementation
**Estimated effort:** TBD
**Depends on:** pkg232

---

## Goal

Before: the canonical delegate wrapper assigns the containment helper to the
Job, synchronously writes/closes its JSON stdin payload, and only then starts
the worker-runtime deadline, so a stalled helper startup or a large payload can
delay the next handled cancellation/timeout checkpoint. After: the launch
boundary and the worker-runtime budget are pinned separately (startup/payload
versus worker runtime, including cancellation behavior and unavailable-evidence
outcomes), with a selected payload-delivery protocol validated by mocks and a
bounded real Windows canary, while preserving pkg232's process-containment
boundary and cleanup/evidence contract.

---

## Context

This is a delivery-tooling (Pillar 5) improvement to the launch boundary of the
canonical delegate wrapper. Pkg232 explicitly documents its budget as worker
runtime AFTER payload delivery; this package is a separate launch-boundary
improvement, not evidence that pkg232 violated its approved runtime budget or
its confirmed-cleanup guarantee. Not dispatch eligible. Detailed architecture
and independent review are required before implementation. No priority
promotion; Pillar 4 remains PAUSED. Independent Terra SIGN-OFF to file,
2026-09-06, under the owner's authorization to use Terra/DeepSeek while Claude
is unavailable. Implementation gates remain UNRUN.

---

## Evidence

- 2026-09-06: Independent Terra SIGN-OFF to file, under the owner's
  authorization to use Terra/DeepSeek while Claude is unavailable.
  Implementation gates remain UNRUN.
- Pkg232 landed in PR #705, merge `d997c499`. Reviewed implementation
  `32458d64be8ed444df63f3fdbf49339b467702bc` remained unchanged through
  delivery.
- Current canonical `.claude/skills/delegate/scripts/delegate.py`,
  `_run_windows_contained:323`, assigns the helper to the Job at `:344`,
  synchronously writes/closes its JSON stdin payload at `:347–348`, and starts
  the worker-runtime deadline at `:349`.
- A stalled helper startup or large payload can delay the next handled
  cancellation/timeout checkpoint. Pkg232 explicitly documents its budget as
  worker runtime AFTER payload delivery. This is a separate launch-boundary
  improvement, not evidence that pkg232 violated its approved runtime budget
  or its confirmed-cleanup guarantee.

---

## Reference

- Depends on pkg232 (`pkg232-delegate-timeout-process-tree.md`).

---

## Prerequisites

- [ ] TBD

---

## Specification

### Files to create

None.

### Files to modify

| File | What changes |
|---|---|
| `.claude/skills/delegate/scripts/delegate.py` | Extend only the canonical wrapper: keep Job assignment BEFORE worker launch, prohibit an uncontained fallback, and implement the selected launch/payload protocol. |

### Key design decisions

#### Phase 0

Phase 0 pins startup/payload and worker-runtime budgets separately, including
cancellation behavior and unavailable-evidence outcomes. Evaluate a bounded
writer versus a payload file plus small gated control record; detailed
architecture selects the protocol before implementation.

#### Phase 1

Phase 1 extends only the canonical wrapper and its tests; keep Job assignment
BEFORE worker launch and prohibit an uncontained fallback.

#### Phase 2

Phase 2 validates the launch boundary and existing cleanup/evidence contract.

---

## Acceptance criteria

- [ ] Blocked startup, large payload, partial handoff, and cancellation mocks
      prove the separately declared budgets and safe failure outcomes.
- [ ] A bounded real Windows canary exercises the approved protocol.
- [ ] Assignment failure cannot release worker launch; cleanup confirms zero
      active owned Job processes before final snapshot and main JSON evidence.
- [ ] No owned process writes after return; unrelated sentinel processes remain
      alive and their files unchanged on timeout, cancellation, and completion.
- [ ] Unconfirmed cleanup yields truthful unavailable evidence; preserve
      canonical JSON compatibility and require independent review.

---

## Non-goals

- Risk: Blocking pipes, stalled startup, and cancellation deadlocks need
  explicit ownership and cleanup ordering.
- Risk: Never kill unrelated processes.
- Do not make model-policy, renderer, or global timeout changes.
- Do not break pkg232's process-containment boundary.
- Do not bundle pkg248 content-snapshot work.

---

## Progress

- (none yet)

---

## Lessons

- (none yet)

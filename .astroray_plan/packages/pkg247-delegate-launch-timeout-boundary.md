# pkg247 — Delegate launch and payload timeout boundary

**Pillar:** 5 (delivery tooling)
**Track:** A
**Status:** OPEN — detailed architect review required before implementation
**Estimated effort:** TBD at detailed architecture review
**Depends on:** [pkg232](pkg232-delegate-timeout-process-tree.md).
Not dispatch eligible. Detailed architecture and independent review are required
before implementation. No priority promotion; Pillar 4 remains PAUSED.

Independent Terra SIGN-OFF to file, 2026-09-06, under the owner's authorization
to use Terra/DeepSeek while Claude is unavailable. Implementation gates remain UNRUN.

## Evidence and existing contract

Pkg232 landed in PR #705, merge `d997c499`. Reviewed implementation
`32458d64be8ed444df63f3fdbf49339b467702bc` remained unchanged through delivery.
Current canonical `.claude/skills/delegate/scripts/delegate.py`,
`_run_windows_contained:323`, assigns the helper to the Job at `:344`,
synchronously writes/closes its JSON stdin payload at `:347–348`, and starts
the worker-runtime deadline at `:349`.

A stalled helper startup or large payload can delay the next handled
cancellation/timeout checkpoint. Pkg232 explicitly documents its budget as
worker runtime AFTER payload delivery. This is a separate launch-boundary
improvement, not evidence that pkg232 violated its approved runtime budget
or its confirmed-cleanup guarantee.

## Bounded scope

Phase 0 pins startup/payload and worker-runtime budgets separately, including
cancellation behavior and unavailable-evidence outcomes. Evaluate a bounded
writer versus a payload file plus small gated control record; detailed
architecture selects the protocol before implementation.
Phase 1 extends only the canonical wrapper and its tests; keep Job assignment
BEFORE worker launch and prohibit an uncontained fallback.
Phase 2 validates the launch boundary and existing cleanup/evidence contract.

## Acceptance — implementation/hardware gates UNRUN

- [ ] Blocked startup, large payload, partial handoff, and cancellation mocks
      prove the separately declared budgets and safe failure outcomes.
- [ ] A bounded real Windows canary exercises the approved protocol.
- [ ] Assignment failure cannot release worker launch; cleanup confirms zero
      active owned Job processes before final snapshot and main JSON evidence.
- [ ] No owned process writes after return; unrelated sentinel processes remain
      alive and their files unchanged on timeout, cancellation, and completion.
- [ ] Unconfirmed cleanup yields truthful unavailable evidence; preserve
      canonical JSON compatibility and require independent review.

## Risks and exclusions

Blocking pipes, stalled startup, and cancellation deadlocks need explicit
ownership and cleanup ordering. Never kill unrelated processes.
No model-policy, renderer, or global timeout changes. Preserve pkg232's
process-containment boundary and do not bundle pkg248 content-snapshot work.

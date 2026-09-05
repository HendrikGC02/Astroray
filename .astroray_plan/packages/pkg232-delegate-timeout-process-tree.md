# pkg232 — Delegate timeout must stop its owned Windows process tree

**Pillar:** 5
**Track:** A
**Status:** open — detailed architect review required before dispatch
**Estimated effort:** TBD at detailed architect review
**Depends on:** none

---

## Goal

**Before:** a delegate wrapper timeout returns `status: timeout` while the worker's Windows `opencode.exe` descendant tree stays alive and keeps writing files after the wrapper has returned its evidence.
**After:** on timeout/cancellation/error the wrapper owns, stops, and awaits its full descendant process tree before the final snapshot; no post-return edits; returned status stays `timeout` even if the orphaned child would later have completed.

---

## Context & evidence

Observed 2026-09-06 Australia/Sydney, 2026-09-05 UTC (wrapper JSON + retained transcript `20260906-002341-grunt.jsonl` in `%LOCALAPPDATA%/astroray/delegate-logs`): wrapper returned `status timeout` at 180.0 s, 18 tool calls, `files_changed []`, `finish_reason tool-calls` — yet the Windows `opencode.exe` child (PID 42916) stayed live and wrote scoped tests AFTER the wrapper returned. The retained transcript eventually holds 31 tool calls, `reason stop`; first event 2026-09-05T14:24:20.006Z, last 2026-09-05T14:27:59.717Z (219.711 s event span — not total wrapper runtime). Parent verified the exact command line matched task token `.delegate-task-20260906-002341.md`, stopped only that child, and independently checked the final files. `files_changed []` must not be read as "no edits".

Mechanism (`.claude/skills/delegate/scripts/delegate.py`): `_opencode_cmd` (L35) wraps the Windows shim via `cmd /c`; `subprocess.run` (L126) with `timeout=` kills/waits only the immediate shim; `except TimeoutExpired` (L130) only marks `status = "timeout"`; `finally` (L132) removes the task file; the post snapshot (L137) is taken without owning/stopping the full descendant tree. This leaves output/logs and files mutable after returned evidence.

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `.claude/skills/delegate/scripts/delegate.py` | Own process-tree tracking/containment; bounded shutdown and await on timeout/cancellation/error; no post-return edits; final truthful snapshot after owned writers stopped; retained `timeout` status despite eventual child success. |
| `tests/` (scoped, when implemented) | Mock process-lifecycle tests + bounded real-Windows canary. |

### Key design decisions

- Ownership by instance/ancestry identity, never executable name alone; handle PID reuse; never terminate unrelated opencode processes.
- No watchdog daemon, no broad killall, no model-policy changes.
- Exact Windows containment implementation still needs architect review.

---

## Acceptance criteria (future — all UNRUN)

- [ ] Mock process-lifecycle tests: owned child/grandchild attempted delayed file writes are stopped; no delayed writes after return.
- [ ] Bounded real-Windows canary: owned child/grandchild + separate unrelated sentinel; owned descendants stopped, no delayed writes after return, sentinel alive, evidence/timed-out snapshot true.
- [ ] Retained `timeout` status even when the orphaned child would have completed; final snapshot only after owned writers stopped.
- [ ] Independent Astra/Claude review of containment and PID-reuse/race/output-handle handling.

---

## Non-goals

- No model-policy changes, no watchdog daemon, no broad killall.
- No delegate routing/tier/prompt changes; no queue priority changes; no Pillar 4 work.

---

## Progress

- [ ] Detailed architect review of scope and Windows containment design (all implementation gates UNRUN).
- [ ] Implementation + scoped tests (future).
Independent Claude filing review: SIGN-OFF TO FILE ONLY, 2026-09-06.
Evidence: `test_results/pkg232-235/claude-filing-review.txt`.

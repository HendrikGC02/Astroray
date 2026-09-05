# pkg232 — Delegate timeout must stop its owned Windows process tree

**Pillar:** 5
**Track:** A
**Status:** verified locally — independent final source sign-off and parent integration passed; CI/delivery pending
**Estimated effort:** one bounded maintenance slice
**Depends on:** none
**Dispatch authority:** owner instruction 2026-09-06 authorizes parallel lower-level backlog; parent selected pkg232 in isolated worktree codex/pkg232 at 305caf5.

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

### Files and ownership

| File | Bounded responsibility |
|---|---|
| .claude/skills/delegate/scripts/delegate.py | Windows containment, private gated-helper entry point, lifecycle cleanup and truthful JSON evidence. Extend this wrapper; no parallel launcher script. |
| tests/test_delegate_process_tree.py | Focused lifecycle/summary tests and real Windows child/grandchild/sentinel canaries; temporary worker programs are test fixtures. |
| .claude/skills/delegate/SKILL.md | Document additive cleanup evidence and the explicit platform boundary. Preserve dynamic tier policy and routing. |
| .astroray_plan/packages/pkg232-delegate-timeout-process-tree.md | Architecture, reviewed gates and factual delivery evidence. |

The existing script index and project index were consulted. No other existing
process-tree helper was found in the scoped wrapper, tests, scripts, tools or
benchmarks. Renderer, CUDA, Blender installation, tier configuration and live
planning records are outside this implementation lane.

### Architectural decision

Use an unnamed Windows Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
set neither breakaway flag. The parent retains the non-inheritable Job handle.
All ordinary CreateProcess descendants of the assigned helper inherit the
Job membership, so shim exit does not release its descendants. This is a
lifecycle boundary for ordinary worker subprocesses, not a security sandbox
against WMI, services or intentional out-of-process brokers.

Avoid the startup race by launching a private helper mode in this same Python
file. The helper may only read a command from its stdin pipe until the parent
has assigned its process instance to the configured Job. The parent sends one
UTF-8 JSON argv record only after assignment succeeds; helper EOF before that
record exits without launching a command. The helper then runs the existing
_opencode_cmd argv unchanged, sends its stdout/stderr to the existing transcript,
and returns the command exit code. The parent opens the unique transcript and
passes it as helper stdout with stderr redirected to that same handle; the
helper and command inherit that output only. Parent summary JSON remains on the
parent stdout. This preserves --dir, argument boundaries,
multiline task-file routing and the current shim selection.

Use documented Win32 APIs via a small local ctypes binding with explicit
argument/result types and pointer-width-correct structures. Keep the Job handle
and the process handle already owned by subprocess.Popen; never reopen a
process by a later PID lookup. CPython's Windows Popen._handle is a private
implementation detail: isolate access in the assignment helper, fail closed if
unavailable, and cover the supported interpreter with the real Windows gate.
Do not use NtResumeProcess, executable-name termination, PID-tree scans,
taskkill, or breakaway flags. Existing console windows must remain hidden;
the helper must use CREATE_NO_WINDOW, covered by a startup-flag assertion.

### Lifecycle and failure semantics

1. Allocate a unique invocation suffix for transcript/task paths so concurrent
   delegates cannot delete each other's task files or share an output stream.
   Snapshot the pre-state after the task file has been written, as today.
2. Create/configure the Job; launch the blocked helper; assign the exact process
   handle; release the command record. Any setup/assignment failure closes the
   pipe, terminates and awaits only this blocked helper, then closes the Job.
   No uncontained command is permitted to start.
3. Wait for helper completion using the configured worker timeout. Timeout
   permanently selects status: timeout; a later clean transcript cannot
   overwrite it. A wrapper/launch exception or handled cancellation selects
   errored with a concrete error entry. Add a structured termination reason
   (normal, timeout, cancelled or error) so cleanup failure cannot erase the
   initiating event. Retain command exit code when known. This is a worker-runtime
   budget starting after launch-gate payload delivery; OS process creation and
   synchronous control-pipe delivery are outside that budget. A stalled helper
   or very large single-line prompt can delay timeout/cancellation checkpoints.
   Do not claim a strict whole-launch deadline.
4. On every exit path, including ordinary completion, terminate any remaining
   Job processes and await helper termination. Query Job basic accounting until
   ActiveProcesses == 0, using a bounded cleanup deadline. Do not treat Job
   handle signaling or TerminateJobObject return alone as proof of exit.
5. Once no owned writer remains, close Job/control/log handles, remove the owned
   task file, then take the final git snapshot and parse the stable transcript.
   Preserve existing event-based completed, errored and no_clean_finish
   meanings; completed still means process completion, never task correctness.
6. Add a cleanup evidence object describing containment method, confirmed
   completion and any cleanup errors. If cleanup cannot be confirmed, retain
   timeout when already timed out (otherwise errored), report cleanup failure,
   and skip the final git snapshot and transcript-derived claims. Use explicit
   null/unavailable evidence rather than a misleading empty changed-file list.
   Close the last Job handle as a final termination fallback; never call this
   a successful cleanup merely because handle closure was attempted.
7. Handled Ctrl-C/termination goes through the same cleanup path; restore any
   temporary signal handlers. Forced process death cannot emit JSON, but closing
   its non-inherited last Job handle invokes kernel termination of members.

Non-Windows keeps its existing subprocess.run path and documented direct-child
termination behavior, with regression coverage. This package makes the full-tree
containment guarantee on Windows only. It does not introduce a Linux/macOS
process supervisor or imply that an escaped/brokered process is contained.

### Acceptance gates (local results recorded below; CI/integration pending)

- [x] Unit lifecycle tests cover configured Job before assignment, blocked helper
  before command release, assignment/launch failures, no command after EOF,
  handle closure on all paths and cancellation cleanup. The real Windows gate
  must confirm assignment through Popen._handle succeeds on the current 64-bit
  CPython (the handle therefore has the required assignment rights).
- [x] Summary tests cover timeout followed by a clean-stop event (still timeout),
  normal completion, error events, incomplete stream, launch error and cleanup
  failure. Final snapshot/log parsing must occur only after confirmed cleanup;
  failed cleanup must yield unavailable evidence, not a false clean snapshot.
- [x] Real Windows canary starts an owned child and grandchild that acknowledge
  startup, retain output handles, and attempt delayed writes. Timeout stops both;
  files and transcript remain byte-identical after the delayed-write horizon.
  An independently launched sentinel stays alive and writes successfully. Keep
  handles for each test-owned process and clean them in the test's finally.
- [x] Real Windows ordinary-completion canary exits the immediate worker while
  its descendant remains pending; cleanup stops the descendant before snapshot.
- [x] Real Windows cancellation and pre-release/assignment-failure canaries
  confirm bounded termination and no uncontained work. Repeated calls do not
  leak owned handles or task files; concurrent calls have distinct artifacts.
- [x] Existing JSON fields and dynamic-tier/--dir/multiline-prompt behavior
  remain covered. Run one bounded real opencode read-only smoke through the
  wrapper after tests, inspect its returned JSON and retained transcript.
- [x] Non-Windows regression tests run on that platform where available; on a
  Windows-only host, mocked branch coverage is explicitly distinguished from
  actual non-Windows runtime result. Both platform legs ran locally; GitHub CI remains pending.
- [x] Run focused pytest, differential lint and the changed-signature/caller
  sweep. No renderer build, GPU render or live Blender smoke is required for
  this Python-only process-lifecycle change.
- [x] Astra architecture review and independent Claude architecture/final
  containment/race/PID/output-evidence sign-off. Parent integration independently
  inspected the source and ran 39 passing Windows tests (one platform skip).

### Risks and boundaries

- Windows hosts may already place the wrapper in a restrictive Job. Nested Job
  assignment failure must report an error before releasing the worker; silently
  falling back to uncontained execution would reproduce the defect.
- Forcibly stopping a descendant can leave a partially written file. The final
  diff is evidence of that state, not a rollback or proof of a successful task.
- The cleanup deadline bounds the failure path; an OS/API failure is reported
  as unverified containment. The wrapper must never fabricate a final snapshot.
- The private CPython process-handle seam and ctypes structure layout require
  the real Windows gate, including pointer-sized fields on the current 64-bit
  interpreter. No optional process-management dependency is introduced.
- Ordinary completion now ends leftover background subprocesses. Delegated tasks
  are bounded; persistent servers/daemons are not supported by this wrapper.

### Primary references checked 2026-09-06

- [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
  — descendant membership, no-breakaway policy, kill-on-close and accounting.
- [AssignProcessToJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject)
  — process-instance handles and nested Job assignment requirements.
- [TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)
  — termination covers the assigned Job and nested child Jobs.
- [Python subprocess](https://docs.python.org/3/library/subprocess.html)
  — run(timeout=) kills and waits its immediate child; Popen permits the
  explicit lifecycle needed here.

---

## Non-goals

- No model-policy changes, no watchdog daemon, no broad killall.
- No delegate routing/tier/prompt changes; no queue priority changes; no Pillar 4 work.

---

## Progress

- [x] Detailed architecture reviewed by Astra and independent Claude (2026-09-06).
- [x] Implementation and scoped Windows gates complete (2026-09-06); CI and final review remain explicit gates.
Independent Claude filing review: SIGN-OFF TO FILE ONLY, 2026-09-06.
Evidence: `test_results/pkg232-235/claude-filing-review.txt`.

Architecture review: independent Claude SIGN-OFF 2026-09-06; binding corrections
above incorporated. Evidence: root `test_results/pkg232/architecture-claude.txt`.

## Local verification — 2026-09-06

- Isolated branch `codex/pkg232`, base `305caf569b43c62cb8a8a0d6af9f35fb5f4fc9a2`;
  only the four owned files changed. No renderer, GPU, build or live Blender work.
- Initial dynamic implement delegation returned `no_clean_finish`, exit 0,
  110 tool calls, 1075.3 seconds. This is draft evidence, not success. An
  independent monitor retained exact process-instance handles and confirmed
  all 1130 observed instances exited. Subsequent Astra inspection repaired
  duplicated handle closure, setup interruption, cancellation classification,
  insufficient canary acknowledgements and unavailable-evidence handling.
- Focused pytest: **39 passed, 1 skipped in 6.66 seconds** on Windows 11,
  64-bit CPython 3.13.12. The skip is the actual non-Windows runtime test;
  the same suite also ran on actual Ubuntu WSL/Linux with Python 3.10.12:
  **14 passed, 26 Windows-only skipped in 2.74 seconds**, including the actual
  direct-child runtime test. This is local platform verification, not GitHub CI.
- Real Windows tests prove assignment using the existing Popen process handle,
  non-inheritable Job handle, exactly KILL_ON_JOB_CLOSE/no breakaway flags,
  CREATE_NO_WINDOW helper startup, blocked launch before assignment,
  timeout/cancel/error/normal cleanup, zero active processes, and closed helper
  handles. Child and grandchild acknowledge startup; they attempt both file
  and inherited stdout writes only after return. Neither writes; the unrelated
  sentinel remains alive and writes successfully. Native handle count does not
  grow across repeated runs; concurrent contained runs remain isolated.
- Failure tests exercise assignment rejection/interruption/exception, Job/log/
  helper creation failure, worker launch failure, query/termination/deadline
  failure, and cancellation during assignment and cleanup. Unconfirmed cleanup
  withholds snapshot/transcript-derived fields and retains the task file.
- Real dynamic grunt-tier smoke: **completed**, 58.9 seconds, one read tool call,
  finish_reason stop, exit 0, no changed files, cleanup confirmed with
  **active_processes 0**. Parent independently inspected the JSON and transcript.
- Differential lint: **0 new findings**, Ruff/markdownlint/codespell/diff-check
  ran, no unavailable or errored tools. No existing callable signature changed;
  new lifecycle helpers are private and their callers are in this wrapper and
  the focused tests. Existing CLI consumers and agent/workflow docs were checked.

Evidence in the pkg232 worktree under `test_results/pkg232/`:
`implement-wrapper.json`, `implement-monitor.json`, `focused-tests.log`,
`focused.xml`, `lint.log`, `real-opencode-smoke.json`, `caller-signatures.json`,
`caller-sweep.txt`, `source-manifest.json`, `non-windows-tests.log`, and
`non-windows.xml`. `final-claude.txt` records independent final SIGN-OFF
conditional on parent integration/CI and actual Linux verification (now run). No commit, push, PR, CI success or merge is claimed here.

Parent integration raised a separate launch-latency edge after final source
review: the configured worker timeout starts after synchronous stdin payload
handoff, so process creation or a stalled/large payload write can delay timeout
and handled cancellation. Full Job cleanup/exit evidence after the handoff is
unaffected; no strict whole-launch deadline has been proved. A targeted Claude
follow-up could not run because the subscription reached its weekly limit
(`timeout-boundary-claude.txt`). The existing final source sign-off is retained;
no independent approval of this additional edge is claimed. Parent Astra
integration accepted the existing worker-runtime budget as consistent with the
reviewed architecture and required this explicit limitation in the spec and
SKILL. The process implementation remains byte-identical to final-reviewed
source. Bounded startup/payload delivery remains future hardening, outside this
package's containment fix; no full-launch deadline is claimed.

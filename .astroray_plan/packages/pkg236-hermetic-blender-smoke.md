# pkg236 — Hermetic Blender dev-loop smoke

**Pillar:** 5 (Blender/DCC dev-loop tooling)
**Track:** A
**Status:** OPEN — detailed architect review required before implementation
**Estimated effort:** TBD at architect review
**Depends on:** none — reuses canonical `scripts/dev_addon.ps1` and existing build/install helpers; no owner queue promotion

## Evidence

`tests/test_dev_loop_smoke.py::test_dev_loop_smoke_local_host` invokes
`scripts/dev_addon.ps1 -Smoke -SkipBuild`; with Blender 5.2 installed this path
can install into the REAL Blender 5.2 user profile. The pkg230 Phase 2 full-suite
attempt hit a locked native `.pyd` and partially deleted addon support
directories. Recovery restored Python/assets from the matching `1967cb5` tree
and the unchanged runtime DLL bundle, preserving the installed native module;
`PKG175_REGISTER_RESULT` passed. This is restored incident context, not an
implementation result for this new package. Evidence retained in feature
`test_results/pkg230-p2/full-suite.log`.

## Goal

Automate the dev-loop smoke entirely under a disposable, isolated Blender user
profile with explicitly bounded staging/install paths. The test invocation must
pass isolated-profile plumbing through the canonical `scripts/dev_addon.ps1` and
existing build/install helpers; never infer safety from `-SkipBuild` (it still
installs). Resolve and check final absolute targets before any destructive
copy/remove/move; reject profile-escape, symlink/reparse, and path tricks. Make
the install atomic or roll back completely on a locked `.pyd` or any failure.
Preserve the live user addon/files/preferences and restore the process
environment after the test.

## Scoped direction

Detailed architect review chooses the implementation and exact file scope. Reuse
canonical scripts and existing build/install helpers; create no parallel
installer. This follow-up does not change owner queue priority; Pillar 4 remains
PAUSED.

## Acceptance — all implementation gates UNRUN

- [ ] Disposable-profile real Blender register/smoke, with a sentinel proving the
      real user profile was never written.
- [ ] Path-boundary adversarial/mocked checks: profile escape, symlink/reparse,
      and path tricks rejected before any destructive operation.
- [ ] Concurrent unrelated/live-profile sentinel files and content hashes unchanged
      across the full invocation.
- [ ] Injected locked-module or copy failure rolls back and preserves the complete
      prior installation.
- [ ] No leftover child processes or environment changes after the test.
- [ ] Full-suite invocation demonstrably cannot write the real user profile.
- [ ] GPU lock if a future smoke uses the GPU; at most two isolated implementation
      worktrees; independent Astra/Claude review.

## Non-goals

No renderer feature changes; no uninstalling or replacing the live user install;
no weakening of the existing freshness/register guards; no owner queue priority
change; no Pillar 4 work.

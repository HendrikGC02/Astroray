# pkg236 — Hermetic Blender dev-loop smoke

**Pillar:** 5 (Blender/DCC dev-loop tooling)
**Track:** A
**Status:** IMPLEMENTED — Terra SIGN-OFF and real Blender gates passed; CI/delivery pending
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
copy/remove/move; reject profile-escape, symlink/reparse, and path tricks. Copy,
locked-target rename, and promotion failures preserve or restore the complete
prior install. Promotion commits the new complete tree; subsequent backup
cleanup failure reports failure and both recovery paths. Never restore a
partially deleted backup. This is not crash-atomic across process termination
between filesystem renames.
Preserve the live user addon/files/preferences and restore the process
environment after the test.

## Scoped direction

Astra's 2026-09-06 bounded architecture uses an owned fresh profile before any
Blender invocation. All five `BLENDER_USER_*` paths and `ASTRORAY_SMOKE_*` values
are restored in `finally`. `-SmokeProfileParent` selects only the parent of a
fresh disposable child; it is never itself installed into or removed. Smoke
must load the actual bounded installation, without a staged-path fallback.
The canonical installer gains an optional keyword-only `allowed_root` and uses
copy-before-mutation plus sibling backup/promotion renames. Launch retains its
explicit user-facing semantics. Pillar 4 remains PAUSED.

Scope: `scripts/dev_addon.ps1`, `scripts/build/build_blender_addon.py`,
`tests/test_dev_loop_smoke.py`, and `tests/test_pkg236_hermetic_install.py`.
The owner authorized bounded parallel lower-backlog work for this round.

## Acceptance — host/real-Blender/review complete; CI/delivery pending

- [x] Disposable-profile real Blender register/smoke, with a sentinel proving the
      real user profile was never written.
- [x] Path-boundary adversarial/mocked checks: profile escape, symlink/reparse,
      and path tricks rejected before any destructive operation.
- [x] Concurrent unrelated/live-profile sentinel files and content hashes unchanged
      across the full invocation.
- [x] Injected locked-module or copy failure rolls back and preserves the complete
      prior installation.
- [x] No leftover child processes or environment changes after the test.
- [x] Exact full-suite local-host test passes through disposable profile plumbing.
- [x] CPU-only smoke, no GPU work; at most two implementation worktrees;
      Astra integration and owner-authorized independent Terra SIGN-OFF.

Host evidence: 62 focused tests passed, one real Blender test deliberately
deselected; differential lint reported zero new findings. Both unset and set
environment states, stage-root links, real Windows junctions, missing installed
paths, temporary unrelated sentinels, and both smoke/launch modes under actual
PowerShell7 and Windows PowerShell5.1 were exercised. Actual Blender smokes,
exact local-host test (8.15s), all471 unchanged live-profile hashes and independent
Terra final review passed. Post-promotion
backup cleanup failure is an explicitly reported incomplete cleanup, not a
claim that the prior installation was restored. Full evidence and delegation
JSON: [pkg236 implementation evidence](../docs/pkg236-implementation-evidence.md).

## Non-goals

No renderer feature changes; no uninstalling or replacing the live user install;
no weakening of the existing freshness/register guards; no owner queue priority
change; no Pillar 4 work.

# pkg236 — Hermetic Blender dev-loop smoke

**Pillar:** 5
**Track:** A
**Status:** done — PR #711, 2699b43, 2026-09-06
**Estimated effort:** TBD
**Depends on:** none

---

## Goal

Before: the dev-loop smoke (`tests/test_dev_loop_smoke.py::test_dev_loop_smoke_local_host`
invoking `scripts/dev_addon.ps1 -Smoke -SkipBuild`) could install into the REAL
Blender 5.2 user profile. After: the dev-loop smoke is automated entirely under
a disposable, isolated Blender user profile with explicitly bounded
staging/install paths; the test invocation passes isolated-profile plumbing
through the canonical `scripts/dev_addon.ps1` and existing build/install
helpers; safety is never inferred from `-SkipBuild` (it still installs); final
absolute targets are resolved and checked before any destructive
copy/remove/move, rejecting profile-escape, symlink/reparse, and path tricks;
copy, locked-target rename, and promotion failures preserve or restore the
complete prior install; promotion commits the new complete tree, and a
subsequent backup cleanup failure reports failure and both recovery paths; a
partially deleted backup is never restored; the live user
addon/files/preferences are preserved and the process environment is restored
after the test. This is not crash-atomic across process termination between
filesystem renames.

---

## Context

This package serves Pillar 5 (Blender/DCC dev-loop tooling). It reuses the
canonical `scripts/dev_addon.ps1` and existing build/install helpers, with no
owner queue promotion; the owner authorized bounded parallel lower-backlog work
for this round. Estimated effort was left TBD at architect review. Terra
SIGN-OFF and documented gates passed.

---

## Evidence

- `tests/test_dev_loop_smoke.py::test_dev_loop_smoke_local_host` invokes
  `scripts/dev_addon.ps1 -Smoke -SkipBuild`; with Blender 5.2 installed this
  path can install into the REAL Blender 5.2 user profile.
- The pkg230 Phase 2 full-suite attempt hit a locked native `.pyd` and
  partially deleted addon support directories.
- Recovery restored Python/assets from the matching `1967cb5` tree and the
  unchanged runtime DLL bundle, preserving the installed native module;
  `PKG175_REGISTER_RESULT` passed.
- This is restored incident context, not an implementation result for this new
  package; evidence retained in feature
  `test_results/pkg230-p2/full-suite.log`.
- Host evidence: 62 focused tests passed, one real Blender test deliberately
  deselected; differential lint reported zero new findings.
- Both unset and set environment states, stage-root links, real Windows
  junctions, missing installed paths, temporary unrelated sentinels, and both
  smoke/launch modes under actual PowerShell 7 and Windows PowerShell 5.1 were
  exercised.
- Actual Blender smokes, exact local-host test (8.15s), all 471 unchanged
  live-profile hashes and independent Terra final review passed.
- Post-promotion backup cleanup failure is an explicitly reported incomplete
  cleanup, not a claim that the prior installation was restored.
- Both push/PR CI runs passed authoritative pytest (2173 passed, 277 skipped,
  15 xfailed, 4 xpassed) and CUDA checks.
- The existing informational reference smoke remains a recorded failure: two
  gates passed, one failed; independent Terra adjudicated it non-blocking for
  this installer-only package.
- Pkg249 owns separate diagnosis; no exact image-level cause or
  full-reference-green claim.

---

## Reference

- Full evidence and delegation JSON:
  [pkg236 implementation evidence](../docs/pkg236-implementation-evidence.md).

---

## Prerequisites

- [ ] TBD

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_pkg236_hermetic_install.py` | Path-boundary adversarial/mocked checks, rollback/preservation, and sentinel/hash coverage for the hermetic install |

### Files to modify

| File | What changes |
|---|---|
| `scripts/dev_addon.ps1` | Canonical installer gains an optional keyword-only `allowed_root` and uses copy-before-mutation plus sibling backup/promotion renames |
| `scripts/build/build_blender_addon.py` | Existing build/install helper that receives the isolated-profile plumbing with explicitly bounded staging/install paths |
| `tests/test_dev_loop_smoke.py` | Dev-loop smoke test invoking `scripts/dev_addon.ps1 -Smoke -SkipBuild`; must pass isolated-profile plumbing through the canonical installer and never infer safety from `-SkipBuild` |

### Key design decisions

- Astra's 2026-09-06 bounded architecture uses an owned fresh profile before
  any Blender invocation.
- All five `BLENDER_USER_*` paths and `ASTRORAY_SMOKE_*` values are restored in
  `finally`.
- `-SmokeProfileParent` selects only the parent of a fresh disposable child; it
  is never itself installed into or removed.
- Smoke must load the actual bounded installation, without a staged-path
  fallback.
- The canonical installer gains an optional keyword-only `allowed_root` and
  uses copy-before-mutation plus sibling backup/promotion renames.
- Launch retains its explicit user-facing semantics.
- Pillar 4 remains PAUSED.

---

## Acceptance criteria

- [x] Disposable-profile real Blender register/smoke, with a sentinel proving the real user profile was never written.
- [x] Path-boundary adversarial/mocked checks: profile escape, symlink/reparse, and path tricks rejected before any destructive operation.
- [x] Concurrent unrelated/live-profile sentinel files and content hashes unchanged across the full invocation.
- [x] Injected locked-module or copy failure rolls back and preserves the complete prior installation.
- [x] No leftover child processes or environment changes after the test.
- [x] Exact full-suite local-host test passes through disposable profile plumbing.
- [x] CPU-only smoke, no GPU work; at most two implementation worktrees; Astra integration and owner-authorized independent Terra SIGN-OFF.

---

## Non-goals

- No renderer feature changes.
- No uninstalling or replacing the live user install.
- No weakening of the existing freshness/register guards.
- No owner queue priority change.
- No Pillar 4 work.

---

## Progress

- (none yet)

---

## Lessons

- (none yet)

# pkg236 implementation evidence

2026-09-06, isolated worktree `.claude/worktrees/pkg236`, branch `codex/pkg236`,
base `45331d3f4e200f845885a612c709c130e4ee06a9`, integrated main `8217234`.
Implementation, actual Blender smoke and owner-authorized Terra final SIGN-OFF
complete; CI and delivery pending.

## Measured host gates

- `python -m pytest tests/test_pkg236_hermetic_install.py tests/test_dev_loop_smoke.py -q -k 'not local_host'`:
  **62 passed, 1 deselected** after final stderr/exit-code regression cases. No Blender or renderer native execution.
- Canonical differential lint against HEAD over the four source/test paths:
  **0 new findings**, ruff/markdownlint/codespell/git-diff-check ran across all
  six source/test/doc paths, zero unavailable/error.
- Actual temporary filesystem tests cover copy after real writes, locked old
  directory rename, failed promotion, failed rollback, partial backup cleanup,
  full old-tree byte comparisons, escape/traversal/Windows path alias rejection,
  symlinks and a real Windows junction. No platform cases skipped in this run.
- The canonical PowerShell entrypoint ran in temporary repositories with fake
  Blender responses and actual Python subprocess installation. Both pre-set and
  absent environment variables were restored. All five Blender paths stayed
  below one owned profile; unrelated sentinel bytes stayed intact; profiles
  were removed on success and injected failures. Unsafe profile/stage paths
  failed before any fake Blender invocation. Missing install did not fall back.
- Both smoke and launch passed under actual PowerShell 7 and Windows
  PowerShell 5.1. A nonempty `-` install-root sentinel preserves argv in legacy
  launch mode; profile creation sends Python through stdin to preserve quotes.

## Behavioral limits for final review

Copy and old-target rename failures leave the old tree unchanged. Failed
promotion restores the complete old backup when rollback succeeds. Failed
rollback returns false and reports the preserved backup path. Successful
promotion commits a complete new installation. If deleting its old backup then
fails, the function returns false and reports both the complete new target and
the remaining, potentially partial backup. It does not roll partial backup data
back into service. This is narrower than rollback on every possible failure.

Filesystem checks inspect lexical ancestors with `lstat`, reject links/reparse
points, check resolved containment, and validate stage/old trees. They are not
an OS-handle-based defense against hostile concurrent filesystem substitution.
Process termination between renames is not crash-atomic. Parent real-Blender
verification confirmed process exit and live-profile preservation as below.

## Caller audit

`install_to_blender(blender_exe: Path, *, allowed_root: Path | None = None) -> bool`
adds one optional keyword. Existing calls in its CLI `main()` and
`scripts/dev/test_blender_addon.py` remain compatible. PowerShell smoke passes
the owned child as `allowed_root`; launch passes `None`. The existing resolver
signature is unchanged. New private validators are used by installer and
PowerShell stage preflight. `-SmokeProfileParent` is an optional PowerShell
parameter; the local smoke test now explicitly passes its pytest temporary dir.

## Canonical implementation delegation JSON

Tier and model were resolved by the current root pkg232 wrapper from its tier
configuration, with `--tier implement --agent worker --dir <pkg236> --timeout 600`.
Worker ownership was only the canonical installer and its new focused tests.
The wrapper snapshot also observed concurrent coordinator changes to PowerShell
and its tests. Coordinator inspected and repaired the draft; process completion
was not accepted as implementation success.

```json
{
  "status": "completed",
  "model": "opencode-go/deepseek-v4-pro",
  "agent": "worker",
  "workdir": "C:\\Users\\hgcom\\OneDrive\\Astroray\\Astroray_repo\\Astroray\\.claude\\worktrees\\pkg236",
  "wall_s": 452.1,
  "exit_code": 0,
  "termination_reason": "normal",
  "cleanup": {
    "method": "windows_job_object",
    "confirmed": true,
    "active_processes": 0,
    "error": null
  },
  "finish_reason": "stop",
  "tool_calls": 29,
  "tokens": {
    "total": 57228,
    "input": 958,
    "output": 718,
    "reasoning": 0,
    "cache": {"write": 0, "read": 55552}
  },
  "cost": 0.003276064,
  "session_id": "ses_f8bf7c3f0ffe2Mv1dsKTZuCowu",
  "errors": [],
  "git_head": "45331d3f4e200f845885a612c709c130e4ee06a9",
  "head_moved": false,
  "files_changed": [
    " M scripts/dev_addon.ps1",
    " M tests/test_dev_loop_smoke.py",
    "?? tests/test_pkg236_hermetic_install.py",
    "M scripts/build/build_blender_addon.py"
  ],
  "transcript": "C:\\Users\\hgcom\\AppData\\Local\\astroray\\delegate-logs\\20260906-100439-51df2e7d23eb-implement.jsonl",
  "verdict": "EVIDENCE ONLY -- caller must verify via build/tests/diff; never trust worker narrative"
}
```

## Parent real-Blender and independent gates

The existing canonical CPU package (build ID `4035a00+20260905T173933Z`, CUDA and
OpenMP false) supplied native binaries for explicit `-SkipBuild` testing. Native
sources match current main; this is not a new build or GPU verification claim.
Final staging includes the landed pkg230b addon from main `8217234`.

- Actual PowerShell7 smoke passed (8.3s); final Windows PowerShell5.1 smoke
  passed (7.4s), exit0 and register/render PASS sentinels, loading the actual
  disposable-profile installation. Finite96x96 RGB, mean luminance0.117186,
  nonblack fraction1.0. The latter covers final stderr handling.
- Exact pytest local-host test: **1 passed in8.15s**, exercising full-suite
  profile plumbing with real Blender.
- Same-process environment comparison passed; owned profile removed; unrelated
  sentinel retained. Read-only hashes of all471 live-profile files showed zero
  changed/new files. Only original user Blender PID36532 remained.
- Initial PowerShell5.1 invocation hit the host script execution policy; retry
  used process-local `-ExecutionPolicy Bypass`, no persistent policy change.
  That retry exposed native-stderr warning handling. It was fixed and tested
  in both shells; failed logs remain retained, not counted as passes. Final
  capture requires a PASS sentinel AND exit0 and retains warning diagnostics.
- Owner-authorized independent Terra final SIGN-OFF covers source/callers,
  safety boundaries, final stderr fix, real smoke and transaction limits.
  Root evidence: `test_results/pkg236/final-terra-review.txt`,
  `real-cpu-smoke.log`, `real-powershell51-cpu-smoke-final.log`,
  `real-smoke-guard-result.json`; feature `test_results/pkg236-local-host.xml`.

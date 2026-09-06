#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Hermetic tests for the Claude Code PreToolUse hooks in .claude/hooks/.

Covers the 2026-09-07 fixes:
  * pre_commit_diag_check.ps1 was reading the tool command from JSON field
    paths that don't match the real PreToolUse payload shape
    (`.tool_input.command`), so it silently no-op'd on every real call.
  * pre_commit_diag_check.ps1 and pre_commit_spec_lint.ps1 always checked
    $env:CLAUDE_PROJECT_DIR (the main checkout) even when the commit
    targeted a linked worktree via `git -C <path>` or `cd <path> && ...`.

CPU-only and hermetic: builds disposable `git init` repos under tmp_path,
each wired to a tiny stub `scripts/project_index.py` so the spec-lint hook's
pass/fail outcome is deterministic and independent of the real linter.
Invokes the real hook scripts in place (so `$PSScriptRoot` still finds the
real `_resolve_repo.ps1`) via subprocess with a fake PreToolUse JSON payload
on stdin. Skips if neither `pwsh` nor `powershell` is on PATH.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / ".claude" / "hooks"
DIAG_HOOK = HOOKS_DIR / "pre_commit_diag_check.ps1"
SPEC_LINT_HOOK = HOOKS_DIR / "pre_commit_spec_lint.ps1"

# Minimal stand-in for `scripts/project_index.py lint <specs...>`: fails only
# when one of the spec paths contains the literal marker "BADSPEC". Keeps the
# hook test independent of the real lint rules.
_STUB_PROJECT_INDEX = (
    "import sys\n"
    'bad = any("BADSPEC" in a for a in sys.argv[1:])\n'
    "if bad:\n"
    '    print("LINT FAIL")\n'
    "    sys.exit(1)\n"
    'print("LINT OK")\n'
    "sys.exit(0)\n"
)


def _pwsh():
    return shutil.which("pwsh") or shutil.which("powershell")


def _init_repo(path: Path, diag_marker: bool, spec_bad: bool) -> Path:
    """Create a disposable git repo with a staged diagnostic-marker file and
    a staged package spec, wired to the stub project_index.py lint script."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)

    notes = path / "notes.txt"
    if diag_marker:
        # Built via concatenation, not a contiguous literal: this repo's own
        # pre_commit_diag_check.ps1 (now fixed to actually run) would block a
        # commit of this test file if the marker text appeared verbatim here.
        marker = "// [" + "diag] " + "REMOVE" + " AFTER debug\n"
        notes.write_text(marker, encoding="ascii")
    else:
        notes.write_text("clean content\n", encoding="ascii")

    scripts = path / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "project_index.py").write_text(_STUB_PROJECT_INDEX, encoding="ascii")

    packages = path / ".astroray_plan" / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    spec_name = "BADSPEC-pkg.md" if spec_bad else "pkg-good.md"
    (packages / spec_name).write_text("# spec\n", encoding="ascii")

    subprocess.run(
        ["git", "add", "notes.txt", "scripts/project_index.py",
         f".astroray_plan/packages/{spec_name}"],
        cwd=path, check=True,
    )
    return path


def _run_hook(hook: Path, command: str, cwd_field: str, project_dir: Path, pwsh: str) -> subprocess.CompletedProcess:
    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": cwd_field,
        "session_id": "test-session",
    })
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(hook)],
        input=payload, capture_output=True, text=True, encoding="utf-8",
        cwd=str(project_dir), env=env, timeout=60, check=False,
    )


@pytest.mark.cpu
class TestPreCommitDiagCheckHook:
    """A plain `git commit`, a `git -C <worktree> commit`, and a non-commit
    command, against the fixed pre_commit_diag_check.ps1."""

    def test_plain_commit_in_main_blocks_on_marker(self, tmp_path):
        pwsh = _pwsh()
        if pwsh is None:
            pytest.skip("pwsh/powershell not found")
        main = _init_repo(tmp_path / "main", diag_marker=True, spec_bad=False)
        proc = _run_hook(DIAG_HOOK, "git commit -m x", str(main), main, pwsh)
        assert proc.returncode == 2, proc.stdout + proc.stderr

    def test_git_dash_c_worktree_checks_worktree_not_main(self, tmp_path):
        pwsh = _pwsh()
        if pwsh is None:
            pytest.skip("pwsh/powershell not found")
        # Main is dirty (staged diagnostic marker); the targeted worktree is
        # clean. The hook must check the worktree, not $env:CLAUDE_PROJECT_DIR.
        main = _init_repo(tmp_path / "main", diag_marker=True, spec_bad=False)
        wt = _init_repo(tmp_path / "worktree", diag_marker=False, spec_bad=False)
        command = 'git -C "{}" commit -m x'.format(wt)
        proc = _run_hook(DIAG_HOOK, command, str(wt), main, pwsh)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_non_commit_command_is_noop(self, tmp_path):
        pwsh = _pwsh()
        if pwsh is None:
            pytest.skip("pwsh/powershell not found")
        main = _init_repo(tmp_path / "main", diag_marker=True, spec_bad=False)
        proc = _run_hook(DIAG_HOOK, "git status", str(main), main, pwsh)
        assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.cpu
class TestPreCommitSpecLintHook:
    """Same three payload shapes against pre_commit_spec_lint.ps1."""

    def test_plain_commit_in_main_blocks_on_bad_spec(self, tmp_path):
        pwsh = _pwsh()
        if pwsh is None:
            pytest.skip("pwsh/powershell not found")
        main = _init_repo(tmp_path / "main", diag_marker=False, spec_bad=True)
        proc = _run_hook(SPEC_LINT_HOOK, "git commit -m x", str(main), main, pwsh)
        assert proc.returncode == 2, proc.stdout + proc.stderr

    def test_git_dash_c_worktree_checks_worktree_not_main(self, tmp_path):
        pwsh = _pwsh()
        if pwsh is None:
            pytest.skip("pwsh/powershell not found")
        # Main has a bad spec staged; the targeted worktree's spec is clean.
        # The hook must lint the worktree, not $env:CLAUDE_PROJECT_DIR.
        main = _init_repo(tmp_path / "main", diag_marker=False, spec_bad=True)
        wt = _init_repo(tmp_path / "worktree", diag_marker=False, spec_bad=False)
        command = 'git -C "{}" commit -m x'.format(wt)
        proc = _run_hook(SPEC_LINT_HOOK, command, str(wt), main, pwsh)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_non_commit_command_is_noop(self, tmp_path):
        pwsh = _pwsh()
        if pwsh is None:
            pytest.skip("pwsh/powershell not found")
        main = _init_repo(tmp_path / "main", diag_marker=False, spec_bad=True)
        proc = _run_hook(SPEC_LINT_HOOK, "git status", str(main), main, pwsh)
        assert proc.returncode == 0, proc.stdout + proc.stderr

#!/usr/bin/env python3
"""Evidence-collecting wrapper around `opencode run` for delegating work to
open-weight models.

Design contract (see SKILL.md): this wrapper NEVER claims the delegated task
succeeded. It runs the worker, captures the full JSONL event stream, snapshots
git state before/after, and emits a machine-readable evidence summary. The
caller (Claude) judges success from the evidence -- build results, diffs,
tests -- never from the worker's own narrative or exit code.

Rationale: opencode has documented cases of exiting 0 after a mid-session
error (anomalyco/opencode #14551, #2489), and open models over-claim under
uncertainty. Artifacts only.

Usage:
  python delegate.py --tier grunt|implement|verify [--model provider/model]
                     [--agent NAME] [--dir PATH] [--timeout SEC]
                     (--prompt "..." | --prompt-file FILE)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TIERS_FILE = SKILL_DIR / "config" / "tiers.json"
LOG_ROOT = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "astroray" / "delegate-logs"


def _opencode_cmd(args):
    """Windows can't CreateProcess a .ps1/.cmd directly -- route via cmd /c."""
    exe = shutil.which("opencode")
    if exe is None:
        sys.exit("delegate.py: opencode not found on PATH")
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat", ".ps1")):
        # npm ships opencode.cmd alongside the .ps1; prefer the .cmd shim
        cmd_shim = str(Path(exe).with_suffix(".cmd"))
        if Path(cmd_shim).exists():
            return ["cmd", "/c", cmd_shim, *args]
        return ["cmd", "/c", exe, *args]
    return [exe, *args]


def _git(workdir, *args):
    try:
        r = subprocess.run(["git", *args], cwd=workdir, capture_output=True,
                           text=True, timeout=60, check=False)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _git_snapshot(workdir):
    status = _git(workdir, "status", "--porcelain")
    head = _git(workdir, "rev-parse", "HEAD")
    return {"head": head, "dirty_files": sorted(status.splitlines()) if status else []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=["grunt", "implement", "verify"])
    ap.add_argument("--model", help="provider/model override; else tier primary")
    ap.add_argument("--fallback", action="store_true",
                    help="use the tier's fallback model instead of primary")
    ap.add_argument("--agent", help="opencode agent name (from .opencode/agents/)")
    ap.add_argument("--dir", default=".", help="working directory for the worker")
    ap.add_argument("--timeout", type=int, help="seconds; default from tier config")
    ap.add_argument("--prompt")
    ap.add_argument("--prompt-file")
    args = ap.parse_args()

    if not args.prompt and not args.prompt_file:
        sys.exit("delegate.py: --prompt or --prompt-file required")
    prompt = args.prompt or Path(args.prompt_file).read_text(encoding="utf-8")

    tiers = json.loads(TIERS_FILE.read_text(encoding="utf-8"))["tiers"]
    tier_cfg = tiers.get(args.tier, {}) if args.tier else {}
    model = args.model or (tier_cfg.get("fallback") if args.fallback
                           else tier_cfg.get("primary"))
    if not model:
        sys.exit("delegate.py: no model resolved (--tier or --model required)")
    timeout = args.timeout or tier_cfg.get("default_timeout_s", 900)

    workdir = str(Path(args.dir).resolve())
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = LOG_ROOT / f"{stamp}-{(args.tier or 'custom')}.jsonl"

    # Multi-line prompts do NOT survive the Windows cmd /c argv path (cmd
    # truncates at the first newline; the worker sees only line 1 — observed
    # 2026-08-07, flash correctly refused a truncated worklist). Route them
    # through a task file inside the project (workers can read project files
    # but not paths outside it).
    task_file = None
    if "\n" in prompt.strip():
        task_file = Path(workdir) / f".delegate-task-{stamp}.md"
        task_file.write_text(prompt, encoding="utf-8")
        prompt = (f"Read the file {task_file.name} in the project root and "
                  "execute the task it contains EXACTLY. That file is your "
                  "full task; do not treat this one-line message as the task.")

    pre = _git_snapshot(workdir)

    # opencode IGNORES the subprocess cwd: it roots its shell/file tools at the
    # git project worktree, which for ANY linked worktree resolves (via the
    # shared .git common dir) to the MAIN checkout. Without opencode's own
    # --dir flag, every edit is silently redirected into main (contamination,
    # not a rejection) while the wrapper watches the worktree and reports
    # files_changed:[] — a false "completed". Pass --dir to root opencode AT
    # the worktree. Verified 2026-08-25: writes then land in the worktree.
    oc_args = ["run", "-m", model, "--dir", workdir, "--format", "json"]
    if args.agent:
        oc_args += ["--agent", args.agent]
    oc_args.append(prompt)

    t0 = time.monotonic()
    status = "completed"
    exit_code = None
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            r = subprocess.run(_opencode_cmd(oc_args), cwd=workdir,
                               stdout=log, stderr=subprocess.STDOUT,
                               timeout=timeout, text=True, check=False)
            exit_code = r.returncode
    except subprocess.TimeoutExpired:
        status = "timeout"
    finally:
        if task_file is not None:
            task_file.unlink(missing_ok=True)
    wall_s = round(time.monotonic() - t0, 1)

    post = _git_snapshot(workdir)

    # Parse the event stream for evidence (defensively -- schema may drift).
    tokens, cost, session_id, tool_calls, errors, finish_reason = None, None, None, 0, [], None
    try:
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            et = ev.get("type")
            session_id = ev.get("sessionID", session_id)
            part = ev.get("part", {})
            if et == "tool_use":
                tool_calls += 1
            elif et == "step_finish":
                tokens = part.get("tokens", tokens)
                cost = part.get("cost", cost)
                finish_reason = part.get("reason", finish_reason)
            elif et == "error":
                err = ev.get("error", {})
                errors.append(err.get("name") or str(err)[:200])
    except OSError:
        pass

    if errors and status == "completed":
        status = "errored"
    if status == "completed" and finish_reason != "stop":
        # Stream ended without a clean stop -- documented unreliable-stream case.
        status = "no_clean_finish"

    changed = sorted(set(post["dirty_files"]) - set(pre["dirty_files"]))
    summary = {
        "status": status,               # completed | timeout | errored | no_clean_finish
        "model": model,
        "agent": args.agent,
        "workdir": workdir,
        "wall_s": wall_s,
        "exit_code": exit_code,
        "finish_reason": finish_reason,
        "tool_calls": tool_calls,
        "tokens": tokens,
        "cost": cost,
        "session_id": session_id,
        "errors": errors,
        "git_head": post["head"],
        "head_moved": pre["head"] != post["head"],
        "files_changed": changed,
        "transcript": str(log_path),
        "verdict": "EVIDENCE ONLY -- caller must verify via build/tests/diff; never trust worker narrative",
    }
    print(json.dumps(summary, indent=2))
    # Exit 0 iff the wrapper itself worked; task success is the caller's call.
    return 0


if __name__ == "__main__":
    sys.exit(main())

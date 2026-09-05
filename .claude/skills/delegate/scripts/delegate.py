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

Windows process-tree containment (pkg232): on Windows the worker is launched
inside an unnamed Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE and no
breakaway flags, so every ordinary CreateProcess descendant of the worker
inherits Job membership. On timeout/cancellation/error -- and on ordinary
completion -- the wrapper terminates and awaits the full Job tree before
taking the final git snapshot and parsing the transcript, so no owned process
keeps writing files after the wrapper returns its evidence. See SKILL.md for
the platform boundary (non-Windows keeps the direct-child subprocess.run path).

Usage:
  python delegate.py --tier grunt|implement|verify [--model provider/model]
                     [--agent NAME] [--dir PATH] [--timeout SEC]
                     (--prompt "..." | --prompt-file FILE)
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TIERS_FILE = SKILL_DIR / "config" / "tiers.json"
LOG_ROOT = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "astroray" / "delegate-logs"

# Platform flag. Computed once at import so tests can stub the non-Windows
# branch without mutating the global os.name (which would break pathlib).
IS_WINDOWS = os.name == "nt"

# ---------------------------------------------------------------------------
# Windows Job Object containment (pkg232). A small local ctypes binding with
# explicit argument/result types and pointer-width-correct structures.
# References: Microsoft "Job Objects" and "AssignProcessToJobObject" docs.
# ---------------------------------------------------------------------------

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # Job Object Information Class for basic accounting.
    _JobObjectBasicAccountingInformation = 1
    # Job Object Information Class for extended limit information.
    _JobObjectExtendedLimitInformation = 9
    # Limit flag: kill all members when the last Job handle closes.
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    # Startup flag: no console window for the helper.
    _CREATE_NO_WINDOW = 0x08000000

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]

    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]

    _kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]

    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]

    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    def _create_job():
        """Create an unnamed Job with KILL_ON_JOB_CLOSE and no breakaway flags.

        Returns the non-inheritable Job handle, or None on failure.
        """
        handle = _kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _kernel32.SetInformationJobObject(
                handle, _JobObjectExtendedLimitInformation,
                ctypes.byref(info), ctypes.sizeof(info)):
            _kernel32.CloseHandle(handle)
            return None
        return handle

    def _job_active_processes(job_handle):
        """Return the number of active processes in the Job, or None on failure."""
        acct = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        ret_len = wintypes.DWORD()
        if not _kernel32.QueryInformationJobObject(
                job_handle, _JobObjectBasicAccountingInformation,
                ctypes.byref(acct), ctypes.sizeof(acct), ctypes.byref(ret_len)):
            return None
        return int(acct.ActiveProcesses)

    def _terminate_job(job_handle):
        """Terminate all processes in the Job. Returns True on success."""
        return bool(_kernel32.TerminateJobObject(job_handle, 1))

    def _close_handle(handle):
        if handle:
            _kernel32.CloseHandle(handle)

    def _get_last_error():
        return ctypes.get_last_error()


def _opencode_cmd(args):
    """Windows can't CreateProcess a .ps1/.cmd directly -- route via cmd /c."""
    exe = shutil.which("opencode")
    if exe is None:
        raise FileNotFoundError("delegate.py: opencode not found on PATH")
    if IS_WINDOWS and exe.lower().endswith((".cmd", ".bat", ".ps1")):
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


def _parse_transcript(log_path):
    """Parse the JSONL event stream for evidence (defensively -- schema may drift)."""
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
    return tokens, cost, session_id, tool_calls, errors, finish_reason


def _helper_main():
    """Private launch gate: command stdin is released only after Job assignment."""
    raw = sys.stdin.buffer.read()
    if not raw:
        return 0
    try:
        record = json.loads(raw.decode("utf-8"))
        cmd, workdir = record["cmd"], record["cwd"]
        if not (isinstance(cmd, list) and cmd
                and all(isinstance(arg, str) for arg in cmd)
                and isinstance(workdir, str)):
            return 2
    except (ValueError, KeyError, TypeError):
        return 2
    try:
        # The parent owns the transcript; this helper and its descendants only
        # inherit that output. They never inherit the parent's Job handle.
        proc = subprocess.Popen(cmd, cwd=workdir, stdin=subprocess.DEVNULL,
                                stdout=sys.stdout, stderr=sys.stderr)
        return proc.wait()
    except OSError as exc:
        print(json.dumps({"type": "error", "error": {
            "name": f"worker launch failed: {exc}"}}), flush=True)
        return 1


@contextmanager
def _cancellation_state():
    """Record console cancellation without interrupting resource acquisition.

    Checkpoints raise only once handles have been stored. During cleanup the
    handler only records a request, so repeated Ctrl-C cannot bypass teardown.
    """
    state = {"signal": None}
    saved = {}

    def record(signum, _frame):
        state["signal"] = signum

    if threading.current_thread() is threading.main_thread():
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            signum = getattr(signal, name, None)
            if signum is not None:
                saved[signum] = signal.signal(signum, record)
    try:
        yield state
    finally:
        for signum, handler in saved.items():
            signal.signal(signum, handler)


def _check_cancellation(state):
    if state["signal"] is not None:
        raise KeyboardInterrupt(f"signal {state['signal']}")


def _cleanup_job(job_handle, helper, timeout=10.0):
    """Stop owned instances and prove exit within one bounded cleanup deadline."""
    deadline = time.monotonic() + timeout
    errors = []
    helper_exited = helper is None
    active = 0 if job_handle is None else None
    if job_handle is not None and not _terminate_job(job_handle):
        errors.append(f"TerminateJobObject failed (error {_get_last_error()})")
    if helper is not None:
        try:
            # Also covers a blocked helper whose assignment failed. Popen uses
            # its retained process handle; no PID lookup or ancestry kill.
            if helper.poll() is None:
                helper.kill()
            helper.wait(timeout=max(0.0, deadline - time.monotonic()))
            helper_exited = True
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"helper exit unconfirmed: {exc}")
    if job_handle is not None:
        while True:
            active = _job_active_processes(job_handle)
            if active in (0, None) or time.monotonic() >= deadline:
                break
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        if active is None:
            errors.append(f"QueryInformationJobObject failed (error {_get_last_error()})")
        elif active:
            errors.append(f"{active} Job processes still active at cleanup deadline")
    return {"method": "windows_job_object", "confirmed": helper_exited and active == 0,
            "active_processes": active, "error": "; ".join(errors) or None}


def _run_windows_contained(cmd, workdir, log_path, timeout):
    """Gate launch on Job assignment; finish teardown before returning evidence."""
    job_handle = helper = log_fh = None
    result = {"status": "completed", "exit_code": None,
              "termination_reason": "normal", "errors": []}
    with _cancellation_state() as cancellation:
        try:
            job_handle = _create_job()
            if not job_handle:
                raise OSError(f"Job creation/configuration failed (error {_get_last_error()})")
            _check_cancellation(cancellation)
            # Parent-opened transcript is distinct from parent JSON stdout.
            log_fh = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
            helper = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--_helper"],
                cwd=workdir, stdin=subprocess.PIPE, stdout=log_fh,
                stderr=subprocess.STDOUT, creationflags=_CREATE_NO_WINDOW)
            _check_cancellation(cancellation)
            proc_handle = getattr(helper, "_handle", None)
            if proc_handle is None:
                raise OSError("Popen._handle unavailable (unsupported interpreter)")
            if not _kernel32.AssignProcessToJobObject(job_handle, proc_handle):
                raise OSError(f"AssignProcessToJobObject failed (error {_get_last_error()})")
            _check_cancellation(cancellation)
            helper.stdin.write(json.dumps({"cmd": cmd, "cwd": workdir}).encode("utf-8"))
            helper.stdin.close()  # EOF releases the complete record.
            deadline = time.monotonic() + timeout
            while True:
                _check_cancellation(cancellation)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(cmd, timeout)
                try:
                    result["exit_code"] = helper.wait(timeout=min(0.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
            if result["exit_code"] != 0:
                result["status"] = "errored"
                result["termination_reason"] = "error"
                result["errors"].append(f"worker exited with code {result['exit_code']}")
        except subprocess.TimeoutExpired:
            result.update(status="timeout", termination_reason="timeout")
        except KeyboardInterrupt as exc:
            result.update(status="errored", termination_reason="cancelled")
            result["errors"].append(f"cancelled: {exc}")
        except (OSError, subprocess.SubprocessError) as exc:
            result.update(status="errored", termination_reason="error")
            result["errors"].append(str(exc))
        finally:
            try:
                result["cleanup_evidence"] = _cleanup_job(job_handle, helper)
            except (OSError, subprocess.SubprocessError) as exc:
                result["cleanup_evidence"] = {
                    "method": "windows_job_object", "confirmed": False,
                    "active_processes": None, "error": f"cleanup failed: {exc}"}
            finally:
                # One owner closes each handle exactly once. Last Job closure
                # is the kernel fallback, never substituted for exit evidence.
                if job_handle is not None:
                    _close_handle(job_handle)
                for stream in (helper.stdin if helper is not None else None, log_fh):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError as exc:
                            result["errors"].append(f"stream close failed: {exc}")
        if cancellation["signal"] is not None and result["termination_reason"] == "normal":
            result.update(status="errored", termination_reason="cancelled")
            result["errors"].append(f"cancelled: signal {cancellation['signal']}")
    return result


def _run_direct_child(cmd, workdir, log_path, timeout):
    """Keep the existing non-Windows subprocess.run/direct-child boundary."""
    result = {"status": "completed", "exit_code": None,
              "termination_reason": "normal", "errors": [],
              "cleanup_evidence": {"method": "direct_child", "confirmed": True,
                                   "error": None}}
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            completed = subprocess.run(cmd, cwd=workdir, stdout=log,
                                       stderr=subprocess.STDOUT, timeout=timeout,
                                       text=True, check=False)
            result["exit_code"] = completed.returncode
    except subprocess.TimeoutExpired:
        result.update(status="timeout", termination_reason="timeout")
    except KeyboardInterrupt as exc:
        # subprocess.run does not promise a child has exited on Ctrl-C.
        result.update(status="errored", termination_reason="cancelled")
        result["cleanup_evidence"].update(confirmed=False,
                                          error="direct-child exit unconfirmed after cancellation")
        result["errors"].append(f"cancelled: {exc}")
    except OSError as exc:
        result.update(status="errored", termination_reason="error")
        result["errors"].append(str(exc))
    return result


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
    ap.add_argument("--_helper", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args._helper:
        return _helper_main()

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
    # Unique invocation suffix so concurrent delegates cannot delete each
    # other's task files or share an output stream.
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{uuid.uuid4().hex[:12]}"
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
    try:
        cmd = _opencode_cmd(oc_args)
    except OSError as exc:
        # Command resolution can fail before any worker was launched.
        result = {"status": "errored", "exit_code": None,
                  "termination_reason": "error", "errors": [str(exc)],
                  "cleanup_evidence": {"method": "not_started", "confirmed": True,
                                       "error": None}}
    else:
        runner = _run_windows_contained if IS_WINDOWS else _run_direct_child
        result = runner(cmd, workdir, log_path, timeout)
    status, exit_code = result["status"], result["exit_code"]
    termination_reason = result["termination_reason"]
    cleanup_evidence = result["cleanup_evidence"]
    wrapper_errors = result.get("errors", [])
    if task_file is not None and cleanup_evidence["confirmed"]:
        try:
            task_file.unlink(missing_ok=True)
        except OSError as exc:
            wrapper_errors.append(f"task-file removal failed: {exc}")
            if status == "completed":
                status = "errored"

    wall_s = round(time.monotonic() - t0, 1)

    # Only take the final snapshot and parse the transcript once cleanup is
    # confirmed. If cleanup could not be confirmed, report unavailable evidence
    # rather than a misleading clean snapshot.
    cleanup_confirmed = bool(cleanup_evidence and cleanup_evidence.get("confirmed"))
    if cleanup_confirmed:
        post = _git_snapshot(workdir)
        tokens, cost, session_id, tool_calls, errors, finish_reason = \
            _parse_transcript(log_path)

        if errors and status == "completed":
            status = "errored"
        if status == "completed" and finish_reason != "stop":
            # Stream ended without a clean stop -- documented unreliable-stream case.
            status = "no_clean_finish"

        changed = sorted(set(post["dirty_files"]) - set(pre["dirty_files"]))
        git_head = post["head"]
        head_moved = pre["head"] != post["head"]
    else:
        # Cleanup unconfirmed: retain timeout when already timed out, else
        # errored; skip snapshot and transcript-derived claims.
        if status != "timeout":
            status = "errored"
        tokens = cost = session_id = finish_reason = None
        tool_calls = None
        errors = []
        changed = None
        git_head = None
        head_moved = None

    errors = wrapper_errors + errors
    if errors and status == "completed":
        status = "errored"
    summary = {
        "status": status,               # completed | timeout | errored | no_clean_finish
        "model": model,
        "agent": args.agent,
        "workdir": workdir,
        "wall_s": wall_s,
        "exit_code": exit_code,
        "termination_reason": termination_reason,  # normal | timeout | cancelled | error
        "cleanup": cleanup_evidence,
        "finish_reason": finish_reason,
        "tool_calls": tool_calls,
        "tokens": tokens,
        "cost": cost,
        "session_id": session_id,
        "errors": errors,
        "git_head": git_head,
        "head_moved": head_moved,
        "files_changed": changed,
        "transcript": str(log_path),
        "verdict": "EVIDENCE ONLY -- caller must verify via build/tests/diff; never trust worker narrative",
    }
    print(json.dumps(summary, indent=2))
    # Exit 0 iff the wrapper itself worked; task success is the caller's call.
    return 0


if __name__ == "__main__":
    sys.exit(main())

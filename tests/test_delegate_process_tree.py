#!/usr/bin/env python
"""Focused lifecycle/summary tests and real Windows process-tree canaries for
the delegate wrapper's Windows Job Object containment (pkg232).

The wrapper (`.claude/skills/delegate/scripts/delegate.py`) must own, stop and
await its full descendant process tree on timeout/cancellation/error and on
ordinary completion, before taking the final git snapshot and parsing the
transcript. These tests exercise that machinery directly (never invoking a real
opencode worker) plus the summary/evidence logic.

Temporary worker programs are test fixtures written into pytest temporary
directories; test-owned process handles are cleaned in `finally` blocks so a
failure cannot leak processes.
"""

import io
import json
import os
import signal
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

import pytest

DELEGATE_PY = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "delegate" / "scripts" / "delegate.py"

# Import the wrapper module by path (it is not a package).
import importlib.util

_spec = importlib.util.spec_from_file_location("delegate", DELEGATE_PY)
delegate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(delegate)

IS_WINDOWS = os.name == "nt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_worker(tmp_path, name, body):
    """Write a small Python worker program into tmp_path and return its path."""
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def _python_cmd(script_path, *args):
    return [sys.executable, script_path, *args]


def _setup_main(monkeypatch, tmp_path, argv):
    """Stub the worker + config for tests that call delegate.main(), and set
    sys.argv so argparse parses our args (not pytest's)."""
    monkeypatch.setattr(delegate, "_opencode_cmd", lambda args: ["fake", *args])
    monkeypatch.setattr(delegate, "LOG_ROOT", tmp_path / "logs")
    monkeypatch.setattr(delegate, "TIERS_FILE", tmp_path / "tiers.json")
    (tmp_path / "tiers.json").write_text(json.dumps({
        "tiers": {"grunt": {"primary": "m/x", "default_timeout_s": 5}}}),
        encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["delegate.py", *argv])
    return io.StringIO()


def _run_main(monkeypatch, tmp_path, argv, contained_result):
    """Run delegate.main() with a stubbed containment result; return (rc, summary)."""
    monkeypatch.setattr(delegate, "IS_WINDOWS", True)
    buf = _setup_main(monkeypatch, tmp_path, argv)
    if contained_result is not None:
        monkeypatch.setattr(delegate, "_run_windows_contained",
                            lambda cmd, workdir, log_path, timeout: contained_result)
    with redirect_stdout(buf):
        rc = delegate.main()
    return rc, json.loads(buf.getvalue())


# ---------------------------------------------------------------------------
# Unit tests: Job object creation / accounting (Windows only)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not IS_WINDOWS, reason="Windows-only Job Object API")
class TestJobObject:
    def test_create_job_returns_handle(self):
        h = delegate._create_job()
        assert h, "CreateJobObjectW should return a valid handle"
        try:
            assert delegate._job_active_processes(h) == 0
        finally:
            delegate._close_handle(h)

    def test_job_handle_closed(self):
        h = delegate._create_job()
        assert h
        delegate._close_handle(h)


# ---------------------------------------------------------------------------
# Unit tests: helper mode (no command after EOF, bad argv)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not IS_WINDOWS, reason="helper is Windows-only")
class TestHelperMode:
    def test_eof_before_record_exits_without_launch(self, tmp_path):
        marker = tmp_path / "marker.txt"
        r = subprocess.run(
            [sys.executable, str(DELEGATE_PY), "--_helper"],
            input=b"", capture_output=True, check=False,
            creationflags=delegate._CREATE_NO_WINDOW, timeout=5,
        )
        assert r.returncode == 0
        assert not marker.exists()

    def test_bad_json_exits_nonzero(self):
        r = subprocess.run(
            [sys.executable, str(DELEGATE_PY), "--_helper"],
            input=b"not-json", capture_output=True, check=False,
            creationflags=delegate._CREATE_NO_WINDOW, timeout=5,
        )
        assert r.returncode == 2

    def test_runs_command_and_returns_exit_code(self, tmp_path):
        marker = tmp_path / "ran.txt"
        worker = _write_worker(tmp_path, "w.py",
                               "import sys\nopen(sys.argv[1],'w').write('x')\n")
        record = json.dumps({"cmd": _python_cmd(worker, str(marker)),
                             "cwd": str(tmp_path)}).encode("utf-8")
        r = subprocess.run(
            [sys.executable, str(DELEGATE_PY), "--_helper"],
            input=record, capture_output=True, check=False,
            creationflags=delegate._CREATE_NO_WINDOW, timeout=5,
        )
        assert r.returncode == 0
        assert marker.exists()


# ---------------------------------------------------------------------------
# Unit tests: summary / order / failure / unavailable evidence
# ---------------------------------------------------------------------------

class TestSummaryLogic:
    def _completed(self):
        return {"status": "completed", "exit_code": 0,
                "termination_reason": "normal",
                "cleanup_evidence": {"method": "windows_job_object",
                                     "confirmed": True, "error": None}}

    def test_completed_summary_fields(self, monkeypatch, tmp_path):
        def fake(cmd, workdir, log_path, timeout):
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "step_finish",
                                    "part": {"reason": "stop", "tokens": 10,
                                             "cost": 0.01}}) + "\n")
            return self._completed()
        monkeypatch.setattr(delegate, "_run_windows_contained", fake)
        rc, s = _run_main(monkeypatch, tmp_path,
                          ["--tier", "grunt", "--prompt", "hello"], None)
        assert rc == 0
        assert s["status"] == "completed"
        assert s["termination_reason"] == "normal"
        assert s["cleanup"]["confirmed"] is True
        assert s["finish_reason"] == "stop"
        assert s["tool_calls"] == 0

    def test_timeout_then_clean_stop_still_timeout(self, monkeypatch, tmp_path):
        def fake(cmd, workdir, log_path, timeout):
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "step_finish",
                                    "part": {"reason": "stop"}}) + "\n")
            return {"status": "timeout", "exit_code": None,
                    "termination_reason": "timeout",
                    "cleanup_evidence": {"method": "windows_job_object",
                                         "confirmed": True, "error": None}}
        monkeypatch.setattr(delegate, "_run_windows_contained", fake)
        _, s = _run_main(monkeypatch, tmp_path,
                         ["--tier", "grunt", "--prompt", "hello"], None)
        # A later clean-stop event must NOT overwrite the sticky timeout.
        assert s["status"] == "timeout"
        assert s["termination_reason"] == "timeout"

    def test_cleanup_failure_yields_unavailable_evidence(self, monkeypatch, tmp_path):
        def fake(cmd, workdir, log_path, timeout):
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "step_finish",
                                    "part": {"reason": "stop"}}) + "\n")
            return {"status": "completed", "exit_code": 0,
                    "termination_reason": "normal",
                    "cleanup_evidence": {"method": "windows_job_object",
                                         "confirmed": False,
                                         "error": "still active"}}
        monkeypatch.setattr(delegate, "_run_windows_contained", fake)
        _, s = _run_main(monkeypatch, tmp_path,
                         ["--tier", "grunt", "--prompt", "hello"], None)
        # Cleanup unconfirmed -> errored, no fabricated snapshot.
        assert s["status"] == "errored"
        assert s["files_changed"] is None
        assert s["git_head"] is None
        assert s["cleanup"]["confirmed"] is False

    def test_cleanup_failure_retains_timeout(self, monkeypatch, tmp_path):
        def fake(cmd, workdir, log_path, timeout):
            return {"status": "timeout", "exit_code": None,
                    "termination_reason": "timeout",
                    "cleanup_evidence": {"method": "windows_job_object",
                                         "confirmed": False, "error": "x"}}
        monkeypatch.setattr(delegate, "_run_windows_contained", fake)
        _, s = _run_main(monkeypatch, tmp_path,
                         ["--tier", "grunt", "--prompt", "hello"], None)
        assert s["status"] == "timeout"
        assert s["files_changed"] is None

    def test_multiline_prompt_routes_to_task_file(self, monkeypatch, tmp_path):
        seen = {}

        def fake(cmd, workdir, log_path, timeout):
            seen["cmd"] = cmd
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "step_finish",
                                    "part": {"reason": "stop"}}) + "\n")
            return self._completed()
        monkeypatch.setattr(delegate, "_run_windows_contained", fake)
        _run_main(monkeypatch, tmp_path,
                  ["--tier", "grunt", "--dir", str(tmp_path),
                   "--prompt", "line one\nline two"], None)
        # The multiline prompt must be routed through a task file, so the final
        # argv prompt is the single-line "Read the file ..." instruction.
        assert "Read the file" in seen["cmd"][-1]
        # Task file must have been cleaned up.
        assert not list(tmp_path.glob(".delegate-task-*.md"))

    def test_dir_flag_forwarded(self, monkeypatch, tmp_path):
        seen = {}

        def fake(cmd, workdir, log_path, timeout):
            seen["cmd"] = cmd
            seen["workdir"] = workdir
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"type": "step_finish",
                                    "part": {"reason": "stop"}}) + "\n")
            return self._completed()
        monkeypatch.setattr(delegate, "_run_windows_contained", fake)
        _run_main(monkeypatch, tmp_path,
                  ["--tier", "grunt", "--dir", str(tmp_path),
                   "--prompt", "hello"], None)
        assert "--dir" in seen["cmd"]
        assert seen["workdir"] == str(tmp_path.resolve())


# ---------------------------------------------------------------------------
# Real Windows canaries
# ---------------------------------------------------------------------------

@pytest.fixture
def owned_helpers(monkeypatch):
    """Retain helper process-instance handles; verify teardown even on failures."""
    owned = []
    original = subprocess.Popen

    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        if "--_helper" in args[0]:
            owned.append(process)
            assert kwargs["creationflags"] & delegate._CREATE_NO_WINDOW
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    yield owned
    for process in owned:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


@pytest.mark.skipif(not IS_WINDOWS, reason="real Windows Job Object canary")
class TestWindowsCanaries:
    @pytest.mark.parametrize("ending", ["timeout", "normal", "error", "cancelled"])
    def test_owned_writers_stop_and_sentinel_survives(
            self, tmp_path, monkeypatch, owned_helpers, ending):
        # Both descendants acknowledge startup, then attempt a file AND inherited
        # stdout write only when the test signals that the wrapper has returned.
        writer = _write_worker(tmp_path, "writer.py", """
import pathlib, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
role = sys.argv[2]
if role == 'child':
    subprocess.Popen([sys.executable, __file__, str(root), 'grandchild'])
(root / (role + '.ready')).write_text('ready')
deadline = time.monotonic() + 12
while not (root / 'after-return').exists() and time.monotonic() < deadline:
    time.sleep(0.02)
if (root / 'after-return').exists():
    (root / (role + '.late')).write_text('late')
    print(role + ' late inherited output', flush=True)
""")
        worker = _write_worker(tmp_path, "worker.py", """
import pathlib, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
subprocess.Popen([sys.executable, sys.argv[2], str(root), 'child'])
deadline = time.monotonic() + 8
while not (root / 'grandchild.ready').exists() and time.monotonic() < deadline:
    time.sleep(0.02)
if sys.argv[3] == 'normal':
    sys.exit(0)
if sys.argv[3] == 'error':
    sys.exit(7)
while time.monotonic() < deadline:
    time.sleep(0.02)
""")
        sentinel = subprocess.Popen(_python_cmd(writer, str(tmp_path), "sentinel"),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # owned_helpers replaces the constructor only; use the actual process type.
        original_wait = type(sentinel).wait
        cancelled = False
        previous_signal = signal.getsignal(signal.SIGINT)

        def wait(process, timeout=None):
            nonlocal cancelled
            if (ending == "cancelled" and not cancelled
                    and (tmp_path / "grandchild.ready").exists()
                    and process in owned_helpers):
                cancelled = True
                signal.raise_signal(signal.SIGINT)
            return original_wait(process, timeout=timeout)

        monkeypatch.setattr(type(sentinel), "wait", wait)
        log = tmp_path / "transcript.jsonl"
        try:
            result = delegate._run_windows_contained(
                _python_cmd(worker, str(tmp_path), writer, ending),
                str(tmp_path), log, timeout=1.5)
            assert result["termination_reason"] == ending
            assert result["status"] == ({"normal": "completed", "timeout": "timeout"}
                                         .get(ending, "errored"))
            assert result["cleanup_evidence"]["confirmed"] is True
            assert result["cleanup_evidence"]["active_processes"] == 0
            assert all(process.poll() is not None for process in owned_helpers)
            for role in ("child", "grandchild", "sentinel"):
                assert (tmp_path / (role + ".ready")).read_text() == "ready"
            assert sentinel.poll() is None
            before = log.read_bytes()
            (tmp_path / "after-return").touch()
            sentinel.wait(timeout=3)
            time.sleep(0.2)
            assert (tmp_path / "sentinel.late").read_text() == "late"
            assert not (tmp_path / "child.late").exists()
            assert not (tmp_path / "grandchild.late").exists()
            assert log.read_bytes() == before
            assert signal.getsignal(signal.SIGINT) is previous_signal
        finally:
            (tmp_path / "after-return").touch()
            if sentinel.poll() is None:
                sentinel.kill()
            sentinel.wait(timeout=5)

    @pytest.mark.parametrize("failure", ["assignment", "interruption", "exception"])
    def test_assignment_never_releases_uncontained_command(
            self, tmp_path, monkeypatch, owned_helpers, failure):
        marker = tmp_path / "uncontained.txt"
        command = [sys.executable, "-c", f"open({str(marker)!r},'w').write('bad')"]

        def assign(_job, _process):
            if failure == "interruption":
                raise KeyboardInterrupt("during assignment")
            if failure == "exception":
                raise OSError("assignment exception")
            return False

        monkeypatch.setattr(delegate._kernel32, "AssignProcessToJobObject", assign)
        result = delegate._run_windows_contained(command, str(tmp_path),
                                                  tmp_path / "log.jsonl", timeout=2)
        assert result["status"] == "errored"
        assert result["termination_reason"] == ("cancelled" if failure == "interruption" else "error")
        assert result["cleanup_evidence"]["confirmed"] is True
        assert all(process.poll() is not None for process in owned_helpers)
        assert not marker.exists()
        assert result["errors"]

    def test_job_handle_has_one_close_owner(self, tmp_path, monkeypatch):
        closed = []
        original = delegate._close_handle

        def close(handle):
            closed.append(handle)
            original(handle)

        monkeypatch.setattr(delegate, "_close_handle", close)
        result = delegate._run_windows_contained([sys.executable, "-c", "pass"],
                                                  str(tmp_path), tmp_path / "log", 2)
        assert result["cleanup_evidence"]["confirmed"] is True
        assert len(closed) == 1

    def test_query_failure_withholds_snapshot(self, tmp_path, monkeypatch, owned_helpers):
        snapshots = []
        monkeypatch.setattr(delegate, "_git_snapshot", lambda _wd: (
            snapshots.append("snapshot") or {"head": "base", "dirty_files": []}))
        monkeypatch.setattr(delegate, "_job_active_processes", lambda _job: None)
        monkeypatch.setattr(delegate, "_parse_transcript", lambda _path: pytest.fail("unstable transcript parsed"))
        buf = _setup_main(monkeypatch, tmp_path, ["--tier", "grunt", "--dir", str(tmp_path),
                                                  "--prompt", "two\nlines"])
        monkeypatch.setattr(delegate, "_opencode_cmd", lambda _args: [sys.executable, "-c", "pass"])
        with redirect_stdout(buf):
            delegate.main()
        result = json.loads(buf.getvalue())
        assert snapshots == ["snapshot"]  # pre-state only
        assert result["status"] == "errored"
        assert result["cleanup"]["confirmed"] is False
        assert result["files_changed"] is None
        assert result["tool_calls"] is None
        assert list(tmp_path.glob(".delegate-task-*.md"))  # retain pointer on unverified teardown

    def test_worker_launch_failure_has_structured_error(self, tmp_path):
        result = delegate._run_windows_contained([str(tmp_path / "missing.exe")],
                                                  str(tmp_path), tmp_path / "log", 2)
        assert result["status"] == "errored"
        assert result["exit_code"] != 0
        assert result["cleanup_evidence"]["confirmed"] is True
        assert "worker launch failed" in (tmp_path / "log").read_text()


# ---------------------------------------------------------------------------
# Non-Windows branch (mocked on Windows host; real on non-Windows)
# ---------------------------------------------------------------------------

class TestNonWindowsBranch:
    def test_non_windows_uses_subprocess_run(self, monkeypatch, tmp_path):
        """The non-Windows path keeps subprocess.run direct-child semantics."""
        calls = {}

        def fake_run(cmd, cwd=None, stdout=None, stderr=None, timeout=None,
                     text=None, check=None, **kwargs):
            if kwargs.get("capture_output"):
                # _git() call -- return a benign empty result.
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            calls["cmd"] = cmd
            calls["cwd"] = cwd
            calls["timeout"] = timeout
            stdout.write(json.dumps({"type": "step_finish",
                                     "part": {"reason": "stop"}}) + "\n")
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(delegate, "IS_WINDOWS", False)
        monkeypatch.setattr(delegate.subprocess, "run", fake_run)
        buf = _setup_main(monkeypatch, tmp_path,
                          ["--tier", "grunt", "--prompt", "hello"])
        with redirect_stdout(buf):
            delegate.main()
        s = json.loads(buf.getvalue())
        assert s["status"] == "completed"
        assert s["cleanup"]["method"] == "direct_child"
        assert calls["timeout"] == 5


@pytest.mark.parametrize("event, expected", [
    ({"type": "error", "error": {"name": "worker failed"}}, "errored"),
    ({"type": "step_finish", "part": {"reason": "tool-calls"}}, "no_clean_finish"),
])
def test_stream_evidence_status(monkeypatch, tmp_path, event, expected):
    def run(_cmd, _wd, path, _timeout):
        Path(path).write_text(json.dumps(event), encoding="utf-8")
        return TestSummaryLogic()._completed()

    monkeypatch.setattr(delegate, "_run_windows_contained", run)
    _, result = _run_main(monkeypatch, tmp_path,
                          ["--tier", "grunt", "--dir", str(tmp_path), "--prompt", "hello"], None)
    assert result["status"] == expected


def test_same_process_same_second_invocations_are_unique(monkeypatch, tmp_path):
    logs, tasks = [], []
    monkeypatch.setattr(delegate.time, "strftime", lambda _fmt: "fixed-second")

    def run(_cmd, workdir, path, _timeout):
        logs.append(str(path))
        task, = Path(workdir).glob(".delegate-task-*.md")
        tasks.append(task.name)
        assert task.read_text(encoding="utf-8") == "first\nsecond"
        Path(path).write_text('{"type":"step_finish","part":{"reason":"stop"}}', encoding="utf-8")
        return TestSummaryLogic()._completed()

    monkeypatch.setattr(delegate, "_run_windows_contained", run)
    for _ in range(2):
        _run_main(monkeypatch, tmp_path, ["--tier", "grunt", "--dir", str(tmp_path),
                                         "--prompt", "first\nsecond"], None)
    assert len(set(logs)) == len(set(tasks)) == 2
    assert not list(tmp_path.glob(".delegate-task-*.md"))


@pytest.mark.parametrize("failure", ["timeout", "cancelled", "launch"])
def test_direct_child_failure_semantics(monkeypatch, tmp_path, failure):
    def run(cmd, **_kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd, 1)
        if failure == "cancelled":
            raise KeyboardInterrupt
        raise FileNotFoundError("missing command")

    monkeypatch.setattr(delegate.subprocess, "run", run)
    result = delegate._run_direct_child(["fixture"], str(tmp_path), tmp_path / "log", 1)
    assert result["status"] == ("timeout" if failure == "timeout" else "errored")
    assert result["termination_reason"] == ("error" if failure == "launch" else failure)
    assert result["cleanup_evidence"]["confirmed"] is (failure != "cancelled")


@pytest.mark.skipif(IS_WINDOWS, reason="actual non-Windows subprocess runtime gate")
def test_non_windows_actual_runtime(tmp_path):
    result = delegate._run_direct_child(
        [sys.executable, "-c", "print('native direct child')"], str(tmp_path), tmp_path / "log", 5)
    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert (tmp_path / "log").read_text().strip() == "native direct child"


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows cleanup failure canaries")
@pytest.mark.parametrize("failure", ["query", "terminate", "deadline"])
def test_cleanup_failure_is_never_a_false_success(monkeypatch, failure):
    monkeypatch.setattr(delegate, "_get_last_error", lambda: 123)
    monkeypatch.setattr(delegate, "_terminate_job", lambda _job: failure != "terminate")
    monkeypatch.setattr(delegate, "_job_active_processes", lambda _job: None if failure == "query" else 1)
    result = delegate._cleanup_job(42, None, timeout=0.001)
    assert result["confirmed"] is False
    assert result["error"]


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows resource acquisition failures")
@pytest.mark.parametrize("failure", ["job", "log", "helper"])
def test_startup_failure_has_no_uncontained_worker(tmp_path, monkeypatch, owned_helpers, failure):
    if failure == "job":
        monkeypatch.setattr(delegate, "_create_job", lambda: None)
    elif failure == "helper":
        def fail(*_args, **_kwargs):
            raise OSError("helper creation failed")
        monkeypatch.setattr(delegate.subprocess, "Popen", fail)
    log = tmp_path / "missing" / "log" if failure == "log" else tmp_path / "log"
    result = delegate._run_windows_contained([sys.executable, "-c", "pass"], str(tmp_path), log, 1)
    assert result["status"] == "errored"
    assert result["cleanup_evidence"]["confirmed"] is True
    assert not owned_helpers
    assert result["errors"]


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows handle and gate contract")
def test_job_flags_and_real_instance_assignment(tmp_path, monkeypatch, owned_helpers):
    import ctypes
    from ctypes import wintypes

    original = delegate._kernel32.AssignProcessToJobObject
    marker = tmp_path / "released"
    assigned = []

    def assign(job, process):
        assert process == owned_helpers[-1]._handle
        flags = wintypes.DWORD()
        get_flags = delegate._kernel32.GetHandleInformation
        get_flags.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        get_flags.restype = wintypes.BOOL
        assert get_flags(job, ctypes.byref(flags))
        assert flags.value & 1 == 0
        info = delegate._JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        assert delegate._kernel32.QueryInformationJobObject(
            job, 9, ctypes.byref(info), ctypes.sizeof(info), None)
        assert info.BasicLimitInformation.LimitFlags == 0x2000
        time.sleep(0.1)  # helper remains blocked even though it is already running
        assert not marker.exists()
        success = original(job, process)
        assigned.append(bool(success))
        return success

    monkeypatch.setattr(delegate._kernel32, "AssignProcessToJobObject", assign)
    result = delegate._run_windows_contained(
        [sys.executable, "-c", f"open({str(marker)!r},'w').write('released')"],
        str(tmp_path), tmp_path / "log", 2)
    assert assigned == [True]  # actual Popen handle has required Win32 rights
    assert result["cleanup_evidence"]["confirmed"] is True
    assert marker.read_text() == "released"


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows cancellation checkpoints")
@pytest.mark.parametrize("stage", ["assignment", "cleanup"])
def test_recorded_cancellation_is_preserved(tmp_path, monkeypatch, stage):
    if stage == "assignment":
        original = delegate._kernel32.AssignProcessToJobObject

        def assign(job, process):
            result = original(job, process)
            signal.raise_signal(signal.SIGINT)
            return result

        monkeypatch.setattr(delegate._kernel32, "AssignProcessToJobObject", assign)
    else:
        original = delegate._cleanup_job

        def cleanup(job, helper):
            signal.raise_signal(signal.SIGINT)
            return original(job, helper)

        monkeypatch.setattr(delegate, "_cleanup_job", cleanup)
    marker = tmp_path / "started"
    result = delegate._run_windows_contained(
        [sys.executable, "-c", f"open({str(marker)!r},'w').write('started')"],
        str(tmp_path), tmp_path / "log", 2)
    assert result["status"] == "errored"
    assert result["termination_reason"] == "cancelled"
    assert result["cleanup_evidence"]["confirmed"] is True
    assert marker.exists() is (stage == "cleanup")


@pytest.mark.skipif(not IS_WINDOWS, reason="Windows handle-count regression")
def test_repeated_runs_do_not_leak_native_handles(tmp_path):
    import ctypes
    import gc
    from ctypes import wintypes

    get_count = delegate._kernel32.GetProcessHandleCount
    get_count.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    get_count.restype = wintypes.BOOL

    def count():
        gc.collect()
        value = wintypes.DWORD()
        assert get_count(wintypes.HANDLE(-1), ctypes.byref(value))
        return value.value

    before = count()
    for iteration in range(4):
        result = delegate._run_windows_contained([sys.executable, "-c", "pass"],
                                                  str(tmp_path), tmp_path / str(iteration), 2)
        assert result["cleanup_evidence"]["confirmed"] is True
    assert count() <= before


@pytest.mark.skipif(not IS_WINDOWS, reason="concurrent Windows Job isolation")
def test_concurrent_contained_runs(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    def run(value):
        output = tmp_path / str(value)
        result = delegate._run_windows_contained(
            [sys.executable, "-c", f"print({value})"], str(tmp_path), output, 3)
        assert result["cleanup_evidence"]["confirmed"] is True
        return output.read_text().strip()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(run, [101, 202])) == ["101", "202"]

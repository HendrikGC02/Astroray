"""Atomic file locks for the tick guard and the shared GPU slot.

Lock files retain the historic ``pid``, ``ts`` and ``meta`` fields. New locks
also record an unguessable owner token and the holder process's start time, so
PID reuse cannot make a different process appear to own a live lock.
"""
import ctypes
from ctypes import wintypes
import json
import os
import time
import uuid
from datetime import datetime, timezone


_CLAIM_SUFFIX = ".claim"
_owned_tokens = {}


def _pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _process_start_time(pid):
    """Return a PID's creation identity, or None when it cannot be read."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            created = wintypes.FILETIME()
            ignored = wintypes.FILETIME()
            if not ctypes.windll.kernel32.GetProcessTimes(
                    handle, ctypes.byref(created), ctypes.byref(ignored),
                    ctypes.byref(ignored), ctypes.byref(ignored)):
                return None
            return (created.dwHighDateTime << 32) | created.dwLowDateTime
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        # Linux field 22 is starttime in ticks since boot; production users run
        # on Windows, but this keeps the focused tests portable.
        return open("/proc/{}/stat".format(pid), encoding="utf-8").read().split()[21]
    except (OSError, IndexError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return None


def _owner_alive(data) -> bool:
    if not isinstance(data, dict) or not _pid_alive(data.get("pid")):
        return False
    recorded_start = data.get("process_start")
    if recorded_start is None:  # legacy lock: preserve its pid-only behaviour.
        return True
    actual_start = _process_start_time(data.get("pid"))
    return actual_start is not None and str(actual_start) == str(recorded_start)


def _identity(data):
    if not isinstance(data, dict):
        return None
    return data.get("owner_token") or (data.get("pid"), data.get("ts"))


def _write_exclusive(path, payload) -> bool:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f)
        f.flush()
        os.fsync(f.fileno())
    return True


def _claim_payload(token):
    return {"pid": os.getpid(), "process_start": _process_start_time(os.getpid()),
            "owner_token": token}


def _claim_lock(path):
    """Atomically acquire the short-lived transition claim for *path*."""
    claim = path + _CLAIM_SUFFIX
    token = uuid.uuid4().hex
    payload = _claim_payload(token)
    while True:
        if _write_exclusive(claim, payload):
            return claim, token
        existing = _load(claim)
        if _owner_alive(existing):
            time.sleep(0.01)
            continue
        # rename (not replace) claims only the stale file. A contender that wins
        # the resulting create race makes our next claim attempt fail harmlessly.
        retired = claim + ".stale." + uuid.uuid4().hex
        try:
            os.rename(claim, retired)
        except (FileNotFoundError, FileExistsError, OSError):
            continue
        if _identity(_load(retired)) == _identity(existing):
            try:
                os.remove(retired)
            except OSError:
                pass


def _release_claim(claim, token):
    data = _load(claim)
    if isinstance(data, dict) and data.get("owner_token") == token:
        try:
            os.remove(claim)
        except FileNotFoundError:
            pass


def lock_status(path: str, stale_seconds: int = None) -> dict:
    """Report the state; elapsed time never expires a live holder.

    ``stale_seconds`` remains accepted for compatibility but is intentionally
    ignored: process identity rather than a wall-clock estimate decides stale.
    """
    del stale_seconds
    if not os.path.exists(path):
        return {"held": False, "stale": False, "meta": None}
    data = _load(path)
    if data is None:
        return {"held": True, "stale": True, "meta": None}
    return {"held": True, "stale": not _owner_alive(data), "meta": data.get("meta"),
            "pid": data.get("pid")}


def acquire_lock(path: str, stale_seconds: int = None, meta: dict = None) -> bool:
    """Acquire *path*, atomically recovering only a dead or corrupt holder."""
    del stale_seconds
    owner_token = uuid.uuid4().hex
    payload = {"pid": os.getpid(),
               "process_start": _process_start_time(os.getpid()),
               "owner_token": owner_token,
               "ts": _now().strftime("%Y-%m-%dT%H:%M:%SZ"),
               "meta": meta or {}}
    while True:
        claim, claim_token = _claim_lock(path)
        try:
            claim_data = _load(claim)
            if not isinstance(claim_data, dict) or claim_data.get("owner_token") != claim_token:
                continue
            existing = _load(path) if os.path.exists(path) else None
            if existing is not None and _owner_alive(existing):
                return False
            if os.path.exists(path):
                # The claim serializes ordinary acquire/release operations. The
                # identity re-check protects against an external replacement.
                before = _identity(existing)
                retired = path + ".stale." + uuid.uuid4().hex
                try:
                    os.rename(path, retired)
                except (FileNotFoundError, FileExistsError, OSError):
                    continue
                if _identity(_load(retired)) != before:
                    try:
                        os.remove(retired)
                    except OSError:
                        pass
                    continue
                try:
                    os.remove(retired)
                except OSError:
                    pass
            if _write_exclusive(path, payload):
                _owned_tokens[os.path.abspath(path)] = owner_token
                return True
        finally:
            _release_claim(claim, claim_token)


def release_lock(path: str, force: bool = False, owner_token: str = None) -> None:
    """Release only this caller's token; force may clear a dead/corrupt lock."""
    token = owner_token or _owned_tokens.get(os.path.abspath(path))
    while True:
        claim, claim_token = _claim_lock(path)
        try:
            claim_data = _load(claim)
            if not isinstance(claim_data, dict) or claim_data.get("owner_token") != claim_token:
                continue
            data = _load(path) if os.path.exists(path) else None
            if data is None:
                return
            if data.get("owner_token") == token or (force and not _owner_alive(data)):
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
            return
        finally:
            _release_claim(claim, claim_token)

"""File-based locks: tick-overlap guard and single-GPU-slot guard.

2026-09-13 (lead): a holder is also considered stale when its recorded pid is no
longer alive, and release_lock() only removes a lock this process owns (pass
force=True to break someone else's) — two lanes built CUDA concurrently after an
unowned release deleted the live holder's file.
"""
import json, os
from datetime import datetime, timezone


def _pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True  # unknown: assume alive, fall back to the ts rule
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        SYNCHRONIZE = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def lock_status(path: str, stale_seconds: int) -> dict:
    if not os.path.exists(path):
        return {"held": False, "stale": False, "meta": None}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        age = (_now() - _parse_ts(data["ts"])).total_seconds()
    except (ValueError, KeyError, OSError):
        return {"held": True, "stale": True, "meta": None}
    stale = age >= stale_seconds or not _pid_alive(data.get("pid"))
    return {"held": True, "stale": stale, "meta": data.get("meta"), "pid": data.get("pid")}


def acquire_lock(path: str, stale_seconds: int, meta: dict = None) -> bool:
    st = lock_status(path, stale_seconds)
    if st["held"] and not st["stale"]:
        return False
    payload = {"pid": os.getpid(),
               "ts": _now().strftime("%Y-%m-%dT%H:%M:%SZ"),
               "meta": meta or {}}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)
    return True


def release_lock(path: str, force: bool = False) -> None:
    if not os.path.exists(path):
        return
    if not force:
        try:
            with open(path, "r", encoding="utf-8") as f:
                owner = json.load(f).get("pid")
        except (ValueError, OSError):
            owner = None
        if owner is not None and int(owner) != os.getpid():
            return  # not ours — never delete another holder's lock
    os.remove(path)

"""File-based locks: tick-overlap guard and single-GPU-slot guard."""
import json, os
from datetime import datetime, timezone


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
    return {"held": True, "stale": age >= stale_seconds, "meta": data.get("meta")}


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


def release_lock(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)

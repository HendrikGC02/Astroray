"""Persisted debounce + SHA-bound hardware-result ledger."""
import json, os
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_ledger(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_ledger(path: str, ledger: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _entry(ledger: dict, number: int) -> dict:
    return ledger.setdefault(str(number), {})


def record_hw_result(ledger, number, head_sha, result, numbers, artifact):
    e = _entry(ledger, number)
    e.update(head_sha=head_sha, hw_result=result, hw_numbers=numbers,
             hw_artifact=artifact, last_action="hw_recorded", last_action_ts=_now())


def record_action(ledger, number, action):
    e = _entry(ledger, number)
    e.update(last_action=action, last_action_ts=_now())


def expire_closed(ledger: dict, open_numbers: set) -> None:
    for k in [k for k in ledger if int(k) not in open_numbers]:
        del ledger[k]

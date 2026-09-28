import json
import os
import sys
import threading
import uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator import locks
from roadmap_orchestrator.locks import acquire_lock, release_lock, lock_status

def test_acquire_when_free(tmp_path):
    p = str(tmp_path / "t.lock")
    assert acquire_lock(p, stale_seconds=1500, meta={"sha": "x"}) is True
    assert os.path.exists(p)

def test_acquire_blocked_when_fresh(tmp_path):
    p = str(tmp_path / "t.lock")
    acquire_lock(p, stale_seconds=1500)
    assert acquire_lock(p, stale_seconds=1500) is False  # held & fresh

def test_old_live_holder_never_expires_by_age(tmp_path):
    p = str(tmp_path / "t.lock")
    with open(p, "w") as f:
        json.dump({"pid": os.getpid(), "process_start": locks._process_start_time(os.getpid()),
                   "ts": "2000-01-01T00:00:00Z"}, f)
    assert lock_status(p, stale_seconds=1)["stale"] is False


def test_acquire_reclaims_dead_holder(tmp_path):
    p = str(tmp_path / "t.lock")
    with open(p, "w") as f:
        json.dump({"pid": 99999999, "process_start": "gone", "ts": "2000-01-01T00:00:00Z"}, f)
    assert acquire_lock(p, stale_seconds=10) is True

def test_release_removes(tmp_path):
    p = str(tmp_path / "t.lock")
    acquire_lock(p, stale_seconds=1500)
    release_lock(p)
    assert not os.path.exists(p)

def test_lock_status_reports_held_and_meta(tmp_path):
    p = str(tmp_path / "t.lock")
    acquire_lock(p, stale_seconds=1500, meta={"sha": "abc"})
    st = lock_status(p, stale_seconds=1500)
    assert st["held"] is True and st["stale"] is False and st["meta"]["sha"] == "abc"

def test_acquire_reclaims_corrupt_lock(tmp_path):
    p = str(tmp_path / "t.lock")
    (tmp_path / "t.lock").write_text("not-json{{{", encoding="utf-8")
    assert acquire_lock(p, stale_seconds=10) is True
    assert os.path.exists(p)


def test_old_owner_cannot_release_replacement(tmp_path):
    p = str(tmp_path / "t.lock")
    assert acquire_lock(p, stale_seconds=10)
    old_token = json.loads((tmp_path / "t.lock").read_text(encoding="utf-8"))["owner_token"]
    replacement = {"pid": os.getpid(), "process_start": locks._process_start_time(os.getpid()),
                   "owner_token": uuid.uuid4().hex, "ts": "2000-01-01T00:00:00Z", "meta": {}}
    (tmp_path / "t.lock").write_text(json.dumps(replacement), encoding="utf-8")
    release_lock(p, owner_token=old_token)
    assert json.loads((tmp_path / "t.lock").read_text(encoding="utf-8"))["owner_token"] == replacement["owner_token"]


def test_simultaneous_contenders_have_one_owner(tmp_path):
    p = str(tmp_path / "t.lock")
    gate = threading.Barrier(8)
    outcomes = []

    def contender():
        gate.wait()
        outcomes.append(acquire_lock(p, stale_seconds=1))

    threads = [threading.Thread(target=contender) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count(True) == 1

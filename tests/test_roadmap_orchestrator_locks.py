import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.locks import acquire_lock, release_lock, lock_status

def test_acquire_when_free(tmp_path):
    p = str(tmp_path / "t.lock")
    assert acquire_lock(p, stale_seconds=1500, meta={"sha": "x"}) is True
    assert os.path.exists(p)

def test_acquire_blocked_when_fresh(tmp_path):
    p = str(tmp_path / "t.lock")
    acquire_lock(p, stale_seconds=1500)
    assert acquire_lock(p, stale_seconds=1500) is False  # held & fresh

def test_acquire_reclaims_when_stale(tmp_path):
    p = str(tmp_path / "t.lock")
    with open(p, "w") as f:
        json.dump({"pid": 1, "ts": "2000-01-01T00:00:00Z"}, f)
    assert acquire_lock(p, stale_seconds=10) is True  # old ts -> reclaim

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

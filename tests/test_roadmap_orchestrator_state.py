import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.state import (
    load_ledger, save_ledger, record_hw_result, record_action, expire_closed)

def test_load_missing_returns_empty(tmp_path):
    assert load_ledger(str(tmp_path / "nope.json")) == {}

def test_save_then_load_roundtrip(tmp_path):
    p = str(tmp_path / "led.json")
    save_ledger(p, {"1": {"head_sha": "a"}})
    assert load_ledger(p) == {"1": {"head_sha": "a"}}

def test_record_hw_result_binds_sha():
    led = {}
    record_hw_result(led, 5, "sha5", "PASS", "SSIM 0.98", "out.png")
    assert led["5"]["head_sha"] == "sha5"
    assert led["5"]["hw_result"] == "PASS"
    assert led["5"]["hw_numbers"] == "SSIM 0.98"

def test_record_action_sets_timestamp():
    led = {}
    record_action(led, 5, "rebase_dispatched")
    assert led["5"]["last_action"] == "rebase_dispatched"
    assert led["5"]["last_action_ts"].endswith("Z")

def test_expire_closed_drops_absent_prs():
    led = {"1": {}, "2": {}, "3": {}}
    expire_closed(led, open_numbers={2})
    assert set(led.keys()) == {"2"}

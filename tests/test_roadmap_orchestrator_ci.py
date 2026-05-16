import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.ci import ci_state

def _cr(concl): return {"__typename": "CheckRun", "status": "COMPLETED", "conclusion": concl}
def _sc(state): return {"__typename": "StatusContext", "state": state}

def test_all_success_is_pass():
    assert ci_state({"statusCheckRollup": [_cr("SUCCESS"), _sc("SUCCESS")]}) == "pass"

def test_any_failure_is_fail():
    assert ci_state({"statusCheckRollup": [_cr("SUCCESS"), _cr("FAILURE")]}) == "fail"

def test_pending_when_non_terminal():
    assert ci_state({"statusCheckRollup": [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]}) == "pending"

def test_empty_rollup_is_pending():
    assert ci_state({"statusCheckRollup": []}) == "pending"

def test_skipped_and_neutral_count_as_success():
    assert ci_state({"statusCheckRollup": [_cr("SKIPPED"), _cr("NEUTRAL")]}) == "pass"

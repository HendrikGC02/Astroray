import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.classify import classify_prs

OK = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]
FAILED = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]
PENDING = [{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": None}]

def _pr(n, **kw):
    base = {"number": n, "headRefOid": f"sha{n}", "isDraft": False,
            "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
            "statusCheckRollup": OK, "createdAt": "2026-05-15T00:00:00Z"}
    base.update(kw); return base

def test_draft_is_in_progress():
    b = classify_prs([_pr(1, isDraft=True)], {})
    assert b["in_progress"] == [1]

def test_conflicting_is_rebase_needed():
    b = classify_prs([_pr(2, mergeable="CONFLICTING")], {})
    assert b["rebase_needed"] == [2]

def test_behind_is_rebase_needed():
    b = classify_prs([_pr(3, mergeStateStatus="BEHIND")], {})
    assert b["rebase_needed"] == [3]

def test_ci_failure_is_ci_failing():
    b = classify_prs([_pr(4, statusCheckRollup=FAILED)], {})
    assert b["ci_failing"] == [4]

def test_hw_fail_for_current_sha_is_hw_failed():
    led = {"5": {"head_sha": "sha5", "hw_result": "FAIL"}}
    b = classify_prs([_pr(5)], led)
    assert b["hw_failed"] == [5]

def test_ready_requires_ci_pass_and_hw_pass():
    led = {"6": {"head_sha": "sha6", "hw_result": "PASS"}}
    b = classify_prs([_pr(6)], led)
    assert b["ready"] == [6]

def test_hw_untested_when_no_result_even_if_ci_pending():
    b = classify_prs([_pr(7, statusCheckRollup=PENDING)], {})
    assert b["hw_untested"] == [7]

def test_stale_hw_result_for_old_sha_is_requeued():
    led = {"8": {"head_sha": "OLDsha", "hw_result": "PASS"}}
    b = classify_prs([_pr(8)], led)  # current sha is sha8 != OLDsha
    assert b["hw_untested"] == [8]
    assert b["ready"] == []

def test_every_pr_in_exactly_one_bucket():
    prs = [_pr(1, isDraft=True), _pr(2, mergeable="CONFLICTING"),
           _pr(4, statusCheckRollup=FAILED), _pr(7, statusCheckRollup=PENDING)]
    b = classify_prs(prs, {})
    flat = [n for v in b.values() for n in v]
    assert sorted(flat) == [1, 2, 4, 7]
    assert len(flat) == len(set(flat))

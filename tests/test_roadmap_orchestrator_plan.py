import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from roadmap_orchestrator.plan import build_tick_plan

OK = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "SUCCESS"}]
FAILED = [{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]

def _pr(n, **kw):
    b = {"number": n, "title": f"pkg9{n}", "headRefName": "b", "headRefOid": f"s{n}",
         "isDraft": False, "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
         "statusCheckRollup": OK, "createdAt": "2026-01-0%dT00:00:00Z" % n}
    b.update(kw); return b

def test_dispatch_respects_cap_minus_inflight():
    p = build_tick_plan([], {}, ["pkg94","pkg95","pkg96"],
                         eligible_packages=["pkg94","pkg95","pkg96"],
                         in_flight_count=1, impl_cap=2, fixer_cap=1,
                         gpu_lock_free=True, fixer_debounce_secs=3600,
                         now_iso="2026-05-16T00:00:00Z")
    assert p["dispatch"] == ["pkg94"]            # only 1 free slot

def test_ready_pr_is_merged():
    led = {"1": {"head_sha": "s1", "hw_result": "PASS"}}
    p = build_tick_plan([_pr(1)], led, [], [], 0, 2, 1, True, 3600, "2026-05-16T00:00:00Z")
    assert p["merges"] == [1]

def test_hw_dispatch_only_when_gpu_free():
    p_busy = build_tick_plan([_pr(2)], {}, ["pkg92"], [], 0, 2, 1,
                             gpu_lock_free=False, fixer_debounce_secs=3600,
                             now_iso="2026-05-16T00:00:00Z")
    assert p_busy["hw_dispatch"] is None
    p_free = build_tick_plan([_pr(2)], {}, ["pkg92"], [], 0, 2, 1,
                             gpu_lock_free=True, fixer_debounce_secs=3600,
                             now_iso="2026-05-16T00:00:00Z")
    assert p_free["hw_dispatch"] == 2

def test_fixer_debounced_within_window():
    led = {"3": {"last_action": "rebase_dispatched", "last_action_ts": "2026-05-16T00:00:30Z"}}
    p = build_tick_plan([_pr(3, mergeable="CONFLICTING")], led, [], [], 0, 2, 1,
                        True, fixer_debounce_secs=3600, now_iso="2026-05-16T00:01:00Z")
    assert p["fixers"] == []          # 30s < 3600s debounce

def test_ci_failing_becomes_ci_fixer():
    p = build_tick_plan([_pr(4, statusCheckRollup=FAILED)], {}, [], [], 0, 2, 1,
                        True, 3600, "2026-05-16T00:00:00Z")
    assert p["fixers"] == [{"pr": 4, "kind": "ci"}]

def test_hw_failed_debounced_after_gate_review_dispatched():
    led = {"5": {"head_sha": "s5", "hw_result": "FAIL",
                 "last_action": "gate_review_dispatched",
                 "last_action_ts": "2026-05-16T00:00:30Z"}}
    p = build_tick_plan([_pr(5)], led, [], [], 0, 2, 1,
                        True, 3600, "2026-05-16T00:01:00Z")
    assert 5 not in p["hw_failed"]  # 30s < 3600s debounce window

def test_hw_dispatch_skipped_for_blocked_buildenv():
    led = {"6": {"last_action": "hw_blocked_buildenv",
                 "last_action_ts": "2026-05-20T00:00:00Z"}}
    # now_iso is 1 hour later — still within 24h window
    p = build_tick_plan([_pr(6)], led, ["pkg64-gpu"], [], 0, 2, 1,
                        True, 3600, "2026-05-20T01:00:00Z")
    assert p["hw_dispatch"] is None  # blocked buildenv debounces HW dispatch

def test_hw_dispatch_resumes_after_blocked_buildenv_expires():
    led = {"7": {"last_action": "hw_blocked_buildenv",
                 "last_action_ts": "2026-05-19T00:00:00Z"}}
    # now_iso is 25 hours later — beyond 24h window
    p = build_tick_plan([_pr(7)], led, ["pkg64-gpu"], [], 0, 2, 1,
                        True, 3600, "2026-05-20T01:00:00Z")
    assert p["hw_dispatch"] == 7  # debounce expired, retry
